#!/bin/bash
# Daily runner: pull today's stock reports from Lightsail and classify
# their news items with laya. Runs on EC2 (UTC); 18:40 Beijing = 10:40 UTC.
set -u
cd "$HOME/laya-sidecar" || exit 1
TODAY=$(date -u +%Y%m%d)
mkdir -p reports logs out
# Pull today's per-stock reports (000572, 002402, screening, ...).
scp -i "$HOME/.ssh/lightsail-key.pem" -o StrictHostKeyChecking=accept-new \
  -o ConnectTimeout=20 \
  "ubuntu@18.119.120.181:~/dsa/reports/report_${TODAY}_*.md" ./reports/ >> "logs/run_${TODAY}.log" 2>&1 || true
for f in reports/report_"${TODAY}"_*.md; do
  [ -e "$f" ] || continue
  base=$(basename "$f" .md)
  echo "=== $base $(date -u +%H:%M:%S) ===" >> "logs/run_${TODAY}.log"
  python3 laya_classify.py "$f" \
    --env "$HOME/laya-sidecar/dsa.env" \
    --env "$HOME/laya-sidecar/.env" \
    --out "out/laya_${base#report_}.md" >> "logs/run_${TODAY}.log" 2>&1
done
echo "done $(date -u +%H:%M:%S)" >> "logs/run_${TODAY}.log"
