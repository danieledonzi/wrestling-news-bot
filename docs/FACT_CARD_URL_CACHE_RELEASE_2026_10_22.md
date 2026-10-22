# Canonical URL reuse for factual cards — 2026-10-22

Owner authorized the bounded correction after the read-only cost investigation.
Canonical main and production base: `fa5606a34f55c7956e667dcc9fe809b82f421b6b` (PR169).

## Reproduced waste

During October 19 and 20 in the billing graph's PDT timezone, 54 articles purchased extraction and
enrichment again on entering published history despite identical titles, complete body hashes, model
and policies. The input URL changed from the feed's www/trailing-slash representation to the history's
canonical representation. Those 108 redundant operations cost USD 0.18319125: 0.09446425 on October 19
and 0.08872700 on October 20, 19.15% of the USD 0.95640725 measurable ordinary cost. Two articles whose
bodies actually changed are excluded. These are measured historical operations, not a promised future
daily saving. Ten separate diagnostic ledger rows without usage remain unpriced, not zero.

For Bayley's Big Time Wrestling anniversary article the two retained extraction keys were reconstructed
from the real full source. The only payload difference was source_url; both distinct cache entries exist.
Other controls found no repeated exact-material final judgments, retry/repair loops or paid card work after
terminal SKIP. All 58 generated news articles in the window have successful publication evidence.

## Narrow implementation and authority

In `menzo_fact_cards` only, use the existing `canonical_source_url` identity for the card source payload,
the owned fact identity and the source-stage technical-recovery binding. This keeps equivalent URL spellings
from changing either stage's request fingerprint, fact refs, completed card hash or admission cache inputs.
Complete source units and titles remain exact. Host/path/scheme distinctions follow the already installed
article identity contract; no new semantic URL matching or cross-article fact reassignment is introduced.

No cache schema/version bump or cache purge. Existing canonical-URL stage outputs and completed cards remain
byte-compatible and reusable. A legacy noncanonical-only entry, with no canonical counterpart already stored,
can incur a one-time rebuild under the canonical representation; it is not reused without an exact bound
request. There is no broad migration, cache scan or mutation of retained production evidence at deployment.

Preserve model, extraction/enrichment policy and schemas, full body coverage, first primary classes, terminal
SKIPs, history duration, preselection policy, per-pair complete accounting, same-run A+B behavior, final full-body
judgment and its cache contract, translation, reports, schedules and publication behavior. Equivalent source
spellings now reuse an existing valid card rather than purchase a new stochastic interpretation of identical
material; distinct factual material still obtains its own card.

Applicable guardrails: AA-03 (canonical identity before reuse), CP-02 (immutable retained material), GC-03
(measured economic authority), MD-10 (fingerprints grant no blocking semantic authority), TOTEM-C01/D01 and
terminal SKIP isolation, plus CR-04 (VPS operational closure). The cache grants neither editorial eligibility
nor a duplicate verdict. Technical failure stays HOLD and alias changes cannot bypass unchanged backoff.

## Verification and operational closure

Thirty-one regression cases cover persisted two-stage reuse for every combination of four www/slash forms,
stable owned fact refs and card hashes, source_url/history projections, unchanged pair-assessment reuse,
source/title/model/schema/policy invalidation, distinct paths/domains/schemes, enrichment-only changes and
technical backoff through alias changes. Against the previous implementation 21 cases fail and ten controls
pass; the correction passes all 31. The combined card/admission/direction/authority suite passes 102 tests.

Before closure, run the complete suite and production-Python tests, check the reviewed tree, replay the 54
retained real sources against existing canonical cards with a provider-denying read-only cache, and verify
that every returned full card matches its retained canonical counterpart. No paid Gemini calls are needed.
Review the actual PR, merge and deploy under the producer lock; compile the affected module, preserve runtime
state hashes, confirm the installed commit and timer, and record deployment evidence separately from the
historical counterfactual estimate. Revert the bounded source change under the same lock if concrete source
binding or cache-reuse regressions appear; never reopen classifications/SKIPs or rewrite retained evidence.

Observe ordinary current-to-history transitions for two-stage cache reuse. Future savings depend on source
volume and actual material changes; a full new source still legitimately costs two isolated operations.
