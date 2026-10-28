"""Função 2 - Classificação "É startup?".

Etapas:
 1. cada menção gera candidatos (organizações) com notas nos cinco critérios
    (método `regras` ou `llm`);
 2. candidatos da mesma organização (mesmo CNPJ ou nome) são consolidados;
 3. enriquecimento com CNPJ (Receita Federal) e georreferenciamento por município;
 4. veredito: startup / nao_startup / revisao_humana (casos duvidosos);
 5. decisões registradas em dados/revisao/revisoes.csv prevalecem sobre o automático.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections import Counter
from pathlib import Path

from ..captacao import juntar_termos
from ..cnpj import ConsultaCNPJ, resumo
from ..config import pasta_dados
from ..exportar import atualizar_datapackage, escrever_csv, escrever_json
from ..geo import URL_MUNICIPIOS, Geocodificador, carregar_municipios
from ..http import ClienteHTTP
from ..modelo import (CAMPOS_STARTUP, CRITERIOS, DESCRICAO_STARTUP, MATURIDADES, NAO_STARTUP, NOMES_CRITERIOS,
                      REVISAO, STARTUP, Startup, hash_curto, normalizar, so_digitos)
from .regras import Candidato, ClassificadorRegras

log = logging.getLogger(__name__)

CAMPOS_REVISAO = ["id", "veredito", "nome", "responsavel", "setor", "maturidade", "modelo_negocio",
                  "municipio", "uf", "revisor", "data_revisao", "observacao"]
_SUFIXOS = re.compile(r"\b(ltda|s\.?a|me|epp|eireli|inc|startup|tecnologia|tecnologias)\b\.?")


def chave(c: Candidato) -> str:
    if len(so_digitos(c.cnpj)) == 14:
        return "cnpj:" + so_digitos(c.cnpj)
    if c.nome:
        return "nome:" + re.sub(r"[^a-z0-9]", "", _SUFIXOS.sub("", normalizar(c.nome)))
    return "mencao:" + c.mencao_id  # sem nome identificado: não agrupa


def mais_comum(valores: list[str]) -> str:
    valores = [v for v in valores if v]
    return Counter(valores).most_common(1)[0][0] if valores else ""


def veredito(s: Startup, duvida: bool, conf: dict) -> tuple[str, str]:
    limiar_sim = float(conf.get("limiar_startup", 3.0))
    limiar_nao = float(conf.get("limiar_nao_startup", 1.5))
    obrigatorios = conf.get("criterios_obrigatorios", ["inovacao", "incerteza"])
    zerados = [NOMES_CRITERIOS[c] for c in obrigatorios if getattr(s, f"crit_{c}") == 0]
    if not s.nome:
        return REVISAO, "Nome da organização não identificado no texto."
    if duvida:
        return REVISAO, "Classificador indicou dúvida."
    if s.pontuacao >= limiar_sim and not zerados:
        return STARTUP, f"Pontuação {s.pontuacao:g}/5 com todos os critérios obrigatórios atendidos."
    if s.pontuacao <= limiar_nao:
        return NAO_STARTUP, f"Pontuação {s.pontuacao:g}/5, igual ou abaixo do limiar ({limiar_nao:g})."
    if zerados:
        return REVISAO, f"Pontuação {s.pontuacao:g}/5, mas sem evidência de: {', '.join(zerados)}."
    return REVISAO, f"Pontuação intermediária ({s.pontuacao:g}/5)."


def consolidar(grupo: list[Candidato], mencoes: dict[str, dict]) -> tuple[Startup, bool]:
    origem = sorted((mencoes[c.mencao_id] for c in grupo), key=lambda m: m.get("data_publicacao") or "")
    notas = {c: max(x.notas.get(c, 0.0) for x in grupo) for c in CRITERIOS}
    evid = {c: list(dict.fromkeys(e for x in grupo for e in x.evidencias.get(c, []))) for c in CRITERIOS}
    estagios = [x.maturidade for x in grupo if x.maturidade != "desconhecida"]
    links = list(dict.fromkeys(m["url"] for m in reversed(origem) if m.get("url")))
    s = Startup(
        nome=mais_comum([x.nome for x in grupo]),
        responsavel=mais_comum([x.responsavel for x in grupo]),
        setor=mais_comum([x.setor for x in grupo]),
        # o estágio mais avançado citado (MATURIDADES vai de ideação a escala)
        maturidade=max(estagios, key=MATURIDADES.index) if estagios else "desconhecida",
        modelo_negocio=" | ".join(dict.fromkeys(m for x in grupo for m in x.modelos)),
        municipio=mais_comum([x.municipio for x in grupo]), uf=mais_comum([x.uf for x in grupo]),
        cnpj=mais_comum([x.cnpj for x in grupo]),
        descricao=max((x.descricao for x in grupo), key=len, default=""),
        **{f"crit_{c}": notas[c] for c in CRITERIOS},
        pontuacao=sum(notas.values()),
        evidencias="; ".join(f"{c}: {', '.join(evid[c][:6])}" for c in CRITERIOS if evid[c]),
        metodo=mais_comum([x.metodo for x in grupo]),
        n_mencoes=len({x.mencao_id for x in grupo}),
        url_fonte=links[0] if links else "", fontes=" | ".join(links),
        primeira_mencao=origem[0].get("data_publicacao", ""), ultima_mencao=origem[-1].get("data_publicacao", ""),
        termos=juntar_termos(*(m.get("termo_busca", "") for m in origem)),
        ids_mencoes="|".join(dict.fromkeys(x.mencao_id for x in grupo)),
        justificativa=" ".join(dict.fromkeys(x.justificativa for x in grupo if x.justificativa)),
    )
    return s, any(x.duvida for x in grupo)


def enriquecer_cnpj(s: Startup, consulta: ConsultaCNPJ, conf: dict) -> list[str]:
    notas = []
    dados = consulta.consultar(s.cnpj) if s.cnpj else None
    if not dados:
        return notas
    r = resumo(dados)
    s.nome = s.nome or r["nome"]
    s.responsavel = s.responsavel or r["responsavel"]
    s.setor = s.setor or r["setor_cnae"]
    s.municipio, s.uf = (s.municipio or r["municipio"]), (s.uf or r["uf"])
    anos_max = float(conf.get("idade_maxima_anos", 10))
    if r["idade_anos"] is not None and r["idade_anos"] > anos_max:
        s.crit_incerteza = 0.0
        s.pontuacao = sum(getattr(s, f"crit_{c}") for c in CRITERIOS)
        notas.append(f"CNPJ aberto há {r['idade_anos']:.0f} anos (> {anos_max:g}): incerteza anulada.")
    if r["situacao"] and r["situacao"].upper() != "ATIVA":
        notas.append(f"Situação cadastral: {r['situacao']}.")
    return notas


def georreferenciar(s: Startup, geo: Geocodificador, textos: list[str]) -> None:
    if not s.municipio:
        for texto in textos:
            municipio, uf = geo.localizar(texto)
            if municipio or uf:
                s.municipio, s.uf = municipio, s.uf or uf
                break
    if s.municipio and (item := geo.coordenadas(s.municipio, s.uf)):
        s.municipio, s.uf, s.latitude, s.longitude = item["nome"], item["uf"], item["lat"], item["lon"]


def ler_revisoes(arquivo: Path) -> dict[str, dict]:
    if not arquivo.exists():
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        with arquivo.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CAMPOS_REVISAO)
        return {}
    with arquivo.open(encoding="utf-8-sig") as f:
        return {r["id"]: r for r in csv.DictReader(f) if r.get("id")}  # a última linha de cada id prevalece


def aplicar_revisao(s: Startup, r: dict, geo: Geocodificador | None) -> None:
    for campo in ["nome", "responsavel", "setor", "maturidade", "modelo_negocio", "municipio", "uf"]:
        if (r.get(campo) or "").strip():
            setattr(s, campo, r[campo].strip())
    if r.get("veredito") in (STARTUP, NAO_STARTUP, REVISAO):
        s.veredito = r["veredito"]
    s.metodo += "+revisao"
    quem = f" por {r['revisor']}" if r.get("revisor") else ""
    s.justificativa = f"Revisão humana{quem}: {r.get('observacao') or 'sem observação'}. (Automático: {s.justificativa})"
    if geo and (r.get("municipio") or r.get("uf")):
        s.latitude = s.longitude = None
        georreferenciar(s, geo, [])


def classificar(config: dict, base: Path, metodo: str | None = None, cliente_llm=None) -> list[dict]:
    conf = config.get("classificacao", {})
    metodo = metodo or conf.get("metodo", "regras")
    raiz = pasta_dados(config, base)
    entrada = raiz / "abertos" / "mencoes.json"
    if not entrada.exists():
        raise FileNotFoundError(f"{entrada} não encontrado: execute a captação primeiro.")
    mencoes = {m["id"]: m for m in json.loads(entrada.read_text(encoding="utf-8"))}

    regras = ClassificadorRegras(conf)
    llm = None
    if metodo == "llm":
        from .llm import ClassificadorLLM
        llm = ClassificadorLLM(conf, raiz / "cache" / "llm", cliente=cliente_llm)

    # 1. candidatos por menção. As regras servem de pré-filtro: menções sem organização
    #    nomeada e com pouca evidência de startup são descartadas (e não vão ao LLM).
    limiar_mencao = float(conf.get("limiar_minimo_mencao", 1.0))
    limiar_sim = float(conf.get("limiar_startup", 3.0))
    candidatos: list[Candidato] = []
    descartadas = 0
    for m in mencoes.values():
        cand = regras.candidatos(m)[0]
        pontos = sum(cand.notas.values())
        if llm is not None and (cand.nome or pontos >= limiar_mencao):
            try:
                candidatos.extend(llm.candidatos(m))
                continue
            except Exception as erro:  # noqa: BLE001
                log.error("LLM falhou na menção %s (%s); usando regras com revisão humana", m["id"], erro)
                cand.duvida = True
        # sem nome, só vale a pena revisar se a própria menção já é forte em evidências
        if cand.nome or pontos >= limiar_sim:
            candidatos.append(cand)
        else:
            descartadas += 1
    log.info("%d menções analisadas, %d candidatos, %d menções descartadas", len(mencoes), len(candidatos), descartadas)

    # 2-4. consolidação, enriquecimento e veredito
    grupos: dict[str, list[Candidato]] = {}
    for c in candidatos:
        grupos.setdefault(chave(c), []).append(c)

    cliente = ClienteHTTP(user_agent="BuscaStartups (pesquisa academica)",
                          intervalo_minimo=float(config.get("coleta", {}).get("intervalo_minimo_s", 1.0)))
    consulta = ConsultaCNPJ(cliente, raiz / "cache" / "cnpj") if conf.get("consultar_cnpj", True) else None
    geo = None
    try:
        geo_conf = config.get("geo", {})
        municipios = carregar_municipios(raiz / "cache", cliente, geo_conf.get("url_municipios", URL_MUNICIPIOS))
        geo = Geocodificador(municipios, geo_conf.get("ufs_foco", []))
    except Exception as erro:  # noqa: BLE001
        log.warning("Georreferenciamento indisponível (%s); o mapa ficará sem pontos", erro)

    revisoes = ler_revisoes(raiz / "revisao" / "revisoes.csv")
    startups: list[Startup] = []
    for k, grupo in grupos.items():
        s, duvida = consolidar(grupo, mencoes)
        s.id = hash_curto(k)
        notas = enriquecer_cnpj(s, consulta, conf) if consulta else []
        if geo:
            textos = [f"{mencoes[c.mencao_id].get('titulo', '')}. {mencoes[c.mencao_id].get('texto', '')}" for c in grupo]
            georreferenciar(s, geo, textos)
        s.veredito, motivo = veredito(s, duvida, conf)
        s.justificativa = " ".join(p for p in [motivo, *notas, s.justificativa] if p)
        if s.id in revisoes:
            aplicar_revisao(s, revisoes[s.id], geo)
        startups.append(s)

    ordem = {STARTUP: 0, REVISAO: 1, NAO_STARTUP: 2}
    startups.sort(key=lambda s: (ordem[s.veredito], -s.pontuacao, s.nome.lower()))
    registros = [s.como_dict() for s in startups]

    # 5. saídas abertas + fila de revisão humana
    abertos = raiz / "abertos"
    escrever_csv(registros, CAMPOS_STARTUP, abertos / "startups.csv")
    escrever_json(registros, abertos / "startups.json")
    atualizar_datapackage(abertos, config.get("projeto", {}), "startups", CAMPOS_STARTUP, DESCRICAO_STARTUP)
    pendentes = [{**r, "veredito": "", "veredito_automatico": r["veredito"]}
                 for r in registros if r["veredito"] == REVISAO and r["id"] not in revisoes]
    escrever_csv(pendentes, CAMPOS_REVISAO + ["veredito_automatico", "pontuacao", "justificativa", "evidencias",
                                              "descricao", "url_fonte"], raiz / "revisao" / "pendentes.csv")
    log.info("Classificação (%s): %s -> %s; %d pendentes de revisão em %s", metodo,
             dict(Counter(s.veredito for s in startups)), abertos, len(pendentes), raiz / "revisao" / "pendentes.csv")
    return registros
