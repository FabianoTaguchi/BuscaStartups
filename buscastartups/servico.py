"""Execução das buscas nos dois modos de uso:

* manual     - palavras-chave, período e fontes escolhidos pela pessoa (painel ou linha de comando);
* automático - repete a busca com os termos do config.toml a cada `intervalo_horas`, cobrindo
               desde a última execução bem-sucedida até hoje.

Cada busca executa captação + classificação. Só uma busca roda por vez; o histórico
fica em dados/estado.json.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .captacao import captar
from .classificacao import classificar
from .config import pasta_dados
from .modelo import Periodo, agora_iso

log = logging.getLogger(__name__)
MAX_HISTORICO = 50


class BuscaEmAndamento(RuntimeError):
    pass


class _ColetorLog(logging.Handler):
    """Guarda as últimas linhas de log da busca em andamento, para exibir no painel."""

    def __init__(self, destino: deque) -> None:
        super().__init__(logging.INFO)
        self.destino = destino
        self.erros = 0
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, registro: logging.LogRecord) -> None:
        self.erros += registro.levelno >= logging.ERROR
        self.destino.append(self.format(registro))


class Servico:
    def __init__(self, config: dict, base: Path) -> None:
        self.config = config
        self.base = base
        self.arquivo_estado = pasta_dados(config, base) / "estado.json"
        self._trava = threading.Lock()
        self.atual: dict | None = None
        self.log: deque[str] = deque(maxlen=200)
        self.agendador_ativo = False

    # ------------------------------------------------------------- estado --

    def estado(self) -> dict:
        if self.arquivo_estado.exists():
            return json.loads(self.arquivo_estado.read_text(encoding="utf-8"))
        return {"ultima_automatica": "", "historico": []}

    def _salvar_estado(self, estado: dict) -> None:
        self.arquivo_estado.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo_estado.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")

    def ocupado(self) -> bool:
        return self._trava.locked()

    # ------------------------------------------------------------- buscas --

    def buscar(self, tipo: str, termos: list[str] | None = None, periodo: Periodo | None = None,
               fontes: list[str] | None = None, metodo: str | None = None) -> dict:
        """Executa captação + classificação (bloqueante). Lança BuscaEmAndamento se já houver uma."""
        if not self._trava.acquire(blocking=False):
            raise BuscaEmAndamento("Já existe uma busca em andamento.")
        coletor = _ColetorLog(self.log)
        raiz = logging.getLogger()
        nivel_original = raiz.level
        raiz.setLevel(min(nivel_original or logging.WARNING, logging.INFO))  # o painel mostra o andamento (INFO)
        raiz.addHandler(coletor)
        termos = termos or self.config.get("coleta", {}).get("termos", [])
        periodo = periodo or Periodo()
        self.log.clear()
        self.atual = {"tipo": tipo, "status": "executando", "termos": termos,
                      "de": str(periodo.inicio or ""), "ate": str(periodo.fim or ""),
                      "fontes": fontes or [], "metodo": metodo or "", "inicio": agora_iso(), "fim": ""}
        try:
            log.info("Busca %s iniciada: termos=%s período=%s", tipo, termos, periodo)
            arquivo = captar(self.config, self.base, termos=termos, periodo=periodo, so_fontes=fontes)
            novas = sum(1 for linha in arquivo.read_text(encoding="utf-8").splitlines() if linha.strip())
            startups = classificar(self.config, self.base, metodo=metodo)
            self.atual.update(status="concluida", mencoes_captadas=novas,
                              startups=sum(1 for s in startups if s["veredito"] == "startup"),
                              revisao=sum(1 for s in startups if s["veredito"] == "revisao_humana"))
            log.info("Busca %s concluída: %d menções captadas", tipo, novas)
        except Exception as erro:  # noqa: BLE001 - o erro é registrado e exibido no painel
            log.exception("Busca %s falhou", tipo)
            self.atual.update(status="erro", erro=str(erro))
        finally:
            self.atual["fim"] = agora_iso()
            self.atual["falhas"] = coletor.erros  # fontes inacessíveis, páginas com erro etc.
            estado = self.estado()
            if tipo == "automatica" and self.atual["status"] == "concluida":
                estado["ultima_automatica"] = self.atual["inicio"]
            estado["historico"] = ([dict(self.atual)] + estado.get("historico", []))[:MAX_HISTORICO]
            self._salvar_estado(estado)
            raiz.removeHandler(coletor)
            raiz.setLevel(nivel_original)
            self._trava.release()
        return dict(self.atual)

    def buscar_em_segundo_plano(self, **kwargs) -> None:
        if self.ocupado():
            raise BuscaEmAndamento("Já existe uma busca em andamento.")
        threading.Thread(target=self._sem_excecao, kwargs=kwargs, daemon=True).start()

    def _sem_excecao(self, **kwargs) -> None:
        try:
            self.buscar(**kwargs)
        except BuscaEmAndamento:
            log.warning("Busca ignorada: outra já estava em andamento")

    # ---------------------------------------------------------- automático --

    def conf_automatico(self) -> dict:
        return {"habilitado": True, "intervalo_horas": 24, "janela_inicial_dias": 30,
                "sobreposicao_dias": 1, **self.config.get("automatico", {})}

    def periodo_automatico(self, hoje: date | None = None) -> Periodo:
        """Da última execução automática (com sobreposição) até hoje; na primeira vez, a janela inicial."""
        conf, hoje = self.conf_automatico(), hoje or date.today()
        ultima = self.estado().get("ultima_automatica")
        if ultima:
            inicio = datetime.fromisoformat(ultima).date() - timedelta(days=int(conf["sobreposicao_dias"]))
        else:
            inicio = hoje - timedelta(days=int(conf["janela_inicial_dias"]))
        return Periodo(inicio, hoje)

    def proxima_automatica(self) -> datetime:
        ultima = self.estado().get("ultima_automatica")
        if not ultima:
            return datetime.now(timezone.utc)
        return datetime.fromisoformat(ultima) + timedelta(hours=float(self.conf_automatico()["intervalo_horas"]))

    def buscar_automatico(self) -> dict:
        conf = self.conf_automatico()
        return self.buscar("automatica", periodo=self.periodo_automatico(), metodo=conf.get("metodo"))

    def agendar(self, parar: threading.Event | None = None) -> threading.Thread:
        """Inicia o agendador em segundo plano: executa sempre que a próxima execução vencer."""
        parar = parar or threading.Event()

        def laco() -> None:
            log.info("Busca automática ativa: a cada %s h", self.conf_automatico()["intervalo_horas"])
            while not parar.is_set():
                if datetime.now(timezone.utc) >= self.proxima_automatica() and not self.ocupado():
                    try:
                        self.buscar_automatico()
                    except BuscaEmAndamento:
                        pass
                    if self.atual and self.atual["status"] == "erro":
                        parar.wait(1800)  # após erro, tenta de novo em 30 min
                parar.wait(60)

        fio = threading.Thread(target=laco, daemon=True, name="agendador")
        fio.start()
        self.agendador_ativo = True
        return fio

    def resumo(self) -> dict:
        conf = self.conf_automatico()
        estado = self.estado()
        return {
            "ocupado": self.ocupado(), "atual": self.atual, "log": list(self.log)[-40:],
            "historico": estado.get("historico", [])[:10],
            "automatico": {**conf, "ativo": self.agendador_ativo, "ultima": estado.get("ultima_automatica", ""),
                           "proxima": self.proxima_automatica().replace(microsecond=0).isoformat()},
        }


def esperar_para_sempre() -> None:
    while True:
        time.sleep(3600)
