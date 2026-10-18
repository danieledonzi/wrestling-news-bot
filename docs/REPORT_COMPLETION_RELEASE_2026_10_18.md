# Source-independent report completion — 2026-10-18

Owner decision: successful publication fulfils an event/show, specific night and date regardless of source.
Base main/production: `fbbbe82fd1523895c4a1ed68e229be90023465a8` (PR164).

## Scope and implementation

TOTEM-R01 now explicitly closes a successfully published report obligation independently of the source and
of future source-policy changes. Simone reads the report publisher's durable history alongside existing
status, publication registry and manual-run evidence. Completion is checked before structured special-event
source election, weekly election, special-event election, reservation and pending replay. The publisher
also checks completion before scraping/preflight and immediately before processing an item. Duplicate
same-key inputs in one batch are coalesced before downstream work. A valid first success is not overwritten.

New successful history entries retain the original source headline and event/night/date metadata, plus a
versioned `report_completion` receipt bound to the report key and date. A receipt with successful WordPress
evidence does not depend on parsing a particular source's URL or accepting that source for new work.
Older records need successful publication evidence, exact obligation binding and deterministic Results,
event/show and explicit date evidence from their original headline/slug. Generated Italian titles and
publication timestamps cannot turn a stale preview, ratings story, wrong event/date or key-only association
into fulfilled report evidence. Existing exact-canonical-URL and manual reconciliation paths remain.

Source preference/deadlines for unfulfilled reports, 06:30 timing, canonical reservation locks, report
extraction/translation/rendering, preshow behavior, Menzo, news/report separation, classification, duplicate
admission/judgment, model routing and scheduling are unchanged. No new model calls or WordPress mutations
are needed for the reform's validation. No historical publication is recreated or automatically deleted.

## Verification

- Isolated VPS Python 3.9: 102 focused report/source/identity tests pass.
- Fresh isolated full checkout: **1,882 pass**, one established pre-existing oversized-body recovery test
  deselected; 18 new regressions cover source independence, future receipts, feed disappearance, no election
  or reservation after completion, pending replay, different nights/dates, negative legacy identities,
  publisher avoidance of downstream work, same-run duplicates and preservation of first success.
- Controlled source-switch replay uses the actual WrestleDream Ringside/Wrestleview URLs and event metadata,
  with the first successful WordPress post ID 13724. It is a bounded counterfactual, not an exact archived
  historical cohort. Baseline reopens one ready report; the candidate closes the obligation before election.
  The replay runs only isolated state paths, makes no provider request or WordPress write, and checks that
  production report/editorial state remains byte-identical during the control.

Deployment must run under the producer lock, verify reviewed file hashes and preserve newsroom state.
Installed validation checks the real current WrestleDream record closes before source selection. Report
publication is not triggered for validation, and both historical publication records are left untouched.
