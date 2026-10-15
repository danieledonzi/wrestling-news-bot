# Bound semantic admission and complete same-run updates

Authority: owner instruction, 2026-10-15 23:38 Europe/Rome. Baseline: PR159,
`c3012140f9049210084b3f494cb4da54e4420d65`.

## Evidence and bounded correction

After noon on October 15, eight primary and two soft admission responses failed
with `semantic_admission_ref`; backoff delayed eligible news. The old diagnostics
retain `invalid_endpoint` but not the returned refs, so they cannot establish which
individual failures were invented indices, wrong prefixes, history-left or self-pairs.
Do not present that unavailable distinction as an observed fact.

The old provider schema accepted any a/h index with the right spelling. The v4
admission contract enumerates only the actual refs supplied in each request: current
articles on the left, current/history targets on the right. Both primary and soft
admission use the same bound schema. Unknown refs and self-pairs still fail closed;
there is no guessed rebinding, silent dropped comparison, all-pairs matrix or repair.
New bounded diagnostics retain the offending refs and table sizes without bodies.
Explicit complete empty election and unchanged successful clearance remain valid.

## Same-run A+B rule

The v6 duplicate schema and v3 judgment policy allow Gemini to identify the covering
side of a same-run MATERIAL_UPDATE. That side must already contain the initial
substantive fact (a summary suffices) and the additional development in its complete
source body. Only that existing body proceeds; Bob is not asked to assemble sources.

No side, uncertainty, incomplete input, a missing covering survivor or a frozen
lower-priority covering class retains both. No primary class is changed. Explicit
coverage chains retain a complete final source; circular graphs without such a
survivor retain their sources. Ordinary duplicate decisions are applied first, so a
covering URL already eliminated as a published duplicate cannot suppress another
initial URL. Valid covered-URL SKIPs are permanent even if projection later fails.
Primary and soft paths share this rule. Recent-history MATERIAL_UPDATE is unchanged;
the Crown Jewel case does not cause a stricter cross-run editorial threshold.

## Non-regression and release

TOTEM-D01/C01/S01/F01 and scoped fail-closed guardrail MD-09 apply. Models, pacing,
report/news separation, bookmaker exclusions and successful-publication history
remain unchanged. Contract fingerprints distinguish the new judge/admission without
clearing first classes, permanent SKIPs, history or caches. No additional provider
stage or corrective call is introduced; changed contract may require fresh clearance.

Offline tests cover exact schema enums, invalid refs, primary/soft contracts, A+B in
both endpoint orders, unconfirmed coverage, class preservation, recent history,
eliminated covering sources, chains and cycles. Run only `pytest tests` in an isolated
checkout: repository-root collection contains operational scripts. Isolate the Gemini
ledger for post-deploy tests so fake providers cannot contaminate production costs.
Baseline has one known oversize-hold retry test failure; compare full-suite outcomes
without changing that separate behavior. Compile and validate SDK schema construction
on installed Python before closure. Real invalid-ref frequency and recovery latency
require observation of subsequent scheduled runs; mocks do not prove model quality.

Rollback reverts code/policy refs, never accepted classifications or terminal SKIPs.
Any new residual invalid refs remain technical HOLD with bounded evidence for review.
