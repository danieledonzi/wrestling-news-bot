# v95.16a Automatic Warning Investigation

## Authority and provenance

This diagnostic reads only the latest Translation Quality Audit JSON, or the exact path supplied with `--audit-json`. The audit remains the inventory and material-provenance authority. Each investigation copies the source, candidate, final-material availability flags, provenance labels, and artifact paths needed to audit the conclusion.

## Status semantics

- `reproduced`: an existing deterministic audit rule directly matched available final published material.
- `not_reproduced`: authoritative material was available and the same rule positively did not match.
- `possible_false_positive`: the audit explicitly supplied that classification as evidence.
- `insufficient_material`: authoritative material or a deterministic evaluator was unavailable.
- `technical`: the code concerns images or other media/technical conditions.

“Reproduced” is not a human editorial verdict and never means “confirmed.” It reports a local rule match only. Missing data never implies editorial correctness.

## Non-blocking daily integration

The daily report runs investigation immediately after the Translation Quality Audit and before Daily Editorial Judgment. Exceptions are logged and converted into an explicit diagnostic warning; email generation continues. A failed run does not expose a stale latest artifact as current. The analyzer does not block, modify, retry, or delete publication.

On execution failure, orchestration writes a current zero-investigation JSON/Markdown pair, replaces the latest JSON with that controlled failure state, and records the exception in `errors`. Attachment discovery pairs Markdown to the `generated_at` value in latest JSON, so an older timestamped Markdown report cannot be presented as the current run.

The production email runner must call `generate_daily_diagnostics_24h()`, or preserve the exact equivalent audit → investigation → Daily Judgment order. Calling only `generate_daily_editorial_judgment_24h()` does not generate either the Translation Quality Audit or warning analysis. Deployment must verify this integration in the external `/opt/owtv/send_daily_report.py` caller; this repository patch intentionally does not modify that VPS-level file.

Daily Judgment and email contain only compact counts, top codes, and up to three priority investigations. Full evidence remains in the artifacts:

- `reports/owtv_translation_warning_analysis_24h_<timestamp>.json`
- `reports/owtv_translation_warning_analysis_24h_<timestamp>.md`
- `state/reports/owtv_translation_warning_analysis_latest.json`

## Known limitations and exclusions

Only warning types with reusable deterministic local rules can be reproduced or positively not reproduced. Comparative warnings require both authoritative source and final material. Evidence excerpts are deliberately short. This patch does not add weekly aggregation (v95.16b), stylistic/AI-likeness scoring, or Guardian work, and it calls no model or external service.
