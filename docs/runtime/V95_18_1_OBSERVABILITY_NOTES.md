# v95.18.1 duplicate-gate observability

## Scope

This patch is diagnostic-only. It does not change duplicate scoring,
thresholds, cache contracts, Gemini admission, editorial decisions,
publication behavior or failure policy.

## Report changes

The operational report now:

- uses the actual requested window in the detailed-ledger heading;
- recognizes dynamic cost and detailed headings such as 12h and 24h;
- distinguishes Gemini 3.5 successful calls from failed attempts;
- exposes the latest Menzo v95.18 postprocess snapshot;
- reports same-run and recent-history theoretical, exact,
  below-threshold and above-threshold counts;
- reports suspicious components, prompt membership, cache activity,
  and planned, executed and avoided duplicate calls;
- exposes material-update, fail-closed and bounded-audit counters;
- uses URL, cluster identity or purpose when a ledger record has no title.

The Menzo counters are labelled as a latest-run snapshot. They are not
presented as aggregate totals for the full report window.
