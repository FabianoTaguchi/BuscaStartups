"""GDELT DOC 2.0: base aberta que indexa notícias do mundo todo, com busca por termo e período.

Documentação: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
Retorna título, link, veículo e data; o corpo pode ser obtido com `baixar_texto = true`.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Iterator

from ..modelo import Mencao, para_iso
from .base import Fonte

log = logging.getLogger(__name__)
URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _data_gdelt(texto: str) -> str:
    try:
        return para_iso(datetime.strptime(texto, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc))
    except (TypeError, ValueError):
        return ""


class FonteGDELT(Fonte):
    tipo = "gdelt"

    def params(self, termo: str) -> dict:
        q = f'"{termo}"' if " " in termo else termo
        if filtro := self.config.get("filtro", "sourcecountry:brazil sourcelang:portuguese"):
            q += f" {filtro}"
        params = {"query": q, "mode": "artlist", "format": "json", "sort": "datedesc",
                  "maxrecords": min(self.max, 250)}
        p = self.ctx.periodo
        if p.inicio:
            params["startdatetime"] = datetime.combine(p.inicio, time.min).strftime("%Y%m%d%H%M%S")
        if p.fim:
            params["enddatetime"] = datetime.combine(p.fim, time.max).strftime("%Y%m%d%H%M%S")
        return params

    def coletar(self) -> Iterator[Mencao]:
        for termo in self.termos:
            try:
                artigos = self.ctx.cliente.get(URL, params=self.params(termo), respeitar_robots=False).json().get("articles", [])
            except Exception as erro:  # noqa: BLE001
                log.error("[%s] falha na busca '%s': %s", self.nome, termo, erro)
                continue
            for art in artigos:
                url = art.get("url", "")
                yield Mencao(
                    plataforma=self.tipo, fonte=self.nome, id_original=url, url=url,
                    titulo=art.get("title", ""),
                    texto=self.texto_da_pagina(url) if self.baixar_texto else "",
                    data_publicacao=_data_gdelt(art.get("seendate", "")),
                    idioma=art.get("language", ""), termo_busca=termo,
                )
