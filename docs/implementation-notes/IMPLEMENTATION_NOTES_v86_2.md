# IMPLEMENTATION_NOTES v86.2

## Version name

`v86_2_morning_report_hold`

## Goal

v86.2 starts from v86.1 and adds a deterministic morning gate for full show reports. The bot can identify the best report candidate during the night, but it must not process/publish complete reports before 06:30 Europe/Rome.

## Main implementation points

### 1. Morning hold

New environment variables:

```yaml
V86_2_REPORT_MORNING_HOLD_ENABLED: "1"
V86_2_REPORT_HOLD_HOUR: "6"
V86_2_REPORT_HOLD_MINUTE: "30"
V86_2_REPORT_HOLD_TIMEZONE: Europe/Rome
```

Before the hold time, `build_candidates()` filters `RESULTS_REPORT` candidates out of the publish queue and saves them to `pending_articles.json` with:

```text
kind=report
reason=report_hold_until_0630
not_before=<today 06:30 Europe/Rome>
```

### 2. Report processing after 06:30

After the morning gate, the report can be processed immediately if it passes completeness checks. The old rolling report delay is no longer the primary gate for weekly reports.

### 3. Strict WordPress confirmation

For `report:*` keys, v86.2 overrides `wp_has_published_event()` and routes to a strict report lookup. A report is considered already published only if WordPress returns a real report-looking post, not merely a news item from the same show.

Strict confirmation requires report markers such as `Results`, `Highlights`, `Key Moments`, `Risultati`, `Report`, or `Recap`, plus the show marker and coherent date. Exact `report:*` metadata remains a valid hard confirmation.

### 4. Pending behavior

Reports held before 06:30 are not written to `history.txt` and not written to `skipped_history.json`. They remain pending until mature.

## Files changed

- `bot.py` -> provided as `bot_v86_2.py`
- `cron.yml` -> provided as `cron_v86_2.yml`
