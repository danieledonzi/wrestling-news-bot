# PS-1 — Pre-report news sequencing

Owner clarification, 2026-10-04; preserves the Show News Urgency agreement of
2026-10-01. A report does not replace an independently valuable news article.
This clarification governs this change over historical interpretations of SR-02
that would discard a news article merely because its fact appears in the report.

## Existing scheduling rule

Eligible show/event news with `SHOULD_PUBLISH` or `PUBLISHABLE_SOFT` and `DEFER`
becomes `SELECT` before the corresponding report is published, within the
existing Bob capacity and 30-news ceiling for the Europe/Rome calendar day.
The report consumes no news slot. `show_news_urgency_pre_report` records the
override; original class and semantic recommendation remain intact. `SKIP`,
duplicate authority, MUST handling and softpool decay retain their contracts.
After the report, this promotion ends. Ordinary selection remains possible;
report coverage is not itself a semantic duplicate or a reason to discard news.

The GitHub newsroom execution step explicitly enables Active, matching the VPS
deployment. Active's global default remains disabled for other callers; legacy
fallback authority remains unchanged.

## Runner order

1. Massy discovers candidates; Simone decides which canonical reports are ready.
2. Menzo captures, deduplicates and classifies once, before report publication.
   Ready weekly occurrences supply dated report keys to capture; publication
   evidence is read for that occurrence, without letting an old week's report
   disable a new week's urgency.
3. If a selected, not-yet-reported story matches a ready report, execute the
   existing Andrea/Bob/Alfred/Publisher news pass before the Simone report pass.
   Exact event/report keys take precedence over stable weekly IDs.
4. Otherwise publish reports before news generation. There is no wait for new
   candidates or for pending news to become publishable.
5. Complete the report pass once in the same run, including handled failures or
   empty outputs in the news pass. Report publication does not depend on news
   successfully reaching WordPress. The Shadow observer and audit follow both.

The run reserves existing `MAX_ARTICLES_WITH_REPORT` capacity when reports are
ready, including before their publication. A scoped context keeps capture,
projection and Bob consistent without writing a false report publication state.
When no report is ready, stale prior-run publication artifacts do not reserve
report capacity. Standalone Bob calls retain their historical status reader;
the context resets even if the runner raises unexpectedly.

`news_report_sequence` in the timeline and summary distinguishes
`selected_show_news_first` from `report_before_news_generation`. Canonical news
and report publication events remain separate authorities for actual outcomes.

## Boundaries and verification

One existing classification and one existing news pass; no additional provider
calls, retries, or alternative report sources. Reports may follow the finite
news pass for related selected stories; there is no indefinite hold. TOTEM-R01
source identity, immutable lock, WAIT/RETRY, and D+1 06:30 Europe/Rome processing
boundary remain unchanged. This change does not move that boundary to 07:30.

Offline runner tests cover SHOULD/SOFT promotion and order, normal post-report
selection, no promotion of SKIP/unrelated news, capacity exhaustion, fallback,
handled news failures, stale capacity artifacts, exact occurrence/night matching,
dated publication evidence and context cleanup. Existing urgency, daily ceiling,
Director, duplicate recovery, canonical observers and report identity suites
remain the regression baseline. Production effectiveness requires an actual
eligible pre-report opportunity; a no-opportunity run is not proof of recovery.
