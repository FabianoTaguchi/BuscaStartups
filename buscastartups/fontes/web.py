"""Páginas web comuns, extraídas por seletores CSS definidos na configuração."""

from __future__ import annotations

import logging
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..modelo import Mencao, iso_de_texto, limpar_espacos
from .base import Fonte

log = logging.getLogger(__name__)


def extrair(html: str, url: str, seletores: dict) -> list[dict]:
    """Extrai itens de uma página.

    Sem `item`, a página inteira vira um único registro. Os demais seletores
    (`titulo`, `texto`, `data`, `link`) são relativos a cada item.
    """
    sopa = BeautifulSoup(html, "html.parser")
    blocos = sopa.select(seletores["item"]) if seletores.get("item") else [sopa]

    def texto_de(bloco, chave):
        sel = seletores.get(chave)
        el = bloco.select_one(sel) if sel else None
        return limpar_espacos(el.get_text(" ")) if el else ""

    itens = []
    for bloco in blocos:
        link = url
        if seletores.get("link") and (el := bloco.select_one(seletores["link"])) and el.get("href"):
            link = urljoin(url, el["href"])
        data = ""
        if seletores.get("data") and (el := bloco.select_one(seletores["data"])):
            data = iso_de_texto(el.get("datetime") or el.get_text())
        titulo = texto_de(bloco, "titulo")
        if not titulo and not seletores.get("item") and sopa.title:
            titulo = sopa.title.get_text().strip()
        texto = texto_de(bloco, "texto") or limpar_espacos(bloco.get_text(" "))
        itens.append({"url": link, "titulo": titulo, "texto": texto, "data": data})
    return itens


class FonteWeb(Fonte):
    tipo = "web"
    filtra_localmente = True

    def coletar(self) -> Iterator[Mencao]:
        seletores = self.config.get("seletores", {})
        total = 0
        for url in self.config.get("urls", []):
            try:
                resp = self.ctx.cliente.get(url)
            except Exception as erro:  # noqa: BLE001
                log.error("[%s] falha ao acessar %s: %s", self.nome, url, erro)
                continue
            for i, item in enumerate(extrair(resp.text, url, seletores)):
                if total >= self.max:
                    return
                if not self.ctx.periodo.contem(item["data"]):
                    continue
                total += 1
                yield Mencao(
                    plataforma=self.tipo, fonte=self.nome,
                    id_original=item["url"] if item["url"] != url else f"{url}#{i}",
                    url=item["url"], titulo=item["titulo"], texto=item["texto"],
                    data_publicacao=item["data"],
                )
