# OpenWrestlingTV v92 - Current Architecture

## Purpose

This document describes the current v92 architecture of the OpenWrestlingTV bot.

It is a technical and editorial handoff. It explains what the bot does, how the pipelines are separated, why certain decisions exist, and what must not be changed casually.

## High-level architecture

The bot is organized around four responsibilities:

```text
1. Runtime / WordPress health
2. Report pipeline
3. News pipeline
4. Manual pipeline
```

The current design principle is separation of concerns:

```text
Reports are not news.
Manual recovery is not automatic scheduling.
Editorial scoring is not translation.
Translation is not category resolution.
Media failure is not a reason to lose the article.
```

## Runtime flow

A normal scheduled run performs:

```text
start
-> ensure directories
-> WordPress health check
-> report pipeline
-> news pipeline
-> persist runtime state
-> end
```

The bot logs every major decision to `logs/master_log.log`.

## WordPress health check

Before expensive work, the bot checks WordPress reachability.

The automatic bot now logs:

```text
DNS resolution
GET /
GET /wp-json/
GET /wp-json/wp/v2/posts?per_page=1
status codes
elapsed times
```

Reason:

The site can be visible in a browser while GitHub Actions cannot reliably reach WordPress. The bot must know whether failures are DNS, hosting, REST API, or authentication endpoint problems.

If WordPress is not reachable:

- report publication is skipped;
- news publication is skipped;
- expensive Gemini translation is avoided when possible.

## Report pipeline

### Purpose

The report pipeline publishes show results / recap articles for:

- WWE Raw;
- WWE SmackDown;
- WWE NXT;
- AEW Dynamite;
- AEW Collision.

### Key rule

```text
A report is not a news item.
```

Reports do not pass through news scoring. They do not compete against normal news. They have their own schedule and source matcher.

### Schedule concept

Each report has an expected day-after publication window.

Examples:

```text
Raw -> Tuesday
NXT -> Wednesday
Dynamite -> Thursday
Collision -> Sunday
SmackDown -> Saturday
```

### Source strategy

Current source preference:

```text
WrestlingInc preferred
Ringside News fallback/manual
```

Rationale:

- WrestlingInc reports have proven more structurally stable.
- Ringside News often contains lazy/social/embed structures that are hard to reconstruct deterministically.
- Ringside can be used manually when needed, but should not become the default automatic source without a reliable extractor.

### Report matching

The matcher looks for:

- results/report-like titles;
- correct show;
- coherent date;
- source publication close to expected date.

Special case:

WrestlingInc can publish combined AEW reports:

```text
AEW Dynamite & Collision Results 5/27
AEW Dynamite/Collision Results...
```

These are accepted for `aew_dynamite` when the date is coherent.

### Report titles

Report titles are deterministic.

Examples:

```text
WWE Raw del 25 maggio 2026 - risultati e momenti salienti
WWE NXT del 26 maggio 2026 - risultati e momenti salienti
AEW Dynamite del 27 maggio 2026 - risultati e momenti salienti
```

### Report categories

Reports always use:

```text
Editoriali + federation/show category
```

Examples:

```text
Raw -> Editoriali, WWE
NXT -> Editoriali, NXT
Dynamite -> Editoriali, AEW
```

### Report duplicate guard

Before feed scan or translation, the report pipeline checks whether the report already exists.

Sources checked:

```text
state/report_status.json
state/manual_runs.json
WordPress search, if WP is available
```

This was added because a report manually published through `manual_v92.py` was later reprocessed by the automatic bot.

Expected log:

```text
[REPORT v92] Gia pubblicato altrove: ... via=manual_runs ...
```

### Report translation

Reports use block extraction and chunked translation.

Current chain:

```text
report_blocks_legacy_prompt
batch translation
model fallback chain
```

Preferred model order currently starts with stronger Gemini models, with fallback to lighter models if 503/high-demand errors occur.

### Report media

Reports can have many images.

If media upload repeatedly fails, the bot enters degraded mode:

```text
Stop uploading inline images.
Continue publishing the article.
```

Reason:

The user prefers publishing a translated report without some images rather than wasting time/tokens and publishing nothing.

## News pipeline

### Purpose

The news pipeline selects and publishes normal wrestling news from feeds.

It should not publish everything. It must distinguish:

- hard news;
- useful soft news;
- low-value soft items;
- report-like items;
- event outcomes already covered by reports.

### Flow

```text
Feed scan
-> deterministic hard skip
-> Phase A local pre-score
-> Phase B Gemini editorial analysis
-> final score and priority
-> hard/soft selection
-> workshop translation
-> WordPress publication
```

### Deterministic hard skip

These do not need Gemini:

- already published URLs;
- hard-skipped URLs;
- report-like items;
- invalid URLs/titles;
- clearly low-value local items;
- show reports handled by report pipeline.

### Phase A - local pre-score

Purpose:

```text
Save tokens before Gemini.
```

Uses title/summary/source/url keywords.

Outputs:

```text
hard_skip
low_soft
candidate_b
```

Local low-soft items are not sent to Gemini unless future logic changes.

### Phase B - Gemini editorial analysis

Purpose:

```text
Understand the story before deciding.
```

Gemini returns structured data:

```json
{
  "article_type": "hard_news | event_outcome | strategic_discussion | standard_useful | soft_news | opinion | report_like | low_value",
  "priority": "hard | soft | skip",
  "category": "WWE | AEW | NXT | TNA | World | Business",
  "main_entities": [],
  "story_core": "...",
  "news_action": "...",
  "freshness": "fresh | stale | evergreen",
  "editorial_notes": "..."
}
```

### Phase C - final selection

The bot no longer forces exactly three news per run.

Current thresholds:

```text
Hard publish minimum: 75
Soft publish minimum: 70
```

With `MAX_NEWS_PER_RUN = 3`, the bot may publish:

- 3 news;
- 2 news;
- 1 news;
- 0 news;

based on quality.

Rationale:

```text
Do not fill slots with weak soft content.
If there are many hard news, publish them across runs.
```

### Soft pool

Soft candidates can persist temporarily in:

```text
state/news_soft_pool.json
```

Soft pool does not mean publish automatically. It means the item can be reconsidered while fresh.

### Hard skips

Skipped items are stored in:

```text
state/news_hard_skips.json
```

Hard skip reasons matter because they explain why an item should not be reconsidered.

## News workshop

The news workshop performs:

```text
fetch article
extract text and featured image
translate/adapt with Gemini
cleanup HTML/glossary
upload featured image
resolve categories
publish WordPress post
save prepublish/published artifacts
```

### Translation glossary

Hard rule:

```text
match remains match.
```

Do not translate match as:

- partita;
- incontro;
- gara;
- gioco.

Other terms can remain natural in wrestling context:

- promo;
- segment;
- storyline;
- push;
- turn;
- feud;
- stable;
- tag team;
- heel;
- face;
- main event.

### Source attribution

The source is appended automatically:

```text
Fonte: Ringside News / Wrestling Inc. / etc.
```

Gemini must not add source attribution inside the body.

### Category resolution

WordPress category resolution is deterministic.

It must:

- match exact category name;
- match exact slug;
- not use the first fuzzy search result;
- create a missing category if needed;
- log requested names and resolved IDs.

Expected logs:

```text
[NEWS v92] Categorie richieste: ['AEW']
[NEWS v92] Categoria risolta exact-name: AEW -> 5
[NEWS v92] Categorie risolte ids: [5]
```

### Featured media diagnostics

News featured image upload now logs:

```text
featured candidate URL
fetch status
content type
bytes
WP upload status
media_id
warning if publishing without featured_media
```

Reason:

A news item showed `featured=True` but no `/media` upload appeared before publishing. Diagnostics were added to make this observable.

## Manual pipeline

Manual mode is used when the editor provides a URL and wants to force publication.

Current manual report behavior:

```text
WP health check first
fetch source title
build job
optional manual title/categories/html
run report workshop
store state/manual_runs.json
```

Manual mode must stop before scrape/translation if WP is unavailable.

Manual news mode is planned but not fully active.

## Configuration/state files

Important files:

```text
config/feeds_v92.json
config/reports_v92.json
config/categories_v92.json
state/report_status.json
state/manual_runs.json
state/published_news.json
state/news_hard_skips.json
state/news_soft_pool.json
logs/master_log.log
published/
published_html_review/
```

## Patch chain

v92 is currently assembled by patch scripts.

Important patch scripts:

```text
scripts/apply_v92_news_scoring_v2.py
scripts/apply_v92_stability_patch.py
scripts/apply_v92_business_ple_card_patch.py
scripts/apply_v92_postrun_guardrails_patch.py
scripts/apply_v92_category_resolution_patch.py
scripts/apply_v92_news_quality_guardrails_patch.py
scripts/apply_v92_news_media_diagnostics_patch.py
```

The patch-chain approach is acceptable during live development but should eventually be consolidated into clean canonical source files.

## Do not casually change

Do not casually undo these decisions:

```text
Reports are separate from news.
Reports bypass scoring.
Manual report publication blocks later automatic report publication.
No forced 3-news fill.
No hard pacing cap.
Business is strictly corporate.
Match remains match.
Event outcomes are skipped after show report publication.
WordPress is checked before expensive manual work.
Failed media should not destroy a translated article.
```
