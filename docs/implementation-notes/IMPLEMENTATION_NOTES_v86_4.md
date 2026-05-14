# IMPLEMENTATION_NOTES v86.4

## Files changed

- `bot.py`
- `cron.yml`

Provided as:

- `bot_v86_4.py`
- `cron_v86_4.yml`

## Main changes

### 1. Report-first candidate gates

A new canonical `build_candidates()` replaces the previous wrapper approach. It detects report-like feed items before generic history gates and applies strict WordPress confirmation first.

For report-like items, these old gates become diagnostic rather than blocking:

- URL already in history;
- semantic ID already in history;
- title key already seen;
- title key seen in this run;
- story signature already in history;
- story signature seen in this run;
- broad event-key confirmation without strict report-title match.

### 2. Strict report confirmation remains required

A report can be skipped only if `v862_wp_has_published_report_strict()` confirms a real report/results article, using title/report markers, show, date and category checks.

### 3. skipped_history rescue fixed

The v86.3 skipped-history rescue checked normalized reasons too narrowly. v86.4 accepts both underscore and space forms:

- `score_below_threshold`
- `score below threshold`
- `low_score`
- `low score`
- `processing_skipped`
- `processing skipped`

This allows post-show outcome URLs such as in-ring debuts to be recalculated instead of hidden by stale low-score records.

### 4. Morning report hold preserved

After candidates are built, v86.2 morning hold still saves report candidates to pending before 06:30 Europe/Rome.

### 5. Runtime labels

New canonical labels:

- `[BOOT v86.4]`
- `[REPORT v86.4]`
- `[FRESHNESS v86.4]`
- `[SKIP v86.4]`

Some deeper legacy helper labels can still appear when old helpers are called.
