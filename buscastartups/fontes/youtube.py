"""YouTube Data API v3 (requer chave gratuita do Google Cloud)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, time, timezone
from typing import Iterator

from ..modelo import Mencao, iso_de_texto
from .base import Fonte

log = logging.getLogger(__name__)
API = "https://www.googleapis.com/youtube/v3"


def _int(valor) -> int | None:
    return int(valor) if valor not in (None, "") else None


class FonteYouTube(Fonte):
    tipo = "youtube"

    def coletar(self) -> Iterator[Mencao]:
        chave = os.environ.get(self.config.get("chave_api_env", "YOUTUBE_API_KEY"), "")
        if not chave:
            log.warning("[%s] chave da API do YouTube ausente; fonte ignorada", self.nome)
            return
        get = self.ctx.cliente.get
        p = self.ctx.periodo
        for termo in self.termos:
            params = {"part": "snippet", "q": termo, "type": "video", "maxResults": 50,
                      "key": chave, "relevanceLanguage": self.config.get("idioma", "pt"), "order": "date"}
            if p.inicio:
                params["publishedAfter"] = datetime.combine(p.inicio, time.min, timezone.utc).isoformat().replace("+00:00", "Z")
            if p.fim:
                params["publishedBefore"] = datetime.combine(p.fim, time.max.replace(microsecond=0), timezone.utc).isoformat().replace("+00:00", "Z")
            total = 0
            while total < self.max:
                try:
                    busca = get(f"{API}/search", params=params, respeitar_robots=False).json()
                    ids = [i["id"]["videoId"] for i in busca.get("items", [])][: self.max - total]
                    if not ids:
                        break
                    videos = get(f"{API}/videos", respeitar_robots=False, params={
                        "part": "snippet,statistics", "id": ",".join(ids), "key": chave}).json()
                except Exception as erro:  # noqa: BLE001
                    log.error("[%s] falha na busca '%s': %s", self.nome, termo, erro)
                    break
                for video in videos.get("items", []):
                    sn, st = video["snippet"], video.get("statistics", {})
                    total += 1
                    yield Mencao(
                        plataforma=self.tipo, fonte=self.nome, id_original=video["id"],
                        url=f"https://www.youtube.com/watch?v={video['id']}",
                        titulo=sn.get("title", ""), texto=sn.get("description", ""),
                        autor_hash=self.autor(sn.get("channelId", "")),
                        data_publicacao=iso_de_texto(sn.get("publishedAt")),
                        idioma=sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "",
                        termo_busca=termo,
                        curtidas=_int(st.get("likeCount")), comentarios=_int(st.get("commentCount")),
                    )
                if not busca.get("nextPageToken"):
                    break
                params["pageToken"] = busca["nextPageToken"]
