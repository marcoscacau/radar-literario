"""Radar Literário — promoções do Kindle (eBooks, Kindle Unlimited, campanhas e aparelhos).

A Amazon não tem API aberta de ofertas e bloqueia leitura automática, então as promoções vêm
das comunidades onde as pessoas postam: Pelando (só as ofertas ainda ativas) e Gatry (pela data
do post). As que batem com a estante e os temas do perfil ganham "para você" e sobem na lista.

Grava docs/api/kindle.json (últimos 30 dias) e acrescenta as novidades "para você" e os eBooks
grátis em avisos.json, para o ntfy.

Uso: python coletor/kindle.py      (depois de coletar.py, que cria avisos.json)
"""
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coletar import API, BRASILIA, RAIZ, carregar_perfil, gravar_json, ler_data, ler_feed, ler_json, pontuar, sem_acento  # noqa: E402
from coletar import baixar as baixar_feed  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9"}
DIAS_RECENTE = 14         # oferta postada há mais tempo que isso não entra
DIAS_HISTORICO = 30
BUSCAS_PELANDO = ["ebook", "ebook-kindle", "kindle", "kindle-unlimited"]
BUSCAS_GATRY = ["kindle", "ebook", "e-book"]

# O que é cada oferta (sem acento). "ebook" com fronteira, para "notebook" não entrar.
RE_CAMPANHA = re.compile(r"encha seu kindle|kindle week|mega desconto|semana do livro|black friday.*(e-?books?|kindle)|e-?books? (a partir|ate|por) r?\$")
RE_KU = re.compile(r"kindle unlimited|\bku\b|prime reading")
RE_APARELHO = re.compile(r"\b\d+ ?gb\b|kindle (paperwhite|scribe|colorsoft|oasis|basic)|\bgeracao\b|\b\d+(th|a|ª) gen|paperwhite|e-?reader|"
                         r"leitor de e-?books?|capa (para |p/ )?(o )?kindle|pocketbook|kobo")
RE_EBOOK = re.compile(r"(?<![a-z])e-?books?(?![a-z])|ebook kindle|livro digital")
MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}


def baixar(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def tipo_de(titulo):
    t = sem_acento(titulo)
    if RE_CAMPANHA.search(t):
        return "campanha"
    if RE_KU.search(t):
        return "unlimited"
    if RE_APARELHO.search(t) and not RE_EBOOK.search(t):
        return "aparelho" if re.search(r"kindle|e-?reader|leitor de e-?book|kobo|pocketbook", t) else None   # "Notebook 512GB" não
    if RE_EBOOK.search(t) or "kindle" in t:
        return "ebook"
    return None


def preco(texto):
    """"R$ 1.019,90" -> 1019.9; "Grátis" -> 0."""
    if not texto:
        return 0.0
    try:
        return float(texto.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def idade_pelando(texto, agora):
    """"2 min", "3 h", "5 dias", "09 set" -> data do post."""
    t = sem_acento(texto or "").strip()
    m = re.match(r"(\d+)\s*(min|h|dias?)", t)
    if m:
        n, u = int(m[1]), m[2]
        return agora - (timedelta(minutes=n) if u == "min" else timedelta(hours=n) if u == "h" else timedelta(days=n))
    m = re.match(r"(\d{1,2}) (\w{3})", t)
    if m and m[2] in MESES:
        try:
            d = agora.replace(month=MESES[m[2]], day=int(m[1]))
        except ValueError:
            return None
        return d if d <= agora else d.replace(year=d.year - 1)
    return None


def pelando(termo, agora):
    t = baixar(f"https://www.pelando.com.br/busca/{termo}")
    cartao = re.compile(r'<a href="(https://www\.pelando\.com\.br/d/[^"]+)" data-deal-id="([^"]+)" data-inactive="(true|false)">([^<]+)</a>'
                        r'[\s\S]{0,400}?_timestamp[^>]*>(?:<i[\s\S]*?</i>)?([^<]*)<'
                        r'[\s\S]{0,400}?(?:Vendido por </span><a[^>]*>([^<]+)</a>)?'
                        r'[\s\S]{0,700}?(?:<small>R\$</small>([\d.,]+)|(Grátis))')
    for link, deal, inativa, titulo, quando, loja, valor, gratis in cartao.findall(t):
        if inativa == "true":
            continue
        yield {"fonte": "Pelando", "id_fonte": deal, "titulo": html.unescape(titulo).strip(), "link": link,
               "loja": html.unescape(loja or "").strip(), "preco": 0.0 if gratis else preco(valor),
               "postado": idade_pelando(quando, agora), "nota": ""}


def gatry(termo, agora):
    t = baixar(f"https://gatry.com/promocoes?q={termo}")
    for a in re.findall(r"<article>([\s\S]*?)</article>", t):
        titulo = re.search(r"<h3><a [^>]*>([^<]+)</a>", a)
        pagina = re.search(r'href="(/promocoes/(\d+)/[^"?]+)', a)
        if not titulo or not pagina:
            continue
        datas = re.findall(r'class="date"[^>]*title="(\d{2})/(\d{2})/(\d{4}) às (\d{2}):(\d{2})', a)
        postado = None
        if datas:   # o último é o do post (o primeiro, no celular, às vezes vem trocado)
            d, m, y, hh, mm = map(int, datas[-1])
            postado = datetime(y, m, d, hh, mm, tzinfo=BRASILIA)
        valor = re.search(r'class="price">\s*R\$\s*([\d.,]+)', a)
        loja = re.search(r"Ir para</span>\s*([^<]+)</a>", a)
        nota = re.search(r'class="comment[^"]*">\s*([^<]+?)\s*</p>', a)
        yield {"fonte": "Gatry", "id_fonte": pagina[2], "titulo": html.unescape(titulo[1]).strip(),
               "link": "https://gatry.com" + pagina[1], "loja": html.unescape(loja[1]).strip() if loja else "",
               "preco": preco(valor[1]) if valor else None, "postado": postado,
               "nota": html.unescape(nota[1]).strip() if nota else ""}


NOTICIAS = ("https://news.google.com/rss/search?q=(kindle+OR+ebook+OR+e-book)+(gr%C3%A1tis+OR+promo%C3%A7%C3%A3o+OR+desconto+OR+"
            "%22Kindle+Unlimited%22+OR+%22Encha+seu+Kindle%22)+when:3d&hl=pt-BR&gl=BR&ceid=BR:pt-419")


def imprensa(_termo, agora):
    """Matérias sobre eBooks grátis e campanhas da Amazon (o Google Notícias responde também no GitHub,
    o que não acontece com o Pelando, que recusa os servidores do GitHub)."""
    for b in ler_feed(baixar_feed(NOTICIAS)):
        titulo, veiculo = (b["titulo"] or "").strip(), (b.get("veiculo") or "").strip()
        if veiculo and titulo.endswith(" - " + veiculo):
            titulo = titulo[: -len(veiculo) - 3].rstrip()
        t = sem_acento(titulo)
        if not re.search(r"kindle|(?<![a-z])e-?books?(?![a-z])", t) or not re.search(r"gratis|promo|descont|unlimited|encha|oferta|r\$", t):
            continue
        yield {"fonte": veiculo or "Google Notícias", "id_fonte": b["link"], "titulo": titulo, "link": b["link"], "loja": "",
               "preco": None, "postado": ler_data(b["data"]), "nota": "", "tipo": "imprensa"}


def main():
    agora = datetime.now(BRASILIA)
    perfil = carregar_perfil()
    pontos_min = perfil["pontos"]["minimo"]
    status, achadas = [], {}
    for nome, buscar, termos in (("Pelando", pelando, BUSCAS_PELANDO), ("Gatry", gatry, BUSCAS_GATRY), ("Imprensa", imprensa, [None])):
        n, erro = 0, None
        for termo in termos:
            try:
                for o in buscar(termo, agora):
                    tipo = o.get("tipo") or tipo_de(o["titulo"])
                    if not tipo or not o["postado"] or o["postado"] < agora - timedelta(days=DIAS_RECENTE):
                        continue
                    o["id"] = hashlib.sha1(f"{o['fonte']}:{o['id_fonte']}".encode()).hexdigest()[:12]
                    o["tipo"] = tipo
                    achadas.setdefault(o["id"], o)
                    n += 1
            except Exception as e:
                erro = f"{type(e).__name__}: {e}"[:160]
        status.append({"fonte": nome, "ok": erro is None, "erro": erro, "ofertas": n})
        print(f"{'ok   ' if erro is None else 'ERRO '} {nome:<8} {n:3d} ofertas recentes" + (f"  ({erro})" if erro else ""))

    anteriores = {o["id"]: o for o in ler_json(API / "kindle.json", {}).get("ofertas", [])}
    corte = (agora - timedelta(days=DIAS_HISTORICO)).isoformat()
    novas, ofertas = [], []
    for o in achadas.values():
        nota, autores, temas = pontuar(sem_acento(o["titulo"] + " " + o["nota"]), perfil)
        item = {"id": o["id"], "titulo": o["titulo"], "link": o["link"], "fonte": o["fonte"], "loja": o["loja"],
                "preco": o["preco"], "tipo": o["tipo"], "nota": o["nota"],
                "postado_em": o["postado"].isoformat(timespec="minutes"),
                "visto_em": anteriores.get(o["id"], {}).get("visto_em") or agora.isoformat(timespec="minutes"),
                "ultima_vez": agora.isoformat(timespec="minutes"),   # some das buscas = expirou ou ficou para trás
                "para_voce": {"pontos": nota, "autores": autores, "temas": temas}}
        if o["id"] not in anteriores:
            novas.append(item)
        ofertas.append(item)
    # O que saiu das buscas (expirou ou ficou para trás) continua no histórico até completar 30 dias.
    ofertas += [o for i, o in anteriores.items() if i not in achadas and o["postado_em"] >= corte]
    ofertas.sort(key=lambda o: (o["para_voce"]["pontos"] >= pontos_min, o["postado_em"]), reverse=True)
    gravar_json(API / "kindle.json", {"gerado_em": agora.isoformat(timespec="seconds"), "fontes": status,
                                     "total": len(ofertas), "ofertas": ofertas})

    # Avisos no celular: o que bate com o perfil, eBook grátis e campanhas (o resto fica só na aba).
    importantes = [o for o in novas if o["para_voce"]["pontos"] >= pontos_min or o["tipo"] in ("campanha", "unlimited")
                   or (o["tipo"] == "ebook" and o["preco"] == 0)
                   or (o["tipo"] == "imprensa" and re.search(r"gratis|encha seu kindle", sem_acento(o["titulo"])))]
    if importantes:
        avisos = ler_json(RAIZ / "avisos.json", {})
        avisos["kindle"] = [{"titulo": o["titulo"], "link": o["link"], "preco": o["preco"], "fonte": o["fonte"],
                             "para_voce": o["para_voce"]["autores"]} for o in importantes]
        gravar_json(RAIZ / "avisos.json", avisos)
    print(f"{len(ofertas)} ofertas no histórico, {len(novas)} novas, {len(importantes)} para avisar.")


if __name__ == "__main__":
    main()
