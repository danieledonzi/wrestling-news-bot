#!/usr/bin/env python3
"""Validate the OWTV Canonical Event Schema v1 (Python 3.9 stdlib only)."""
import argparse
import json
import re
import sys
from pathlib import Path

EXPECTED_SCHEMA = "owtv_event_schema_v1"
EXPECTED_POLICY = "v95.22_a2"
FIELD_TYPES = {"string", "integer", "boolean_or_null", "array"}
PRESENCE = {"required", "optional"}
MAPPING_KINDS = {"exact", "derived", "partial", "no_canonical_equivalent", "planned_future_field"}
REQUIRED_ENVELOPE_FIELDS = {
    "schema_version", "policy_version", "timestamp_utc", "run_id", "correlation_id",
    "content_id", "story_id", "report_key", "logical_request_id", "attempt_id", "stage",
    "agent", "event_type", "attempt_number", "status", "result", "reason_code",
    "model_name", "model_role", "fallback_from", "fallback_to", "latency_ms",
    "error_class", "error_terminal", "artifact_refs", "code_commit",
}
REQUIRED_STAGES = {"runtime", "intake", "reporting", "selection", "duplicate", "content_sufficiency", "generation", "quality", "publication", "audit", "model"}
REQUIRED_AGENTS = {"Jarvis", "Massy", "Simone", "Menzo", "Andrea", "Bob", "Alfred", "Publisher", "Archivista", "Gemini"}
REQUIRED_IDENTITIES = {"run_id", "article_id", "operation_id", "attempt_index", "pair_id", "report_key", "event_key", "cluster_id", "source_id", "candidate_id", "correlation_id", "content_id", "story_id", "logical_request_id", "attempt_id"}
REQUIRED_MODEL_ROLES = {"selection", "duplicate_arbitration", "translation_generation", "report_translation", "quote_resolution", "quality_review"}
REQUIRED_ERROR_CLASSES = {"transient", "permanent", "validation", "upstream", "downstream", "invariant", "policy"}


def unique(values, label, errors):
    if len(values) != len(set(values)):
        errors.append("%s values must be unique" % label)


def validate(data, markdown=None):
    errors = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"]
    if data.get("schema_version") != EXPECTED_SCHEMA:
        errors.append("schema_version must be %s" % EXPECTED_SCHEMA)
    if data.get("policy_version") != EXPECTED_POLICY:
        errors.append("policy_version must be %s" % EXPECTED_POLICY)
    if data.get("contract_scope") != "measurement_only_no_runtime_emission":
        errors.append("contract_scope must preserve the measurement-only boundary")

    envelope = data.get("envelope")
    if not isinstance(envelope, dict):
        errors.append("envelope must be an object")
        envelope = {}
    field_rows = envelope.get("fields") if isinstance(envelope.get("fields"), list) else []
    fields = [row.get("name") for row in field_rows if isinstance(row, dict)]
    unique(fields, "envelope field", errors)
    missing = REQUIRED_ENVELOPE_FIELDS - set(fields)
    if missing:
        errors.append("missing required contract field(s): %s" % ", ".join(sorted(missing)))
    for row in field_rows:
        if not isinstance(row, dict) or set(row) != {"name", "type", "presence"}:
            errors.append("each envelope field requires exactly name/type/presence")
            continue
        if row["type"] not in FIELD_TYPES or row["presence"] not in PRESENCE:
            errors.append("invalid envelope type/presence for %s" % row.get("name"))
    required = envelope.get("required_fields", [])
    optional = envelope.get("optional_fields", [])
    if set(required) | set(optional) != set(fields) or set(required) & set(optional):
        errors.append("required_fields and optional_fields must partition envelope fields")
    expected_required = {r["name"] for r in field_rows if isinstance(r, dict) and r.get("presence") == "required"}
    if set(required) != expected_required:
        errors.append("required_fields must match field presence declarations")

    stages = data.get("stages") if isinstance(data.get("stages"), list) else []
    agents = data.get("agents") if isinstance(data.get("agents"), list) else []
    unique(stages, "stage", errors); unique(agents, "agent", errors)
    if not REQUIRED_STAGES <= set(stages): errors.append("stage taxonomy is missing required stages")
    if not REQUIRED_AGENTS <= set(agents): errors.append("agent taxonomy is missing required agents")
    event_rows = data.get("event_types") if isinstance(data.get("event_types"), list) else []
    event_names = [r.get("name") for r in event_rows if isinstance(r, dict)]
    unique(event_names, "event_type", errors)
    for row in event_rows:
        if not isinstance(row, dict) or not {"name", "agents", "description"} <= set(row):
            errors.append("every event_type requires name/agents/description"); continue
        has_stage, has_allowed = "stage" in row, "allowed_stages" in row
        if has_stage == has_allowed:
            errors.append("event_type %s must define exactly one of stage or allowed_stages" % row["name"])
        elif has_stage and row["stage"] not in stages:
            errors.append("invalid stage %r for event_type %s" % (row["stage"], row["name"]))
        elif has_allowed:
            if not isinstance(row["allowed_stages"], list) or not row["allowed_stages"] or len(row["allowed_stages"]) != len(set(row["allowed_stages"])):
                errors.append("invalid allowed_stages for event_type %s" % row["name"])
            elif any(stage not in stages for stage in row["allowed_stages"]):
                errors.append("invalid stage in allowed_stages for event_type %s" % row["name"])
        if not isinstance(row["agents"], list) or not row["agents"]: errors.append("event_type %s requires agents" % row["name"])
        else:
            for agent in row["agents"]:
                if agent not in agents: errors.append("invalid agent %r for event_type %s" % (agent, row["name"]))

    conditions = envelope.get("conditional_requirements")
    if not isinstance(conditions, list) or not conditions:
        errors.append("conditional_requirements must be a non-empty list")
    else:
        ids = []
        for condition in conditions:
            if not isinstance(condition, dict) or not {"id", "when_event_types", "require", "rule"} <= set(condition):
                errors.append("malformed conditional requirement"); continue
            ids.append(condition["id"])
            if not condition["when_event_types"] or not isinstance(condition["require"], list): errors.append("malformed conditional requirement %s" % condition["id"])
            for name in condition["when_event_types"]:
                if name not in event_names: errors.append("conditional requirement %s references unknown event_type %s" % (condition["id"], name))
            for name in condition["require"] + condition.get("forbid", []):
                if name not in fields: errors.append("conditional requirement %s references unknown field %s" % (condition["id"], name))
        unique(ids, "conditional requirement id", errors)
        condition_map = {x.get("id"): x for x in conditions if isinstance(x, dict)}
        pair_rule = condition_map.get("duplicate_pair_identity", {})
        if set(pair_rule.get("when_event_types", [])) != {"duplicate_pair_evaluated", "duplicate_pair_resolved", "duplicate_pair_unresolved"} or "pair_id" not in pair_rule.get("require", []):
            errors.append("duplicate_pair_* events must conditionally require pair_id")
    for lifecycle in ("stage_started", "stage_completed", "stage_failed"):
        row = next((x for x in event_rows if isinstance(x, dict) and x.get("name") == lifecycle), {})
        if set(row.get("allowed_stages", [])) != set(stages):
            errors.append("generic lifecycle event %s must preserve every canonical pipeline stage" % lifecycle)

    identities = data.get("identities") if isinstance(data.get("identities"), dict) else {}
    allowed = identities.get("allowed_classifications", [])
    if set(allowed) != {"existing_runtime", "existing_partial", "planned_canonical", "derived", "legacy_only"}:
        errors.append("identity classifications must equal the canonical classification enum")
    identity_rows = identities.get("fields") if isinstance(identities.get("fields"), list) else []
    identity_names = [r.get("name") for r in identity_rows if isinstance(r, dict)]
    unique(identity_names, "identity", errors)
    if not REQUIRED_IDENTITIES <= set(identity_names): errors.append("identity contract is missing required identities")
    identity_map = {}
    for row in identity_rows:
        if not isinstance(row, dict) or not {"name", "classification", "description"} <= set(row): errors.append("malformed identity entry"); continue
        identity_map[row["name"]] = row["classification"]
        if row["classification"] not in allowed: errors.append("invalid identity classification for %s" % row["name"])
    for name in ("content_id", "correlation_id", "story_id"):
        if identity_map.get(name) != "planned_canonical": errors.append("%s must remain planned_canonical in A2" % name)
    if identity_map.get("run_id") != "existing_runtime" or identity_map.get("article_id") != "existing_runtime": errors.append("run_id and article_id must be existing_runtime")
    if identity_map.get("candidate_id") == "existing_runtime": errors.append("candidate_id is not reliably populated")

    attempt = data.get("attempt_contract") if isinstance(data.get("attempt_contract"), dict) else {}
    expected_attempt = {"logical_request_id_stable_across_retry_and_fallback": True, "attempt_id_unique_per_concrete_attempt": True, "attempt_number_base": 1, "legacy_attempt_index_base": 0, "operation_id_equivalent_to_logical_request_id": False, "avoided_is_concrete_attempt": False}
    for key, value in expected_attempt.items():
        if attempt.get(key) != value: errors.append("invalid logical request / attempt semantic: %s" % key)
    if "attempt_index + 1" not in str(attempt.get("legacy_conversion", "")): errors.append("legacy attempt conversion must explicitly add one")

    outcome = data.get("outcome_contract") if isinstance(data.get("outcome_contract"), dict) else {}
    statuses = outcome.get("status_values", [])
    unique(statuses, "status", errors)
    if not {"started", "success", "failed", "avoided", "pending", "skipped"} <= set(statuses) or outcome.get("namespaces_disjoint") is not True:
        errors.append("invalid status/result/reason taxonomy")
    if set(statuses) & set(event_names): errors.append("event_type and status namespaces must be disjoint")
    if not outcome.get("result_semantics") or not outcome.get("reason_code_semantics"): errors.append("result and reason_code semantics are required")

    error = data.get("error_contract") if isinstance(data.get("error_contract"), dict) else {}
    if set(error.get("classes", [])) != REQUIRED_ERROR_CLASSES or error.get("terminal_type") != "boolean_or_null" or error.get("non_error_requires_error_class") is not False:
        errors.append("invalid error contract")
    model = data.get("model_contract") if isinstance(data.get("model_contract"), dict) else {}
    if not REQUIRED_MODEL_ROLES <= set(model.get("roles", [])) or model.get("fallback_same_logical_request") is not True:
        errors.append("invalid model_role contract")
    artifact = data.get("artifact_refs_contract") if isinstance(data.get("artifact_refs_contract"), dict) else {}
    if artifact.get("type") != "array" or artifact.get("item_type") != "object" or set(artifact.get("required_item_fields", [])) != {"path", "relation"} or artifact.get("embed_content") is not False or not {"input", "output", "evidence"} <= set(artifact.get("relation_values", [])):
        errors.append("invalid artifact_refs contract")

    mapping_kinds = data.get("legacy_mapping_kinds", [])
    if set(mapping_kinds) != MAPPING_KINDS: errors.append("legacy mapping kind enum is invalid")
    valid_targets = set(fields)
    for row in data.get("legacy_field_mappings", []):
        if not isinstance(row, dict) or not {"source", "legacy_field", "canonical_field", "mapping_kind", "note"} <= set(row): errors.append("malformed legacy field mapping"); continue
        if row["mapping_kind"] not in mapping_kinds: errors.append("invalid legacy mapping kind")
        target = row["canonical_field"]
        if target is not None and target not in valid_targets: errors.append("legacy mapping points to nonexistent canonical field %s" % target)
        if row["mapping_kind"] in {"exact", "derived", "partial", "planned_future_field"} and target is None: errors.append("mapped legacy field requires canonical_field")
    legacy_fields = {(x.get("source"), x.get("legacy_field")): x for x in data.get("legacy_field_mappings", []) if isinstance(x, dict)}
    for field in ("status", "result"):
        row = legacy_fields.get(("gemini_call_ledger", field), {})
        if row.get("mapping_kind") != "partial":
            errors.append("gemini_call_ledger.%s cannot be an exact canonical mapping" % field)
    if "called" not in str(legacy_fields.get(("gemini_call_ledger", "status"), {}).get("note", "")):
        errors.append("Gemini status normalization must document legacy called")
    if "free-form" not in str(legacy_fields.get(("gemini_call_ledger", "result"), {}).get("note", "")):
        errors.append("Gemini result normalization must document free-form values")

    event_stage = {row.get("name"): row.get("stage") for row in event_rows if isinstance(row, dict)}
    expected_gemini_pairs = {("Menzo", "duplicate_arbitration"), ("Menzo", "duplicate_arbitration_same_run_batch"), ("Menzo", "duplicate_arbitration_recent_history_batch"), ("Menzo", "duplicate_arbitration_recent_history_repair"), ("Bob", "translate_article"), ("Bob", "report_blocks_legacy_prompt"), ("Alfred", "quote_resolver"), ("Alfred", "quote_ambiguity_resolver")}
    phase_rows = data.get("legacy_phase_mappings", [])
    for row in phase_rows:
        required_phase_keys = {"source", "legacy_agent", "legacy_phase", "canonical_agent", "event_type", "stage", "mapping_kind", "note"}
        if not isinstance(row, dict) or not required_phase_keys <= set(row): errors.append("malformed source-aware legacy phase mapping"); continue
        if row.get("event_type") not in event_names: errors.append("legacy phase maps to unknown event_type")
        if row.get("stage") not in stages: errors.append("legacy phase maps to unknown stage")
        elif row.get("stage") not in ({event_stage.get(row.get("event_type"))} if event_stage.get(row.get("event_type")) else set(next((x.get("allowed_stages", []) for x in event_rows if x.get("name") == row.get("event_type")), []))): errors.append("legacy phase stage disagrees with canonical event_type stage semantics")
        if row.get("legacy_agent") not in agents or row.get("canonical_agent") not in agents: errors.append("legacy phase mapping references invalid agent")
        if row.get("mapping_kind") not in mapping_kinds: errors.append("invalid legacy phase mapping kind")
    observed_gemini_pairs = {(x.get("legacy_agent"), x.get("legacy_phase")) for x in phase_rows if x.get("source") == "gemini_call_ledger"}
    if observed_gemini_pairs != expected_gemini_pairs or any(x.get("legacy_agent") == "Gemini" for x in phase_rows if x.get("source") == "gemini_call_ledger"):
        errors.append("legacy Gemini agent/phase mappings must match observed runtime callers")
    sensitive = {("Massy", "forced_policy_active"), ("Menzo", "forced_policy_active"), ("Bob", "bob_brief_guard_applied"), ("Alfred", "bob_warning_guard_applied"), ("Simone", "report_decision_ready")}
    for row in phase_rows:
        if (row.get("legacy_agent"), row.get("legacy_phase")) in sensitive and (row.get("event_type") in {"warning_recorded", "report_selected"} or row.get("mapping_kind") == "exact"):
            errors.append("policy/guard/decision readiness cannot imply warning or selection")

    if markdown is not None:
        sync = data.get("document_sync", {})
        for section in sync.get("required_sections", []):
            if not re.search(r"^##+ " + re.escape(section) + r"\s*$", markdown, re.MULTILINE): errors.append("Markdown missing section: %s" % section)
        marker_values = {"STAGES": stages, "AGENTS": agents, "EVENT_TYPES": event_names, "IDENTITIES": identity_names, "LEGACY_PHASES": [r["source"] + ":" + r["legacy_agent"] + ":" + r["legacy_phase"] for r in data.get("legacy_phase_mappings", [])], "MODEL_ROLES": model.get("roles", []), "ERROR_CLASSES": error.get("classes", [])}
        for marker, values in marker_values.items():
            expected = "<!-- SYNC:%s %s -->" % (marker, "|".join(values))
            if expected not in markdown: errors.append("Markdown sync marker mismatch: %s" % marker)
        for row in data.get("legacy_field_mappings", []):
            canonical = row.get("canonical_field") or "—"
            expected = "| %s | %s | %s | %s |" % (row.get("source"), row.get("legacy_field"), canonical, row.get("mapping_kind"))
            if expected not in markdown: errors.append("Markdown legacy field mapping mismatch: %s.%s" % (row.get("source"), row.get("legacy_field")))
        for row in phase_rows:
            expected = "| %s | %s | %s | %s | %s | %s | %s |" % (row.get("source"), row.get("legacy_agent"), row.get("legacy_phase"), row.get("canonical_agent"), row.get("event_type"), row.get("stage"), row.get("mapping_kind"))
            if expected not in markdown: errors.append("Markdown legacy phase mapping mismatch: %s:%s" % (row.get("legacy_agent"), row.get("legacy_phase")))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("schema", nargs="?", default="config/event_schema_v1.json")
    parser.add_argument("--markdown", default="docs/runtime/OWTV_EVENT_SCHEMA_V1.md")
    args = parser.parse_args(argv)
    try:
        data = json.loads(Path(args.schema).read_text(encoding="utf-8"))
        markdown = Path(args.markdown).read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print("event schema validation failed: %s" % exc, file=sys.stderr); return 2
    errors = validate(data, markdown)
    if errors:
        for error in errors: print("ERROR: %s" % error, file=sys.stderr)
        return 1
    print("OK: %s (%d stages, %d agents, %d event types, %d identities, %d legacy mappings)" % (args.schema, len(data["stages"]), len(data["agents"]), len(data["event_types"]), len(data["identities"]["fields"]), len(data["legacy_field_mappings"]) + len(data["legacy_phase_mappings"])))
    return 0

if __name__ == "__main__":
    sys.exit(main())
