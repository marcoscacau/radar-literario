"""Radar Literário — coletor diário.

Lê as fontes de fontes.json, junta as novidades do dia e grava a "API"
estática em docs/api/ (servida pelo GitHub Pages). Só biblioteca padrão.

Uso: python coletor/coletar.py
"""
import hashlib
import html
import json
import re
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
API = RAIZ / "docs" / "api"
DIAS = API / "dias"

BRASILIA = timezone(timedelta(hours=-3))
DIAS_SEMANA = 7          # quantos dias entram em semana.json
DIAS_HISTORICO = 90      # quantos arquivos diários manter
JANELA_NOVIDADE = 3      # notícia com data mais antiga que isso não entra como novidade
MAX_RESUMO = 300

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
RSS1 = "{http://purl.org/rss/1.0/}"

# Fontes de cultura geral só passam se falarem disso (comparação sem acento).
LITERARIO = [
    "livro", "livros", "literatura", "literario", "literaria", "literarios", "literarias",
    "escritor", "escritora", "escritores", "escritoras", "romancista", "romance", "romances", "poesia", "poeta", "poetisa", "poemas", "poema",
    "conto", "contos", "cronica", "cronicas", "cronista", "editora", "editoras", "editorial",
    "flip", "bienal do livro", "feira do livro", "jabuti", "oceanos", "premio camoes",
    "nobel de literatura", "academia brasileira de letras", "leitores", "biblioteca",
    "best-seller", "bestseller", "mais vendidos", "livraria", "livrarias", "biografia",
]
PREMIOS = [
    "premio", "premios", "premiado", "premiada", "vence", "vencedor", "vencedora", "finalista",
    "finalistas", "jabuti", "oceanos", "camoes", "nobel", "booker", "pulitzer", "prize", "prizes",
    "award", "awards", "shortlist", "longlist", "winner", "wins", "laureate",
    "mais vendidos", "best-seller", "bestseller", "bestsellers",
]
LANCAMENTOS = [
    "lancamento", "lancamentos", "lanca", "lancam", "novo livro", "novo romance",
    "chega as livrarias", "pre-venda", "new book", "new novel", "debut novel", "out now",
    "forthcoming", "new releases", "most anticipated",
]


def sem_acento(texto):
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def compilar(termos):
    return re.compile(r"\b(" + "|".join(re.escape(t) for t in termos) + r")\b")


RE_LITERARIO = compilar(LITERARIO)
RE_PREMIOS = compilar(PREMIOS)
RE_LANCAMENTOS = compilar(LANCAMENTOS)


def limpar(texto):
    if not texto:
        return ""
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > MAX_RESUMO:
        texto = texto[:MAX_RESUMO].rsplit(" ", 1)[0] + "…"
    return texto


def ler_data(texto):
    if not texto:
        return None
    texto = texto.strip()
    try:
        d = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def baixar(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; RadarLiterario/1.0)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    ultimo_erro = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read()
        except Exception as e:  # rede instável: tenta mais uma vez
            ultimo_erro = e
    raise ultimo_erro


def ler_feed(dados):
    raiz = ET.fromstring(dados)
    itens = []
    for it in raiz.iter("item"):                     # RSS 2.0
        itens.append({
            "titulo": it.findtext("title"),
            "link": it.findtext("link"),
            "data": it.findtext("pubDate") or it.findtext(DC + "date"),
            "resumo": it.findtext("description"),
        })
    for it in raiz.iter(RSS1 + "item"):              # RSS 1.0 / RDF
        itens.append({
            "titulo": it.findtext(RSS1 + "title"),
            "link": it.findtext(RSS1 + "link"),
            "data": it.findtext(DC + "date"),
            "resumo": it.findtext(RSS1 + "description"),
        })
    for it in raiz.iter(ATOM + "entry"):             # Atom
        link = ""
        for l in it.findall(ATOM + "link"):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href", "")
                break
        itens.append({
            "titulo": it.findtext(ATOM + "title"),
            "link": link,
            "data": it.findtext(ATOM + "published") or it.findtext(ATOM + "updated"),
            "resumo": it.findtext(ATOM + "summary") or it.findtext(ATOM + "content"),
        })
    return itens


def coletar_fonte(fonte):
    try:
        brutos = ler_feed(baixar(fonte["url"]))
    except Exception as e:
        return fonte, [], f"{type(e).__name__}: {e}"[:200]

    itens = []
    for b in brutos:
        titulo = limpar(b["titulo"])
        link = (b["link"] or "").strip()
        if not titulo or not link:
            continue
        resumo = limpar(b["resumo"])
        if sem_acento(resumo).startswith(sem_acento(titulo[:40])):  # Google Notícias repete o título
            resumo = ""
        texto = sem_acento(f"{titulo} {resumo}")
        if fonte.get("filtrar") and not RE_LITERARIO.search(texto):
            continue
        tags = []
        if RE_PREMIOS.search(texto):
            tags.append("premios")
        if RE_LANCAMENTOS.search(texto):
            tags.append("lancamentos")
        data = ler_data(b["data"])
        itens.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "titulo": titulo,
            "link": link,
            "resumo": resumo,
            "fonte": fonte["nome"],
            "fonte_id": fonte["id"],
            "grupo": fonte["grupo"],
            "idioma": fonte["idioma"],
            "publicado_em": data.astimezone(BRASILIA).isoformat(timespec="minutes") if data else None,
            "tags": tags,
        })
    return fonte, ordenar(itens), None


def ler_json(caminho, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def ordenar(itens):
    return sorted(itens, key=lambda i: i["publicado_em"] or "", reverse=True)


def secoes(itens):
    return {
        "premios-lancamentos": [i["id"] for i in itens if i["tags"]],
        "brasil-portugal": [i["id"] for i in itens if i["grupo"] == "brasil-portugal"],
        "internacional": [i["id"] for i in itens if i["grupo"] == "internacional"],
    }


def main():
    agora = datetime.now(BRASILIA)
    hoje = agora.date().isoformat()
    fontes = json.loads((RAIZ / "fontes.json").read_text(encoding="utf-8"))["fontes"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(coletar_fonte, fontes))

    # O que já saiu em dias anteriores não volta como novidade.
    arquivos = sorted(DIAS.glob("*.json"))
    vistos = set()
    for arq in arquivos:
        if arq.stem != hoje:
            vistos.update(i["link"] for i in ler_json(arq, {}).get("itens", []))

    dia = ler_json(DIAS / f"{hoje}.json", {"itens": []})
    do_dia = {i["link"]: i for i in dia["itens"]}
    limite = agora - timedelta(days=JANELA_NOVIDADE)

    status = []
    for fonte, itens, erro in resultados:
        maximo = fonte.get("max_por_dia")
        ja_no_dia = sum(1 for i in do_dia.values() if i["fonte_id"] == fonte["id"])
        novos = 0
        for i in itens:
            if maximo and ja_no_dia + novos >= maximo:
                break
            if i["link"] in vistos or i["link"] in do_dia:
                continue
            if i["publicado_em"] and datetime.fromisoformat(i["publicado_em"]) < limite:
                continue
            do_dia[i["link"]] = i
            novos += 1
        status.append({
            "id": fonte["id"], "nome": fonte["nome"], "grupo": fonte["grupo"],
            "ok": erro is None, "erro": erro, "itens_no_feed": len(itens), "novos_hoje": novos,
        })
        print(f"{'ok   ' if erro is None else 'ERRO '} {fonte['nome']:<40} {len(itens):3d} itens, {novos:3d} novos"
              + (f"  ({erro})" if erro else ""))

    gerado_em = agora.isoformat(timespec="seconds")
    itens_hoje = ordenar(do_dia.values())
    pacote_hoje = {"data": hoje, "gerado_em": gerado_em, "total": len(itens_hoje),
                   "secoes": secoes(itens_hoje), "itens": itens_hoje}
    gravar_json(DIAS / f"{hoje}.json", pacote_hoje)
    gravar_json(API / "hoje.json", pacote_hoje)

    # Histórico: apaga o que passou do prazo e monta a semana.
    corte = (agora.date() - timedelta(days=DIAS_HISTORICO)).isoformat()
    for arq in DIAS.glob("*.json"):
        if arq.stem < corte:
            arq.unlink()
    datas = sorted((a.stem for a in DIAS.glob("*.json")), reverse=True)
    semana = []
    for d in datas[:DIAS_SEMANA]:
        for i in ler_json(DIAS / f"{d}.json", {}).get("itens", []):
            semana.append({**i, "dia": d})
    gravar_json(API / "semana.json", {"gerado_em": gerado_em, "dias": datas[:DIAS_SEMANA],
                                      "total": len(semana), "secoes": secoes(semana), "itens": semana})
    gravar_json(API / "indice.json", {"gerado_em": gerado_em, "dias": datas})
    gravar_json(API / "fontes.json", {"gerado_em": gerado_em, "fontes": status})

    print(f"\n{len(itens_hoje)} novidades em {hoje}; {len(semana)} na semana.")
    if not any(s["ok"] for s in status):
        sys.exit("Nenhuma fonte respondeu.")


if __name__ == "__main__":
    main()
