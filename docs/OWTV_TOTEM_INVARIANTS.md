# OpenWrestlingTV — TOTEM Invariants

**Status:** OWNER-ratified, canonical normative authority  
**Scope:** OpenWrestlingTV
**Owner-approved clarification:** 2026-10-10 — feed-URL news coverage and Gemini semantic authority.

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
under the bounded repair/fail-closed contract. Semantic decisions must not be invented locally to resolve them.

Owner decision, 2026-10-10: this rule supersedes earlier requirements that made local semantic anchoring a veto over
an otherwise well-formed, endpoint-bound Gemini decision. Runtime changes implementing it require their own reviewed release.
