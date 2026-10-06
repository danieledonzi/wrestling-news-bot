# OWTV EDITORIAL TOTEMS — FROZEN CONTRACT

**Status:** FROZEN  
**Effective architecture target:** post-ED-2 editorial reform  
**Timezone authority:** Europe/Rome  
**Scope:** normal-news editorial eligibility, duplicate authority, hard/soft admission, soft-pool lifecycle, daily boundary, run capacity

This document freezes the non-negotiable editorial invariants for the next OpenWrestlingTV Editorial Director reform. Implementation may change; these invariants may not be weakened without an explicit OWNER decision and a new frozen contract.

## 1. UNIVERSAL DUPLICATE AUTHORITY

Every URL entering from the feed MUST pass through the canonical duplicate authority before it can acquire editorial eligibility.

The duplicate authority is above every editorial class, including breaking news, MUST and SHOULD.

- `DUPLICATE` => terminal hard skip.
- duplicate check unresolved, unavailable, invalid or failed => terminal hard skip for that opportunity.
- `MATERIAL_UPDATE` => survives as a new editorial opportunity and is evaluated on the concrete new fact.
- `NO_MATCH` / unique => survives.

**Totem:** Duplicate beats MUST.

No candidate may be published, pooled, promoted, or protected from expiry merely because it would otherwise be MUST or SHOULD if its uniqueness has not first been authoritatively established.

Duplicate/history memory persists across the local midnight boundary.

## 2. PRIMARY EDITORIAL CLASS IS INTRINSIC VALUE

After duplicate clearance, Gemini assigns exactly one primary class:

- `MUST_PUBLISH`
- `SHOULD_PUBLISH`
- `PUBLISHABLE_SOFT`
- `SKIP`

The primary class answers only:

> How much editorial value does this story have in itself?

The primary class MUST NOT depend on:
- remaining daily slots;
- current publication count;
- whether the day appears quiet or busy;
- soft-pool size;
- desire to fill capacity.

The publication context may affect scheduling only after intrinsic class has been established.

## 3. MUST_PUBLISH IS A TOTEM

A unique, validated `MUST_PUBLISH` story is published.

It:
- does not compete;
- is never deferred for pacing;
- never enters the soft pool;
- is not sacrificed to protect the nominal daily ceiling;
- has priority over every SHOULD and every soft candidate.

A duplicate candidate that would otherwise be MUST is still terminally skipped under Totem 1.

## 4. SHOULD_PUBLISH IS DEMAND-DRIVEN

A unique, validated `SHOULD_PUBLISH` story is published immediately after MUST items.

It:
- does not compete with soft candidates;
- does not enter the soft pool;
- is not downgraded because the day is already rich;
- is not promoted merely because the day is quiet.

A genuine SHOULD consumes ordinary publication capacity before any soft candidate is considered.

If genuine MUST+SHOULD volume exceeds the nominal daily ceiling, editorially justified hard coverage wins over the numerical ceiling. The ceiling exists to prevent soft inflation/feed-copying, not to suppress a genuinely exceptional hard-news day.

## 5. PUBLISHABLE_SOFT IS THE ONLY COMPETITIVE CLASS

A `PUBLISHABLE_SOFT` candidate has no publication entitlement.

It may:
- be published when the contextual soft-board judgment says publication is worthwhile now;
- remain temporarily eligible in the soft pool;
- lose freshness through meaningful competitive review;
- be terminally skipped.

Unused capacity has zero editorial value.

**Totem:** A run with zero publications is a valid editorial outcome. One or more consecutive empty runs are acceptable.

## 6. MORNING ACCUMULATION WINDOW — 00:00 TO 12:00 EUROPE/ROME

The interval from local midnight through 11:59:59 is an accumulation window, not a quiet-day judgment window.

The wrestling news cycle is structurally US-heavy. Weekly shows commonly begin around 01:00–02:00 Italian time and run for several hours; related news, post-show developments and reports continue through the morning. Therefore low early-day publication counts are not evidence that the day is quiet.

During this window:

- MUST => publish.
- SHOULD => publish.
- SKIP => terminal skip.
- PUBLISHABLE_SOFT => enter/refresh the soft pool.

Morning soft candidates do NOT compete with each other and do NOT accumulate competitive losses merely because stronger hard/show news is being published.

**Totem:** quiet-day soft admission MUST NOT begin before 12:00 Europe/Rome.

## 7. CONTEXTUAL SOFT BOARD REVIEW — FROM 12:00 TO MIDNIGHT

From 12:00 Europe/Rome onward, every meaningful run may conduct a contextual Soft Board Review.

Gemini MUST see the whole currently eligible soft pool plus sufficient day context to judge not only each story in isolation but whether publishing it makes sense for OWTV at that point in the day.

At minimum the context should include:
- current Europe/Rome time;
- MUST published today;
- SHOULD published today;
- soft publications today;
- total news published today;
- remaining nominal daily capacity;
- current run capacity after MUST and SHOULD;
- relevant show/report state where available;
- for each soft candidate: title, story_core, concise factual/editorial description, source, first-seen time, age, prior meaningful soft-review history and any relevant freshness metadata.

The contextual soft review MUST NOT rewrite the primary class. It evaluates only how to manage candidates already classified `PUBLISHABLE_SOFT`.

Recommended secondary dispositions:

- `SOFT_MUST` — worth publishing now among the available soft material.
- `SOFT_SHOULD` — still worthwhile enough to retain for bounded reconsideration, but not worth publishing now.
- `SOFT_SKIP` — no longer worth standalone publication; terminal expiry.

These are secondary soft-board dispositions, not replacements for the primary MUST/SHOULD classes.

## 8. RUN CAPACITY ORDER

For every run after duplicate clearance:

1. publish all eligible MUST;
2. publish all eligible SHOULD;
3. compute residual ordinary run capacity;
4. consider soft candidates only for the residual capacity.

Residual capacity is a maximum, never a target.

If residual capacity is 3 and the soft review finds:
- one worthwhile soft => publish one;
- zero worthwhile soft => publish zero;
- five worthwhile soft => at most the capacity-authorized number may publish, with the remainder retained or expired according to the soft-board decision.

No mechanism may manufacture soft publications solely because slots are free.

## 9. SOFT-POOL MEMORY, REDISCOVERY AND DECAY

Soft-pool state belongs to the canonical story identity, not to one transient feed appearance.

Rediscovery of the same canonical URL/story MUST NOT reset:
- first-seen time;
- soft-pool age;
- prior meaningful soft-board reviews;
- prior contextual dispositions;
- expiry/tombstone state.

Morning HOLD is not a competitive loss.

Only a meaningful post-12:00 soft-board review in which a candidate remains eligible but is not selected may advance its bounded reconsideration state.

The exact maximum number of meaningful `SOFT_SHOULD` reviews is an implementation parameter to validate during rollout, not a frozen totem. Repeatedly outranked soft material MUST eventually expire; it may not persist indefinitely until capacity happens to become available.

`SOFT_SKIP` expires immediately.

Freshness expiry may also terminate a soft candidate before the review limit when its standalone editorial value has become obsolete.

## 10. MIDNIGHT IS A TOMBSTONE BOUNDARY

At 00:00 Europe/Rome, ordinary unpublished editorial opportunities from the previous local day expire.

All residual soft opportunities from the prior day are tombstoned. They do not become eligible again merely because the new day starts with a fresh capacity counter.

The system preserves:
- duplicate memory;
- canonical history;
- tombstones;
- published-history authority.

The following are new opportunities, not carry-over:
- a genuinely new breaking/MUST fact that emerges around/after midnight;
- a grounded material update;
- valid continuation of an explicitly recognized live-event fact when the new factual development itself is new.

**Totem:** midnight resets daily capacity, not editorial debt.

## 11. CONTEXT MAY AFFECT ACTION, NEVER INTRINSIC CLASS

The primary classification pass decides what the story is.

The contextual soft-board pass decides whether an already-soft story is worth publishing now.

Publication count, time of day, free slots or board weakness MUST NOT turn a PUBLISHABLE_SOFT into a primary SHOULD/MUST.

This separation exists specifically to prevent contextual class inflation.

## 12. OBSERVABILITY AND NON-REGRESSION

The implementation MUST retain auditable evidence sufficient to answer, per candidate and per run:

- duplicate authority outcome;
- primary editorial class;
- primary story_core/category;
- local-day publication context;
- soft-pool identity/state;
- soft-board disposition when applicable;
- meaningful review count;
- reason for publication, retention or expiry;
- final publication outcome.

Daily reporting must distinguish:
- intrinsic hard coverage (MUST+SHOULD);
- contextual soft publications;
- morning pooled softs;
- softs retained;
- softs expired by quality/freshness/repeated review;
- midnight tombstones.

No future report should infer these categories from article type when canonical Director evidence exists.

---

## Frozen summary

**DUPLICATE beats everything.**  
**MUST does not compete.**  
**SHOULD does not compete.**  
**SOFT is the only competitive class.**  
**00:00–12:00 accumulates soft; it does not judge a quiet day.**  
**From 12:00, Gemini judges the whole soft board in the context of the day.**  
**Free capacity is not a publication objective.**  
**Repeatedly weak/stale soft material dies.**  
**Midnight tombstones ordinary carry-over.**  
**A zero-publication run is valid.**
