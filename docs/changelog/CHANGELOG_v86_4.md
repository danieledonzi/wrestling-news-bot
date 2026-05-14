# CHANGELOG v86.4 - Report-first candidate gates

## Added

- `v86_4_report_first_candidate_gates` version name.
- Report-first `build_candidates()` implementation.
- Report-like detection before URL/title/semantic gates.
- Explicit diagnostics when a report is allowed through despite old history keys.
- Broader skipped-history rescue for post-show outcome URLs.

## Changed

- Complete reports are no longer blocked by generic `title already seen`, `semantic_id already in history`, `URL already in history`, or `story_signature already seen` checks before strict WordPress report confirmation.
- `skipped_history` low-score entries no longer hide post-show outcomes when URL/title suggests a concrete debut, return, attack, win, title change or similar event.
- v86.2 morning hold remains active after the canonical candidate queue is built.

## Fixed

- NXT report recovery being stopped by `titolo già visto` after v86.3 had already removed the URL-history blocker.
- Post-show outcome rescue not firing because normalized skip reasons used spaces instead of underscores.

## Preserved

- v86.3 strict WordPress report verification.
- v86.2 report hold until 06:30 Europe/Rome.
- v86 hard embed engine and YouTube inline extraction.
- v85.4 skipped-history performance behavior for normal news.
