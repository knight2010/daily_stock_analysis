# Laya sidecar for daily_stock_analysis

Read-only companion to the resident stock app: it classifies the news items
in a generated report (`### 📰 重要信息速览`) with the self-hosted Laya
decision API, without touching the main program, its image, or its container.

## How it works

1. Extract the news items from one report markdown file.
2. Translate each item from Chinese to concise English with Gemini
   (the model behind Laya only reads English).
3. Call Laya `POST /decide` with three typed questions per item:
   - `choice` — sentiment: positive / neutral / negative
   - `noul` — is this news material to the share price?
   - `score` — urgency: routine / worth watching / act now
4. Write a markdown table with one row per item.

## Run

```bash
python3 laya_classify.py ~/dsa/reports/report_20261026_000572.md \
  --env ~/dsa/.env --env ~/laya-sidecar/.env \
  --out ~/laya-sidecar/out/laya_20261026_000572.md
```

Environment (never commit these files):

- `GEMINI_API_KEY`, `GEMINI_MODEL` — from the stock app's `~/dsa/.env`
- `LAYA_API_KEY` — the Laya service key (its Basic-auth password / Bearer token),
  kept in `~/laya-sidecar/.env` with mode 600

## Notes

- Laya's `/decide` takes `{"state": "<english string>",
  "questions": [...]}`. Questions are a **list**; choice/score questions need
  an `"options"` list (`"criteria"` returns HTTP 500 on this template).
  Answers come back in the same order as the questions.
- Laya scales to zero when idle: the first call after idle wakes the service
  (the script polls `GET /healthz` first; model load takes ~45 s).
- Laya judges the text, not the market: sentiment/materiality/urgency
  classification only. It does not predict prices.
