# v95.18 deterministic duplicate suspicion gate — implementation notes

## Root cause and design

v95.17 cached semantic decisions but formed requests from a universal same-run
snapshot and a broad recent-history frontier. Consequently Gemini still proved
that unrelated stories were distinct. v95.18 moves admission ahead of cache and
Gemini: every actionable pair is scored, exact duplicates are resolved locally,
and only above-threshold edges enter arbitration.

`agents/menzo_duplicate_scorer.py` is a pure Python 3.9-compatible scorer with
stable version `v95.18-deterministic-suspicion-2`. Its six normalized components
use the approved weights (0.30 entity, 0.25 central action, 0.20 event/show,
0.10 promotion, 0.05 time, 0.10 lexical), subtract the four approved explicit
incompatibility penalties, then clamp to `[0, 1]`.

The shared threshold is read from `MENZO_DUPLICATE_SUSPECT_THRESHOLD`, then the
temporary `MASSY_DUPLICATE_SUSPECT_THRESHOLD` fallback, then `0.55`. There is no
grey zone. Scorer version and effective threshold are cache-contract inputs.
Version 2 conservatively maps English and Italian central-fact vocabulary into
the same action categories and recognizes Italian month names. This permits the
English current feed to be scored against Publisher-shaped `title_it` history
without treating generic Italian words as action evidence.

## Runtime behavior

Same-run exact canonical-URL and material-hash duplicates retain the richer
deterministic winner without Gemini. Non-exact above-threshold pairs form graph
edges; Gemini receives exactly one request for each connected component. An
isolated node is marked distinct and never enters a prompt.
Distinct and Gemini no-match records remain ordinary articles with no Menzo
duplicate metadata, preserving Publisher compatibility. Cached no-matches use
an empty decisions map and rehydrate no metadata.

Recent history is loaded only from `publisher_history.json`. The loader accepts
successful publication statuses inside the configured lookback, rejects future,
failed, pending, skipped and dry-run entries, requires a canonical source URL,
and deterministically retains the newest/most complete record per URL. Each
survivor is compared with every loaded publication, but its request contains
only above-threshold publications. Exact history matches block locally.

## Cache, failures, and diagnostics

The contract is `v95.18-suspicious-doubts-1`; prompt and validator versions also
advance to v95.18. A same-run entry is one suspicious component plus its scoring
identity. A history entry is one candidate plus only its suspicious published
set. Member material changes therefore invalidate only the affected unit, while
below-threshold additions cannot invalidate it. Existing canonical JSON, strict
decision validation, cooldown, fsync, temporary write and atomic replace remain.
Old v95.17 state cannot match the new fingerprint and behaves as empty state.

Failures are keyed by component/candidate suspicious-set identity. Fail-closed
handling is confined to that unit; independent components and isolated records
continue. Postprocess includes all v95.18 theoretical/exact/below/above,
component, prompt-member, cache and actual-call counters. Bounded audit records
are retained only for above-threshold pairs. Usage and cost remain `null` when
the call layer supplies no measured ledger values rather than being presented as
measured zero.

Each suspicious unit retains the strict batch, one same-subset repair, and
same-subset micro fallback sequence. Cache hits and cooldowns use the avoided
call ledger path. Audit evidence is capped at 50 records per run and reports an
omitted-record counter. Every retained record is finalized with cache status,
Gemini outcome, and editorial disposition. Same-run accounting obeys
`theoretical = exact + below threshold + above threshold`; recent history
evaluates every theoretical pair even when an exact match blocks the candidate.

Every Gemini invocation carries the content-addressed suspicious-unit key as
`cluster_id`. Same-run batch, repair and micro calls share the component key;
recent-history calls share the candidate/subset key and current URL. Model
cooldowns are therefore isolated rather than falling into a global `unknown`
bucket. `actual_gemini_request_count` is incremented only after the call layer
confirms a real request; missing-key and model-cooldown avoidances are excluded.

Same-run audit finalization is pair-specific. An edge is `DUPLICATE` only when
both endpoints resolve to the same non-empty winner identity. Other edges are
`NO_MATCH / ordinary_pair`, with endpoint dispositions recording ordinary,
winner, loser, or blocking caused by another edge. Cache hits reconstruct the
same edge semantics from validated cached decisions.

Recent-history audit finalization is also pair-specific. Only the edge whose
publication identity matches the validated `published_id` (or cached
`menzo_compared_with_url`) receives `DUPLICATE / blocked` or
`MATERIAL_UPDATE / material_update`; every other suspicious publication edge
is finalized as `NO_MATCH / ordinary_pair`.

## Files and tests

Production changes are limited to the Menzo policy, cache helper and new scorer.
Focused tests cover formula/threshold precedence, distinct isolation, suspicious
prompt membership, exact resolution, Publisher-history filtering, recent subset
prompts and cache metadata rehydration. Tests redirect cache and history to
temporary paths.

## Rollback

Reverting these files restores the prior arbitration flow. The v95.18 cache is
safe to delete; older code will reject it by contract fingerprint. No production
publication, model-routing, budget, scoring, Publisher, or workflow state is
migrated by this change.

## Historical test retirement

The v95.17 universal actionable-snapshot and reviewed-history-frontier tests
were retired with that architecture. v95.18 regression coverage is written
against suspicious connected components and candidate-specific authoritative
Publisher subsets; obsolete architecture tests are not migration requirements.
Operational verification continues on the VPS after merge.
