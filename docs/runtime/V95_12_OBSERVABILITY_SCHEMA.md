# V95.12 Observability Snapshot Schema

V95.12a is measurement-only. It preserves the V95.11 duplicate architecture described by `V95_11_DUPLICATE_ARCHITECTURE_HANDOFF.md` when that handoff is present in deployment docs, and does not alter Menzo, Bob, Alfred, Publisher, Simone, WordPress, prompts, thresholds, scheduling, or runtime state formats.

## Authoritative data sources

The reusable snapshot module reads master-log JSONL artifacts defensively. `state/newsroom/master_log.jsonl` is the primary complete source; `artifacts/newsroom/master_log_tail.jsonl` is used only as a fallback when the full master log is missing or unreadable. Reads are fail-soft and produce `schema_warnings` for malformed or missing artifacts.

## Boundary semantics

Windows are explicit inclusive UTC intervals: `[window_start, window_end]`. Production master rows remain structured run records. Nested Publisher, Simone, Menzo, Bob, and Alfred children inherit timestamps in this order: child timestamp, parent `recorded_at`, parent `run.ended_at`, parent `run.started_at`. Records without a parseable effective timestamp are not promoted into in-window publication counts.

## Publication authority

News publication authority is strictly `publisher.published[]` plus `publisher.results[]` where `status == published`. Simone report authority is strictly `simone.published_reports[]` where `status == published` (or explicitly adapted known report registries if added later). Hard skips, Bob, Alfred, Menzo, story footprints/fingerprints, duplicate memory, Gemini ledgers, skipped histories, audits, arbitrary JSON files, and old WordPress links are not publication authority.

Identity is stable and conservative: source URL first, then WordPress/published URL, then normalized title fallback.

## Unique counts versus events

The principal funnel is unique-flow based over real `master_log_v93_19` keys: `menzo.selected`, `menzo.pending`, `menzo.skipped_sample`, `bob.articles`, `alfred.reviews`, `publisher.published`, `publisher.results`, and `simone.published_reports`. Repeated run appearances of the same source URL are deduplicated for unique article counts. Raw repeated events remain available only in `funnel.event_counts` diagnostics. Stages not reconstructable from the current master format, including item-level Massy and Andrea outcomes, are nullable and accompanied by schema warnings.

## Menzo V95.11 active metrics

The first-class active duplicate arbitration counters are:

- `menzo_same_run_batch_calls`
- `menzo_same_run_batch_repairs`
- `menzo_same_run_micro_fallback_calls`
- `menzo_same_run_duplicate_groups`
- `menzo_same_run_duplicates_blocked`
- `menzo_recent_history_batch_calls`
- `menzo_recent_history_batch_repairs`
- `menzo_recent_history_micro_fallback_calls`
- `menzo_recent_history_duplicates_blocked`
- `menzo_recent_history_material_updates`
- `menzo_duplicate_arbitration_fail_closed`
- `gemini_calls_used_for_duplicate_arbitration`

Counters are aggregated only from the explicit per-run `menzo.duplicate_arbitration` compact payload. The snapshot exposes duplicate-counter coverage metadata: `available`, `covered_runs`, `total_runs`, and `counters`. Missing historical coverage is not rendered as authoritative zero. Legacy footprint/fingerprint signals remain only under `diagnostics.legacy_duplicate_signals` and are not the headline semantic duplicate result.

## Alfred final outcomes

`alfred.events` counts warning entries, blocker entries, and reviews whose compact final status is `needs_revision`. `alfred.unique` sorts `alfred.reviews[]` chronologically by effective timestamp and counts final unique outcomes by stable article identity. A temporary blocker or needs-revision followed by approval/publication is counted as revised-then-approved/published, not as a final blocker.

## Expected runtime paths and scheduler diagnostics

`reports/` is expected runtime output. The snapshot separates `expected_runtime_untracked_paths` from `actual_source_modifications`. Systemd scheduling is reported separately from cron; absence of cron is not an anomaly when systemd is active.

## Limitations and warnings

If a ratio or final outcome cannot be supported by available source chronology, the snapshot emits a schema warning and returns `null` instead of inventing zeroes. Malformed JSON/JSONL is skipped with warnings.

## Top-level artifact fields

- `schema_version`
- `generated_at`
- `window_start`
- `window_end`
- `artifact_sources`
- `schema_warnings`
- `publication`
- `funnel`
- `duplicate_arbitration`
- `alfred`
- `gemini_summary_if_available`
- `diagnostics`

## Additive master-log observability fields

`agents/master_log_v93_19.py` compacts Alfred reviews using `status` or `decision`, preserves blocker diagnostics from explicit blockers or blocker-severity issues, and stores only the v95.11 Menzo duplicate-arbitration counter subset under `menzo.duplicate_arbitration`. These fields are additive observability data and do not alter newsroom decisions.

## Handoff note

`V95_11_DUPLICATE_ARCHITECTURE_HANDOFF.md` is absent from this checkout, so this repository patch does not recreate or quote it.

## V95.12 resilience clarifications

Daily Editorial Judgment treats `authority_available=true` snapshots as primary authority even when authoritative values are zero. Legacy operational Markdown and state files may produce mismatch warnings, but they must not override authoritative publication counts, run counts, Alfred counts, duplicate coverage, or unique funnel values.

Publisher publication event counts treat `publisher.published[]` and `publisher.results[]` as storage views of the same run outcome. Per run, the snapshot prefers `publisher.published[]` when present; otherwise it uses `publisher.results[]` filtered to `status=published`.

Alfred chronology is strict per stable article identity. `approved` means the latest resolved review outcome is approved. `revised_then_approved` requires a needs-revision or blocker review before a later approved review. `revised_then_published` requires a needs-revision or blocker review before a later authoritative publication. `final_blocked` applies when the latest unresolved review outcome is needs-revision/blocker and there is no later approved review or later publication. Earlier approvals do not suppress later unresolved blockers, and earlier publications do not make later revisions count as revised-then-published.

Master-log source health is explicit under diagnostics: `master_log_source`, `master_log_partial`, `master_log_valid_rows`, `master_log_malformed_lines`, and `tail_fallback_used`. A readable primary master log with valid production rows remains authoritative even if some lines are malformed. Tail fallback is used only when the primary cannot be read or has no usable production-shaped rows. A readable empty primary master log is authoritative empty.

## Translation audit material availability

Publication authority is not linguistic material. A Publisher/Simone authoritative record can establish that an article/report was published in the window, but title/source URL/WP URL/status metadata alone is not source text and is not final published text.

Translation Quality Audit keeps metadata alias matching separate from content matching. Source URL, WordPress URL, and normalized-title aliases may merge artifacts into one canonical audit row, but source material is available only when substantive original/source content is found, and published material is available only when substantive final/published text or matched HTML is found.

Comparative language analysis requires both original/source material and final published material. Missing source or published material is reported explicitly in coverage fields instead of being silently treated as a successful comparison match.

## Direct CLI execution and provenance

The repository-side scripts `scripts/translation_quality_audit.py`, `scripts/daily_editorial_judgment.py`, and `scripts/observability_snapshot.py` support direct execution from the repository root or production paths by adding the repository root to `sys.path` before importing repository modules.

Publication authority is distinct from final linguistic material. Generic `body_html` from Bob packages, Alfred approved-article objects, review packages, or other intermediate artifacts is translated-candidate material only; it is not final published material. Final published material requires explicit final provenance such as matched `published_html_review` HTML, `published_text`, `published_html`, `final_text`, `final_html`, or another documented final-output source.

Source material may come from text fields such as `original_text`, `source_text`, or `extracted_text`, or from explicit source HTML fields such as `source_html`, `original_html`, or `raw_source_html` after visible-text extraction. Generic translated `body_html` is never source HTML.

Translation-audit comparative pairs require source material plus final published material. Source plus translated candidate material remains non-comparative until final published material is available. When publication authority is unavailable, fallback legacy rows are counted as `legacy_artifacts_inspected` and are not labeled as authoritative publications.

## Translation audit published-html-review provenance

The Translation Quality Audit treats publication authority and linguistic material as separate concepts. The production `published_html_review/` archive adapter supports the historical nested v80.10 shape, flat v81 triplets, and current modular v93 snapshots. The nested shape is:

```text
published_html_review/
  run_<timestamp>_<sha>/
    summary.json
    001_<article_slug>/
      metadata.json
      original.html
      final.html
```

Within a nested article directory, `metadata.json` supplies aliases (`source_url`, `wp_link`/published URL, source title, translated/final title) used to merge source URL, WordPress URL, and normalized-title matches into one canonical `ArticleAudit` row. It is metadata only and does not prove source or final linguistic material. `original.html` is source/original linguistic material. `final.html` is final-published linguistic material.

The flat v81 form uses `<base>_metadata.json`, `<base>_original.html`, and `<base>_final.html`; when the metadata declares `original_html_file` or `final_html_file`, those filenames are authoritative over suffix assumptions. The current modular v93 form maps `v93-news-<slug>.html` / `v93-news_<slug>.html` to translated-candidate material and `v93-publisher-<slug>.html` / `v93-publisher_<slug>.html` to verified final Publisher material after stripping the technical prefix for alias matching.

The merge is order-independent: a longer source/original HTML file never replaces `published_text`, and verified final HTML never replaces `original_text`. Generic `body_html` from Bob, Alfred, review packages, or intermediate artifacts remains translated-candidate material only; it is not final-published evidence. Known archive filenames are consumed by the explicit adapter and do not fall through to generic HTML handling.

A comparative translation-quality pair requires source/original material plus final-published material. Metadata-only matches and translated-candidate-only matches keep explicit missing-material diagnostics.

## Translation audit detail limit

`--limit` on `scripts/translation_quality_audit.py` limits the detailed rows rendered/returned for inspection only. Discovery, publication authority, and material-availability coverage are computed across the full authoritative publication population in the requested window.

Coverage fields therefore distinguish `authoritative_total` / `audit_population_total` from `detailed_rows_returned` / `detail_limit`. When publication authority is unavailable, fallback legacy rows are labeled as legacy artifacts and are not called authoritative publications.

## Translation audit material provenance ranking

Each selected material field records explicit provenance and an authority rank: `source_material_provenance` / `source_material_rank`, `translated_candidate_provenance` / `translated_candidate_rank`, and `final_published_material_provenance` / `final_published_material_rank`. Higher authority rank wins even when the replacement text is shorter; length is used only as a tie-breaker within the same rank.

Final-published material ranks verified modular Publisher HTML above nested/flat final archives, and both above explicit lower-authority final fields. Source material ranks nested/flat original archives above explicit source fields and review-package source HTML. Translated-candidate material ranks v93 news HTML above Bob/Alfred body HTML and review-package candidate HTML.

Unknown HTML under `published_html_review/` is diagnostic-only (`unclassified_html_artifacts`) unless it matches a documented adapter format. Review-package HTML is role-classified: `original.html`, `*_original.html`, `source.html`, and `*_source.html` are source material; `translated.html`, `*_translated.html`, `candidate.html`, `*_candidate.html`, and `body.html` are translated-candidate material; unknown review-package HTML is diagnostic-only. Review-package files never establish final-published material.

Specialized archive fallback scanning is bounded to the requested audit window using metadata timestamps, parseable run/file timestamps, then filesystem mtimes. When publication authority is available, exact source/WP URL matches may attach to in-window authoritative publications; title-only or slug-only matching remains time-bounded so stale archive content cannot attach to current publications.
