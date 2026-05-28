# OpenWrestlingTV - Changelog v92

## Purpose

This changelog records the practical evolution of v92.

It is not a full git log. It explains why the main changes were made, which problems they solved, and what should be monitored next.

## v92.0 - Clean split pipeline bootstrap

### Goal

Restart from a cleaner architecture after the earlier bot became too patched.

### Main decision

```text
Reports and news must be separate pipelines.
```

### Result

Initial v92 could scan feeds and identify report candidates, but did not yet publish all content.

## v92.0.1 - Report scheduler and matcher

### Added

- scheduled report definitions;
- expected day-after logic;
- report candidate matching;
- deterministic report titles;
- category mapping for reports.

### Reason

Reports should not depend on news scoring or compete with normal news.

## v92.0.2 - Report workshop publish

### Added

- report extraction;
- report translation;
- WordPress publication;
- prepublish artifacts;
- source attribution;
- media handling.

### Issues observed

Reports initially missed or mishandled:

- embeds;
- featured image behavior;
- source attribution;
- strong translation prompt;
- duplicated first inline image;
- source intro paragraphs.

### Fixes

- legacy report translation prompt restored;
- model chain logging added;
- first inline image skipped when already used as featured;
- source intro paragraphs removed;
- chunked translation introduced.

## Ringside report embed experiments

### Problem

Ringside News report pages had many social embeds but stored them in lazy/custom structures. Initial extraction either:

- included social share bar links as embeds;
- lost actual Twitter/X embeds;
- extracted all embeds but could not filter correctly;
- failed on base64/lazy structures;
- introduced syntax or regex errors.

### Decision

Do not make Ringside the default automatic report source until extraction is deterministic.

### Accepted compromise

Use WrestlingInc as default automatic report source. Use Ringside manually/fallback if needed.

## Manual report mode

### Added

Manual report publication via URL.

### Problem observed

Manual run initially scraped and translated before checking WordPress. If WordPress timed out during media upload/post, Gemini tokens and GitHub time were wasted.

### Fix

Manual mode now performs WP health check first.

Expected behavior when WP is down:

```text
[MANUAL v92] WordPress non disponibile: interrompo prima di scrape/traduzione
```

## WordPress diagnostics

### Problem

The site could be visible from the browser but GitHub Actions timed out.

### Fix

Added diagnostics:

- DNS resolution;
- home endpoint;
- REST root;
- posts endpoint;
- elapsed time;
- status codes.

This was added to both manual and automatic workflows.

## AEW Dynamite & Collision combined report matcher

### Problem

WrestlingInc published a combined title:

```text
AEW Dynamite & Collision Results 5/27...
```

The news pipeline recognized it as report-like, but the report pipeline did not match it as Dynamite.

### Fix

Added combined report matcher for:

```text
AEW Dynamite & Collision Results
AEW Dynamite/Collision Results
Dynamite and Collision Results
```

When date is coherent, this can satisfy `aew_dynamite`.

## Duplicate report guard after manual publication

### Problem

A report published manually was later reprocessed by the automatic report pipeline because `report_status.json` did not know it was already published.

### Fix

Before scanning feeds/translating, the report pipeline checks:

- `report_status.json`;
- `manual_runs.json`;
- WordPress search.

### Expected log

```text
[REPORT v92] Gia pubblicato altrove: ... via=manual_runs ...
```

## News pipeline v2

### Added

A structured news pipeline:

```text
feed scan
-> deterministic hard skip
-> Phase A local pre-score
-> Phase B Gemini editorial analysis
-> final hard/soft selection
-> translation/publication
```

### Reason

Old keyword scoring was not enough. The bot needed to understand story type before selecting articles.

## News scoring thresholds

### Initial behavior

The bot tended to publish up to three items even when they were soft.

### Decision

`MAX_NEWS_PER_RUN` is a ceiling, not a target.

### Current thresholds

```text
V92_MIN_HARD_PUBLISH_SCORE = 75
V92_MIN_SOFT_PUBLISH_SCORE = 70
```

### Reason

Better fewer strong news than many weak news.

## Business category fix

### Problem

A broad Business override classified personal legal/medical/personal items as Business.

Examples that should not be Business:

- GUNTHER / Ludwig Kaiser arrest;
- Rhea Ripley collapse/panic attack;
- JDC personal story.

### Fix

Business now requires corporate/business signals.

Business includes:

- ownership;
- acquisitions;
- parent company;
- media rights;
- TV/streaming deals;
- revenue;
- corporate partnerships.

Personal legal/medical stories fall back to WWE/AEW/NXT/TNA/World.

## Deterministic WordPress category resolution

### Problem

Category resolution used WordPress fuzzy search and could fall back to the first result.

### Fix

Now category resolution:

- matches exact name;
- matches exact slug;
- does not accept fuzzy first result;
- creates missing category if needed;
- logs requested names and resolved IDs.

## PLE/PPV card scoring

### Decision

Complete or updated WWE/AEW PLE/PPV cards have editorial and SEO value.

They are not generic previews.

### Added signals

- full card;
- complete card;
- updated card;
- final card;
- match added;
- title match;
- championship match;
- betting odds near event.

## Event outcome after report guard

### Problem

Individual show-angle news could publish after the full report was already published.

### Fix

`event_outcome` items tied to a show are skipped if that show report is already published.

Reason:

The report already covers the event. Duplicating show outcomes clutters the site.

## News translation glossary

### Problem

One Candice Michelle article translated `match` as `partita`.

### Fix

Added prompt rule and deterministic cleanup:

```text
match remains match.
```

Also added cleanup for awkward literal phrases such as:

```text
non devono farsi spezzare da un errore
```

## News featured image diagnostics

### Problem

A news article logged `featured=True` but there was no `/media` POST and the post was published without featured image.

### Fix

Added diagnostics:

- candidate image URL;
- fetch status;
- content type;
- byte size;
- WP upload status;
- uploaded media ID;
- warning if post publishes without featured media.

## Current active watchlist

1. Confirm featured image diagnostics on next news runs.
2. Watch whether strategic speculation scores too high.
3. Watch whether soft pool still contains too many weak items.
4. Confirm event outcome skip after report publication.
5. Confirm category logs remain exact and stable.

## Current accepted state

v92 is not perfect, but the architecture is now coherent:

```text
Reports separate.
News scored editorially.
Manual recovery exists.
WordPress checked before expensive work.
Categories deterministic.
Business strict.
Translation glossary enforced.
Media failures observable.
```
