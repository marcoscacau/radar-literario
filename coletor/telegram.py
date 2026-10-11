"""Radar Literário — mensagem matinal no Telegram.

Manda as 5 melhores do "Para você" e os alertas de lançamento do dia; aos
domingos, também o resumo da semana. Lê o que coletar.py acabou de gravar.

Precisa de TELEGRAM_TOKEN e TELEGRAM_CHAT_ID no ambiente (segredos do GitHub).
Sem eles, não faz nada. Só biblioteca padrão.
"""
import html
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

API = Path(__file__).resolve().parent.parent / "docs" / "api"
SITE = "https://marcoscacau.github.io/radar-literario/"


def ler(nome):
    return json.loads((API / nome).read_text(encoding="utf-8"))


def e(texto):
    return html.escape(texto, quote=False)


def mensagem_do_dia():
    hoje = ler("hoje.json")
    por_id = {i["id"]: i for i in hoje["itens"]}
    linhas = [f"📚 <b>Radar Literário</b> · {date.fromisoformat(hoje['data']).strftime('%d/%m')}", ""]
    sergipe = hoje["secoes"].get("sergipe", [])
    if sergipe:
        linhas.append("📍 <b>Em Sergipe</b>")
        for k in sergipe[:8]:
            i = por_id[k]
            linhas.append(f"• <a href=\"{e(i['link'])}\">{e(i['titulo'])}</a>")
        linhas.append("")
    ids = hoje["secoes"].get("para-voce", [])[:5]
    if ids:
        linhas.append("<b>Para você</b>")
        for k in ids:
            i = por_id[k]
            motivo = ", ".join(i["para_voce"]["autores"] + i["para_voce"]["temas"])
            linhas.append(f"• <a href=\"{e(i['link'])}\">{e(i['titulo'])}</a>" + (f" <i>({e(motivo)})</i>" if motivo else ""))
    else:
        linhas.append("Nada da sua estante hoje.")

    alertas = [a for a in ler("alertas.json")["alertas"] if a.get("dia") == hoje["data"]]
    if alertas:
        linhas += ["", "🔔 <b>Lançamentos</b>"]
        for a in alertas[:5]:
            linhas.append(f"• {e(', '.join(a['autores']))}: <a href=\"{e(a['link'])}\">{e(a['titulo'])}</a>")

    alta = ler("em-alta.json")["termos"][:3]
    if alta:
        linhas += ["", "📈 Em alta: " + e(", ".join(t["termo"] for t in alta))]
    linhas += ["", f"<a href=\"{SITE}\">Edição completa</a> · {hoje['total']} notícias"]
    return "\n".join(linhas)


def mensagem_da_semana():
    r = ler("resumo-semana.json")
    semana = {i["id"]: i for i in ler("semana.json")["itens"]}
    linhas = ["🗞 <b>Edição de domingo — a semana</b>", ""]
    if r["subindo"]:
        linhas.append("<b>Subindo</b>: " + e(", ".join(s["termo"] for s in r["subindo"])))
    if r["em_alta"]:
        linhas.append("<b>Mais citados</b>: " + e(", ".join(r["em_alta"])))
    if r["autores"]:
        linhas.append("<b>Sua estante</b>: " + e(", ".join(f"{a['nome']} ({a['noticias']})" for a in r["autores"][:6])))
    if r["destaques"]:
        linhas += ["", "<b>Destaques</b>"]
        for k in r["destaques"][:6]:
            i = semana.get(k)
            if i:
                linhas.append(f"• <a href=\"{e(i['link'])}\">{e(i['titulo'])}</a>")
    linhas += ["", f"<a href=\"{SITE}?secao=semana\">A semana inteira</a> · {r['total']} notícias"]
    return "\n".join(linhas)


def caber(texto, limite=4000):
    """O Telegram aceita até 4096 caracteres: tira itens do fim das listas até caber, avisando quantos ficaram de fora."""
    linhas = texto.split("\n")
    tirados = 0
    while len("\n".join(linhas)) > limite:
        k = max(i for i, l in enumerate(linhas) if l.startswith("• "))
        del linhas[k]
        tirados += 1
    if tirados:
        linhas.insert(len(linhas) - 1, f"<i>(+{tirados} no site)</i>")
    return "\n".join(linhas)


def enviar(token, chat_id, texto):
    dados = urllib.parse.urlencode({"chat_id": chat_id, "text": texto, "parse_mode": "HTML",
                                    "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", dados, timeout=30) as r:
        resposta = json.load(r)
    if not resposta.get("ok"):
        raise RuntimeError(resposta)


def main():
    mensagens = [mensagem_do_dia()]
    if date.fromisoformat(ler("hoje.json")["data"]).weekday() == 6 or "--semana" in sys.argv:
        mensagens.append(mensagem_da_semana())
    mensagens = [caber(m) for m in mensagens]
    if "--mostrar" in sys.argv:   # só mostra, não envia
        print("\n\n".join(mensagens))
        return
    token, chat_id = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram não configurado (faltam TELEGRAM_TOKEN/TELEGRAM_CHAT_ID); nada a enviar.")
        return
    for m in mensagens:
        enviar(token, chat_id, m)
    print(f"Telegram: {len(mensagens)} mensagem(ns) enviada(s).")


if __name__ == "__main__":
    main()
