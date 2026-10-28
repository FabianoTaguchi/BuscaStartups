"""Bases de dados abertas em CSV ou JSON (arquivo local ou URL).

Exemplos: listas de startups apoiadas em editais públicos, programas de aceleração,
portais de dados abertos (dados.gov.br, portais estaduais), exportações de mapeamentos.
O mapeamento `colunas` liga os campos padrão aos nomes das colunas do arquivo.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Iterator

from ..modelo import Mencao, iso_de_texto, limpar_espacos
from .base import Fonte

log = logging.getLogger(__name__)
CAMPOS = ["nome", "cnpj", "municipio", "uf", "setor", "descricao", "url", "data", "id"]


class FonteBaseAberta(Fonte):
    tipo = "base_aberta"

    def ler(self) -> list[dict]:
        origem = self.config["caminho"]
        if origem.startswith(("http://", "https://")):
            resp = self.ctx.cliente.get(origem, respeitar_robots=False)
            resp.encoding = self.config.get("encoding", resp.encoding or "utf-8")
            conteudo = resp.text
        else:
            conteudo = Path(origem).read_text(encoding=self.config.get("encoding", "utf-8-sig"))
        if self.config.get("formato", Path(origem.split("?")[0]).suffix.lstrip(".")) == "json":
            dados = json.loads(conteudo)
            if chave := self.config.get("chave_lista"):  # ex.: {"result": {"records": [...]}}
                for parte in chave.split("."):
                    dados = dados[parte]
            return dados
        return list(csv.DictReader(io.StringIO(conteudo), delimiter=self.config.get("separador", ",")))

    def coletar(self) -> Iterator[Mencao]:
        colunas = self.config.get("colunas", {})
        valor = lambda linha, campo: limpar_espacos(str(linha.get(colunas.get(campo, campo), "") or ""))  # noqa: E731
        try:
            linhas = self.ler()
        except Exception as erro:  # noqa: BLE001
            log.error("[%s] falha ao ler %s: %s", self.nome, self.config.get("caminho"), erro)
            return
        for i, linha in enumerate(linhas[: self.max]):
            nome = valor(linha, "nome")
            if not nome:
                continue
            data = iso_de_texto(valor(linha, "data"))
            if not self.ctx.periodo.contem(data):
                continue
            yield Mencao(
                plataforma=self.tipo, fonte=self.nome,
                id_original=valor(linha, "id") or valor(linha, "cnpj") or f"{nome}#{i}",
                url=valor(linha, "url") or self.config.get("url_referencia", self.config["caminho"]),
                titulo=nome, texto=valor(linha, "descricao"), data_publicacao=data,
                entidade=nome, cnpj=valor(linha, "cnpj"), municipio=valor(linha, "municipio"),
                uf=valor(linha, "uf").upper(), setor_declarado=valor(linha, "setor"),
            )
