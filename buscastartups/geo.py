"""Georreferenciamento por município.

Usa a tabela de municípios brasileiros com código IBGE e coordenadas da sede
municipal (https://github.com/kelvins/municipios-brasileiros, dados abertos),
baixada uma única vez e guardada em cache. O ponto no mapa representa a sede do
município, não o endereço da empresa (precisão adequada a mapas regionais e
sem expor endereços).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from pathlib import Path

from .modelo import normalizar

log = logging.getLogger(__name__)

URL_MUNICIPIOS = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"

UF_POR_CODIGO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
    "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
    "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
    "51": "MT", "52": "GO", "53": "DF",
}
ESTADOS = {  # grafia oficial (comparada no texto original); nomes longos primeiro
    "Mato Grosso do Sul": "MS", "Rio Grande do Norte": "RN", "Rio Grande do Sul": "RS", "Mato Grosso": "MT",
    "Espírito Santo": "ES", "Santa Catarina": "SC", "Minas Gerais": "MG", "Distrito Federal": "DF",
    "Pernambuco": "PE", "Amazonas": "AM", "Maranhão": "MA", "Rondônia": "RO", "Tocantins": "TO",
    "Paraíba": "PB", "Alagoas": "AL", "Sergipe": "SE", "Paraná": "PR", "Roraima": "RR", "Amapá": "AP",
    "Goiás": "GO", "Bahia": "BA", "Ceará": "CE", "Piauí": "PI", "Acre": "AC", "Pará": "PA",
}
# gentílicos usados pela imprensa: cidade (municipio, uf) ou só estado (None, uf)
GENTILICOS = {
    "cuiabana": ("Cuiabá", "MT"), "cuiabano": ("Cuiabá", "MT"), "varzea-grandense": ("Várzea Grande", "MT"),
    "rondonopolitana": ("Rondonópolis", "MT"), "sinopense": ("Sinop", "MT"),
    "paulistana": ("São Paulo", "SP"), "paulistano": ("São Paulo", "SP"), "carioca": ("Rio de Janeiro", "RJ"),
    "brasiliense": ("Brasília", "DF"), "campo-grandense": ("Campo Grande", "MS"), "goianiense": ("Goiânia", "GO"),
    "curitibana": ("Curitiba", "PR"), "florianopolitana": ("Florianópolis", "SC"),
    "porto-alegrense": ("Porto Alegre", "RS"), "recifense": ("Recife", "PE"),
    "belo-horizontina": ("Belo Horizonte", "MG"), "manauara": ("Manaus", "AM"),
    "mato-grossense": (None, "MT"), "sul-mato-grossense": (None, "MS"), "paulista": (None, "SP"),
    "mineira": (None, "MG"), "gaucha": (None, "RS"), "catarinense": (None, "SC"), "paranaense": (None, "PR"),
    "baiana": (None, "BA"), "pernambucana": (None, "PE"), "cearense": (None, "CE"), "goiana": (None, "GO"),
    "capixaba": (None, "ES"), "paraense": (None, "PA"), "amazonense": (None, "AM"),
}
_UFS = "|".join(sorted(set(UF_POR_CODIGO.values())))
RE_CIDADE_UF = re.compile(rf"([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\wÀ-ú'’\- ]{{1,40}}?)\s*(?:\(|/|-|–|,)\s*({_UFS})\b")


def carregar_municipios(pasta_cache: Path, cliente=None, url: str = URL_MUNICIPIOS) -> list[dict]:
    arquivo = pasta_cache / "municipios.csv"
    if not arquivo.exists():
        if cliente is None:
            raise FileNotFoundError(arquivo)
        log.info("Baixando tabela de municípios (uma única vez): %s", url)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(cliente.get(url, respeitar_robots=False).text, encoding="utf-8")
    return list(csv.DictReader(io.StringIO(arquivo.read_text(encoding="utf-8"))))


class Geocodificador:
    def __init__(self, municipios: list[dict], ufs_foco: list[str] | None = None) -> None:
        self.por_chave: dict[tuple[str, str], dict] = {}
        self.por_nome: dict[str, list[dict]] = {}
        self.capitais: list[dict] = []
        for m in municipios:
            item = {"nome": m["nome"], "uf": UF_POR_CODIGO.get(str(m["codigo_uf"]), ""),
                    "lat": float(m["latitude"]), "lon": float(m["longitude"]),
                    "capital": str(m.get("capital", "0")) in ("1", "True", "true")}
            chave = normalizar(m["nome"])
            self.por_chave[(chave, item["uf"])] = item
            self.por_nome.setdefault(chave, []).append(item)
            if item["capital"]:
                self.capitais.append(item)
        self.ufs_foco = [u.upper() for u in (ufs_foco or [])]
        # municípios das UFs de foco podem ser reconhecidos só pelo nome no texto
        self.foco = [i for lst in self.por_nome.values() for i in lst
                     if i["uf"] in self.ufs_foco and len(i["nome"]) >= 5]

    def coordenadas(self, municipio: str, uf: str = "") -> dict | None:
        chave = normalizar(municipio)
        if uf:
            return self.por_chave.get((chave, uf.upper()))
        opcoes = self.por_nome.get(chave, [])
        if len(opcoes) == 1:
            return opcoes[0]
        return next((o for o in opcoes if o["uf"] in self.ufs_foco), None)

    def localizar(self, texto: str) -> tuple[str, str]:
        """Procura a localização no texto; devolve (municipio, uf) ou ('', uf) ou ('', '')."""
        for m in RE_CIDADE_UF.finditer(texto):  # "Sinop (MT)", "Cuiabá/MT", "Cuiabá - MT"
            palavras = m.group(1).strip().split()
            for i in range(len(palavras)):  # tenta o sufixo mais longo que seja município
                item = self.por_chave.get((normalizar(" ".join(palavras[i:])), m.group(2)))
                if item:
                    return item["nome"], item["uf"]
        alvo = normalizar(texto)
        for gentilico, (cidade, uf) in GENTILICOS.items():
            if re.search(rf"(?<![\w-]){gentilico}(?![\w-])", alvo):
                return cidade or "", uf
        for item in self.capitais + self.foco:
            if re.search(rf"\b{re.escape(item['nome'])}\b", texto):
                return item["nome"], item["uf"]
        for estado, uf in ESTADOS.items():
            if re.search(rf"\b{estado}\b", texto):
                return "", uf
        return "", ""
