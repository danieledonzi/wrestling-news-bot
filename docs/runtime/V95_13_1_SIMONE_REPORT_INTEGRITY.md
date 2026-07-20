# v95.13.1 — Simone Report Integrity

## Incident and invariant

The Saturday Night's Main Event incident was caused by treating an early live-coverage URL as a completed article and by relying on a later feed scan to rediscover it. A report-like title was therefore sufficient to enter the translation/publication path. v95.13.1 separates **URL discovery/reservation** from **source readiness**.

Massy dynamically compares generic results/report/live-coverage items with the effective event registry. Distinct factual stories (title changes, injuries, returns, backstage developments and similar novelty) remain Menzo news. A matched general report URL is persisted with its report/night identity and never falls through to Menzo.

## Reservation, 06:30 and retry lifecycle

`state/newsroom/simone_pending_reports.json` stores the normalized URL, report/night key, identity, source title, local date, category, discovery/check timestamps, publish-after time, readiness evidence and retry count. Repeated discovery of the same normalized URL and report key is idempotent.

Before the configured Europe/Rome `publish_after` (normally 06:30), the item remains `waiting_publish_after`: it is not translated, published, or treated as news. When due, Simone fetches the reserved URL anew. A scrape failure remains retryable. A preview/card/opening remains `waiting_source_completion` and is retried by the next natural newsroom run; it is not permanently worked.

The positive gate counts completed-outcome language and structured result blocks. A heading, URL, or title containing “results” or “live coverage” is never enough. Conversely, an introductory “Welcome” does not block an updated body that contains multiple real outcomes. The gate precedes Gemini and WordPress checks.

## Effective special-event registry

The tracked `config/special_events.json` remains the curated seed/fallback and is never rewritten by runtime refresh. Massy and Simone share `state/newsroom/special_events_effective.json`. At most once per 20 hours, the loader merges the newest structured Wikipedia schedule-layer artifact into a copy of the seed. Dated WWE (including NXT), AEW, TNA and ROH records become operationally confirmed. AAA, unsupported promotions and undated records are excluded. Multi-date records create independent night keys.

Curated events are never automatically deleted. Ambiguous proposals are skipped and diagnosed. Refresh failure uses the prior runtime registry, then the static seed if no runtime state exists. Diagnostics identify `refreshed_structured_schedule`, `prior_runtime_state`, or `static_fallback` and include accepted, skipped and ambiguous records.

## Multiple reports and idempotency

Weekly shows and any number of confirmed event nights coexist because deduplication uses `report_key`/`night_key`, not date. The old single-special-report slot is removed. `SIMONE_MAX_REPORTS_PER_RUN` is a technical safety cap (default 4); deferred rows are counted rather than silently discarded. Publication catches each report failure independently, so Collision and a WWE PLE can both be attempted in one run. Existing status, manual-run and publication-history checks remain authoritative.

## Attribution versus removable boilerplate

Source attribution is mandatory and is not boilerplate. Every publication ends with one visible, linked `Fonte: Wrestling Inc.` or `Fonte: Ringside News` footer; `original_url` and `report_key` remain WordPress metadata. Attribution finalization is idempotent.

Only strongly identified source editorial text is removed. Leading Wrestling Inc. live-coverage announcements/start-time invitations are removed before translation. Actual first results and contextual openings remain. High-confidence author biographies are detected conservatively from combined author/staff, Ringside News, wrestling-writing/experience, syndication and outlet-list signals, primarily in trailing blocks or explicit bio containers. English and Italian forms are handled without keying on one author name. Defensive rendered-HTML cleanup runs before the source footer is appended.

## Observability

Artifacts expose registry source/refresh status; reserved URLs; `waiting_publish_after`; `waiting_source_completion`; ready/published counts; multi-report processing; incomplete pages blocked before Gemini; intro, biography and final cleanup counts; and reports deferred by the safety cap. Existing Gemini ledger fields and v95.12/v95.13a meanings are unchanged and no diagnostic requires a Gemini call.

## VPS smoke test (non-publishing)

1. Set `V93_SIMONE_REPORT_DRY_RUN=1` and use a temporary state directory or backup runtime state.
2. Place a generic Wrestling Inc. event live-coverage fixture in a mocked Massy feed result before 06:30 Europe/Rome; verify one pending reservation and no Menzo handoff.
3. Mock the URL with preview-only blocks after 06:30; run Simone's publisher entry point and verify `waiting_source_completion`, zero Gemini calls, and zero WordPress calls.
4. Replace the mock with at least two completed outcomes; verify `ready_complete_results` and dry-run progression.
5. Supply complete Collision and PLE fixtures together; verify two distinct keys and two independent dry-run results.
6. Inspect rendered fixture HTML for exactly one linked `Fonte:` footer and absence of the coverage introduction/author biography.

Never use this smoke test to invoke a real WordPress endpoint or any report/email delivery script.
