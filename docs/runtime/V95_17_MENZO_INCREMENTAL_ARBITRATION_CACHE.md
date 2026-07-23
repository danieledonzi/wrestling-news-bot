# v95.17 Menzo incremental duplicate-arbitration cache

## Production cost problem

Repeated half-hourly runs were sending unchanged candidate batches to Gemini. The legacy cache was TTL-oriented and represented the retired pre-batch contract, so it could not safely reuse current validated batch outcomes.

## Content-addressed validity

The v2 cache is `state/newsroom/menzo_duplicate_arbitration_cache_v2.json`. Candidate identity is the repository-normalized canonical source URL. Candidate material is canonical JSON derived from the compact prompt record; batch aliases, clocks, scores, run identifiers, counters, and diagnostics are excluded. Keys include schema, contract, model, prompt-builder, and validator versions. Decisions do not expire merely because time passes.

## Gates and scopes

The order-independent actionable snapshot gate reuses a complete cached decision set when the candidate identity/material pairs are unchanged. Same-run state records every candidate material hash, validated duplicate group, authorized representative, loser, and explicit standalone survivor. A delta run rehydrates old outcomes and submits only new or changed candidates plus cached authorized representatives; cached losers never return to Gemini. Recent-history entries are per candidate and include only broadly plausible records selected with the repository's existing same-story signals (plus URL-slug continuity). Cache hits rehydrate all eight downstream `menzo_duplicate_*` fields and the validated disposition before the normal pipeline continues. A candidate with no plausible comparison material makes no Gemini request.

Every completed entry distinguishes `validated_decisions` from `validated_no_matches` and records evaluated candidate identities, their exact material hashes, comparison hash, contract fingerprint, complete decisions, and the actual request count (batch, repair, and micro fallbacks) used to obtain it. Avoided-call accounting reuses that recorded count rather than assuming one call.

Same-run state explicitly stores `groups` keyed by deterministic group ID, with the authorized representative, complete member IDs and material hashes, winner URL, and `standalone_survivors`. Recent-history entries are keyed by an exact relevance-set group and store per-candidate outcomes, exact comparison records, request count, and origin request-group ID. Candidates with different relevance sets never share a prompt.

Before partial reuse, the complete same-run state is validated for contract, outcomes, dispositions, group membership, representative authorization, winner references, hashes, and disjoint standalone survivors. Removing any group member invalidates only the remaining current members of that group; removed candidates and standalone survivors are pruned. URL-slug continuity ignores promotion, publishing, numeric/date, short, and other generic terms and requires two meaningful overlaps (or a meaningful overlap backed by an existing full-entity signal).

## Failure cooldown

API or validation failures are never editorial cache entries. An identical failed request receives a two-hour configurable cooldown (`MENZO_DUPLICATE_FAILURE_COOLDOWN_HOURS`); changed candidate, comparison, or contract material bypasses it. Writes use a same-directory temporary file, flush, `fsync`, and `os.replace`.

## Counters and verification

Menzo postprocess exposes unchanged/no-comparison gates, same-run and recent-history hits, candidate/comparison/contract invalidations, failure cooldown hits, recomputed components/groups, planned/executed/avoided calls, cache load status, and entry count. Avoidances are additive Gemini-ledger events with explicit reasons. Operators can compare two identical runs: the second must show zero executed duplicate calls and cache/gate hits, while selected/pending/skipped and authorization remain semantically equivalent.

## Rollback

Rollback the code and leave or delete the v2 file. Older code does not read it, and v95.17 never migrates or trusts the legacy v1 cache. A missing or malformed v2 file is treated as empty and cannot block Menzo.

This version does **not** change the Gemini model, prompts, validators, winner rules, or editorial duplicate policy.
