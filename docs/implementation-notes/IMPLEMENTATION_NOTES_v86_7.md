# Implementation Notes v86.7

## Main change

The `run_bot()` runtime gate has been rewritten so the v72.1 pending gate no longer controls true results reports.

Old behavior:

```text
pending item exists
↓
queue item matches history/title/semantic
↓
[SKIP v72.1] Gia pubblicata da pending in questa run
↓
pending can be removed without publication
```

New behavior:

```text
pending item exists
↓
true results report is not considered published
↓
queue candidate remains processable
↓
legacy gates are ignored unless WordPress strictly confirms a full report
```

## New helper functions

- `v867_is_true_results_item(item)`
- `v867_report_key(item)`
- `v867_candidate_key(item)`
- `v867_wp_confirms_true_results_item(item, wp_available=True)`
- `v867_legacy_history_match_for_item(item, history, seen_story_signatures_v71)`

## Pending removal policy

A pending true-results report is removed only when:

1. publish succeeds; or
2. WordPress strictly confirms a complete matching report.

If the item is skipped ambiguously, fails validation, or is blocked by legacy state, it remains pending.

## Gate rewrite

The old v72.1 behavior is not called as an authoritative runtime gate in v86.7. Its underlying helpers may still be used elsewhere, but this version establishes a new truth-based runtime order.

## Syntax

`bot_v86_7.py` was checked with:

```bash
python -m py_compile bot_v86_7.py
```
