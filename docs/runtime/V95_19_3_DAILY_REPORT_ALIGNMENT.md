# OpenWrestlingTV v95.19.3 — Daily report canonical alignment

## Scope

This release is measurement/reporting-only. It does not change selection,
scoring, translation, review, publication, WordPress, scheduling, or model use.

## Authoritative daily-email summary

The daily email body now uses the structured Daily Editorial Judgment JSON as
its authoritative editorial summary.

It presents:

- unique Menzo actionable candidates, downstream handoffs, final publications,
  and the linked handoff/publication ratio;
- classified warning investigation outcomes (`reproduced`,
  `insufficient_material`, `possible_false_positive`, `technical`);
- Alfred reviewed articles, articles with warnings, and final unique blockers;
- Andrea event coverage, pass/exception/block counts, and exception-reason
  occurrences.

The legacy operational/editorial reports remain attached for diagnostics, but
legacy per-run Menzo totals and raw Alfred warning totals are no longer promoted
as authoritative values in the email body.

## Andrea observability

Andrea now persists aggregate exception reasons in its handoff. The structured
master log records the handoff and the observability snapshot aggregates it over
the requested window.

Immediately after deployment, Andrea coverage is expected to be partial because
older runs in the 24-hour window do not contain the new fields. Coverage becomes
complete naturally after one full reporting window; missing historical fields
are never interpreted as zero.

## External VPS runner

`/opt/owtv/send_daily_report.py` lives outside the repository. Apply its narrow,
idempotent migration with:

```bash
python3 scripts/patch_runtime_daily_report_v95_19_3.py --check
python3 scripts/patch_runtime_daily_report_v95_19_3.py --apply
```

The apply mode creates a timestamped backup before writing. Do not execute the
external runner manually during verification because it sends email.
