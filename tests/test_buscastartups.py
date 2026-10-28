import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from buscastartups.captacao import captar
from buscastartups.classificacao import classificar
from buscastartups.classificacao.llm import ClassificadorLLM
from buscastartups.classificacao.regras import ClassificadorRegras, NOMES_IGNORADOS, extrair_nomes, extrair_responsavel
from buscastartups.fontes import TIPOS, Contexto
from buscastartups.fontes.google_news import FonteGoogleNews
from buscastartups.fontes.rss import ler_feed
from buscastartups.fontes.web import extrair
from buscastartups.geo import Geocodificador, carregar_municipios
from buscastartups.modelo import Periodo, anonimizar_texto, pseudonimizar

FIX = Path(__file__).parent / "fixtures"


class Resposta:
    def __init__(self, conteudo: bytes):
        self.content = conteudo
        self.text = conteudo.decode("utf-8")

    def json(self):
        return json.loads(self.content)


def geocodificador(ufs=("MT",)):
    pasta = Path(tempfile.mkdtemp())
    shutil.copy(FIX / "municipios.csv", pasta / "municipios.csv")
    return Geocodificador(carregar_municipios(pasta), list(ufs))


class TestModelo(unittest.TestCase):
    def test_pseudonimizacao(self):
        self.assertEqual(pseudonimizar("joao", "s"), pseudonimizar("joao", "s"))
        self.assertNotEqual(pseudonimizar("joao", "s"), pseudonimizar("joao", "t"))
        self.assertEqual(pseudonimizar("", "s"), "")

    def test_anonimizar_preserva_cnpj(self):
        t = anonimizar_texto("Fale com @maria ou maria@ex.com.br, tel (65) 99999-1234. CNPJ 12.345.678/0001-90")
        self.assertNotIn("maria", t)
        self.assertIn("[email]", t)
        self.assertIn("[telefone]", t)
        self.assertIn("12.345.678/0001-90", t)

    def test_periodo(self):
        p = Periodo.de_texto("2026-01-01", "2026-06-30")
        self.assertTrue(p.contem("2026-03-01T00:00:00+00:00"))
        self.assertFalse(p.contem("2025-12-31T23:00:00+00:00"))
        self.assertTrue(p.contem(""))  # sem data: mantém
        self.assertTrue(p.anterior_ao_inicio("2025-12-31T00:00:00+00:00"))


class TestCaptacao(unittest.TestCase):
    def test_feeds(self):
        self.assertEqual(len(ler_feed((FIX / "feed.xml").read_bytes())), 4)
        atom = ler_feed(b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>a</id><link href="https://ex/a"/>
            <title>T</title><published>2026-01-02T03:04:05Z</published></entry></feed>""")[0]
        self.assertEqual(atom["data"], "2026-01-02T03:04:05+00:00")

    def test_google_news_periodo_na_consulta(self):
        ctx = Contexto(mock.Mock(), "s", periodo=Periodo(date(2026, 1, 1), date(2026, 3, 31)))
        fonte = FonteGoogleNews({"complemento": '"Mato Grosso"'}, ctx)
        self.assertEqual(fonte.consulta("venture capital"),
                         '"venture capital" "Mato Grosso" after:2025-12-31 before:2026-04-01')

    def test_gdelt(self):
        cliente = mock.Mock()
        cliente.get.return_value = Resposta(json.dumps({"articles": [
            {"url": "https://n.br/1", "title": "Startup X", "seendate": "20260310T120000Z", "language": "Portuguese"}]}).encode())
        ctx = Contexto(cliente, "s", termos=["startup"], periodo=Periodo(date(2026, 3, 1), None))
        m = list(TIPOS["gdelt"]({}, ctx).coletar())[0]
        self.assertEqual(m.data_publicacao, "2026-03-10T12:00:00+00:00")
        self.assertEqual(cliente.get.call_args.kwargs["params"]["startdatetime"], "20260301000000")

    def test_mastodon_reblog_e_periodo(self):
        cliente = mock.Mock()
        cliente.get.return_value = Resposta((FIX / "mastodon.json").read_bytes())
        ctx = Contexto(cliente, "s", periodo=Periodo(date(2026, 1, 1), None))
        regs = list(TIPOS["mastodon"]({"hashtags": ["startup"]}, ctx).coletar())
        self.assertEqual([r.id_original for r in regs], ["111"])  # sem reblog e sem o antigo
        self.assertEqual(cliente.get.call_count, 1)  # parou ao passar do início do período
        self.assertEqual(regs[0].autor_hash, pseudonimizar("joao", "s"))

    def test_base_aberta(self):
        conf = {"caminho": str(FIX / "base_aberta.csv"), "separador": ";",
                "colunas": {"nome": "Nome da empresa", "cnpj": "CNPJ", "municipio": "Município", "uf": "UF",
                            "setor": "Área", "descricao": "Descrição"}}
        regs = list(TIPOS["base_aberta"](conf, Contexto(mock.Mock(), "s")).coletar())
        self.assertEqual(len(regs), 1)
        self.assertEqual((regs[0].entidade, regs[0].municipio, regs[0].setor_declarado), ("Cerrado Data", "Várzea Grande", "govtech"))

    def test_web(self):
        html = """<article><h2>Startup e SUS</h2><p>Texto</p><time datetime="2026-05-01T10:00:00Z">1 mai</time>
                  <a href="/n/1">leia</a></article>"""
        item = extrair(html, "https://site.br/x", {"item": "article", "titulo": "h2", "texto": "p", "data": "time", "link": "a"})[0]
        self.assertEqual((item["url"], item["data"]), ("https://site.br/n/1", "2026-05-01T10:00:00+00:00"))


class TestRegras(unittest.TestCase):
    def test_extracao(self):
        t = "A AgroSense, startup cuiabana de agtech, recebeu aporte. Segundo Ana Souza, CEO da empresa, vai crescer."
        self.assertEqual(extrair_nomes(t, NOMES_IGNORADOS), ["AgroSense"])
        self.assertEqual(extrair_responsavel(t), "Ana Souza (CEO)")
        self.assertEqual(extrair_nomes("A startup mato-grossense TerraViva Tech criou", NOMES_IGNORADOS), ["TerraViva Tech"])
        self.assertEqual(extrair_responsavel("o fundador João Pedro Almeida disse"), "João Pedro Almeida (fundador)")

    def test_empresa_consolidada_anula_incerteza(self):
        notas, evid, consolidada = ClassificadorRegras().avaliar("Multinacional fundada em 1950 cria aceleradora de startups")
        self.assertTrue(consolidada)
        self.assertEqual(notas["incerteza"], 0.0)

    def test_termo_curto_exige_palavra_inteira(self):
        notas, _, _ = ClassificadorRegras().avaliar("Ele pagou a diária")  # "ia" não casa dentro de "diária"
        self.assertEqual(notas["inovacao"], 0.0)


class TestGeo(unittest.TestCase):
    def test_localizar(self):
        g = geocodificador()
        self.assertEqual(g.localizar("empresa de Sinop (MT) cresce"), ("Sinop", "MT"))
        self.assertEqual(g.localizar("A startup cuiabana"), ("Cuiabá", "MT"))
        self.assertEqual(g.localizar("sediada em Várzea Grande"), ("Várzea Grande", "MT"))  # UF de foco
        self.assertEqual(g.localizar("atua em Campinas"), ("", ""))  # fora do foco e sem UF: não arrisca
        self.assertEqual(g.localizar("startup sul-mato-grossense"), ("", "MS"))
        self.assertEqual(g.localizar("solução para todos"), ("", ""))  # "para" não é o estado do Pará
        self.assertEqual(g.coordenadas("CUIABA", "MT")["nome"], "Cuiabá")


class TestPontaAPonta(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        cache = self.base / "dados" / "cache"
        (cache / "cnpj").mkdir(parents=True)
        shutil.copy(FIX / "municipios.csv", cache / "municipios.csv")
        shutil.copy(FIX / "cnpj_12345678000190.json", cache / "cnpj" / "12345678000190.json")
        self.config = {
            "projeto": {"nome": "Teste"},
            "coleta": {"termos": ["startup"], "data_inicio": "2026-01-01"},
            "privacidade": {"sal": "s"},
            "fontes": [{"tipo": "rss", "nome": "feed", "urls": ["https://exemplo.br/rss"]}],
            "classificacao": {"metodo": "regras"},
            "geo": {"ufs_foco": ["MT"]},
        }

    def captar(self):
        with mock.patch("buscastartups.http.ClienteHTTP.get", return_value=Resposta((FIX / "feed.xml").read_bytes())):
            captar(self.config, self.base)

    def test_captar_classificar_revisar(self):
        self.captar()
        self.captar()  # segunda captação não duplica
        abertos = self.base / "dados" / "abertos"
        mencoes = json.loads((abertos / "mencoes.json").read_text())
        self.assertEqual({m["id_original"] for m in mencoes}, {"n1", "n3"})  # futebol: sem termo; n4: fora do período
        n1 = next(m for m in mencoes if m["id_original"] == "n1")
        self.assertEqual(n1["cnpj"], "12.345.678/0001-90")
        self.assertIn("[email]", n1["texto"])

        startups = {s["nome"]: s for s in classificar(self.config, self.base)}
        agro = startups["AgroSense"]
        self.assertEqual(agro["veredito"], "startup")
        self.assertEqual((agro["municipio"], agro["uf"], agro["latitude"]), ("Cuiabá", "MT", -15.601))
        self.assertEqual(agro["responsavel"], "Ana Souza (CEO)")
        self.assertEqual((agro["setor"], agro["maturidade"]), ("agtech", "operacao"))
        self.assertIn("SaaS", agro["modelo_negocio"])
        self.assertEqual(agro["url_fonte"], "https://exemplo.br/n1")

        lumen = startups["Lumen Edu"]
        self.assertEqual(lumen["veredito"], "revisao_humana")
        self.assertEqual((lumen["municipio"], lumen["setor"]), ("Sinop", "edtech"))
        pendentes = (self.base / "dados" / "revisao" / "pendentes.csv").read_text()
        self.assertIn(lumen["id"], pendentes)

        # a decisão humana prevalece na próxima classificação
        with (self.base / "dados" / "revisao" / "revisoes.csv").open("a") as f:
            f.write(f"{lumen['id']},startup,,,,,,,,Banca,2026-10-28,Confirmado no site da empresa\n")
        lumen = {s["nome"]: s for s in classificar(self.config, self.base)}["Lumen Edu"]
        self.assertEqual(lumen["veredito"], "startup")
        self.assertIn("Revisão humana por Banca", lumen["justificativa"])
        self.assertNotIn(lumen["id"], (self.base / "dados" / "revisao" / "pendentes.csv").read_text())

        pacote = json.loads((abertos / "datapackage.json").read_text())
        self.assertEqual({r["name"] for r in pacote["resources"]},
                         {"mencoes-csv", "mencoes-json", "startups-csv", "startups-json"})

    def test_metodo_llm(self):
        self.captar()
        resposta_llm = {"organizacoes": [{
            "nome": "AgroSense", "responsavel": "Ana Souza (CEO)", "setor": "agtech", "maturidade": "operacao",
            "modelo_negocio": ["SaaS"], "municipio": "Cuiabá", "uf": "MT", "cnpj": "", "descricao": "Monitora lavouras",
            "criterios": {c: {"nota": 2, "evidencia": "trecho"} for c in
                          ["inovacao", "modelo_inovador", "escalabilidade", "repetibilidade", "incerteza"]},
            "duvida": False, "justificativa": "Atende aos critérios."}]}
        cliente = mock.Mock()
        cliente.beta.messages.create.return_value = SimpleNamespace(
            stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(resposta_llm))])
        startups = classificar(self.config, self.base, metodo="llm", cliente_llm=cliente)
        self.assertEqual(startups[0]["nome"], "AgroSense")
        self.assertEqual((startups[0]["veredito"], startups[0]["pontuacao"], startups[0]["metodo"]), ("startup", 5.0, "llm"))
        kwargs = cliente.beta.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        self.assertEqual(kwargs["output_config"]["format"]["type"], "json_schema")
        chamadas = cliente.beta.messages.create.call_count
        classificar(self.config, self.base, metodo="llm", cliente_llm=cliente)
        self.assertEqual(cliente.beta.messages.create.call_count, chamadas)  # respostas em cache

    def test_llm_recusa_vai_para_revisao(self):
        cliente = mock.Mock()
        cliente.beta.messages.create.return_value = SimpleNamespace(stop_reason="refusal", content=[])
        clf = ClassificadorLLM({}, Path(tempfile.mkdtemp()), cliente=cliente)
        cand = clf.candidatos({"id": "m1", "entidade": "X"})[0]
        self.assertTrue(cand.duvida)


if __name__ == "__main__":
    unittest.main()
