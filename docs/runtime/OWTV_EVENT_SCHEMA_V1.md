# OWTV Canonical Event Schema v1 — v95.22 A2

## Purpose and scope

A2 is the **Phase 0, measurement-only** contract for future OpenWrestlingTV events. It exists to stop counts from confusing pipeline intentions, API attempts, outcomes, and legacy rows. It follows A1 Metrics Catalog v1: A1 defines what is measured; A2 defines the future event facts from which those measurements may be computed. A future Phase 1 may implement an append-only canonical ledger against this contract. This change neither creates that ledger nor changes any producer.

The production observation of roughly 26 `generate_translate_article` calls for one content item across runs motivates the identity split. It is not fixed here: the contract merely makes `logical_requests = 1` and `model_attempts = N` representable.

## Envelope

Every future event has the version literals `owtv_event_schema_v1` and `v95.22_a2`, an RFC 3339 UTC `timestamp_utc`, `run_id`, canonical `stage`, `agent`, `event_type`, `status`, and an `artifact_refs` array. The remaining envelope fields are optional or conditionally required. Optional means the key may be absent; JSON `null` is used only when the field type explicitly permits it. Producers must not invent an identity merely to fill a field.

`event_type` says **what happened**. `status` says lifecycle/outcome state. `result` is a normalized immediate output classification. `reason_code` says why or for which machine purpose. These namespaces are not interchangeable.

### Field presence

| Presence | Fields |
|---|---|
| required | schema_version, policy_version, timestamp_utc, run_id, stage, agent, event_type, status, artifact_refs |
| optional | article_id, pair_id, correlation_id, content_id, story_id, report_key, logical_request_id, attempt_id, attempt_number, result, reason_code, model_name, model_role, fallback_from, fallback_to, latency_ms, error_class, error_terminal, code_commit |
| conditional | Concrete attempt events require request/attempt/model identity; avoided events forbid concrete attempt identity; fallback events name both models; failures carry error classification and terminality. |

## Identity model

Identities describe different grains and are not universally required. `run_id` contains many future `correlation_id` values. A correlation links end-to-end events for one content/process; `content_id` identifies a stable source item; `story_id` may group several contents into one editorial story. A logical request contains one or more attempts when calls occur. Optional `article_id` supports candidate/duplicate migration toward `content_id`; `pair_id` identifies one scoped duplicate pair and is required for every `duplicate_pair_*` outcome. `report_key` identifies one Simone report.

`article_id` is already derived by runtime code from canonical source URL, but its *observed contract status* is existing runtime. `candidate_id` is only partial: the ledger field exists, while the sampled 800 rows were null. The planned identities are deliberately not presented as current runtime output.

<!-- SYNC:IDENTITIES run_id|article_id|operation_id|attempt_index|pair_id|report_key|event_key|cluster_id|source_id|candidate_id|correlation_id|content_id|story_id|logical_request_id|attempt_id -->

| Identity | Classification | Meaning |
|---|---|---|
| run_id | existing_runtime | Observed run identity; one run may contain many correlations. |
| article_id | existing_runtime | Stable SHA-256 identity derived by the duplicate subsystem from canonical source URL. |
| operation_id | existing_runtime | Per-call-site Gemini operation token, normally UUID-bearing; grouping stability across every retry/fallback is not guaranteed. It is not a synonym of logical_request_id. |
| attempt_index | legacy_only | Legacy Gemini zero-based attempt ordinal; canonical attempt_number = attempt_index + 1 only when the same logical operation grouping is established. |
| pair_id | existing_runtime | Scoped identity for a duplicate article pair. |
| report_key | existing_runtime | Simone report identity. |
| event_key | existing_partial | Observed Simone event/night key, not universally populated. |
| cluster_id | existing_partial | Observed cluster identity, not universally populated. |
| source_id | existing_partial | Observed only on part of the pipeline. |
| candidate_id | existing_partial | Field exists in the Gemini ledger but the production sample was null; not a reliably populated identity. |
| correlation_id | planned_canonical | Planned end-to-end process/content correlation within a run. |
| content_id | planned_canonical | Planned stable source/content item identity. |
| story_id | planned_canonical | Planned editorial story identity that may group several content_id values. |
| logical_request_id | planned_canonical | Planned ID for one pipeline intention; stable across all retries and fallbacks for that intention. |
| attempt_id | planned_canonical | Planned unique ID for exactly one concrete attempt. |

## Logical request versus attempt

`logical_request_id` identifies one pipeline intention and remains stable through retry, repair, and fallback belonging to that intention. It is **not regenerated per API call**. `attempt_id` is globally unique for one concrete model/API attempt. `attempt_number` is canonically **1-based** and increases within the logical request.

The legacy Gemini `attempt_index` is 0-based, so a mapping may use `attempt_number = attempt_index + 1`, but only after establishing that the rows belong to the same logical request. Current `operation_id` is passed by call sites or generated as `agent:phase:key:uuid`; it identifies a recorded Gemini operation/attempt context, but code does not guarantee the stable retry/fallback grouping required by `logical_request_id`. Therefore `operation_id` is never automatically its synonym. An avoided cache hit is a logical request outcome but no concrete SDK attempt: it has no `attempt_id`, `attempt_number`, or call latency.

## Stage taxonomy

Stages are stable semantic pipeline areas, not raw phases.

<!-- SYNC:STAGES runtime|intake|reporting|selection|duplicate|content_sufficiency|generation|quality|publication|audit|model -->

| Canonical stage |
|---|
| runtime |
| intake |
| reporting |
| selection |
| duplicate |
| content_sufficiency |
| generation |
| quality |
| publication |
| audit |
| model |

## Agent taxonomy

`Gemini` represents model-attempt events; the editorial caller remains available through the request event and identity.

<!-- SYNC:AGENTS Jarvis|Massy|Simone|Menzo|Andrea|Bob|Alfred|Publisher|Archivista|Gemini -->

| Canonical agent |
|---|
| Jarvis |
| Massy |
| Simone |
| Menzo |
| Andrea |
| Bob |
| Alfred |
| Publisher |
| Archivista |
| Gemini |

## Event type taxonomy

Each name has one meaning. Raw `phase` values are mapped separately and may need outcome context. Generic `stage_started`, `stage_completed`, and `stage_failed` accept every canonical stage so the event retains its real pipeline area; they are not forced into `runtime`.

<!-- SYNC:EVENT_TYPES run_started|run_completed|stage_started|stage_completed|stage_failed|candidate_seen|candidate_selected|candidate_pending|candidate_skipped|duplicate_check_requested|duplicate_pair_evaluated|duplicate_pair_resolved|duplicate_pair_unresolved|logical_ai_request_created|model_attempt_started|model_attempt_completed|model_attempt_failed|model_attempt_avoided|fallback_started|repair_started|article_generation_requested|article_generated|revision_requested|revision_completed|report_candidate_seen|report_selected|report_published|publication_attempted|publication_completed|publication_failed|publication_already_present|content_sufficiency_checked|quality_review_completed|audit_completed|warning_recorded|blocker_recorded -->

| Event type | Default stage | Allowed agents |
|---|---|---|
| run_started | runtime | Jarvis |
| run_completed | runtime | Jarvis |
| stage_started | any canonical stage | Jarvis, Massy, Simone, Menzo, Andrea, Bob, Alfred, Publisher, Archivista, Gemini |
| stage_completed | any canonical stage | Jarvis, Massy, Simone, Menzo, Andrea, Bob, Alfred, Publisher, Archivista, Gemini |
| stage_failed | any canonical stage | Jarvis, Massy, Simone, Menzo, Andrea, Bob, Alfred, Publisher, Archivista, Gemini |
| candidate_seen | intake | Massy |
| candidate_selected | selection | Menzo |
| candidate_pending | selection | Menzo |
| candidate_skipped | selection | Massy, Menzo, Andrea |
| duplicate_check_requested | duplicate | Menzo |
| duplicate_pair_evaluated | duplicate | Menzo |
| duplicate_pair_resolved | duplicate | Menzo |
| duplicate_pair_unresolved | duplicate | Menzo |
| logical_ai_request_created | model | Menzo, Bob, Alfred, Simone, Gemini |
| model_attempt_started | model | Gemini |
| model_attempt_completed | model | Gemini |
| model_attempt_failed | model | Gemini |
| model_attempt_avoided | model | Gemini |
| fallback_started | model | Gemini |
| repair_started | model | Gemini |
| article_generation_requested | generation | Bob |
| article_generated | generation | Bob |
| revision_requested | quality | Alfred |
| revision_completed | quality | Bob, Alfred |
| report_candidate_seen | reporting | Simone |
| report_selected | reporting | Simone |
| report_published | reporting | Simone, Publisher |
| publication_attempted | publication | Publisher |
| publication_completed | publication | Publisher |
| publication_failed | publication | Publisher |
| publication_already_present | publication | Publisher |
| content_sufficiency_checked | content_sufficiency | Andrea |
| quality_review_completed | quality | Alfred |
| audit_completed | audit | Archivista |
| warning_recorded | audit | Alfred, Archivista, Jarvis |
| blocker_recorded | audit | Alfred, Archivista |

## Status, result, and reason

Canonical statuses are `started`, `success`, `failed`, `avoided`, `pending`, and `skipped`. For example, a successful arbitration call is `event_type=model_attempt_completed`, `status=success`, `result=valid_json`, `reason_code=ai_duplicate_arbitration`. A cache hit is `model_attempt_avoided`, `status=avoided`, `result=duplicate_recent_cache_hit`, with the same reason code. Legacy `called` makes the status mapping partial and is not copied as a canonical status: it is interpreted into a started/completed/failed event using available outcome evidence. The legacy result mapping is also partial: free-form provider failures such as `503 UNAVAILABLE high demand` require normalization and cannot be copied into the normalized canonical result namespace.

## Error contract

`error_class` classifies the failure domain. `error_terminal` is `true` when no later attempt in the logical request is expected, `false` when retry/fallback may continue, and `null` only when terminality is unknown or no error classification applies. Non-error events do not require `error_class`.

<!-- SYNC:ERROR_CLASSES transient|permanent|validation|upstream|downstream|invariant|policy -->

| Error class |
|---|
| transient |
| permanent |
| validation |
| upstream |
| downstream |
| invariant |
| policy |

## Model contract

`model_name` is the effective model where known. `model_role` records the semantic job independently of routing. `fallback_from`/`fallback_to` describe a transition within one logical request. `latency_ms` is non-negative elapsed milliseconds for a concrete attempt, not cache lookup latency. A2 changes no model selection or fallback behavior.

<!-- SYNC:MODEL_ROLES selection|duplicate_arbitration|translation_generation|report_translation|quote_resolution|quality_review -->

| Model role |
|---|
| selection |
| duplicate_arbitration |
| translation_generation |
| report_translation |
| quote_resolution |
| quality_review |

## Artifact references

`artifact_refs` is an array of objects. Every item has repository/runtime-relative `path` and `relation` (`input`, `output`, or `evidence`); it may add `artifact_type`, `schema_version`, and SHA-256 `sha256`. It links an event without embedding artifact content. An empty array is valid. This is not Artifact Manifest v1 and does not add schema versions to existing artifacts.

## Legacy mappings

Mapping kinds mean: **exact** copies compatible meaning; **derived** requires a deterministic conversion; **partial** requires contextual normalization; **no canonical equivalent** is retained only as legacy/context; **planned future field** has no current producer. No producer changes in A2.

### Source-aware observed master/Gemini phase mapping

<!-- SYNC:LEGACY_PHASES master_log.timeline:Jarvis:bootstrap_status_written|master_log.timeline:Massy:sentinel_board_ready|master_log.timeline:Massy:forced_policy_active|master_log.timeline:Simone:report_decision_ready|master_log.timeline:Simone:report_publication_ready|master_log.timeline:Menzo:editorial_decision_ready|master_log.timeline:Menzo:forced_policy_active|master_log.timeline:Andrea:pre_bob_content_sufficiency_ready|master_log.timeline:Bob:article_packages_ready|master_log.timeline:Bob:bob_brief_guard_applied|master_log.timeline:Alfred:quality_review_ready|master_log.timeline:Alfred:bob_warning_guard_applied|master_log.timeline:Publisher:publication_ready|master_log.timeline:Jarvis:runtime_skipped|master_log.timeline:Archivista:audit_ready|gemini_call_ledger:Menzo:duplicate_arbitration|gemini_call_ledger:Menzo:duplicate_arbitration_same_run_batch|gemini_call_ledger:Menzo:duplicate_arbitration_recent_history_batch|gemini_call_ledger:Menzo:duplicate_arbitration_recent_history_repair|gemini_call_ledger:Bob:translate_article|gemini_call_ledger:Bob:report_blocks_legacy_prompt|gemini_call_ledger:Alfred:quote_resolver|gemini_call_ledger:Alfred:quote_ambiguity_resolver -->

| Source | Legacy agent | Legacy phase | Canonical agent | Future event type | Stage | Kind | Constraint |
|---|---|---|---|---|---|---|---|
| master_log.timeline | Jarvis | bootstrap_status_written | Jarvis | stage_completed | runtime | partial | Artifact write indicates orchestration completion in runtime. |
| master_log.timeline | Massy | sentinel_board_ready | Massy | stage_completed | intake | partial | Ready phase indicates intake stage completion, subject to timeline context. |
| master_log.timeline | Massy | forced_policy_active | Massy | stage_completed | intake | partial | Policy was applied; it does not imply a warning. |
| master_log.timeline | Simone | report_decision_ready | Simone | stage_completed | reporting | partial | Decision stage is ready; it does not prove that a report was selected. |
| master_log.timeline | Simone | report_publication_ready | Simone | stage_completed | reporting | partial | Publication handoff readiness is a stage lifecycle signal, not publication success. |
| master_log.timeline | Menzo | editorial_decision_ready | Menzo | stage_completed | selection | partial | Selection decision stage completed; item outcome remains in artifacts. |
| master_log.timeline | Menzo | forced_policy_active | Menzo | stage_completed | selection | partial | Policy was applied; it does not imply a warning. |
| master_log.timeline | Andrea | pre_bob_content_sufficiency_ready | Andrea | content_sufficiency_checked | content_sufficiency | partial | Ready artifact supports a check; item result needs artifact context. |
| master_log.timeline | Bob | article_packages_ready | Bob | article_generated | generation | partial | Packages may contain zero or more generated articles; inspect artifact context. |
| master_log.timeline | Bob | bob_brief_guard_applied | Bob | stage_completed | generation | partial | Guard application is a lifecycle signal and does not imply a warning. |
| master_log.timeline | Alfred | quality_review_ready | Alfred | quality_review_completed | quality | partial | Review readiness maps after inspecting review outcomes. |
| master_log.timeline | Alfred | bob_warning_guard_applied | Alfred | stage_completed | quality | partial | Guard application does not imply that a warning exists. |
| master_log.timeline | Publisher | publication_ready | Publisher | stage_completed | publication | partial | Publisher stage completion does not itself prove publication. |
| master_log.timeline | Jarvis | runtime_skipped | Jarvis | stage_completed | runtime | partial | Runtime lifecycle ended as skipped; status normalization supplies skipped. |
| master_log.timeline | Archivista | audit_ready | Archivista | audit_completed | audit | partial | Audit artifact readiness supports completion with artifact context. |
| gemini_call_ledger | Menzo | duplicate_arbitration | Gemini | model_attempt_completed | model | partial | Observed raw caller; status/result evidence selects completed, failed, or avoided. |
| gemini_call_ledger | Menzo | duplicate_arbitration_same_run_batch | Gemini | model_attempt_completed | model | partial | Observed raw caller; status/result evidence selects completed, failed, or avoided. |
| gemini_call_ledger | Menzo | duplicate_arbitration_recent_history_batch | Gemini | model_attempt_completed | model | partial | Observed raw caller; status/result evidence selects completed, failed, or avoided. |
| gemini_call_ledger | Menzo | duplicate_arbitration_recent_history_repair | Gemini | repair_started | model | partial | Repair flag/phase identifies repair; attempt outcome requires its ledger row. |
| gemini_call_ledger | Bob | translate_article | Gemini | model_attempt_completed | model | partial | Observed raw caller; called/failed and result evidence determine canonical attempt event. |
| gemini_call_ledger | Bob | report_blocks_legacy_prompt | Gemini | model_attempt_completed | model | partial | Report workshop records agent Bob; outcome evidence determines canonical attempt event. |
| gemini_call_ledger | Alfred | quote_resolver | Gemini | model_attempt_completed | model | partial | Observed raw caller; outcome evidence determines canonical attempt event. |
| gemini_call_ledger | Alfred | quote_ambiguity_resolver | Gemini | model_attempt_avoided | model | partial | Observed history-hit avoided row; verify status before mapping to avoided. |

### Field mapping inventory

| Source | Legacy field | Canonical field | Kind | Constraint |
|---|---|---|---|---|
| gemini_call_ledger | run_id | run_id | exact |  |
| gemini_call_ledger | agent | agent | partial | Raw agent is the editorial caller (Menzo, Bob, or Alfred); future model attempts use canonical agent Gemini. |
| gemini_call_ledger | status | status | partial | Legacy 'called' is not canonical: normalize with result/error evidence to started, success, or failed; avoided/failed still require event context. |
| gemini_call_ledger | result | result | partial | Normalize known classifications; free-form provider/error text such as 503 UNAVAILABLE high demand is not copied as a canonical result. |
| gemini_call_ledger | reason | reason_code | exact |  |
| gemini_call_ledger | phase | event_type | partial | Requires phase table and outcome context. |
| gemini_call_ledger | operation_id | logical_request_id | partial | Use only after proving stable grouping; never automatic equivalence. |
| gemini_call_ledger | attempt_index | attempt_number | derived | Zero-based legacy index plus one, conditional on valid request grouping. |
| gemini_call_ledger | model | model_name | partial | Precedence depends on requested-versus-actual analysis. |
| gemini_call_ledger | model_requested | model_name | partial | Precedence depends on requested-versus-actual analysis. |
| gemini_call_ledger | actual_model | model_name | partial | Precedence depends on requested-versus-actual analysis. |
| master_log.timeline | agent | agent | exact |  |
| master_log.timeline | phase | event_type | partial | Map raw phase using legacy_phase_mappings. |
| duplicate_subsystem | article_id | article_id | exact | Observed identity is available in the optional canonical envelope. |
| duplicate_subsystem | pair_id | pair_id | exact | Observed identity is available in the optional canonical envelope. |
| duplicate_subsystem | left_article_id | — | no_canonical_equivalent | Retained as identity/context metadata until envelope extension. |
| duplicate_subsystem | right_article_id | — | no_canonical_equivalent | Retained as identity/context metadata until envelope extension. |
| duplicate_subsystem | scope | result | partial | Requires field-specific normalization; do not copy blindly. |
| duplicate_subsystem | final_disposition | result | partial | Requires field-specific normalization; do not copy blindly. |
| duplicate_subsystem | gemini_decision | result | partial | Requires field-specific normalization; do not copy blindly. |
| duplicate_subsystem | cache_status | result | partial | Requires field-specific normalization; do not copy blindly. |
| simone | report_key | report_key | exact |  |
| simone | report_id | — | no_canonical_equivalent | Legacy context identity; no envelope field in v1. |
| simone | event_key | — | no_canonical_equivalent | Legacy context identity; no envelope field in v1. |
| simone | night_key | — | no_canonical_equivalent | Legacy context identity; no envelope field in v1. |
| publisher | source_url | — | no_canonical_equivalent | May be represented by artifact metadata in a future contract, not artifact content. |
| publisher | wp_link | — | no_canonical_equivalent | May be represented by artifact metadata in a future contract, not artifact content. |
| publisher | wp_post_id | — | no_canonical_equivalent | May be represented by artifact metadata in a future contract, not artifact content. |
| future_canonical_ledger | correlation_id | correlation_id | planned_future_field |  |
| future_canonical_ledger | content_id | content_id | planned_future_field |  |
| future_canonical_ledger | story_id | story_id | planned_future_field |  |
| future_canonical_ledger | logical_request_id | logical_request_id | planned_future_field |  |
| future_canonical_ledger | attempt_id | attempt_id | planned_future_field |  |

The duplicate subsystem's `article_id` and `pair_id` map exactly into optional envelope identities (`pair_id` conditionally required for pair outcomes); `left_article_id`, `right_article_id`, `scope`, `final_disposition`, `gemini_decision`, and `cache_status` remain visible in the inventory even when v1 has no envelope slot. Simone's `report_key`, `report_id`, `event_key`/`night_key`, and Publisher's `source_url`, `wp_link`, `wp_post_id` are likewise classified rather than silently promoted.

## Null, zero, and non-applicable

Absent means not captured or not applicable. `null` never means zero. Numeric zero is authoritative (for example `latency_ms=0` if genuinely measured); an empty `artifact_refs` means there are no references, not unknown contents. Avoided calls have no attempt ordinal/latency because no attempt occurred. `error_terminal=null` means unknown/non-applicable, while `false` means explicitly non-terminal.

## Contractual examples

These are illustrative future ledger records; runtime emits none in A2. For compactness, optional absent keys are omitted.

### A. Menzo candidate decision
```json
{"schema_version":"owtv_event_schema_v1","policy_version":"v95.22_a2","timestamp_utc":"2026-08-13T10:00:00Z","run_id":"run-42","correlation_id":"corr-article-a","content_id":"content-a","stage":"selection","agent":"Menzo","event_type":"candidate_selected","status":"success","result":"selected","reason_code":"editorial_policy_passed","artifact_refs":[{"path":"artifacts/newsroom/menzo_decisions.json","relation":"output"}],"code_commit":"23a1a515"}
```

### B. Gemini duplicate arbitration call
```json
{"schema_version":"owtv_event_schema_v1","policy_version":"v95.22_a2","timestamp_utc":"2026-08-13T10:01:00Z","run_id":"run-42","correlation_id":"corr-article-a","logical_request_id":"lr-dup-1","attempt_id":"attempt-dup-1","stage":"model","agent":"Gemini","event_type":"model_attempt_completed","attempt_number":1,"status":"success","result":"valid_json","reason_code":"ai_duplicate_arbitration","model_name":"gemini-example","model_role":"duplicate_arbitration","latency_ms":421,"artifact_refs":[]}
```

### C. Gemini avoided cache hit
```json
{"schema_version":"owtv_event_schema_v1","policy_version":"v95.22_a2","timestamp_utc":"2026-08-13T10:01:10Z","run_id":"run-42","logical_request_id":"lr-dup-2","stage":"model","agent":"Gemini","event_type":"model_attempt_avoided","status":"avoided","result":"duplicate_recent_cache_hit","reason_code":"ai_duplicate_arbitration","model_role":"duplicate_arbitration","artifact_refs":[{"path":"state/newsroom/menzo_duplicate_arbitration_cache_v2.json","relation":"evidence"}]}
```

### D. Bob request with two model attempts
```json
[
  {"schema_version":"owtv_event_schema_v1","policy_version":"v95.22_a2","timestamp_utc":"2026-08-13T10:02:00Z","run_id":"run-42","content_id":"content-a","logical_request_id":"lr-bob-1","stage":"model","agent":"Bob","event_type":"logical_ai_request_created","status":"started","reason_code":"generate_translate_article","model_role":"translation_generation","artifact_refs":[]},
  {"schema_version":"owtv_event_schema_v1","policy_version":"v95.22_a2","timestamp_utc":"2026-08-13T10:02:01Z","run_id":"run-42","logical_request_id":"lr-bob-1","attempt_id":"attempt-bob-1","stage":"model","agent":"Gemini","event_type":"model_attempt_failed","attempt_number":1,"status":"failed","result":"unavailable","reason_code":"generate_translate_article","model_name":"primary-example","model_role":"translation_generation","latency_ms":800,"error_class":"transient","error_terminal":false,"artifact_refs":[]},
  {"schema_version":"owtv_event_schema_v1","policy_version":"v95.22_a2","timestamp_utc":"2026-08-13T10:02:02Z","run_id":"run-42","logical_request_id":"lr-bob-1","attempt_id":"attempt-bob-2","stage":"model","agent":"Gemini","event_type":"model_attempt_completed","attempt_number":2,"status":"success","result":"text","reason_code":"generate_translate_article","model_name":"fallback-example","model_role":"translation_generation","fallback_from":"primary-example","fallback_to":"fallback-example","latency_ms":650,"artifact_refs":[]}
]
```
One logical request and two concrete attempts are countable without treating the two calls as two editorial intentions.

### E. Publisher publication completed
```json
{"schema_version":"owtv_event_schema_v1","policy_version":"v95.22_a2","timestamp_utc":"2026-08-13T10:03:00Z","run_id":"run-42","content_id":"content-a","stage":"publication","agent":"Publisher","event_type":"publication_completed","status":"success","result":"published","reason_code":"wordpress_create_succeeded","artifact_refs":[{"path":"artifacts/newsroom/publisher_result.json","relation":"output"}]}
```

### F. Simone report publication
```json
{"schema_version":"owtv_event_schema_v1","policy_version":"v95.22_a2","timestamp_utc":"2026-08-13T10:04:00Z","run_id":"run-42","report_key":"raw-2026-08-13","stage":"reporting","agent":"Simone","event_type":"report_published","status":"success","result":"published","reason_code":"report_publication","artifact_refs":[{"path":"artifacts/newsroom/simone_report_publish.json","relation":"output"}]}
```

## Future Reform D regression notes

These are corpus notes only; A2 changes no dedupe behavior.

* **D-DUP-001 — Jim Ross, SAME_STORY / DUPLICATE.** Ringside News, “Jim Ross Reveals Doctors Will Drill Hole in His Skull During Brain Surgery” (`https://www.ringsidenews.com/jim-ross-reveals-doctors-will-drill-hole-his-skull-during-brain-surgery/`) and WrestlingInc, “Jim Ross Explains Upcoming Brain Surgery, Thanks Fans For Support” (`https://www.wrestlinginc.com/2235088/aew-jim-ross-brain-surgery-thanks-fan-support/`). Observed OWTV outputs were “Jim Ross rivela i dettagli del suo intervento al cervello” and “Jim Ross spiega il prossimo intervento chirurgico al cervello e ringrazia i fan”. Same subject, procedure, temporal update, and core fact; thanks alone is not a material update.
* **D-DUP-002 — The Rock, SAME_STORY / DUPLICATE.** Preserve the observed cross-source pair about The Rock's possible country-music career.
* **D-NODUP-001 — Randy Orton, distinct story / must not false-block.** Candidate “Randy Orton Confirmed for First Appearance After Taking Out Cody Rhodes at SummerSlam” had terminal Gemini `NO_MATCH` decisions but ended `skip:duplicate_arbitration_unresolved`. Future coverage logic must not turn terminal NO_MATCH pairs into a false candidate block.

## Scope guard

A2 is contract/documentation/validator/tests only. It emits no events, creates no canonical runtime ledger or artifact manifest, changes no newsroom agent, scoring, thresholds, softpool, dedupe/novelty, prompts, model routing, retry/fallback, WordPress publication, or editorial behavior. It does not fix the Bob cost anomaly or duplicate cases. **No runtime deploy is required.**
