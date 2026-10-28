"""Escrita dos dados em formatos abertos: CSV, JSON e descritor datapackage.json
(padrão Frictionless Data, https://specs.frictionlessdata.io/data-package/)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .modelo import agora_iso


def escrever_csv(registros: list[dict], campos: list[str], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", newline="", encoding="utf-8") as arq:
        escritor = csv.DictWriter(arq, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        for r in registros:
            escritor.writerow({c: "" if r.get(c) is None else r.get(c) for c in campos})


def escrever_json(registros: list[dict], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8")


def ler_jsonl(caminho: Path) -> list[dict]:
    with caminho.open(encoding="utf-8") as arq:
        return [json.loads(linha) for linha in arq if linha.strip()]


def escrever_jsonl(registros: list[dict], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8") as arq:
        for r in registros:
            arq.write(json.dumps(r, ensure_ascii=False) + "\n")


def esquema(campos: list[str], descricoes: dict[str, tuple[str, str]]) -> dict:
    return {
        "fields": [
            {"name": c, "type": descricoes.get(c, ("string", ""))[0],
             "description": descricoes.get(c, ("", ""))[1]}
            for c in campos
        ],
        "primaryKey": "id",
    }


def atualizar_datapackage(pasta: Path, projeto: dict, recurso: str, campos: list[str],
                          descricoes: dict[str, tuple[str, str]]) -> None:
    """Cria/atualiza o descritor do conjunto de dados com o recurso informado (CSV e JSON)."""
    caminho = pasta / "datapackage.json"
    pacote = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    pacote.update({
        "name": "".join(c if c.isalnum() else "-" for c in projeto.get("nome", "dados").lower()).strip("-"),
        "title": projeto.get("nome", "Dados coletados"),
        "description": projeto.get("descricao", ""),
        "licenses": [{"name": projeto.get("licenca", "CC-BY-4.0")}],
        "contributors": [{"title": projeto.get("responsavel", ""), "email": projeto.get("contato", "")}],
        "created": agora_iso(),
    })
    recursos = {r["name"]: r for r in pacote.get("resources", [])}
    for formato in ("csv", "json"):
        recursos[f"{recurso}-{formato}"] = {
            "name": f"{recurso}-{formato}", "path": f"{recurso}.{formato}",
            "format": formato, "mediatype": "text/csv" if formato == "csv" else "application/json",
            "encoding": "utf-8", "schema": esquema(campos, descricoes),
        }
    pacote["resources"] = list(recursos.values())
    caminho.write_text(json.dumps(pacote, ensure_ascii=False, indent=2), encoding="utf-8")
