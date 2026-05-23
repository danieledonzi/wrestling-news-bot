#!/usr/bin/env bash
set -euo pipefail

paths=(
  published/
  published_html_review/
  logs/
  pending_articles.json
  history.txt
  history.json
  confirmed_published_reports.json
  review_bundle_latest.zip
  soft_pool.json
  v90_2_event_cores.json
  processed_urls.json
  .bot_exit_code
)

staged_any=0
for path in "${paths[@]}"; do
  if [ -e "$path" ]; then
    git add -f "$path"
    staged_any=1
  else
    echo "[RUNTIME] Path assente, skip: $path"
  fi
done

if [ "$staged_any" = "0" ]; then
  echo "[RUNTIME] Nessun path runtime esistente da salvare"
  exit 0
fi

if git diff --cached --quiet; then
  echo "[RUNTIME] Nessuna modifica runtime da salvare"
  exit 0
fi

git commit -m "runtime: update bot artifacts and logs"
git push
