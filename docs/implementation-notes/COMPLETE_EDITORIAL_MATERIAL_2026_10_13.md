# Complete editorial source material and observable decision paths

Owner authorization: 2026-10-13, conditional on a read-only comparison demonstrating improvements. Base:
`cd5a58c38c2648031e9adb0d1fe15d5487ead8c5` (PR157), confirmed on repository main and VPS.

## Isolated evidence

The same model (`gemini-3.1-flash-lite`), frozen v9 classification criteria and original retained RSS inputs were used.
Current bodies were obtained through Bob's existing completeness-verified extractor or immutable source archives.
Each controlled variant was repeated three times. These are reconstructed controlled comparisons, not an exact
replay of the historical whole-run context. Current fetched bodies may differ from their original publication version.
No production classification, tombstone, queue, duplicate cache, provider ledger or WordPress state was changed.
Diagnostic material and raw responses were kept under `/tmp/owtv-fulltext-*-20261013` on the VPS, outside production.

| Case | RSS baseline (3 trials) | Full body with unchanged policy (3 trials) |
|---|---|---|
| Penta creative plans | 2 PUBLISHABLE_SOFT, 1 SKIP | 3 SHOULD |
| Tiffany booking rationale | 2 PUBLISHABLE_SOFT, 1 SKIP | 3 SHOULD |
| Jacy professional mentorship | 3 SKIP | 2 PUBLISHABLE_SOFT, 1 SKIP |
| Leon title victory control | 3 MUST | 3 MUST |
| Leon off-air speech | 3 SHOULD | 3 SHOULD |
| Routine fan-dislike control | 3 SKIP | 2 SKIP, 1 PUBLISHABLE_SOFT |

Complete body alone did NOT fix the two false duplicates: Omega/Moxley and Ben Bishop stayed DUPLICATE in 3/3
trials. A general all-developments clarification alone was also inconsistent. A final controlled variant asked for
`shared_fact` and `new_fact` before `decision`, using complete bodies and the unchanged mechanical ref/decision
validator. Omega/Moxley and Bishop became MATERIAL_UPDATE in 3/3 trials each; the true Tiffany duplicate stayed
DUPLICATE in 3/3. The final schema/policy implement that tested variant. Explanation fields accept null, and the
runtime validator still accepts a sparse, correctly bound final decision. There is no semantic repair or second judge.

The replay supports the conditional reform, not a claim of universal correctness. The fan-reaction control and
remaining class variability are explicit limitations; a body-completeness ratio is not an editorial quality score.

## Implementation and preserved authority

Active acquires a complete body before a new primary decision, persists reusable validated material, and supplies
the body to the independent admission and duplicate operations. The first primary store is not cleared or version-
invalidated. Terminal/published URL exclusions still precede fetching. Source failures retain a dated, bounded
technical retry opportunity; no class or editorial tombstone is invented. Their pending handoff is separate from the
soft board. Missing history bodies block only actually admitted comparisons and connected current components.

Optional soft review receives full source text alongside its existing context and disposition contract. Primary
classifications, soft capacity, midday start, three meaningful reviews, report source/layout, models and Bob translation
policy are unchanged. Complete material is never silently shortened to fit a provider bound; existing oversize holds
remain visible. The frozen Shadow operation is not changed.

## Metrics and interpretation

The noon report JSON/Markdown/email expose:

| Metric | Authority / grain | Interpretation |
|---|---|---|
| Source extraction, canonical reuse and holds | Canonical source events; endpoint-stage observations and unique held URLs | HTTP/source reuse, distinct from Gemini pair or implicit token cache |
| Full-body coverage, endpoint lengths/hashes, prompt bytes | Exact provider-input profiles per logical request | Full material supplied, not semantic correctness |
| Final DUPLICATE / NO_MATCH / MATERIAL_UPDATE | Canonical verdict events keyed by pair + input-material hash + contract | Both primary and soft paths; repeated/cache observations are not new pairs |
| Duplicate components and update links | Recorded final decisions only | No lexical/show clusters; MATERIAL_UPDATE never merges duplicate components |
| PR131 cycles, lookups, hits, misses, hit rate, stores, requests avoided | Existing canonical PR131 reader | A pair hit is not a whole provider request avoided; confirmation is a historical field only |
| Pair-cache entry count | Current file snapshot | Not historical efficiency or proof of a hit |
| Workload calls, input/output/cached/thinking usage, costs, models and failures | Gemini economic ledger | Standard-list-price calculation, distinct from actual billing |
| News/editorial vs report costs and attempts per publication | Ledger partitions / canonical publication denominator | Window efficiency including skipped/pending work, not marginal per-article cost |
| Classes, final skips, cohorts, soft review dispositions | First-class store and retained chronological lifecycle | Classification and soft disposition remain distinct; no volume target |

All profiles/records and economic breakdowns are attached in the current report JSON. Pre-cutover, partial or corrupt
evidence yields unavailable window totals, with the observed sample retained separately. Source caches do not become
historical authorities. The existing dated observation journal and owner-approval gate remain unchanged. No legacy
lexical cluster recommendations or report-versus-news suppression metrics are reinstated.

## Consolidated pre-PR review

PR158 identified a transport-bound handoff gap. Existing terminal-memory guards already reject
technical fail-closed skips, but oversized complete-body batches did not retain fresh feed URLs
for retry. Primary, admission and duplicate input bounds now persist the affected candidates in
the existing bounded technical-hold container and expose a pending handoff with no publication
authorization. Independently final primary SKIPs and duplicate decisions remain terminal; reused
primary classes survive retries. Bodies are not truncated, soft-board reviews are not consumed,
and no provider repair or confirmation call is added.

The recovered implementation was reviewed against the production baseline without new provider calls or replay
generation. Four concrete P1 families were reproduced offline and corrected together:

- Complete-source contracts must also bind to the endpoint's canonical source URL. A mismatched archive is discarded
  before extraction; a corrupt source cache is preserved and cannot manufacture an editorial SKIP.
- Source failure in soft competition holds only affected URLs and admitted connected components. Complete independent
  URLs can compete; held URLs persist without consuming meaningful reviews or changing their primary class.
- Source sessions and verdict batches have explicit observation identities and closure counts. Missing/malformed
  evidence produces unavailable totals. Repeated input observations are distinct from unique logical requests,
  attempts and pair/material verdicts. No observer failure can veto a valid editorial decision.
- Missing economic evidence is unavailable rather than a known zero. Actual report producers are recognized from
  explicit pipeline/phase evidence when workload is absent. Unattributed work remains separate and prevents a complete
  news-cost-per-publication claim. Retry/fallback totals require valid economic evidence.

The existing same-run winner fix reuses extracted canonical bodies; all-primary-SKIP cycles avoid irrelevant history
extraction. Classification policy, single-attempt semantics, optional nullable rationale fields, tombstones, live-show
coverage, bookmaker exclusion, report autonomy and the 12-hour Publisher window are unchanged.

Pre-PR regression coverage is in `tests/test_complete_editorial_material_review.py`, including source URL mismatch,
corrupt cache preservation, scoped soft holds and persistence, missing source/input/verdict events, repeated profiles,
malformed payloads and report/unknown-workload cost attribution. Controlled replay outcomes remain case-specific
diagnostic evidence. Neither full-body coverage nor these offline tests certify universal editorial accuracy or savings.
