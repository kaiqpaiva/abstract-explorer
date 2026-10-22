"""Busca abstracts de um pesquisador na OpenAlex e gera um HTML expositivo.

A busca soma duas fontes, porque a OpenAlex nem sempre liga um trabalho ao perfil do autor:
    1. por ID do autor (confiável, mas pode deixar trabalhos de fora);
    2. por nome bruto na autoria + instituição do autor (pega trabalhos sem perfil,
       mas pode trazer homônimos — esses vêm marcados como "confirme" no HTML).

Uso:
    python buscar_abstracts.py "Yoshua Bengio" -n 10
    python buscar_abstracts.py "Yoshua Bengio" --candidato 2     # escolhe outro homônimo
    python buscar_abstracts.py --orcid 0000-0002-9322-3515 -n 5
    python buscar_abstracts.py --id A5086198262 --ordem recentes
    python buscar_abstracts.py "Nome Sobrenome" --instituicao "Universidade de São Paulo"
    python buscar_abstracts.py "Nome Sobrenome" --so-id   # desliga a busca por nome

Só usa a biblioteca padrão. Chave de API é opcional (variável OPENALEX_API_KEY).
"""
import argparse
import html
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "https://api.openalex.org"
PASTA = Path(__file__).parent
CAMPOS_TRABALHO = "id,title,publication_year,publication_date,cited_by_count,doi,authorships,abstract_inverted_index"


def get(caminho, **params):
    chave = os.environ.get("OPENALEX_API_KEY")
    if chave:
        params["api_key"] = chave
    url = f"{BASE}/{caminho}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "ic-openalex-teste"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def curto(url):
    return url.rsplit("/", 1)[-1]


def sem_acento(texto):
    base = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def buscar_autores(nome):
    d = get("authors", search=nome, per_page=5,
            select="id,display_name,orcid,works_count,cited_by_count,last_known_institutions,affiliations")
    return d["results"]


def autor_por_id(id_ou_orcid):
    caminho = f"authors/{id_ou_orcid}" if id_ou_orcid.startswith("A") else f"authors/orcid:{id_ou_orcid}"
    try:
        return get(caminho)
    except urllib.error.HTTPError as erro:
        if erro.code == 404:
            sys.exit(f"A OpenAlex não tem nenhum autor com '{id_ou_orcid}'. "
                     "Tente buscar pelo nome (o perfil pode existir sem esse ORCID ligado).")
        raise


def reconstruir_abstract(indice):
    """A OpenAlex entrega {palavra: [posições]}; aqui remontamos o texto."""
    if not indice:
        return None
    palavras = {}
    for palavra, posicoes in indice.items():
        for p in posicoes:
            palavras[p] = palavra
    return " ".join(palavras[i] for i in sorted(palavras))


def nome_do_trabalho(w, origem):
    return {
        "id": w["id"],
        "titulo": w.get("title"),
        "ano": w.get("publication_year"),
        "data": w.get("publication_date") or "",
        "citacoes": w.get("cited_by_count") or 0,
        "doi": w.get("doi"),
        "abstract": reconstruir_abstract(w.get("abstract_inverted_index")),
        "origem": origem,
    }


def buscar_por_id(autor_id, ordem):
    sort = "cited_by_count:desc" if ordem == "citados" else "publication_date:desc"
    d = get("works", filter=f"author.id:{autor_id},has_abstract:true",
            sort=sort, per_page=100, select=CAMPOS_TRABALHO)
    return [nome_do_trabalho(w, "id") for w in d["results"]], d["meta"]["count"]


def ids_das_instituicoes(autor):
    """IDs curtos (I123...) das instituições do autor, vindas do perfil dele."""
    insts = list(autor.get("last_known_institutions") or [])
    insts += [a["institution"] for a in autor.get("affiliations") or [] if a.get("institution")]
    return sorted({curto(i["id"]) for i in insts if i.get("id")})


def resolver_instituicao(nome):
    d = get("institutions", search=nome, per_page=1, select="id,display_name,country_code")
    if not d["results"]:
        sys.exit(f"Instituição não encontrada: {nome}")
    inst = d["results"][0]
    print(f"Instituição: {inst['display_name']} ({inst['country_code']})")
    return curto(inst["id"])


def variantes_do_nome(nome):
    """Nome completo e 'primeiro + último', já que muitos trabalhos omitem os nomes do meio."""
    partes = nome.split()
    variantes = [" ".join(partes)]
    if len(partes) > 2:
        variantes.append(f"{partes[0]} {partes[-1]}")
    return variantes


def mesma_autoria(autoria, tokens_nome, autor_id, inst_ids):
    """Confere NA MESMA autoria: nome compatível + instituição + sem perfil de outra pessoa."""
    perfil = autoria["author"].get("id")
    if perfil and curto(perfil) != autor_id:
        return False  # a OpenAlex já atribuiu este nome a outro perfil
    nome = set(sem_acento(autoria.get("raw_author_name") or "").replace(".", " ").split())
    if not (tokens_nome[0] in nome and tokens_nome[-1] in nome):
        return False
    return any(curto(i["id"]) in inst_ids for i in autoria.get("institutions") or [])


def buscar_por_nome(autor, autor_id, inst_ids):
    tokens = sem_acento(autor["display_name"]).replace(".", " ").split()
    achados = {}
    for variante in variantes_do_nome(autor["display_name"]):
        d = get("works",
                filter=f'authorships.institutions.id:{"|".join(inst_ids)},'
                       f'raw_author_name.search:"{variante}",has_abstract:true',
                per_page=100, select=CAMPOS_TRABALHO)
        for w in d["results"]:
            if any(mesma_autoria(a, tokens, autor_id, inst_ids) for a in w["authorships"]):
                achados[w["id"]] = nome_do_trabalho(w, "nome")
    return list(achados.values())


def juntar(por_id, por_nome, n, ordem):
    todos = {t["id"]: t for t in por_id}
    for t in por_nome:
        if t["id"] in todos:
            todos[t["id"]]["origem"] = "id+nome"
        else:
            todos[t["id"]] = t
    chave = (lambda t: t["citacoes"]) if ordem == "citados" else (lambda t: t["data"])
    return sorted(todos.values(), key=chave, reverse=True)[:n]


def instituicao(autor):
    inst = autor.get("last_known_institutions") or []
    return inst[0]["display_name"] if inst else None


# Mostra o botão "Ler mais" só nos abstracts que passam de 5 linhas.
SCRIPT_LER_MAIS = """
<script>
  const blocos = document.querySelectorAll("article");
  function conferir() {
    blocos.forEach(function (bloco) {
      const texto = bloco.querySelector(".abstract");
      const botao = bloco.querySelector(".mais");
      if (texto.classList.contains("aberto")) return;
      botao.hidden = texto.scrollHeight <= texto.clientHeight + 1;
    });
  }
  blocos.forEach(function (bloco) {
    const texto = bloco.querySelector(".abstract");
    const botao = bloco.querySelector(".mais");
    botao.addEventListener("click", function () {
      const aberto = texto.classList.toggle("aberto");
      botao.textContent = aberto ? "Ler menos" : "Ler mais";
      botao.setAttribute("aria-expanded", aberto);
    });
  });
  window.addEventListener("load", conferir);
  window.addEventListener("resize", conferir);
</script>"""


def gerar_html(autor, trabalhos, total, ordem):
    e = html.escape
    cards = []
    for t in trabalhos:
        link = f'<a href="{e(t["doi"])}" target="_blank" rel="noopener">DOI</a>' if t["doi"] else ""
        aviso = ('<p class="aviso">Encontrado só por nome e instituição (sem perfil de autor na OpenAlex). '
                 'Confirme que é a mesma pessoa.</p>') if t["origem"] == "nome" else ""
        cards.append(f"""
    <article>
      <h2>{e(t["titulo"] or "(sem título)")}</h2>
      <p class="meta">{t["ano"]} · {t["citacoes"]} citações {("· " + link) if link else ""}</p>
      {aviso}<p class="abstract">{e(t["abstract"] or "")}</p>
      <button class="mais" type="button" aria-expanded="false" hidden>Ler mais</button>
    </article>""")
    inst = instituicao(autor)
    orcid = autor.get("orcid")
    sub = " · ".join(filter(None, [
        e(inst) if inst else None,
        f'<a href="{e(orcid)}" target="_blank" rel="noopener">ORCID</a>' if orcid else None,
        f'{autor.get("works_count")} trabalhos no perfil',
    ]))
    criterio = "mais citados" if ordem == "citados" else "mais recentes"
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Abstracts — {e(autor["display_name"])}</title>
<style>
  :root {{ --bg:#fafaf7; --fg:#1d1d1b; --muted:#6b6b66; --card:#fff; --line:#e4e4de; --accent:#2f5d8a; --warn:#8a5a00; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141413; --fg:#ecece6; --muted:#9a9a92; --card:#1e1e1c; --line:#33332f; --accent:#8db6e0; --warn:#e0b45a; }}
  }}
  body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 system-ui, sans-serif; }}
  .topo {{ padding:14px 24px; border-bottom:1px solid var(--line); }}
  .marca {{ font-weight:700; font-size:1.1rem; letter-spacing:.01em; color:var(--fg); }}
  main {{ max-width:760px; margin:0 auto; padding:32px 16px 64px; }}
  header h1 {{ margin:0 0 4px; font-size:1.8rem; }}
  header p {{ margin:0; color:var(--muted); }}
  article {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 20px; margin-top:16px; }}
  article h2 {{ font-size:1.35rem; line-height:1.3; margin:0 0 6px; }}
  .meta {{ color:var(--muted); font-size:.85rem; margin:0 0 8px; }}
  .aviso {{ color:var(--warn); font-size:.85rem; margin:0 0 8px; }}
  .abstract {{ margin:0; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:5; line-clamp:5; overflow:hidden; }}
  .abstract.aberto {{ display:block; -webkit-line-clamp:unset; line-clamp:unset; overflow:visible; }}
  .mais {{ margin-top:8px; padding:0; border:0; background:none; color:var(--accent); font:inherit; font-size:.9rem; font-weight:600; cursor:pointer; }}
  .mais:hover {{ text-decoration:underline; }}
  a {{ color:var(--accent); }}
  footer {{ margin-top:32px; color:var(--muted); font-size:.8rem; }}
</style>
<noscript><style>.abstract {{ display:block; -webkit-line-clamp:unset; line-clamp:unset; overflow:visible; }}</style></noscript>
</head>
<body>
<nav class="topo"><span class="marca">Abstract Explorer</span></nav>
<main>
  <header>
    <h1>{e(autor["display_name"])}</h1>
    <p>{sub}</p>
    <p>{len(trabalhos)} abstracts exibidos ({criterio}) de {total} trabalhos com abstract</p>
  </header>{"".join(cards)}
  <footer>Fonte: OpenAlex · gerado em {datetime.now():%d/%m/%Y %H:%M}</footer>
</main>{SCRIPT_LER_MAIS}
</body>
</html>"""


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # evita caracteres quebrados no console do Windows
    sys.stderr.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("nome", nargs="?", help="nome do pesquisador")
    ap.add_argument("--id", help="ID OpenAlex do autor (ex.: A5086198262)")
    ap.add_argument("--orcid", help="ORCID do autor (ex.: 0000-0002-9322-3515)")
    ap.add_argument("-n", type=int, default=10, help="quantidade de abstracts (padrão 10)")
    ap.add_argument("--candidato", type=int, default=1, help="qual resultado da busca por nome usar (padrão 1)")
    ap.add_argument("--ordem", choices=["citados", "recentes"], default="citados")
    ap.add_argument("--instituicao", help="instituição para a busca por nome (padrão: a do perfil do autor)")
    ap.add_argument("--so-id", action="store_true", help="desliga a busca por nome e instituição")
    args = ap.parse_args()

    if args.id or args.orcid:
        autor = autor_por_id(args.id or args.orcid)
    elif args.nome:
        candidatos = buscar_autores(args.nome)
        if not candidatos:
            sys.exit("Nenhum autor encontrado.")
        print("Candidatos (nomes iguais são comuns — confira!):")
        for i, a in enumerate(candidatos, 1):
            print(f"  {i}. {' '.join(a['display_name'].split())} | {a['works_count']} trabalhos | "
                  f"{instituicao(a) or 's/ instituição'} | {curto(a['id'])}")
        autor = candidatos[args.candidato - 1]
    else:
        ap.error("informe um nome, --id ou --orcid")

    autor["display_name"] = " ".join(autor["display_name"].split())
    autor_id = curto(autor["id"])
    print(f"\nUsando: {autor['display_name']} ({autor_id})")

    por_id, total = buscar_por_id(autor_id, args.ordem)
    print(f"Por ID do autor: {total} trabalhos com abstract")

    por_nome = []
    if not args.so_id:
        inst_ids = [resolver_instituicao(args.instituicao)] if args.instituicao else ids_das_instituicoes(autor)
        if inst_ids:
            por_nome = buscar_por_nome(autor, autor_id, inst_ids)
            novos = [t for t in por_nome if t["id"] not in {x["id"] for x in por_id}]
            print(f"Por nome + instituição: {len(por_nome)} trabalhos, {len(novos)} novos (sem perfil de autor)")
            total += len(novos)
        else:
            print("Busca por nome pulada: o perfil não tem instituição (use --instituicao).")

    trabalhos = juntar(por_id, por_nome, args.n, args.ordem)
    for t in trabalhos:
        t.pop("id")
    (PASTA / "abstracts.json").write_text(
        json.dumps({"autor": autor["display_name"], "trabalhos": trabalhos}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (PASTA / "index.html").write_text(gerar_html(autor, trabalhos, total, args.ordem), encoding="utf-8")
    print(f"{len(trabalhos)} abstracts salvos em abstracts.json e index.html")


if __name__ == "__main__":
    main()
