import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agents import gemini_ledger
from agents import archivista
from agents.gemini_diagnostics import (
    build_email_gemini_summary,
    build_gemini_diagnostics,
    build_gemini_economic_truth,
    load_ledger,
    render_gemini_diagnostics_markdown,
)
from agents.gemini_ledger import calculate_v96_2_cost, extract_usage_metadata, load_pricing_table, resolve_pricing_model
from owtv_report import render_gemini_detailed_ledger_24h
from scripts.daily_editorial_judgment import _render_gemini_economic_lines
from scripts.observability_snapshot import build_snapshot


def usage(**overrides):
    base = {"usage_available": True, "input_tokens": 100, "cached_input_tokens": 20,
            "output_tokens": 10, "thinking_tokens": 5, "total_tokens": 115,
            "total_tokens_provider_reported": True}
    base.update(overrides)
    return base


def resolved_row(**overrides):
    model = overrides.pop("actual_model", "gemini-2.5-flash")
    cost = calculate_v96_2_cost(usage(), model)
    row = {"status": "called", "ledger_schema_version": "v3", "provider_attempt_id": "attempt-1",
           "actual_model": model, "model_requested": model, "agent": "Bob", "reason": "translation", **cost}
    row.update(overrides)
    return row


def test_all_six_frozen_model_rates_and_metadata():
    table = load_pricing_table()
    assert table["schema_version"] == "v96.2_pricing.v2"
    assert table["price_table_version"] == "google-gemini-paid-standard-2026-08-22.v1"
    assert table["source_url"] == "https://ai.google.dev/gemini-api/docs/pricing"
    expected = {
        "gemini-3.5-flash": ("1.50", "9.00", "0.15"),
        "gemini-3.1-flash-lite": ("0.25", "1.50", "0.025"),
        "gemini-3-flash-preview": ("0.50", "3.00", "0.05"),
        "gemini-2.5-flash": ("0.30", "2.50", "0.03"),
        "gemini-2.5-flash-lite": ("0.10", "0.40", "0.01"),
    }
    for model, rates in expected.items():
        conf = table["models"][model]
        assert tuple(conf[k] for k in ("input_price_per_million", "output_price_per_million", "cached_input_price_per_million")) == rates
    assert [(x["input_price_per_million"], x["output_price_per_million"], x["cached_input_price_per_million"]) for x in table["models"]["gemini-2.5-pro"]["tiers"]] == [("1.25", "10.00", "0.125"), ("2.50", "15.00", "0.25")]
    assert table["aliases"] == {} and "gemini-3.5-flash-lite" not in table["models"]
    assert resolve_pricing_model("unknown", table)[1] is None


def test_cached_and_thinking_charged_once_and_pro_tier_uses_full_prompt():
    result = calculate_v96_2_cost(usage(), "gemini-3.1-flash-lite")
    expected = Decimal(80)*Decimal("0.25")/1_000_000 + Decimal(20)*Decimal("0.025")/1_000_000 + Decimal(15)*Decimal("1.50")/1_000_000
    assert result["non_cached_input_tokens"] == 80
    assert Decimal(result["computed_list_price_cost"]) == expected
    low = calculate_v96_2_cost(usage(input_tokens=200000, cached_input_tokens=199999, total_tokens=200015), "gemini-2.5-pro")
    high = calculate_v96_2_cost(usage(input_tokens=200001, cached_input_tokens=200000, total_tokens=200016), "gemini-2.5-pro")
    assert Decimal(low["computed_non_cached_input_cost"]) == Decimal("0.00000125")
    assert Decimal(high["computed_non_cached_input_cost"]) == Decimal("0.0000025")
    assert Decimal(low["computed_cached_input_cost"]) == Decimal(199999)*Decimal("0.125")/1_000_000
    assert Decimal(high["computed_candidate_output_cost"]) == Decimal(10)*Decimal("15")/1_000_000


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "cached_input_tokens", "thinking_tokens"])
def test_negative_token_counters_invalid(field):
    assert calculate_v96_2_cost(usage(**{field: -1}), "gemini-2.5-flash")["usage_resolution_reason"] == "usage_invalid"


def test_cached_greater_than_prompt_invalid():
    assert calculate_v96_2_cost(usage(cached_input_tokens=101), "gemini-2.5-flash")["usage_resolution_reason"] == "usage_invalid"


@pytest.mark.parametrize("provider_name,state_key", [("prompt_token_count", "input_tokens"), ("candidates_token_count", "output_tokens"), ("total_token_count", "total_tokens"), ("cached_content_token_count", "cached_input_tokens"), ("thoughts_token_count", "thinking_tokens")])
def test_malformed_optional_provider_field_is_invalid_not_derived(provider_name, state_key):
    meta = {"prompt_token_count": 10, "candidates_token_count": 2, "total_token_count": 12, provider_name: "bad"}
    extracted = extract_usage_metadata({"usage_metadata": meta})
    assert extracted["token_field_states"][state_key] == "present_malformed"
    result = calculate_v96_2_cost(extracted, "gemini-2.5-flash")
    assert result["usage_resolution_reason"] == "usage_invalid"
    assert not result["cached_input_tokens_zero_normalized"]
    assert not result["thinking_tokens_derived"]


def test_malformed_total_with_explicit_thinking_is_invalid_and_not_legacy_derived():
    extracted = extract_usage_metadata({"usage_metadata": {"prompt_token_count": 10, "candidates_token_count": 2,
        "thoughts_token_count": 3, "total_token_count": "bad"}})
    assert extracted["token_field_states"]["total_tokens"] == "present_malformed"
    assert extracted["total_tokens_legacy_derived"] is False
    result = calculate_v96_2_cost(extracted, "gemini-2.5-flash")
    assert result["usage_resolution_status"] == "unresolved" and result["usage_resolution_reason"] == "usage_invalid"


def test_total_and_thinking_semantics_are_separate_from_legacy_total():
    explicit_no_total = calculate_v96_2_cost(usage(total_tokens=None, total_tokens_provider_reported=False), "gemini-2.5-flash")
    assert explicit_no_total["cost_resolution_status"] == "resolved"
    missing_both = calculate_v96_2_cost(usage(total_tokens=None, thinking_tokens=None, total_tokens_provider_reported=False), "gemini-2.5-flash")
    assert missing_both["usage_resolution_status"] == "unresolved"
    correct = calculate_v96_2_cost(usage(), "gemini-2.5-flash")
    assert correct["cost_resolution_status"] == "resolved"
    mismatch = calculate_v96_2_cost(usage(total_tokens=116), "gemini-2.5-flash")
    assert mismatch["usage_resolution_reason"] == "usage_invalid"
    legacy_total = calculate_v96_2_cost(usage(total_tokens=110, total_tokens_provider_reported=False, total_tokens_legacy_derived=True), "gemini-2.5-flash")
    assert legacy_total["cost_resolution_status"] == "resolved"


def test_model_service_tier_and_modality_resolution():
    assert calculate_v96_2_cost(usage(), "unknown", "gemini-2.5-flash")["cost_resolution_reason"] == "model_unresolved"
    requested = calculate_v96_2_cost(usage(), None, "gemini-2.5-flash")
    assert requested["pricing_identity_source"] == "model_requested"
    explicit = calculate_v96_2_cost(usage(service_tier="standard"), "gemini-2.5-flash")
    assert explicit["pricing_service_tier_source"] == "provider_usage"
    default = calculate_v96_2_cost(usage(), "gemini-2.5-flash")
    assert default["pricing_service_tier_source"] == "runtime_default_standard"
    assert calculate_v96_2_cost(usage(service_tier="flex"), "gemini-2.5-flash")["cost_resolution_reason"] == "price_class_unresolved"
    assert calculate_v96_2_cost(usage(modality="image"), "gemini-2.5-flash")["cost_resolution_reason"] == "mixed_or_unresolved_modality"


@pytest.mark.parametrize(("tier", "resolved", "source"), [
    ("standard", True, "provider_usage"),
    ("unspecified", True, "provider_usage_default_standard"),
    ("flex", False, "provider_usage"),
    ("priority", False, "provider_usage"),
    ("SERVICE_TIER_STANDARD", True, "provider_usage"),
    ("SERVICE_TIER_UNSPECIFIED", True, "provider_usage_default_standard"),
    ("SERVICE_TIER_FLEX", False, "provider_usage"),
    ("SERVICE_TIER_PRIORITY", False, "provider_usage"),
    ("future_paid_class", False, "provider_usage"),
])
def test_service_tier_string_normalization(tier, resolved, source):
    result = calculate_v96_2_cost(usage(service_tier=tier), "gemini-2.5-flash")
    assert (result["cost_resolution_status"] == "resolved") is resolved
    assert result["pricing_service_tier_source"] == source
    if resolved:
        assert result["pricing_service_tier"] == "standard"
    else:
        assert result["cost_resolution_reason"] == "price_class_unresolved"


@pytest.mark.parametrize(("value", "source"), [("standard", "provider_usage"), ("unspecified", "provider_usage_default_standard")])
def test_enum_like_service_tier_is_normalized_during_extraction(value, source):
    class Tier:
        def __init__(self, raw):
            self.value = raw

        def __str__(self):
            return f"ServiceTier.{self.value.upper()}"

    extracted = extract_usage_metadata({"usage_metadata": {"prompt_token_count": 10, "candidates_token_count": 2,
        "thoughts_token_count": 0, "service_tier": Tier(value)}})
    assert extracted["service_tier"] == value
    result = calculate_v96_2_cost(extracted, "gemini-2.5-flash")
    assert result["cost_resolution_status"] == "resolved"
    assert result["pricing_service_tier"] == "standard"
    assert result["pricing_service_tier_source"] == source


def test_absent_service_tier_uses_runtime_default_standard():
    result = calculate_v96_2_cost(usage(service_tier=None), "gemini-2.5-flash")
    assert result["cost_resolution_status"] == "resolved"
    assert result["pricing_service_tier"] == "standard"
    assert result["pricing_service_tier_source"] == "runtime_default_standard"


def test_failure_usage_attempt_grain_and_avoided_semantics():
    rows = [resolved_row(status="failed", provider_attempt_id="fail-used"),
            {"status": "failed", "ledger_schema_version": "v3", "provider_attempt_id": "fail-empty", "usage_resolution_status": "unresolved", "cost_resolution_status": "unresolved"},
            resolved_row(provider_attempt_id="retry", retry=True), resolved_row(provider_attempt_id="fallback", fallback=True),
            resolved_row(provider_attempt_id="repair", repair=True), {"status": "avoided", "observed_provider_cost": "0"}]
    truth = build_gemini_economic_truth(rows, available=True)
    assert truth["real_attempts"] == 5 and truth["computed_cost_resolved_attempts"] == 4
    assert truth["diagnostics"]["failed_with_usage"] == 1 and truth["diagnostics"]["failed_without_usage"] == 1
    assert (truth["diagnostics"]["retry_attempts"], truth["diagnostics"]["fallback_attempts"], truth["diagnostics"]["repair_attempts"]) == (1, 1, 1)
    assert "counterfactual" not in json.dumps(truth)


def test_recorded_provider_attempt_ids_unique_and_no_legacy_estimates(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", tmp_path / "state" / "ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", tmp_path / "artifacts" / "latest.json")
    response = {"usage_metadata": {"prompt_token_count": 1, "candidates_token_count": 1, "thoughts_token_count": 0}}
    for flag in ({"retry": True}, {"fallback": True}, {"repair": True}):
        gemini_ledger.record_gemini_attempt(response=response, model_requested="gemini-2.5-flash", status="called", operation_id="same", **flag)
    rows = [json.loads(x) for x in gemini_ledger.LEDGER_FILE.read_text().splitlines()]
    assert len({x["provider_attempt_id"] for x in rows}) == 3
    assert {x["operation_id"] for x in rows} == {"same"}
    assert all(x.get("estimated_cost") is None and x["legacy_estimated_cost_authoritative"] is False for x in rows)


def test_straddling_window_preserves_usage_but_not_legacy_cost():
    legacy = {"status": "called", "ledger_schema_version": "v2", "usage_available": True, "input_tokens": 4, "output_tokens": 2, "total_tokens": 6,
              "estimated_cost": "999", "model_requested": "gemini-2.5-flash", "agent": "Bob", "reason": "translation"}
    forward = resolved_row()
    truth = build_gemini_economic_truth([legacy, forward], available=True)
    assert truth["real_attempts"] == 2 and truth["provider_usage_resolved_attempts"] == 2
    assert truth["provider_usage_coverage"] == 1 and truth["computed_cost_coverage"] == .5
    assert truth["known_computed_list_price_cost"] == forward["computed_list_price_cost"]
    assert truth["complete_window_computed_list_price_cost"] is None


def test_resolved_row_integrity_malformed_cost_and_versions_and_currency():
    malformed = resolved_row(computed_list_price_cost="not-money")
    bad = build_gemini_economic_truth([malformed], available=True)
    assert bad["computed_cost_resolved_attempts"] == 0 and bad["unknown_computed_cost_attempts"] == 1
    assert bad["complete_window_computed_list_price_cost"] is None
    assert bad["diagnostics"]["economic_row_integrity_reasons"] == {"resolved_row_integrity_invalid_cost": 1}
    a = resolved_row(provider_attempt_id="a", price_table_version="table-a", pricing_currency="USD")
    b = resolved_row(provider_attempt_id="b", price_table_version="table-b", pricing_currency="EUR")
    mixed = build_gemini_economic_truth([a, b], available=True)
    assert mixed["price_table_version"] == "mixed" and mixed["price_table_versions"] == ["table-a", "table-b"]
    assert mixed["currency"] == "mixed" and mixed["complete_window_computed_list_price_cost"] is None


def test_breakdowns_reconcile_without_operation_id_deduplication():
    rows = [resolved_row(provider_attempt_id="a", operation_id="same", agent="Bob", reason="translate"),
            resolved_row(provider_attempt_id="b", operation_id="same", agent="Menzo", reason="repair", actual_model="gemini-3.1-flash-lite")]
    truth = build_gemini_economic_truth(rows, available=True)
    assert truth["real_attempts"] == 2
    for dimension in ("by_model", "by_agent", "by_reason"):
        values = truth["breakdowns"][dimension].values()
        assert sum(x["attempts"] for x in values) == 2
        assert sum(Decimal(x["known_computed_list_price_cost"]) for x in values) == Decimal(truth["known_computed_list_price_cost"])


def test_readable_empty_missing_and_malformed_ledgers(tmp_path):
    readable = tmp_path / "empty.jsonl"; readable.write_text("")
    records, warnings, meta = load_ledger(readable, return_metadata=True, strict_bounded=True)
    assert meta["readable"] and not warnings
    empty = build_gemini_economic_truth(records, available=True)
    assert empty["coverage"] == "full" and empty["complete_window"] is True
    assert empty["real_attempts"] == empty["provider_usage_resolved_attempts"] == empty["computed_cost_resolved_attempts"] == 0
    assert empty["provider_usage_coverage"] is None and empty["computed_cost_coverage"] is None
    assert empty["known_computed_list_price_cost"] == empty["complete_window_computed_list_price_cost"] == "0"
    missing_records, _, missing_meta = load_ledger(tmp_path / "missing", return_metadata=True, strict_bounded=True)
    missing = build_gemini_economic_truth(missing_records, available=missing_meta["readable"])
    for field in ("real_attempts", "provider_usage_resolved_attempts", "provider_usage_coverage", "computed_cost_resolved_attempts", "computed_cost_coverage", "unknown_computed_cost_attempts", "known_computed_list_price_cost", "complete_window_computed_list_price_cost"):
        assert missing[field] is None
    assert missing["coverage"] == "unavailable" and missing["breakdowns"] == {}
    malformed_path = tmp_path / "bad.jsonl"; malformed_path.write_text("{bad}\n")
    bad_records, _, bad_meta = load_ledger(malformed_path, return_metadata=True, strict_bounded=True)
    malformed = build_gemini_economic_truth(bad_records, available=bad_meta["readable"] and bad_meta["malformed_rows"] == 0)
    assert malformed["available"] is False and malformed["known_computed_list_price_cost"] is None


def test_economic_coverage_partial_and_full():
    full = build_gemini_economic_truth([resolved_row()], available=True)
    partial = build_gemini_economic_truth([resolved_row(), {"status": "failed", "ledger_schema_version": "v3"}], available=True)
    assert full["coverage"] == "full" and full["complete_window"] is True
    assert partial["coverage"] == "partial" and partial["complete_window"] is False


def test_archivista_propagates_authority_availability(monkeypatch):
    healthy = resolved_row()
    monkeypatch.setattr(archivista, "load_ledger", lambda **kwargs: ([healthy], [], {"readable": True, "malformed_rows": 0, "undated_rows": 0}))
    diag, _ = archivista._load_authoritative_gemini_diagnostics()
    assert diag["economic"]["available"] is True and diag["economic"]["coverage"] == "full"
    monkeypatch.setattr(archivista, "load_ledger", lambda **kwargs: ([], ["missing"], {"readable": False, "malformed_rows": 0, "undated_rows": 0}))
    unavailable, _ = archivista._load_authoritative_gemini_diagnostics()
    rendered = render_gemini_diagnostics_markdown(unavailable)
    assert unavailable["economic"]["real_attempts"] is None
    assert "known computed paid-tier Standard list-price cost: n.d. n.d." in rendered


def test_operational_and_email_render_authority_and_unavailable_nd(tmp_path):
    missing = tmp_path / "missing.jsonl"
    markdown = render_gemini_detailed_ledger_24h(ledger_path=missing)
    assert markdown.count("### AUTHORITATIVE Gemini economic truth") == 1
    assert "### NON-AUTHORITATIVE legacy call and usage diagnostics" in markdown
    assert "known computed paid-tier Standard list-price cost: n.d. n.d." in markdown
    diag = build_gemini_diagnostics([], economic_available=False)
    email = build_email_gemini_summary(diag)
    assert "Known paid-tier Standard list-price cost: n.d. n.d." in email
    assert "Complete-window computed cost: n.d." in email
    assert "$0" not in email
    judgment = "\n".join(_render_gemini_economic_lines({"real_attempts": 2, "provider_usage_coverage": 1.0,
        "computed_cost_coverage": .5, "known_computed_list_price_cost": "0.001", "complete_window_computed_list_price_cost": None,
        "unknown_computed_cost_attempts": 1, "currency": "USD", "price_table_version": "table-a"}))
    assert "provider usage coverage / computed cost coverage: 100.0% / 50.0%" in judgment
    assert "complete-window computed list-price cost: n.d. USD" in judgment


def test_observability_snapshot_enforces_whole_ledger_integrity(tmp_path):
    now = datetime.now(timezone.utc)
    ledger = tmp_path / "state/newsroom/gemini_call_ledger.jsonl"
    ledger.parent.mkdir(parents=True)

    valid = resolved_row(timestamp=now.isoformat())
    ledger.write_text(json.dumps(valid) + "\n", encoding="utf-8")
    healthy = build_snapshot(now - timedelta(hours=1), now, tmp_path)
    assert healthy["section_metadata"]["gemini"]["available"] is True
    assert healthy["gemini"]["economic"]["available"] is True

    ledger.write_text(json.dumps(valid) + "\n{malformed}\n", encoding="utf-8")
    corrupt = build_snapshot(now - timedelta(hours=1), now, tmp_path)
    assert corrupt["section_metadata"]["gemini"]["available"] is False
    assert corrupt["gemini"]["economic"]["available"] is False
    assert corrupt["gemini"]["economic"]["known_computed_list_price_cost"] is None
    assert corrupt["gemini"]["economic"]["complete_window_computed_list_price_cost"] is None

    ledger.write_text("", encoding="utf-8")
    empty = build_snapshot(now - timedelta(hours=1), now, tmp_path)
    assert empty["section_metadata"]["gemini"]["available"] is True
    assert empty["gemini"]["economic"]["real_attempts"] == 0
    assert empty["gemini"]["economic"]["complete_window_computed_list_price_cost"] == "0"
