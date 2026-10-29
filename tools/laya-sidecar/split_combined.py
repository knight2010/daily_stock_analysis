#!/usr/bin/env python3
"""Split a combined daily dashboard (report_YYYYMMDD.md) into per-stock files.

The combined report has one '## <name> (<code>)' section per stock, each with
its own '### 📰 重要信息速览' news section. This writes
reports/report_<date>_<code>.md for every stock that does NOT already have a
per-stock file (files from manual WebUI watchlist runs always win).

Usage:
    python3 split_combined.py reports/report_20261029.md --date 20261029 --outdir reports/
"""
import argparse
import os
import re
import sys

STOCK_HEADING_RE = re.compile(r"^##\s*🟠?\s*(.+?)\s*\((\d{6}(?:\.[A-Z]+)?)\)\s*$", re.M)


def main():
    ap = argparse.ArgumentParser(description="Split combined dashboard by stock.")
    ap.add_argument("combined", help="combined dashboard markdown file")
    ap.add_argument("--date", required=True, help="YYYYMMDD for output filenames")
    ap.add_argument("--outdir", default=".", help="directory for per-stock files")
    args = ap.parse_args()

    with open(args.combined, encoding="utf-8") as f:
        text = f.read()

    matches = list(STOCK_HEADING_RE.finditer(text))
    if not matches:
        print("no per-stock sections found", file=sys.stderr)
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    wrote = 0
    for i, m in enumerate(matches):
        name, code = m.group(1).strip(), m.group(2)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].rstrip() + "\n"
        out_path = os.path.join(args.outdir, f"report_{args.date}_{code}.md")
        if os.path.exists(out_path):
            print(f"skip {out_path} (per-stock file already exists)")
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(chunk)
        print(f"wrote {out_path} ({name})")
        wrote += 1
    print(f"split {len(matches)} stock sections, wrote {wrote} new files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
