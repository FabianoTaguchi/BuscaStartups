"""Esquemas de dados e utilidades comuns.

Dois níveis de dado:
  * Mencao  - um conteúdo captado (notícia, página, postagem, linha de base aberta);
  * Startup - uma organização candidata, consolidada a partir de uma ou mais menções
              e avaliada pelos critérios de classificação.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timezone


# ------------------------------------------------------------------ menção --

@dataclass
class Mencao:
    plataforma: str              # google_news | gdelt | rss | web | mastodon | reddit | youtube | base_aberta
    fonte: str                   # nome da fonte definido no config.toml
    id_original: str             # identificador na plataforma de origem
    url: str
    titulo: str = ""
    texto: str = ""
    autor_hash: str = ""         # autor pseudonimizado (LGPD) - nunca o nome real
    data_publicacao: str = ""    # ISO 8601 em UTC
    data_coleta: str = field(default_factory=lambda: agora_iso())
    idioma: str = ""
    termo_busca: str = ""
    curtidas: int | None = None
    comentarios: int | None = None
    compartilhamentos: int | None = None
    # preenchidos quando a própria fonte já informa a organização (ex.: bases abertas)
    entidade: str = ""
    cnpj: str = ""
    municipio: str = ""
    uf: str = ""
    setor_declarado: str = ""
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = hash_curto(f"{self.plataforma}|{self.id_original or self.url}")

    def como_dict(self) -> dict:
        return asdict(self)


CAMPOS_MENCAO = ["id"] + [f.name for f in fields(Mencao) if f.name != "id"]

DESCRICAO_MENCAO = {
    "id": ("string", "Identificador estável da menção (hash de plataforma + id original)."),
    "plataforma": ("string", "Tipo de fonte: google_news, gdelt, rss, web, mastodon, reddit, youtube ou base_aberta."),
    "fonte": ("string", "Nome da fonte conforme o config.toml."),
    "id_original": ("string", "Identificador do conteúdo na plataforma de origem."),
    "url": ("string", "Endereço público do conteúdo."),
    "titulo": ("string", "Título (quando existe)."),
    "texto": ("string", "Texto limpo, com e-mails/@menções/telefones anonimizados quando configurado."),
    "autor_hash": ("string", "Autor pseudonimizado via HMAC-SHA256 com sal secreto."),
    "data_publicacao": ("datetime", "Data de publicação, ISO 8601 (UTC)."),
    "data_coleta": ("datetime", "Momento da captação, ISO 8601 (UTC)."),
    "idioma": ("string", "Idioma informado pela plataforma."),
    "termo_busca": ("string", "Palavra-chave que levou à captação."),
    "curtidas": ("integer", "Curtidas/favoritos/pontuação, quando disponível."),
    "comentarios": ("integer", "Comentários/respostas, quando disponível."),
    "compartilhamentos": ("integer", "Compartilhamentos/reblogs, quando disponível."),
    "entidade": ("string", "Nome da organização, quando informado pela própria fonte."),
    "cnpj": ("string", "CNPJ informado ou encontrado no texto."),
    "municipio": ("string", "Município informado pela fonte."),
    "uf": ("string", "UF informada pela fonte."),
    "setor_declarado": ("string", "Setor informado pela fonte."),
}


# ----------------------------------------------------------------- startup --

CRITERIOS = ["inovacao", "modelo_inovador", "escalabilidade", "repetibilidade", "incerteza"]
NOMES_CRITERIOS = {
    "inovacao": "Inovação",
    "modelo_inovador": "Modelo de negócio inovador",
    "escalabilidade": "Escalabilidade",
    "repetibilidade": "Repetibilidade",
    "incerteza": "Extrema incerteza",
}
MATURIDADES = ["ideacao", "validacao", "operacao", "escala", "desconhecida"]

STARTUP = "startup"
NAO_STARTUP = "nao_startup"
REVISAO = "revisao_humana"


@dataclass
class Startup:
    nome: str = ""
    responsavel: str = ""
    setor: str = ""
    maturidade: str = "desconhecida"
    modelo_negocio: str = ""
    municipio: str = ""
    uf: str = ""
    latitude: float | None = None
    longitude: float | None = None
    cnpj: str = ""
    descricao: str = ""
    crit_inovacao: float = 0.0
    crit_modelo_inovador: float = 0.0
    crit_escalabilidade: float = 0.0
    crit_repetibilidade: float = 0.0
    crit_incerteza: float = 0.0
    pontuacao: float = 0.0
    veredito: str = REVISAO
    justificativa: str = ""
    evidencias: str = ""
    metodo: str = ""
    n_mencoes: int = 0
    url_fonte: str = ""
    fontes: str = ""
    primeira_mencao: str = ""
    ultima_mencao: str = ""
    ids_mencoes: str = ""
    id: str = ""

    def como_dict(self) -> dict:
        return asdict(self)


CAMPOS_STARTUP = ["id"] + [f.name for f in fields(Startup) if f.name != "id"]

DESCRICAO_STARTUP = {
    "id": ("string", "Identificador estável da startup (hash do CNPJ ou do nome normalizado)."),
    "nome": ("string", "Nome da organização."),
    "responsavel": ("string", "Fundador(a)/CEO/responsável citado publicamente."),
    "setor": ("string", "Setor de atuação (agtech, fintech, healthtech...)."),
    "maturidade": ("string", "Estágio: ideacao, validacao, operacao, escala ou desconhecida."),
    "modelo_negocio": ("string", "Modelos de negócio identificados (SaaS, marketplace, B2B...), separados por '|'."),
    "municipio": ("string", "Município da sede."),
    "uf": ("string", "UF da sede."),
    "latitude": ("number", "Latitude da sede municipal (georreferenciamento por município)."),
    "longitude": ("number", "Longitude da sede municipal."),
    "cnpj": ("string", "CNPJ, quando identificado."),
    "descricao": ("string", "Trecho descritivo extraído das menções."),
    "crit_inovacao": ("number", "Critério inovação: 0, 0.5 ou 1."),
    "crit_modelo_inovador": ("number", "Critério modelo de negócio inovador: 0, 0.5 ou 1."),
    "crit_escalabilidade": ("number", "Critério escalabilidade: 0, 0.5 ou 1."),
    "crit_repetibilidade": ("number", "Critério repetibilidade: 0, 0.5 ou 1."),
    "crit_incerteza": ("number", "Critério extrema incerteza: 0, 0.5 ou 1."),
    "pontuacao": ("number", "Soma dos cinco critérios (0 a 5)."),
    "veredito": ("string", "startup, nao_startup ou revisao_humana."),
    "justificativa": ("string", "Motivo do veredito."),
    "evidencias": ("string", "Trechos/termos que sustentam cada critério."),
    "metodo": ("string", "Método da classificação: regras, llm e/ou revisao."),
    "n_mencoes": ("integer", "Número de menções consolidadas."),
    "url_fonte": ("string", "Link da fonte principal (mais recente)."),
    "fontes": ("string", "Todos os links de fontes, separados por ' | '."),
    "primeira_mencao": ("datetime", "Data da menção mais antiga."),
    "ultima_mencao": ("datetime", "Data da menção mais recente."),
    "ids_mencoes": ("string", "Ids das menções de origem, separados por '|'."),
}


# ----------------------------------------------------------------- período --

@dataclass
class Periodo:
    inicio: date | None = None
    fim: date | None = None

    @classmethod
    def de_texto(cls, inicio: str | None, fim: str | None) -> "Periodo":
        conv = lambda t: date.fromisoformat(str(t)) if t else None  # noqa: E731
        return cls(conv(inicio), conv(fim))

    def contem(self, data_iso: str) -> bool:
        """Conteúdos sem data são mantidos (não há como excluí-los com segurança)."""
        if not data_iso:
            return True
        dia = datetime.fromisoformat(data_iso).date()
        return (self.inicio is None or dia >= self.inicio) and (self.fim is None or dia <= self.fim)

    def anterior_ao_inicio(self, data_iso: str) -> bool:
        return bool(data_iso and self.inicio and datetime.fromisoformat(data_iso).date() < self.inicio)

    def __str__(self) -> str:
        return f"{self.inicio or '...'} a {self.fim or '...'}"


# --------------------------------------------------------------- utilidades --

def agora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def para_iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def iso_de_texto(texto: str | None) -> str:
    """Converte '2026-10-27T15:30:00.000Z' e variações ISO para ISO 8601 UTC."""
    if not texto:
        return ""
    try:
        return para_iso(datetime.fromisoformat(texto.strip().replace("Z", "+00:00")))
    except ValueError:
        return ""


def hash_curto(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16]


def pseudonimizar(valor: str, sal: str) -> str:
    """Substitui um identificador pessoal por um código irreversível e consistente."""
    if not valor:
        return ""
    return hmac.new(sal.encode("utf-8"), valor.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_MENCAO = re.compile(r"(?<![\w@])@[\w.]+(?:@[\w.-]+)?")
_RE_TELEFONE = re.compile(r"(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[-\s]?\d{4}\b")
_RE_ESPACOS = re.compile(r"\s+")
RE_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")


def anonimizar_texto(texto: str) -> str:
    """Remove e-mails, @menções a perfis e telefones do texto livre (CNPJs são preservados)."""
    cnpjs = RE_CNPJ.findall(texto)
    for i, c in enumerate(cnpjs):
        texto = texto.replace(c, f"\0{i}\0")
    texto = _RE_EMAIL.sub("[email]", texto)
    texto = _RE_MENCAO.sub("@[usuario]", texto)
    texto = _RE_TELEFONE.sub("[telefone]", texto)
    for i, c in enumerate(cnpjs):
        texto = texto.replace(f"\0{i}\0", c)
    return texto


def limpar_espacos(texto: str) -> str:
    return _RE_ESPACOS.sub(" ", texto or "").strip()


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparar termos de forma robusta."""
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def so_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")
