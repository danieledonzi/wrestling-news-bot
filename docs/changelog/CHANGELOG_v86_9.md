# Changelog v86.9

## Added
- Fallback report source recovery from the current candidate URL.
- Diagnostics for report source selection and completeness score.
- True-results priority sorting before normal news candidates.
- Internal `report_ready` guard to avoid re-entering the report gate.
- Post-AI cap for commentary/opinion articles masked as post-show news.

## Changed
- True-results reports no longer depend exclusively on aggregate `sources[]` items.
- Opinion/commentary pieces such as `Bully Ray reveals why...` cannot climb to score 100 without a concrete new fact.

## Preserved
- v86.8 Gemini-offline pending preservation.
- v86.7 pending truth fix.
- v86.6 recursion fix and media guard.
- v86.5 strict true-results report gate.

## Expected behavior
If the NXT report is not confirmed on WordPress, the bot should try the current feed candidate as the report source instead of logging `Nessuna fonte valida per report` and stopping.
