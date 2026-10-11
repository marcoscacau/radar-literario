# Radar Literário

O que está acontecendo no mundo literário, atualizado sozinho todo dia às 06:00 (Brasília).

Todo dia uma tarefa do GitHub Actions lê as fontes de `fontes.json`, separa as novidades e publica uma página para leitura e uma API em JSON pelo GitHub Pages. Nenhum computador precisa ficar ligado e não tem custo.

## A API

Com o GitHub Pages ligado, os endereços são `https://SEU-USUARIO.github.io/radar-literario/...`:

| Endereço | O que traz |
|---|---|
| `api/hoje.json` | novidades de hoje |
| `api/semana.json` | últimos 7 dias (cada item tem o campo `dia`) |
| `api/em-alta.json` | nomes citados por mais fontes diferentes na semana, com menções por dia |
| `api/dias/AAAA-MM-DD.json` | um dia específico (guarda 90 dias) |
| `api/indice.json` | lista dos dias disponíveis |
| `api/fontes.json` | situação de cada fonte na última coleta (bom para saber se alguma parou) |

Cada notícia:

```json
{
  "id": "a1b2c3d4e5f6",
  "titulo": "Anne Carson vence o Nobel de Literatura 2026",
  "link": "https://...",
  "resumo": "...",
  "fonte": "Quatro Cinco Um",
  "fonte_id": "quatrocincoum",
  "grupo": "brasil-portugal",
  "idioma": "pt",
  "publicado_em": "2026-10-08T08:21-03:00",
  "tags": ["premios"],
  "para_voce": { "pontos": 3, "autores": ["Dan Brown"], "temas": ["suspense"] }
}
```

`secoes` traz os `id` de cada seção: `para-voce`, `premios-lancamentos`, `brasil-portugal` e `internacional`.

## Para você

`perfil.json` é o perfil de leitura, montado a partir da estante e dos textos de [marcoscacau.github.io](https://marcoscacau.github.io). Cada notícia ganha pontos:

- autor da estante (Augusto Cury, Dan Brown, Tolkien, C. S. Lewis, Kafka, Gógol, Púchkin, Sagan, Kaku, Aleksiévitch…): **3**
- autor vizinho (Dostoiévski, Tolstói, Chesterton, Rovelli, Hawking, Le Guin…): **2**
- tema (física e ciência, fé e teologia, filosofia, literatura russa, fantasia e ficção científica, suspense, mente e emoções): **1** cada, até 2, e mais **1** se o tema vier junto com livro/romance/book
- notícia de filme, série ou jogo: **−2** (o radar é de livros)

Com 2 pontos ou mais, a notícia entra em "Para você", com no máximo 3 por autor por dia. Leu um autor novo? É só pôr no `perfil.json`.

## Em alta

Nomes de duas a quatro palavras com inicial maiúscula (pessoas, prêmios, obras) citados por **3 fontes diferentes ou mais** nos últimos 7 dias, com as menções de cada dia. Serve para perceber o padrão antes que vire manchete.

## Sergipe

A aba "Sergipe" e o `api/sergipe.json` (histórico de 90 dias) trazem os eventos literários do estado: feiras, bienais (Itabaiana, Lagarto, Socorro), o Salão de Literatura do FASC, saraus, lançamentos e sessões de autógrafos.

- **Fontes:** a agenda cultural semanal da Mangue Jornalismo (da agenda, fica só o trecho literário), o Infonet, o FaxAju, o g1 Sergipe e duas buscas do Google Notícias.
- **Filtro:** a notícia só entra se citar um lugar ou instituição de Sergipe **e** um termo de evento literário.
- **Avisos:** cada evento novo vai para o e-mail (issue no GitHub) e abre a mensagem do Telegram.

## Estante

`estante.json` guarda as obras completas de Rebecca Yarros, Raphael Montes, Stephen King e C. S. Lewis, com o título original, o brasileiro, o ano e a série. Os títulos inconfundíveis ("Quarta Asa", "Pet Sematary", "Cartas de um Diabo a seu Aprendiz") contam como se o nome do autor estivesse na notícia. Os comuns ("It", "Holly") só contam entre aspas. A aba Estante mostra quantas notícias citaram cada livro na semana.

## Alerta de lançamento

Quando chega notícia de livro novo de um autor acompanhado, o Radar abre uma issue no repositório, e o GitHub manda e-mail. Se a notícia cita entre aspas um título que não está na estante, o alerta aponta: "título fora da estante".

## A semana

`resumo-semana.json` e a aba "A semana" trazem o que subiu nos últimos 3 dias, os mais citados, a estante e os temas da semana e um destaque por autor. Aos domingos, o resumo vai também para o Telegram.

## Telegram

`coletor/telegram.py` manda, às 6h, as 5 melhores do "Para você", os alertas e o que está em alta. Precisa dos segredos `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID` no repositório (*Settings → Secrets and variables → Actions*); sem eles, o passo é pulado. Para ver a mensagem sem enviar: `python coletor/telegram.py --mostrar --semana`.

## Obsidian

Todo dia sai também `api/obsidian/AAAA-MM-DD.md`, um trecho em Markdown com as 5 do dia. O modelo do Diário do caderno busca esse trecho pela data da nota.

## Na página

- **Edição antiga**: botão no topo; o visual é de jornal antigo com janelas de Windows 98, em pastel (`?estilo=antigo`).
- **Aprendendo com você**: a página guarda neste navegador as notícias que você abre, nota os nomes que se repetem e sugere pôr no perfil.
- Link direto para qualquer aba: `?secao=para-voce|em-alta|estante|semana|tudo`.

## Alarme

Se metade das fontes ou mais falhar, a execução falha de propósito e o GitHub manda um e-mail.

## Seções

- **Brasil e Portugal**: Rascunho, Quatro Cinco Um, Folha (Ilustrada), Estadão (Cultura), Público, Observador, Mundo Cristão, Revista Pesquisa FAPESP e buscas do Google Notícias sobre prêmios, mercado editorial e os autores da estante.
- **Internacional**: Literary Hub, The Guardian (Books, ciência, filosofia, religião), The New York Times Books, The Paris Review, The Gospel Coalition (resenhas), Christianity Today, Reactor (fantasia e ficção científica) e buscas do Google News sobre prêmios e os autores da estante.
- **Prêmios e lançamentos**: tudo o que menciona prêmio, finalistas, mais vendidos ou lançamento, venha de onde vier.

As fontes de cultura geral (Folha, Estadão, Público e Observador) têm `"filtrar": true`, ou seja, só entra o que falar de livros e literatura. As buscas do Google Notícias têm limite de 12 notícias por dia (`max_por_dia`) para não afogar o resto.

## Mexendo

- **Adicionar ou tirar fonte**: edite `fontes.json`. Qualquer feed RSS ou Atom serve.
- **Rodar na hora**: aba *Actions* → *Atualizar Radar Literário* → *Run workflow*.
- **Rodar no seu PC**: `python coletor/coletar.py` (Python 3.10 ou mais novo, sem instalar nada).
- **Mudar o horário**: a linha `cron` em `.github/workflows/atualizar.yml` (está em UTC; Brasília = UTC−3).
