"""Registro dos tipos de fonte. Para adicionar uma nova plataforma, crie uma
subclasse de `Fonte` e inclua-a em `TIPOS`."""

from .base import Contexto, Fonte
from .base_aberta import FonteBaseAberta
from .gdelt import FonteGDELT
from .google_news import FonteGoogleNews
from .mastodon import FonteMastodon
from .reddit import FonteReddit
from .rss import FonteRSS
from .web import FonteWeb
from .youtube import FonteYouTube

TIPOS: dict[str, type[Fonte]] = {
    f.tipo: f for f in (FonteGoogleNews, FonteGDELT, FonteRSS, FonteWeb, FonteBaseAberta,
                        FonteMastodon, FonteReddit, FonteYouTube)
}

__all__ = ["Contexto", "Fonte", "TIPOS"]
