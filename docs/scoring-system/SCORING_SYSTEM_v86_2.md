# SCORING_SYSTEM v86.2

v86.2 does not change the scoring philosophy from v86.1. It changes when complete report candidates are allowed to enter the publishing pipeline.

## Report timing gate

A complete report can score 100 and still be held before 06:30 Europe/Rome. The hold is not a score penalty and not an editorial skip. It is a scheduling gate.

```text
RESULTS_REPORT before 06:30 -> pending
RESULTS_REPORT after 06:30 -> normal report pipeline
```

## Non-report post-show news

Post-show news remains governed by the existing v68/v70/v86.1 rules and can be published before 06:30 if it is not a complete report.

## Duplicate policy

For `report:*` keys, WordPress confirmation is strict. Broad token overlap with a same-show news post is not sufficient to suppress a report.
