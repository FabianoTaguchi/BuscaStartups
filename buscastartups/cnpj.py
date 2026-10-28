"""Consulta ao Cadastro Nacional da Pessoa Jurídica (dados abertos da Receita Federal)
pela BrasilAPI (https://brasilapi.com.br/docs#tag/CNPJ). Resultados ficam em cache."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

from .modelo import so_digitos

log = logging.getLogger(__name__)
URL = "https://brasilapi.com.br/api/cnpj/v1/{}"


class ConsultaCNPJ:
    def __init__(self, cliente, pasta_cache: Path) -> None:
        self.cliente = cliente
        self.cache = pasta_cache
        self.cache.mkdir(parents=True, exist_ok=True)

    def consultar(self, cnpj: str) -> dict | None:
        digitos = so_digitos(cnpj)
        if len(digitos) != 14:
            return None
        arquivo = self.cache / f"{digitos}.json"
        if arquivo.exists():
            return json.loads(arquivo.read_text(encoding="utf-8"))
        try:
            dados = self.cliente.get(URL.format(digitos), respeitar_robots=False).json()
        except Exception as erro:  # noqa: BLE001
            log.warning("CNPJ %s não consultado: %s", digitos, erro)
            return None
        arquivo.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        return dados


def resumo(dados: dict) -> dict:
    """Extrai do cadastro os campos usados no enriquecimento."""
    socios = dados.get("qsa") or []
    admin = next((s for s in socios if "administrador" in (s.get("qualificacao_socio") or "").lower()), None)
    socio = admin or (socios[0] if socios else None)
    idade = None
    if inicio := dados.get("data_inicio_atividade"):
        try:
            idade = (date.today() - date.fromisoformat(inicio)).days / 365.25
        except ValueError:
            pass
    return {
        "nome": (dados.get("nome_fantasia") or dados.get("razao_social") or "").title(),
        "responsavel": f"{socio['nome_socio'].title()} ({socio.get('qualificacao_socio', 'sócio').lower()})" if socio else "",
        "setor_cnae": dados.get("cnae_fiscal_descricao") or "",
        "municipio": (dados.get("municipio") or "").title(),
        "uf": dados.get("uf") or "",
        "idade_anos": idade,
        "situacao": dados.get("descricao_situacao_cadastral") or "",
    }
