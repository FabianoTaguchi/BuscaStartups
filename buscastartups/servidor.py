"""Servidor local do painel: arquivos estáticos + API da busca manual e do modo automático.

Escuta apenas em 127.0.0.1 (a própria máquina). Rotas:
  GET  /api/config               termos, fontes e período padrão
  GET  /api/status               busca em andamento, log, histórico e agenda automática
  GET  /api/startups             startups.json da pasta de dados configurada
  POST /api/buscar               {"termos": [...], "de": "AAAA-MM-DD", "ate": "...", "fontes": [...], "metodo": "regras"}
  POST /api/automatico/executar  executa agora a busca automática
"""

from __future__ import annotations

import functools
import http.server
import json
import logging
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from .config import pasta_dados
from .fontes import TIPOS
from .modelo import Periodo
from .servico import BuscaEmAndamento, Servico

log = logging.getLogger(__name__)


def validar_busca(corpo: dict, config: dict) -> dict:
    """Converte o JSON do formulário nos parâmetros da busca, com mensagens de erro claras."""
    termos = corpo.get("termos") or []
    if isinstance(termos, str):
        termos = termos.split(",")
    termos = [t.strip() for t in termos if str(t).strip()]
    if not termos:
        raise ValueError("Informe ao menos uma palavra-chave.")
    try:
        periodo = Periodo.de_texto(corpo.get("de") or None, corpo.get("ate") or None)
    except ValueError:
        raise ValueError("Datas inválidas: use o formato AAAA-MM-DD.") from None
    if periodo.inicio and periodo.fim and periodo.inicio > periodo.fim:
        raise ValueError("A data inicial é posterior à data final.")
    if periodo.inicio and periodo.inicio > date.today():
        raise ValueError("A data inicial está no futuro.")
    nomes = {f.get("nome", f.get("tipo")) for f in config.get("fontes", [])}
    fontes = [f for f in corpo.get("fontes") or [] if f in nomes or f in TIPOS]
    metodo = corpo.get("metodo") if corpo.get("metodo") in ("regras", "llm") else None
    return {"termos": termos, "periodo": periodo, "fontes": fontes or None, "metodo": metodo}


class Manipulador(http.server.SimpleHTTPRequestHandler):
    servico: Servico

    def log_message(self, formato, *args):  # silencia o log de cada arquivo servido
        log.debug(formato, *args)

    def _json(self, codigo: int, dados) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _origem_local(self) -> bool:
        """Bloqueia pedidos vindos de outros sites abertos no navegador (CSRF)."""
        origem = self.headers.get("Origin")
        return origem is None or urlsplit(origem).hostname in ("127.0.0.1", "localhost")

    def do_GET(self):
        caminho = urlsplit(self.path).path
        if caminho == "/":
            self.send_response(302)
            self.send_header("Location", "/dashboard/")
            self.end_headers()
        elif caminho == "/api/config":
            cfg = self.servico.config
            self._json(200, {
                "termos": cfg.get("coleta", {}).get("termos", []),
                "de": cfg.get("coleta", {}).get("data_inicio", ""), "ate": cfg.get("coleta", {}).get("data_fim", ""),
                "fontes": [{"nome": f.get("nome", f.get("tipo")), "tipo": f.get("tipo"),
                            "habilitada": f.get("habilitada", True)} for f in cfg.get("fontes", [])],
                "metodo": cfg.get("classificacao", {}).get("metodo", "regras"),
            })
        elif caminho == "/api/status":
            self._json(200, self.servico.resumo())
        elif caminho == "/api/startups":
            arquivo = pasta_dados(self.servico.config, self.servico.base) / "abertos" / "startups.json"
            if not arquivo.exists():
                return self._json(404, {"erro": "Nenhuma classificação ainda."})
            corpo = arquivo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
        else:
            super().do_GET()

    def do_POST(self):
        caminho = urlsplit(self.path).path
        if not self._origem_local():
            return self._json(403, {"erro": "Origem não permitida."})
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._json(415, {"erro": "Envie JSON."})
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(min(tamanho, 100_000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"erro": "JSON inválido."})
        try:
            if caminho == "/api/buscar":
                parametros = validar_busca(corpo, self.servico.config)
                self.servico.buscar_em_segundo_plano(tipo="manual", **parametros)
            elif caminho == "/api/automatico/executar":
                conf = self.servico.conf_automatico()
                self.servico.buscar_em_segundo_plano(tipo="automatica", periodo=self.servico.periodo_automatico(),
                                                     metodo=conf.get("metodo"))
            else:
                return self._json(404, {"erro": "Rota inexistente."})
        except ValueError as erro:
            return self._json(400, {"erro": str(erro)})
        except BuscaEmAndamento as erro:
            return self._json(409, {"erro": str(erro)})
        self._json(202, {"ok": True})


def servir(servico: Servico, base: Path, porta: int) -> None:
    classe = type("ManipuladorBusca", (Manipulador,), {"servico": servico})
    handler = functools.partial(classe, directory=str(base))
    with http.server.ThreadingHTTPServer(("127.0.0.1", porta), handler) as servidor:
        print(f"Painel em http://127.0.0.1:{porta}/dashboard/  (Ctrl+C para sair)", flush=True)
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            pass
