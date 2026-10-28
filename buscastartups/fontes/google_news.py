"""Google Notícias: busca por palavra-chave e período via feed RSS público de pesquisa.

Os operadores `after:` e `before:` restringem o período no próprio buscador.
O feed traz título, veículo e um resumo curto; use `baixar_texto = true` para
tentar obter o corpo da notícia (só quando o robots.txt do veículo permitir).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterator

from .rss import FonteRSS, ler_feed
from ..modelo import Mencao

log = logging.getLogger(__name__)
URL = "https://news.google.com/rss/search"


class FonteGoogleNews(FonteRSS):
    tipo = "google_news"
    filtra_localmente = False

    def consulta(self, termo: str) -> str:
        q = f'"{termo}"' if " " in termo else termo
        if extra := self.config.get("complemento"):  # ex.: '"Mato Grosso"'
            q += f" {extra}"
        p = self.ctx.periodo
        if p.inicio:
            q += f" after:{(p.inicio - timedelta(days=1)).isoformat()}"
        if p.fim:
            q += f" before:{(p.fim + timedelta(days=1)).isoformat()}"
        return q

    def coletar(self) -> Iterator[Mencao]:
        idioma = self.config.get("idioma", "pt-BR")
        pais = self.config.get("pais", "BR")
        for termo in self.termos:
            params = {"q": self.consulta(termo), "hl": idioma, "gl": pais, "ceid": f"{pais}:{idioma.split('-')[0]}-419"}
            try:
                itens = ler_feed(self.ctx.cliente.get(URL, params=params).content)
            except Exception as erro:  # noqa: BLE001
                log.error("[%s] falha na busca '%s': %s", self.nome, termo, erro)
                continue
            for item in itens[: self.max]:
                if not self.ctx.periodo.contem(item["data"]):
                    continue
                yield self.mencao(item, termo)
