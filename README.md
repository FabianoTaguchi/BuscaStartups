# BuscaStartups

Ferramenta de pesquisa para **mapear startups a partir de dados públicos da internet**:
notícias, sites, redes sociais e bases de dados abertas. Os dados são entregues em
**formatos abertos (CSV e JSON, com dicionário de dados)**, classificados pela pergunta
**"É startup?"** e exibidos em um **painel com georreferenciamento**.

O projeto tem três funções bem definidas:

| # | Função | Saída |
|---|--------|-------|
| 1 | **Captação ativa**: busca por palavras-chave e período em notícias, sites, redes sociais e bases abertas | `dados/abertos/mencoes.csv` / `.json` |
| 2 | **Classificação "É startup?"**: inovação, modelo de negócio inovador, escalabilidade, repetibilidade e extrema incerteza; casos duvidosos vão para revisão humana | `dados/abertos/startups.csv` / `.json`, `dados/revisao/pendentes.csv` |
| 3 | **Painel**: nome, responsável, setor, maturidade, modelo de negócio, link da fonte e mapa | `http://127.0.0.1:8000/dashboard/` |

E dois modos de uso, que podem funcionar juntos:

- **Automático**: repete a busca sozinho a cada `intervalo_horas`, com os termos do `config.toml`,
  cobrindo o período desde a última execução até hoje;
- **Manual**: você informa as palavras-chave, o período e as fontes (no painel ou na linha de
  comando), e o painel mostra o resultado daquela busca.

Cada busca, manual ou automática, executa captação + classificação, e o resultado vai para a mesma base.

```
                  1. CAPTAÇÃO                        2. CLASSIFICAÇÃO                         3. PAINEL
 ┌────────────────────────────────┐      ┌───────────────────────────────────┐      ┌──────────────────────┐
 │ Google Notícias  GDELT  RSS    │      │ candidatos por menção             │      │ tabela + filtros     │
 │ páginas web      Mastodon      │ ───► │  (regras ou IA) → 5 critérios     │ ───► │ mapa por município   │
 │ Reddit  YouTube  bases abertas │      │ consolidação por CNPJ/nome        │      │ setor · maturidade   │
 │ palavras-chave + período       │      │ + CNPJ (Receita) + município/IBGE │      │ revisão humana       │
 └────────────────────────────────┘      │ veredito: startup / não / revisão │      └──────────────────────┘
          mencoes.csv/json               └───────────────────────────────────┘
                                                  startups.csv/json
```

## Instalação

Requer Python 3.11 ou superior.

```bash
git clone https://github.com/FabianoTaguchi/BuscaStartups.git
```

```bash
cd BuscaStartups
```

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

Variáveis de ambiente (opcionais, mas recomendadas):

```bash
export BUSCASTARTUPS_SAL="uma-frase-secreta-longa"   # pseudonimização de autores de postagens
export YOUTUBE_API_KEY="..."                         # ativa a fonte YouTube
export ANTHROPIC_API_KEY="..."                       # ativa a classificação com IA (método llm)
```

## Uso

Tudo é configurado em [`config.toml`](config.toml): termos, período, fontes, critérios, limiares e agenda.

### Início rápido

```bash
python -m buscastartups iniciar
```

Abra `http://127.0.0.1:8000/dashboard/`. O mesmo comando:

- liga a **busca automática** (seção `[automatico]` do `config.toml`). Na primeira execução, ela busca
  os últimos `janela_inicial_dias` dias e depois se repete a cada `intervalo_horas`;
- mostra no topo do painel o formulário de **busca manual**: palavras-chave, datas inicial e final,
  fontes e método de classificação. O andamento aparece ao vivo e, no fim, o painel filtra o
  resultado daquela busca (o botão "mostrar tudo" volta à base completa).

Para só a busca manual, sem o modo automático:

```bash
python -m buscastartups iniciar --sem-automatico
```

O servidor atende apenas a própria máquina (`127.0.0.1`) e só uma busca roda por vez. O histórico
fica em `dados/estado.json`.

### Busca manual pela linha de comando

```bash
python -m buscastartups buscar --termos "startup,agtech,aceleradora" --de 2026-01-01 --ate 2026-06-30
```

`--fontes google_news,gdelt` limita as fontes (por nome ou tipo); `--metodo llm` usa a IA. Sem
`--termos`/`--de`/`--ate`, valem os do `config.toml`.

### Busca automática sem o painel

Para deixar o processo rodando em segundo plano:

```bash
python -m buscastartups automatico
```

Ou, para que o sistema operacional agende uma execução por vez, use `--uma-vez` no **cron**
(Linux/macOS) ou no **Agendador de Tarefas** (Windows). Exemplo de cron, todo dia às 6h:

```bash
0 6 * * * cd /caminho/BuscaStartups && .venv/bin/python -m buscastartups automatico --uma-vez
```

### 1. Captação ativa

Os comandos `buscar` e `iniciar` já fazem a captação. Para executar só esta etapa:

```bash
python -m buscastartups captar --termos "startup,agtech" --de 2026-01-01 --ate 2026-06-30
```

Fontes disponíveis (tipo em `[[fontes]]`):

| Tipo | Categoria | Busca por termo | Período | Observação |
|------|-----------|-----------------|---------|------------|
| `google_news` | notícias | sim (no buscador) | sim (`after:`/`before:`) | feed RSS público de pesquisa; `complemento` restringe a região |
| `gdelt` | base aberta de notícias | sim | sim | [GDELT DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/); filtrável por país/idioma |
| `rss` | sites | filtro local | filtro local | qualquer feed RSS/Atom (portais, blogs, ecossistemas, órgãos públicos) |
| `web` | sites | filtro local | filtro local | páginas comuns, extraídas por seletores CSS |
| `base_aberta` | bases abertas | — | filtro local | CSV/JSON local ou por URL (editais, programas, portais de dados abertos) |
| `mastodon` | rede social | hashtag | sim | API pública, sem login |
| `reddit` | rede social | sim | sim | endpoints públicos `.json` |
| `youtube` | rede social | sim | sim | YouTube Data API v3 (chave gratuita) |

Na busca manual, as palavras-chave digitadas valem para todas as fontes, substituindo os termos e as
hashtags definidos em cada fonte. Para incluir uma nova plataforma, crie uma subclasse de `Fonte` em
`buscastartups/fontes/` e registre-a em `TIPOS`.

### 2. Classificação "É startup?"

```bash
python -m buscastartups classificar
```

Para usar o classificador com IA em vez das regras:

```bash
python -m buscastartups classificar --metodo llm
```

Cada organização recebe nota **0, 0,5 ou 1** em cada critério, com as evidências que a justificam:

| Critério | O que indica |
|----------|--------------|
| Inovação | produto, serviço ou processo novo: tecnologia, P&D, patente, IA, solução inédita |
| Modelo de negócio inovador | plataforma digital, SaaS, marketplace, assinatura, nova forma de capturar valor |
| Escalabilidade | crescer sem aumento proporcional de custos: expansão, novos mercados, base de usuários |
| Repetibilidade | entrega padronizada e replicável: produto, software, receita recorrente, licenciamento |
| Extrema incerteza | estágio inicial, MVP, validação, aceleração, investimento anjo, capital de risco |

**Veredito** (limiares ajustáveis em `[classificacao]`):

- **startup**: pontuação ≥ 3,0 **e** inovação e incerteza diferentes de zero;
- **não startup**: pontuação ≤ 1,5;
- **revisão humana**: todo o resto (pontuação intermediária, critério obrigatório zerado, nome não
  identificado, dúvida do classificador, falha ou recusa da IA). **Todos os dados do caso são
  mantidos** para o revisor: justificativa, evidências, trecho e todas as fontes.

Sinais de empresa consolidada ("multinacional", "fundada em 1950", "rede de supermercados", CNPJ
aberto há mais de 10 anos) anulam o critério de incerteza.

Dois métodos, com as mesmas saídas:

- **`regras`** (padrão): dicionários de indícios, transparentes, reprodutíveis e sem custo
  (`buscastartups/classificacao/regras.py`, ampliáveis no `config.toml`);
- **`llm`**: o modelo Claude lê cada menção e devolve, em JSON validado por esquema, os campos do painel
  e a nota de cada critério com a evidência textual. As regras funcionam como pré-filtro, para que só
  menções relevantes sejam enviadas, e as respostas ficam em cache (`dados/cache/llm/`).

#### Revisão humana

1. Abra `dados/revisao/pendentes.csv` (ou use o painel, filtro "Em revisão humana").
2. Preencha a coluna `veredito` com `startup` ou `nao_startup`. Também pode corrigir nome,
   responsável, setor, maturidade, modelo de negócio, município ou UF, além de `revisor` e `observacao`.
3. Copie as linhas preenchidas para `dados/revisao/revisoes.csv`. No painel, o botão
   "Baixar revisões" gera essas linhas prontas.
4. Rode `classificar` de novo: **a decisão humana prevalece** e fica registrada na justificativa.

O arquivo `revisoes.csv` deve ser versionado: é o registro auditável das decisões da pesquisa e
pode servir de padrão-ouro para medir a precisão dos métodos automáticos.

### 3. Painel

Aberto com `python -m buscastartups iniciar`, o painel mostra:

- área de **busca manual** e situação da **busca automática** (última e próxima execução, botão
  "Executar agora", andamento e histórico);
- indicadores: startups, em revisão, não startups, municípios no mapa e organizações sem localização;
- **mapa** (OpenStreetMap/Leaflet) com um ponto por município, de tamanho proporcional ao número de
  organizações. O ponto é a sede do município (tabela IBGE), não o endereço da empresa;
- distribuição por setor, maturidade, modelo de negócio, UF e organizações mais citadas;
- tabela com **nome, responsável, setor, maturidade, modelo de negócio, município/UF, link da fonte**,
  classificação e pontuação. Clique em uma linha para ver critérios, evidências e todas as fontes;
- filtros (classificação, setor, maturidade, UF, termo, período em que foi citada e texto), download do
  recorte em CSV/JSON e registro de revisões.

Fora do servidor, o arquivo `dashboard/index.html` continua funcionando como visualizador: o botão
"Abrir arquivo" carrega qualquer `startups.json`/`.csv`, mas a área de busca fica oculta.

## Dados abertos gerados

```
dados/
├── brutos/captacao_<data>.jsonl      # cada execução da captação, sem alteração
├── abertos/
│   ├── mencoes.csv | mencoes.json    # conteúdos captados (deduplicados)
│   ├── startups.csv | startups.json  # organizações classificadas
│   └── datapackage.json              # dicionário de dados (padrão Frictionless Data)
├── revisao/
│   ├── pendentes.csv                 # fila de revisão humana (gerado)
│   └── revisoes.csv                  # decisões humanas (versionar)
├── estado.json                       # histórico de buscas e última execução automática
└── cache/                            # municípios IBGE, consultas CNPJ e respostas da IA
```

Os arquivos usam UTF-8 e separador vírgula. O `datapackage.json` descreve cada coluna (tipo e
significado), a licença e os responsáveis, de modo que os dados podem ser publicados em portais
de dados abertos (CKAN/dados.gov.br, Zenodo).

## Ética, LGPD e boas práticas de coleta

- Coleta apenas conteúdo **público**; respeita o `robots.txt` dos sites e limita a frequência de
  requisições (`intervalo_minimo_s`). O User-Agent identifica a pesquisa e o contato.
- **Autores de postagens** em redes sociais são pseudonimizados (HMAC-SHA256 com sal secreto). Os
  textos têm e-mails, @menções e telefones substituídos por marcadores.
- O **responsável** pela startup é registrado apenas quando citado publicamente, em notícia ou cadastro
  oficial de CNPJ, no papel de dirigente da organização (dado de interesse público da pesquisa).
- Plataformas cujos termos de uso proíbem a coleta automatizada sem API oficial (X/Twitter,
  Instagram, Facebook, LinkedIn) **não** foram incluídas. Se forem necessárias, use as APIs oficiais
  ou programas de acesso para pesquisadores.
- `dados/brutos`, `dados/abertos` e `dados/cache` ficam fora do Git. Avalie o que publicar e
  submeta o protocolo ao Comitê de Ética, se a instituição exigir.

## Limitações conhecidas

- O classificador por regras depende de vocabulário: pode confundir organizações citadas na mesma
  notícia e não entende negações. Por isso existem a faixa de revisão humana e o método `llm`.
- Feeds de notícias trazem só título e resumo; `baixar_texto = true` tenta obter o corpo, quando o
  site permite.
- A geolocalização é feita por município (texto, gentílicos e CNPJ). Organizações sem cidade
  identificável ficam fora do mapa e aparecem no indicador "Sem localização".
- A disponibilidade e os limites das APIs públicas (Reddit, Mastodon, GDELT, Google Notícias) mudam
  com o tempo. Cada fonte falha de forma isolada, sem interromper as demais.

## Testes

```bash
python -m unittest discover -s tests -t .
```

Os testes não acessam a internet: usam respostas simuladas em `tests/fixtures/`.

## Estrutura do código

```
buscastartups/
├── __main__.py           # linha de comando
├── config.py             # leitura do config.toml
├── modelo.py             # esquemas Mencao e Startup, período, privacidade
├── http.py               # cliente HTTP (robots.txt, limite de taxa, novas tentativas)
├── captacao.py           # função 1
├── servico.py            # buscas manual e automática (agenda, histórico, uma por vez)
├── servidor.py           # servidor local do painel + API da busca
├── fontes/               # uma classe por plataforma
├── classificacao/
│   ├── __init__.py       # função 2: consolidação, enriquecimento, veredito, revisão
│   ├── regras.py         # critérios e extração por dicionários
│   └── llm.py            # critérios e extração com Claude (opcional)
├── cnpj.py               # consulta CNPJ (BrasilAPI / Receita Federal)
├── geo.py                # municípios IBGE e localização em texto
└── exportar.py           # CSV, JSON, JSONL e datapackage.json
dashboard/index.html      # função 3
docs/metodologia.md       # descrição metodológica para o texto da pesquisa
```
