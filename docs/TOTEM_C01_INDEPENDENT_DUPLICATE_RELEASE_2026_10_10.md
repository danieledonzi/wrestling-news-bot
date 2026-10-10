# Immutable primary classification and independent duplicate operations

Authority: owner-approved autonomous implementation of TOTEM-C01/D01/S01/N02, 2026-10-10.
This release replaces the combined classification/admission request and removes model repair paths from Active
primary classification, semantic pair election, full duplicate judgment and soft-board competition.

## Resulting behavior

1. Every as-yet unclassified eligible canonical feed URL receives its first valid primary class once. Each valid
   individual row is persisted before downstream operations, even when another row is malformed. The permanent
   store has no TTL or policy-version expiry. Its original class, action, policy and timestamps remain audit authority.
2. Terminal SKIP and bookmaker exclusions precede semantic work. Eligible facts enter the separate admission
   contract; classifier class/story_core/rank never enter its payload. Gemini elects plausible shared central facts,
   without a lexical pair matrix. Complete empty suspicion lists are valid and exact unchanged clearances are reused.
3. Only elected pairs reach the independent duplicate schema/policy. Supplied endpoint ref and a legal verdict
   suffice. Optional quotations/explanations are not semantic gates. Valid individual judgments persist even when
   another pair is invalid. Published duplicates win; otherwise content/media richness prevails, then earliest arrival.
4. Duplicate losers are terminal before projection. A failed later write cannot revoke accepted primary classes or
   duplicate SKIP. A valid independent soft SKIP likewise survives a malformed sibling and remains separate from its
   original PUBLISHABLE_SOFT class. Larger pools use bounded endpoint/relation batches, deciding survivors once across
   the operation's duplicate components; prior valid verdicts survive a later batch failure.
5. Each operation makes at most one provider attempt, with no repair, body-repair or semantic confirmation call.
   Unchanged failures have explicit 60/120/240-minute recovery backoff (240-minute cap). Changed factual input or
   contract permits a new operation. Successful admission clearance is reused only for exact eligible context and
   bindings. Clock/age changes alone do not bypass a failed soft competition's backoff. Recovery-cache corruption
   holds technically; a cache write failure cannot revoke an already accepted permanent class.
6. Technical telemetry retains stage, validation families, bounded refs/fields, response shape, fingerprint, request
   ID and retry_after. It does not store raw model responses in recovery records. Soft admission and gate errors
   propagate their technical reason rather than collapsing everything into ValueError.

## State migration and boundaries

The first access creates the permanent class store from the earliest retained valid master-log observations,
then valid legacy pool/queue decisions where no earlier observation exists. Unavailable older observations cannot
be reconstructed; the migration does not invent historical classifications. A corrupt existing permanent store
blocks new model work instead of silently replacing its history. Terminal memory is never cleared.

Historical strong-queue promotions contradicting an original PUBLISHABLE_SOFT decision are removed from the
strong queue and preserved under their original soft eligibility; valid original strong classes remain strong.
Published and terminal URLs are excluded before this reconciliation. Midnight/competitive terminal rules still apply.

Successful Publisher history remains 12h; the Henry/24h question is unchanged. Feed news and reports remain
independent: no report-derived news URLs and no report substitution for eligible live MUST/SHOULD feed news.
Legacy deterministic exact-identity safeguards remain unchanged before semantic work. V8 semantic verdicts do
not supply V9 clearance because the dedicated judge schema/policy/material contract changed; no state reset occurs.

## Verification and release closure

Run the complete offline suite with `python -m pytest -q tests`; repository-root collection contains historical
operational scripts. Regression coverage includes all-class permanence across rediscovery/policy/time changes,
partial classification preservation, malformed ref/coverage failures, no repair calls, soft schema independence,
terminal SKIP before projection, separate primary audit, unchanged admission reuse, technical recovery/backoff,
large pool batches and informational arrival ties. Mocked providers verify mechanics, not actual Gemini accuracy
or realized savings. No manual newsroom run or experimental model replay is needed for this release.

Release closure requires the actual PR diff/check/review state, an isolated full-suite run on production Python 3.9,
verified installed merged source, compilation/import/provider-schema checks and timer/service/state verification.
Observe subsequent scheduled runs for real admission validity, publications and authoritative ledger costs.
