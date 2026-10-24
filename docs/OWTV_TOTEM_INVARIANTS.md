# OpenWrestlingTV — TOTEM Invariants

**Status:** OWNER-ratified, canonical normative authority  
**Scope:** OpenWrestlingTV
**Owner-approved amendment:** 2026-10-16 — Wrestleview fallback from 08:30 Europe/Rome and important material updates.
**Owner-approved amendment:** 2026-10-11 — Ringside canonical source and complete ordered Simone reports.
**Owner-approved clarification:** 2026-10-10 — feed-URL news coverage and Gemini semantic authority.
**Additional owner-approved clarification:** 2026-10-10 — bookmaker exclusions and terminal SKIP isolation.
**Additional owner-approved clarification:** 2026-10-10 — immutable first valid primary classification, under TOTEM-C01.
**Owner-approved conditional reform, confirmed by isolated replay:** 2026-10-13 — complete editorial source material, under TOTEM-F01.
**Owner-approved clarification:** 2026-10-15 — same-run material updates may replace the initial article only when their own complete body contains both the initial fact and the update.
**Owner-approved clarification:** 2026-10-18 — summary/roundup articles do not automatically cover autonomous dedicated feed news; contextual newsletter citations are not subscription CTAs.
**Owner-approved clarification:** 2026-10-18 — a successful report publication closes that event/night/date independently of its source.
**Owner-approved reform:** 2026-10-18 — isolated reusable factual cards, explicit identities/tags, prudent history preselection and complete admission accounting; final full-body duplicate judgment unchanged.

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

Before 06:30 the canonical source URL may be discovered and reserved, but must not be published as the report. At or after 06:30 the canonical source may be processed. If it is unavailable, the system waits and retries under the source election below; it must not substitute an ordinary event article.

### C. Canonical source and identity

For new report identities **Ringside News is preferred until 08:30 Europe/Rome on D+1**. From 08:30, when no Ringside source published by that deadline has been selected or is available, a complete **Wrestleview Results report** may become canonical. Timely source publication timestamps can establish Ringside eligibility when discovery occurs in the next scheduled scan. Unknown timestamps do not prove timely publication after the cutoff. A Wrestleview URL is discoverable earlier but cannot be reserved or published before 08:30.

For either source, title/source metadata must deterministically establish all of:

1. the correct show/event identity;
2. the correct event/show date;
3. explicit **Results** identity.

Harmless title/date formatting variants may be recognized. This permission must not become semantic article matching.

### D. Negative identity

A preview, card article, spoiler, expected result, rumor, backstage article, reaction, interview/comment, post-show opinion, ordinary event news, or an article that merely mentions the event is not a report substitute. Neither the word “report” nor an event-name mention independently means “Results report.”

### E. Fail-safe behavior

Before 08:30, when Ringside is absent: **WAIT / RETRY**. From 08:30, use an eligible complete Wrestleview Results source; if neither source is eligible, **WAIT / RETRY**. Quick results lists, previews and taping spoilers are not the complete fallback report. Do not select another event article, publish an incomplete semantic substitute, mark the report published because another URL was associated with the event, or let stale pending state supply another identity.

### F. Identity immutability

Once the canonical Results URL is identified for a `report_key`, another URL must not replace it merely because it references the event. Reservation, pending, and reconciliation may preserve or verify identity, but may not redefine it. URL-collision protection must not let an incorrect prior reservation replace the canonical report. Stale state fails closed for that identity; it does not redirect the report to another story.

### Canonical source lock

Canonical report identity is monotonic. The first elected URL that satisfies deterministic Results identity and the source deadline policy for a `report_key` becomes the immutable canonical source for that report. Discovery of an ineligible early fallback cannot establish a lock.

Later candidate URLs cannot reopen source selection, replace the canonical source, or block publication of the locked source. A stale or invalid pre-existing URL is not a canonical lock merely because it exists in pending/runtime state; only a URL that itself satisfies TOTEM-R01 canonical identity may establish the lock.

Owner amendment, 2026-10-16: this source policy applies to weekly shows, PLE/PPV and confirmed special events. Once Wrestleview is selected, later Ringside URLs are ignored even if translation or publication is still pending or the report has already published. No source replacement or second report is allowed. The Wrestleview feed is report-only and must not supply new ordinary news opportunities.

Owner amendment, 2026-10-11, amended above: new identities originally used Ringside News for every report type. There is no automatic WrestlingInc fallback. Already validated and locked WrestlingInc URLs remain locked to preserve identity immutability; this exception does not admit new WrestlingInc reservations. Published records are not reopened.

### Successful publication is final — owner clarification, 2026-10-18

Once a valid report for an event/show, its specific night and its date has been successfully published,
that report obligation is permanently fulfilled, regardless of the source used. This rule is source-agnostic:
it applies to today's sources and to any future source. No alternative source is subsequently sought or
elected for that fulfilled report; no further reservation, scraping, translation or report publication is
authorized for that identity. The 08:30 fallback applies only to an unfulfilled report. A successful
publication record must not be replaced by a later source or report. Separate nights/dates remain separate
obligations. A preview, news article, wrong event/date, dry run or failed attempt is not successful report
publication. This closure concerns reports only and does not suppress autonomous individual feed news.

### G. Downstream freedom

After the canonical Results URL is identified and the 06:30 boundary is reached, downstream processing may scrape, clean, translate, format, upload media, publish, and prevent duplicate WordPress publication. None of those mechanisms may change report identity.

### H. Non-regression examples (2026-08-30 incident)

- “Tony Khan Downplays Report About Restricted Pyro At Wembley Stadium For AEW All In” must **never** satisfy the All In Results identity.
- “Backstage Spoiler On Major AEW All In 2026 Expected Match Result” must **never** satisfy the All In Results identity.
- “AEW All In 2026 Results - ...” is the kind of explicit canonical identity required.
- “WWE NXT Heatwave Results 8/30 - ...” must be identified as Heatwave, not transformed into a fictional generic WWE NXT weekly show dated 8/29.

## TOTEM-R02 — Complete report and ordered media

Every report uses the same complete translation and ordered rendering contract: weekly shows, PLE, PPV and confirmed special events. Translate all substantive source paragraphs, headings, card items, match actions, results, segments, quotes and details; never summarize or compress the report. Preserve the original sequence of text, images and embedded media, including lazy embeds. Source scripts are not published; verified media permalinks use native WordPress embeds.

Remove the source website’s greetings, author biographies, advertising and calls to action. Actual show greetings and wrestlers discussing their careers remain substantive content. One linked source attribution is retained.

A pre-show may be collapsed only when the configured event type is PLE or PPV and its boundaries are identifiable. Its heading must be prominent and explicitly invite the reader to click to expand and read the complete pre-show. Weekly reports never use this collapse. The main show remains expanded, and all pre-show text and media remain available.

Missing text translations, invalid media recovery or an obviously condensed translation fail publication technically; they do not become a successful report or an editorial SKIP. The full block manifest remains available for review. Technical coverage checks cannot prove every semantic detail, so an apparent omission remains a report-quality defect.

Owner decision, 2026-10-11: approved Ringside proof adopted as the production Simone contract. TOTEM-N01 remains unchanged: no individual news is extracted from a report.

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

### Summary articles and dedicated news — owner clarification, 2026-10-18

A news roundup or short multi-story pre-show recap does not automatically cover the autonomous dedicated
feed news it mentions. Evaluate the dedicated article as its own publication product, as with report/news
separation. Its substantive focused treatment and editorial media must be considered; a shared brief mention
alone is not duplicate coverage. The approved Jay White case consists of an initial short multi-story pre-show
article followed by a substantially more detailed dedicated article with an X embed: both remain legitimate.
This is not blanket immunity for every roundup/dedicated pair, and it does not make every extra detail or embed
an important material update between two ordinary dedicated articles. Gemini retains semantic authority.

An editorial citation of the Wrestling Observer Newsletter or another newsletter is source attribution/reporting,
not a subscription CTA. Alfred must identify actual promotional/subscription language rather than block the
standalone word "newsletter". Other translation, safety and source-boilerplate checks remain in force.

## TOTEM-D01 — Gemini owns semantic duplicate decisions

Owner clarification, 2026-10-16: MATERIAL_UPDATE requires an **important substantive factual development** worth reporting after the shared story is known. Any factual difference is not enough. Historical dates, career summaries, older matches/titles, ancillary biography, restated quotes and media differences do not alone justify a follow-up. New consequences, confirmed plans, important professional explanations and autonomous substantial developments may qualify. This is Gemini's semantic judgment, guided by policy examples; no local keyword veto or second editorial classification is introduced. The same-run A+B coverage rule remains in force only after materiality is established.

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

## TOTEM-D02 — Source-isolated facts and accountable pair admission

Owner decision, 2026-10-18: after the controlled card, identity/tag and complete-pair tests, the duplicate admission path uses reusable source-isolated factual cards. Each extraction and each identity/tag enrichment operation sees one complete source article only. Code binds article, fact and source-unit identities. An enrichment operation cannot rewrite the fixed statements or change their owner. Profiles distinguish complete bodies supplied to extraction from cards derived from those bodies.

Primary classification still precedes duplicate work and remains immutable under TOTEM-C01. This reform cannot reclassify a URL, generate feed news from a report, revive SKIP or change soft competition. A closed URL cannot cause later card generation or appear as comparison context. Retained archived cards do not confer editorial eligibility.

Cards and their isolated stages are cached against canonical URL, complete material, title, model, schema and policy. Exact reuse avoids a new provider attempt; changing a card contract does not reopen a primary classification. Explicit, conservative identity aliases and multi-facet episode tags support history retrieval; broad show/promotion/speaker context alone is insufficient. Uncertain identities or insufficient episode tags remain reviewable rather than being treated as certain distinctions. History remains the existing successful-publication lookback, not soft tombstones or a new 24-hour window.

Every eligible pair has a recorded disposition: excluded from history retrieval with its card identities and reason; explicitly ADMIT or NO_SUSPICION; or unresolved TECHNICAL_HOLD. These are different authorities and must not be conflated with a final DUPLICATE/NO_MATCH/MATERIAL_UPDATE verdict. The model returns an explicit assessment for every permitted pair in bounded collective batches; there is no arbitrary pair cap that discards the remainder. Valid sibling assessments survive a malformed or missing sibling. A valid ADMIT authorizes the unchanged full-body judgment and never independently closes a URL.

Technical inability to produce a card or an assessment is not a negative semantic judgment and never SKIP. Current-card failures hold their own URL. An unavailable published-history card leaves its potential current/history comparisons unresolved; without evidence to exclude them, those current endpoints remain on recoverable HOLD. A suspected same-run connection can propagate a HOLD within that connected component. These uncertainties and their scope must be visible, including the possibility that a cold/unavailable history source affects several current endpoints; they must not be reported as an empty soft pool or no qualifying news. A later eligible attempt follows the existing explicit technical backoff, without repair calls.

The final two-full-body duplicate policy, schema, model and Gemini authority remain unchanged. Existing final verdicts for exact material remain reusable across this admission transport reform. Local validation owns exact references, provenance, coverage and technical limits, not semantic vetoes. Same-run material updates still require the surviving article's own complete body to contain A+B.

Telemetry must reconcile captured newsroom URLs, cards, the entire eligible pair universe, retrieval exclusions, positive/negative admissions and unresolved pairs. The captured-input denominator must not be mislabeled as every URL in every RSS feed. Repeated observations, unique URLs, pair/material identities, provider attempts and final verdicts are distinct grains. Missing coverage is unavailable/partial, never a certified zero. Complete accounting does not certify AI semantic correctness. The noon report exposes these facts and technical gaps; changes to soft editorial selection remain a separate owner decision.

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
explanations and local headline/evidence heuristics cannot veto Gemini. Against a published history endpoint,
MATERIAL_UPDATE preserves eligibility without rewriting primary class. Successful Publisher history stays 12h.
Published duplicates prevail; unpublished duplicates retain richer factual content/media, with earliest arrival as
the informational tie-break. A losing URL is terminal SKIP under TOTEM-S01.

Owner clarification, 2026-10-15: for two unpublished articles in the same run, Gemini may designate B as the
sole surviving source of a MATERIAL_UPDATE only when B's own complete supplied body already covers the
substantive initial fact A (a faithful summary suffices) AND the update B. Arrival order, text length and shared
names alone do not establish coverage. No automatic article merging, stitching or invented recap is authorized.
If coverage is missing, uncertain, or neither source contains A+B, retain both eligible articles. The covered
initial URL may become terminal only with an eligible complete covering survivor. An update must not move
a MUST/SHOULD obligation into a lower frozen class or soft competition: retain both rather than reclassify.
The recent-history MATERIAL_UPDATE policy remains unchanged; this clarification does not tighten its
editorial threshold, reopen prior decisions or resurrect terminal URLs. Cyclic or unresolved replacement
directions must never eliminate every available source of the facts.

Owner-approved implementation, 2026-10-10: this supersedes combined primary/admission schemas and every model
repair path in these Active operations. Technical recovery is a subsequent operation under the explicit backoff,
not a request to revise an accepted classification or duplicate verdict.

## TOTEM-F01 — Complete source material before irreversible editorial decisions

Owner authorization, 2026-10-13: implement after an isolated RSS-versus-complete-body replay demonstrates
improvement; see `docs/implementation-notes/COMPLETE_EDITORIAL_MATERIAL_2026_10_13.md`.

For an eligible, as-yet unclassified feed URL, primary classification receives the entire cleaned, extraction-verified
article body. RSS metadata remains context, never an unlabelled substitute for a complete body. Terminal URL,
bookmaker and already-published exact exclusions remain before source work. Reports remain independent under R01/N01.

The body is reusable factual material across primary classification, independent pair admission, final duplicate
judgment and optional soft competition. It must not be silently truncated or require another semantic classification.
Body acquisition or transport-limit failure is a technical HOLD, not a primary SKIP. A failed candidate cannot
suppress an independent candidate whose input is complete. Missing published-body material may be visible as
explicitly unavailable metadata during suspicion election; an admitted comparison against it cannot issue a final
semantic verdict or clear its affected component until that body is available.

An article may contain multiple substantial autonomous factual developments. DUPLICATE cannot discard an entire
article merely because one development, one person or its opening recap is shared with an earlier article. A substantial
uncovered development against successful published history is MATERIAL_UPDATE. The judge is asked to identify
shared facts and uncovered facts before its verdict. Those explanatory fields remain nullable; local validation must
still accept a correctly bound final decision when local semantic evidence is insufficient. No repair is introduced.

This improves the input and execution of D01; it does not rewrite accepted classes, resurrect skipped URLs, extract
news from reports, alter pacing, or grant soft content an entitlement to publication. Cache expiry and body-cache
eviction never undo C01/S01. Diagnostic replays never apply their alternative decisions to production.


## TOTEM-P01 — Quality floor, frozen priority and rolling publication pressure

**Owner approved: 2026-10-24.** Explicitly supersedes earlier unconditional SHOULD publication/live exceptions and
calendar-day-only pacing where they conflict. Source/report independence, full-body input, immutable classes,
terminal skips, pair admission and duplicate authority remain in force.

- Use primary V10's always-on quality floor even at zero publications. New interviews, quotations and supporting
  medical/contract details do not automatically qualify as SHOULD or gain automatic SOFT admission.
- The first valid primary class remains final. coverage_priority is an intrinsic boolean assigned in that same
  primary call and frozen with it; true applies only to especially important SHOULD. Legacy decisions without
  this field retain their class and have no priority entitlement. No migration/reclassification calls are allowed.
- Count successful news in the preceding rolling 24 hours, excluding reports, dry runs and failed publications.
  The interval is (now minus 24 hours, now]. Midnight never resets pressure. Current-day reporting and the soft
  midnight lifecycle remain separate concepts.
- With fewer than 25 news already published/reserved, use strict ordinary selection. At 25–29, admit only MUST
  and priority SHOULD. At 30 or more, admit only MUST. All thresholds describe the count BEFORE the next item.
  Reserve headroom within each run so a batch cannot bypass a boundary. MUST is always exempt after duplicate
  clearance and technical safeguards; 30 remains a reference rather than an absolute mandatory-news ceiling.
- Apply the gate before translation and at Publisher, including retries. SHOULD rejected for pressure is terminal
  for its canonical URL, with its original class preserved for audit. It does not wait for midnight or enter SOFT.
  Ordinary per-run technical capacity overflow remains queued, subject to pressure on its next eligible attempt.
- Live SHOULD uses the same frozen priority/pressure rules; a report still cannot replace or suppress its individual
  news by itself. No automatic promotion to MUST, live-news count quota or new source synthesis is authorized.
- Soft capacity ends at 25 in the rolling window, subtracting strong reservations. Existing morning hold, optional
  competition, decay and midnight expiry continue. No unused slot creates publication entitlement.
- Record policy, rolling count, reservations, immutable priority, rejected URLs/reasons and publisher guard results.
  Noon observation distinguishes terminal pressure exclusions from duplicate exclusions and technical holds.

## TOTEM-D03 — Substantial follow-up

**Owner approved: 2026-10-24.** MATERIAL_UPDATE requires an important new development that almost independently
justifies an article AND occupies at least half the follow-up's substantive informational content, with old recap
included in the denominator. This is a semantic full-body assessment, not a deterministic word-count validator.
A+B same-run coverage and autonomous dedicated-news exceptions remain unchanged. V5 judgment is final for the
same material and contract; no repair or second semantic vote is introduced.

## TOTEM-T01 — Natural faithful wrestling Italian

**Owner approved: 2026-10-24.** Bob interprets idioms contextually, uses natural wrestling terminology, checks
agreement and preserves negation, causality, attribution and uncertainty. Complete text, quotes and media order
remain mandatory. Apply instructions within the existing translation call/model route; no global string-replacement
rules, additional translation pass, source biopic or CTA is authorized.
