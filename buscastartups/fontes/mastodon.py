"""Mastodon (fediverso): linha do tempo pública de hashtags, sem necessidade de login."""

from __future__ import annotations

import logging
from typing import Iterator

from ..modelo import Mencao, iso_de_texto
from .base import Fonte

log = logging.getLogger(__name__)


class FonteMastodon(Fonte):
    tipo = "mastodon"

    def mencao(self, status: dict, hashtag: str) -> Mencao:
        conta = status.get("account") or {}
        return Mencao(
            plataforma=self.tipo, fonte=self.nome,
            id_original=str(status["id"]), url=status.get("url") or status.get("uri", ""),
            texto=self.html_para_texto(status.get("content", "")),
            autor_hash=self.autor(conta.get("acct", "")),
            data_publicacao=iso_de_texto(status.get("created_at")),
            idioma=status.get("language") or "", termo_busca=f"#{hashtag}",
            curtidas=status.get("favourites_count"), comentarios=status.get("replies_count"),
            compartilhamentos=status.get("reblogs_count"),
        )

    def coletar(self) -> Iterator[Mencao]:
        instancia = self.config.get("instancia", "mastodon.social")
        hashtags = self.config.get("hashtags") or [t.replace(" ", "") for t in self.termos]
        for hashtag in hashtags:
            hashtag = hashtag.lstrip("#")
            url = f"https://{instancia}/api/v1/timelines/tag/{hashtag}"
            params = {"limit": 40}
            total = 0
            while total < self.max:
                try:
                    statuses = self.ctx.cliente.get(url, params=params, respeitar_robots=False).json()
                except Exception as erro:  # noqa: BLE001
                    log.error("[%s] falha em #%s: %s", self.nome, hashtag, erro)
                    break
                if not statuses:
                    break
                for status in statuses:
                    if total >= self.max:
                        break
                    m = self.mencao(status, hashtag)
                    if status.get("reblog") or not self.ctx.periodo.contem(m.data_publicacao):
                        continue  # reblogs são ignorados: o original é captado
                    total += 1
                    yield m
                # linha do tempo vem da mais nova para a mais antiga: para ao passar do início
                if self.ctx.periodo.anterior_ao_inicio(iso_de_texto(statuses[-1].get("created_at"))):
                    break
                params["max_id"] = statuses[-1]["id"]
