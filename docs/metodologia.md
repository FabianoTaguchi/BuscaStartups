# Metodologia

Este documento descreve as decisões metodológicas do BuscaStartups, como base para o texto da
qualificação. Os parâmetros citados estão em `config.toml`.

## 1. Referencial: o que é uma startup

Os cinco critérios de classificação reúnem as definições mais usadas na literatura e na legislação:

- **Blank**: startup é uma organização temporária em busca de um modelo de negócio **repetível e
  escalável**;
- **Ries**: instituição humana desenhada para criar um novo produto ou serviço sob condições de
  **extrema incerteza**;
- **Marco Legal das Startups (Lei Complementar nº 182/2021, art. 4º)**: organizações empresariais
  nascentes ou de operação recente cuja atuação se caracteriza pela **inovação aplicada ao modelo de
  negócios ou a produtos e serviços**, com até 10 anos de inscrição no CNPJ e receita bruta anual
  de até R$ 16 milhões.

Daí os critérios: inovação, modelo de negócio inovador, escalabilidade, repetibilidade e extrema
incerteza. O limite de 10 anos de CNPJ está implementado (`idade_maxima_anos`): quando o CNPJ é
conhecido e mais antigo, o critério de incerteza é anulado. A receita bruta não é pública no
cadastro de CNPJ e fica a cargo da revisão humana.

## 2. Captação

- **Unidade de coleta**: a *menção*, ou seja, um conteúdo público (notícia, página, postagem, linha de
  uma base aberta) que contém ao menos uma palavra-chave dentro do período definido.
- **Fontes**: notícias (Google Notícias, GDELT), sites (RSS/Atom e páginas por seletores CSS), redes
  sociais com acesso público por API (Mastodon, Reddit, YouTube) e bases abertas (CSV/JSON).
- **Busca**: nas plataformas com busca própria, o termo e o período vão na consulta. Nas demais, o
  conteúdo é baixado e filtrado localmente, sem acento e sem diferenciar maiúsculas.
- **Reprodutibilidade**: cada execução é gravada sem alteração em `dados/brutos/` (JSONL com data e
  hora da coleta). A base consolidada é derivada desses arquivos e deduplicada por identificador
  estável (plataforma + id original).

## 3. Classificação

1. **Candidatos**: cada menção gera candidatos (organizações) com nome, responsável, setor, maturidade,
   modelo de negócio, município/UF, CNPJ e notas por critério.
   - *Regras*: dicionários de indícios por critério. Nota 0 sem indício, 0,5 com um indício e 1 com
     dois ou mais. Os indícios encontrados são guardados como evidência.
   - *IA (opcional)*: modelo de linguagem com instruções fixas e saída em JSON validado por esquema;
     notas 0/1/2, normalizadas para 0/0,5/1, cada uma com o trecho do texto que a justifica.
2. **Consolidação**: candidatos com o mesmo CNPJ ou o mesmo nome normalizado formam uma organização.
   Cada critério recebe a maior nota observada entre as menções, e os demais campos recebem o valor
   mais frequente.
3. **Enriquecimento**: cadastro de CNPJ (dados abertos da Receita Federal, via BrasilAPI) e
   georreferenciamento pela sede do município (tabela de municípios com código IBGE).
4. **Veredito**: *startup* (pontuação ≥ 3 com inovação e incerteza não nulas), *não startup*
   (≤ 1,5) ou *revisão humana* (demais casos, nome ausente ou dúvida declarada).
5. **Revisão humana**: decisões registradas em `revisoes.csv` prevalecem sobre a classificação
   automática e ficam rastreáveis (revisor, data e observação).

## 4. Avaliação sugerida

- Montar uma **amostra de referência** (padrão-ouro): sortear menções, classificá-las manualmente,
  de preferência com dois avaliadores e medida de concordância (kappa de Cohen), e registrar o
  resultado em `revisoes.csv`.
- Medir **precisão, revocação e F1** de cada método (regras e IA) contra essa amostra, além da taxa
  de casos enviados à revisão humana. Esse é o equilíbrio entre automação e qualidade, ajustável
  pelos limiares.
- Analisar a **cobertura por fonte**: quantas startups cada fonte encontrou sozinha. Isso ajuda a
  justificar o conjunto de fontes.

## 5. Ética e proteção de dados

Coleta restrita a conteúdo público, com respeito ao `robots.txt` e aos termos das plataformas
(somente APIs públicas ou oficiais). Autores de postagens são pseudonimizados e contatos pessoais
são removidos dos textos. O responsável pela startup só é registrado quando citado publicamente no
papel de dirigente. Os dados brutos não são versionados; a publicação dos dados abertos deve passar
pela avaliação do(a) pesquisador(a) e, se a instituição exigir, pelo Comitê de Ética.
