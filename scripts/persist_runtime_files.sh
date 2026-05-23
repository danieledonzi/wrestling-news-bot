#!/usr/bin/env bash
set -euo pipefail

git add published/ published_html_review/ logs/ pending_articles.json history.txt history.json confirmed_published_reports.json review_bundle_latest.zip soft_pool.json v90_2_event_cores.json .bot_exit_code || true

if git diff --cached --quiet; then
  echo "[RUNTIME] Nessuna modifica runtime da salvare"
  exit 0
fi

git commit -m "runtime: update bot artifacts and logs"
git push
