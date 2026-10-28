"""Feeds RSS 2.0 e Atom de sites (portais de notícias, blogs, órgãos públicos, ecossistemas)."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Iterator

from ..modelo import Mencao, iso_de_texto, para_iso
from .base import Fonte

log = logging.getLogger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"


def _data(texto: str | None) -> str:
    if not texto:
        return ""
    try:
        return para_iso(parsedate_to_datetime(texto.strip()))  # RSS (RFC 822)
    except (TypeError, ValueError):
        return iso_de_texto(texto)  # Atom (ISO 8601)


def ler_feed(xml: bytes) -> list[dict]:
    """Converte o XML de um feed em uma lista de itens simples."""
    raiz = ET.fromstring(xml)
    itens = []
    for item in raiz.iter("item"):  # RSS 2.0
        itens.append({
            "id": item.findtext("guid") or item.findtext("link") or "",
            "url": item.findtext("link") or "",
            "titulo": item.findtext("title") or "",
            "html": item.findtext("description") or "",
            "autor": item.findtext("author") or item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "",
            "veiculo": item.findtext("source") or "",
            "data": _data(item.findtext("pubDate")),
        })
    for entry in raiz.iter(f"{ATOM}entry"):  # Atom
        link = entry.find(f"{ATOM}link")
        itens.append({
            "id": entry.findtext(f"{ATOM}id") or "",
            "url": link.get("href", "") if link is not None else "",
            "titulo": entry.findtext(f"{ATOM}title") or "",
            "html": entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content") or "",
            "autor": entry.findtext(f"{ATOM}author/{ATOM}name") or "",
            "veiculo": "",
            "data": _data(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")),
        })
    return itens


class FonteRSS(Fonte):
    tipo = "rss"
    filtra_localmente = True  # feeds não têm busca: filtra pelos termos após baixar

    def mencao(self, item: dict, termo: str = "") -> Mencao:
        texto = self.html_para_texto(item["html"])
        if self.baixar_texto and item["url"]:
            texto = self.texto_da_pagina(item["url"]) or texto
        return Mencao(
            plataforma=self.tipo, fonte=self.nome, id_original=item["id"], url=item["url"],
            titulo=item["titulo"].strip(), texto=texto, autor_hash=self.autor(item["autor"]),
            data_publicacao=item["data"], termo_busca=termo,
        )

    def coletar(self) -> Iterator[Mencao]:
        total = 0
        for url in self.config.get("urls", []):
            try:
                itens = ler_feed(self.ctx.cliente.get(url).content)
            except Exception as erro:  # noqa: BLE001 - uma fonte com problema não interrompe as demais
                log.error("[%s] falha ao ler %s: %s", self.nome, url, erro)
                continue
            for item in itens:
                if total >= self.max:
                    return
                if not self.ctx.periodo.contem(item["data"]):
                    continue
                total += 1
                yield self.mencao(item)
