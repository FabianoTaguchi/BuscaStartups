"""Interface comum das fontes de captação."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterator

from bs4 import BeautifulSoup

from ..http import ClienteHTTP
from ..modelo import Mencao, Periodo, limpar_espacos, pseudonimizar

log = logging.getLogger(__name__)


@dataclass
class Contexto:
    cliente: ClienteHTTP
    sal: str
    termos: list[str] = field(default_factory=list)
    periodo: Periodo = field(default_factory=Periodo)
    max_por_fonte: int = 200


class Fonte:
    """Cada tipo de fonte implementa `coletar`, devolvendo menções já normalizadas."""

    tipo = ""
    filtra_localmente = False  # True quando a plataforma não oferece busca por termo

    def __init__(self, config: dict, contexto: Contexto) -> None:
        self.config = config
        self.ctx = contexto
        self.nome = config.get("nome", self.tipo)
        self.max = int(config.get("max", contexto.max_por_fonte))
        # termos específicos da fonte têm prioridade sobre os termos globais
        self.termos = config.get("termos", contexto.termos)
        self.baixar_texto = bool(config.get("baixar_texto", False))

    def coletar(self) -> Iterator[Mencao]:
        raise NotImplementedError

    def autor(self, identificador: str) -> str:
        return pseudonimizar(identificador, self.ctx.sal)

    @staticmethod
    def html_para_texto(html: str) -> str:
        if not html:
            return ""
        return limpar_espacos(BeautifulSoup(html, "html.parser").get_text(" "))

    def texto_da_pagina(self, url: str, limite: int = 8000) -> str:
        """Baixa a página da notícia e extrai os parágrafos do corpo (respeitando robots.txt)."""
        try:
            html = self.ctx.cliente.get(url).text
        except Exception as erro:  # noqa: BLE001
            log.debug("[%s] sem texto completo de %s: %s", self.nome, url, erro)
            return ""
        sopa = BeautifulSoup(html, "html.parser")
        corpo = sopa.find("article") or sopa
        paragrafos = [limpar_espacos(p.get_text(" ")) for p in corpo.find_all("p")]
        return " ".join(p for p in paragrafos if len(p) > 40)[:limite]
