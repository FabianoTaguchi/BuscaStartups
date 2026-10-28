"""Classificador assistido por modelo de linguagem (Claude, da Anthropic).

Opcional: requer `pip install anthropic` e a variável ANTHROPIC_API_KEY.
O modelo lê cada menção, identifica as organizações citadas e devolve, em JSON
validado por esquema, os campos do painel e a nota de cada critério com a
evidência textual. As respostas ficam em cache (dados/cache/llm) para que a
mesma menção nunca seja enviada duas vezes.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..modelo import CRITERIOS, MATURIDADES
from .regras import Candidato

log = logging.getLogger(__name__)

MODELO_PADRAO = "claude-opus-5-5"

INSTRUCOES = """Você apoia uma pesquisa de mestrado que mapeia startups a partir de conteúdos públicos da internet.

Para o conteúdo fornecido, identifique cada organização (empresa, projeto empreendedor) citada e avalie se ela é uma STARTUP segundo cinco critérios:
1. inovacao - oferece produto, serviço ou processo novo ou significativamente melhorado (tecnologia, P&D, solução inédita).
2. modelo_inovador - o modelo de negócio é inovador (ex.: plataforma digital, SaaS, marketplace, assinatura, nova forma de capturar valor).
3. escalabilidade - consegue crescer receita/clientes sem aumento proporcional de custos (alcance regional/nacional/global, produto digital).
4. repetibilidade - entrega o mesmo produto/serviço de forma padronizada e replicável, sem customização por cliente.
5. incerteza - opera em condições de extrema incerteza (empresa jovem, validação de mercado, MVP, aceleração, capital de risco, investimento anjo).

Notas por critério: 0 = sem evidência ou evidência contrária; 1 = evidência fraca/indireta; 2 = evidência clara no texto.
Baseie-se apenas no texto. Não invente nomes, pessoas, cidades ou CNPJs: use "" quando a informação não estiver no conteúdo.
Marque "duvida": true quando o texto for insuficiente ou ambíguo para decidir, para que um humano revise.
Empresas consolidadas/tradicionais, órgãos públicos, aceleradoras, fundos de investimento e eventos NÃO são startups (nota 0 em incerteza), mas podem ser listados se citados.
Se o conteúdo não trata de nenhuma organização, devolva a lista "organizacoes" vazia."""

_CRITERIO = {
    "type": "object",
    "properties": {"nota": {"type": "integer", "enum": [0, 1, 2]}, "evidencia": {"type": "string"}},
    "required": ["nota", "evidencia"],
    "additionalProperties": False,
}
ESQUEMA = {
    "type": "object",
    "properties": {
        "organizacoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string"},
                    "responsavel": {"type": "string", "description": "Nome e cargo, ex.: 'Ana Souza (CEO)'"},
                    "setor": {"type": "string", "description": "ex.: agtech, fintech, healthtech, edtech, govtech"},
                    "maturidade": {"type": "string", "enum": MATURIDADES},
                    "modelo_negocio": {"type": "array", "items": {"type": "string"}},
                    "municipio": {"type": "string"},
                    "uf": {"type": "string", "description": "Sigla da UF ou ''"},
                    "cnpj": {"type": "string"},
                    "descricao": {"type": "string", "description": "Uma frase sobre o que a organização faz"},
                    "criterios": {
                        "type": "object",
                        "properties": {c: _CRITERIO for c in CRITERIOS},
                        "required": CRITERIOS,
                        "additionalProperties": False,
                    },
                    "duvida": {"type": "boolean"},
                    "justificativa": {"type": "string"},
                },
                "required": ["nome", "responsavel", "setor", "maturidade", "modelo_negocio", "municipio", "uf",
                             "cnpj", "descricao", "criterios", "duvida", "justificativa"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["organizacoes"],
    "additionalProperties": False,
}


class ClassificadorLLM:
    def __init__(self, conf: dict, pasta_cache: Path, cliente=None) -> None:
        if cliente is None:
            try:
                import anthropic
            except ImportError as erro:
                raise RuntimeError("Para o método 'llm' instale o SDK: pip install anthropic") from erro
            cliente = anthropic.Anthropic()  # lê ANTHROPIC_API_KEY do ambiente
        self.cliente = cliente
        self.modelo = conf.get("modelo", MODELO_PADRAO)
        self.esforco = conf.get("esforco", "medium")
        self.cache = pasta_cache
        self.cache.mkdir(parents=True, exist_ok=True)

    def _consultar(self, mencao: dict) -> dict:
        arquivo = self.cache / f"{mencao['id']}.json"
        if arquivo.exists():
            return json.loads(arquivo.read_text(encoding="utf-8"))
        conteudo = (f"Fonte: {mencao.get('plataforma')} - {mencao.get('url')}\n"
                    f"Data: {mencao.get('data_publicacao') or 'desconhecida'}\n"
                    f"Título: {mencao.get('titulo', '')}\n\nTexto:\n{mencao.get('texto', '')}")
        resposta = self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=16000,
            system=INSTRUCOES,
            messages=[{"role": "user", "content": conteudo}],
            output_config={"effort": self.esforco, "format": {"type": "json_schema", "schema": ESQUEMA}},
            # em caso de recusa por política, a API refaz o pedido em um modelo alternativo
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resposta.stop_reason == "refusal":
            log.warning("Menção %s recusada pelo modelo; enviada para revisão humana", mencao["id"])
            return {"recusa": True, "organizacoes": []}
        if resposta.stop_reason == "max_tokens":
            raise RuntimeError(f"Resposta truncada para a menção {mencao['id']}")
        texto = next(b.text for b in resposta.content if b.type == "text")
        dados = json.loads(texto)
        arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        return dados

    def candidatos(self, mencao: dict) -> list[Candidato]:
        dados = self._consultar(mencao)
        if dados.get("recusa"):
            return [Candidato(mencao_id=mencao["id"], nome=mencao.get("entidade", ""), duvida=True,
                              justificativa="Modelo recusou a análise; revisar manualmente.", metodo="llm")]
        saida = []
        for org in dados["organizacoes"]:
            crit = org["criterios"]
            saida.append(Candidato(
                mencao_id=mencao["id"], nome=org["nome"].strip(), responsavel=org["responsavel"],
                setor=org["setor"] or mencao.get("setor_declarado", ""), maturidade=org["maturidade"],
                modelos=org["modelo_negocio"], municipio=org["municipio"] or mencao.get("municipio", ""),
                uf=(org["uf"] or mencao.get("uf", "")).upper()[:2], cnpj=org["cnpj"] or mencao.get("cnpj", ""),
                descricao=org["descricao"],
                notas={c: crit[c]["nota"] / 2 for c in CRITERIOS},
                evidencias={c: [crit[c]["evidencia"]] if crit[c]["evidencia"] else [] for c in CRITERIOS},
                duvida=org["duvida"], justificativa=org["justificativa"], metodo="llm",
            ))
        return saida
