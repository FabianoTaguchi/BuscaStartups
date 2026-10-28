"""Reddit: busca pública em subreddits via endpoints .json."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

from ..modelo import Mencao, para_iso
from .base import Fonte

log = logging.getLogger(__name__)


class FonteReddit(Fonte):
    tipo = "reddit"

    def mencao(self, post: dict, termo: str) -> Mencao:
        return Mencao(
            plataforma=self.tipo, fonte=self.nome,
            id_original=post["name"], url="https://www.reddit.com" + post.get("permalink", ""),
            titulo=post.get("title", ""), texto=post.get("selftext", ""),
            autor_hash=self.autor(post.get("author", "")),
            data_publicacao=para_iso(datetime.fromtimestamp(post.get("created_utc", 0), timezone.utc)),
            termo_busca=termo, curtidas=post.get("score"), comentarios=post.get("num_comments"),
        )

    def coletar(self) -> Iterator[Mencao]:
        for sub in self.config.get("subreddits") or ["all"]:
            for termo in self.termos:
                url = f"https://www.reddit.com/r/{sub}/search.json"
                params = {"q": termo, "restrict_sr": 1, "sort": "new", "limit": 100}
                total = 0
                while total < self.max:
                    try:
                        dados = self.ctx.cliente.get(url, params=params, respeitar_robots=False).json()["data"]
                    except Exception as erro:  # noqa: BLE001
                        log.error("[%s] falha em r/%s '%s': %s", self.nome, sub, termo, erro)
                        break
                    passou_do_inicio = False
                    for filho in dados.get("children", []):
                        if total >= self.max:
                            break
                        m = self.mencao(filho["data"], termo)
                        if self.ctx.periodo.anterior_ao_inicio(m.data_publicacao):
                            passou_do_inicio = True  # ordenado do mais novo ao mais antigo
                            break
                        if self.ctx.periodo.contem(m.data_publicacao):
                            total += 1
                            yield m
                    if passou_do_inicio or not dados.get("after"):
                        break
                    params["after"] = dados["after"]
