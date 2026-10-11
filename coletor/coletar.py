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
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"

# Sergipe: a notícia precisa citar um lugar ou instituição de Sergipe E um evento literário.
RE_SERGIPE = re.compile(r"(?<![\w-])(sergipe|sergipan[oa]s?|aracaju|aracajuano|sao cristovao|itabaiana|itabaianinha|lagarto|"
                        r"estancia|nossa senhora do socorro|bienal do livro de socorro|propria|laranjeiras|barra dos coqueiros|"
                        r"tobias barreto|simao dias|caninde de sao francisco|nossa senhora da gloria|ufs|"
                        r"academia sergipana|ases|riomar aracaju|shopping jardins|fasc|epifanio doria|epiphanio dorea)(?![\w-])")
RE_EVENTO_LIT = re.compile(r"(?<![\w-])(livro|livros|literatura|literari[oa]s?|sarau|saraus|poesia|poemas?|poetas?|slam|"
                           r"autografos|lancamento do livro|lanca livro|lancam livro|bienal|feira de livros|feira do livro|"
                           r"festa literaria|festival literario|salao de literatura|clube de leitura|roda de leitura|"
                           r"contacao de historias|escritor|escritora|escritores|escritoras|cordel|academia sergipana de letras|"
                           r"biblioteca)(?![\w-])")
# Para recortar o trecho de uma agenda: só termos que não deixam dúvida ("poesia" de um show não conta).
RE_EVENTO_FORTE = re.compile(r"(?<![\w-])(livro|livros|literatura|literari[oa]s?|sarau|saraus|autografos|feira de livros|"
                             r"feira do livro|festa literaria|festival literario|salao de literatura|clube de leitura|"
                             r"roda de leitura|contacao de historias|slam|cordel|escritor|escritora|escritores|escritoras)(?![\w-])")

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


# ---------- Data do evento (para a agenda .ics) ----------

MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]
MES = "(" + "|".join(MESES) + ")"
ANO = r"(?: de (20\d\d))?"
RE_FAIXA_MESES = re.compile(rf"\b(\d{{1,2}}) de {MES} (?:a|ate) (\d{{1,2}}) de {MES}{ANO}")
RE_FAIXA = re.compile(rf"\b(\d{{1,2}}) (?:a|e|ate) (\d{{1,2}}) de {MES}{ANO}")
RE_FAIXA_NUM = re.compile(r"(?<![\d/])(\d{1,2})(?:/(\d{1,2}))? (?:a|ate) (\d{1,2})/(\d{1,2})(?:/(20\d\d))?(?![\d/])")
RE_DIA = re.compile(rf"\b(\d{{1,2}})(?:º|o)? de {MES}{ANO}")
RE_DIA_NUM = re.compile(r"(?<![\d/,.])(\d{1,2})/(\d{1,2})(?:/(20\d\d))?(?![\d/%]|[.,]\d)")
SEMANA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
RE_DIA_SEMANA = re.compile(r"\b(?:neste|nesta|no proximo|na proxima|proximo|proxima) (fim de semana|"
                           + "|".join(SEMANA) + r")\b")


def data_br(iso):
    return f"{iso[8:10]}/{iso[5:7]}" + ("" if iso[:4] == str(datetime.now(BRASILIA).year) else f"/{iso[:4]}")


def datas_do_evento(texto, base):
    """Primeira data de evento citada no texto (sem acento), relativa à data da notícia.
    Faixa ("20 a 22 de novembro") vale mais que dia solto, porque o dia solto costuma ser outra coisa
    ("a programação sai no dia 15"). Devolve (início, fim) ou None."""
    def dia(d, m, ano=None):
        try:
            x = datetime(int(ano) if ano else base.year, int(m), int(d)).date()
        except ValueError:
            return None
        if not ano and x < base - timedelta(days=45):     # "5 de janeiro" lido em dezembro é do ano que vem;
            seguinte = x.replace(year=x.year + 1)         # "12 de março" lido em outubro já passou
            return seguinte if seguinte <= base + timedelta(days=120) else None
        return x

    def valida(ini, fim):
        return (ini and fim and ini <= fim <= ini + timedelta(days=31)
                and fim >= base - timedelta(days=1) and ini <= base + timedelta(days=240))

    candidatos = []
    for m in RE_FAIXA_MESES.finditer(texto):
        candidatos.append((m.start(), dia(m[1], MESES.index(m[2]) + 1, m[5]), dia(m[3], MESES.index(m[4]) + 1, m[5])))
    for m in RE_FAIXA.finditer(texto):
        mes = MESES.index(m[3]) + 1
        candidatos.append((m.start(), dia(m[1], mes, m[4]), dia(m[2], mes, m[4])))
    for m in RE_FAIXA_NUM.finditer(texto):
        candidatos.append((m.start(), dia(m[1], m[2] or m[4], m[5]), dia(m[3], m[4], m[5])))
    for _, ini, fim in sorted(candidatos, key=lambda c: c[0]):
        if valida(ini, fim):
            return ini, fim

    soltos = [(m.start(), dia(m[1], MESES.index(m[2]) + 1, m[3])) for m in RE_DIA.finditer(texto)]
    soltos += [(m.start(), dia(m[1], m[2], m[3])) for m in RE_DIA_NUM.finditer(texto)]
    for _, d in sorted(soltos, key=lambda c: c[0]):
        if valida(d, d):
            return d, d

    m = RE_DIA_SEMANA.search(texto)
    if m:
        if m[1] == "fim de semana":
            sab = base + timedelta(days=(5 - base.weekday()) % 7)
            return sab, sab + timedelta(days=1)
        d = base + timedelta(days=(SEMANA.index(m[1]) - base.weekday()) % 7)
        return d, d
    return None


def quando_do_evento(i):
    if i.get("evento"):
        return {"inicio": i["evento"]["inicio"], "fim": i["evento"]["fim"], "origem": "sympla"}
    base = datetime.fromisoformat(i["publicado_em"]).date() if i.get("publicado_em") else \
        datetime.fromisoformat(i.get("dia") or datetime.now(BRASILIA).date().isoformat()).date()
    achou = datas_do_evento(sem_acento(f"{i['titulo']} {i['resumo']}"), base)
    if not achou:
        return None
    return {"inicio": achou[0].isoformat(), "fim": achou[1].isoformat(), "origem": "texto"}


def texto_quando(q, antes=""):
    if not q:
        return ""
    return antes + "📅 " + (data_br(q["inicio"]) if q["inicio"] == q["fim"] else f"{data_br(q['inicio'])} a {data_br(q['fim'])}")


def ics_texto(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_linha(linha):
    """Linhas de no máximo 75 bytes, como a norma pede (a continuação começa com espaço)."""
    partes, atual = [], ""
    for c in linha:
        if len((atual + c).encode("utf-8")) > (75 if not partes else 74):
            partes.append(atual)
            atual = ""
        atual += c
    partes.append(atual)
    return "\r\n ".join(partes)


def agenda_ics(eventos, agora):
    carimbo = agora.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    linhas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Radar Literario//Sergipe//PT", "CALSCALE:GREGORIAN",
              "METHOD:PUBLISH", "X-WR-CALNAME:Radar Literário – Sergipe", "X-WR-TIMEZONE:America/Sao_Paulo",
              "X-WR-CALDESC:Eventos literários em Sergipe encontrados pelo Radar Literário",
              "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H"]
    ja = set()
    for i in eventos:
        q = i.get("quando")
        if not q:
            continue
        chave = (q["inicio"], q["fim"], sem_acento(i["titulo"])[:40])
        if chave in ja:
            continue
        ja.add(chave)
        fim = (datetime.fromisoformat(q["fim"]) + timedelta(days=1)).strftime("%Y%m%d")   # no .ics o fim é exclusivo
        nota = ("" if q["origem"] == "sympla" else
                "\n\nData lida automaticamente do texto da notícia: confira no link.")
        linhas += ["BEGIN:VEVENT", f"UID:{i['id']}@radar-literario", f"DTSTAMP:{carimbo}",
                   f"DTSTART;VALUE=DATE:{q['inicio'].replace('-', '')}", f"DTEND;VALUE=DATE:{fim}",
                   f"SUMMARY:{ics_texto(i['titulo'])}",
                   f"DESCRIPTION:{ics_texto((i['resumo'] + chr(10) + chr(10) if i['resumo'] else '') + 'Fonte: ' + i['fonte'] + chr(10) + i['link'] + nota)}",
                   f"URL:{i['link']}", "TRANSP:TRANSPARENT"]
        if i.get("evento", {}).get("local"):
            linhas.append(f"LOCATION:{ics_texto(i['evento']['local'])}")
        linhas.append("END:VEVENT")
    linhas.append("END:VCALENDAR")
    return "\r\n".join(ics_linha(l) for l in linhas) + "\r\n"


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
            "conteudo": it.findtext(CONTENT + "encoded"),
        })
    for it in raiz.iter(RSS1 + "item"):              # RSS 1.0 / RDF
        itens.append({
            "titulo": it.findtext(RSS1 + "title"),
            "link": it.findtext(RSS1 + "link"),
            "data": it.findtext(DC + "date"),
            "resumo": it.findtext(RSS1 + "description"),
            "veiculo": None,
            "conteudo": None,
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
            "conteudo": it.findtext(ATOM + "content"),
        })
    return itens


SYMPLA = "https://www.sympla.com.br/api/discovery-bff/search/category-type"


def ler_sympla(fonte):
    """Eventos à venda no Sympla perto de Aracaju (a mesma busca da página de eventos do site deles).
    A busca não filtra por estado: o que não for de Sergipe, for online ou já tiver acabado fica de fora."""
    hoje = datetime.now(BRASILIA).date().isoformat()
    vistos, itens = set(), []
    for termo in fonte["termos"]:
        corpo = {"q": termo, "location": fonte["coordenadas"], "limit": 50, "page": 1, "type": "normal",
                 "sort": "location-score", "need_pay": "1", "has_banner": "0", "service": "/v4/search",
                 "only": "name,start_date,end_date,location,id,url,type"}
        req = urllib.request.Request(SYMPLA, data=json.dumps(corpo).encode(), method="POST", headers={
            "User-Agent": "Mozilla/5.0 (compatible; RadarLiterario/1.0)", "Content-Type": "application/json",
            "Accept": "application/json", "Origin": "https://www.sympla.com.br"})
        with urllib.request.urlopen(req, timeout=25) as r:
            dados = json.loads(r.read())
        for e in dados.get("data", []):
            local = e.get("location") or {}
            inicio, fim = (e.get("start_date") or "")[:10], (e.get("end_date") or e.get("start_date") or "")[:10]
            if (e.get("id") in vistos or local.get("state") != "SE" or "online" in sem_acento(local.get("name") or "")
                    or not inicio or fim < hoje):
                continue
            vistos.add(e["id"])
            onde = ", ".join(x for x in (local.get("name"), local.get("city")) if x)
            quando = data_br(inicio) if fim == inicio else f"{data_br(inicio)} a {data_br(fim)}"
            itens.append({
                "titulo": e["name"], "link": e["url"], "data": datetime.now(BRASILIA).isoformat(),
                "resumo": f"{quando} · {onde} (ingressos no Sympla)", "veiculo": None,
                "conteudo": f"{e['name']}. {onde}, Sergipe.",
                "evento": {"inicio": inicio, "fim": fim, "local": onde},
            })
    return itens


def coletar_fonte(fonte, perfil):
    try:
        brutos = ler_sympla(fonte) if fonte.get("tipo") == "sympla" else ler_feed(baixar(fonte["url"]))
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
        resumo = re.sub(r"\s*O post .+? apareceu primeiro em .+$", "", limpar(b["resumo"]))   # rodapé do WordPress
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
        if fonte.get("local") == "sergipe":
            completo = limpar(b.get("conteudo"), limite=0)
            tudo = sem_acento(f"{titulo} {resumo} {completo} {nome_fonte}")   # "Prefeitura de Aracaju" às vezes só aparece como veículo
            if not (RE_SERGIPE.search(tudo) and RE_EVENTO_LIT.search(tudo)):
                continue
            if fonte.get("so_titulos_com") and fonte["so_titulos_com"] not in sem_acento(titulo):
                continue                            # da Mangue, só as agendas culturais
            if fonte.get("trecho") and completo:   # agenda da semana: fica só o trecho do evento literário
                frases = re.split(r"(?<=[.!?])\s+|\s+[•●▪]\s+", completo)
                literarias = [f for f in frases if RE_EVENTO_FORTE.search(sem_acento(f))]
                if not literarias:
                    continue
                resumo = limpar(" ".join(literarias[:3]))
            tags.append("sergipe")
        pontos, motivos, temas = pontuar(texto, perfil)
        data = ler_data(b["data"])
        extra = {"evento": b["evento"]} if b.get("evento") else {}
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
            **extra,
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
        "sergipe": [i["id"] for i in itens if "sergipe" in i["tags"]],
        "premios-lancamentos": [i["id"] for i in itens if set(i["tags"]) & {"premios", "lancamentos"}],
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
            limite_fonte = agora - timedelta(days=fonte["janela_dias"]) if fonte.get("janela_dias") else limite
            if i["publicado_em"] and datetime.fromisoformat(i["publicado_em"]) < limite_fonte:
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
        if "sergipe" in i["tags"]:
            i["quando"] = quando_do_evento(i)

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
    # Eventos literários em Sergipe: todo evento novo também vira aviso, e o histórico de 90 dias fica em sergipe.json.
    eventos_novos = [i for i in novos_agora if "sergipe" in i["tags"]]
    eventos = []
    for d in datas:
        for i in ler_json(DIAS / f"{d}.json", {}).get("itens", []):
            if "sergipe" in i.get("tags", []):
                eventos.append({**i, "dia": d})
    for e in eventos:
        e["quando"] = quando_do_evento(e)
    gravar_json(API / "sergipe.json", {"gerado_em": gerado_em, "total": len(eventos), "eventos": eventos})
    # Agenda para assinar no Google Agenda / celular: só o que tem data reconhecível.
    (API / "sergipe.ics").write_bytes(agenda_ics(eventos, agora).encode("utf-8"))
    por_id = {e["id"]: e for e in eventos}
    # O que é novo nesta execução, para os avisos no celular (ntfy.py); não vai para o repositório.
    gravar_json(RAIZ / "avisos.json", {
        "eventos": [{"titulo": i["titulo"], "link": i["link"], "resumo": i["resumo"], "fonte": i["fonte"],
                     "quando": por_id.get(i["id"], {}).get("quando")} for i in eventos_novos],
        "lancamentos": [{"titulo": a["titulo"], "link": a["link"], "autores": a["autores"], "fonte": a["fonte"]}
                        for a in alertas_novos],
    })

    aviso = RAIZ / "alerta.md"
    if alertas_novos or eventos_novos:
        linhas = [f"@marcoscacau, novidades do Radar Literário ({hoje}):", ""]
        if eventos_novos:
            linhas += ["### Eventos literários em Sergipe", ""]
            for i in eventos_novos:
                linhas.append(f"- [{i['titulo']}]({i['link']}) ({i['fonte']})" + texto_quando(por_id.get(i["id"], {}).get("quando"), " — ")
                              + (f"\n  > {i['resumo']}" if i["resumo"] else ""))
            linhas.append("")
        if alertas_novos:
            linhas += ["### Livros novos dos autores que você acompanha", ""]
            for a in alertas_novos:
                linhas.append(f"- **{', '.join(a['autores'])}** — [{a['titulo']}]({a['link']}) ({a['fonte']})")
                for t in a["titulos_fora_da_estante"]:
                    linhas.append(f"  - título fora da estante: **{t}** — vale pôr em `estante.json`?")
            linhas.append("")
        linhas += ["[Abrir o Radar](https://marcoscacau.github.io/radar-literario/)"]
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
