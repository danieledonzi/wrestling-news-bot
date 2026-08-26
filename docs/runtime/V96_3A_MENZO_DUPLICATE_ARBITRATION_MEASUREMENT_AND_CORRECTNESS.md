# V96.3A Menzo Duplicate-Arbitration Measurement and Correctness

## Base and scope

Implementation base: `beb0c926ccf0c5655a80486008ad45de56ffc0b6` (`main`, OWNER-verified).
V96.3A is measurement/correctness-only: it fixes recent-history cooldown expiry,
retains repair and fail-closed explanations, reports active cache-v2 behavior over
master-log windows, and closes recent-history temporal cache validity. The Gemini
ledger remains authoritative for provider attempts, tokens, and cost.

## Failure cooldown

A real failed recent-history arbitration records `failed_at`, `retry_after`, and
increments `attempt_count`. A lookup hit before `retry_after` is read-only: it
avoids the call and emits cooldown evidence, but never calls `record_failure`.
Once expired, the same request key may call Gemini; only a real new failed attempt
records a new deadline. Changed candidate, comparison, or contract material has a
different content-addressed key.

## Diagnostic contract

Bounded diagnostic rows use the existing Menzo postprocess -> newsroom master-log
path. A repair row retains scope, existing request-key unit identity, normalized
trigger reason, primary validation result, repair-attempt flag, terminal result
and reason, candidate/comparison counts, and contract fingerprint. Provider
attempt details and economics are intentionally not duplicated.

Fail-closed rows retain scope, deterministically known cause, affected grain
(candidate or component), request-key identity, counts, and contract fingerprint.
The historical `menzo_duplicate_arbitration_fail_closed` counter is unchanged.
Instrumentation is bounded and fail-open and has no editorial authority.

Master-log window aggregation exposes repair-reason, terminal-result, and
scope/grain/cause distributions. The same retained run records provide bounded
24-hour, 72-hour, and 7-day observation when those windows are requested.
New V96.3A cache/cooldown counter sums are full-window facts only when
`v96_3a_counter_stream_complete` is true; pre-cutover and straddling windows
retain explicitly partial sums with covered-run and total-run counts.

## Active cache-v2

Diagnostics now identify active-v2 hits, misses, calls avoided by validated reuse,
failure-cooldown hits/calls avoided, contract invalidations, and unclassified
misses. Candidate/comparison invalidation is not exposed as a zero-valued metric
because current cache evidence cannot classify it reliably. Unknown miss causes remain
`other`; no state reconstruction or guessed classification occurs. Gemini cache
inspection reads `menzo_duplicate_arbitration_cache_v2.json`, reports its
content-addressed contract/entry/failure state, and does not apply retired-cache
TTL semantics.

## Temporal validity and transition

Recent Publisher comparison material is hashed with normalized `published_at`,
because the current prompt and material-update validator consume that clock.
Same-run candidate hashing and identity are unchanged. The explicit arbitration
contract is `v96.3a-recent-history-temporal-material-5`; its fingerprint makes all
pre-V96.3A entries cold without migrating or inferring outcomes. A valid cache
rehydration preserves the live semantic outcome, differing only in provenance
and avoidance diagnostics.

## Validation and later observation

Regression validation covers deterministic exact/below-threshold gating,
suspicious-component isolation, Publisher-only 12-hour history, duplicate,
NO_MATCH and material-update outcomes, isolated fail-closed behavior, read-only
cooldown hits and expiry, changed keys, repair/terminal diagnostics, active-v2
reuse/invalidation, old-contract rejection, semantic rehydration, and fail-open
instrumentation.

Post-deploy validation is not part of this change. At 24 hours, verify installed
commit, timers/runtime, newsroom behavior, and telemetry emission. At 48–72 hours,
verify genuine cooldown expiry, v2 reuse, repair reasons, and fail-closed causes.
At 7 days, review primary/repair counts and rates, repair/terminal/cache/fail-closed
distributions, and Menzo provider attempts/tokens/cost from the V96.2 ledger,
including primary/repair phase where ledger correlation permits.

## Deferred work and rollback

V96.3B remains deferred: structured output, targeted or partial repair, salvage,
frontier/delta reuse, V95.17 restoration, batching, normalization, prompt/body
reduction, scorer/threshold/model/policy changes, reporting redesign, and any
Editorial Director or semantic projection are absent.

Rollback is the code commit only. Cache-v2 is an optimization, so a missing,
old-contract, or malformed cache fails open to live arbitration. Do not rewrite
runtime cache state or migrate decisions during rollback. Reverting restores the
old fingerprint but must be OWNER-reviewed because those old entries omit the
new temporal validity input.
