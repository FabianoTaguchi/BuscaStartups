"""Leitura da configuração e caminhos de dados."""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

log = logging.getLogger(__name__)
SAL_PADRAO = "troque-este-sal"


def carregar_config(caminho: str | Path) -> dict:
    with open(caminho, "rb") as arq:
        return tomllib.load(arq)


def pasta_dados(config: dict, base: Path) -> Path:
    return base / config.get("projeto", {}).get("pasta_dados", "dados")


def obter_sal(config: dict) -> str:
    sal = os.environ.get("BUSCASTARTUPS_SAL") or config.get("privacidade", {}).get("sal", "")
    if not sal:
        log.warning("Nenhum sal definido (BUSCASTARTUPS_SAL). Usando um valor padrão: "
                    "defina um sal secreto antes da captação definitiva.")
        sal = SAL_PADRAO
    return sal
