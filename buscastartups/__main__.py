"""Linha de comando do BuscaStartups.

    python -m buscastartups captar      [--termos "agtech,startup"] [--de 2026-01-01] [--ate 2026-10-31] [--fontes google_news,gdelt]
    python -m buscastartups classificar [--metodo regras|llm]
    python -m buscastartups dashboard   [--porta 8000]
"""

from __future__ import annotations

import argparse
import functools
import http.server
import logging
from pathlib import Path

from .captacao import captar, consolidar_mencoes
from .classificacao import classificar
from .config import carregar_config
from .modelo import Periodo

BASE = Path(__file__).resolve().parent.parent


def lista(texto: str | None) -> list[str] | None:
    return [t.strip() for t in texto.split(",") if t.strip()] if texto else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="buscastartups", description="Captação, classificação e painel de startups.")
    sub = parser.add_subparsers(dest="comando", required=True)
    p_cap = sub.add_parser("captar", help="Função 1: busca por palavras-chave e período")
    p_cap.add_argument("--termos", help="palavras-chave separadas por vírgula (substitui as do config)")
    p_cap.add_argument("--de", help="data inicial AAAA-MM-DD")
    p_cap.add_argument("--ate", help="data final AAAA-MM-DD")
    p_cap.add_argument("--fontes", help="nomes ou tipos de fonte, separados por vírgula (padrão: todas habilitadas)")
    sub.add_parser("consolidar", help="refaz mencoes.csv/json a partir das captações brutas")
    p_cla = sub.add_parser("classificar", help="Função 2: classifica 'É startup?'")
    p_cla.add_argument("--metodo", choices=["regras", "llm"], help="padrão: o definido no config")
    p_das = sub.add_parser("dashboard", help="Função 3: abre o painel no navegador")
    p_das.add_argument("--porta", type=int, default=8000)
    for p in (p_cap, p_cla, sub.choices["consolidar"]):
        p.add_argument("--config", default=str(BASE / "config.toml"))
    parser.add_argument("-v", "--verboso", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verboso else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    if args.comando == "dashboard":
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(BASE))
        with http.server.ThreadingHTTPServer(("127.0.0.1", args.porta), handler) as servidor:
            print(f"Painel em http://127.0.0.1:{args.porta}/dashboard/  (Ctrl+C para sair)")
            try:
                servidor.serve_forever()
            except KeyboardInterrupt:
                pass
        return

    config = carregar_config(args.config)
    if args.comando == "captar":
        opcoes = config.get("coleta", {})
        periodo = Periodo.de_texto(args.de or opcoes.get("data_inicio"), args.ate or opcoes.get("data_fim"))
        captar(config, BASE, termos=lista(args.termos), periodo=periodo, so_fontes=lista(args.fontes))
    elif args.comando == "consolidar":
        consolidar_mencoes(config, BASE)
    elif args.comando == "classificar":
        classificar(config, BASE, metodo=args.metodo)


if __name__ == "__main__":
    main()
