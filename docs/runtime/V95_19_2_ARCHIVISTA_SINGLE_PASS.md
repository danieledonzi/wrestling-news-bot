# v95.19.2 — Archivista single-pass audit

## Problem

`newsroom_runner.py` executed Archivista twice in every newsroom run: first through `safe_agent()` without the current in-memory context, then directly with the complete context. Each execution appended a ledger row, doubling `runs_48h` and `published_48h` and producing repeated raw audit lines in the operational report.

## Correction

- `safe_agent()` now accepts keyword arguments for keyword-only agents.
- Archivista is executed once, with the complete current-run context.
- Archivista ledger rows carry `NEWSROOM_RUN_ID` and replace an existing row for the same run ID, making the ledger idempotent against accidental re-entry.
- `scripts/repair_archivista_ledger_v95_19_2.py` safely removes only consecutive legacy rows with identical payloads and timestamps no more than five seconds apart. It defaults to dry-run and creates a timestamped backup when `--apply` is used.

## Non-regression boundary

No editorial selection, translation, review, publication, WordPress, Simone, schedule, retry, or Gemini behavior changes.
