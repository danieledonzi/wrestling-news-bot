# Timed Wrestleview fallback and important material updates

Authority: owner approval, 2026-10-16 08:53 Europe/Rome. Baseline: main/VPS
`a828e6182495924d6977e07005a089b01a2ea8be` (PR160).

## Report election

All weekly, PLE/PPV and configured special-event report identities keep Ringside
as primary from 06:30. From 08:30 Europe/Rome on D+1, a full Wrestleview Results
report may be elected if no timely Ringside source is locked or available.
A valid publication timestamp at/before 08:30 proves timely Ringside availability
when the scheduled scan happens a few minutes later. Missing timestamps cannot
prove it. At the exact 08:30 boundary a present Ringside source retains priority.
The decision is made by scheduled runs, not a new timer at exactly 08:30.

The Wrestleview feed is report-only: ordinary URLs never enter Menzo. Discovery
can precede the fallback deadline but cannot reserve Wrestleview early. Host,
promotion/show identity and explicit date/results identity remain mandatory.
Wrestleview quick results, taping spoilers and previews are ineligible. Two-digit
years in explicit results dates are recognized; conflicting fallback dates fail
closed rather than relying on the RSS timestamp.

Once elected, the exact source lock wins across scans, publication holds and
successful publication. A later Ringside source cannot replace it or produce a
second report. Existing validated WrestlingInc locks remain compatible; no new
WrestlingInc source is admitted. First classes, terminal news SKIPs, publication
history and unrelated queues are not migrated or deleted.

Wrestleview uses the existing complete ordered report extractor/translator.
Narrow source service text, author credits and contact/promotion footers are
removed without removing wrestlers' careers or actual show greetings. The final
report retains one linked Wrestleview attribution. Source HTML is data, not code.
The same existing media, full-translation and weekly/preshow contracts apply.

## Duplicate judgment

Policy v4 places materiality ahead of same-run A+B coverage. An important
independent development is required; historical match dates, older title matches,
ancillary biography or other supporting context do not alone create a follow-up.
The Gowen/house-show examples are negative examples, not hardcoded name/URL rules.
The confirmed U.S. Crown Jewel contingency venue illustrates a positive update.
Other independent substantial developments remain eligible.

Only the provider instructions change. There is no second classification, local
semantic veto, repair, added model call, pair-admission change or model change.
Gemini retains final semantic authority and same-run A+B coverage remains explicit.
The existing policy hash naturally separates pair-cache/recovery contracts;
no state is cleared and permanent SKIPs remain permanent.

## Evidence and validation limits

Read-only observation before implementation: 17 post-PR160 runs validated, eight
news published, no observed first-class changes or SKIP resurrection. Both Gowen
and Reigns pairs were admitted, but Gemini called supporting details material
updates. This is a policy interpretation correction, not a ref-binding repair.

The October 15 Impact Wrestleview feed item was published at 04:18:24 UTC (06:18
Rome). Extraction found the entire main-event outcome and closing segment, plus
a YouTube embed. MITB/Collision sample extraction also worked; site author/service
content required the narrow cleanup added here. This is sample evidence, not a
guarantee of future source completeness or coverage of every show.

Run tests only under `tests`, in an isolated checkout on production Python. Test
telemetry must never enter the live Gemini ledger. Verify the 08:30 boundary in
CET/CEST, source order, both weekly/special locks including after publication,
negative source identities, ordered content/media and ordinary-news isolation.
The pre-existing oversize full-body retry test is a known baseline failure.
Mocks can validate contracts but cannot prove future Gemini semantic accuracy.
Observe the next real run/verdicts before claiming a measured editorial gain.

Validation completed on the installed production Python 3.9.25 in an isolated
checkout: initial full comparison had 1,780 passes and the identical known
baseline failure; final suite after the stale-pending regression had 1,781 passes
with that single baseline test explicitly deselected. Initial targeted contracts
had 149 passes. The live Wrestleview feed yielded five report candidates and zero
ordinary news, and isolated Simone elected exactly the current Impact report.
Clean extraction retained 60 blocks, the video and the closing segment without
source courtesy/byline text. No provider call or WordPress mutation was used for
this verification.
