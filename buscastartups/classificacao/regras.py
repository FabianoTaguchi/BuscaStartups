"""Classificador por regras: dicionários de indícios para os cinco critérios de startup
e extração heurística de nome, responsável, setor, maturidade e modelo de negócio.

É a linha de base transparente e reprodutível do projeto: cada ponto atribuído
vem acompanhado dos termos que o justificaram (coluna `evidencias`).
Todos os dicionários podem ser ampliados/substituídos no config.toml.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..modelo import CRITERIOS, normalizar

# ----------------------------------------------------------- dicionários --

INDICIOS_CRITERIOS: dict[str, list[str]] = {
    "inovacao": [
        "inovacao", "inovador", "inovadora", "tecnologia", "tecnologica", "inteligencia artificial", "ia",
        "machine learning", "aprendizado de maquina", "patente", "pesquisa e desenvolvimento", "inedit",
        "disruptiv", "deep tech", "deeptech", "biotecnologia", "blockchain", "internet das coisas", "iot",
        "algoritmo", "visao computacional", "nanotecnologia", "solucao tecnologica",
    ],
    "modelo_inovador": [
        "modelo de negocio", "saas", "marketplace", "assinatura", "freemium", "plataforma",
        "economia compartilhada", "sob demanda", "on demand", "as a service", "como servico",
        "aplicativo", "app", "conecta", "digitaliza", "intermedia",
    ],
    "escalabilidade": [
        "escala", "escalavel", "escalabilidade", "escalar", "expansao", "expandir", "crescimento",
        "cresceu", "crescer", "novos mercados", "outros estados", "todo o brasil", "todo o pais",
        "internacional", "exterior", "milhares de", "milhoes de", "usuarios",
    ],
    "repetibilidade": [
        "recorrente", "receita recorrente", "assinatura", "mensalidade", "replicavel", "replicar",
        "padronizad", "automatiza", "produto", "licenca", "licenciamento", "em serie",
        "software", "plataforma",
    ],
    "incerteza": [
        "startup", "mvp", "validacao", "validar", "pivot", "pivotar", "prototipo", "aceleradora",
        "acelerada", "aceleracao", "incubadora", "incubada", "investimento anjo", "investidor anjo",
        "venture capital", "capital de risco", "seed", "pre-seed", "rodada", "aporte", "centelha",
        "fase inicial", "em desenvolvimento", "primeiros clientes", "projeto piloto", "piloto",
    ],
}

# Indícios de organização consolidada/tradicional: anulam o critério de extrema incerteza
INDICIOS_CONSOLIDADA = [
    "multinacional", "estatal", "empresa tradicional", "fundada em 18", "fundada em 19",
    "desde 18", "desde 19", "centenaria", "rede de lojas", "rede de supermercados",
    "grupo empresarial", "holding", "concessionaria", "cooperativa", "autarquia",
]

SETORES: dict[str, list[str]] = {
    "agtech": ["agtech", "agro", "agronegocio", "agricultura", "agricola", "pecuaria", "lavoura", "safra", "soja", "rebanho"],
    "fintech": ["fintech", "pagamento", "pagamentos", "credito", "banco digital", "pix", "open finance", "meio de pagamento"],
    "healthtech": ["healthtech", "saude", "telemedicina", "hospital", "medico", "clinica", "paciente"],
    "edtech": ["edtech", "educacao", "ensino", "escola", "aprendizagem", "alunos"],
    "govtech": ["govtech", "setor publico", "prefeitura", "gestao publica", "cidadao", "licitacao"],
    "logtech": ["logtech", "logistica", "frete", "entrega", "transporte de cargas"],
    "energytech": ["energia solar", "energia renovavel", "energytech", "eficiencia energetica", "biogas"],
    "foodtech": ["foodtech", "alimentacao", "alimentos", "delivery", "restaurante"],
    "legaltech": ["legaltech", "juridico", "advocacia", "lawtech"],
    "retailtech": ["varejo", "retailtech", "e-commerce", "ecommerce", "loja virtual"],
    "proptech": ["proptech", "imobiliario", "imoveis", "construtech", "construcao civil"],
    "hrtech": ["hrtech", "recursos humanos", "recrutamento", "rh"],
    "cleantech": ["cleantech", "sustentabilidade", "reciclagem", "carbono", "residuos", "meio ambiente"],
    "mobilidade": ["mobilidade", "transporte urbano", "carro eletrico", "patinete"],
}

MATURIDADE: dict[str, list[str]] = {  # do estágio mais avançado para o menos avançado
    "escala": ["serie a", "serie b", "serie c", "series a", "expansao internacional", "internacionalizacao",
               "unicornio", "ipo", "milhoes de usuarios", "milhoes de clientes"],
    "operacao": ["seed", "faturamento", "fatura", "receita", "clientes ativos", "tracao", "contratos",
                 "cresceu", "crescimento de"],
    "validacao": ["mvp", "validacao", "validar", "projeto piloto", "piloto", "primeiros clientes", "incubada",
                  "acelerada", "programa de aceleracao", "versao beta"],
    "ideacao": ["ideia", "ideacao", "prototipo", "pre-seed", "pre-operacional", "centelha", "concepcao", "hackathon"],
}

MODELOS_NEGOCIO: dict[str, list[str]] = {
    "SaaS": ["saas", "software como servico", "software as a service"],
    "Marketplace": ["marketplace", "plataforma que conecta", "conecta produtores", "conecta compradores", "intermedia"],
    "Assinatura": ["assinatura", "mensalidade", "plano mensal", "receita recorrente"],
    "B2B": ["b2b", "para empresas", "clientes corporativos", "industrias"],
    "B2C": ["b2c", "consumidor final", "para consumidores"],
    "B2G": ["b2g", "setor publico", "prefeituras", "orgaos publicos"],
    "Aplicativo": ["aplicativo", "app"],
    "Hardware/IoT": ["hardware", "iot", "internet das coisas", "sensor", "sensores", "drone", "drones", "dispositivo"],
    "Licenciamento": ["licenciamento", "royalties", "patente"],
    "E-commerce": ["e-commerce", "ecommerce", "loja virtual", "venda online"],
}

NOMES_IGNORADOS = {
    "brasil", "mato grosso", "mato grosso do sul", "sao paulo", "rio de janeiro", "cuiaba", "sebrae", "governo",
    "estado", "programa", "edital", "startup", "startups", "ceo", "uma", "um", "a", "o", "as", "os", "de", "da",
    "do", "em", "no", "na", "que", "para", "com", "secitec", "fapemat", "finep", "inovativa", "centelha",
    # instituições de fomento/apoio frequentemente citadas junto a startups
    "bndes", "embrapa", "senai", "sesi", "cnpq", "capes", "mcti", "abstartups", "anprotec", "ufmt", "ifmt",
    "unemat", "fiemt", "google", "microsoft", "amazon", "meta",
}

# --------------------------------------------------------------- utilidades --


def compilar(termos: list[str]) -> list[tuple[str, re.Pattern]]:
    """Termos curtos exigem palavra inteira; termos longos aceitam sufixos (inedit -> inédita)."""
    pads = []
    for t in termos:
        n = normalizar(t)
        fim = r"\b" if len(n) <= 4 else ""
        pads.append((t, re.compile(rf"(?<![\w-]){re.escape(n)}{fim}")))
    return pads


def encontrados(pads: list[tuple[str, re.Pattern]], alvo_normalizado: str) -> list[str]:
    return [t for t, p in pads if p.search(alvo_normalizado)]


def nota(qtd_indicios: int) -> float:
    """0 indício -> 0; 1 indício -> 0,5; 2 ou mais -> 1."""
    return 0.0 if qtd_indicios == 0 else 0.5 if qtd_indicios == 1 else 1.0


# ------------------------------------------------------- extração de nomes --

_MAI = "A-ZÁÉÍÓÚÂÊÔÃÕÇ"
_MIN = "a-záéíóúâêôãõç"
_PALAVRA_NOME = rf"[{_MAI}0-9][\w&.\-]*"
_NOME = rf"{_PALAVRA_NOME}(?:\s+{_PALAVRA_NOME}){{0,2}}"
_ARTIGOS = r"(?:A|O|As|Os|Uma|Um|Na|No|Da|Do|Pela|Pelo|Em|Com|E)\s+"
RE_NOME = [
    # "a startup (cuiabana) Agrosmart", "startup de tecnologia Xpto"
    re.compile(rf"\b[Ss]tartups?\s+(?:[{_MIN}\-]+\s+){{0,3}}({_NOME})"),
    # "A Agrosmart, startup que...", "Xpto, uma startup de..."
    re.compile(rf"(?:^|[.!?]\s+|\s)(?:{_ARTIGOS})?({_NOME}),\s+(?:uma\s+|a\s+)?startup"),
    # "Xpto é uma startup"
    re.compile(rf"(?:{_ARTIGOS})?({_NOME})\s+(?:é|e)\s+uma\s+startup"),
]
_PESSOA = rf"[{_MAI}][{_MIN}]+(?:\s+(?:d[aeo]s?\s+)?[{_MAI}][{_MIN}]+){{1,3}}"
_CARGO = (r"(?:CEO|[Ff]undador(?:a)?|[Cc]o-?[Ff]undador(?:a)?|[Ss][óo]ci[oa](?:-fundador(?:a)?)?|"
          r"[Dd]iretor(?:a)?(?:-executiv[oa])?|[Pp]residente|[Ii]dealizador(?:a)?|[Cc]riador(?:a)?)")
RE_RESPONSAVEL = [
    re.compile(rf"({_PESSOA}),\s+(?:um\s+d?os\s+|uma\s+das\s+)?({_CARGO})"),
    re.compile(rf"({_CARGO})(?:\s+e\s+{_CARGO})?(?:\s+d[aoe]\s+(?:startup\s+)?{_NOME})?,?\s+({_PESSOA})"),
]


def limpar_nome(nome: str) -> str:
    nome = re.sub(rf"^(?:{_ARTIGOS})+", "", nome.strip()).strip(" .,-")
    return nome


def extrair_nomes(texto: str, ignorados: set[str]) -> list[str]:
    nomes = []
    for rx in RE_NOME:
        for m in rx.finditer(texto):
            nome = limpar_nome(m.group(1))
            if len(nome) >= 2 and normalizar(nome) not in ignorados:
                nomes.append(nome)
    return nomes


_INTRODUTORIAS = re.compile(r"^(?:Segundo|Conforme|Para|Diz|Disse|Afirma|Explica|Destaca|Com|De|Em|Por)\s+")


def extrair_responsavel(texto: str) -> str:
    for rx in RE_RESPONSAVEL:
        if m := rx.search(texto):
            pessoa, cargo = (m.group(1), m.group(2)) if rx is RE_RESPONSAVEL[0] else (m.group(2), m.group(1))
            pessoa = _INTRODUTORIAS.sub("", pessoa)
            if " " in pessoa:  # exige nome e sobrenome
                return f"{pessoa} ({cargo if cargo == 'CEO' else cargo.lower()})"
    return ""


def trecho_com(nome: str, texto: str, tamanho: int = 280) -> str:
    """Primeira frase que cita o nome (ou o começo do texto)."""
    for frase in re.split(r"(?<=[.!?])\s+", texto):
        if nome and nome in frase:
            return frase[:tamanho]
    return texto[:tamanho]


# ------------------------------------------------------------ classificador --

@dataclass
class Candidato:
    """Uma organização candidata identificada em uma menção."""

    mencao_id: str
    nome: str = ""
    responsavel: str = ""
    setor: str = ""
    maturidade: str = "desconhecida"
    modelos: list[str] = field(default_factory=list)
    municipio: str = ""
    uf: str = ""
    cnpj: str = ""
    descricao: str = ""
    notas: dict[str, float] = field(default_factory=dict)
    evidencias: dict[str, list[str]] = field(default_factory=dict)
    consolidada: bool = False
    duvida: bool = False
    justificativa: str = ""
    metodo: str = "regras"


class ClassificadorRegras:
    def __init__(self, conf: dict | None = None) -> None:
        conf = conf or {}

        def mesclar(padrao: dict, chave: str) -> dict:
            return {**padrao, **conf.get(chave, {})}

        self.criterios = {c: compilar(t) for c, t in mesclar(INDICIOS_CRITERIOS, "criterios").items()}
        self.consolidada = compilar(conf.get("indicios_consolidada", INDICIOS_CONSOLIDADA))
        self.setores = {s: compilar(t) for s, t in mesclar(SETORES, "setores").items()}
        self.maturidade = {m: compilar(t) for m, t in mesclar(MATURIDADE, "maturidade").items()}
        self.modelos = {m: compilar(t) for m, t in mesclar(MODELOS_NEGOCIO, "modelos_negocio").items()}
        self.ignorados = NOMES_IGNORADOS | {normalizar(n) for n in conf.get("nomes_ignorados", [])}

    def avaliar(self, texto: str) -> tuple[dict[str, float], dict[str, list[str]], bool]:
        alvo = normalizar(texto)
        evid = {c: encontrados(p, alvo) for c, p in self.criterios.items()}
        notas = {c: nota(len(evid[c])) for c in CRITERIOS}
        consolidada = bool(encontrados(self.consolidada, alvo))
        if consolidada:
            evid["incerteza"] = evid["incerteza"] + ["(anulado: indícios de empresa consolidada)"]
            notas["incerteza"] = 0.0
        return notas, evid, consolidada

    def setor(self, texto: str) -> str:
        alvo = normalizar(texto)
        contagem = {s: len(encontrados(p, alvo)) for s, p in self.setores.items()}
        melhor = max(contagem, key=contagem.get, default="")
        return melhor if contagem.get(melhor) else ""

    def estagio(self, texto: str) -> str:
        alvo = normalizar(texto)
        return next((m for m, p in self.maturidade.items() if encontrados(p, alvo)), "desconhecida")

    def modelos_negocio(self, texto: str) -> list[str]:
        alvo = normalizar(texto)
        return [m for m, p in self.modelos.items() if encontrados(p, alvo)]

    def candidatos(self, mencao: dict) -> list[Candidato]:
        texto = f"{mencao.get('titulo', '')}. {mencao.get('texto', '')}".strip(". ")
        notas, evid, consolidada = self.avaliar(texto)
        nomes = [mencao["entidade"]] if mencao.get("entidade") else extrair_nomes(texto, self.ignorados)
        nome = Counter(nomes).most_common(1)[0][0] if nomes else ""
        return [Candidato(
            mencao_id=mencao["id"], nome=nome, responsavel=extrair_responsavel(texto),
            setor=mencao.get("setor_declarado") or self.setor(texto), maturidade=self.estagio(texto),
            modelos=self.modelos_negocio(texto), municipio=mencao.get("municipio", ""),
            uf=mencao.get("uf", ""), cnpj=mencao.get("cnpj", ""), descricao=trecho_com(nome, texto),
            notas=notas, evidencias=evid, consolidada=consolidada,
        )]
