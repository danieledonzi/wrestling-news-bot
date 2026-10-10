# TOTEM-N01 / TOTEM-D01 implementation — 2026-10-10

Owner authority: the 2026-10-10 clarification ratified in `OWTV_TOTEM_INVARIANTS.md`, followed by explicit
authorization to update the repository and implement those rules autonomously. These rules supersede the earlier
local headline-anchor veto and mandatory second semantic confirmation. Uploaded operational handoff documents
remain historical context; the current authorization includes PR, merge and VPS validation.

## Reconstructed failures and resulting behavior

- The Money in the Bank opening-match feed pair received a primary Gemini DUPLICATE. The local headline-subject
  requirement rejected it and repair returned NO_MATCH. V7 accepts the technically valid exact-pair decision and
  does not request semantic confirmation or replace it to satisfy local wording/identity heuristics.
- Valid canonical bodies use `cleaned_full_text`, not the legacy `text` field. Capture already retains validated
  canonical bodies privately through `source_body.contract_text`; Active now projects those bodies for authorized
  relation endpoints only. Unrelated history bodies are not sent. Each body is bounded at 24,000 characters and
  existing provider byte limits remain enforced. Classification remains before duplicate work.
- Massy could suppress a feed news URL as a recap merely because a report was present. In Active mode this veto
  is removed; the feed URL reaches editorial classification. Full report routing and canonical identity remain
  separate. No news URL is extracted from a report body.
- Soft Board rechecks use the older duplicate batch validator. It now validates required temporal/novelty fields
  and endpoint coverage without rejecting Gemini's MATERIAL_UPDATE because local lexical/date heuristics cannot
  establish its semantics. Both duplicate cache contracts are versioned to exclude old-contract verdicts.
- A technical repair preserves already-valid exact-pair decisions. Missing decisions are not manufactured from
  neighboring duplicate classes. Body recovery remains bounded to an unresolved pair with genuinely new material;
  already-projected bodies do not justify another call.

## Authorities and non-regression boundaries

Gemini owns semantic DUPLICATE / MATERIAL_UPDATE / NO_MATCH decisions. Local code owns source identity, exact
duplicate equality, supplied relation refs/scope, coverage, mandatory fields, types and technical publication
safeguards. Evidence observations are advisory and cannot trigger semantic repair.

Applicable architectural guardrails: MD-01 (duplicate before pacing), MD-02/04/05 (deterministic suspicion admission
and bounded arbitration), MD-03 (local exact equality), MD-06 (successful Publisher history, 12 hours), MD-07
(updates survive), MD-08 (cache only arbitrated doubts), CP-05 (contract fingerprinting), CR-04/05 (production
validation and finite review), plus TOTEM-R01 canonical report identity. Scorer and threshold remain unchanged.

MUST/SHOULD feed news retain their existing SELECT contract and persistent strong-news queue; they do not compete
in the soft pool or wait for a report. Reports remain autonomous. Post-show freshness, report source/due time,
WordPress safeguards, primary editorial value thresholds and model selection remain unchanged. V7 explicitly
accepts V6 primary queue classifications and soft admissions, preserving their age/review count, while requiring
new-contract duplicate clearance. Older primary policies remain subject to the existing migration rules.

## Cost, reliability and limitations

Removing a second semantic confirmation saves that operation on new DUPLICATE verdicts. Advisory evidence cannot
cause heuristic-driven repairs. Supplying retained endpoint bodies increases tokens in affected cache misses;
the aggregate monetary effect must be measured from subsequent provider-ledger usage, not promised from tests.
The first run may incur cache misses because old contracts are no longer eligible. No all-to-all provider
comparison, additional model, history expansion or unrestricted source-body scraping is introduced.

Trusting a technically valid Gemini verdict means local semantic heuristics no longer protect against a wrong
model judgment. This is the owner's explicit authority choice. Missing/malformed answers, absent required fields,
wrong refs/scopes and uncovered relations remain technical failures with bounded recovery and fail-closed publication.

The Henry repetition remains outside the current 12-hour Publisher window (first publication around 03:56,
second around 17:30 Europe/Rome). A 24-hour window is not part of this release. Separate scorer-admission gaps and
the Juice/soft-lifecycle classification investigation also remain outside this release.

## Validation, rollback and closure

Offline tests exercise the name-free opening announcement, final cached decisions in both scopes, real updates,
technical failures, repair preservation, bounded endpoint bodies, no redundant body call, feed/report independence,
and existing live strong-news sequencing. Mocked providers establish application authority and control flow;
they do not measure Gemini's real editorial accuracy.

Run the suite as `python -m pytest -q tests`: root-level collection includes historical operational scripts with
top-level side effects. Local full-suite validation passed before release. Production closure requires the exact
merged commit on the VPS, compilation, the test suite under its Python interpreter, and a clean source diff.
Production state/cache/history/report identities must not be reset. Existing runtime log changes are recorded
at preflight and preserved.

Rollback: revert the implementation and ratified-rule commits through an owner-approved reviewed change, deploy
the resulting `main`, and let contract fingerprinting cause cache misses naturally. Do not restore stale cache
decisions or mutate Publisher history to compensate. Once merged-source and VPS checks pass, review is closed;
subsequent measured editorial incidents justify a new scoped investigation.
