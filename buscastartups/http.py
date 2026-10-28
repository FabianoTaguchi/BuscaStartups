"""Cliente HTTP "educado": identifica-se, respeita robots.txt e limita a taxa de requisições."""

from __future__ import annotations

import logging
import time
from urllib import robotparser
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)


class ClienteHTTP:
    def __init__(self, user_agent: str, intervalo_minimo: float = 1.0,
                 tentativas: int = 3, timeout: float = 20.0) -> None:
        self.sessao = requests.Session()
        self.sessao.headers["User-Agent"] = user_agent
        self.user_agent = user_agent
        self.intervalo_minimo = intervalo_minimo
        self.tentativas = tentativas
        self.timeout = timeout
        self._ultimo_acesso: dict[str, float] = {}
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}

    def permitido(self, url: str) -> bool:
        """Consulta o robots.txt do site (cacheado por host)."""
        partes = urlsplit(url)
        base = f"{partes.scheme}://{partes.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                resp = self.sessao.get(base + "/robots.txt", timeout=self.timeout)
                if resp.status_code >= 400:
                    rp = None  # sem robots.txt: acesso permitido
                else:
                    rp.parse(resp.text.splitlines())
            except requests.RequestException:
                rp = None
            self._robots[base] = rp
        rp = self._robots[base]
        return rp is None or rp.can_fetch(self.user_agent, url)

    def _aguardar(self, host: str) -> None:
        decorrido = time.monotonic() - self._ultimo_acesso.get(host, 0.0)
        if decorrido < self.intervalo_minimo:
            time.sleep(self.intervalo_minimo - decorrido)
        self._ultimo_acesso[host] = time.monotonic()

    def get(self, url: str, *, params: dict | None = None,
            respeitar_robots: bool = True) -> requests.Response:
        if respeitar_robots and not self.permitido(url):
            raise PermissionError(f"robots.txt não permite a coleta de {url}")
        host = urlsplit(url).netloc
        for tentativa in range(1, self.tentativas + 1):
            self._aguardar(host)
            try:
                resp = self.sessao.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as erro:
                if tentativa == self.tentativas:
                    raise
                log.warning("Falha de rede em %s (%s); nova tentativa", url, erro)
            else:
                if resp.status_code not in (429, 500, 502, 503, 504):
                    resp.raise_for_status()
                    return resp
                if tentativa == self.tentativas:
                    resp.raise_for_status()
                log.warning("HTTP %s em %s; nova tentativa", resp.status_code, url)
            time.sleep(2 ** tentativa)
        raise RuntimeError("inalcançável")
