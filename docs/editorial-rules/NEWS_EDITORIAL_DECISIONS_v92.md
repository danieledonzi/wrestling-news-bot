# OpenWrestlingTV v92 - News Editorial Decisions

## Purpose

This document records the editorial rules that drive the v92 news pipeline.

It exists to prevent repeated debates in future chats. If a rule here is changed, the reason should be documented in a changelog or a new decision note.

## Core philosophy

The bot must behave like an editor, not like a feed copier.

The goal is not to publish every item. The goal is to publish items that matter to the OpenWrestlingTV audience.

Current guiding principle:

```text
Better fewer high-value news than many weak news.
If many hard news exist, publish many across runs.
If only weak soft news exist, publish fewer.
```

## Content classes

### Hard news

Hard news includes concrete, current, relevant developments.

Examples:

- death;
- serious arrest/legal matter;
- major lawsuit;
- major injury with operational impact;
- return/debut;
- signing/release/departure;
- contract expiration or renewal with real implications;
- title change or major championship development;
- TV/media rights deal;
- ownership/acquisition/business development;
- confirmed show or card change of real importance;
- major storyline development with future impact.

Hard news should normally score at least 75.

### Strategic discussion

Strategic discussion includes business, industry or future-direction items.

Examples:

- WWE/AEW/TKO strategy;
- TV/streaming distribution;
- Netflix/ESPN/Fox/WBD/Paramount-related items;
- NJPW World / streaming rights / international distribution;
- backstage direction with meaningful impact;
- major fan/business perception stories.

Strategic discussion can be hard if concrete. If speculative, it should usually be soft-high rather than hard.

### Standard useful

Useful but not urgent content.

Examples:

- substantial interview revealing a relevant detail;
- contract/future comments from a major name;
- credible backstage context;
- significant ratings/viewership when context matters;
- non-breaking but relevant update.

### Soft news

Soft news includes interesting but non-essential content.

Examples:

- personal reflections;
- nostalgia;
- quotes from interviews/podcasts;
- light backstage anecdotes;
- minor social reactions;
- curiosity items;
- personal stories without immediate current impact.

Soft news should not be published just to fill a slot.

Current principle:

```text
Soft items need a strong score to publish.
Otherwise they remain in soft pool or are skipped.
```

### Low value / skip

Skip items include:

- generic listicles;
- weak opinion pieces;
- nostalgia without current value;
- minor social media reactions;
- report/results already handled elsewhere;
- generic previews without real news;
- stale updates;
- weak speculation;
- show-angle event outcomes after a report is already published.

## Reports are not news

Show reports and results are handled by the report pipeline.

Examples that must not be treated as normal news:

```text
WWE Raw Results...
WWE NXT Results...
AEW Dynamite Results...
AEW Dynamite & Collision Results...
```

Reports do not need scoring. They are scheduled and deterministic.

## Event outcomes after report

Important decision:

```text
An event outcome from a show should not be published after the full report for that show has already been published.
```

Example:

```text
David Finlay & Clark Connors attack Adam Copeland and Christian Cage on AEW Dynamite
```

This can be useful during immediate live/show coverage if no report exists yet. But after the full Dynamite report is published, it becomes redundant.

Reason:

The report already covers the show. Publishing individual event-outcome items afterward clutters the site with duplicated show content.

Exception:

If the event outcome has major independent future impact, it may still be treated as a separate hard news item. This should be explicit in the analysis.

## PLE/PPV card items

The user observed that people search for complete PLE/PPV cards.

Decision:

```text
Complete or updated cards for WWE/AEW PLE/PPV events have medium-high editorial and SEO value.
```

They are not generic previews.

Examples that should receive useful scoring:

- full card;
- complete card;
- updated card;
- final card;
- match added;
- title match added;
- betting odds close to event;
- official card update.

Generic preview without changes remains low value.

## Business category

Business must be strict.

Business includes:

- ownership;
- parent company;
- acquisitions;
- sales;
- investors/shareholders;
- revenue/financials;
- media rights;
- TV deals;
- streaming deals;
- corporate partnerships;
- ticketing business;
- executive/corporate matters.

Business does not include:

- arrests;
- personal legal issues;
- wrestler medical problems;
- panic attacks;
- personal history;
- in-ring angles;
- ordinary interview comments.

Examples:

```text
Netflix expected to land WWE in Japan as AEW leaves NJPW World -> Business
NJPW ownership change -> Business
Former WWE star arrested -> WWE
Rhea Ripley panic attack/collapse story -> WWE
JDC personal story while currently in TNA -> TNA
```

## Category trust

Gemini's category is generally useful but not blindly trusted.

Business requires explicit corporate signals.

If Gemini says Business without corporate terms, the bot should fall back to WWE/AEW/NXT/TNA/World according to entities and current context.

When Gemini identifies a current affiliation correctly, it can be trusted if WordPress category resolution confirms it.

Example:

```text
JDC is in TNA -> TNA is acceptable.
```

## NXT category

NXT is a separate category.

Do not collapse NXT into WWE for site category purposes.

## Scoring and publication count

Do not publish exactly three news by obligation.

The previous assumption was:

```text
max 3 news per run means fill up to 3 whenever possible.
```

Current decision:

```text
max 3 is a ceiling, not a target.
```

A run can publish 0, 1, 2, or 3 news.

Reason:

If only weak soft items are available, publishing fewer is better.

## Hard/soft thresholds

Current default thresholds:

```text
Hard publish minimum: 75
Soft publish minimum: 70
```

These can be tuned, but do not remove the concept of separate thresholds.

## No rigid person/source caps

Rejected rules:

```text
max 1 Cody Rhodes per run
max 2 Ringside News per run
max 1 WWE per run
```

Reason:

During major events or breaking stories, several news about the same person/source/category can be genuinely relevant.

The bot should rely on editorial scoring and semantic difference, not arbitrary caps.

## No simple pacing cap

Rejected rule:

```text
If the site has published many articles recently, block more publication.
```

Reason:

The bot runs around 12-15 times per day. After WrestleMania, major PLEs or major breaking news, there may be many valid hard news. The correct solution is better scoring, not artificial throttling.

Future acceptable direction:

```text
storm mode -> publish more hard news if there are many hard candidates
slow day mode -> lower threshold only when there are truly few candidates
```

But these should be scoring modes, not hard pacing caps.

## Interviews and anecdotes

Personal anecdotes, nostalgia, reflections and interview comments should usually be capped unless they contain current operational impact.

Examples of operational impact:

- contract expiring;
- active return/debut;
- active legal case;
- active health/injury issue affecting wrestling;
- title/program/storyline implication;
- business/TV/contract relevance.

Without these, an anecdote should not reach hard-news priority.

## Viewership/ratings

Routine viewership/ratings should not automatically publish.

They can be useful when:

- a major increase/decrease occurs;
- there is context such as TV deal pressure;
- the article ties to business strategy;
- it involves major programming changes.

Otherwise they are standard useful or soft.

## Social-media/bot engagement stories

A story about suspicious engagement, bot accounts or platform manipulation may be strategic if it affects perception of a major company or TV/social strategy.

However, weak social reactions should remain soft or skip.

## Translation editorial rules

The translated news should feel like a human Italian wrestling article.

Rules:

- no AI filler;
- no overdramatic literal titles;
- no invented interpretation;
- all quotes preserved faithfully;
- source attribution added automatically;
- wrestling terminology preserved naturally.

Hard glossary:

```text
match -> match
```

Never use:

- partita;
- incontro;
- gara;
- gioco.

## Media and publication

An article should not be lost just because an image fails.

For reports and news, media failures should be logged and, where possible, publication should proceed without media.

For news featured images, logs must show the candidate URL and upload outcome.

## Current examples from v92 testing

### Correct / acceptable

```text
Jim Ross future uncertain as AEW contract nears end -> AEW, high-soft/hard-borderline
Netflix/WWE Japan/AEW leaves NJPW World -> Business, strategic
JDC personal story while in TNA -> TNA, soft if no current operational impact
```

### Needs guardrail

```text
Candice Michelle botch advice -> soft, not Business, title must be natural, match not partita
David Finlay/Clark Connors Dynamite angle -> event outcome; skip after Dynamite report
Omega vs Ospreay All In speculation -> strategic/soft-high, monitor featured image upload
```

## Handoff summary

The news bot should publish fewer but better items.

It should never lose major news, but it should also avoid filling the site with weak soft content simply because there are empty slots.
