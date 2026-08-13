#!/usr/bin/env python3
"""Validate the Phase 0 baseline, deprecation registry, and derived view."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "config" / "phase0_baseline_v1.json"
DEFAULT_REGISTRY = ROOT / "config" / "legacy_metric_deprecations_v1.json"
DEFAULT_CATALOG = ROOT / "config" / "metrics_catalog_v1.json"
DEFAULT_EVENT = ROOT / "config" / "event_schema_v1.json"
DEFAULT_MANIFEST = ROOT / "config" / "artifact_manifest_schema_v1.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "runtime" / "OWTV_PHASE0_BASELINE_V1.md"
DEFAULT_LEGACY = ROOT / "docs" / "runtime" / "OWTV_METRICS_LEGACY_INVENTORY.md"

AVAILABILITIES = {
    "exact", "partial", "current_snapshot_only", "unsupported_historical",
    "source_unavailable", "not_observed",
}
EXACTNESSES = {
    "exact", "bounded_by_source_retention", "unsupported", "not_observed",
}
AVAILABILITY_EXACTNESS = {
    "exact": "exact",
    "partial": "bounded_by_source_retention",
    "current_snapshot_only": "exact",
    "unsupported_historical": "unsupported",
    "source_unavailable": "unsupported",
    "not_observed": "not_observed",
}
COVERAGES = {
    "full_target_window", "partial_target_window", "current_snapshot_only",
    "history_without_reliable_window", "bounded_state_current",
    "source_unavailable", "not_timestamped", "point_in_time",
}
DEPRECATION_STATUSES = {
    "scheduled_for_deprecation", "retain_diagnostic_until_replacement",
    "blocked_missing_exact_replacement", "compatibility_alias_only",
    "already_non_authoritative",
}
REASON_CODES = {
    "ambiguous_semantics", "duplicate_metric", "event_count_vs_unique_count",
    "non_authoritative_source", "legacy_name", "unsupported_exactness",
    "superseded_by_canonical_metric",
}
CALCULATION_BASES = {
    "canonical_observability_snapshot", "canonical_gemini_diagnostics",
    "canonical_repository_diagnostics", "master_handoff_exact_event_sum",
    "current_state_snapshot", "direct_source_count",
}
RAW_HANDOFF_METRICS = {
    "massy.candidate_news", "massy.candidate_reports", "massy.hard_skips",
    "massy.actionable_handoffs", "menzo.selected_after_budget", "menzo.pending",
    "menzo.skipped", "bob.packages_ready", "bob.packages_pending",
    "bob.packages_empty", "bob.packages_errors", "simone.reports_ready",
    "publisher.already_present_events", "publisher.dry_run_events",
    "publisher.wordpress_not_ready_events",
}
SECTIONS = {
    "SOURCE_WINDOWS": "source_windows",
    "METRIC_BASELINES": "metric_baselines",
    "DEPRECATIONS": "entries",
    "GUARDRAILS": "stabilized_guardrails",
    "PHASE1_GAPS": "known_phase1_gaps",
    "PHASE0_COMPLETION": "phase0_completion",
}


def _load(path: Path, errors: List[str], label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append("cannot load {} {}: {}".format(label, path, exc))
        return {}
    if not isinstance(value, dict):
        errors.append("{} root must be an object".format(label))
        return {}
    return value


def _time(value: Any, field: str, errors: List[str]) -> Optional[datetime]:
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append("{} must be an ISO UTC string or null".format(field))
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append("{} is not a valid ISO timestamp".format(field))
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        errors.append("{} must be UTC-aware".format(field))
        return None
    return parsed


def _unique(rows: Any, key: str, label: str, errors: List[str]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(rows, list):
        errors.append("{} must be a list".format(label))
        return {}
    result = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or not row.get(key):
            errors.append("{} row {} requires non-empty {}".format(label, index, key))
            continue
        name = row[key]
        if name in result:
            errors.append("duplicate {}: {}".format(label, name))
        result[name] = row
    return result


def _markdown_rows(text: str, section: str, errors: List[str]) -> Any:
    pattern = re.compile(
        r"<!-- BEGIN " + re.escape(section) + r" -->\s*```jsonl\s*\n"
        r"(.*?)\n```\s*<!-- END " + re.escape(section) + r" -->", re.S
    )
    matches = pattern.findall(text)
    if len(matches) != 1:
        errors.append("Markdown must contain exactly one {} synchronized block".format(section))
        return []
    rows = []
    for number, line in enumerate(matches[0].splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            errors.append("Markdown {} line {} is invalid JSON: {}".format(section, number, exc))
    return rows[0] if section == "PHASE0_COMPLETION" and len(rows) == 1 else rows


def _glob_regex(pattern: str) -> str:
    """Translate the immutable A3 python_glob_v1 subset to a regex."""
    output, index = "", 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                if index + 2 < len(pattern) and pattern[index + 2] == "/":
                    output += "(?:[^/]+/)*"
                    index += 3
                else:
                    output += ".*"
                    index += 2
            else:
                output += "[^/]*"
                index += 1
        elif char == "?":
            output += "[^/]"
            index += 1
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end < 0:
                output += r"\["
                index += 1
            else:
                output += pattern[index:end + 1]
                index = end + 1
        else:
            output += re.escape(char)
            index += 1
    return "^" + output + "$"


def _a3_family(path: str, manifest: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    inventory = manifest.get("legacy_artifact_inventory", [])
    matches = [
        row for row in inventory if isinstance(row, dict)
        and re.fullmatch(_glob_regex(str(row.get("path_or_pattern", ""))), path)
    ]
    catch_all = set(
        manifest.get("family_resolution_contract", {}).get("catch_all_patterns", [])
    )
    specific = [row for row in matches if row.get("path_or_pattern") not in catch_all]
    resolved = specific or matches
    return resolved[0] if len(resolved) == 1 else None


def _nullable_number(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def validate(
    baseline_path: Path = DEFAULT_BASELINE,
    registry_path: Path = DEFAULT_REGISTRY,
    catalog_path: Path = DEFAULT_CATALOG,
    event_path: Path = DEFAULT_EVENT,
    manifest_path: Path = DEFAULT_MANIFEST,
    markdown_path: Path = DEFAULT_MARKDOWN,
    legacy_path: Path = DEFAULT_LEGACY,
) -> List[str]:
    errors: List[str] = []
    baseline = _load(baseline_path, errors, "baseline")
    registry = _load(registry_path, errors, "registry")
    catalog = _load(catalog_path, errors, "catalog")
    event = _load(event_path, errors, "event schema")
    manifest = _load(manifest_path, errors, "artifact manifest")
    if errors:
        return errors

    expected_root = {
        "schema_version", "policy_version", "phase", "measurement_only",
        "baseline_generated_at_utc", "baseline_cutoff_utc", "target_window_days",
        "target_window_start_utc", "contract_code_commit", "production_code_commit",
        "production_branch", "production_python_version",
        "production_repo_dirty_paths_grouped", "a3_merge_commit",
        "production_scheduler", "source_windows", "metric_baselines",
        "stabilized_guardrails", "known_phase1_gaps", "phase0_completion",
    }
    missing = sorted(expected_root - set(baseline))
    if missing:
        errors.append("baseline missing root fields: {}".format(", ".join(missing)))
    if baseline.get("schema_version") != "owtv_phase0_baseline_v1":
        errors.append("invalid baseline schema_version")
    if registry.get("schema_version") != "owtv_legacy_metric_deprecations_v1":
        errors.append("invalid deprecation registry schema_version")
    if baseline.get("policy_version") != "v95.22_a4" or registry.get("policy_version") != "v95.22_a4":
        errors.append("baseline and registry policy_version must be v95.22_a4")
    if baseline.get("phase") != "phase_0" or baseline.get("measurement_only") is not True:
        errors.append("baseline must be measurement-only Phase 0")
    if registry.get("measurement_only") is not True:
        errors.append("registry must be measurement_only")
    if catalog.get("schema_version") != "owtv_metrics_catalog_v1":
        errors.append("A1 catalog schema mismatch")
    if event.get("schema_version") != "owtv_event_schema_v1":
        errors.append("A2 event schema mismatch")
    if manifest.get("schema_version") != "owtv_artifact_manifest_schema_v1":
        errors.append("A3 artifact manifest schema mismatch")

    cutoff = _time(baseline.get("baseline_cutoff_utc"), "baseline_cutoff_utc", errors)
    target = _time(baseline.get("target_window_start_utc"), "target_window_start_utc", errors)
    generated = _time(baseline.get("baseline_generated_at_utc"), "baseline_generated_at_utc", errors)
    if baseline.get("target_window_days") != 30:
        errors.append("target_window_days must equal 30")
    if cutoff and target and cutoff - target != timedelta(days=30):
        errors.append("target window timestamps must span exactly 30 days")
    if generated and cutoff and generated < cutoff:
        errors.append("baseline generation cannot precede cutoff")
    sha = re.compile(r"^[0-9a-f]{40}$")
    for key in ("contract_code_commit", "production_code_commit", "a3_merge_commit"):
        if not isinstance(baseline.get(key), str) or not sha.match(baseline[key]):
            errors.append("{} must be a full lowercase Git SHA".format(key))
    # Production and contract SHAs are intentionally not required to match.

    source_rows = _unique(baseline.get("source_windows"), "source_path", "source window", errors)
    for path, row in source_rows.items():
        required = {
            "artifact_family", "exists", "authority_purposes", "observed_start_utc",
            "observed_end_utc", "observed_span_days", "target_window_days",
            "coverage_status", "row_or_item_count", "schema_version_observed",
            "evidence_basis", "retention_effect", "notes", "semantic_roles",
        }
        if not required <= set(row):
            errors.append("source {} is missing required fields".format(path))
        if row.get("coverage_status") not in COVERAGES:
            errors.append("source {} has unknown coverage_status".format(path))
        if not isinstance(row.get("exists"), bool):
            errors.append("source {} exists must be boolean".format(path))
        if not isinstance(row.get("authority_purposes"), list) or any(
            not isinstance(value, str) for value in row.get("authority_purposes", [])
        ):
            errors.append("source {} authority_purposes must be a string list".format(path))
        if not isinstance(row.get("semantic_roles"), list) or any(
            not isinstance(value, str) for value in row.get("semantic_roles", [])
        ):
            errors.append("source {} semantic_roles must be a string list".format(path))
        if not _nullable_number(row.get("observed_span_days")):
            errors.append("source {} observed_span_days must be numeric or null".format(path))
        if row.get("row_or_item_count") is not None and (
            not isinstance(row.get("row_or_item_count"), int)
            or isinstance(row.get("row_or_item_count"), bool)
            or row.get("row_or_item_count") < 0
        ):
            errors.append("source {} row_or_item_count must be a non-negative integer or null".format(path))
        if not isinstance(row.get("notes"), str):
            errors.append("source {} notes must be a string".format(path))
        if row.get("target_window_days") != 30:
            errors.append("source {} target_window_days must equal 30".format(path))
        start = _time(row.get("observed_start_utc"), path + ".observed_start_utc", errors)
        end = _time(row.get("observed_end_utc"), path + ".observed_end_utc", errors)
        if start and end and start > end:
            errors.append("source {} observed start exceeds end".format(path))
        if cutoff and end and end > cutoff:
            errors.append("source {} observed end exceeds cutoff".format(path))
        if row.get("coverage_status") == "full_target_window" and (not start or not end or (target and start > target)):
            errors.append("source {} cannot claim full target coverage".format(path))
        if row.get("coverage_status") == "point_in_time" and start != end:
            errors.append("source {} point-in-time window must have equal timestamps".format(path))
        if row.get("coverage_status") == "current_snapshot_only" and target and start and start <= target:
            errors.append("source {} current snapshot cannot claim the editorial target start".format(path))
        if row.get("coverage_status") in {"history_without_reliable_window", "bounded_state_current"} and start is not None:
            errors.append("source {} must not manufacture a historical start".format(path))
        if path == "state/newsroom/master_log.jsonl":
            if row.get("coverage_status") != "partial_target_window":
                errors.append("bounded master log must be partial_target_window")
            if target and start and start <= target:
                errors.append("bounded master log cannot claim the full 30-day start")
        if path == "state/newsroom/gemini_call_ledger.jsonl" and row.get("coverage_status") != "full_target_window":
            errors.append("observed Gemini ledger must cover the full target window")
        family = None if path == "repository_diagnostics" else _a3_family(path, manifest)
        if path != "repository_diagnostics" and family is None:
            errors.append("source {} does not resolve to exactly one A3 family".format(path))
        if family is not None:
            purposes = [claim.get("purpose") for claim in family.get("authority_claims", [])]
            if row.get("artifact_family") != family.get("artifact_type"):
                errors.append("source {} artifact_family disagrees with A3".format(path))
            if row.get("authority_purposes") != purposes:
                errors.append("source {} authority_purposes disagree with A3 authority_claims".format(path))
            if row.get("semantic_roles") != family.get("semantic_roles"):
                errors.append("source {} semantic_roles disagree with A3".format(path))

    catalog_rows = _unique(catalog.get("metrics"), "canonical_name", "catalog metric", errors)
    metric_rows = _unique(baseline.get("metric_baselines"), "metric_name", "baseline metric", errors)
    if set(metric_rows) != set(catalog_rows):
        errors.append("baseline metric set must exactly equal the A1 catalog metric set")
    for name, row in metric_rows.items():
        cat = catalog_rows.get(name)
        if cat is None:
            continue
        required = {
            "domain", "catalog_status", "catalog_unit", "baseline_availability",
            "value", "observed_window_start_utc", "observed_window_end_utc",
            "source_primary", "source_coverage_status", "exactness",
            "calculation_basis", "zero_semantics", "missing_semantics",
            "evidence_kind", "notes", "source_window_ref",
        }
        if not required <= set(row):
            errors.append("metric {} is missing required fields".format(name))
        for field, catalog_field in (("domain", "domain"), ("catalog_status", "status"), ("catalog_unit", "unit"), ("zero_semantics", "zero_semantics"), ("missing_semantics", "missing_semantics")):
            if row.get(field) != cat.get(catalog_field):
                errors.append("metric {} {} drifts from A1".format(name, field))
        for field in ("metric_name", "domain", "catalog_status", "catalog_unit", "baseline_availability", "source_primary", "source_coverage_status", "exactness", "evidence_kind"):
            if not isinstance(row.get(field), str) or not row.get(field):
                errors.append("metric {} {} must be a non-empty string".format(name, field))
        if row.get("source_primary") != cat.get("source_primary"):
            errors.append("metric {} source_primary drifts from A1 authority".format(name))
        source_ref = row.get("source_window_ref")
        if source_ref is not None and (not isinstance(source_ref, str) or source_ref not in source_rows):
            errors.append("metric {} has unknown source_window_ref".format(name))
        if source_ref in source_rows and row.get("source_coverage_status") != source_rows[source_ref].get("coverage_status"):
            errors.append("metric {} coverage drifts from referenced source window".format(name))
        if source_ref in source_rows:
            source_exists = source_rows[source_ref].get("exists")
            if source_exists is False and row.get("baseline_availability") != "source_unavailable":
                errors.append("metric {} references an absent source but is not source_unavailable".format(name))
            if source_exists is True and row.get("baseline_availability") == "source_unavailable":
                errors.append("metric {} calls a present source unavailable".format(name))
        if row.get("source_coverage_status") not in COVERAGES:
            errors.append("metric {} has unknown source_coverage_status".format(name))
        if row.get("exactness") not in EXACTNESSES:
            errors.append("metric {} has unknown exactness".format(name))
        expected_exactness = AVAILABILITY_EXACTNESS.get(row.get("baseline_availability"))
        if expected_exactness is not None and row.get("exactness") != expected_exactness:
            errors.append("metric {} availability/exactness combination is invalid".format(name))
        if row.get("calculation_basis") is not None and not isinstance(row.get("calculation_basis"), str):
            errors.append("metric {} calculation_basis must be a string or null".format(name))
        availability = row.get("baseline_availability")
        if availability not in AVAILABILITIES:
            errors.append("metric {} has unknown baseline_availability".format(name))
        value = row.get("value")
        start = _time(row.get("observed_window_start_utc"), name + ".observed_window_start_utc", errors)
        end = _time(row.get("observed_window_end_utc"), name + ".observed_window_end_utc", errors)
        if start and end and start > end:
            errors.append("metric {} observed start exceeds end".format(name))
        if cutoff and end and end > cutoff:
            errors.append("metric {} observed end exceeds cutoff".format(name))
        unit = cat.get("unit")
        if value is not None:
            if unit == "count" and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                errors.append("metric {} count value must be a non-negative integer".format(name))
            elif unit == "boolean" and not isinstance(value, bool):
                errors.append("metric {} boolean value must be bool".format(name))
            elif unit == "ratio" and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
                or not 0 <= value <= 1
            ):
                errors.append("metric {} ratio value must be numeric in [0, 1]".format(name))
        if value is not None and row.get("calculation_basis") not in CALCULATION_BASES:
            errors.append("metric {} non-null value lacks a defensible calculation_basis".format(name))
        if availability in {"unsupported_historical", "source_unavailable", "not_observed"}:
            if value is not None:
                errors.append("metric {} unavailable/unsupported value must be null".format(name))
            if start is not None or end is not None:
                errors.append("metric {} unavailable/unsupported window must be null".format(name))
        if availability == "unsupported_historical" and row.get("exactness") != "unsupported":
            errors.append("metric {} unsupported exactness must be unsupported".format(name))
        if availability in {"exact", "partial", "current_snapshot_only"} and value is None:
            errors.append("metric {} available observation cannot use null".format(name))
        if availability == "exact" and row.get("source_coverage_status") != "full_target_window":
            errors.append("metric {} exact historical baseline requires full_target_window".format(name))
        if availability == "partial" and row.get("source_coverage_status") != "partial_target_window":
            errors.append("metric {} partial baseline requires partial_target_window".format(name))
        if availability == "current_snapshot_only":
            if row.get("source_coverage_status") not in {"point_in_time", "current_snapshot_only", "bounded_state_current"} or start != end:
                errors.append("metric {} current snapshot is falsely historical".format(name))
        source = row.get("source_window_ref")
        if source == "state/newsroom/master_log.jsonl" and availability == "exact":
            errors.append("master-backed metric {} cannot claim exact 30-day coverage".format(name))
        if source == "state/newsroom/master_log.jsonl" and availability == "partial" and (start != _time(source_rows.get(source, {}).get("observed_start_utc"), "master source start", errors) or end != _time(source_rows.get(source, {}).get("observed_end_utc"), "master source end", errors)):
            errors.append("master-backed metric {} must use retained source window".format(name))
        if name.startswith("gemini.") and availability == "exact":
            if source != "state/newsroom/gemini_call_ledger.jsonl" or row.get("source_coverage_status") != "full_target_window" or cat.get("availability") != "available":
                errors.append("Gemini metric {} lacks canonical full-window authority".format(name))
        if cat.get("availability") == "unavailable" and availability != "unsupported_historical":
            errors.append("A1-unavailable metric {} must remain unsupported".format(name))
        if name in RAW_HANDOFF_METRICS and value is not None and row.get("calculation_basis") != "master_handoff_exact_event_sum":
            errors.append("raw handoff metric {} must use master_handoff_exact_event_sum".format(name))
    terminal = metric_rows.get("simone.terminal_errors", {})
    if terminal.get("value") is not None or terminal.get("baseline_availability") != "unsupported_historical":
        errors.append("simone.terminal_errors must remain null until typed taxonomy exists")
    reports = metric_rows.get("simone.reports_published", {})
    if reports and (reports.get("source_window_ref") != "state/newsroom/master_log.jsonl" or reports.get("evidence_kind") != "canonical_bounded_aggregate"):
        errors.append("simone.reports_published must use publication-authority distinct identities")
    handoffs = metric_rows.get("menzo.unique_downstream_handoffs", {})
    if handoffs and handoffs.get("evidence_kind") != "canonical_bounded_aggregate":
        errors.append("Menzo unique handoffs cannot use an event sum")

    dep_rows = _unique(registry.get("entries"), "legacy_metric_name", "deprecation", errors)
    aliases = {alias: row["canonical_name"] for row in catalog_rows.values() for alias in row.get("legacy_aliases", [])}
    deprecated_names = {row["canonical_name"] for row in catalog_rows.values() if row.get("status") == "deprecated"}
    try:
        legacy_text = legacy_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append("cannot load legacy inventory {}: {}".format(legacy_path, exc))
        legacy_text = ""
    for name, row in dep_rows.items():
        required = {
            "legacy_source", "deprecation_status", "reason_codes",
            "canonical_replacements", "known_consumers", "transition_requirement",
            "earliest_removal_phase", "safety_notes",
        }
        if not required <= set(row):
            errors.append("legacy metric {} is missing required fields".format(name))
        for field in ("legacy_metric_name", "legacy_source", "deprecation_status", "transition_requirement", "earliest_removal_phase", "safety_notes"):
            if not isinstance(row.get(field), str) or not row.get(field):
                errors.append("legacy metric {} {} must be a non-empty string".format(name, field))
        inventory_tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9_]+", name)]
        inventory_match = inventory_tokens and all(token in legacy_text.lower() for token in inventory_tokens)
        if name not in aliases and name not in deprecated_names and name not in legacy_text and not inventory_match:
            errors.append("unknown legacy metric {}".format(name))
        if row.get("deprecation_status") not in DEPRECATION_STATUSES:
            errors.append("legacy metric {} has forbidden/unknown deprecation status".format(name))
        reasons = row.get("reason_codes")
        if not isinstance(reasons, list) or not reasons or not set(reasons) <= REASON_CODES:
            errors.append("legacy metric {} has invalid reason_codes".format(name))
        replacements = row.get("canonical_replacements")
        if not isinstance(replacements, list) or any(not isinstance(value, str) or value not in catalog_rows for value in replacements):
            errors.append("legacy metric {} has unknown canonical replacement".format(name))
        if not replacements and row.get("deprecation_status") not in {"blocked_missing_exact_replacement", "retain_diagnostic_until_replacement", "already_non_authoritative"}:
            errors.append("legacy metric {} without replacement must be retained or blocked".format(name))
        consumers = row.get("known_consumers")
        if not isinstance(consumers, list) or any(
            not isinstance(c, dict) or set(c) != {"path", "consumer_type"}
            or not isinstance(c.get("path"), str) or not c.get("path")
            or c.get("consumer_type") not in {"runtime", "report", "test", "documentation_only"}
            for c in consumers
        ):
            errors.append("legacy metric {} has invalid consumers".format(name))
        if any(isinstance(c, dict) and c.get("consumer_type") == "runtime" for c in consumers or []):
            if row.get("earliest_removal_phase") in {"phase_0", "phase_1", "immediate", "now"}:
                errors.append("runtime legacy metric {} cannot be removed immediately".format(name))

    guard_rows = _unique(baseline.get("stabilized_guardrails"), "guardrail_id", "guardrail", errors)
    for name, row in guard_rows.items():
        if row.get("status") != "stabilized" or row.get("introduced_before_a4") is not True:
            errors.append("guardrail {} is not confirmed stabilized before A4".format(name))
        for evidence in row.get("evidence_files", []):
            if not (ROOT / evidence).is_file():
                errors.append("guardrail {} evidence file does not exist: {}".format(name, evidence))
    gap_rows = _unique(baseline.get("known_phase1_gaps"), "gap_id", "Phase 1 gap", errors)
    if any(row.get("blocks_phase0") is not False for row in gap_rows.values()):
        errors.append("Phase 1 diagnostic gaps must not block Phase 0")
    completion = baseline.get("phase0_completion", {})
    for field in ("metrics_catalog_v1", "event_schema_v1", "artifact_manifest_schema_v1", "baseline_report_v1", "legacy_metric_deprecation_registry_v1"):
        if completion.get(field) != "complete":
            errors.append("phase0_completion.{} must be complete".format(field))
    if completion.get("phase1_ready") is not True or completion.get("known_blockers") != []:
        errors.append("validated Phase 0 must be phase1_ready with no Phase 0 blockers")

    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append("cannot load Markdown {}: {}".format(markdown_path, exc))
    else:
        expected = {
            "SOURCE_WINDOWS": baseline.get("source_windows"),
            "METRIC_BASELINES": baseline.get("metric_baselines"),
            "DEPRECATIONS": registry.get("entries"),
            "GUARDRAILS": baseline.get("stabilized_guardrails"),
            "PHASE1_GAPS": baseline.get("known_phase1_gaps"),
            "PHASE0_COMPLETION": completion,
        }
        for section, value in expected.items():
            if _markdown_rows(markdown, section, errors) != value:
                errors.append("Markdown {} block does not exactly match JSON".format(section))
    return errors


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", nargs="?", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("registry", nargs="?", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--event-schema", type=Path, default=DEFAULT_EVENT)
    parser.add_argument("--artifact-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--legacy-inventory", type=Path, default=DEFAULT_LEGACY)
    args = parser.parse_args(argv)
    errors = validate(args.baseline, args.registry, args.catalog, args.event_schema, args.artifact_manifest, args.markdown, args.legacy_inventory)
    if errors:
        print("Phase 0 baseline invalid ({} error(s)):".format(len(errors)), file=sys.stderr)
        for error in errors:
            print("- " + error, file=sys.stderr)
        return 1
    count = len(json.loads(args.baseline.read_text(encoding="utf-8"))["metric_baselines"])
    print("Phase 0 baseline valid: {} A1 metric rows".format(count))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
