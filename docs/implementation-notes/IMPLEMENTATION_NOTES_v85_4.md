# IMPLEMENTATION_NOTES v85.4

## Files changed
- `bot.py`
- `cron.yml`

## Main implementation points

### 1. `skipped_history.json`
A new state file stores rejected URLs with:
- URL
- title
- reason
- score
- summary
- score reasons
- created_at
- expires_at
- TTL
- bot version

The file is written atomically through the existing v85 atomic JSON writer.

### 2. Early feed skip
`build_candidates()` now checks `v854_should_skip_url(link)` immediately after confirming the RSS entry has a link. If the skip record is still valid, the item is discarded before scoring and before Gemini can ever be called.

### 3. Skip recording
The bot records skipped URLs for:
- score below threshold hard skips;
- expired preview/show announcements;
- editorial excludes;
- offline pending candidates rejected by the v85.2 hard gate;
- validation failures and low-score processing skips.

### 4. Pending report pre-scraping skip
`process_candidate_item()` now detects report pending items already present in local history and skips them before choosing/scraping the report source.

### 5. Boot diagnostics
The bot prints markers at:
- top-of-file start;
- imports completed;
- `__main__` reached;
- `run_bot()` entry;
- first WP health-check call.

The workflow also prints UTC timestamps before and after `python bot.py`, allowing separation of GitHub Actions startup time from Python/import/bot time.

### 6. Configuration
New environment variables:
- `V85_4_SKIPPED_HISTORY_ENABLED=1`
- `V85_4_BOOT_DIAGNOSTICS_ENABLED=1`
- `SKIPPED_HISTORY_FILE=skipped_history.json`
- `V85_4_SKIP_TTL_DEFAULT_SECONDS`
- `V85_4_SKIP_TTL_LOW_SCORE_SECONDS`
- `V85_4_SKIP_TTL_EXPIRED_PREVIEW_SECONDS`
- `V85_4_SKIP_TTL_OBSOLETE_PRESHOW_SECONDS`
- `V85_4_SKIP_TTL_DUPLICATE_SECONDS`
- `V85_4_SKIP_TTL_VALIDATION_SECONDS`
