# SCORING_SYSTEM v86.4

v86.4 does not change the scoring philosophy. It changes which gates are allowed to act before scoring.

## Report scoring

Reports/results remain protected:

- classified as `RESULTS_REPORT`;
- category Editoriali;
- bypass below-threshold score if they are valid complete reports;
- subject to one-report-only dedupe through strict WordPress report confirmation.

## Gate order impact

For report-like candidates, generic pre-score duplicate gates do not suppress the item. The item reaches report scoring unless WordPress strictly confirms the complete report already exists.

## Post-show outcome rescue

If an item was previously stored in `skipped_history` as low-score but is now recognized as a concrete post-show outcome, it is rescored.

## Unchanged

- Opinion caps remain.
- Expired previews remain skippable.
- Weak normal news remains skippable.
- Embeds do not affect score.
