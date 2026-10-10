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
