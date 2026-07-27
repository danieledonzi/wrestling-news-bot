# OpenWrestlingTV - Project History

## Purpose of this document

This file is the historical handoff for the OpenWrestlingTV automated news bot.

It exists so that a future chat, developer session, or Codex session can understand not only what the bot does, but why it does it this way. The most important lesson of the project is that many rules were not arbitrary: they were introduced after real publishing failures, wasted token/GitHub time, bad report matching, poor category assignment, AI translation drift, WordPress instability, or editorial over-publication.

When changing the bot, preserve the decisions documented here unless there is an explicit new editorial decision to replace them.

## Executive summary

OpenWrestlingTV is an AI-assisted automated wrestling news publishing system.

The bot reads selected wrestling news feeds, identifies publishable items, distinguishes show reports from normal news, performs editorial scoring, translates/adapts content into natural Italian, attaches categories and media, and publishes to WordPress.

The current v92 direction is a clean split-pipeline architecture:

```text
Report pipeline
News pipeline
Manual pipeline
WordPress/runtime resilience
```

The project moved away from a heavily patched v80-v91 style bot and toward a v92 rebuild where each content class has its own workflow and its own rules.

The current core philosophy is:

```text
A report is not a news item.
A hard news is not a soft news.
A soft item is not automatically worth publishing.
The bot must understand the editorial nature of an item before spending translation tokens.
The bot must not waste Gemini or GitHub time when WordPress is unavailable.
The bot must preserve human editorial decisions in code and docs.
```

## Origins and evolution

### Early project goal

The first goal was simple: build a low-cost automatic site for OpenWrestlingTV news, fed by selected US wrestling sources, translated into Italian and published to WordPress.

The first sources were:

- WrestlingInc;
- Ringside News;
- Fightful, considered for future/manual usage.

The editorial goal was never to produce a low-quality scraper. The intended output was a readable Italian news site supporting the community and OpenWrestlingTV, not an ads-first project.

### Translation philosophy

The translation chain became one of the most successful parts of the project.

The guiding prompt was based on this idea:

```text
Sei un giornalista italiano esperto di wrestling.
Non fare una traduzione letterale: devi trasformare il materiale in italiano giornalistico naturale, mantenendo fatti e citazioni.
```

Important decisions:

- do not summarize when a full news translation is expected;
- preserve all factual content;
- translate quotes faithfully;
- avoid AI-sounding filler;
- keep wrestling terminology natural;
- avoid invented context;
- add source attribution automatically, not inside Gemini prose.

Later v92 added a hard glossary rule:

```text
match is never translated as partita, incontro, gara, or gioco.
```

This was added after an article about Candice Michelle translated a quote as `prossima partita`, which is wrong in a wrestling context.

### Report pipeline history

Reports became the hardest part of the system.

The project initially treated report-like items as feed/news candidates. That caused multiple problems:

- reports competed with normal news scoring;
- reports could be skipped as duplicates or low-score items;
- show results could be published too late or not at all;
- report titles varied by source and were hard to control;
- Ringside News embeds caused parsing issues;
- WrestlingInc reports were more stable structurally but often lacked social embeds.

The v92 decision was:

```text
Reports have a dedicated pipeline.
Reports do not pass through news scoring.
Reports do not compete with the max news per run.
Reports use deterministic titles and categories.
```

A report can publish in addition to the normal news limit. For example, if `MAX_NEWS_PER_RUN = 3`, a run can publish three news plus one report.

### Report source strategy

Current default:

- WrestlingInc is preferred for report reliability.
- Ringside News is fallback or manual, especially when embeds are useful but extraction is unstable.

Why:

- WrestlingInc extraction was more stable.
- Ringside News often stores social embeds in lazy/base64/custom structures and can produce social bar noise.
- Multiple attempts to reconstruct Ringside embeds were not reliable enough to make it the default automatic report source.

### Report titles

Report titles must be deterministic.

Examples:

```text
WWE Raw del 25 maggio 2026 - risultati e momenti salienti
WWE NXT del 26 maggio 2026 - risultati e momenti salienti
AEW Dynamite del 27 maggio 2026 - risultati e momenti salienti
```

Manual combined reports need normalization:

```text
AEW Dynamite & Collision del 27 maggio 2026 - risultati e momenti salienti
```

but if the automatic pipeline is publishing the Dynamite report, the title should usually remain:

```text
AEW Dynamite del [data] - risultati e momenti salienti
```

### Combined AEW Dynamite & Collision reports

WrestlingInc sometimes publishes combined reports titled like:

```text
AEW Dynamite & Collision Results 5/27...
AEW Dynamite/Collision Results...
```

A v92 fix explicitly allows these titles to match `aew_dynamite` when the date is coherent.

Reason: the news pipeline correctly recognized those URLs as report-like, but the report matcher initially failed to claim them. That caused the report to be missed automatically.

### Report duplicate guard

A key v92 bug was that the automatic report pipeline tried to reprocess a report that had already been published manually.

Cause:

```text
report_status.json did not know about manual_runs.json or WordPress-published manual reports.
```

Fix:

Before scanning feeds or translating, the report pipeline now checks:

- `state/report_status.json`;
- `state/manual_runs.json`;
- WordPress search, if WP is available.

Expected log:

```text
[REPORT v92] Gia pubblicato altrove: ... via=manual_runs ...
```

This prevents wasting Gemini and GitHub time on a report that already exists.

## News pipeline history

### Why scoring exists

The bot must not publish everything in the feeds.

There are always many low-value items:

- generic podcast quotes;
- nostalgia items;
- listicles;
- social reactions;
- minor personal anecdotes;
- weak speculation;
- show event outcomes after a report has already covered the show.

The goal is not to fill exactly three slots every run. The goal is to publish the best available news.

### Old scoring idea

Earlier versions used a two-stage idea:

```text
cheap/local score -> Gemini/editorial refinement -> final decision
```

This was correct in principle but became too patched over time.

v92 restored the principle in a cleaner way.

### Current v92 scoring architecture

The current news pipeline uses:

```text
Feed collection
Hard skip deterministic
Phase A - local pre-score
Phase B - light editorial Gemini analysis
Phase C - hard/soft selection
Workshop translation/publication
```

Phase A saves tokens.
Phase B understands the story.
Phase C selects what to publish.

### Hard skip vs soft pool

Three states must remain separate:

```text
Never evaluate again / hard skip
Keep as candidate / soft pool
Publish now / hard or high-soft
```

Not publishing an item is not the same as hard-skipping it forever.

### Current thresholds

The latest v92 direction:

- hard items should publish only if they are truly strong;
- soft items should not automatically fill empty slots;
- soft publish threshold is currently raised to avoid mediocre output;
- hard publish threshold exists separately.

Current patch introduced environment-driven thresholds:

```text
V92_MIN_HARD_PUBLISH_SCORE = 75
V92_MIN_SOFT_PUBLISH_SCORE = 70
```

This means the bot may publish fewer than three news in a run.

Decision behind this:

```text
Better 20 strong news overall than 30 low-value news.
If there are 40 hard news, publish them across runs.
If there are only weak soft items, publish fewer.
```

### No pacing cap

No artificial pacing cap was added.

Rejected idea:

```text
If many news were published recently, reduce output.
```

Reason: the bot runs about 12-15 times per day, not continuously. After WrestleMania, a PLE, or major breaking news, there can be many genuinely important items. The system should not suppress hard news. It should select better, not throttle blindly.

Future direction may include:

```text
storm mode
slow day mode
```

but only as dynamic scoring thresholds, not a hard cap on output.

## Editorial category history

### Main categories

Current site categories include:

- WWE;
- NXT;
- AEW;
- TNA;
- World;
- Business, if present in WordPress.

NXT is treated as a separate category, not merely WWE.

### Business category correction

A major v92 correction involved Business.

The intended rule:

```text
Business is for business/corporate matters only.
```

Business includes:

- ownership;
- acquisitions;
- parent company issues;
- media rights;
- TV/streaming deals;
- corporate partnerships;
- revenue/financials;
- ticketing business;
- executive/corporate matters.

Business does not include:

- arrests;
- personal legal trouble;
- panic attacks;
- medical stories;
- wrestler anecdotes;
- in-ring storyline items;
- ordinary signings unless the business angle is the point.

Examples:

```text
NJPW ownership / Netflix Japan / AEW leaves NJPW World -> Business
GUNTHER / Ludwig Kaiser arrest -> WWE
Rhea Ripley panic attack -> WWE
JDC personal story -> TNA, if current editorial context is TNA
```

A bug briefly made too many items Business. The fix made Business strict and prevented Gemini Business output from being trusted unless corporate/business signals exist.

### WordPress category resolution

Another v92 bug was category resolution.

The old WordPress resolver searched categories and, if no exact match was found, used the first fuzzy result. That could map an intended category to the wrong one.

Fix:

- exact name match;
- exact slug match;
- no fuzzy first-result fallback;
- create missing category when necessary;
- log requested category names and resolved IDs.

Expected logs:

```text
[NEWS v92] Categorie richieste: ['AEW']
[NEWS v92] Categoria risolta exact-name: AEW -> 5
[NEWS v92] Categorie risolte ids: [5]
```

## News translation history

The news workshop translates the article after scoring selection.

Important rules:

- natural Italian journalism;
- not literal translation;
- no invented details;
- preserve quotes;
- source attribution added by the system;
- title must be natural and not clickbait;
- avoid AI style;
- wrestling glossary enforced.

A v92 issue occurred with Candice Michelle:

```text
prossima partita
```

This caused the hard rule:

```text
match remains match.
```

The current cleanup also rewrites overly literal phrasing like:

```text
non devono farsi spezzare da un errore
```

into more natural phrasing.

## Event outcome after report

Important editorial decision:

```text
A show event outcome is useful only before or during report coverage.
After the full report is published, ordinary show-angle/event outcome news should not be published.
```

Example:

```text
David Finlay & Clark Connors attack Adam Copeland and Christian Cage on AEW Dynamite
```

This may be relevant during immediate show coverage. But once the Dynamite report is published, it should be skipped. The report already covers it.

v92 now adds a guard:

```text
event_outcome_after_report
```

## WordPress/runtime history

### Why health checks matter

Manual mode initially performed scrape and translation before checking WordPress. If WordPress timed out at the end, GitHub time and Gemini tokens were wasted.

Fix:

Manual mode checks WP first:

- DNS;
- home endpoint;
- REST root;
- posts endpoint.

If WP is not reachable, manual mode stops before scrape/translation.

The automatic bot now also logs WP diagnostics.

### Intermittent WordPress reachability

The site can be up from a browser but time out from GitHub Actions.

Therefore the bot logs:

```text
DNS
home /
/wp-json/
/wp-json/wp/v2/posts?per_page=1
elapsed times
```

This helps distinguish:

- DNS failure;
- REST API failure;
- hosting slowness;
- runner-to-host reachability issues.

### Media upload resilience

Report media upload can be expensive. Report articles may have many images. If media uploads fail repeatedly, the bot must not lose the article after translation.

Decision:

```text
Better publish a translated article without an image than waste token/time and publish nothing.
```

Report media upload now has degraded mode.

For news featured images, a later issue showed `featured=True` but no `/media` POST in log for one article. A diagnostics patch was added to log:

- featured candidate URL;
- image fetch status;
- content type;
- upload status;
- media ID;
- warning when publishing without featured media despite a featured candidate.

## Manual mode history

Manual mode exists for cases where the automatic feed pipeline misses something or the editor wants to force a URL.

Current manual report behavior:

- requires WP health check before scrape/translation;
- fetches source title;
- builds job;
- can use manually supplied title/categories;
- publishes through report workshop;
- stores result in `state/manual_runs.json`.

Future manual news mode is planned but not fully active.

## Current known open issues / watchlist

### 1. News featured media diagnostics

A recent run showed one news item with `featured=True` but no media upload log. The diagnostics patch has been added. Next run should be monitored for:

```text
[NEWS v92] Publish featured candidate: ...
[NEWS v92] Featured image fetch status=...
[NEWS v92] Featured image WP upload status=...
[NEWS v92] Featured image caricata: media_id=...
```

### 2. Soft pool still needs tuning

The soft pool can still contain many items. This is acceptable if they are not published, but watch for:

- personal anecdotes scoring too high;
- nostalgia items lingering;
- viewership reports being considered too often;
- speculation being published as strategic discussion.

### 3. PLE/PPV card handling

Decision already made:

```text
Complete/updated PLE or PPV cards for WWE/AEW are valuable SEO/editorial items.
```

They should not be treated like generic previews.

Still monitor whether scoring over-boosts weak betting odds or minor card updates.

### 4. Report source strategy

Current stable default is WrestlingInc. Ringside News remains problematic for embeds. Do not make Ringside the default automatic report source again without a proven deterministic embed extraction solution.

## Current v92 patches of note

The v92 system is currently assembled by a patch chain, with important late-stage patches including:

- `apply_v92_news_scoring_v2.py`;
- `apply_v92_stability_patch.py`;
- `apply_v92_business_ple_card_patch.py`;
- `apply_v92_postrun_guardrails_patch.py`;
- `apply_v92_category_resolution_patch.py`;
- `apply_v92_news_quality_guardrails_patch.py`;
- `apply_v92_news_media_diagnostics_patch.py`.

The patch-chain approach is useful during live development, but future cleanup should eventually consolidate stable logic into canonical modules.

## Handoff principle

When resuming in a new chat, do not restart the architecture discussion from zero.

The current accepted decisions are:

```text
Reports are separate from news.
Reports use deterministic titles.
WrestlingInc is default report source.
Manual reports must block later automatic duplication.
News scoring uses local pre-score + Gemini editorial analysis + hard/soft selection.
No forced three-news fill.
No rigid pacing cap.
Business is strictly corporate.
Match is never translated.
Show event outcomes are skipped after the report is published.
WordPress must be checked before expensive work.
Failed media should not destroy the article.
```
# v95.19.1 — Simone report identity guard

Special-event reports now become due the following morning, explicit title/URL show identity wins over supporting text, and the automatic publisher enforces one normalized source URL per report key. See `docs/v95.19.1_simone_report_identity_guard.md`.
