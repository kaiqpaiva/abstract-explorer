# abstract-explorer

Testes para puxar os **abstracts** de pesquisadores/professores a partir de APIs bibliográficas e mostrá-los numa página HTML simples. Projeto de apoio à iniciação científica.

Hoje há dois scripts, ambos só com a biblioteca padrão do Python 3.9 ou mais novo (sem `pip install`):

| Script | Fonte | Para que serve |
|---|---|---|
| `buscar_abstracts.py` | [OpenAlex](https://openalex.org) | Busca os abstracts de um pesquisador e gera `index.html` + `abstracts.json` |
| `testar_elsevier.py` | [Elsevier / Scopus](https://dev.elsevier.com) | Só diagnóstico: testa se a sua chave devolve abstracts |

## OpenAlex

Não precisa de chave para testes pequenos. Sem chave o orçamento diário é dividido com o seu IP; uma chave grátis em <https://openalex.org/settings/api> dá mais folga e pode ser passada pela variável `OPENALEX_API_KEY`.

```bash
python buscar_abstracts.py "Nome do Pesquisador" -n 10
```

O script não abre a página: ele grava o `index.html` ao lado dele. Depois de rodar, abra o arquivo no navegador (`start index.html` no PowerShell, ou dois cliques no arquivo).

Opções úteis:

- `--id A5086198262` ou `--orcid 0000-0002-9322-3515` (exemplos com o Yoshua Bengio): vai direto ao autor, sem depender da busca por nome (o mais seguro).
- `--candidato 2`: usa outro resultado da busca por nome, útil com homônimos.
- `--ordem recentes`: ordena por data em vez de citações.
- `--instituicao Mackenzie`: instituição usada na busca por nome.
- `--so-id`: desliga a busca por nome e instituição.

### Como a busca funciona

1. **Por ID do autor:** pega os trabalhos ligados ao perfil do autor.
2. **Por nome e instituição:** procura o nome como aparece na autoria do trabalho, junto com a instituição do autor. Isso acha trabalhos que a OpenAlex não ligou a nenhum perfil.

Os resultados são somados. O que veio **só** pela segunda busca aparece no HTML com o aviso "Confirme que é a mesma pessoa".

O abstract não vem como texto: a OpenAlex entrega um índice invertido (`palavra → posições`) e o script remonta a frase.

### Limitações conhecidas

- **Homônimos e perfis duplicados:** nomes comuns geram vários perfis, e trabalhos de pessoas diferentes às vezes ficam no mesmo perfil. Confira a lista.
- **Abstracts faltantes ou truncados:** nem todo trabalho tem abstract, e alguns vêm curtos ou com texto extra.
- **Busca por nome:** olha só a primeira página (100 trabalhos).
- Não misture citações e h-index da OpenAlex com os do Scopus: as bases cobrem conjuntos diferentes.

## Elsevier (Scopus)

A chave é grátis, mas os dados completos dependem da assinatura da sua instituição, e o Scopus reconhece você pelo IP. Rode de dentro da rede da universidade ou pela VPN dela.

```powershell
$env:ELSEVIER_API_KEY = "sua_chave"
python testar_elsevier.py "Sobrenome, Nome" -n 5
```

Também aceita `--orcid` (o mesmo ORCID usado na OpenAlex), `--au-id` (ID do autor no Scopus) e `--doi`. Se a busca por ORCID voltar vazia, o Scopus pode simplesmente não ter ligado o ORCID ao perfil do autor; nesse caso use o nome ou o `--au-id`. O script não grava nada; só diz se os abstracts vieram. Se existir um Institutional Token, use `ELSEVIER_INSTTOKEN`.

### O que já foi testado

Com uma chave grátis, **fora da rede da universidade**: a chave funciona e a busca por ORCID devolve os documentos (título, ano, DOI), mas **sem abstract**. A visão completa (`COMPLETE`/`FULL`) responde `AUTHORIZATION_ERROR`, ou seja, o Scopus não reconheceu o acesso como assinante.

Falta testar **de dentro da rede da universidade** (ou com Institutional Token). Se continuar sem abstract, a OpenAlex segue como fonte principal.

Antes de guardar dados da Elsevier num banco próprio, leia o API Service Agreement deles.

## Chaves de API

As chaves ficam **sempre em variáveis de ambiente**, nunca no código. O `.gitignore` já ignora `.env` e a saída gerada (`index.html`, `abstracts.json`). Não cole a chave em arquivos do repositório, em issues ou em mensagens; se ela vazar, apague-a no portal e crie outra.

## Próximos passos

- Gravar os resultados em SQLite para não repetir chamadas.
- Receber uma lista de pesquisadores de uma vez.
- Puxar também palavras-chave, tópicos e citações.
