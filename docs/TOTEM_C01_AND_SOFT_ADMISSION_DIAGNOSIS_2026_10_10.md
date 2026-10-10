# TOTEM-C01 and soft duplicate-admission diagnosis

Owner instruction: 2026-10-10, after the first-hours V8 observation. This document records evidence and a
historical proposed implementation. Its repair proposal is superseded by the owner-approved no-repair V9 release
described in `TOTEM_C01_INDEPENDENT_DUPLICATE_RELEASE_2026_10_10.md`; historical findings below remain unchanged.

## Confirmed production boundary

Observed deployed commit: `ea3f266bc09adac4d25f86c1f90dc16c68fa6302`.
Window: 2026-10-10 16:35 UTC to 21:12 UTC, nine completed runs.

Each soft-pool duplicate-admission operation called Gemini once and attempted one validation repair. All nine
operations ended in TECHNICAL_BLOCK and WAIT_DUPLICATE_CLEARANCE. The failure occurs before meaningful
soft-board competition. The primary pipeline's VALIDATED status does not establish soft-stage success.

`menzo_soft_board._revalidate_pool_duplicates` calls `active._classify` with no fresh classification candidates,
but with fixed-class pool articles in the admission context. A non-VALIDATED result causes
`ValueError('semantic_admission_failed')`; the catch replaces the result with TECHNICAL_BLOCK and exports
only `technical_block_reason='ValueError'`. The underlying validation_errors and validation_attempts are lost.
An additional read-only check confirmed that all nine admission metadata records contain only status, exception
class, semantic version and call count. Existing accounting/event producers do not persist response JSON.
No raw/provider-response artifact filename was found in newsroom state. Therefore the exact rejected field in
the historical responses cannot be established from those retained records.

## Repair mechanism

`active._classify` allows at most two provider attempts: an initial request and one repair. Provider exceptions
return immediately. After a response, the local validator decodes JSON and validates classification references,
coverage, classes/actions, followed by semantic-admission completeness and endpoint binding.

The repair uses the same primary output schema and full primary policy. `_prompt` appends at most 20 technical
validation failures as `REPAIR ONLY THESE VALIDATION FAMILIES`; it does not include the rejected response JSON.
If primary classification was invalid, the same classification input is resent. If all primary classes were valid
and only admission failed, those classes are frozen in memory, SKIP URLs are removed, and admission is repaired
using the surviving fixed-class context. In the next scheduled run a blocked pool repeats this operation; the
two-attempt bound is per operation, not a bound on calls across runs.

The full-material duplicate gate has a separate repair path: it preserves independently valid relation decisions
and targets unresolved relation refs. The observed 18 failed calls belong to admission, not that full-material gate.

## Four offline reproductions

Executed the actual V8 functions with synthetic URLs and mocked responses, suppressing ledger/state writes and
using no external provider. All four checks passed:

1. Admission-only input has zero fresh c refs and two fixed a refs. If a response classifies c0/c1 anyway, both
   attempts fail with candidate_ref. Repair retains the same input and primary schema. This is a demonstrated
   failure mechanism, not proof that the historical Gemini responses contained those rows.
2. The same admission input with candidates=[], relations=[], admission_complete=true and an empty suspicion
   list validates in one attempt. Zero plausible pairs is a valid clearance result.
3. When every initial primary class is valid but admission_complete=false, a successful admission repair
   preserves the initial classes even if the repaired response tries to change them.
4. When one primary row lacks story_core, another valid row is discarded with the invalid batch. A repaired
   response can change that otherwise valid row from PUBLISHABLE_SOFT to SHOULD. This is an additional
   violation of the newly ratified TOTEM-C01, distinct from later-run reclassification.

## Proposed correction

- Give admission-only requests a dedicated schema and prompt: admission_complete and suspected_duplicates,
  with no classification or final duplicate-verdict output. Use a dedicated validator; do not run primary
  classification validation on an operation with no unclassified candidates. Apply this to soft-pool admission
  and admission-only repairs after primary decisions are fixed.
- Persist sanitized technical telemetry: stage, attempt, validation family, field/ref, coverage, response shape,
  input/contract fingerprint and logical request ID. Propagate those records into soft-stage results and the
  master log. Distinguish provider failure, malformed response, admission invalidity and full-gate invalidity.
- Freeze and durably store the first valid classification per canonical URL before downstream work, preserving
  valid rows individually even if sibling rows or admission fail. Reuse all four classes, not only queued MUST
  and SHOULD. Keep original primary class separate from terminal downstream disposition.
- Repair only unresolved technical fields/rows; do not ask Gemini to reconsider valid class or relation decisions.
  The repair context must identify the precise invalid structure and preserve the already accepted decisions.
- Reuse valid admission clearance only for unchanged eligible material/history/contract. Avoid repeating an
  identical failed repair in every timer run without a declared recovery condition; classify deterministic
  contract failures separately from transient provider failures. A hold must never become an invented SKIP.
- Repair existing contradictory strong/soft queue state using the earliest valid primary decision and preserve
  audit. Weak SOFT is SKIP; PUBLISHABLE_SOFT retains optional competition. Do not infer that every eligible
  PUBLISHABLE_SOFT must be discarded solely because its attempted SHOULD promotion was invalid.

Normative authority: docs/OWTV_TOTEM_INVARIANTS.md, TOTEM-C01, and the editorial soft-board contract.
The active V8 provider policy, source code and production state were not modified by this diagnostic work.
