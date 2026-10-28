"""Testes dos dois modos de busca (manual e automático) e do servidor local."""

import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from buscastartups import servidor
from buscastartups.servico import BuscaEmAndamento, Servico
from buscastartups.servidor import validar_busca

FIX = Path(__file__).parent / "fixtures"


class Resposta:
    def __init__(self, conteudo: bytes):
        self.content = conteudo
        self.text = conteudo.decode("utf-8")


def preparar() -> tuple[dict, Path]:
    base = Path(tempfile.mkdtemp())
    cache = base / "dados" / "cache"
    (cache / "cnpj").mkdir(parents=True)
    shutil.copy(FIX / "municipios.csv", cache / "municipios.csv")
    shutil.copy(FIX / "cnpj_12345678000190.json", cache / "cnpj" / "12345678000190.json")
    config = {
        "projeto": {"nome": "Teste"},
        "coleta": {"termos": ["startup"]},
        "privacidade": {"sal": "s"},
        "fontes": [{"tipo": "rss", "nome": "feed", "urls": ["https://exemplo.br/rss"]},
                   {"tipo": "mastodon", "nome": "masto", "hashtags": ["startup"], "habilitada": False}],
        "automatico": {"intervalo_horas": 24, "janela_inicial_dias": 30, "sobreposicao_dias": 1},
        "geo": {"ufs_foco": ["MT"]},
    }
    return config, base


def feed_simulado():
    return mock.patch("buscastartups.http.ClienteHTTP.get", return_value=Resposta((FIX / "feed.xml").read_bytes()))


class TestServico(unittest.TestCase):
    def test_periodo_automatico(self):
        config, base = preparar()
        s = Servico(config, base)
        hoje = date(2026, 10, 28)
        p = s.periodo_automatico(hoje)
        self.assertEqual((p.inicio, p.fim), (date(2026, 9, 28), hoje))  # primeira vez: janela inicial
        s._salvar_estado({"ultima_automatica": "2026-10-20T08:00:00+00:00", "historico": []})
        self.assertEqual(s.periodo_automatico(hoje).inicio, date(2026, 10, 19))  # desde a última, com sobreposição
        self.assertEqual(s.proxima_automatica(), datetime(2026, 10, 21, 8, tzinfo=timezone.utc))

    def test_busca_manual_e_automatica_registram_historico(self):
        config, base = preparar()
        s = Servico(config, base)
        with feed_simulado(), mock.patch("buscastartups.servico.date") as d:
            d.today.return_value = date(2026, 10, 28)
            r = s.buscar_automatico()
        self.assertEqual(r["status"], "concluida")
        self.assertEqual(r["startups"], 1)  # AgroSense (a Lumen Edu vai para revisão)
        self.assertEqual(r["revisao"], 1)
        self.assertEqual(r["falhas"], 0)
        estado = s.estado()
        self.assertTrue(estado["ultima_automatica"])
        with feed_simulado():
            from buscastartups.modelo import Periodo
            m = s.buscar("manual", termos=["educação", "startup"], periodo=Periodo(date(2026, 10, 26), date(2026, 10, 26)))
        self.assertEqual(m["status"], "concluida")
        self.assertEqual(m["mencoes_captadas"], 1)  # só a notícia de 26/10
        historico = s.estado()["historico"]
        self.assertEqual([h["tipo"] for h in historico], ["manual", "automatica"])
        self.assertEqual(s.estado()["ultima_automatica"], estado["ultima_automatica"])  # manual não mexe na agenda
        startups = json.loads((base / "dados" / "abertos" / "startups.json").read_text())
        self.assertIn("startup", {t for s_ in startups for t in s_["termos"].split(" | ")})

    def test_uma_busca_por_vez(self):
        config, base = preparar()
        s = Servico(config, base)
        s._trava.acquire()
        with self.assertRaises(BuscaEmAndamento):
            s.buscar("manual", termos=["x"])
        with self.assertRaises(BuscaEmAndamento):
            s.buscar_em_segundo_plano(tipo="manual", termos=["x"])
        s._trava.release()

    def test_erro_fica_registrado(self):
        config, base = preparar()
        s = Servico(config, base)
        with mock.patch("buscastartups.servico.captar", side_effect=RuntimeError("sem rede")):
            r = s.buscar("manual", termos=["x"])
        self.assertEqual((r["status"], r["erro"]), ("erro", "sem rede"))
        self.assertEqual(r["falhas"], 1)
        self.assertFalse(s.ocupado())

    def test_termos_manuais_substituem_hashtags(self):
        config, base = preparar()
        config["fontes"][1]["habilitada"] = True
        chamadas = []
        with mock.patch("buscastartups.fontes.mastodon.FonteMastodon.coletar",
                        lambda self: chamadas.append((self.config.get("hashtags"), self.termos)) or iter([])), feed_simulado():
            from buscastartups.captacao import captar
            captar(config, base, termos=["agtech"], so_fontes=["masto"])
        self.assertEqual(chamadas, [(None, ["agtech"])])


class TestValidacao(unittest.TestCase):
    def test_validar_busca(self):
        config, _ = preparar()
        p = validar_busca({"termos": " agtech , fintech ,", "de": "2026-01-01", "ate": "2026-02-01",
                           "fontes": ["feed", "inexistente"], "metodo": "llm"}, config)
        self.assertEqual(p["termos"], ["agtech", "fintech"])
        self.assertEqual(p["fontes"], ["feed"])
        self.assertEqual(p["metodo"], "llm")
        for corpo, msg in [({"termos": []}, "palavra-chave"), ({"termos": ["x"], "de": "2026-13-01"}, "Datas"),
                           ({"termos": ["x"], "de": "2026-02-01", "ate": "2026-01-01"}, "posterior"),
                           ({"termos": ["x"], "de": (date.today() + timedelta(days=2)).isoformat()}, "futuro")]:
            with self.assertRaisesRegex(ValueError, msg):
                validar_busca(corpo, config)


class TestServidor(unittest.TestCase):
    def setUp(self):
        config, self.base = preparar()
        (self.base / "dashboard").mkdir()
        (self.base / "dashboard" / "index.html").write_text("<p>painel</p>")
        self.servico = Servico(config, self.base)
        classe = type("M", (servidor.Manipulador,), {"servico": self.servico})
        import functools
        import http.server
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                                   functools.partial(classe, directory=str(self.base)))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def pedir(self, caminho, corpo=None, cabecalhos=None):
        dados = None if corpo is None else json.dumps(corpo).encode()
        req = urllib.request.Request(self.url + caminho, data=dados, headers={
            "Content-Type": "application/json", **(cabecalhos or {})})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read() or b"null") if "json" in resp.headers["Content-Type"] else resp.read()
        except urllib.error.HTTPError as erro:
            return erro.code, json.loads(erro.read())

    def test_fluxo_busca_manual(self):
        status, conf = self.pedir("/api/config")
        self.assertEqual((status, conf["termos"]), (200, ["startup"]))
        self.assertEqual([f["nome"] for f in conf["fontes"]], ["feed", "masto"])
        self.assertEqual(self.pedir("/dashboard/")[0], 200)

        with feed_simulado():
            status, _ = self.pedir("/api/buscar", {"termos": "startup", "de": "2026-10-01", "ate": "2026-10-28",
                                                   "fontes": ["feed"]})
            self.assertEqual(status, 202)
            for _ in range(100):
                st = self.pedir("/api/status")[1]
                if not st["ocupado"] and st["atual"]:
                    break
                time.sleep(0.05)
        self.assertEqual(st["atual"]["status"], "concluida")
        self.assertEqual(st["atual"]["termos"], ["startup"])
        self.assertTrue(st["log"])
        self.assertEqual(st["historico"][0]["tipo"], "manual")

    def test_erros_e_protecao(self):
        self.assertEqual(self.pedir("/api/buscar", {"termos": []})[0], 400)
        self.assertEqual(self.pedir("/api/buscar", {"termos": ["x"]}, {"Origin": "https://site-malicioso.com"})[0], 403)
        self.servico._trava.acquire()
        self.assertEqual(self.pedir("/api/buscar", {"termos": ["x"]})[0], 409)
        self.servico._trava.release()
        self.assertEqual(self.pedir("/api/nada", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
