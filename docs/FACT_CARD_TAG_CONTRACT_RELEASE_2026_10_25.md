# Factual-card tag contract — 2026-10-25

Owner authorization: implement the circumscribed correction discussed on October 25, including release and VPS validation. Baseline main/production: `fdf24676dc35a6c0ae86cdd0f2e7cb5023f505f3`.

## Observed failure and scope

The WrestlingInc women's Blood & Guts announcement was classified MUST on its complete retained body. Extraction succeeded. Enrichment failed with `fact_card_shape / invalid_episode_tags` at 18:55 UTC. The next run respected the one-hour technical backoff. The original rejected response was not retained, so the exact offending value cannot be reconstructed. One failed enrichment was observed among 172 extraction/enrichment provider calls in the preceding 72 hours; this is not evidence of a broad editorial selection failure.

The provider schema omitted bounds enforced locally: nonblank strings, 150 characters per tag, 64 tags per array. This mismatch reproduces the same rejection with synthetic inputs. The correction exposes the existing bounds and concise-tag instructions in enrichment schema descriptions; local validation remains authoritative. Google documents that string length keywords are not enforced during constrained decoding, so descriptions guide generation and local checks remain necessary: https://ai.google.dev/gemini-api/docs/structured-output . No claim is made that schema annotations guarantee every future response will validate.

## Resulting behavior

- Enrichment schema exposes the existing bounds for tag lists, identities, and evidence lists. Exact owned-reference checks remain unchanged.
- Tag diagnostics identify the owned fact reference, field, element index, failure type and applicable numeric bound. Rejected source text or private model reasoning is not stored.
- Card observation events retain bounded validation errors and retry times, including when a later run reuses a technical failure during backoff.
- Partial successful handoffs distinguish factual-admission technical holds from missing complete source bodies. No decision authority is migrated.
- Valid legacy enrichment cache entries are independently revalidated and reused with their original provenance/card hashes. Existing card/pair decisions are not invalidated merely by adding schema bounds. Invalid legacy outputs do not grant clearance.

## Preserved contracts

Primary classes remain frozen; terminal SKIP remains terminal. No facts are reassigned or rewritten. Pair admission remains complete and conservative; the final duplicate judgment still receives full bodies. No fallback can publish through an unresolved duplicate check. Models, 12-hour history, source extraction, report scheduling, publication pressure and translation behavior remain unchanged. No new provider stage, repair loop or paid diagnostic is introduced.

Applicable guardrails: AA-03 (identity before aggregation), MD-09 (scoped technical failure), CP-02 (immutable retained material), GC-03 (ledger cost authority), CR-04 (production validation before closure).

## Validation and release

The isolated Python 3.9 VPS regression suite includes tag boundaries, invalid/foreign references, scoped holds, frozen MUST recovery without reclassification or repeated extraction, and legacy cache/card/pair reuse without provider calls. All provider responses in tests are synthetic. Production validation must verify deployed bytes, compilation, targeted tests in an isolated checkout and the unchanged production state/timer baseline. The Blood & Guts URL is left to the ordinary scheduled pipeline; there is no manual publication or state rewrite.

Rollback is a code revert to the previous main commit. State formats, cached successful cards, frozen classes and final duplicate verdicts remain compatible; no cache purge or state migration is required.
