# CHANGELOG v85.4 - Skipped history and boot diagnostics

## Added
- `skipped_history.json` as a separate fast-skip store for URLs rejected by the editorial pipeline.
- TTL-based skip records by reason:
  - low score / editorial skip: 72 hours
  - expired previews: 7 days
  - obsolete pre-show spoilers: 7 days
  - duplicate/news-core/history skips: 14 days
  - validation failures: 24 hours
- Early feed-level skip: URLs still valid in `skipped_history.json` are discarded before scoring and Gemini.
- Processing-level safety skip: pending/feed items still valid in `skipped_history.json` are skipped before scraping/Gemini.
- Offline pending rejection now records the URL in skipped history instead of just ignoring it.
- Boot diagnostics to identify pre-health-check delay:
  - top-of-file marker
  - imports-completed marker
  - `__main__` marker
  - `run_bot()` marker
  - first WordPress health-check marker
- Workflow timestamps before and after `python bot.py`.

## Changed
- `BOT_VERSION` is now `v85_4_skipped_history_boot_diagnostics`.
- `cron.yml` now persists `skipped_history.json` with bot state.
- Pending report items already present in history are skipped before full report scraping.

## Notes
- `history.txt` remains the canonical list of published/treated-as-published URLs.
- `skipped_history.json` is intentionally separate because skipped URLs may become valid again after their TTL expires.
