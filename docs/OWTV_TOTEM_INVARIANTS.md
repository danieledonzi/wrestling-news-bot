# OpenWrestlingTV — TOTEM Invariants

**Status:** OWNER-ratified, canonical normative authority  
**Scope:** OpenWrestlingTV
**Owner-approved clarification:** 2026-10-10 — feed-URL news coverage and Gemini semantic authority.
**Additional owner-approved clarification:** 2026-10-10 — bookmaker exclusions and terminal SKIP isolation.
**Additional owner-approved clarification:** 2026-10-10 — immutable first valid primary classification, under TOTEM-C01.

## TOTEM supremacy

A new feature or reform may add capability around a TOTEM behavior, but may not silently redefine, weaken, bypass, substitute, or reinterpret that behavior.

If implementation logic conflicts with a TOTEM, the implementation is wrong.

A TOTEM may change only through an explicit OWNER decision that explicitly amends this document.

Existing architectural guardrails continue to apply, but where interpretation is ambiguous a TOTEM has precedence over ordinary implementation decisions, local heuristics, and future reform specifications.

## TOTEM-R01 — Canonical report contract

### A. Scope

This single rule applies to every configured report-producing event: weekly shows, PLE, PPV, and confirmed special events. PLE/PPV must not have a separate, weaker semantic identity policy.

### B. Due time

For an event/show dated **D**, its report is due at **06:30 Europe/Rome on calendar day D+1**.

Before 06:30 the canonical source URL may be discovered and reserved, but must not be published as the report. At or after 06:30 the canonical source may be processed. If it is unavailable, the system waits and retries; it must not substitute another article.

### C. Canonical source and identity

The canonical source is **WrestlingInc**. Its title/source metadata must deterministically establish all of:

1. the correct show/event identity;
2. the correct event/show date;
3. explicit **Results** identity.

Harmless title/date formatting variants may be recognized. This permission must not become semantic article matching.

### D. Negative identity

A preview, card article, spoiler, expected result, rumor, backstage article, reaction, interview/comment, post-show opinion, ordinary event news, or an article that merely mentions the event is not a report substitute. Neither the word “report” nor an event-name mention independently means “Results report.”

### E. Fail-safe behavior

When the expected canonical WrestlingInc Results source is absent: **WAIT / RETRY**. Do not select another event article, publish an incomplete semantic substitute, mark the report published because another URL was associated with the event, or let stale pending state supply another identity.

### F. Identity immutability

Once the canonical Results URL is identified for a `report_key`, another URL must not replace it merely because it references the event. Reservation, pending, and reconciliation may preserve or verify identity, but may not redefine it. URL-collision protection must not let an incorrect prior reservation replace the canonical report. Stale state fails closed for that identity; it does not redirect the report to another story.

### Canonical source lock

Canonical report identity is monotonic. The first source URL that successfully satisfies the deterministic canonical WrestlingInc Results identity for a `report_key` becomes the immutable canonical source for that report.

Later candidate URLs cannot reopen source selection, replace the canonical source, or block publication of the locked source. A stale or invalid pre-existing URL is not a canonical lock merely because it exists in pending/runtime state; only a URL that itself satisfies TOTEM-R01 canonical identity may establish the lock.

### G. Downstream freedom

After the canonical Results URL is identified and the 06:30 boundary is reached, downstream processing may scrape, clean, translate, format, upload media, publish, and prevent duplicate WordPress publication. None of those mechanisms may change report identity.

### H. Non-regression examples (2026-08-30 incident)

- “Tony Khan Downplays Report About Restricted Pyro At Wembley Stadium For AEW All In” must **never** satisfy the All In Results identity.
- “Backstage Spoiler On Major AEW All In 2026 Expected Match Result” must **never** satisfy the All In Results identity.
- “AEW All In 2026 Results - ...” is the kind of explicit canonical identity required.
- “WWE NXT Heatwave Results 8/30 - ...” must be identified as Heatwave, not transformed into a fictional generic WWE NXT weekly show dated 8/29.

## TOTEM-N01 — Feed news and autonomous live coverage

An individual news opportunity is an article URL received through a configured news feed. The newsroom must not
extract, split, or manufacture individual news opportunities from a Results report or its live-update body.

The full show/event report and individual feed news are autonomous publication products. The report does not
replace individual news. Its expected, pending, or published state is not, by itself, a reason to suppress an
otherwise eligible individual feed URL; report presence alone is not semantic duplicate evidence.

During the live coverage period of a followed event, individual feed URLs classified MUST_PUBLISH or
SHOULD_PUBLISH must publish as sources make them available, subject to authoritative duplicate decisions and
the existing technical publication safeguards. They must not wait for the full report or compete in the soft pool.
Ordinary SHOULD capacity overflow follows the existing persistent strong-news queue, never soft competition.

This rule creates no minimum article quota and does not authorize new report-derived URLs. It does not independently
change post-show freshness rules: a later feed URL is judged on its own central development under the applicable policy.

## TOTEM-D01 — Gemini owns semantic duplicate decisions

A well-formed Gemini decision bound to the supplied exact relation is the semantic authority for DUPLICATE,
MATERIAL_UPDATE, or NO_MATCH. For the same material and contract, that decision is effective and final.

Local validation may verify JSON/schema, allowed decisions, endpoint references, relation scope, and coverage.
Its lack of sufficient local semantic evidence — including a shared headline name, a deterministic subject anchor,
or locally recognizable wording — must not invalidate or reverse Gemini's semantic decision. Missing local evidence
is not proof that Gemini is wrong, and must not trigger a repair that replaces the decision merely to satisfy a local heuristic.

Actual provider failure, malformed output, missing decisions, or invalid endpoint binding remain technical failures
under the single-attempt technical recovery/fail-closed contract. There are no model repair or second
confirmation calls in primary classification, pair admission, duplicate judgment or soft competition. Valid individual
classes/verdicts survive an invalid sibling. Identical failed input waits under an explicit recovery backoff;
changed factual material or contract can retry. A technical HOLD never becomes an invented semantic SKIP.

Owner decision, 2026-10-10: this rule supersedes earlier requirements that made local semantic anchoring a veto over
an otherwise well-formed, endpoint-bound Gemini decision. Runtime changes implementing it require their own reviewed release.

Semantic duplication means the same autonomous central factual development in both articles. Shared words,
capitalization, promotion, show, person, or broad action category are not sufficient evidence of that relationship.
Pair-admission heuristics do not establish semantic suspicion or a duplicate verdict merely by adding these signals.
Gemini must interpret the meaning of the supplied articles; quoting a word from each endpoint does not establish
that they report the same development.

## TOTEM-N02 — Bookmaker odds are excluded news

An article whose central content is bookmaker odds, betting-market movements, favorites or predictions derived
from those odds is SKIP. Event proximity, a major promotion, and available publication capacity do not provide
an exception. Such an article must not publish or enter the soft pool or semantic duplicate work.

This exclusion concerns the article's central content, not incidental betting vocabulary in an otherwise distinct
factual development. A complete or materially updated confirmed event card remains a separate news type.

Owner decision, 2026-10-10: this reinstates the bookmaker exclusion present in the legacy Menzo policy and
supersedes the older `NEWS_EDITORIAL_DECISIONS_v92.md` example that favored betting odds close to an event.

## TOTEM-S01 — Terminal SKIP closes an individual URL

Whenever a valid editorial SKIP is decided for an individual news URL — primary classification, soft-board review,
competitive expiry, or a final duplicate decision — that canonical URL permanently leaves editorial eligibility.
It must not be reclassified, revived, or retained in the pool because of feed rediscovery, changed title/summary,
refreshed source timestamp, a previous soft admission, midnight, or expiration of a runtime cache or TTL.

A terminally skipped URL must not be either endpoint of a later semantic duplicate/material-update comparison
and must not be injected as comparison history or semantic context for another URL. Its archived decision may
remain for audit and deterministic rejection of that same canonical URL only. A fresh different URL is evaluated
on its own; the skipped article is not its semantic comparison target. Successful publication history remains
the authoritative cross-run duplicate comparison source under the existing lookback contract.

Technical inability to obtain a decision is not a valid editorial SKIP: retain the separate technical fail-closed
publication behavior and its declared recovery contract without inventing a terminal semantic judgment.

Owner decision, 2026-10-10: this explicitly supersedes soft-tombstone comparison history, restoration of prior
soft state over a valid downstream SKIP, and time-limited semantic finality. This does not authorize a new primary
classification of an already classified URL; TOTEM-C01 governs that authority. Terminal downstream decisions
must remain distinguishable from the original primary classification in the audit trail.

## TOTEM-C01 — The first valid primary classification is immutable

Every individual feed news URL receives its primary editorial classification before semantic duplicate work or
entry into an editorial pool. The first technically valid classification for the canonical URL is final:
`MUST_PUBLISH`, `SHOULD_PUBLISH`, `PUBLISHABLE_SOFT`, or `SKIP`. That classification must be durably retained
and reused, not requested again because of a later run, feed rediscovery, changed title/summary, refreshed source
timestamp, elapsed time, midnight, cache expiry, policy-version change, or movement between queues and pools.

A duplicate-admission request, a full duplicate judgment, a scheduling decision, or a soft-board review cannot
promote or demote that primary class. Only a missing or technically invalid initial decision may be requested
in a subsequent eligible operation; there is no repair call and no reconsideration of an already valid row.
Once accepted, classes survive an unrelated admission, duplicate, projection, or handoff failure.

Downstream authority may still terminate eligibility: a final DUPLICATE, a meaningful soft-board SKIP,
competitive expiry, or the applicable midnight boundary closes the URL under TOTEM-S01. This is a terminal
disposition, not a new primary classification. Technical failure remains a recoverable hold, not editorial SKIP.

The owner-facing weak SOFT category maps to primary `SKIP`, as already defined by the category reform; it is
discarded before duplicate work and never enters the pool. `PUBLISHABLE_SOFT` is a distinct eligible class,
which may compete for residual slots but can never turn into SHOULD or MUST. Improvements to classification
apply to as-yet unclassified URLs. A different fresh feed URL has its own first classification; a same-URL
MATERIAL_UPDATE verdict cannot reopen primary classification or revive a terminally skipped URL.

Examples: weak SOFT at 19:00 remains SKIP at 20:00; PUBLISHABLE_SOFT at 19:00 remains PUBLISHABLE_SOFT at
20:00 and cannot enter the strong-news queue; SHOULD awaiting duplicate recovery remains SHOULD.

Owner decision, 2026-10-10: this supersedes any primary reclassification mechanism, including reuse limited to
strong queues, reclassification on policy/cache changes, or reclassification of rediscovered pool URLs. The V8
runtime did not implement this invariant completely. V9 implements it with permanent first-class storage and
independent primary/admission/judgment contracts; see `TOTEM_C01_INDEPENDENT_DUPLICATE_RELEASE_2026_10_10.md`.

## Independent pair election and judgment

After immutable primary classification and terminal URL exclusions, a dedicated semantic admission operation
interprets eligible articles' central factual developments and elects plausible pairs. It receives factual article
context only, no editorial classes, ranks or classifier story_core. Lexical scorer thresholds, shared promotion/show
names and broad action labels cannot authorize a semantic comparison. This operation sends compact article tables,
not an all-against-all pair matrix. An explicitly complete empty suspicion list is valid clearance.

Only admitted exact pairs reach the independent duplicate judge, using their titles, summaries and available
canonical bodies. A technically valid exact ref plus DUPLICATE/NO_MATCH/MATERIAL_UPDATE suffices; optional
explanations and local headline/evidence heuristics cannot veto Gemini. MATERIAL_UPDATE requires a published
history endpoint and preserves eligibility without rewriting primary class. Successful Publisher history stays 12h.
Published duplicates prevail; unpublished duplicates retain richer factual content/media, with earliest arrival as
the informational tie-break. A losing URL is terminal SKIP under TOTEM-S01.

Owner-approved implementation, 2026-10-10: this supersedes combined primary/admission schemas and every model
repair path in these Active operations. Technical recovery is a subsequent operation under the explicit backoff,
not a request to revise an accepted classification or duplicate verdict.
