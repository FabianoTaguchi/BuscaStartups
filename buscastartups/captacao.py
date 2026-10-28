"""Função 1 - Captação ativa: busca por palavras-chave e período em notícias, sites,
redes sociais e bases abertas, gerando a base de menções em formato aberto."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import obter_sal, pasta_dados
from .exportar import atualizar_datapackage, escrever_csv, escrever_json, escrever_jsonl, ler_jsonl
from .fontes import TIPOS, Contexto
from .http import ClienteHTTP
from .modelo import CAMPOS_MENCAO, DESCRICAO_MENCAO, RE_CNPJ, Mencao, Periodo, anonimizar_texto, normalizar

log = logging.getLogger(__name__)


SEP_TERMOS = " | "


def termos_encontrados(mencao: Mencao, termos: list[str]) -> list[str]:
    """Termos presentes no título/texto (sem acento e sem diferenciar maiúsculas)."""
    alvo = normalizar(f"{mencao.titulo} {mencao.texto}")
    return [t for t in termos if normalizar(t) in alvo]


def juntar_termos(*valores: str) -> str:
    termos = [t for v in valores for t in (v or "").split(SEP_TERMOS) if t]
    return SEP_TERMOS.join(dict.fromkeys(termos))


def captar(config: dict, base: Path, termos: list[str] | None = None,
           periodo: Periodo | None = None, so_fontes: list[str] | None = None) -> Path:
    projeto, opcoes = config.get("projeto", {}), config.get("coleta", {})
    termos_cli = bool(termos)
    termos = termos or opcoes.get("termos", [])
    periodo = periodo or Periodo.de_texto(opcoes.get("data_inicio"), opcoes.get("data_fim"))
    anonimizar = config.get("privacidade", {}).get("anonimizar_texto", True)
    cliente = ClienteHTTP(
        user_agent=f"BuscaStartups/{__version__} (pesquisa academica; contato: {projeto.get('contato', '-')})",
        intervalo_minimo=float(opcoes.get("intervalo_minimo_s", 1.0)),
    )
    ctx = Contexto(cliente=cliente, sal=obter_sal(config), termos=termos, periodo=periodo,
                   max_por_fonte=int(opcoes.get("max_por_fonte", 200)))
    log.info("Captação: termos=%s período=%s", termos, periodo)

    captadas: list[dict] = []
    for conf in config.get("fontes", []):
        nome = conf.get("nome", conf.get("tipo"))
        if not conf.get("habilitada", True) or (so_fontes and nome not in so_fontes and conf.get("tipo") not in so_fontes):
            continue
        classe = TIPOS.get(conf.get("tipo", ""))
        if classe is None:
            log.error("Tipo de fonte desconhecido: %r (disponíveis: %s)", conf.get("tipo"), ", ".join(TIPOS))
            continue
        # termos passados na linha de comando valem para todas as fontes
        if termos_cli:  # termos informados na hora valem para todas as fontes (inclusive hashtags)
            conf = {**{k: v for k, v in conf.items() if k != "hashtags"}, "termos": termos}
        fonte = classe(conf, ctx)
        n = 0
        for m in fonte.coletar():
            if fonte.filtra_localmente and fonte.termos:
                achados = termos_encontrados(m, fonte.termos)
                if not achados:
                    continue
                m.termo_busca = SEP_TERMOS.join(achados)
            if not m.cnpj and (achado := RE_CNPJ.search(f"{m.titulo} {m.texto}")):
                m.cnpj = achado.group()
            if anonimizar:
                m.texto, m.titulo = anonimizar_texto(m.texto), anonimizar_texto(m.titulo)
            captadas.append(m.como_dict())
            n += 1
        log.info("[%s] %d menções", fonte.nome, n)

    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    arquivo = pasta_dados(config, base) / "brutos" / f"captacao_{carimbo}.jsonl"
    escrever_jsonl(captadas, arquivo)
    log.info("Captação salva em %s (%d menções)", arquivo, len(captadas))
    consolidar_mencoes(config, base)
    return arquivo


def consolidar_mencoes(config: dict, base: Path) -> list[dict]:
    """Junta todas as captações brutas, remove duplicados e gera mencoes.csv/json."""
    raiz = pasta_dados(config, base)
    por_id: dict[str, dict] = {}
    for arquivo in sorted((raiz / "brutos").glob("captacao_*.jsonl")):
        for m in ler_jsonl(arquivo):
            # a captação mais recente prevalece (métricas atualizadas), mas os termos que
            # encontraram a menção em buscas diferentes se acumulam
            anterior = por_id.get(m["id"], {}).get("termo_busca", "")
            m["termo_busca"] = juntar_termos(anterior, m.get("termo_busca", ""))
            por_id[m["id"]] = m
    mencoes = sorted(por_id.values(), key=lambda m: m.get("data_publicacao") or "", reverse=True)
    abertos = raiz / "abertos"
    escrever_csv(mencoes, CAMPOS_MENCAO, abertos / "mencoes.csv")
    escrever_json(mencoes, abertos / "mencoes.json")
    atualizar_datapackage(abertos, config.get("projeto", {}), "mencoes", CAMPOS_MENCAO, DESCRICAO_MENCAO)
    log.info("Base de menções: %d %s -> %s", len(mencoes), dict(Counter(m["plataforma"] for m in mencoes)), abertos)
    return mencoes
