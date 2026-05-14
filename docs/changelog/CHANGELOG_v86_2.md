# CHANGELOG v86.2 - Morning report hold

## Added

- Morning hold for complete results reports.
- Report candidates detected before 06:30 Europe/Rome are saved to pending and not processed immediately.
- Strict WordPress report confirmation for `report:*` event keys.
- A WordPress match only suppresses a report when the matching post looks like a complete report: show marker, report/results marker, coherent date, and Editoriali category or exact event key.

## Changed

- Complete reports no longer use the older rolling delay as the main gate. The hard gate is now the morning threshold: 06:30 Europe/Rome.
- After 06:30, reports can be processed immediately if complete and not strictly confirmed on WordPress.
- Generic event-key token matches are no longer enough to block a report.

## Preserved

- v86.1 scoring/signature/validation stabilizers.
- v86 embed engine.
- v85.4 skipped history behavior.
- Draft-first publishing and review bundle generation.
