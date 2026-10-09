# ED-6: editorial category admission

Owner-approved reform based on the 8–9 October 2026 retrospective audit. Runtime base: main
`4205cd4b08531e26e49fdcabea68915e795e7821`.

## Binding policy

Active uses `owtv_editorial_director_policy_v6_active` and
`docs/editorial-rules/OWTV_GEMINI_EDITORIAL_DIRECTOR_POLICY_V6_ACTIVE.md` on every fresh primary classification.
The existing schema and class/action contract remain unchanged:

| Editorial category | Wire class | Action | Admission |
|---|---|---|---|
| MUST | MUST_PUBLISH | SELECT | Essential consequential news |
| SHOULD | SHOULD_PUBLISH | SELECT | Concrete relevant useful coverage |
| Publishable soft | PUBLISHABLE_SOFT | DEFER | All four qualitative admission conditions |
| Weak soft | SKIP | SKIP | Terminal before semantic duplicate work |

The four soft conditions are professional relevance, informative substance, audience interest and standalone
value. Gemini evaluates them semantically and explains its central fact/class in the existing story_core field.
Python does not classify by names, brands or keywords, and there is no extra model call, local classifier or quota.
MUST is reserved for essential consequences. Routine procedural legal updates, ordinary event dates and limited
development-program departures are not automatically MUST. Concrete live results and events of followed shows
remain at least SHOULD and the full report remains autonomous.

## State transition

Policy-version mismatch already prevents reuse of old strong-queue classes. Existing queued news receive one fresh
primary classification under V6 before publication; unchanged subsequent current-policy strong entries still reuse
their class and obtain current duplicate clearance.

The separate soft container never re-enters Active solely because it is waiting. Old-policy pool rows retain their
identity, original day and meaningful-review count in WAIT_PRIMARY_POLICY. They cannot enter soft review or publish
until feed rediscovery obtains a fresh current-policy class and duplicate clearance. A current primary SKIP removes
the row; a current strong decision exits the soft pool; a current PUBLISHABLE_SOFT decision resumes its existing
lifecycle. Primary/provider failure does not authorize publication. Midnight tombstones remain binding.

## Verification and scope

Offline tests cover mixed prefilter admission, all-SKIP without semantic work, old-policy strong reclassification,
soft-policy hold/resumption/rejection, hold persistence beside reviewed current rows, failed sibling duplicate work,
and midnight expiry. Provider examples are calibration cases, not a claim that mocked tests prove Gemini's semantic
accuracy. Live classification must be measured after release.

VPS verification on the release branch: full `pytest -q tests` passed 1,633 tests; focused editorial/live/report
regression suites passed 201 tests after final prompt calibration. Do not run bare pytest: legacy scripts outside
`tests` can execute configuration changes during collection.

A non-binding Gemini 3.1 Flash Lite probe used 16 archived title/summary inputs. The final probe rejected all six
weak cases, including Nemeth dating, Roberts/Reigns insults, routine Kaiser legal administration, Hardy's pitch and
Owens' interview taunt. It preserved three MUST, four SHOULD and the HD-production PUBLISHABLE_SOFT example.
Two manually forecast soft examples (Bailey tribute and Knight/Triple H) became SKIP from their limited RSS excerpts;
soft-borderline outcomes varied across calibration probes. These probes neither published articles nor changed
production decision state, and they do not establish a production accuracy or savings rate.

The historical audit suggested 25 of 83 candidate URLs would be SKIP, removing 61.5% of repeated relation lookups
and 45.3% of cache misses on the frozen 49-run history. These are manual retrospective estimates, not expected
production percentages or guaranteed net savings.

No change to duplicate suspicion scoring, threshold, historical window, binding/confirmation semantics, model
routing, report pipeline, publishing capacities or soft-review timing. Baszler/Mickie pair-admission and Henry's
12-hour-history gap belong to a separate duplicate reform. The shared policy fingerprint can initially cause a cold
duplicate cache. Compare steady-state metrics separately from migration costs.
