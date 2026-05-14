# Changelog v87.2

## Added

- Task-based Gemini model matrix.
- Per-run global model cooldown after 503/capacity errors.
- Strong local confirmed report history via `confirmed_published_reports.json`.
- Final embed canonicalization and dedupe.
- Strict X/Twitter output format: `https://x.com/<user>/status/<id>`.
- YouTube canonical output format: `https://www.youtube.com/watch?v=<video_id>`.
- Published HTML review in-run dedupe.
- Pending retry preservation for temporary model failures.

## Changed

- Report skip logic can now use confirmed local report history when WordPress is offline.
- Legacy model chains are rebound to safer v87.2 defaults.
- Translate/report/title/postedit now use task-specific chains rather than a single broad router.
- `save_published_html_review_item()` now avoids duplicate saves for the same published article.

## Fixed

- Duplicate raw YouTube URLs appearing in the middle of the article while the embed also appears elsewhere.
- Twitter links emitting as `twitter.com` instead of canonical `x.com`.
- Repeated calls to a model already returning 503 in the same run.
- True-results report uncertainty when WordPress is offline after a report was already confirmed.
