# Radar Literário

O que está acontecendo no mundo literário, atualizado sozinho todo dia às 06:00 (Brasília).

Todo dia uma tarefa do GitHub Actions lê as fontes de `fontes.json`, separa as novidades e publica uma página para leitura e uma API em JSON pelo GitHub Pages. Nenhum computador precisa ficar ligado e não tem custo.

## A API

Com o GitHub Pages ligado, os endereços são `https://SEU-USUARIO.github.io/radar-literario/...`:

| Endereço | O que traz |
|---|---|
| `api/hoje.json` | novidades de hoje |
| `api/semana.json` | últimos 7 dias (cada item tem o campo `dia`) |
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
  "tags": ["premios"]
}
```

`secoes` traz os `id` de cada seção: `premios-lancamentos`, `brasil-portugal` e `internacional`.

## Seções

- **Brasil e Portugal**: Rascunho, Quatro Cinco Um, Folha (Ilustrada), Estadão (Cultura), Público, Observador e buscas do Google Notícias sobre prêmios e mercado editorial.
- **Internacional**: Literary Hub, The Guardian Books, The New York Times Books, The Paris Review e uma busca do Google News sobre prêmios literários.
- **Prêmios e lançamentos**: tudo o que menciona prêmio, finalistas, mais vendidos ou lançamento, venha de onde vier.

As fontes de cultura geral (Folha, Estadão, Público e Observador) têm `"filtrar": true`, ou seja, só entra o que falar de livros e literatura. As buscas do Google Notícias têm limite de 12 notícias por dia (`max_por_dia`) para não afogar o resto.

## Mexendo

- **Adicionar ou tirar fonte**: edite `fontes.json`. Qualquer feed RSS ou Atom serve.
- **Rodar na hora**: aba *Actions* → *Atualizar Radar Literário* → *Run workflow*.
- **Rodar no seu PC**: `python coletor/coletar.py` (Python 3.10 ou mais novo, sem instalar nada).
- **Mudar o horário**: a linha `cron` em `.github/workflows/atualizar.yml` (está em UTC; Brasília = UTC−3).
