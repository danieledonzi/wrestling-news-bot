from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_metrics_catalog import AVAILABILITIES, REQUIRED_FIELDS, STATUSES, validate

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "config" / "metrics_catalog_v1.json"
MARKDOWN_PATH = ROOT / "docs" / "runtime" / "OWTV_METRICS_CATALOG.md"
LEGACY_PATH = ROOT / "docs" / "runtime" / "OWTV_METRICS_LEGACY_INVENTORY.md"


def catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def by_name():
    return {row["canonical_name"]: row for row in catalog()["metrics"]}


def test_json_is_valid_and_validator_accepts_contract():
    payload = catalog()
    assert payload["schema_version"] == "owtv_metrics_catalog_v1"
    assert payload["policy_version"] == "v95.22_a1"
    assert validate(CATALOG_PATH, MARKDOWN_PATH) == []


def test_names_unique_and_required_fields_complete():
    rows = catalog()["metrics"]
    names = [row["canonical_name"] for row in rows]
    assert len(names) == len(set(names))
    assert all(REQUIRED_FIELDS <= row.keys() for row in rows)


def test_enums_and_aliases_are_valid_without_collisions():
    rows = catalog()["metrics"]
    names = {row["canonical_name"] for row in rows}
    aliases = {}
    for row in rows:
        assert row["status"] in STATUSES
        assert row["availability"] in AVAILABILITIES
        for alias in row["legacy_aliases"]:
            assert alias not in names
            assert alias not in aliases or aliases[alias] == row["canonical_name"]
            aliases[alias] = row["canonical_name"]


def test_active_metrics_have_authority_formula_and_distinct_zero_missing():
    for row in catalog()["metrics"]:
        if row["status"] != "active":
            continue
        assert row["availability"] == "available"
        assert row["source_primary"] not in {"", "not_available"}
        assert row["formula"] not in {"", "not currently defined"}
        assert row["time_window"]
        assert row["zero_semantics"]
        assert row["missing_semantics"]
        assert row["zero_semantics"] != row["missing_semantics"]
        assert "Zero" in row["zero_semantics"]
        assert "Null" in row["missing_semantics"]


def test_frozen_v9519_boundary_semantics_are_explicit():
    rows = by_name()
    ratio = rows["menzo.handoff_to_publication_ratio"]
    assert "greater than zero" in ratio["zero_semantics"]
    assert "overlap equals zero" in ratio["zero_semantics"]
    assert "denominator is zero or absent" in ratio["missing_semantics"]
    assert "identity linkage is not supported" in ratio["missing_semantics"]

    actionable = rows["menzo.unique_actionable_candidates"]
    assert "pending sample ambiguously truncated" in actionable["missing_semantics"]
    warnings = rows["alfred.warning_occurrences"]
    assert "exactly ten entries" in warnings["missing_semantics"]
    assert "without an authoritative warning_occurrences_total" in warnings["missing_semantics"]
    overlap = rows["menzo.linked_handoff_publication_overlap"]
    assert "no identity namespace is shared by all" in overlap["missing_semantics"]


def test_duplicate_coverage_complete_has_boolean_coverage_semantics():
    row = by_name()["menzo.duplicate_coverage_complete"]
    assert row["unit"] == "boolean"
    assert row["entity_counted"] == "producing-run duplicate pair matrix coverage state"
    assert row["entity_counted"] != "events"
    assert row["zero_semantics"].startswith("False means")
    assert "pair coverage is incomplete" in row["zero_semantics"]
    assert "no qualifying entities" not in row["zero_semantics"].lower()
    assert "artifact is absent or unreadable" in row["missing_semantics"]
    assert "membership in the observed producing run cannot be verified" in row["missing_semantics"]


def test_latest_run_metrics_never_claim_editorial_window_cardinality():
    for row in catalog()["metrics"]:
        if "latest-run" not in row["aggregation"]:
            continue
        assert row["status"] == "diagnostic_only"
        assert row["cardinality"] == "one scalar per producing run/latest retained artifact"
        assert "no authoritative editorial-window series exists" in row["time_window"]
        assert "inclusive UTC" not in row["time_window"]
        assert "membership in the observed producing run cannot be verified" in row["missing_semantics"]


def test_high_risk_legacy_inventory_is_present():
    text = LEGACY_PATH.read_text(encoding="utf-8")
    required = [
        "`selected`", "`pending`", "`skipped`", "`warnings`", "`warning_count`",
        "warning event", "warning occurrence", "`called_total`", "`called_35_total`",
        "`gemini_3_5_called_total`", "`status=called`", "Simone `errors`",
        "Publisher `errors`", "`published`", "`already`, `already_published`",
        "`wp_not_ready`", "`footprint`", "`fingerprint`", "`ai_duplicate_arbitration_calls`",
        "`gemini_calls_used_for_duplicate_arbitration`", "`duplicate_pair_coverage`",
        "`duplicate_pair_terminal_invariant_failures`", "expected runtime dirt",
        "unexpected runtime dirt",
    ]
    assert all(value in text for value in required)


def test_v9519_canonical_names_are_preserved():
    names = by_name()
    frozen = {
        "menzo.unique_actionable_candidates", "menzo.unique_downstream_handoffs",
        "menzo.unique_final_publications", "menzo.linked_handoff_publication_overlap",
        "menzo.handoff_to_publication_ratio", "alfred.unique_articles_reviewed",
        "alfred.unique_articles_with_warnings", "alfred.warning_events",
        "alfred.warning_occurrences", "alfred.unique_final_blockers", "gemini.real_attempts",
        "gemini.completed_calls", "gemini.failures", "gemini.avoided_calls",
        "gemini.fallbacks", "simone.reports_published", "simone.already_present_events",
    }
    assert frozen <= names.keys()
    assert all(names[name]["status"] == "active" for name in frozen)


def test_markdown_lists_every_active_metric():
    text = MARKDOWN_PATH.read_text(encoding="utf-8")
    for row in catalog()["metrics"]:
        if row["status"] == "active":
            assert "`{}`".format(row["canonical_name"]) in text


def test_unmeasurable_families_are_planned_and_unavailable():
    rows = by_name()
    required = {
        "simone.reports_due", "simone.reports_missing", "simone.reports_ambiguous",
        "simone.terminal_errors", "simone.sla_violations", "publisher.recoverable_errors",
        "publisher.terminal_errors", "wordpress.preflight_attempts", "wordpress.endpoint_probes",
        "wordpress.terminal_failures", "bob.logical_translation_requests", "bob.model_successes",
    }
    for name in required:
        assert rows[name]["status"] == "planned"
        assert rows[name]["availability"] == "unavailable"


def test_unsupported_andrea_unique_metrics_are_not_event_sums():
    rows = by_name()
    for name in ("andrea.checked_unique", "andrea.passed_unique", "andrea.blocked_unique"):
        row = rows[name]
        assert row["status"] == "planned"
        assert row["availability"] == "unavailable"
        assert row["formula"] == "not currently defined"
        assert "only per-run events" in row["notes"]
    for name in ("andrea.checked_events", "andrea.passed_events", "andrea.blocked_events"):
        assert rows[name]["status"] == "diagnostic_only"
        assert rows[name]["availability"] == "partially_available"


def test_massy_handoffs_and_simone_event_identity_are_not_unique_errors():
    rows = by_name()
    assert "Unique" not in rows["massy.actionable_handoffs"]["description"]
    assert "Per-run" in rows["massy.actionable_handoffs"]["description"]
    assert rows["simone.already_present_events"]["identity_key"] == (
        "report publication event row; stable report/source identity when available"
    )


def test_markdown_contract_tables_match_json_exactly():
    assert validate(CATALOG_PATH, MARKDOWN_PATH) == []
    markdown = MARKDOWN_PATH.read_text(encoding="utf-8")
    assert markdown.count("| `selected` | `menzo.selected_after_budget` |") == 1
    assert "| `selected` | `menzo.unique_downstream_handoffs` |" not in markdown
    assert "menzo.selected` is instead the authoritative source field" in markdown


def test_validator_rejects_markdown_alias_collision(tmp_path):
    markdown = MARKDOWN_PATH.read_text(encoding="utf-8").replace(
        "| `selected` | `menzo.selected_after_budget` |",
        "| `selected` | `menzo.unique_downstream_handoffs` |\n"
        "| `selected` | `menzo.selected_after_budget` |",
    )
    path = tmp_path / "catalog.md"
    path.write_text(markdown, encoding="utf-8")
    errors = validate(CATALOG_PATH, path)
    assert any("points to both" in error for error in errors)


def test_validator_rejects_markdown_status_and_replacement_drift(tmp_path):
    markdown = MARKDOWN_PATH.read_text(encoding="utf-8")
    markdown = markdown.replace("| `andrea.checked_unique` | unavailable |", "| `andrea.checked_WRONG` | unavailable |")
    markdown = markdown.replace(
        "| `gemini.completed_successful_calls` | `gemini.completed_calls` |",
        "| `gemini.completed_successful_calls` | `gemini.failures` |",
    )
    path = tmp_path / "catalog.md"
    path.write_text(markdown, encoding="utf-8")
    errors = validate(CATALOG_PATH, path)
    assert "Markdown planned table does not match JSON planned metrics" in errors
    assert "Markdown deprecated table/replacements do not match JSON" in errors


def test_generic_errors_are_not_promoted_to_terminal_errors():
    rows = by_name()
    assert rows["simone.legacy_errors_diagnostic"]["status"] == "diagnostic_only"
    assert rows["simone.legacy_errors_diagnostic"]["legacy_aliases"] == ["errors"]
    assert rows["simone.terminal_errors"]["source_primary"] == "not_available"
    assert rows["publisher.terminal_errors"]["source_primary"] == "not_available"
    assert all(not row["canonical_name"].endswith(".errors") for row in rows.values())


def test_gemini_called_is_not_semantic_success():
    rows = by_name()
    completed = rows["gemini.completed_calls"]
    assert "not semantic success" in completed["description"]
    assert "called_total" in completed["legacy_aliases"]
    legacy = LEGACY_PATH.read_text(encoding="utf-8")
    assert "API returned without an attempt exception" in legacy
    assert "not that the content was usable or semantically correct" in legacy


def test_simone_terminal_errors_remain_null_unavailable_until_typed():
    row = by_name()["simone.terminal_errors"]
    assert row["status"] == "planned"
    assert row["availability"] == "unavailable"
    assert row["source_primary"] == "not_available"
    assert "Generic handoff errors" in row["notes"]


def test_a1_changes_only_measurement_contract_files():
    # A guard on the intended patch surface: this test itself cannot inspect a Git parent,
    # so it asserts that no catalog module is imported by the newsroom runner.
    runtime = (ROOT / "newsroom_runner.py").read_text(encoding="utf-8")
    assert "metrics_catalog_v1" not in runtime
    assert "validate_metrics_catalog" not in runtime
