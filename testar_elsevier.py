"""Testa se a sua chave da Elsevier devolve ABSTRACTS (Scopus Search + Abstract Retrieval).

Antes de rodar:
    1. Crie a chave em https://dev.elsevier.com  (My API Key)
    2. Conecte na rede/VPN da sua universidade (o Scopus te reconhece pelo IP)
    3. No PowerShell:   $env:ELSEVIER_API_KEY = "sua_chave"
       (opcional)       $env:ELSEVIER_INSTTOKEN = "seu_token"

Uso:
    python testar_elsevier.py "Bengio, Yoshua" -n 5
    python testar_elsevier.py --orcid 0000-0002-9322-3515 -n 5   # mesmo ORCID usado na OpenAlex
    python testar_elsevier.py --au-id 7003958611 -n 5     # ID do autor no Scopus
    python testar_elsevier.py --doi 10.1109/5.726791

O script não grava nada; só imprime um diagnóstico.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.elsevier.com/content"


def chamar(caminho, **params):
    """Devolve (status_http, json_ou_None, texto_do_erro)."""
    chave = os.environ.get("ELSEVIER_API_KEY")
    if not chave:
        sys.exit("Defina a variável ELSEVIER_API_KEY com a sua chave (veja o topo do arquivo).")
    headers = {"X-ELS-APIKey": chave, "Accept": "application/json"}
    token = os.environ.get("ELSEVIER_INSTTOKEN")
    if token:
        headers["X-ELS-Insttoken"] = token
    url = f"{BASE}/{caminho}?{urllib.parse.urlencode(params, safe='(),')}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
            return r.status, json.load(r), None
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300]
        return e.code, None, f"{corpo}  [X-ELS-Status: {e.headers.get('X-ELS-Status')}]"
    except urllib.error.URLError as e:
        return 0, None, f"sem conexão: {e.reason}"


def explicar(status, erro):
    if "APIKEY_INVALID" in (erro or ""):
        return f"HTTP {status} — a chave de API é inválida. Confira se copiou a chave inteira.\n    {erro}"
    dicas = {
        401: "401: o Scopus não te reconhece como assinante. Use a rede/VPN da universidade ou peça um Institutional Token.",
        403: "403: a chave não tem permissão para esse recurso/visão (provável falta de assinatura).",
        429: "429: cota semanal ou limite por segundo estourado.",
    }
    return f"HTTP {status} — {dicas.get(status, 'erro inesperado')}\n    {erro}"


def limpar_orcid(valor):
    """Aceita '0000-0002-9322-3515' ou a URL completa do ORCID."""
    orcid = valor.strip().removeprefix("https://orcid.org/")
    if not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid):
        sys.exit(f"ORCID inválido: '{valor}'. O formato é 0000-0000-0000-0000.")
    return orcid


def buscar_scopus(args):
    if args.orcid:
        consulta = f"ORCID({limpar_orcid(args.orcid)})"
    elif args.au_id:
        consulta = f"AU-ID({args.au_id})"
    else:
        sobrenome, _, nome = args.nome.partition(",")
        consulta = f"AUTHLASTNAME({sobrenome.strip()})"
        if nome.strip():
            consulta += f" AND AUTHFIRST({nome.strip()})"
    print(f"Consulta Scopus: {consulta}")

    for visao in ("COMPLETE", "STANDARD"):
        status, dados, erro = chamar("search/scopus", query=consulta, view=visao,
                                     count=min(args.n, 25), sort="citedby-count")
        if dados:
            break
        print(f"  view={visao}: {explicar(status, erro)}")
    else:
        return []

    entradas = dados["search-results"].get("entry", [])
    entradas = [e for e in entradas if "error" not in e]
    com_abstract = sum(1 for e in entradas if e.get("dc:description"))
    print(f"  view={visao}: {len(entradas)} documentos, {com_abstract} com abstract no resultado da busca")
    if not entradas and args.orcid:
        print("  Nenhum documento para esse ORCID. Isso pode ser só porque o Scopus não ligou o ORCID ao "
              "perfil do autor (a chave está funcionando). Tente pelo nome ou com --au-id.")
    for e in entradas:
        marca = "ABSTRACT OK" if e.get("dc:description") else "sem abstract"
        print(f"   - [{marca}] {e.get('dc:title')} ({e.get('prism:coverDate', '')[:4]}) doi={e.get('prism:doi')}")
    return [e["prism:doi"] for e in entradas if e.get("prism:doi")]


def testar_abstract_retrieval(doi):
    print(f"\nAbstract Retrieval para DOI {doi}")
    for visao in ("META", "FULL"):
        status, dados, erro = chamar(f"abstract/doi/{doi}", view=visao)
        if not dados:
            print(f"  view={visao}: {explicar(status, erro)}")
            continue
        core = dados["abstracts-retrieval-response"]["coredata"]
        texto = core.get("dc:description")
        if texto:
            print(f"  view={visao}: ABSTRACT OK ({len(texto.split())} palavras): {texto[:120].strip()}...")
        else:
            print(f"  view={visao}: resposta OK, mas SEM abstract (provável acesso reduzido)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    ap =argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("nome", nargs="?", help='"Sobrenome, Nome" do pesquisador')
    ap.add_argument("--orcid", help="ORCID do autor (ex.: 0000-0002-9322-3515)")
    ap.add_argument("--au-id", help="ID do autor no Scopus")
    ap.add_argument("--doi", help="testar só o Abstract Retrieval com este DOI")
    ap.add_argument("-n", type=int, default=5, help="quantos documentos buscar (máx. 25)")
    args = ap.parse_args()

    if args.doi:
        testar_abstract_retrieval(args.doi)
        return
    if not (args.nome or args.au_id or args.orcid):
        ap.error("informe um nome, --orcid, --au-id ou --doi")
    dois = buscar_scopus(args)
    if dois:
        testar_abstract_retrieval(dois[0])


if __name__ == "__main__":
    main()
