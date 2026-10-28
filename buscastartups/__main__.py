"""Linha de comando do BuscaStartups.

    python -m buscastartups iniciar     [--porta 8000] [--sem-automatico]   # painel + busca manual + automática
    python -m buscastartups automatico  [--uma-vez]                          # só a busca automática (sem painel)
    python -m buscastartups buscar      --termos "agtech,startup" [--de 2026-01-01] [--ate 2026-10-31] [--fontes ...]
    python -m buscastartups captar      (mesmos argumentos de buscar, sem classificar)
    python -m buscastartups classificar [--metodo regras|llm]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .captacao import captar, consolidar_mencoes
from .classificacao import classificar
from .config import carregar_config
from .modelo import Periodo
from .servico import Servico, esperar_para_sempre
from .servidor import servir

BASE = Path(__file__).resolve().parent.parent


def lista(texto: str | None) -> list[str] | None:
    return [t.strip() for t in texto.split(",") if t.strip()] if texto else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="buscastartups", description="Captação, classificação e painel de startups.")
    sub = parser.add_subparsers(dest="comando", required=True)
    p_ini = sub.add_parser("iniciar", aliases=["dashboard"],
                           help="abre o painel com busca manual e liga a busca automática")
    p_ini.add_argument("--porta", type=int, default=8000)
    p_ini.add_argument("--sem-automatico", action="store_true", help="não executa buscas automáticas")
    p_aut = sub.add_parser("automatico", help="executa a busca automática periodicamente, sem painel")
    p_aut.add_argument("--uma-vez", action="store_true",
                       help="executa uma única vez e sai (para agendar no cron ou no Agendador de Tarefas)")
    p_bus = sub.add_parser("buscar", help="busca manual: captação + classificação")
    p_cap = sub.add_parser("captar", help="Função 1: só a captação")
    for p in (p_bus, p_cap):
        p.add_argument("--termos", help="palavras-chave separadas por vírgula (padrão: as do config)")
        p.add_argument("--de", help="data inicial AAAA-MM-DD")
        p.add_argument("--ate", help="data final AAAA-MM-DD")
        p.add_argument("--fontes", help="nomes ou tipos de fonte, separados por vírgula (padrão: todas habilitadas)")
    p_bus.add_argument("--metodo", choices=["regras", "llm"])
    sub.add_parser("consolidar", help="refaz mencoes.csv/json a partir das captações brutas")
    p_cla = sub.add_parser("classificar", help="Função 2: classifica 'É startup?'")
    p_cla.add_argument("--metodo", choices=["regras", "llm"], help="padrão: o definido no config")
    for p in {id(p): p for p in sub.choices.values()}.values():  # aliases repetem o mesmo parser
        p.add_argument("--config", default=str(BASE / "config.toml"))
    parser.add_argument("-v", "--verboso", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verboso else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    config = carregar_config(args.config)
    servico = Servico(config, BASE)
    if args.comando in ("iniciar", "dashboard"):
        if not args.sem_automatico and servico.conf_automatico()["habilitado"]:
            servico.agendar()
        servir(servico, BASE, args.porta)
    elif args.comando == "automatico":
        if args.uma_vez:
            resultado = servico.buscar_automatico()
            raise SystemExit(0 if resultado["status"] == "concluida" else 1)
        servico.agendar()
        esperar_para_sempre()
    elif args.comando in ("buscar", "captar"):
        opcoes = config.get("coleta", {})
        periodo = Periodo.de_texto(args.de or opcoes.get("data_inicio"), args.ate or opcoes.get("data_fim"))
        if args.comando == "captar":
            captar(config, BASE, termos=lista(args.termos), periodo=periodo, so_fontes=lista(args.fontes))
        else:
            resultado = servico.buscar("manual", termos=lista(args.termos), periodo=periodo,
                                       fontes=lista(args.fontes), metodo=args.metodo)
            raise SystemExit(0 if resultado["status"] == "concluida" else 1)
    elif args.comando == "consolidar":
        consolidar_mencoes(config, BASE)
    elif args.comando == "classificar":
        classificar(config, BASE, metodo=args.metodo)


if __name__ == "__main__":
    main()
