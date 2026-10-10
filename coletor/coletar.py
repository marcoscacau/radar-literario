"""Radar Literário — coletor diário.

Lê as fontes de fontes.json, junta as novidades do dia, pontua cada uma pelo
perfil de leitura (perfil.json), detecta os nomes em alta na semana e grava a
"API" estática em docs/api/ (servida pelo GitHub Pages). Só biblioteca padrão.

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
from collections import Counter, defaultdict
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
MIN_FONTES_EM_ALTA = 3   # um nome só está "em alta" se aparece em tantas fontes diferentes
MAX_EM_ALTA = 15

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"
RSS1 = "{http://purl.org/rss/1.0/}"

# Fontes de cultura geral só passam se falarem disso (comparação sem acento).
LITERARIO = [
    "livro", "livros", "literatura", "literario", "literaria", "literarios", "literarias",
    "escritor", "escritora", "escritores", "escritoras", "romancista",
    "romance", "romances", "poesia", "poeta", "poetisa", "poemas", "poema",
    "conto", "contos", "cronica", "cronicas", "cronista", "editora", "editoras", "editorial",
    "flip", "bienal do livro", "feira do livro", "jabuti", "oceanos", "premio camoes",
    "nobel de literatura", "academia brasileira de letras", "leitores", "biblioteca",
    "best-seller", "bestseller", "mais vendidos", "livraria", "livrarias", "biografia",
    "book", "books", "novel", "novels", "novelist", "author", "authors", "writer", "writers",
    "poet", "poetry", "poem", "poems", "memoir", "literary", "literature", "fiction",
    "publisher", "publishing", "bestsellers", "readers", "bookshop", "bookstore",
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
    "forthcoming", "new releases", "most anticipated", "novo thriller", "novo suspense",
    "capa revelada", "cover reveal", "pre-order", "pre-orders", "release date", "announces new",
    "anuncia novo", "next book", "proximo livro", "is here", "arrives",
]
# Para o alerta: notícia de autor acompanhado que fala de livro novo.
RE_NOVIDADE = re.compile(r"(?<![\w-])(novo livro|novo romance|novo thriller|novo suspense|lanca|lancamento|"
                         r"pre-venda|capa revelada|anuncia novo|new book|new novel|announces new|pre-order|"
                         r"cover reveal|release date|next book|proximo livro|out now|chega as livrarias|"
                         r"finale|conclusion|desfecho)(?![\w-])")
ASPAS = re.compile(r"[‘'“\"]([^‘'“\"’”]{3,60})[’'”\"]")

# Palavras que não começam nem terminam um nome próprio (início de frase, artigos).
VAZIAS = set("""
a o as os um uma uns umas e ou de da do das dos em no na nos nas por para com sem sobre
ao aos à às pelo pela pelos pelas que se como quando onde quem qual seu sua seus suas
the an and or of in on at to for with by from as is are was were his her their its this
that these those how why what who when where after before new
""".split())
CONECTORES = {"de", "da", "do", "das", "dos", "del", "van", "von", "e"}


def sem_acento(texto):
    texto = texto.replace("’", "'").replace("‘", "'")
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def compilar(termos):
    return re.compile(r"(?<![\w-])(" + "|".join(re.escape(sem_acento(t)) for t in termos) + r")(?![\w-])")


RE_LITERARIO = compilar(LITERARIO)
RE_PREMIOS = compilar(PREMIOS)
RE_LANCAMENTOS = compilar(LANCAMENTOS)


def titulo_inconfundivel(titulo, livro):
    """Título que, sozinho, identifica o livro (sem risco de ser expressão comum)."""
    if livro.get("ambiguo"):
        return False
    if livro.get("unico"):
        return True
    t = sem_acento(titulo)
    palavras = [p for p in re.findall(r"[\w/]+", t) if p not in VAZIAS]
    return len(palavras) >= 2 and len(t) >= 9


def titulos(livro):
    return [t for t in (livro["titulo"], livro.get("pt")) if t]


def carregar_perfil():
    perfil = json.loads((RAIZ / "perfil.json").read_text(encoding="utf-8"))
    estante = json.loads((RAIZ / "estante.json").read_text(encoding="utf-8"))["autores"]
    por_nome = {a["nome"]: a for a in perfil["autores"]}
    for autor in estante:   # obras completas: o autor e seus títulos inconfundíveis contam como autor da estante
        termos = list(autor["termos"])
        for livro in autor["livros"]:
            termos += [sem_acento(t) for t in titulos(livro) if titulo_inconfundivel(t, livro)]
            if titulo_inconfundivel(livro["titulo"], livro):
                livro["re"] = compilar(titulos(livro))
            else:   # título comum ("It", "Holly"): só conta entre aspas
                livro["re"] = re.compile(r"['\"“‘](" + "|".join(re.escape(sem_acento(t)) for t in titulos(livro)) + r")['\"”’]")
        if autor["nome"] in por_nome:
            por_nome[autor["nome"]]["termos"] += termos
        else:
            perfil["autores"].append({"nome": autor["nome"], "termos": termos})
        autor["re"] = compilar(autor["termos"])
    perfil["estante"] = estante
    for grupo in ("autores", "vizinhos", "temas"):
        for p in perfil[grupo]:
            p["re"] = compilar(p["termos"])
    perfil["re_tela"] = compilar(perfil.get("tela", [])) if perfil.get("tela") else None
    return perfil


def pontuar(texto, perfil):
    """Pontos e motivos de uma notícia para o perfil (texto já sem acento)."""
    pts, motivos, temas = perfil["pontos"], [], []
    total = 0
    for a in perfil["autores"]:
        if a["re"].search(texto):
            total += pts["autor"]
            motivos.append(a["nome"])
    for v in perfil["vizinhos"]:
        if v["re"].search(texto):
            total += pts["vizinho"]
            motivos.append(v["nome"])
    for t in perfil["temas"]:
        if t["re"].search(texto):
            temas.append(t["id"])
    total += pts["tema"] * min(len(temas), pts["max_temas"])
    if temas and RE_LITERARIO.search(texto):
        total += pts.get("tema_com_livro", 0)
    if total and perfil["re_tela"] and perfil["re_tela"].search(texto):
        total += pts.get("tela", 0)   # adaptação para tela não é notícia literária
    return max(total, 0), motivos, temas


def limpar(texto, limite=MAX_RESUMO):
    if not texto:
        return ""
    texto = html.unescape(re.sub(r"<[^>]+>", " ", texto))
    texto = re.sub(r"\s+", " ", texto).strip()
    if limite and len(texto) > limite:
        texto = texto[:limite].rsplit(" ", 1)[0] + "…"
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
            "veiculo": it.findtext("source"),
        })
    for it in raiz.iter(RSS1 + "item"):              # RSS 1.0 / RDF
        itens.append({
            "titulo": it.findtext(RSS1 + "title"),
            "link": it.findtext(RSS1 + "link"),
            "data": it.findtext(DC + "date"),
            "resumo": it.findtext(RSS1 + "description"),
            "veiculo": None,
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
            "veiculo": None,
        })
    return itens


def coletar_fonte(fonte, perfil):
    try:
        brutos = ler_feed(baixar(fonte["url"]))
    except Exception as e:
        return fonte, [], f"{type(e).__name__}: {e}"[:200]

    itens = []
    for b in brutos:
        titulo = limpar(b["titulo"], limite=0)
        link = (b["link"] or "").strip()
        if not titulo or not link:
            continue
        nome_fonte = fonte["nome"]
        # Google Notícias: "Manchete - Jornal" -> manchete limpa, jornal como fonte.
        veiculo = limpar(b.get("veiculo"), limite=0)
        if veiculo and titulo.endswith(" - " + veiculo):
            titulo = titulo[: -len(veiculo) - 3].rstrip()
            nome_fonte = f"{veiculo} (via Google)"
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
        pontos, motivos, temas = pontuar(texto, perfil)
        data = ler_data(b["data"])
        itens.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:12],
            "titulo": titulo,
            "link": link,
            "resumo": resumo,
            "fonte": nome_fonte,
            "fonte_id": fonte["id"],
            "grupo": fonte["grupo"],
            "idioma": fonte["idioma"],
            "publicado_em": data.astimezone(BRASILIA).isoformat(timespec="minutes") if data else None,
            "tags": tags,
            "para_voce": {"pontos": pontos, "autores": motivos, "temas": temas},
        })
    return fonte, ordenar(itens), None


# ---------- Em alta: nomes que se repetem em fontes diferentes ----------

PALAVRA = re.compile(r"[\wÀ-ÿ][\wÀ-ÿ.'’-]*")


def titulo_em_caixa_alta(titulo):
    """Manchete em inglês com Toda Palavra Maiúscula não serve para achar nomes."""
    palavras = [p for p in PALAVRA.findall(titulo) if p.lower() not in VAZIAS and len(p) > 3]
    return len(palavras) >= 3 and sum(p[0].isupper() for p in palavras) / len(palavras) > 0.7


def nomes_proprios(texto):
    """Sequências de 2 a 4 palavras com inicial maiúscula (ligadas por de/da/do...)."""
    achados = []
    for frase in re.split(r"[.:;!?“”\"()\[\]|–—]|\s-\s", texto):
        atual = []
        for p in PALAVRA.findall(frase):
            p = re.sub(r"(['’]s|['’])$", "", p).strip(".-")
            if not p:
                continue
            if p[0].isupper() and not p.isupper() or (p.isupper() and len(p) > 1 and atual):
                atual.append(p)
            elif atual and p.lower() in CONECTORES:
                atual.append(p)
            else:
                achados.append(atual)
                atual = []
        achados.append(atual)

    nomes = []
    for seq in achados:
        while seq and (seq[0].lower() in VAZIAS or seq[0].lower() in CONECTORES):
            seq = seq[1:]
        while seq and seq[-1].lower() in CONECTORES:
            seq = seq[:-1]
        if 2 <= len(seq) <= 4:
            nomes.append(" ".join(seq))
    return nomes


def em_alta(itens, dias, ignorar):
    """Nomes citados por mais fontes na semana, com a contagem de cada dia."""
    fontes = defaultdict(set)
    por_dia = defaultdict(Counter)
    ids = defaultdict(list)
    formas = defaultdict(Counter)
    for i in itens:
        textos = [i["resumo"]]
        if not (i["idioma"] == "en" and titulo_em_caixa_alta(i["titulo"])):
            textos.append(i["titulo"])
        vistos = set()
        for nome in nomes_proprios(" . ".join(textos)):
            chave = sem_acento(nome)
            if chave in vistos or chave in ignorar:
                continue
            vistos.add(chave)
            formas[chave][nome] += 1
            fontes[chave].add(i["fonte"])
            por_dia[chave][i["dia"]] += 1
            ids[chave].append(i["id"])

    # "Anne Carson" e "Carson" juntos: um nome contido em outro mais citado é descartado.
    ordem = sorted(fontes, key=lambda k: (len(fontes[k]), sum(por_dia[k].values())), reverse=True)
    escolhidos = []
    for k in ordem:
        if len(fontes[k]) < MIN_FONTES_EM_ALTA:
            break
        if any(k in e or e in k for e in escolhidos):
            continue
        escolhidos.append(k)
        if len(escolhidos) == MAX_EM_ALTA:
            break

    dias_cresc = sorted(dias)
    hoje = dias_cresc[-1] if dias_cresc else None
    resultado = []
    for k in escolhidos:
        serie = [por_dia[k].get(d, 0) for d in dias_cresc]
        resultado.append({
            "termo": formas[k].most_common(1)[0][0],
            "fontes": len(fontes[k]),
            "mencoes": sum(serie),
            "por_dia": serie,
            "novo_hoje": bool(hoje) and sum(serie[:-1]) == 0,
            "itens": ids[k][:12],
        })
    return {"dias": dias_cresc, "termos": resultado}


# ---------- Estante, alertas, resumo da semana e nota do Obsidian ----------

def texto_de(i):
    return sem_acento(f"{i['titulo']} {i['resumo']}").replace("”", '"').replace("“", '"')


def estante_semana(estante, semana):
    """Obras completas com o que saiu de cada livro na semana."""
    autores = []
    for autor in estante:
        do_autor = [i for i in semana if autor["re"].search(texto_de(i))]
        livros = []
        for livro in autor["livros"]:
            # título comum só conta se o autor também aparece na notícia
            base = semana if titulo_inconfundivel(livro["titulo"], livro) else do_autor
            ids = [i["id"] for i in base if livro["re"].search(texto_de(i))]
            livros.append({k: v for k, v in livro.items() if k != "re"} | {"noticias": ids})
        autores.append({"nome": autor["nome"], "noticias": [i["id"] for i in do_autor], "livros": livros})
    return autores


def alertas_do_dia(novos, perfil):
    """Notícias novas de autor acompanhado falando de livro novo; aponta título fora da estante."""
    conhecidos = {}
    for autor in perfil["estante"]:
        conhecidos[autor["nome"]] = {sem_acento(t) for l in autor["livros"] for t in titulos(l)}
    alertas = []
    for i in novos:
        autores = i["para_voce"]["autores"]
        texto = texto_de(i)
        if not autores or not RE_NOVIDADE.search(texto) or not RE_LITERARIO.search(texto):
            continue   # precisa falar de livro E de novidade ("anuncia apoio a..." não é lançamento)
        desconhecidos = []
        for nome in autores:
            if nome not in conhecidos:
                continue
            for t in ASPAS.findall(i["titulo"]):
                t = t.strip(" .,")
                if len(t.split()) <= 6 and t[:1].isupper() and sem_acento(t) not in conhecidos[nome] \
                        and sem_acento(t) not in {sem_acento(a) for a in autores}:
                    desconhecidos.append(t)
        alertas.append({"id": i["id"], "dia": i.get("dia"), "autores": autores, "titulo": i["titulo"],
                        "link": i["link"], "fonte": i["fonte"], "titulos_fora_da_estante": desconhecidos})
    return alertas


def resumo_semana(semana, padroes, perfil):
    temas, autores = Counter(), Counter()
    for i in semana:
        temas.update(i["para_voce"]["temas"])
        autores.update(i["para_voce"]["autores"])
    nomes_temas = {t["id"]: t["nome"] for t in perfil["temas"]}
    subindo = []
    for t in padroes["termos"]:
        recente, antes = sum(t["por_dia"][-3:]), sum(t["por_dia"][:-3])
        if len(t["por_dia"]) > 3 and recente > antes:
            subindo.append({"termo": t["termo"], "ultimos_3_dias": recente, "antes": antes})
    destaques = sorted(semana, key=lambda i: (i["para_voce"]["pontos"], i["publicado_em"] or ""), reverse=True)
    vistos, top = set(), []
    for i in destaques:   # um destaque por autor, para a lista ter variedade
        chave = (i["para_voce"]["autores"] or [i["id"]])[0]
        if i["para_voce"]["pontos"] < perfil["pontos"]["minimo"] or chave in vistos:
            continue
        vistos.add(chave)
        top.append(i["id"])
        if len(top) == 8:
            break
    return {
        "total": len(semana),
        "por_grupo": dict(Counter(i["grupo"] for i in semana)),
        "temas": [{"id": k, "nome": nomes_temas.get(k, k), "noticias": n} for k, n in temas.most_common()],
        "autores": [{"nome": k, "noticias": n} for k, n in autores.most_common(10)],
        "em_alta": [t["termo"] for t in padroes["termos"][:5]],
        "subindo": sorted(subindo, key=lambda s: s["ultimos_3_dias"] - s["antes"], reverse=True)[:5],
        "destaques": top,
    }


def obsidian_md(pacote, padroes, por_id_semana):
    """Trecho em Markdown que o modelo do Diário do Obsidian puxa (sem links internos)."""
    ids = pacote["secoes"]["para-voce"][:5]
    linhas = []
    for k in ids:
        i = por_id_semana.get(k) or next(x for x in pacote["itens"] if x["id"] == k)
        motivo = ", ".join(i["para_voce"]["autores"] + i["para_voce"]["temas"])
        titulo = i["titulo"].replace("[", "(").replace("]", ")")
        linhas.append(f"- [{titulo}]({i['link']}) — {i['fonte']}" + (f" · *{motivo}*" if motivo else ""))
    if not linhas:
        linhas.append("- Nada da sua estante hoje.")
    if padroes["termos"]:
        linhas.append("")
        linhas.append("**Em alta:** " + ", ".join(t["termo"] for t in padroes["termos"][:5]))
    linhas.append("")
    linhas.append(f"[Edição completa](https://marcoscacau.github.io/radar-literario/) · "
                  f"{pacote['total']} notícias")
    return "\n".join(linhas) + "\n"


# ---------- gravação ----------

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


def secoes(itens, pontos):
    candidatos = sorted((i for i in itens if i.get("para_voce", {}).get("pontos", 0) >= pontos["minimo"]),
                        key=lambda i: (i.get("dia", ""), i["para_voce"]["pontos"], i["publicado_em"] or ""),
                        reverse=True)
    para_voce, por_autor = [], Counter()
    for i in candidatos:   # um autor só não toma a seção inteira
        autores = i["para_voce"]["autores"]
        if autores:
            chave = (i.get("dia"), autores[0])
            if por_autor[chave] >= pontos.get("max_por_autor_dia", 99):
                continue
            por_autor[chave] += 1
        para_voce.append(i)
    return {
        "para-voce": [i["id"] for i in para_voce],
        "premios-lancamentos": [i["id"] for i in itens if i["tags"]],
        "brasil-portugal": [i["id"] for i in itens if i["grupo"] == "brasil-portugal"],
        "internacional": [i["id"] for i in itens if i["grupo"] == "internacional"],
    }


def main():
    agora = datetime.now(BRASILIA)
    hoje = agora.date().isoformat()
    fontes = json.loads((RAIZ / "fontes.json").read_text(encoding="utf-8"))["fontes"]
    perfil = carregar_perfil()
    pontos = perfil["pontos"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        resultados = list(pool.map(lambda f: coletar_fonte(f, perfil), fontes))

    # O que já saiu em dias anteriores não volta como novidade.
    vistos = set()
    for arq in DIAS.glob("*.json"):
        if arq.stem != hoje:
            vistos.update(i["link"] for i in ler_json(arq, {}).get("itens", []))

    dia = ler_json(DIAS / f"{hoje}.json", {"itens": []})
    do_dia = {i["link"]: i for i in dia["itens"]}
    limite = agora - timedelta(days=JANELA_NOVIDADE)

    status, novos_agora = [], []
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
            novos_agora.append(i)
            novos += 1
        status.append({
            "id": fonte["id"], "nome": fonte["nome"], "grupo": fonte["grupo"],
            "ok": erro is None, "erro": erro, "itens_no_feed": len(itens), "novos_hoje": novos,
        })
        print(f"{'ok   ' if erro is None else 'ERRO '} {fonte['nome']:<42} {len(itens):3d} itens, {novos:3d} novos"
              + (f"  ({erro})" if erro else ""))

    # Notícias que chegaram antes do perfil existir (ou de ele mudar) são pontuadas de novo.
    for i in do_dia.values():
        nota, motivos, temas = pontuar(sem_acento(f"{i['titulo']} {i['resumo']}"), perfil)
        i["para_voce"] = {"pontos": nota, "autores": motivos, "temas": temas}

    gerado_em = agora.isoformat(timespec="seconds")
    itens_hoje = ordenar(do_dia.values())
    pacote_hoje = {"data": hoje, "gerado_em": gerado_em, "total": len(itens_hoje),
                   "secoes": secoes(itens_hoje, pontos), "itens": itens_hoje}
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

    # Nomes de veículos e seções não contam como "em alta".
    ignorar = {sem_acento(n) for f in fontes for n in [f["nome"]] + f["nome"].split(" – ")}
    ignorar |= {sem_acento(re.sub(r" \(via Google\)$", "", i["fonte"])) for i in semana}
    padroes = em_alta(semana, datas[:DIAS_SEMANA], ignorar)

    perfil_temas = {t["id"]: t["nome"] for t in perfil["temas"]}
    gravar_json(API / "semana.json", {"gerado_em": gerado_em, "dias": datas[:DIAS_SEMANA],
                                      "total": len(semana), "secoes": secoes(semana, pontos),
                                      "temas": perfil_temas, "itens": semana})
    gravar_json(API / "em-alta.json", {"gerado_em": gerado_em, **padroes})
    gravar_json(API / "indice.json", {"gerado_em": gerado_em, "dias": datas})
    gravar_json(API / "fontes.json", {"gerado_em": gerado_em, "fontes": status})

    # Estante (obras completas + o que saiu de cada livro) e resumo da semana.
    gravar_json(API / "estante.json", {"gerado_em": gerado_em, "autores": estante_semana(perfil["estante"], semana)})
    gravar_json(API / "resumo-semana.json", {"gerado_em": gerado_em, "dias": datas[:DIAS_SEMANA],
                                             **resumo_semana(semana, padroes, perfil)})
    # O que a página usa para sugerir autores novos a partir dos cliques.
    gravar_json(API / "perfil.json", {
        "gerado_em": gerado_em,
        "conhecidos": sorted({a["nome"] for a in perfil["autores"] + perfil["vizinhos"]}),
        "temas": perfil_temas,
        "editar": "https://github.com/marcoscacau/radar-literario/edit/main/perfil.json",
    })

    # Alertas de lançamento: guardados por 30 dias; os desta execução vão para alerta.md (vira issue no GitHub).
    for i in novos_agora:
        i["dia"] = hoje
    alertas_novos = alertas_do_dia(novos_agora, perfil)
    corte_alertas = (agora.date() - timedelta(days=30)).isoformat()
    historico = [a for a in ler_json(API / "alertas.json", {}).get("alertas", []) if (a.get("dia") or "") >= corte_alertas]
    gravar_json(API / "alertas.json", {"gerado_em": gerado_em, "alertas": alertas_novos + historico})
    aviso = RAIZ / "alerta.md"
    if alertas_novos:
        linhas = [f"@marcoscacau, notícias novas sobre livros dos autores que você acompanha ({hoje}):", ""]
        for a in alertas_novos:
            linhas.append(f"- **{', '.join(a['autores'])}** — [{a['titulo']}]({a['link']}) ({a['fonte']})")
            for t in a["titulos_fora_da_estante"]:
                linhas.append(f"  - título fora da estante: **{t}** — vale pôr em `estante.json`?")
        linhas += ["", "[Abrir o Radar](https://marcoscacau.github.io/radar-literario/?secao=estante)"]
        aviso.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    elif aviso.exists():
        aviso.unlink()

    # Trecho para o Diário do Obsidian, um por dia (o modelo busca pela data da nota).
    obsidian = API / "obsidian"
    obsidian.mkdir(parents=True, exist_ok=True)
    por_id_semana = {i["id"]: i for i in semana}
    (obsidian / f"{hoje}.md").write_text(obsidian_md(pacote_hoje, padroes, por_id_semana), encoding="utf-8")
    for arq in obsidian.glob("*.md"):
        if arq.stem < corte:
            arq.unlink()

    n_pv = len(pacote_hoje["secoes"]["para-voce"])
    print(f"\n{len(itens_hoje)} novidades em {hoje} ({n_pv} para você); {len(semana)} na semana; "
          f"{len(padroes['termos'])} nomes em alta; {len(alertas_novos)} alertas de lançamento.")

    # Alarme: com metade das fontes fora, a execução falha e o GitHub avisa por e-mail.
    falhas = [s["nome"] for s in status if not s["ok"]]
    if len(falhas) * 2 >= len(status):
        sys.exit(f"{len(falhas)} de {len(status)} fontes falharam: {', '.join(falhas)}")


if __name__ == "__main__":
    main()
