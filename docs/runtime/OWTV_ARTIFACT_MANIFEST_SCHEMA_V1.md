# OWTV Artifact Manifest Schema v1

## Purpose and scope
A3 is the Phase 0 measurement-only, contract-only definition of a future artifact manifest entry. It emits nothing and changes no runtime behavior.

## A1, A2, Phase 1 and Reform B
A1 defines metrics; A2 defines future events; A3 defines artifact-instance metadata compatible with A2 `artifact_refs`. Phase 1 may later build the canonical ledger and artifact index. Reform B may later retain the source → Bob candidate → Alfred review → final material chain. A3 implements neither retention nor indexing.

## Artifact instance and family
An inventory row describes a family; a manifest envelope describes one concrete version. **`artifact_id != path`**: fixed snapshot paths are reused across runs, so `artifact_id` is stable for one instance and unique across distinct instances. A3 deliberately specifies no runtime generation algorithm.

## Taxonomies

### Artifact types
<!-- SYNC:ARTIFACT_TYPES snapshot|ledger|history|cache|memory|coverage|archive|report|log -->
| Value |
|---|
| snapshot |
| ledger |
| history |
| cache |
| memory |
| coverage |
| archive |
| report |
| log |

### Storage classes
<!-- SYNC:STORAGE_CLASSES runtime_snapshot|runtime_state|runtime_log|diagnostic_report|review_archive|published_material_archive -->
| Value |
|---|
| runtime_snapshot |
| runtime_state |
| runtime_log |
| diagnostic_report |
| review_archive |
| published_material_archive |

### Persistence classes
<!-- SYNC:PERSISTENCE_CLASSES current_snapshot|bounded_history|persistent_state|append_only_ledger|immutable_archive|generated_report -->
| Value |
|---|
| current_snapshot |
| bounded_history |
| persistent_state |
| append_only_ledger |
| immutable_archive |
| generated_report |

### Mutation modes
<!-- SYNC:MUTATION_MODES atomic_overwrite|bounded_rewrite|append_only|immutable -->
| Value |
|---|
| atomic_overwrite |
| bounded_rewrite |
| append_only |
| immutable |

### Retention modes
<!-- SYNC:RETENTION_MODES current_only|bounded_count|bounded_time|persistent|sampled|unknown_legacy -->
| Value |
|---|
| current_only |
| bounded_count |
| bounded_time |
| persistent |
| sampled |
| unknown_legacy |

### Semantic roles
<!-- SYNC:SEMANTIC_ROLES runtime_status|intake_snapshot|report_lifecycle|selection_decision|duplicate_evidence|content_sufficiency|translated_candidate|quality_review|publication_result|audit|model_call_telemetry|source_material|final_published_material|diagnostic_output|state_memory -->
| Value |
|---|
| runtime_status |
| intake_snapshot |
| report_lifecycle |
| selection_decision |
| duplicate_evidence |
| content_sufficiency |
| translated_candidate |
| quality_review |
| publication_result |
| audit |
| model_call_telemetry |
| source_material |
| final_published_material |
| diagnostic_output |
| state_memory |

### Authority purposes
<!-- SYNC:AUTHORITY_PURPOSES pipeline_observability|publication_outcome|report_publication_outcome|source_material|translated_candidate_material|final_published_material|duplicate_decision|quality_review|model_usage_cost|runtime_health -->
| Value |
|---|
| pipeline_observability |
| publication_outcome |
| report_publication_outcome |
| source_material |
| translated_candidate_material |
| final_published_material |
| duplicate_decision |
| quality_review |
| model_usage_cost |
| runtime_health |

### Authority levels
<!-- SYNC:AUTHORITY_LEVELS authoritative|supporting|diagnostic|legacy_context -->
| Value |
|---|
| authoritative |
| supporting |
| diagnostic |
| legacy_context |

Storage class is physical placement; persistence class is lifecycle intent. Mutation mode independently states how bytes change. Semantic roles are multi-valued and do not replace producer stage. Known agentic components (`newsroom_runner`, master-log, Gemini-ledger, Menzo-policy, Publisher-history, Simone-publisher, Menzo-cache, and story-dedupe components) require a canonical `producer_agent`; diagnostic adapters, generic legacy components, and the future Reform B placeholder may omit it. The validator derives the known agentic component set from this inventory to prevent silent drift.

## Retention policy
`mode` and `value_source` are required. `bounded_count` requires positive `max_items`; `bounded_time` requires positive `max_age_days`. Sources are `fixed_contract`, `code_default`, `runtime_configurable`, and `unknown_legacy`. Values are observations only and do not change retention.

## Purpose-scoped authority
Authority is a list of `{purpose, level, selector?, note?}` claims, never a global boolean. Publication outcome metadata does not establish final linguistic material. Bob/Alfred generic bodies are candidates. Source material needs explicit provenance. Only documented verified published-html adapters establish final material; review packages never do. Master log is primary observability and its tail is fallback.

## Path-pattern dialect
The inventory uses `python_glob_v1`: `/` is the separator and only Python-compatible `*`, `**`, `?`, and `[...]` glob tokens are supported. Brace expansion is forbidden, as are absolute paths and parent traversal. Patterns are metadata only: A3 performs no filesystem discovery.

## Identity, path and integrity
Identity links retain A2 names: `run_id`, `article_id`, `pair_id`, `correlation_id`, `content_id`, `story_id`, `report_key`, `logical_request_id`. Missing means unavailable/not applicable, never empty evidence. Paths are runtime/repository-relative, non-absolute, traversal-free and never embed content. Optional SHA-256 is lowercase hexadecimal over exact artifact bytes; `size_bytes` is non-negative. Integrity is recommended for future immutable/indexed instances, not required retroactively.

## A2 artifact_refs compatibility
A2 remains `path` + `relation` (`input`, `output`, `evidence`) with optional `artifact_type`, `schema_version`, `sha256`, and `embed_content=false`. A3 does not redefine event-relative relations. Producer agent/stage taxonomies are checked against A2.

## Legacy artifact inventory
Family resolution uses the protected `specific_before_catch_all` strategy: recognized adapter families govern matching paths, while `review_packages/**/*.html` and `published_html_review/**/*.html` apply only when no specific family matches. Recognized `published_html_review` adapters are ordered semantically: nested and flat originals are source material, nested and flat finals are verified final material, modular `v93-news` is candidate material, and modular `v93-publisher` is verified final material. Catch-all HTML rows apply only after those adapters. Review-package source and candidate HTML families are separate from unknown HTML and metadata; none is final-publication authority. Report JSON and Markdown families are split so each pattern has one truthful format.

Evidence is existence evidence, not semantic authority: `both` means code plus the supplied production probe; `observed_production` is probe-only; `code_declared` is repository-only; `documented_legacy` is adapter/documentation evidence; `planned_canonical` is future-only.

<!-- SYNC:INVENTORY_COLUMNS path_or_pattern|artifact_type|format|producer_component|producer_agent|producer_stage|storage_class|persistence_class|mutation_mode|evidence_basis|lifecycle_status|semantic_roles|retention_summary|authority_claims|artifact_schema_status|notes -->
| Path/pattern | Type | Format | Component | Agent | Stage | Storage | Persistence | Mutation | Evidence | Lifecycle | Roles | Retention | Authority | Schema status | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| artifacts/newsroom/jarvis_status.json | snapshot | json | newsroom_runner | Jarvis | runtime | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["runtime_status"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"runtime_health","level":"authoritative"}] | none_unknown | Fixed-path newsroom snapshot atomically replaced by the runner. |
| artifacts/newsroom/massy_board.json | snapshot | json | newsroom_runner | Massy | intake | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["intake_snapshot"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"pipeline_observability","level":"supporting"}] | none_unknown | Fixed-path newsroom snapshot atomically replaced by the runner. |
| artifacts/newsroom/simone_reports.json | snapshot | json | newsroom_runner | Simone | reporting | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["report_lifecycle"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"pipeline_observability","level":"supporting"}] | none_unknown | Fixed-path newsroom snapshot atomically replaced by the runner. |
| artifacts/newsroom/simone_report_publish.json | snapshot | json | newsroom_runner | Simone | reporting | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["report_lifecycle","publication_result"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"report_publication_outcome","level":"authoritative","selector":"results[status=published]"}] | none_unknown | Raw Simone publisher artifact records outcome rows in results[]; only results with status=published establish report publication. |
| artifacts/newsroom/menzo_decisions.json | snapshot | json | newsroom_runner | Menzo | selection | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["selection_decision","duplicate_evidence"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"duplicate_decision","level":"supporting"}] | none_unknown | Fixed-path newsroom snapshot atomically replaced by the runner. |
| artifacts/newsroom/andrea_pre_bob_latest.json | snapshot | json | newsroom_runner | Andrea | content_sufficiency | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["content_sufficiency"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"pipeline_observability","level":"supporting"}] | none_unknown | Fixed-path newsroom snapshot atomically replaced by the runner. |
| artifacts/newsroom/bob_articles.json | snapshot | json | newsroom_runner | Bob | generation | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["translated_candidate"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"translated_candidate_material","level":"supporting","selector":"articles[].body_html"}] | none_unknown | Bob body_html is translated-candidate material and never final-published material. |
| artifacts/newsroom/alfred_review.json | snapshot | json | newsroom_runner | Alfred | quality | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["quality_review","translated_candidate"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"quality_review","level":"supporting"},{"purpose":"translated_candidate_material","level":"supporting","selector":"reviews[].article.body_html"}] | none_unknown | Alfred review/candidate bodies are not final-published material. |
| artifacts/newsroom/publisher_result.json | snapshot | json | newsroom_runner | Publisher | publication | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["publication_result"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"publication_outcome","level":"authoritative","selector":"published[] and results[status=published]"}] | none_unknown | Publisher status, title, source URL and WordPress URL establish outcome, not final linguistic material. |
| artifacts/newsroom/archivista_report.json | snapshot | json | newsroom_runner | Archivista | audit | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["audit"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"pipeline_observability","level":"diagnostic"}] | none_unknown | Fixed-path newsroom snapshot atomically replaced by the runner. |
| artifacts/newsroom/agent_timeline.json | snapshot | json | newsroom_runner | Jarvis | runtime | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["runtime_status","diagnostic_output"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"pipeline_observability","level":"diagnostic"}] | none_unknown | Fixed-path newsroom snapshot atomically replaced by the runner. |
| artifacts/newsroom/run_summary.json | snapshot | json | newsroom_runner | Jarvis | runtime | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["runtime_status","diagnostic_output"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"pipeline_observability","level":"diagnostic"}] | none_unknown | Fixed-path newsroom snapshot atomically replaced by the runner. |
| state/newsroom/master_log.jsonl | memory | jsonl | agents.master_log_v93_19 | Jarvis | runtime | runtime_state | bounded_history | bounded_rewrite | both | active | ["state_memory","audit"] | {"mode":"bounded_count","max_items":300,"value_source":"runtime_configurable"} | [{"purpose":"pipeline_observability","level":"authoritative","selector":"complete run records"}] | none_unknown | Primary complete observability source; MAX_RUNS defaults to 300 and is environment-configurable. |
| artifacts/newsroom/master_log_tail.jsonl | memory | jsonl | agents.master_log_v93_19 | Jarvis | runtime | runtime_snapshot | bounded_history | bounded_rewrite | code_declared | fallback | ["state_memory","diagnostic_output"] | {"mode":"bounded_count","max_items":40,"value_source":"runtime_configurable"} | [{"purpose":"pipeline_observability","level":"supporting","selector":"tail fallback"}] | none_unknown | Bounded TAIL_RUNS fallback only; never outranks the primary master log. |
| artifacts/newsroom/newsroom_master.log | log | text/log | agents.master_log_v93_19 | Jarvis | runtime | runtime_log | bounded_history | bounded_rewrite | code_declared | active | ["diagnostic_output"] | {"mode":"bounded_count","max_items":40,"value_source":"runtime_configurable"} | [{"purpose":"pipeline_observability","level":"diagnostic"}] | none_unknown | Human-readable artifact rebuilt atomically from records[-TAIL_RUNS:]; TAIL_RUNS defaults to 40 via V93_MASTER_LOG_ARTIFACT_TAIL. |
| state/newsroom/gemini_call_ledger.jsonl | ledger | jsonl | agents.gemini_ledger | Gemini | model | runtime_state | append_only_ledger | append_only | both | active | ["model_call_telemetry"] | {"mode":"persistent","value_source":"code_default"} | [{"purpose":"model_usage_cost","level":"authoritative"}] | producer_version_only | Current runtime appends one JSONL row per Gemini call/avoidance record. |
| artifacts/newsroom/gemini_call_ledger_latest.json | snapshot | json | agents.gemini_ledger | Gemini | model | runtime_snapshot | current_snapshot | atomic_overwrite | code_declared | active | ["model_call_telemetry"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"model_usage_cost","level":"supporting"}] | producer_version_only | Latest-call snapshot; it is not the append-only ledger. |
| artifacts/newsroom/menzo_duplicate_pair_coverage.json | coverage | json | agents.menzo_policy_v93_15 | Menzo | duplicate | runtime_snapshot | current_snapshot | atomic_overwrite | both | active | ["duplicate_evidence"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"duplicate_decision","level":"authoritative","selector":"producing latest run only"}] | known | Latest-run pair coverage written by Menzo policy with artifact schema owtv_duplicate_pair_coverage_v1. |
| state/newsroom/publisher_history.json | history | json | agents.publisher_history | Publisher | publication | runtime_state | persistent_state | atomic_overwrite | both | active | ["publication_result","state_memory"] | {"mode":"persistent","value_source":"code_default"} | [{"purpose":"publication_outcome","level":"supporting","selector":"successful publication records"}] | none_unknown | Publisher idempotency/history state; outcome evidence, not final text. |
| state/newsroom/simone_report_history.json | history | json | agents.simone_publisher_v93_18 | Simone | reporting | runtime_state | persistent_state | atomic_overwrite | both | active | ["report_lifecycle","state_memory"] | {"mode":"persistent","value_source":"code_default"} | [{"purpose":"report_publication_outcome","level":"supporting"}] | none_unknown | Report publication history state. |
| state/newsroom/simone_reports_latest.json | snapshot | json | agents.simone_publisher_v93_18 | Simone | reporting | runtime_state | current_snapshot | atomic_overwrite | both | active | ["report_lifecycle"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"report_publication_outcome","level":"supporting"}] | none_unknown | Latest Simone report-processing snapshot. |
| state/newsroom/simone_report_publish_latest.json | snapshot | json | agents.simone_publisher_v93_18 | Simone | reporting | runtime_state | current_snapshot | atomic_overwrite | code_declared | active | ["report_lifecycle","publication_result"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"report_publication_outcome","level":"authoritative","selector":"results[status=published]"}] | none_unknown | Latest Simone report-publisher state snapshot atomically overwritten with the same result payload; Bob reads handoff counters for dynamic capacity. Only results[status=published] establishes report publication outcome; it contains no final linguistic material. |
| state/newsroom/menzo_duplicate_arbitration_cache_v2.json | cache | json | agents.menzo_duplicate_cache | Menzo | duplicate | runtime_state | persistent_state | atomic_overwrite | both | active | ["duplicate_evidence","state_memory"] | {"mode":"persistent","value_source":"code_default"} | [{"purpose":"duplicate_decision","level":"supporting"}] | producer_version_only | Versioned deterministic duplicate arbitration cache; cache evidence is not publication authority. |
| state/newsroom/story_dedupe_memory.json | memory | json | agents.story_dedupe_v93_32 | Menzo | duplicate | runtime_state | persistent_state | atomic_overwrite | code_declared | active | ["duplicate_evidence","state_memory"] | {"mode":"bounded_time","max_age_days":4,"value_source":"code_default"} | [{"purpose":"duplicate_decision","level":"legacy_context"}] | producer_version_only | Story dedupe memory is TTL-pruned at the 96-hour code default; it is not canonical pair truth. |
| state/newsroom/story_footprints.json | memory | json | agents.story_dedupe_v93_32 | Menzo | duplicate | runtime_state | persistent_state | atomic_overwrite | code_declared | legacy | ["duplicate_evidence","state_memory"] | {"mode":"bounded_time","max_age_days":7,"value_source":"code_default"} | [{"purpose":"duplicate_decision","level":"legacy_context"}] | producer_version_only | Legacy heuristic story-footprint memory uses the 168-hour code default and is not blocking pair authority. |
| state/newsroom/story_fingerprints.json | memory | json | agents.story_dedupe_v93_32 | Menzo | duplicate | runtime_state | persistent_state | atomic_overwrite | code_declared | legacy | ["duplicate_evidence","state_memory"] | {"mode":"bounded_time","max_age_days":7,"value_source":"code_default"} | [{"purpose":"duplicate_decision","level":"legacy_context"}] | producer_version_only | Generalized fingerprint memory uses the 168-hour code default and remains supporting/legacy duplicate context. |
| state/newsroom/menzo_softpool.json | memory | json | agents.menzo_policy_v93_15 | Menzo | selection | runtime_state | persistent_state | atomic_overwrite | code_declared | active | ["selection_decision","state_memory"] | {"mode":"persistent","value_source":"code_default"} | [{"purpose":"pipeline_observability","level":"supporting"}] | none_unknown | Selective softpool state confirmed by current policy code. |
| state/newsroom/pending_*.json | memory | json | legacy pending subsystem | — | runtime | runtime_state | persistent_state | atomic_overwrite | code_declared | legacy | ["state_memory","report_lifecycle"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"pipeline_observability","level":"legacy_context"}] | none_unknown | Legacy root/state pending families are producer-specific and do not imply selection or publication. |
| reports/*.json | report | json | observability and audit scripts | — | audit | diagnostic_report | generated_report | immutable | code_declared | active | ["audit","diagnostic_output"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"pipeline_observability","level":"diagnostic"}] | varies | Generated JSON diagnostic report family; retention is producer/runtime-specific and not changed by A3. |
| reports/*.md | report | markdown | observability and audit scripts | — | audit | diagnostic_report | generated_report | immutable | code_declared | active | ["audit","diagnostic_output"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"pipeline_observability","level":"diagnostic"}] | varies | Generated Markdown diagnostic report family; retention is producer/runtime-specific and not changed by A3. |
| review_packages/**/original.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["source_material","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"source_material","level":"supporting","selector":"recognized original.html or source.html"}] | varies | Recognized review-package source HTML; never publication or final-material authority. |
| review_packages/**/source.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["source_material","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"source_material","level":"supporting","selector":"recognized original.html or source.html"}] | varies | Recognized review-package source HTML; never publication or final-material authority. |
| review_packages/**/*_original.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["source_material","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"source_material","level":"supporting","selector":"recognized *_original.html or *_source.html"}] | varies | Recognized suffixed review-package source HTML; never publication or final-material authority. |
| review_packages/**/*_source.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["source_material","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"source_material","level":"supporting","selector":"recognized *_original.html or *_source.html"}] | varies | Recognized suffixed review-package source HTML; never publication or final-material authority. |
| review_packages/**/translated.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["translated_candidate","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"translated_candidate_material","level":"supporting","selector":"recognized translated.html, candidate.html, or body.html"}] | varies | Recognized review-package candidate HTML; never publication or final-material authority. |
| review_packages/**/candidate.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["translated_candidate","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"translated_candidate_material","level":"supporting","selector":"recognized translated.html, candidate.html, or body.html"}] | varies | Recognized review-package candidate HTML; never publication or final-material authority. |
| review_packages/**/body.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["translated_candidate","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"translated_candidate_material","level":"supporting","selector":"recognized translated.html, candidate.html, or body.html"}] | varies | Recognized review-package candidate HTML; never publication or final-material authority. |
| review_packages/**/*_translated.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["translated_candidate","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"translated_candidate_material","level":"supporting","selector":"recognized suffixed candidate/body HTML"}] | varies | Recognized suffixed review-package candidate HTML; never publication or final-material authority. |
| review_packages/**/*_candidate.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["translated_candidate","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"translated_candidate_material","level":"supporting","selector":"recognized suffixed candidate/body HTML"}] | varies | Recognized suffixed review-package candidate HTML; never publication or final-material authority. |
| review_packages/**/*_body.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["translated_candidate","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"translated_candidate_material","level":"supporting","selector":"recognized suffixed candidate/body HTML"}] | varies | Recognized suffixed review-package candidate HTML; never publication or final-material authority. |
| review_packages/**/*.html | archive | html | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["diagnostic_output","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"quality_review","level":"diagnostic","selector":"only unclassified review-package HTML"}] | varies | Unknown review-package HTML is diagnostic-only after recognized role adapters. |
| review_packages/**/metadata.json | archive | json | scripts.translation_quality_audit documented review-package adapter | — | quality | review_archive | immutable_archive | immutable | documented_legacy | legacy | ["diagnostic_output","quality_review"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"quality_review","level":"diagnostic","selector":"metadata only"}] | varies | Review-package metadata is diagnostic context and contains no final-material authority. |
| published_html_review/**/original.html | archive | html | scripts.translation_quality_audit documented adapter | — | audit | published_material_archive | immutable_archive | immutable | documented_legacy | legacy | ["source_material"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"source_material","level":"authoritative","selector":"nested v80.10 original.html with adapter provenance"}] | varies | Nested v80.10 source adapter; recognized rows take precedence over the diagnostic catch-all. |
| published_html_review/**/final.html | archive | html | scripts.translation_quality_audit documented adapter | — | audit | published_material_archive | immutable_archive | immutable | documented_legacy | legacy | ["final_published_material"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"final_published_material","level":"authoritative","selector":"nested v80.10 final.html verified by adapter"}] | varies | Nested v80.10 verified-final adapter; recognized rows take precedence over the diagnostic catch-all. |
| published_html_review/*_original.html | archive | html | scripts.translation_quality_audit documented adapter | — | audit | published_material_archive | immutable_archive | immutable | documented_legacy | legacy | ["source_material"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"source_material","level":"authoritative","selector":"flat v81 metadata-linked original HTML"}] | varies | Flat v81 source adapter; metadata-declared filenames are authoritative over suffix assumptions. |
| published_html_review/*_final.html | archive | html | scripts.translation_quality_audit documented adapter | — | audit | published_material_archive | immutable_archive | immutable | documented_legacy | legacy | ["final_published_material"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"final_published_material","level":"authoritative","selector":"flat v81 metadata-linked final HTML"}] | varies | Flat v81 verified-final adapter; metadata-declared filenames are authoritative over suffix assumptions. |
| published_html_review/v93[-_]news[-_]*.html | archive | html | scripts.translation_quality_audit documented adapter | — | audit | published_material_archive | immutable_archive | immutable | documented_legacy | legacy | ["translated_candidate"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"translated_candidate_material","level":"supporting","selector":"recognized modular v93-news HTML"}] | varies | Modular v93 news HTML is translated-candidate material, never final-published material. |
| published_html_review/v93[-_]publisher[-_]*.html | archive | html | scripts.translation_quality_audit documented adapter | — | audit | published_material_archive | immutable_archive | immutable | documented_legacy | legacy | ["final_published_material"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"final_published_material","level":"authoritative","selector":"recognized and matched modular v93-publisher HTML"}] | varies | Modular v93 Publisher HTML is verified final material when matched by the documented adapter. |
| published_html_review/**/*.html | archive | html | scripts.translation_quality_audit documented adapter | — | audit | published_material_archive | immutable_archive | immutable | documented_legacy | legacy | ["diagnostic_output"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"final_published_material","level":"diagnostic","selector":"only HTML not matched by a recognized adapter"}] | varies | Diagnostic catch-all applies only after recognized nested, flat, and modular adapters; it does not declassify their files. |
| logs/newsroom_master.log | log | text/log | agents.master_log_v93_19 | Jarvis | runtime | runtime_log | bounded_history | bounded_rewrite | code_declared | active | ["diagnostic_output"] | {"mode":"bounded_count","max_items":300,"value_source":"runtime_configurable"} | [{"purpose":"pipeline_observability","level":"diagnostic"}] | none_unknown | Primary human log rebuilt atomically from the bounded master-log records; MAX_RUNS defaults to 300 via V93_MASTER_LOG_MAX_RUNS. |
| published/**/* | archive | html | legacy publication archive | Publisher | publication | published_material_archive | immutable_archive | immutable | documented_legacy | legacy | ["diagnostic_output"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"final_published_material","level":"legacy_context"}] | varies | Legacy published family requires a documented adapter before linguistic authority is claimed. |
| artifacts/newsroom/master_log_error.json | report | json | newsroom_runner | Jarvis | runtime | runtime_snapshot | current_snapshot | atomic_overwrite | code_declared | error_only | ["diagnostic_output"] | {"mode":"current_only","value_source":"fixed_contract"} | [{"purpose":"pipeline_observability","level":"diagnostic"}] | none_unknown | Error-only snapshot written by newsroom_runner.write_master_log_safe under ARTIFACT_DIR; not an ordinary run artifact. |
| state/newsroom/future_retained_source/** | archive | html | future Reform B retention | — | intake | runtime_state | immutable_archive | immutable | planned_canonical | planned | ["source_material"] | {"mode":"unknown_legacy","value_source":"unknown_legacy"} | [{"purpose":"source_material","level":"authoritative","selector":"explicit content_id provenance"}] | none_unknown | Illustrative future source-retention family linked by content_id; A3 creates no directory, file, retention, or producer. |

## Examples
The following JSON blocks are illustrative contract entries and are validated by the A3 validator; they create no runtime artifact.

### Bob current-run snapshot
```json
{"schema_version":"owtv_artifact_manifest_schema_v1","policy_version":"v95.22_a3","artifact_id":"example:instance:001","artifact_type":"snapshot","path":"artifacts/newsroom/bob_articles.json","storage_class":"runtime_snapshot","format":"json","producer_agent":"Bob","producer_stage":"generation","producer_component":"newsroom_runner","manifested_at_utc":"2026-08-13T12:00:00Z","artifact_created_at_utc":"2026-08-13T11:59:59Z","run_id":"run-42","semantic_roles":["translated_candidate"],"persistence_class":"current_snapshot","mutation_mode":"atomic_overwrite","retention_policy":{"mode":"current_only","value_source":"fixed_contract"},"authority_claims":[{"purpose":"translated_candidate_material","level":"supporting","selector":"articles[].body_html"}],"artifact_schema_version":{"status":"none_unknown"}}
```

### master_log bounded history
```json
{"schema_version":"owtv_artifact_manifest_schema_v1","policy_version":"v95.22_a3","artifact_id":"example:master:001","artifact_type":"memory","path":"state/newsroom/master_log.jsonl","storage_class":"runtime_state","format":"jsonl","producer_agent":"Jarvis","producer_stage":"runtime","producer_component":"agents.master_log_v93_19","manifested_at_utc":"2026-08-13T12:00:00Z","artifact_created_at_utc":"2026-08-13T11:59:59Z","run_id":"run-42","semantic_roles":["state_memory","audit"],"persistence_class":"bounded_history","mutation_mode":"bounded_rewrite","retention_policy":{"mode":"bounded_count","max_items":300,"value_source":"runtime_configurable"},"authority_claims":[{"purpose":"pipeline_observability","level":"authoritative","selector":"complete run records"}],"artifact_schema_version":{"status":"none_unknown"}}
```

### Gemini append-only ledger
```json
{"schema_version":"owtv_artifact_manifest_schema_v1","policy_version":"v95.22_a3","artifact_id":"example:gemini-ledger:001","artifact_type":"ledger","path":"state/newsroom/gemini_call_ledger.jsonl","storage_class":"runtime_state","format":"jsonl","producer_agent":"Gemini","producer_stage":"model","producer_component":"agents.gemini_ledger","manifested_at_utc":"2026-08-13T12:00:00Z","artifact_created_at_utc":"2026-08-13T11:59:59Z","run_id":"run-42","semantic_roles":["model_call_telemetry"],"persistence_class":"append_only_ledger","mutation_mode":"append_only","retention_policy":{"mode":"persistent","value_source":"code_default"},"authority_claims":[{"purpose":"model_usage_cost","level":"authoritative"}],"artifact_schema_version":{"status":"producer_version_only","version":"v2"}}
```

### Gemini latest snapshot
```json
{"schema_version":"owtv_artifact_manifest_schema_v1","policy_version":"v95.22_a3","artifact_id":"example:gemini-latest:001","artifact_type":"snapshot","path":"artifacts/newsroom/gemini_call_ledger_latest.json","storage_class":"runtime_snapshot","format":"json","producer_agent":"Gemini","producer_stage":"model","producer_component":"agents.gemini_ledger","manifested_at_utc":"2026-08-13T12:00:00Z","artifact_created_at_utc":"2026-08-13T11:59:59Z","run_id":"run-42","semantic_roles":["model_call_telemetry"],"persistence_class":"current_snapshot","mutation_mode":"atomic_overwrite","retention_policy":{"mode":"current_only","value_source":"fixed_contract"},"authority_claims":[{"purpose":"model_usage_cost","level":"supporting"}],"artifact_schema_version":{"status":"producer_version_only","version":"v2"}}
```

### Menzo duplicate pair coverage
```json
{"schema_version":"owtv_artifact_manifest_schema_v1","policy_version":"v95.22_a3","artifact_id":"example:pair-coverage:001","artifact_type":"coverage","path":"artifacts/newsroom/menzo_duplicate_pair_coverage.json","storage_class":"runtime_snapshot","format":"json","producer_agent":"Menzo","producer_stage":"duplicate","producer_component":"agents.menzo_policy_v93_15","manifested_at_utc":"2026-08-13T12:00:00Z","artifact_created_at_utc":"2026-08-13T11:59:59Z","run_id":"run-42","semantic_roles":["duplicate_evidence"],"persistence_class":"current_snapshot","mutation_mode":"atomic_overwrite","retention_policy":{"mode":"current_only","value_source":"fixed_contract"},"authority_claims":[{"purpose":"duplicate_decision","level":"authoritative","selector":"producing latest run only"}],"artifact_schema_version":{"status":"known","version":"owtv_duplicate_pair_coverage_v1"},"pair_id":"pair-1"}
```

### published_html_review verified final artifact
```json
{"schema_version":"owtv_artifact_manifest_schema_v1","policy_version":"v95.22_a3","artifact_id":"example:final:001","artifact_type":"archive","path":"published_html_review/run_1/item/final.html","storage_class":"published_material_archive","format":"html","producer_stage":"audit","producer_component":"scripts.translation_quality_audit documented adapter","manifested_at_utc":"2026-08-13T12:00:00Z","artifact_created_at_utc":"2026-08-13T11:59:59Z","run_id":"run-42","semantic_roles":["final_published_material"],"persistence_class":"immutable_archive","mutation_mode":"immutable","retention_policy":{"mode":"unknown_legacy","value_source":"unknown_legacy"},"authority_claims":[{"purpose":"final_published_material","level":"authoritative","selector":"documented verified adapter"}],"artifact_schema_version":{"status":"varies"},"content_id":"content-1"}
```

### review package source/candidate material
```json
{"schema_version":"owtv_artifact_manifest_schema_v1","policy_version":"v95.22_a3","artifact_id":"example:review:001","artifact_type":"archive","path":"review_packages/run_1/item/source.html","storage_class":"review_archive","format":"html","producer_stage":"quality","producer_component":"scripts.translation_quality_audit documented review-package adapter","manifested_at_utc":"2026-08-13T12:00:00Z","artifact_created_at_utc":"2026-08-13T11:59:59Z","run_id":"run-42","semantic_roles":["source_material","quality_review"],"persistence_class":"immutable_archive","mutation_mode":"immutable","retention_policy":{"mode":"unknown_legacy","value_source":"unknown_legacy"},"authority_claims":[{"purpose":"source_material","level":"supporting","selector":"source.html"}],"artifact_schema_version":{"status":"varies"},"content_id":"content-1"}
```

### future retained source artifact linked by content_id
```json
{"schema_version":"owtv_artifact_manifest_schema_v1","policy_version":"v95.22_a3","artifact_id":"example:source:001","artifact_type":"archive","path":"state/newsroom/future_retained_source/content-1/source.html","storage_class":"runtime_state","format":"html","producer_stage":"intake","producer_component":"future Reform B retention","manifested_at_utc":"2026-08-13T12:00:00Z","artifact_created_at_utc":"2026-08-13T11:59:59Z","run_id":"run-42","semantic_roles":["source_material"],"persistence_class":"immutable_archive","mutation_mode":"immutable","retention_policy":{"mode":"unknown_legacy","value_source":"unknown_legacy"},"authority_claims":[{"purpose":"source_material","level":"authoritative","selector":"explicit retained source"}],"artifact_schema_version":{"status":"none_unknown"},"content_id":"content-1","sha256":"0000000000000000000000000000000000000000000000000000000000000000","size_bytes":0}
```

## Null, missing and not applicable
Optional missing fields mean unavailable or not applicable. Empty strings are not substitutes. For `artifact_schema_version`, `known` requires a concrete artifact schema `version`; `producer_version_only` requires a producer/runtime version and explicitly does not claim an artifact schema; `none_unknown` and `varies` forbid `version`. A3 does not add schema versions to legacy producers.

## Scope guard
Contract, documentation, validator and tests only: no runtime writer, artifact index, state output, retention/storage change, source copying, agent change, report change, deploy, or editorial behavior change.
