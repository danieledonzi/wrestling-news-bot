from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_phase0_baseline import validate

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config" / "phase0_baseline_v1.json"
REGISTRY = ROOT / "config" / "legacy_metric_deprecations_v1.json"
MARKDOWN = ROOT / "docs" / "runtime" / "OWTV_PHASE0_BASELINE_V1.md"
VALIDATOR = ROOT / "scripts" / "validate_phase0_baseline.py"


def payload():
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def registry():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def metric(data, name):
    return next(row for row in data["metric_baselines"] if row["metric_name"] == name)


def source(data, path):
    return next(row for row in data["source_windows"] if row["source_path"] == path)


def write_json(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def errors_for(tmp_path, data=None, dep=None, markdown=None, catalog=None):
    baseline_path = write_json(tmp_path, "baseline.json", data or payload())
    registry_path = write_json(tmp_path, "registry.json", dep or registry())
    markdown_path = tmp_path / "baseline.md"
    markdown_path.write_text(
        MARKDOWN.read_text(encoding="utf-8") if markdown is None else markdown,
        encoding="utf-8",
    )
    catalog_path = write_json(tmp_path, "catalog.json", catalog) if catalog is not None else None
    kwargs = {"markdown_path": markdown_path}
    if catalog_path is not None:
        kwargs["catalog_path"] = catalog_path
    return validate(baseline_path, registry_path, **kwargs)


def test_happy_path_cli_and_contract_count_is_derived_from_a1():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)], cwd=str(ROOT), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    assert result.returncode == 0, result.stderr
    catalog_rows = json.loads((ROOT / "config/metrics_catalog_v1.json").read_text())["metrics"]
    # Phase 0 is a frozen pre-V96.1 observation. Later catalog additions must
    # validate without pretending that they existed in the historical window.
    baseline_catalog_count = sum(row.get("policy_version") == "v95.22_a1" for row in catalog_rows)
    assert len(payload()["metric_baselines"]) == baseline_catalog_count
    assert "{} A1 metric rows".format(baseline_catalog_count) in result.stdout


def test_frozen_a1_metric_policy_selects_exact_baseline_and_ignores_future_metric(tmp_path):
    catalog = json.loads((ROOT / "config/metrics_catalog_v1.json").read_text())
    selected = {row["canonical_name"] for row in catalog["metrics"]
                if row.get("policy_version") == "v95.22_a1"}
    baseline_names = {row["metric_name"] for row in payload()["metric_baselines"]}
    assert len(selected) == 99
    assert selected == baseline_names

    future = copy.deepcopy(catalog["metrics"][0])
    future.update(canonical_name="future.synthetic_metric", domain="future",
                  policy_version="v96.2", introduced_in="v96.2")
    catalog["metrics"].append(future)
    errors = errors_for(tmp_path, catalog=catalog)
    assert not any("baseline metric set" in error for error in errors)


def test_root_target_window_matches_declared_days():
    data = payload()
    from datetime import datetime
    start = datetime.fromisoformat(data["target_window_start_utc"])
    cutoff = datetime.fromisoformat(data["baseline_cutoff_utc"])
    assert (cutoff - start).total_seconds() == data["target_window_days"] * 86400


@pytest.mark.parametrize("field,delta", [
    ("observed_window_start_utc", "2026-07-14T14:53:54.829687+00:00"),
    ("observed_window_end_utc", "2026-08-13T14:53:52.829687+00:00"),
])
def test_exact_metric_requires_exact_target_boundary(tmp_path, field, delta):
    data = payload()
    metric(data, "gemini.real_attempts")[field] = delta
    assert any("must use target_window_start_utc" in error for error in errors_for(tmp_path, data=data))


def test_exact_metric_rejects_one_second_interval_despite_full_coverage_label(tmp_path):
    data = payload()
    row = metric(data, "gemini.real_attempts")
    row["observed_window_start_utc"] = "2026-08-13T14:53:52.829687+00:00"
    assert row["source_coverage_status"] == "full_target_window"
    assert any("must use target_window_start_utc" in error for error in errors_for(tmp_path, data=data))


def test_exact_gemini_target_boundaries_are_valid():
    data = payload()
    row = metric(data, "gemini.real_attempts")
    assert row["observed_window_start_utc"] == data["target_window_start_utc"]
    assert row["observed_window_end_utc"] == data["baseline_cutoff_utc"]
    assert validate() == []


@pytest.mark.parametrize("mutation", ["omitted", "unknown", "duplicate"])
def test_a1_metric_set_and_duplicates_are_rejected(tmp_path, mutation):
    data = payload()
    if mutation == "omitted":
        data["metric_baselines"].pop()
    elif mutation == "unknown":
        data["metric_baselines"][-1]["metric_name"] = "unknown.metric"
    else:
        data["metric_baselines"].append(copy.deepcopy(data["metric_baselines"][0]))
    errors = errors_for(tmp_path, data=data)
    assert any("metric set" in error or "duplicate baseline metric" in error for error in errors)


def test_unit_drift_is_rejected(tmp_path):
    data = payload()
    metric(data, "runtime.runs_started")["catalog_unit"] = "ratio"
    assert any("catalog_unit drifts" in error for error in errors_for(tmp_path, data=data))


@pytest.mark.parametrize("bad_value", [0, 300])
def test_unsupported_metric_cannot_use_zero_or_nonzero(tmp_path, bad_value):
    data = payload()
    metric(data, "simone.terminal_errors")["value"] = bad_value
    errors = errors_for(tmp_path, data=data)
    assert any("must be null" in error for error in errors)


def test_real_partial_master_window_cannot_be_labeled_exact_30d(tmp_path):
    data = payload()
    row = metric(data, "runtime.runs_started")
    row.update(
        baseline_availability="exact", source_coverage_status="full_target_window",
        observed_window_start_utc=data["target_window_start_utc"], exactness="exact",
    )
    errors = errors_for(tmp_path, data=data)
    assert any("master-backed" in error or "retained source window" in error for error in errors)
    master = source(payload(), "state/newsroom/master_log.jsonl")
    assert master["observed_span_days"] == 6.281054


def test_runs_seen_cannot_substitute_runs_started():
    data = payload()
    started = metric(data, "runtime.runs_started")
    assert started["baseline_availability"] == "not_observed"
    assert started["value"] is None
    assert started["exactness"] == "not_observed"
    assert "runs_seen" in started["notes"]


def test_exit_zero_bucket_cannot_substitute_runs_completed():
    data = payload()
    completed = metric(data, "runtime.runs_completed")
    exit_zero = metric(data, "runtime.runs_exit_zero")
    assert completed["value"] is None
    assert completed["baseline_availability"] == "not_observed"
    assert exit_zero["value"] == 300
    assert exit_zero["baseline_availability"] == "partial"


def test_raw_handoff_value_cannot_claim_canonical_snapshot_provenance(tmp_path):
    data = payload()
    metric(data, "bob.packages_ready")["calculation_basis"] = "canonical_observability_snapshot"
    assert any("raw handoff metric" in error for error in errors_for(tmp_path, data=data))


def test_metric_source_primary_is_bound_exactly_to_a1(tmp_path):
    data = payload()
    metric(data, "runtime.runs_exit_zero")["source_primary"] = "state/newsroom/master_log.jsonl"
    assert any("source_primary drifts" in error for error in errors_for(tmp_path, data=data))


def test_metric_source_window_reference_must_exist(tmp_path):
    data = payload()
    metric(data, "runtime.runs_exit_zero")["source_window_ref"] = "unknown/source.json"
    assert any("unknown source_window_ref" in error for error in errors_for(tmp_path, data=data))


def test_metric_coverage_must_match_referenced_source(tmp_path):
    data = payload()
    metric(data, "runtime.runs_exit_zero")["source_coverage_status"] = "full_target_window"
    assert any("coverage drifts" in error for error in errors_for(tmp_path, data=data))


@pytest.mark.parametrize("field,value,error", [
    ("artifact_family", "ledger", "artifact_family disagrees"),
    ("authority_purposes", ["state_memory"], "authority_purposes disagree"),
    ("semantic_roles", ["pipeline_observability"], "semantic_roles disagree"),
])
def test_a3_family_authority_and_roles_are_enforced(tmp_path, field, value, error):
    data = payload()
    source(data, "state/newsroom/master_log.jsonl")[field] = value
    assert any(error in item for item in errors_for(tmp_path, data=data))


def test_a3_glob_family_is_resolved_for_report_source(tmp_path):
    data = payload()
    report = source(data, "reports/translation_quality_audit_latest.json")
    assert report["artifact_family"] == "report"
    assert report["authority_purposes"] == ["pipeline_observability"]
    report["artifact_family"] = "snapshot"
    assert any("artifact_family disagrees" in error for error in errors_for(tmp_path, data=data))


def test_current_snapshot_cannot_be_labeled_historical(tmp_path):
    data = payload()
    row = metric(data, "runtime.expected_dirt_paths")
    row["observed_window_start_utc"] = data["target_window_start_utc"]
    assert any("falsely historical" in error for error in errors_for(tmp_path, data=data))


@pytest.mark.parametrize("mutation", ["after_cutoff", "start_after_end"])
def test_source_timestamp_order_and_cutoff(tmp_path, mutation):
    data = payload()
    master = source(data, "state/newsroom/master_log.jsonl")
    if mutation == "after_cutoff":
        master["observed_end_utc"] = "2026-08-14T00:00:00+00:00"
    else:
        master["observed_start_utc"] = "2026-08-13T14:50:00+00:00"
    errors = errors_for(tmp_path, data=data)
    assert any("exceeds" in error for error in errors)


def test_target_must_be_exactly_thirty_days(tmp_path):
    data = payload()
    data["target_window_days"] = 29
    assert any("must equal 30" in error for error in errors_for(tmp_path, data=data))


def test_production_sha_may_differ_from_contract_sha():
    data = payload()
    assert data["production_code_commit"] != data["contract_code_commit"]
    assert validate() == []


@pytest.mark.parametrize("mutation", ["unknown_metric", "unknown_replacement", "removed", "immediate", "duplicate"])
def test_deprecation_registry_rejects_unsafe_mutations(tmp_path, mutation):
    dep = registry()
    row = dep["entries"][0]
    if mutation == "unknown_metric":
        row["legacy_metric_name"] = "definitely_unknown_legacy_xyz"
    elif mutation == "unknown_replacement":
        row["canonical_replacements"] = ["unknown.canonical"]
    elif mutation == "removed":
        row["deprecation_status"] = "removed"
    elif mutation == "immediate":
        runtime_row = next(x for x in dep["entries"] if any(c["consumer_type"] == "runtime" for c in x["known_consumers"]))
        runtime_row["earliest_removal_phase"] = "phase_1"
    else:
        dep["entries"].append(copy.deepcopy(row))
    errors = errors_for(tmp_path, dep=dep)
    assert any(word in error for error in errors for word in ("unknown legacy", "unknown canonical", "forbidden", "immediately", "duplicate deprecation"))


def test_missing_guardrail_evidence_is_rejected(tmp_path):
    data = payload()
    data["stabilized_guardrails"][0]["evidence_files"] = ["tests/does_not_exist.py"]
    assert any("does not exist" in error for error in errors_for(tmp_path, data=data))


@pytest.mark.parametrize("field,value,needle", [
    ("legacy_source", 3, "legacy_source must be"),
    ("reason_codes", "legacy_name", "invalid reason_codes"),
    ("canonical_replacements", "runtime.runs_exit_zero", "unknown canonical replacement"),
    ("known_consumers", [{"path": "x", "consumer_type": "python"}], "invalid consumers"),
    ("transition_requirement", None, "transition_requirement must be"),
    ("earliest_removal_phase", 2, "earliest_removal_phase must be"),
    ("safety_notes", [], "safety_notes must be"),
])
def test_deprecation_row_primitive_types(tmp_path, field, value, needle):
    dep = registry()
    dep["entries"][0][field] = value
    assert any(needle in error for error in errors_for(tmp_path, dep=dep))


@pytest.mark.parametrize("malformed", [123, {"path": "agents/example.py"}, "runtime"])
def test_malformed_known_consumers_returns_error_without_exception(tmp_path, malformed):
    dep = registry()
    dep["entries"][0]["known_consumers"] = malformed
    errors = errors_for(tmp_path, dep=dep)
    assert any("invalid consumers" in error for error in errors)


def test_empty_known_consumers_list_does_not_crash(tmp_path):
    dep = registry()
    dep["entries"][0]["known_consumers"] = []
    errors = errors_for(tmp_path, dep=dep)
    assert not any("invalid consumers" in error for error in errors)


def test_malformed_consumer_item_returns_error_without_exception(tmp_path):
    dep = registry()
    dep["entries"][0]["known_consumers"] = [123]
    assert any("invalid consumers" in error for error in errors_for(tmp_path, dep=dep))


def test_cli_reports_malformed_consumers_without_traceback(tmp_path):
    dep = registry()
    dep["entries"][0]["known_consumers"] = 123
    baseline_path = write_json(tmp_path, "baseline.json", payload())
    registry_path = write_json(tmp_path, "registry.json", dep)
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(baseline_path), str(registry_path)],
        cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode != 0
    assert "invalid consumers" in result.stderr
    assert "Traceback" not in result.stderr


def test_gemini_success_aliases_include_observability_report_consumer():
    entries = {row["legacy_metric_name"]: row for row in registry()["entries"]}
    expected = {"path": "scripts/observability_snapshot.py", "consumer_type": "report"}
    for name in ("completed_successful_calls", "gemini_3_5_completed_successful_calls"):
        assert expected in entries[name]["known_consumers"]


@pytest.mark.parametrize("name", [
    "completed_successful_calls", "gemini_3_5_completed_successful_calls",
])
def test_removing_required_gemini_alias_consumer_fails(tmp_path, name):
    dep = registry()
    row = next(item for item in dep["entries"] if item["legacy_metric_name"] == name)
    row["known_consumers"] = [
        consumer for consumer in row["known_consumers"]
        if consumer["path"] != "scripts/observability_snapshot.py"
    ]
    assert any("missing required known consumer" in error for error in errors_for(tmp_path, dep=dep))


def test_reporting_scripts_are_not_classified_as_runtime_consumers():
    reporting_paths = {
        "scripts/observability_snapshot.py", "scripts/daily_editorial_judgment.py",
        "scripts/owtv_gemini_ledger_report.py", "send_daily_report.py",
    }
    consumers = [c for row in registry()["entries"] for c in row["known_consumers"]]
    assert all(c["consumer_type"] == "report" for c in consumers if c["path"] in reporting_paths)
    assert any(
        c == {"path": "agents/gemini_diagnostics.py", "consumer_type": "runtime"}
        for c in consumers
    )


def test_phase1_ledger_gap_does_not_block_phase0():
    data = payload()
    assert any(gap["gap_id"] == "canonical_event_ledger_absent" for gap in data["known_phase1_gaps"])
    assert data["phase0_completion"]["phase1_ready"] is True
    assert validate() == []


def test_simone_legacy_errors_are_not_terminal_taxonomy(tmp_path):
    data = payload()
    assert metric(data, "simone.legacy_errors_diagnostic")["value"] == 300
    assert metric(data, "simone.terminal_errors")["value"] is None
    metric(data, "simone.terminal_errors")["value"] = 300
    assert any("terminal_errors must remain null" in error for error in errors_for(tmp_path, data=data))


def test_simone_ready_events_are_not_reports_published(tmp_path):
    data = payload()
    published = metric(data, "simone.reports_published")
    ready = metric(data, "simone.reports_ready")
    assert published["value"] == 5 and ready["value"] == 753
    published["evidence_kind"] = "event_sum"
    published["calculation_basis"] = "master_handoff_exact_event_sum"
    assert any("publication-authority" in error for error in errors_for(tmp_path, data=data))


def test_menzo_event_sum_cannot_replace_unique_identity_count(tmp_path):
    data = payload()
    unique = metric(data, "menzo.unique_downstream_handoffs")
    events = metric(data, "menzo.selected_after_budget")
    assert unique["value"] == 116 and events["value"] == 146
    unique["evidence_kind"] = "event_sum"
    assert any("cannot use an event sum" in error for error in errors_for(tmp_path, data=data))


def test_bob_package_event_is_not_promoted_to_unsupported_unique_semantic():
    data = payload()
    assert metric(data, "bob.packages_ready")["value"] == 144
    assert metric(data, "bob.logical_translation_requests")["value"] is None
    assert metric(data, "bob.model_successes")["value"] is None


def test_gemini_exact_metric_requires_full_window_source(tmp_path):
    data = payload()
    metric(data, "gemini.real_attempts")["source_coverage_status"] = "partial_target_window"
    errors = errors_for(tmp_path, data=data)
    assert any("full_target_window" in error or "full-window" in error for error in errors)


def test_absent_source_is_distinct_from_present_unobserved_source():
    data = payload()
    absent = source(data, "reports/translation_quality_audit_latest.json")
    coverage = source(data, "artifacts/newsroom/menzo_duplicate_pair_coverage.json")
    audit_metric = metric(data, "artifact_coverage.source_material_coverage")
    pair_metric = metric(data, "menzo.same_run_expected_pairs")
    assert absent["exists"] is False
    assert audit_metric["baseline_availability"] == "source_unavailable"
    assert audit_metric["source_coverage_status"] == "source_unavailable"
    assert coverage["exists"] is True
    assert pair_metric["baseline_availability"] == "not_observed"
    assert pair_metric["source_coverage_status"] == "current_snapshot_only"


def test_present_source_can_have_unsupported_a1_semantic():
    data = payload()
    row = metric(data, "bob.model_successes")
    assert source(data, "state/newsroom/gemini_call_ledger.jsonl")["exists"] is True
    assert row["baseline_availability"] == "unsupported_historical"
    assert row["source_window_ref"] is None
    assert row["value"] is None


@pytest.mark.parametrize("name,bad_value", [
    ("runtime.runs_exit_zero", "300"),
    ("runtime.runs_exit_zero", 3.5),
    ("runtime.runs_exit_zero", True),
    ("menzo.duplicate_coverage_complete", 1),
    ("menzo.handoff_to_publication_ratio", "0.5"),
    ("menzo.handoff_to_publication_ratio", True),
    ("menzo.handoff_to_publication_ratio", 1.5),
])
def test_metric_value_type_contract(tmp_path, name, bad_value):
    data = payload()
    row = metric(data, name)
    row["value"] = bad_value
    if row["baseline_availability"] == "not_observed":
        row.update(
            baseline_availability="current_snapshot_only", exactness="exact",
            observed_window_start_utc="2026-08-13T14:38:04.615706+00:00",
            observed_window_end_utc="2026-08-13T14:38:04.615706+00:00",
            calculation_basis="current_state_snapshot",
        )
    errors = errors_for(tmp_path, data=data)
    assert any("value must" in error for error in errors)


@pytest.mark.parametrize("field,value,needle", [
    ("source_coverage_status", "made_up", "unknown source_coverage_status"),
    ("exactness", "approximately_exact", "unknown exactness"),
    ("exactness", "exact", "availability/exactness"),
])
def test_metric_coverage_and_exactness_taxonomies(tmp_path, field, value, needle):
    data = payload()
    metric(data, "runtime.runs_exit_zero")[field] = value
    assert any(needle in error for error in errors_for(tmp_path, data=data))


@pytest.mark.parametrize("field,value,needle", [
    ("exists", 1, "exists must be boolean"),
    ("authority_purposes", "pipeline_observability", "authority_purposes must"),
    ("observed_span_days", "6.2", "observed_span_days must"),
    ("row_or_item_count", True, "row_or_item_count must"),
    ("notes", 3, "notes must be a string"),
])
def test_source_row_primitive_types(tmp_path, field, value, needle):
    data = payload()
    source(data, "state/newsroom/master_log.jsonl")[field] = value
    assert any(needle in error for error in errors_for(tmp_path, data=data))


def test_publisher_and_simone_history_counts_are_not_historical_metrics():
    data = payload()
    pub = source(data, "state/newsroom/publisher_history.json")
    simone = source(data, "state/newsroom/simone_report_history.json")
    assert (pub["row_or_item_count"], simone["row_or_item_count"]) == (826, 38)
    assert pub["coverage_status"] == simone["coverage_status"] == "history_without_reliable_window"
    assert pub["observed_start_utc"] is simone["observed_start_utc"] is None


def test_history_without_timestamps_cannot_claim_target_window(tmp_path):
    data = payload()
    pub = source(data, "state/newsroom/publisher_history.json")
    pub["observed_start_utc"] = data["target_window_start_utc"]
    assert any("must not manufacture" in error for error in errors_for(tmp_path, data=data))


def test_state_ttl_is_current_state_not_event_history(tmp_path):
    data = payload()
    footprints = source(data, "state/newsroom/story_footprints.json")
    assert footprints["row_or_item_count"] == 138
    footprints["observed_start_utc"] = "2026-08-06T14:38:04.689214+00:00"
    assert any("must not manufacture" in error for error in errors_for(tmp_path, data=data))


def test_repository_dirt_semantics_are_distinct_from_grouped_probe():
    data = payload()
    assert data["production_repo_dirty_paths_grouped"] == 3
    assert metric(data, "runtime.expected_dirt_paths")["value"] == 178
    assert metric(data, "runtime.unexpected_dirt_paths")["value"] == 0
    assert metric(data, "runtime.expected_dirt_paths")["baseline_availability"] == "current_snapshot_only"


@pytest.mark.parametrize("section", ["METRIC_BASELINES", "DEPRECATIONS"])
def test_markdown_stale_rows_are_rejected(tmp_path, section):
    markdown = MARKDOWN.read_text(encoding="utf-8")
    begin = "<!-- BEGIN {} -->".format(section)
    position = markdown.index(begin)
    markdown = markdown[:position] + markdown[position:].replace('"notes":', '"notes_drift":', 1)
    errors = errors_for(tmp_path, markdown=markdown)
    assert any("does not exactly match JSON" in error for error in errors)


def test_markdown_duplicate_row_is_rejected(tmp_path):
    markdown = MARKDOWN.read_text(encoding="utf-8")
    marker = '<!-- BEGIN METRIC_BASELINES -->\n```jsonl\n'
    start = markdown.index(marker) + len(marker)
    end = markdown.index("\n", start)
    row = markdown[start:end]
    markdown = markdown[:end] + "\n" + row + markdown[end:]
    assert any("does not exactly match JSON" in error for error in errors_for(tmp_path, markdown=markdown))


def test_markdown_note_provenance_drift_is_rejected(tmp_path):
    markdown = MARKDOWN.read_text(encoding="utf-8").replace(
        "No value inferred from similar counters", "Value inferred from similar counters", 1
    )
    assert any("does not exactly match JSON" in error for error in errors_for(tmp_path, markdown=markdown))


def test_validator_source_is_python39_compatible():
    source_text = VALIDATOR.read_text(encoding="utf-8")
    ast.parse(source_text, filename=str(VALIDATOR), feature_version=(3, 9))
