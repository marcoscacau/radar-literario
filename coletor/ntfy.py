"""Radar Literário — avisos no celular pelo ntfy (app grátis, sem conta).

Lê avisos.json (o que o coletor achou de novo nesta execução) e manda uma notificação
por evento em Sergipe e por lançamento. Mais de 5 de uma vez viram uma notificação só.

Uso: NTFY_TOPICO=... python coletor/ntfy.py            (envia o que houver em avisos.json)
     NTFY_TOPICO=... python coletor/ntfy.py --teste    (envia uma notificação de teste)
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = "https://ntfy.sh"
SITE = "https://marcoscacau.github.io/radar-literario/"
MAX_SEPARADAS = 5


def enviar(topico, titulo, mensagem, link=SITE, tags=("books",), prioridade=3):
    corpo = {"topic": topico, "title": titulo, "message": mensagem[:3500], "click": link,
             "tags": list(tags), "priority": prioridade}
    req = urllib.request.Request(SERVIDOR, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "RadarLiterario/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def quando(q):
    if not q:
        return ""
    br = lambda iso: f"{iso[8:10]}/{iso[5:7]}"
    return "📅 " + (br(q["inicio"]) if q["inicio"] == q["fim"] else f"{br(q['inicio'])} a {br(q['fim'])}") + "\n"


def main():
    topico = os.environ.get("NTFY_TOPICO", "").strip()
    if not topico:
        print("NTFY_TOPICO não configurado; nada enviado.")
        return
    if "--teste" in sys.argv:
        enviar(topico, "Radar Literário ligado", "Daqui para frente, eventos literários em Sergipe e lançamentos "
               "dos seus autores chegam aqui.", tags=("books", "white_check_mark"))
        print("Teste enviado.")
        return
    try:
        avisos = json.loads((RAIZ / "avisos.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("Sem avisos.json; nada enviado.")
        return
    eventos, lancamentos = avisos.get("eventos", []), avisos.get("lancamentos", [])
    if len(eventos) + len(lancamentos) > MAX_SEPARADAS:
        linhas = [f"📍 {e['titulo']}" for e in eventos] + [f"📚 {a['titulo']}" for a in lancamentos]
        enviar(topico, f"Radar Literário: {len(linhas)} novidades", "\n".join(linhas), link=SITE + "?secao=sergipe")
        print(f"1 resumo com {len(linhas)} novidades enviado.")
        return
    for e in eventos:
        enviar(topico, "Evento literário em Sergipe", f"{e['titulo']}\n{quando(e.get('quando'))}{e['fonte']}",
               link=e["link"], tags=("round_pushpin",), prioridade=4)
    for a in lancamentos:
        enviar(topico, f"Lançamento: {', '.join(a['autores'])}", f"{a['titulo']}\n{a['fonte']}",
               link=a["link"], tags=("books",), prioridade=4)
    print(f"{len(eventos)} eventos e {len(lancamentos)} lançamentos enviados.")


if __name__ == "__main__":
    main()
