# EDITORIAL_RULES v85.4

## Published history vs skipped history
- `history.txt` is only for URLs that were published or must be treated as already handled/published.
- `skipped_history.json` is for URLs rejected by the editorial pipeline and should not be re-analyzed until their TTL expires.

## Skipped history TTLs
- Score/editorial low-value skips: 72 hours.
- Expired preview/show announcement: 7 days.
- Obsolete pre-show spoiler: 7 days.
- Duplicate/news-core/history skips: 14 days.
- Validation failure: 24 hours.

## Feed processing rule
At the beginning of a run, feed URLs are checked in this order:
1. published history (`history.txt`);
2. skipped history (`skipped_history.json`) if the record is still valid;
3. validation-fail suspension;
4. normal scoring/editorial pipeline.

## Offline WordPress rule
When WordPress is offline, only genuinely publishable candidates can become pending. Low-score, expired, obsolete, tier3/tier4 or otherwise weak candidates are rejected and recorded in `skipped_history.json`.

## Spoiler rule
If the run is outside a plausible live-event window, live spoiler checks are globally disabled once per run. Pre-show obsolete/expired preview rules still apply as deterministic editorial filters.

## Publishing rule
Draft-first publishing remains mandatory: upload featured image first, create draft with featured media, validate, then publish.
