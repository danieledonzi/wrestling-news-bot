# OWTV canonical metrics catalog — v95.22 A1

## 1. General contract

This measurement-only contract inventories the semantics that already exist; it does not change newsroom decisions, prompts, routing, scoring, thresholds, retries, publishing, scheduling, state, retention, or the v95.21.1 pair matrix. The normative machine-readable representation is `config/metrics_catalog_v1.json` (`owtv_metrics_catalog_v1`, policy `v95.22_a1`). The frozen v95.19 names and meanings remain intact. A dotted name identifies a semantic metric, not every numeric runtime field.

Runtime data, events, attempts, final results, diagnostic aggregates, canonical metrics, and legacy aliases are distinct classes. `active` means the current architecture supports the stated formula and authority. `diagnostic_only` is observable but unsuitable as an authoritative editorial-window outcome. `planned` is intentionally not synthesized.

## 2. Zero and null rules

- **Zero** is valid only when the authoritative source was available for the declared window and contained no qualifying entity.
- **Null / missing** means that the authority is absent, unreadable, outside its coverage contract, lacks identity/chronology, or cannot express the requested semantic. It must never be coerced to zero.
- Empty populations do not automatically make ratios zero: a missing denominator or unsupported linkage is null.
- Generic `errors`, capped samples, and latest-run counters cannot prove a typed terminal result or a complete window.

## 3. Authoritative sources

Each JSON row has exactly one `source_primary`. `source_secondary` entries are explicitly non-competing reconciliation, diagnostic, or legacy inputs. The master log is primary for structured run, handoff, review, and publication records; the Gemini ledger is primary for API attempts; Publisher records are news-publication authority; Simone published-report records are report-publication authority; and the v95.21.1 pair-coverage artifact is authority only for its producing latest run. Markdown reports and textual logs are consumers or diagnostics, never alternative authorities.

## 4. Active canonical metrics

| Canonical name | Meaning | Primary authority | Formula / unit |
|---|---|---|---|
| `runtime.runs_started` | Production-shaped master run records whose start timestamp is in the window. | `state/newsroom/master_log.jsonl: run.started_at` | count production-shaped run records with an in-window parseable run.started_at; count |
| `runtime.runs_completed` | Production-shaped master run records with an end timestamp in the window. | `state/newsroom/master_log.jsonl: run.ended_at` | count production-shaped run records with an in-window parseable run.ended_at; count |
| `runtime.runs_exit_zero` | Completed runs whose recorded runtime exit code equals zero. | `state/newsroom/master_log.jsonl: run.runtime_exit_code` | count completed in-window run records where runtime_exit_code == 0; count |
| `runtime.run_failures` | Completed runs whose recorded runtime exit code is non-zero. | `state/newsroom/master_log.jsonl: run.runtime_exit_code` | count completed in-window run records where runtime_exit_code is an integer other than 0; count |
| `menzo.unique_actionable_candidates` | Unique content identities selected or pending. | `state/newsroom/master_log.jsonl: menzo.actionable_identity_keys` | cardinality of the union of actionable identity keys across in-window runs; count |
| `menzo.unique_downstream_handoffs` | Unique selected identities handed downstream. | `state/newsroom/master_log.jsonl: menzo.selected` | cardinality of unique stable identities in selected rows across in-window runs; count |
| `menzo.unique_final_publications` | Unique final news publications. | `state/newsroom/master_log.jsonl: publisher.published/results(status=published)` | cardinality of authoritative unique Publisher publication identities; count |
| `menzo.linked_handoff_publication_overlap` | Unique handoff identities linked to final news publications. | `state/newsroom/master_log.jsonl: menzo.selected and authoritative Publisher publication set` | cardinality of the intersection in a namespace shared by every compared record; count |
| `menzo.handoff_to_publication_ratio` | Linked handoff/publication overlap divided by unique downstream handoffs. | `scripts/observability_snapshot.py canonical funnel` | menzo.linked_handoff_publication_overlap / menzo.unique_downstream_handoffs; ratio |
| `alfred.unique_articles_reviewed` | Unique identities with a review. | `state/newsroom/master_log.jsonl: alfred.reviews (plus Publisher authority where required)` | cardinality of unique identities in alfred.reviews; count |
| `alfred.unique_articles_with_warnings` | Unique reviewed identities having at least one warning entry. | `state/newsroom/master_log.jsonl: alfred.reviews (plus Publisher authority where required)` | cardinality of unique warning-bearing review identities; count |
| `alfred.warning_events` | Review events whose warning list is non-empty. | `state/newsroom/master_log.jsonl: alfred.reviews (plus Publisher authority where required)` | count warning-bearing review rows; count |
| `alfred.warning_occurrences` | Individual entries across warning lists. | `state/newsroom/master_log.jsonl: alfred.reviews (plus Publisher authority where required)` | sum warning_occurrences_total; legacy lists at the ten-entry cap are unavailable; count |
| `alfred.unique_final_blockers` | Unique identities whose latest unresolved review remains blocked without later approval/publication. | `state/newsroom/master_log.jsonl: alfred.reviews (plus Publisher authority where required)` | chronological latest-outcome computation joined to authoritative publications; count |
| `alfred.revised_then_approved` | Unique identities revised before a later approval. | `state/newsroom/master_log.jsonl: alfred.reviews (plus Publisher authority where required)` | chronological transition count by identity; count |
| `alfred.revised_then_published` | Unique identities revised before a later authoritative publication. | `state/newsroom/master_log.jsonl: alfred.reviews (plus Publisher authority where required)` | chronological transition count joined to publications; count |
| `gemini.real_attempts` | Ledger rows with status called or failed. | `state/newsroom/gemini_call_ledger.jsonl` | count rows whose status is called or failed; count |
| `gemini.completed_calls` | API calls that returned without an attempt exception; not semantic success. | `state/newsroom/gemini_call_ledger.jsonl` | count rows whose status is called; count |
| `gemini.failures` | Attempt exceptions. | `state/newsroom/gemini_call_ledger.jsonl` | count rows whose status is failed; count |
| `gemini.avoided_calls` | Explicitly saved calls that were not made. | `state/newsroom/gemini_call_ledger.jsonl` | count rows whose status is avoided; count |
| `gemini.fallbacks` | Real attempts carrying fallback=true. | `state/newsroom/gemini_call_ledger.jsonl` | count real-attempt rows with fallback=true; count |
| `gemini.gemini_3_5_attempts` | Gemini 3.5 ledger rows with status called or failed; completed does not imply semantic success. | `state/newsroom/gemini_call_ledger.jsonl` | filter bounded rows to model name containing 3.5 and status called or failed; count |
| `gemini.gemini_3_5_completed_calls` | Gemini 3.5 ledger rows with status called; completed does not imply semantic success. | `state/newsroom/gemini_call_ledger.jsonl` | filter bounded rows to model name containing 3.5 and status called; count |
| `gemini.gemini_3_5_failures` | Gemini 3.5 ledger rows with status failed; completed does not imply semantic success. | `state/newsroom/gemini_call_ledger.jsonl` | filter bounded rows to model name containing 3.5 and status failed; count |
| `gemini.gemini_3_5_avoided_calls` | Gemini 3.5 ledger rows with status avoided; completed does not imply semantic success. | `state/newsroom/gemini_call_ledger.jsonl` | filter bounded rows to model name containing 3.5 and status avoided; count |
| `simone.reports_published` | Unique authoritative published reports. | `state/newsroom/master_log.jsonl: simone.published_reports(status=published)` | cardinality of unique authoritative report publication identities; count |
| `simone.already_present_events` | Master-log report publication events marked already present. | `state/newsroom/master_log.jsonl: simone.publish_handoff.already_published` | sum in-window already_published event counters; count |
| `publisher.publications_unique` | Unique successful news publications. | `state/newsroom/master_log.jsonl: publisher.published/results(status=published)` | cardinality of unique authoritative published identities; count |

| `andrea.checked_occurrences` | Canonical Andrea checked occurrences. | `state/newsroom/canonical_event_ledger.jsonl` | count validated content_sufficiency_checked events at checked grain; count |
| `andrea.checked_content` | Unique content at canonical Andrea checked grain. | `state/newsroom/canonical_event_ledger.jsonl` | distinct content_id across validated checked events; count |
| `andrea.passed_occurrences` | Canonical Andrea passed occurrences. | `state/newsroom/canonical_event_ledger.jsonl` | count validated content_sufficiency_checked events at passed grain; count |
| `andrea.passed_content` | Unique content at canonical Andrea passed grain. | `state/newsroom/canonical_event_ledger.jsonl` | distinct content_id across validated passed events; count |
| `andrea.passed_with_exception_occurrences` | Canonical Andrea passed_with_exception occurrences. | `state/newsroom/canonical_event_ledger.jsonl` | count validated content_sufficiency_checked events at passed_with_exception grain; count |
| `andrea.passed_with_exception_content` | Unique content at canonical Andrea passed_with_exception grain. | `state/newsroom/canonical_event_ledger.jsonl` | distinct content_id across validated passed_with_exception events; count |
| `andrea.blocked_occurrences` | Canonical Andrea blocked occurrences. | `state/newsroom/canonical_event_ledger.jsonl` | count validated content_sufficiency_checked events at blocked grain; count |
| `andrea.blocked_content` | Unique content at canonical Andrea blocked grain. | `state/newsroom/canonical_event_ledger.jsonl` | distinct content_id across validated blocked events; count |
| `alfred.warning_bearing_reviews` | Canonical Alfred reviews bearing warnings. | `state/newsroom/canonical_event_ledger.jsonl` | distinct run_id plus correlation_id among warning_recorded events; count |
| `alfred.blocker_occurrences` | Historical Alfred blocker occurrences. | `state/newsroom/canonical_event_ledger.jsonl` | count blocker_recorded events including later-resolved blockers; count |
| `alfred.blocker_bearing_reviews` | Canonical Alfred reviews bearing blockers. | `state/newsroom/canonical_event_ledger.jsonl` | distinct run_id plus correlation_id among blocker_recorded events; count |
| `alfred.unique_articles_with_blockers` | Unique content with historical Alfred blockers. | `state/newsroom/canonical_event_ledger.jsonl` | distinct content_id among blocker_recorded events; count |

## 5. Partially available and diagnostic metrics

These rows expose real signals but not a complete authoritative editorial-window metric. Typical causes are per-run-only counters, incomplete stable identities, legacy caps, partial run coverage, or a latest-run artifact without retention.

For Menzo pair coverage, the sole primary authority is the nested producing-run artifact: `same_run.expected_pair_count`, `same_run.authoritative_evaluated_pair_count`, `recent_history.expected_pair_count`, `recent_history.authoritative_evaluated_pair_count`, and `total.coverage_complete` under `artifacts/newsroom/menzo_duplicate_pair_coverage.json`. The corresponding flat `postprocess.duplicate_pair_coverage.*` fields are reconciliation sources only.

| Name | Availability | Limitation |
|---|---|---|
| `runtime.expected_dirt_paths` | source_dependent | Expected paths are limited to .bot_exit_code, logs/master_log.log, and reports/. This is repository diagnostics, not a newsroom outcome. |
| `runtime.unexpected_dirt_paths` | source_dependent | Expected paths are limited to .bot_exit_code, logs/master_log.log, and reports/. This is repository diagnostics, not a newsroom outcome. |
| `massy.urls_found` | partially_available | The numeric handoff exists, but complete stable item identities and authoritative cross-run uniqueness do not. |
| `massy.candidate_news` | partially_available | The numeric handoff exists, but complete stable item identities and authoritative cross-run uniqueness do not. |
| `massy.candidate_reports` | partially_available | The numeric handoff exists, but complete stable item identities and authoritative cross-run uniqueness do not. |
| `massy.hard_skips` | partially_available | The numeric handoff exists, but complete stable item identities and authoritative cross-run uniqueness do not. |
| `massy.published_skips` | partially_available | The numeric handoff exists, but complete stable item identities and authoritative cross-run uniqueness do not. |
| `massy.actionable_handoffs` | partially_available | The numeric handoff exists, but complete stable item identities and authoritative cross-run uniqueness do not. |
| `menzo.same_run_expected_pairs` | partially_available | Authoritative for its producing run only; the artifact has no retained window series. The v95.21.1 matrix is unchanged. No authoritative series exists across the editorial window. |
| `menzo.same_run_evaluated_pairs` | partially_available | Authoritative for its producing run only; the artifact has no retained window series. The v95.21.1 matrix is unchanged. No authoritative series exists across the editorial window. |
| `menzo.recent_history_expected_pairs` | partially_available | Authoritative for its producing run only; the artifact has no retained window series. The v95.21.1 matrix is unchanged. No authoritative series exists across the editorial window. |
| `menzo.recent_history_evaluated_pairs` | partially_available | Authoritative for its producing run only; the artifact has no retained window series. The v95.21.1 matrix is unchanged. No authoritative series exists across the editorial window. |
| `menzo.duplicate_coverage_complete` | partially_available | Not promoted to an editorial-window active metric because only latest-run detail is retained. No authoritative series exists across the editorial window. |
| `menzo.exact_duplicate_pairs` | partially_available | Not promoted to an editorial-window active metric because only latest-run detail is retained. No authoritative series exists across the editorial window. |
| `menzo.suspicious_pairs` | partially_available | Not promoted to an editorial-window active metric because only latest-run detail is retained. No authoritative series exists across the editorial window. |
| `menzo.pairs_below_threshold` | partially_available | Not promoted to an editorial-window active metric because only latest-run detail is retained. No authoritative series exists across the editorial window. |
| `menzo.duplicates_blocked` | partially_available | Not promoted to an editorial-window active metric because only latest-run detail is retained. No authoritative series exists across the editorial window. |
| `menzo.arbitration_failures` | partially_available | Not promoted to an editorial-window active metric because only latest-run detail is retained. No authoritative series exists across the editorial window. |
| `menzo.terminal_invariant_failures` | partially_available | Not promoted to an editorial-window active metric because only latest-run detail is retained. No authoritative series exists across the editorial window. |
| `menzo.material_updates` | partially_available | Not promoted to an editorial-window active metric because only latest-run detail is retained. No authoritative series exists across the editorial window. |
| `menzo.selected_after_budget` | partially_available | Final handoff count is not interchangeable with intermediate selected values printed during policy postprocessing. |
| `menzo.pending` | partially_available | Final handoff count is not interchangeable with intermediate selected values printed during policy postprocessing. |
| `menzo.skipped` | partially_available | Final handoff count is not interchangeable with intermediate selected values printed during policy postprocessing. |
| `andrea.gemini_calls_saved` | partially_available | Name describes the desired metric; current source supports event counts only, so it is not active. |
| `andrea.fetches_performed` | partially_available | Name describes the desired metric; current source supports event counts only, so it is not active. |
| `andrea.checked_events` | partially_available | This measures events only and must not substitute for the corresponding planned unique metric. |
| `andrea.passed_events` | partially_available | This measures events only and must not substitute for the corresponding planned unique metric. |
| `andrea.blocked_events` | partially_available | This measures events only and must not substitute for the corresponding planned unique metric. |
| `bob.model_attempts` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `bob.model_failures` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `bob.fallbacks` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `bob.packages_ready` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `bob.packages_pending` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `bob.packages_empty` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `bob.packages_errors` | partially_available | Generic errors do not distinguish recoverable from terminal outcomes. |
| `gemini.token_usage_coverage` | source_dependent | Coverage describes metadata availability, not token or cost completeness for legacy rows. |
| `gemini.cost_coverage` | source_dependent | Coverage describes metadata availability, not token or cost completeness for legacy rows. |
| `simone.report_candidates_found` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `simone.reports_ready` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `simone.legacy_errors_diagnostic` | partially_available | Never substitute for simone.terminal_errors. |
| `publisher.publication_attempts` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `publisher.already_present_events` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `publisher.dry_run_events` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `publisher.wordpress_not_ready_events` | partially_available | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `artifact_coverage.source_material_coverage` | source_dependent | No retention or new artifact is introduced by A1. |
| `artifact_coverage.translated_candidate_coverage` | source_dependent | No retention or new artifact is introduced by A1. |
| `artifact_coverage.alfred_reviewed_coverage` | source_dependent | No retention or new artifact is introduced by A1. |
| `artifact_coverage.final_published_coverage` | source_dependent | No retention or new artifact is introduced by A1. |
| `artifact_coverage.end_to_end_comparative_coverage` | source_dependent | No retention or new artifact is introduced by A1. |

## 6. Planned metrics

Planned rows are contract placeholders, not fabricated measurements. Simone lifecycle/SLA and typed errors wait for lifecycle telemetry; Publisher error terminality waits for typed outcomes; WordPress waits for structured probe/error telemetry; Bob semantic success and logical-request accounting wait for a stable operation taxonomy.

| Name | Availability | Why unavailable |
|---|---|---|
| `andrea.checked_unique` | unavailable | Existing andrea.handoff counters support only per-run events; they cannot authoritatively deduplicate articles across runs. |
| `andrea.passed_unique` | unavailable | Existing andrea.handoff counters support only per-run events; they cannot authoritatively deduplicate articles across runs. |
| `andrea.blocked_unique` | unavailable | Existing andrea.handoff counters support only per-run events; they cannot authoritatively deduplicate articles across runs. |
| `bob.logical_translation_requests` | unavailable | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `bob.model_successes` | unavailable | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `simone.reports_due` | unavailable | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `simone.reports_missing` | unavailable | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `simone.reports_ambiguous` | unavailable | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `simone.errors_recovered` | unavailable | Generic handoff errors are diagnostic and MUST NOT be interpreted as terminal errors. |
| `simone.terminal_errors` | unavailable | Generic handoff errors are diagnostic and MUST NOT be interpreted as terminal errors. |
| `simone.sla_violations` | unavailable | Null means the authoritative source is absent, unreadable, incomplete, or cannot support this semantic. |
| `publisher.recoverable_errors` | unavailable | Generic publisher.handoff.errors cannot establish recovery or terminality. |
| `publisher.terminal_errors` | unavailable | Generic publisher.handoff.errors cannot establish recovery or terminality. |
| `wordpress.preflight_attempts` | unavailable | Text diagnostics and generic counters are insufficient for an authoritative typed metric. |
| `wordpress.endpoint_probes` | unavailable | Text diagnostics and generic counters are insufficient for an authoritative typed metric. |
| `wordpress.recovered_failures` | unavailable | Text diagnostics and generic counters are insufficient for an authoritative typed metric. |
| `wordpress.terminal_failures` | unavailable | Text diagnostics and generic counters are insufficient for an authoritative typed metric. |
| `wordpress.timeouts` | unavailable | Text diagnostics and generic counters are insufficient for an authoritative typed metric. |
| `wordpress.http_errors` | unavailable | Text diagnostics and generic counters are insufficient for an authoritative typed metric. |
| `wordpress.dns_errors` | unavailable | Text diagnostics and generic counters are insufficient for an authoritative typed metric. |

## 7. Legacy aliases

Aliases are input-compatibility labels only. They never become competing authorities. `called` means that the API returned without an attempt exception, not that the content was usable or semantically correct. The label `selected` is an alias only of `menzo.selected_after_budget`; `state/newsroom/master_log.jsonl: menzo.selected` is instead the authoritative source field used to calculate `menzo.unique_downstream_handoffs`, not an alias of that metric.

| Observed alias | Canonical destination | Warning |
|---|---|---|
| `duplicate_pair_coverage.same_run_expected` | `menzo.same_run_expected_pairs` | Interpret only with the destination semantics and source/window contract. |
| `duplicate_pair_coverage.same_run_evaluated` | `menzo.same_run_evaluated_pairs` | Interpret only with the destination semantics and source/window contract. |
| `duplicate_pair_coverage.recent_history_expected` | `menzo.recent_history_expected_pairs` | Interpret only with the destination semantics and source/window contract. |
| `duplicate_pair_coverage.recent_history_evaluated` | `menzo.recent_history_evaluated_pairs` | Interpret only with the destination semantics and source/window contract. |
| `duplicate_pair_coverage.coverage_complete` | `menzo.duplicate_coverage_complete` | Interpret only with the destination semantics and source/window contract. |
| `duplicate_pair_terminal_invariant_failures` | `menzo.terminal_invariant_failures` | Interpret only with the destination semantics and source/window contract. |
| `selected` | `menzo.selected_after_budget` | Interpret only with the destination semantics and source/window contract. |
| `pending` | `menzo.pending` | Interpret only with the destination semantics and source/window contract. |
| `skipped` | `menzo.skipped` | Interpret only with the destination semantics and source/window contract. |
| `warnings` | `alfred.warning_occurrences` | Interpret only with the destination semantics and source/window contract. |
| `warning_count` | `alfred.warning_occurrences` | Interpret only with the destination semantics and source/window contract. |
| `called_total` | `gemini.completed_calls` | Interpret only with the destination semantics and source/window contract. |
| `avoided_total` | `gemini.avoided_calls` | Interpret only with the destination semantics and source/window contract. |
| `called_35_total` | `gemini.gemini_3_5_completed_calls` | Interpret only with the destination semantics and source/window contract. |
| `gemini_3_5_called_total` | `gemini.gemini_3_5_completed_calls` | Interpret only with the destination semantics and source/window contract. |
| `simone.publish_handoff.errors` | `simone.legacy_errors_diagnostic` | Interpret only with the destination semantics and source/window contract. |

## 8. Ambiguous metrics

No ambiguous counter is promoted to `active`. Bare `selected`, `pending`, `skipped`, `warnings`, `warning_count`, `published`, `already`, `wp_not_ready`, and `errors` are context-dependent legacy observations catalogued in the legacy inventory. Their scope, entity, and lifecycle state must be established before use.

## 9. Deprecated metrics

| Name | Replacement | Reason |
|---|---|---|
| `gemini.completed_successful_calls` | `gemini.completed_calls` | Deprecated because status=called is not semantic success. |
| `gemini.gemini_3_5_completed_successful_calls` | `gemini.gemini_3_5_completed_calls` | Deprecated because status=called is not semantic success. |

## 10. Diagnostic gaps

- Massy lacks complete persisted outcome identities across runs.
- Andrea compact handoffs support event aggregation, not authoritative unique article counts.
- Menzo pair coverage is authoritative per produced run but has no retained window series in the current contract.
- Bob lacks a stable logical-operation and semantic-success taxonomy distinct from attempts and package outcomes.
- Simone and Publisher generic errors lack typed recovery/terminal lifecycle states.
- WordPress probes and failures lack structured typed telemetry.
- Gemini token/cost values are source-dependent; coverage is reported rather than invented.
- Artifact coverage depends on the generated translation-audit population and material provenance; A1 adds no retention.

## 11. Schema evolution rules

1. Frozen canonical names cannot change meaning. A new semantic requires a new dotted name.
2. A rename must retain the old name as alias or deprecated and identify `replacement`.
3. One metric has one primary authority; other inputs remain secondary/reconciliation/diagnostic/legacy.
4. Promotion to `active` requires a real primary source, formula, time window, identity/aggregation contract, and distinct zero/missing semantics.
5. Enum or required-field changes require a new catalog schema version; semantic policy changes require a new policy version.
6. Removal follows deprecation and consumer migration; aliases must be collision-free.
7. The validator remains offline and is not connected to newsroom runtime.
