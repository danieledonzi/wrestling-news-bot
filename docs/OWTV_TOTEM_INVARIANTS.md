# OpenWrestlingTV — TOTEM Invariants

**Status:** OWNER-ratified, canonical normative authority  
**Scope:** OpenWrestlingTV

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
