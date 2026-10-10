# OpenWrestlingTV — Editorial Totems and Soft Board Contract

**Status:** FROZEN
**Scope:** Editorial Director authority, duplicate safety, soft-pool lifecycle, daily pacing
**Timezone authority:** Europe/Rome
**Frozen on:** 2026-10-07
**Owner-approved revision:** 2026-10-09 — primary eligibility before semantic duplicates; persistent SHOULD overflow; live show coverage.
**Owner-approved clarification:** 2026-10-10 — feed-URL news only, autonomous reports, and final Gemini semantic decisions.

This document freezes the editorial invariants that MUST survive any implementation reform. Operational parameters may still be tuned, but the invariants below are non-negotiable unless explicitly superseded by a later owner-approved architecture decision.

## 1. Duplicate authority is above every editorial class

Primary editorial classification precedes semantic duplicate work. SKIP is discarded before semantic comparisons.
Every MUST, SHOULD or PUBLISHABLE_SOFT candidate MUST receive authoritative duplicate clearance before publication or soft-pool admission.

- `DUPLICATE` -> terminal hard skip.
- duplicate check technically unresolved / invalid / failed -> terminal hard skip for that opportunity.
- `MATERIAL_UPDATE` -> survives as a new editorial opportunity grounded in the new fact.
- `NO_MATCH` / unique -> may proceed to scheduling according to its already assigned class.

There is no exception for breaking, MUST or SHOULD content. A duplicate MUST is still a duplicate and MUST NOT publish.

Duplicate memory and relation history persist across the midnight boundary.

Gemini owns relation semantics under `docs/OWTV_TOTEM_INVARIANTS.md`, TOTEM-D01. A well-formed decision bound to
the supplied exact endpoints is effective and final for the same material and contract. Insufficient local semantic
evidence, including missing headline subject anchors, must not invalidate that decision or cause a semantic reversal
through repair. Technical schema, reference, scope and coverage failures remain subject to bounded repair/fail-closed.

## 2. Primary classification measures intrinsic editorial value

Candidates receive one of these classes before semantic duplicate work:

- `MUST_PUBLISH`
- `SHOULD_PUBLISH`
- `PUBLISHABLE_SOFT`
- `SKIP`

Primary class MUST be based on the story's intrinsic editorial value and central development. It MUST NOT be promoted or demoted merely because the day is quiet, because many slots remain, or because the soft pool is weak.

Primary classification and publication pacing are separate decisions.

## 3. MUST_PUBLISH is a totem

A duplicate-cleared MUST:

- publishes;
- never competes with other candidates;
- is never deferred for ordinary pacing;
- never enters the soft pool;
- may exceed the nominal daily ceiling if genuine MUST/SHOULD demand requires it.

The daily ceiling exists to prevent filler inflation, not to suppress genuinely mandatory coverage.

## 4. SHOULD_PUBLISH is demand-driven

A duplicate-cleared SHOULD:

- publishes after MUST within the run;
- does not compete with soft content;
- is not deferred merely to reserve capacity for soft content;
- when ordinary run capacity is exhausted, persists in the strong-news queue and is retried next run even without feed rediscovery;
- remains in that queue until confirmed publication or a validated terminal decision;
- may contribute to exceeding the nominal daily ceiling if genuine editorial demand requires it.

A day with 30 genuine MUST+SHOULD items is an exceptional strong-news day, not a pacing failure.

## 5. PUBLISHABLE_SOFT is the only competitive editorial class

Owner-approved category reform: PUBLISHABLE_SOFT requires all four of professional wrestling
relevance, informative substance, recognizable OWTV audience interest and standalone value. Weak SOFT maps to the
existing terminal SKIP class and is removed before semantic comparisons. The binding definitions and calibrated
examples are in `OWTV_GEMINI_EDITORIAL_DIRECTOR_POLICY_V7_ACTIVE.md`.

A soft candidate has no publication entitlement.

Soft content may:

- be held;
- compete with other soft content;
- be selected when publication adds real value;
- decay through repeated meaningful non-selection;
- be dropped immediately when freshness or editorial usefulness is gone;
- expire at midnight.

Unused publication capacity has zero editorial value.

A run with zero publications is a valid editorial outcome. Consecutive empty runs are also valid.

## 6. 00:00 Europe/Rome is a tombstone boundary

At 00:00 Europe/Rome, ordinary unresolved editorial opportunities from the previous day lose eligibility.

In particular:

- residual soft-pool candidates expire;
- prior-day soft candidates MUST NOT become eligible again merely because the daily counter reset;
- same-story rediscovery MUST NOT revive an expired opportunity.

Exceptions are limited to:

- a genuinely fresh breaking / MUST development that emerges across the boundary;
- a grounded MATERIAL_UPDATE after midnight;
- continuity of a live event already in progress when the new development itself is fresh.

The memory of duplicates, tombstones, history and canonical identity survives midnight.

## 7. 00:00–12:00 is the morning accumulation window

Before 12:00 Europe/Rome, the system MUST NOT infer that the day is quiet from low publication count.

The wrestling news cycle is strongly US-driven. Weekly shows commonly air during the Italian night and generate live news, post-show news, reports and follow-up material through the morning.

During 00:00–12:00:

- MUST publishes;
- SHOULD publishes;
- SKIP dies;
- PUBLISHABLE_SOFT enters the morning soft pool;
- soft candidates do not compete;
- morning hold does not count as a competitive loss;
- low `published_news_today_local` MUST NOT justify soft admission.

The morning soft pool is a **separate persistent container**. It MUST NOT be injected back into the
primary Active candidate list on later runs merely because it is waiting. `MAX_CANDIDATES` and other
primary-capture limits apply to the current feed candidate board, not to the accumulated soft pool.

A soft URL enters this container only after it has already passed the duplicate gate and primary classification.
If the same URL appears again in a later feed run, that feed appearance still follows normal duplicate/tombstone
rules; the stored pool row itself does not need to be reclassified every 30 minutes.

The soft pool may grow independently during the morning. Its size is not an editorial candidate-count cap.

A primary policy change invalidates an older pool row's admission. Such a row waits in WAIT_PRIMARY_POLICY until a
feed rediscovery receives a validated current-policy primary decision and duplicate clearance. It cannot enter a
soft review or publish using the old class, does not accrue competitive losses while waiting, and still expires at
the original midnight boundary. It is not injected into Active just for migration. Same-policy carried soft URLs
retain the existing lifecycle.

## 8. From 12:00, every run may perform a contextual Soft Board Review

After 12:00 Europe/Rome, remaining run capacity is calculated only after MUST and SHOULD have taken precedence.

At the first eligible Soft Board Review, Gemini receives the **entire currently eligible soft pool as its own board**,
independent of the primary Active candidate list. New PUBLISHABLE_SOFT items arriving after 12:00 join that same
container before the contextual review.

Gemini MUST receive day context for the soft review, including at minimum:

- current Europe/Rome time;
- MUST published today;
- SHOULD published today;
- soft published today;
- total news published today;
- current run ordinary capacity and residual soft capacity;
- daily residual capacity;
- report/show publication context where relevant;
- all currently eligible soft candidates;
- first-seen time and age;
- prior meaningful soft reviews / competitive losses;
- title, story core, concise factual description and source.

The review asks whether each soft candidate adds enough value **now, in the context of what OWTV has already published today**.

## 9. Secondary soft-board labels are not primary editorial classes

The Soft Board Review may use these secondary dispositions:

- `SOFT_MUST`: publish now if residual soft capacity permits.
- `SOFT_SHOULD`: keep in the pool for bounded reconsideration.
- `SOFT_SKIP`: terminal soft tombstone.

These labels do not rewrite the primary class. A `SOFT_MUST` remains primary `PUBLISHABLE_SOFT`; it is only the current best soft-board choice.

Soft-board selection MUST NOT promote a soft candidate into primary `MUST_PUBLISH` or `SHOULD_PUBLISH`.

## 10. Soft capacity is a maximum, never a target

For every run after 12:00:

1. duplicate-cleared MUST publishes;
2. duplicate-cleared SHOULD publishes;
3. residual run capacity becomes the maximum available for soft content;
4. the Soft Board Review may select anywhere from zero to that maximum.

If three soft slots remain, publishing zero, one, two or three are all valid outcomes.

The system MUST NOT manufacture soft publications to fill unused slots.

## 11. Soft-pool memory follows story identity, not the current feed instance

The soft state belongs to the canonical story/opportunity identity.

Rediscovery by Massy or the feed MUST NOT reset:

- first-seen time;
- soft-pool age;
- meaningful review count;
- competitive-loss count;
- tombstone status.

The canonical URL is immutable for the lifetime of a soft opportunity. Feed-text drift on the same URL
(headline rewrite, summary rewrite, refreshed timestamp or other metadata change) MUST NOT create a new opportunity,
MUST NOT reset soft state, and MUST NOT promote the item to MUST/SHOULD.

In OWTV's source environment, a genuinely new development is represented by a new URL. That new URL is a new candidate,
but it still MUST pass duplicate/material-update authority against published history and relevant soft tombstones.
If it is the same old story under another URL, it dies as DUPLICATE. If it contains a genuinely new development,
MATERIAL_UPDATE may authorize it as a new editorial opportunity.

No implementation should invent a same-URL material-update path.

## 12. Competitive decay begins only when competition begins

Morning HOLD is not a loss.

After 12:00, a `SOFT_SHOULD` may accumulate a bounded number of **meaningful soft-board reviews**. Repeated meaningful non-selection eventually expires the opportunity as repeatedly outranked/stale.

`SOFT_SKIP` expires immediately.

The exact review limit is an implementation parameter and is not frozen by this document.

## 13. Fail-closed duplicate safety, fail-safe editorial restraint

No URL may bypass duplicate authority.

When no technically valid, endpoint-bound Gemini duplicate decision can be obtained, the opportunity is hard-skipped
rather than published speculatively. A local validator's inability to independently establish semantic evidence does
not make an otherwise well-formed Gemini decision unresolved; TOTEM-D01 governs that distinction.

When soft-board judgment is unavailable or invalid, the safe editorial default is to publish no soft content for that run. MUST/SHOULD behavior remains governed by their validated primary classification and duplicate clearance.

## 14. Observability requirements

Implementation MUST make it possible to audit, per candidate:

- duplicate decision and authority;
- primary editorial class;
- first seen;
- current local day;
- morning HOLD vs competitive review;
- soft-board disposition;
- meaningful review count;
- tombstone / expiry reason;
- publication outcome;
- day-context values supplied to the soft review.

Reports MUST distinguish primary class from secondary soft-board disposition.

## Frozen summary

`DUPLICATE` beats everything.

`MUST_PUBLISH` does not compete.

`SHOULD_PUBLISH` does not compete.

`PUBLISHABLE_SOFT` is the only competitive class.

Before 12:00, soft content accumulates but does not compete.

From 12:00, Gemini evaluates the entire soft board in day context.

Soft capacity is optional capacity, never a fill target.

Repeatedly outranked or stale soft content dies.

Midnight is a tombstone boundary for unresolved ordinary opportunities.

Zero-publication runs are valid editorial decisions.

## 12. Live coverage and ED-5 observation

Concrete match results and events of followed shows are at least SHOULD, with important developments MUST.
Here news means an individual article URL received through a configured feed. Do not extract, split or manufacture
news from the full Results report or its live-update body. Publish duplicate-cleared MUST/SHOULD feed URLs during
the live coverage period as source availability permits; do not wait for the report or send them to soft competition.
Ordinary SHOULD overflow retains the existing strong-news queue. The full report is autonomous and does not replace
individual feed news. Its expected, pending or published state is not, by itself, a reason to suppress such a URL or
declare it a semantic duplicate. Later feed URLs still follow the applicable post-show freshness policy on their own
central development. See TOTEM-N01 in `docs/OWTV_TOTEM_INVARIANTS.md`.
Four or five items is a planning reference, not a quota. Retain primary class/reason, post-filter relation counts, phase-level cost,
soft-pool admissions, queue overflow and first-seen/publication timestamps for the 24 hours after verified deployment.
