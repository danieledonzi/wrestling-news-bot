# OWTV P1.3 common operational event semantics

**Implementation:** `v95.25_p1_3_operational_event_semantics`. **Baseline:** `724427e8036315abc00a498d67532604a420b466`.

P1.3 is fail-open measurement only. It begins at deployment cutover: neither canonical nor Gemini JSONL history is rewritten or backfilled. `operation_id` remains legacy diagnostic evidence and is never a canonical logical-request identity; historical `attempt_index` is likewise not promoted.

## Active production model inventory and roles

| Owner / active boundary reachable from `newsroom_runner` | Purpose | A2 role |
|---|---|---|
| Bob, `agents.bob.call_gemini` | article block translation/generation | `translation_generation` |
| Menzo, `agents.menzo_policy_v93_15.call_gemini_json_model` | batch, micro, novelty, fallback and structured-output duplicate arbitration | `duplicate_arbitration` |

Simone's active report director/publisher contains no Gemini provider call or Gemini-ledger writer at this baseline, so P1.3 does not fabricate report-translation requests. Alfred's active path similarly has no provider call. Archived modules are unsupported and untouched.

## Identity and lifecycle

One intention generates `lrq_` plus UUID4 hex once. Each concrete provider invocation generates a new `att_` plus UUID4 hex immediately before the call. Its ordinal is 1-based and increments once per external invocation. Retry, fallback, and model repair reuse the request object. Fallback emits `fallback_started`; actual AI structured-output repair emits `repair_started`. Avoidance emits a request plus `model_attempt_avoided` and never attempt identity or latency.

Menzo batch attempts defer canonical completion until the existing same-run or recent-history domain validator accepts the response. A rejected batch is a nonterminal validation failure when its existing repair follows; the repair reuses the request and is terminal if rejected. Per-item micro arbitration after the batch mechanism fails remains a separate logical intention. A real `duplicate_failure_cooldown` gate creates one avoided request, while snapshot/cache saved-call replay remains legacy accounting only and creates none.

A completion after an earlier nonterminal failure is *derived* recovery; there is no recovery event. A failure is terminal only when current control flow has no later retry/fallback/repair. It says nothing about a future newsroom run.

## Stable classifications

| Existing evidence | `error_class` |
|---|---|
| cooldown/known availability failure | `transient` |
| other provider failure | `upstream` |
| empty/invalid structured model output | `validation` |
| Publisher/Simone WordPress or preflight failure | `downstream` |
| missing required publication input | `validation` |

Raw exception text stays in the legacy Gemini ledger only.

## Occurrence and publication normalization

Every entry in Alfred's `warnings` produces a `warning_recorded`; repeated codes are retained. Separately, only an entry in `issues` whose actual severity is `blocker` produces `blocker_recorded`. A blocker issue is not also a warning unless it independently occurs in `warnings`. Both use source-derived P1.1 content/correlation identity, code as `reason_code`, and severity as `result`.

| Publisher item status | Canonical outcome |
|---|---|
| `published` | attempted + completed |
| `already_published` | already present; non-error |
| `dry_run` | non-error, no write attempt |
| `publish_error` | attempted + downstream terminal failure |
| `wp_not_ready` | downstream terminal stage failure; no write attempt |
| `missing_url_or_title` | validation terminal stage failure; no write attempt |
| duplicate/capacity/safety skip | no failure |

| Simone item evidence | Canonical outcome |
|---|---|
| `published` | `report_published` |
| `already_published`, `dry_run`, waiting/skipped | non-error |
| item `wp_not_ready` / `publish_error` | downstream failure |
| aggregate `errors` only | no canonical failure |

The legacy Gemini ledger, token extraction, pricing, costs, call count and provider-version evidence are unchanged. Canonical additions use the runner-installed writer, so its summary remains authoritative. Emission and identity failures are swallowed at telemetry boundaries and never alter provider exceptions or operational outcomes.

## Validator

`scripts/validate_canonical_operational_semantics.py` uses `lrq_` identity as the explicit P1.3-native rule. It reports request success/first/recovered/terminal/avoided totals, attempt lifecycle and terminality, fallback/repair totals, model and role dimensions, warning/blocker occurrence and distinct-article dimensions, Publisher and Simone outcomes, and invariant/identity/lifecycle errors. Rows without a P1.3 identity remain historical and are not subjected to lifecycle completeness.
