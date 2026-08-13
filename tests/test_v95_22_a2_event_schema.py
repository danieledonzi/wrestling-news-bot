"""Mutation-heavy contract tests for v95.22 A2."""
import ast
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "config" / "event_schema_v1.json"
DOC = ROOT / "docs" / "runtime" / "OWTV_EVENT_SCHEMA_V1.md"
VALIDATOR = ROOT / "scripts" / "validate_event_schema.py"

spec = importlib.util.spec_from_file_location("validate_event_schema", VALIDATOR)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def load():
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def errors(mutator, with_markdown=False):
    data = copy.deepcopy(load())
    mutator(data)
    return validator.validate(data, DOC.read_text(encoding="utf-8") if with_markdown else None)


def assert_rejected(mutator, phrase):
    found = errors(mutator)
    assert found
    assert phrase in "\n".join(found)


def test_happy_path_validator_cli():
    completed = subprocess.run([sys.executable, str(VALIDATOR), str(SCHEMA)], cwd=str(ROOT), text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    assert "36 event types" in completed.stdout


def test_json_markdown_sync():
    assert validator.validate(load(), DOC.read_text(encoding="utf-8")) == []
    broken = DOC.read_text(encoding="utf-8").replace("<!-- SYNC:STAGES", "<!-- STALE:STAGES", 1)
    assert "Markdown sync marker mismatch: STAGES" in validator.validate(load(), broken)


def test_duplicate_event_type_rejected():
    assert_rejected(lambda d: d["event_types"].append(copy.deepcopy(d["event_types"][0])), "event_type values must be unique")


def test_invalid_stage_rejected():
    assert_rejected(lambda d: d["event_types"][0].update(stage="raw_phase"), "invalid stage")


def test_invalid_agent_rejected():
    assert_rejected(lambda d: d["event_types"][0]["agents"].append("UnknownAgent"), "invalid agent")


def test_invalid_identity_classification_rejected():
    assert_rejected(lambda d: d["identities"]["fields"][0].update(classification="observed_maybe"), "invalid identity classification")


def test_missing_required_contract_field_rejected():
    def mutate(d):
        d["envelope"]["fields"] = [x for x in d["envelope"]["fields"] if x["name"] != "timestamp_utc"]
        d["envelope"]["required_fields"].remove("timestamp_utc")
    assert_rejected(mutate, "missing required contract field")


def test_malformed_conditional_requirement_rejected():
    assert_rejected(lambda d: d["envelope"]["conditional_requirements"][0].pop("require"), "malformed conditional requirement")


def test_logical_request_attempt_contract_mutations_rejected():
    for key, value in [("attempt_number_base", 0), ("attempt_id_unique_per_concrete_attempt", False), ("logical_request_id_stable_across_retry_and_fallback", False), ("operation_id_equivalent_to_logical_request_id", True), ("avoided_is_concrete_attempt", True)]:
        assert_rejected(lambda d, k=key, v=value: d["attempt_contract"].update({k: v}), "invalid logical request / attempt semantic")


def test_invalid_status_result_reason_taxonomy_rejected():
    assert_rejected(lambda d: d["outcome_contract"].update(namespaces_disjoint=False), "invalid status/result/reason taxonomy")
    assert_rejected(lambda d: d["outcome_contract"]["status_values"].append("run_started"), "namespaces must be disjoint")


def test_invalid_model_role_rejected():
    assert_rejected(lambda d: d["model_contract"]["roles"].remove("quote_resolution"), "invalid model_role contract")


def test_invalid_error_contract_rejected():
    assert_rejected(lambda d: d["error_contract"].update(terminal_type="string"), "invalid error contract")


def test_invalid_artifact_refs_contract_rejected():
    assert_rejected(lambda d: d["artifact_refs_contract"].update(embed_content=True), "invalid artifact_refs contract")


def test_planned_identities_are_not_claimed_as_runtime():
    identities = {x["name"]: x["classification"] for x in load()["identities"]["fields"]}
    assert all(identities[x] == "planned_canonical" for x in ("content_id", "correlation_id", "story_id"))
    assert identities["run_id"] == identities["article_id"] == "existing_runtime"
    assert identities["candidate_id"] == "existing_partial"


def test_operation_id_is_not_automatic_logical_request_synonym():
    data = load()
    assert data["attempt_contract"]["operation_id_equivalent_to_logical_request_id"] is False
    mapping = next(x for x in data["legacy_field_mappings"] if x["source"] == "gemini_call_ledger" and x["legacy_field"] == "operation_id")
    assert mapping["mapping_kind"] == "partial"
    assert "never automatic" in mapping["note"]


def test_legacy_mapping_cannot_target_unknown_field():
    assert_rejected(lambda d: d["legacy_field_mappings"][0].update(canonical_field="imaginary_id"), "nonexistent canonical field")


def test_python_39_compatible_syntax():
    for path in (VALIDATOR, Path(__file__)):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 9))


def _legacy_field(data, name):
    return next(x for x in data["legacy_field_mappings"] if x["source"] == "gemini_call_ledger" and x["legacy_field"] == name)


def _legacy_phase(data, agent, phase):
    return next(x for x in data["legacy_phase_mappings"] if x["legacy_agent"] == agent and x["legacy_phase"] == phase)


def test_legacy_called_status_and_free_form_result_are_partial():
    data = load()
    assert _legacy_field(data, "status")["mapping_kind"] == "partial"
    assert "called" in _legacy_field(data, "status")["note"]
    assert _legacy_field(data, "result")["mapping_kind"] == "partial"
    assert "free-form" in _legacy_field(data, "result")["note"]
    assert_rejected(lambda d: _legacy_field(d, "status").update(mapping_kind="exact"), "cannot be an exact")
    assert_rejected(lambda d: _legacy_field(d, "result").update(mapping_kind="exact"), "cannot be an exact")


def test_legacy_gemini_phases_use_observed_callers_not_gemini():
    data = load()
    rows = [x for x in data["legacy_phase_mappings"] if x["source"] == "gemini_call_ledger"]
    assert {(x["legacy_agent"], x["legacy_phase"]) for x in rows} == {
        ("Menzo", "duplicate_arbitration"), ("Menzo", "duplicate_arbitration_same_run_batch"),
        ("Menzo", "duplicate_arbitration_recent_history_batch"), ("Menzo", "duplicate_arbitration_recent_history_repair"),
        ("Bob", "translate_article"), ("Bob", "report_blocks_legacy_prompt"),
        ("Alfred", "quote_resolver"), ("Alfred", "quote_ambiguity_resolver"),
    }
    assert all(x["canonical_agent"] == "Gemini" and x["legacy_agent"] != "Gemini" for x in rows)
    assert_rejected(lambda d: _legacy_phase(d, "Menzo", "duplicate_arbitration").update(legacy_agent="Gemini"), "observed runtime callers")


def test_duplicate_pair_events_conditionally_require_pair_id():
    data = load()
    assert {"article_id", "pair_id"} <= {x["name"] for x in data["envelope"]["fields"]}
    rule = next(x for x in data["envelope"]["conditional_requirements"] if x["id"] == "duplicate_pair_identity")
    assert set(rule["when_event_types"]) == {"duplicate_pair_evaluated", "duplicate_pair_resolved", "duplicate_pair_unresolved"}
    assert "pair_id" in rule["require"]
    assert_rejected(lambda d: next(x for x in d["envelope"]["conditional_requirements"] if x["id"] == "duplicate_pair_identity")["require"].remove("pair_id"), "must conditionally require pair_id")


def test_generic_lifecycle_events_preserve_pipeline_stage():
    data = load()
    for name in ("stage_started", "stage_completed", "stage_failed"):
        row = next(x for x in data["event_types"] if x["name"] == name)
        assert "stage" not in row
        assert set(row["allowed_stages"]) == set(data["stages"])
    assert_rejected(lambda d: next(x for x in d["event_types"] if x["name"] == "stage_failed")["allowed_stages"].remove("generation"), "must preserve every canonical pipeline stage")


def test_policy_and_guard_phases_do_not_imply_warning():
    data = load()
    for agent, phase in (("Massy", "forced_policy_active"), ("Menzo", "forced_policy_active"), ("Bob", "bob_brief_guard_applied"), ("Alfred", "bob_warning_guard_applied")):
        row = _legacy_phase(data, agent, phase)
        assert row["mapping_kind"] == "partial"
        assert row["event_type"] == "stage_completed"
        assert "does not imply" in row["note"]
    assert_rejected(lambda d: _legacy_phase(d, "Massy", "forced_policy_active").update(event_type="warning_recorded"), "cannot imply warning or selection")


def test_report_decision_ready_does_not_imply_selected_report():
    data = load()
    row = _legacy_phase(data, "Simone", "report_decision_ready")
    assert row["mapping_kind"] == "partial"
    assert row["event_type"] == "stage_completed"
    assert "does not prove" in row["note"]
    assert_rejected(lambda d: row if False else _legacy_phase(d, "Simone", "report_decision_ready").update(event_type="report_selected"), "cannot imply warning or selection")
