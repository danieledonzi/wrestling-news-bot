# OpenWrestlingTV v92 - Operational Handoff

## Purpose

This document is the practical handoff for operating and continuing work on the v92 bot.

Use it when moving to another chat or developer session.

## Current stable mental model

The bot has three main modes:

```text
Scheduled automatic run
Manual report run
Future manual news run
```

The scheduled automatic run handles reports and news.

Manual report mode is used when the editor provides a URL and wants to force a report.

Manual news is planned but not yet fully active.

## Normal scheduled run

A normal run should look like:

```text
===== RUN START ... VERSION [v92_0_2_report_workshop_publish] =====
[WP v92] BOT WP DIAG ...
[RUN v92] wp_ok=True/False ...
[REPORT v92] ...
[NEWS v92] ...
[RUN v92] totale pubblicazioni=...
===== RUN END ... =====
```

## Health check expectations

The run should first diagnose WordPress:

```text
[WP v92] BOT WP DIAG DNS news.openwrestlingtv.com: ...
[WP v92] BOT WP DIAG health attempt ...
[WP v92] BOT WP DIAG probe status=200 ... endpoint=https://news.openwrestlingtv.com/
[WP v92] BOT WP DIAG probe status=200 ... endpoint=https://news.openwrestlingtv.com/wp-json/
[WP v92] Health check API OK: status_200 label=rest_root
```

If WP fails:

```text
[RUN v92] wp_ok=False
[NEWS v92] WordPress non disponibile: skip news
```

This is expected and good. It avoids token waste.

## Report operational checks

### Already published report

Expected logs:

```text
[REPORT v92] Gia pubblicato: aew_dynamite_2026_05_27
```

or, if published manually:

```text
[REPORT v92] Gia pubblicato altrove: ... via=manual_runs ...
```

If the bot translates a report that already exists, the duplicate guard failed.

### Combined AEW reports

If WrestlingInc publishes:

```text
AEW Dynamite & Collision Results ...
```

expected log:

```text
[REPORT v92] Match report combinato AEW Dynamite/Collision: ...
```

The report should be used for `aew_dynamite` when date is coherent.

### Report failure after translation

If a report fails after translation, check for:

- missing helper functions;
- media upload errors;
- WP post errors;
- category resolution errors.

A previous failure was:

```text
name 'normalize_media_identity' is not defined
```

This should be fixed by guardrails.

## Manual report run

Manual mode must check WordPress before scrape/translation.

Expected log:

```text
[MANUAL v92] WP health check ...
[MANUAL v92] wp_ok=True/False ...
```

If WP is down:

```text
[MANUAL v92] WordPress non disponibile: interrompo prima di scrape/traduzione
```

This is correct.

Manual report state is stored in:

```text
state/manual_runs.json
```

The automatic report pipeline now reads this to avoid duplicate reports.

## News run expectations

The news pipeline should show:

```text
[NEWS v92] Hard news Fase B (...)
[NEWS v92] Soft pool Fase B (...)
[NEWS v92] Hard skip Fase A (...)
[NEWS v92] Hard skip Fase B (...)
[NEWS v92] Pubblico hard/soft score=...
```

It may publish fewer than 3 news.

This is intentional.

## Category logs

Before publishing news, expected logs:

```text
[NEWS v92] Publish categories decision: ['AEW'] | title=...
[NEWS v92] Categorie richieste: ['AEW']
[NEWS v92] Categoria risolta exact-name: AEW -> 5
[NEWS v92] Categorie risolte ids: [5]
```

If the site shows the wrong category, compare:

```text
Publish categories decision
Categorie risolte ids
WordPress category on post
```

Do not assume theme issue unless logs show correct category IDs and WordPress still displays differently.

## Featured image logs

After the media diagnostics patch, news publication should log:

```text
[NEWS v92] Publish featured candidate: ...
[NEWS v92] Featured image candidata: ...
[NEWS v92] Featured image fetch status=... content_type=... bytes=...
[NEWS v92] Featured image WP upload status=...
[NEWS v92] Featured image caricata: media_id=...
```

If the article publishes without image despite a candidate:

```text
[NEWS v92] WARNING: pubblico senza featured_media nonostante featured candidata: ...
```

This warning should be investigated.

## Important states

### `state/report_status.json`

Stores automatic report publication status.

### `state/manual_runs.json`

Stores manual publications. Used to avoid duplicate automatic reports.

### `state/published_news.json`

Stores published news URL state, category, score, post ID and link.

### `state/news_hard_skips.json`

Stores URLs that should not be reconsidered.

### `state/news_soft_pool.json`

Stores soft candidates that can be reconsidered while fresh.

## What to inspect after every run

1. Did WordPress health check pass?
2. Did report pipeline skip already published reports?
3. Did any report fail after translation?
4. Did news publish fewer than 3 items? If yes, was that because soft scores were below threshold?
5. Did categories resolve correctly?
6. Did featured images upload correctly?
7. Did event outcomes get skipped after show report publication?
8. Did any soft anecdote get over-published?

## When to intervene manually

Manual report publication is appropriate when:

- automatic matcher missed a report;
- a report source URL is known and should be forced;
- a combined report needs manual treatment;
- WordPress was down during the scheduled report run.

Manual publication should not be used for routine news unless manual news mode is completed.

## Current monitoring targets

### 1. News featured media

A recent item about Omega/Ospreay logged `featured=True` but no `/media` POST before publication. Diagnostics were added after that. Monitor the next few runs.

### 2. Soft pool quality

Soft pool can still be large. This is acceptable if not published. Watch whether weak soft items reach score 70.

### 3. Strategic speculation

Some strategic discussion items are useful but speculative. Example: possible Omega vs Ospreay All In main event. These can publish if score is high enough, but monitor whether speculation becomes too prominent.

### 4. Viewership/ratings

Routine ratings should usually not publish unless context makes them important.

## Known accepted compromises

### Publishing without images

Accepted.

Reason:

```text
Better a good translated article without image than no article after spending Gemini/GitHub time.
```

### WrestlingInc reports without social embeds

Accepted.

Reason:

```text
Stable report publication is more important than perfect embed replication.
```

### Fewer than three news per run

Accepted.

Reason:

```text
Max 3 is a ceiling, not a target.
```

## Do not reopen unless explicitly requested

These debates are considered settled for now:

- report pipeline separate from news;
- WrestlingInc as preferred automatic report source;
- no forced 3-news fill;
- no rigid pacing cap;
- Business strictly corporate;
- event outcomes after report skipped;
- match never translated;
- manual WP health check before scrape/translation.
