#!/usr/bin/env python3
"""Laya sidecar for the daily stock reports (read-only w.r.t. the stock app).

Reads one report markdown file, extracts the news items under
"重要信息速览", translates each item to concise English with Gemini,
classifies it with the laya /decide API, and writes a markdown result.

Usage:
    python3 laya_classify.py <report.md> [--out <result.md>]

Environment (read from --env files, never from this script):
    GEMINI_API_KEY  - from the stock app's ~/dsa/.env
    GEMINI_MODEL    - e.g. gemini-3.5-flash (defaults to gemini-3.5-flash)
    LAYA_API_KEY    - the laya service API key (Basic-auth password / Bearer)

Exit codes: 0 ok, 1 usage/config error, 2 all items failed.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

LAYA_BASE = "https://prod-main-laya-4dc41b-00xeqzkewa4.compute.instacloud-edge.com"
LAYA_DECIDE = LAYA_BASE + "/decide"
LAYA_HEALTHZ = LAYA_BASE + "/healthz"

QUESTIONS = [
    {
        "type": "choice",
        "instructions": "What is the sentiment of this news for the stock?",
        "options": ["positive", "neutral", "negative"],
    },
    {"type": "noul", "instructions": "Is this news material to the share price?"},
    {
        "type": "score",
        "instructions": "How urgent is this news for an investor holding the stock?",
        "options": ["routine", "worth watching", "act now"],
    },
]

SECTION_RE = re.compile(r"^###\s*📰\s*重要信息速览\s*$", re.M)
HEADING_RE = re.compile(r"^#{1,6}\s", re.M)


def load_env_file(path):
    """Load KEY=VALUE lines from a dotenv file into os.environ (no overwrite)."""
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def extract_items(report_path):
    """Return (stock_label, [(label, text), ...]) from the news section."""
    with open(report_path, encoding="utf-8") as f:
        text = f.read()
    m = SECTION_RE.search(text)
    if not m:
        raise SystemExit(f"no '重要信息速览' section found in {report_path}")
    start = m.end()
    rest = text[start:]
    end = len(rest)
    for hm in HEADING_RE.finditer(rest):
        if hm.start() > 0:
            end = hm.start()
            break
    section = rest[:end]
    stock_m = re.search(r"##\s*🟠?\s*(.+?)\s*\(\d{6}\)", text)
    stock_label = stock_m.group(1).strip() if stock_m else os.path.basename(report_path)
    items = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line or line.startswith(">") or line.startswith("|"):
            continue
        line = re.sub(r"^\*\*([^*]+)\*\*:?\s*", r"\1：", line)
        line = re.sub(r"^-\s*", "", line)
        line = re.sub(r"\*\*", "", line).strip()
        if len(line) < 8:
            continue
        if "：" in line:
            label, _, body = line.partition("：")
            items.append((label.strip(), body.strip()))
        else:
            items.append(("", line))
    return stock_label, items


def gemini_translate(text, api_key, model, retries=3):
    """Translate one Chinese item to concise English with Gemini."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + urllib.parse.quote(model)
        + ":generateContent"
    )
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Translate the following Chinese financial news item "
                            "into concise English (1-2 sentences). Keep numbers, "
                            "dates and stock codes exact. Output only the "
                            f"translation.\n\n{text}"
                        )
                    }
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 256},
    }
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            url + "?key=" + urllib.parse.quote(api_key),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                raise RuntimeError(f"unexpected Gemini response: {data}")
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
            if e.code in (429, 500, 502, 503):
                time.sleep(10 * (attempt + 1))
                continue
            raise RuntimeError(last_err)
        except Exception as e:  # noqa: BLE001 - timeouts etc., retry with backoff
            last_err = str(e)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Gemini translate failed after {retries} tries: {last_err}")


def laya_wake(timeout=180):
    """GET /healthz (no auth) to wake the service; returns True if model loaded."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(LAYA_HEALTHZ, timeout=15) as resp:
                data = json.load(resp)
            if data.get("model_loaded"):
                return True
        except Exception:
            pass
        time.sleep(10)
    return False


def laya_decide(state_en, api_key, retries=3):
    """POST /decide; retries on 503 (model still loading). Returns parsed JSON."""
    body = json.dumps({"state": state_en, "questions": QUESTIONS}).encode("utf-8")
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(
            LAYA_DECIDE,
            data=body,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code == 503:
                time.sleep(30)
                continue
            raise RuntimeError(last_err)
        except Exception as e:  # noqa: BLE001 - network flakiness, retry once
            last_err = str(e)
            time.sleep(10)
    raise RuntimeError(f"laya /decide failed after {retries} tries: {last_err}")


def summarize(answer):
    """One-line human summary of one laya answer."""
    t = answer.get("type")
    if t == "choice":
        probs = answer.get("probabilities", {})
        top = max(probs.items(), key=lambda kv: kv[1]) if probs else ("?", 0)
        return f"{answer.get('choice')} ({top[0]} {top[1]:.0%})"
    if t == "noul":
        return f"{answer.get('noul', 0):.0%} 可能是实质性消息"
    if t == "score":
        legend = answer.get("legend", {})
        score = answer.get("score", 0)
        nearest = legend.get(str(round(score)), "")
        return f"{score:.2f}（{nearest}）"
    return json.dumps(answer, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description="Classify report news with laya.")
    ap.add_argument("report", help="report markdown file, e.g. report_20261026_000572.md")
    ap.add_argument("--out", help="result markdown file (default: <report>.laya.md)")
    ap.add_argument("--env", action="append", default=[],
                    help="dotenv file to load (repeatable)")
    ap.add_argument("--max-items", type=int, default=8,
                    help="max news items to classify (default 8)")
    args = ap.parse_args()

    for env_file in args.env:
        load_env_file(env_file)
    gemini_key = os.environ.get("GEMINI_API_KEY")
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    # Translation can use a different (cheaper/quota-richer) model than the
    # stock analysis: free-tier request quota is per model (20/day each),
    # so splitting the two workloads across models doubles the headroom.
    translate_model = os.environ.get("GEMINI_TRANSLATE_MODEL", gemini_model)
    laya_key = os.environ.get("LAYA_API_KEY")
    missing = [k for k, v in (("GEMINI_API_KEY", gemini_key),
                              ("LAYA_API_KEY", laya_key)) if not v]
    if missing:
        print(f"missing env: {', '.join(missing)} (use --env)", file=sys.stderr)
        return 1

    stock_label, items = extract_items(args.report)
    items = items[: args.max_items]
    print(f"stock: {stock_label} | items: {len(items)}")
    if not items:
        print("no news items found", file=sys.stderr)
        return 1

    print("waking laya ...")
    if not laya_wake():
        print("warning: laya /healthz did not report model_loaded; trying anyway",
              file=sys.stderr)

    out_lines = [
        f"# Laya 分类：{stock_label}",
        "",
        f"来源：`{os.path.basename(args.report)}`",
        "",
        "| # | 新闻 | 情绪 | 是否重大 | 紧急程度 |",
        "|---|------|------|----------|----------|",
    ]
    failed = 0
    quota_fail_streak = 0
    for i, (label, text) in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {label or '新闻'} ...", flush=True)
        try:
            state_en = gemini_translate(text, gemini_key, translate_model)
            result = laya_decide(state_en, laya_key)
            answers = result.get("answers", [])
            s = [summarize(a) for a in answers]
            while len(s) < 3:
                s.append("—")
            row_label = f"{label}：{text}" if label else text
            out_lines.append(
                f"| {i} | {row_label} | {s[0]} | {s[1]} | {s[2]} |"
            )
            print(f"    -> {s[0]} | {s[1]} | {s[2]}")
            quota_fail_streak = 0
        except Exception as e:  # noqa: BLE001 - keep going with the next item
            failed += 1
            print(f"    FAILED: {e}", file=sys.stderr)
            row_label = f"{label}：{text}" if label else text
            out_lines.append(f"| {i} | {row_label} | 失败 | 失败 | 失败 |")
            if "429" in str(e):
                quota_fail_streak += 1
                if quota_fail_streak >= 2:
                    print("Gemini quota exhausted (2 consecutive 429s) — "
                          "aborting this report", file=sys.stderr)
                    break
            else:
                quota_fail_streak = 0
        if i < len(items):
            time.sleep(3)

    out_path = args.out or (args.report + ".laya.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines) + "\n")
    print(f"wrote {out_path}")
    return 2 if failed == len(items) else 0


if __name__ == "__main__":
    raise SystemExit(main())
