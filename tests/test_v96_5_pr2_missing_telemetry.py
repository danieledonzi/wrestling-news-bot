from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.daily_editorial_judgment import _render_pr131_lines, email_summary
from scripts.observability_snapshot import build_pr131_cache_metrics

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(hours=24)


def event(kind, *, ts=None, result=None, reason=None, pair_id=None, agent="Menzo"):
    row = {
        "timestamp_utc": (ts or NOW - timedelta(hours=1)).isoformat(),
        "run_id": "run",
        "event_type": kind,
        "agent": agent,
        "stage": "duplicate" if kind.startswith("duplicate_pair_cache") else "model",
        "status": "success",
        "artifact_refs": [],
    }
    if result is not None:
        row["result"] = result
    if reason is not None:
        row["reason_code"] = reason
    if pair_id is not None:
        row["pair_id"] = pair_id
    return row


def test_pr131_read_model_full_coverage_keeps_pair_and_call_grains_distinct():
    rows = [
        event("duplicate_pair_cache_observed", ts=SINCE - timedelta(minutes=1), result="loaded"),
        event("duplicate_pair_cache_observed", result="loaded"),
        event("duplicate_pair_cache_lookup", result="hit", pair_id="p1"),
        event("duplicate_pair_cache_lookup", result="hit", pair_id="p2"),
        event("duplicate_pair_cache_lookup", result="miss", pair_id="p3"),
        event("duplicate_pair_cache_stored", result="stored", pair_id="p3"),
        event("model_attempt_avoided", reason="pr131_duplicate_pair_cache_gate_full_hit", agent="Gemini"),
    ]
    gemini = [
        {
            "timestamp": (NOW - timedelta(minutes=55)).isoformat(),
            "agent": "Menzo", "status": "avoided",
            "reason": "pr131_duplicate_pair_cache_gate_full_hit",
            "logical_request_id": "lrq-avoid",
        },
        {
            "timestamp": (NOW - timedelta(minutes=40)).isoformat(),
            "agent": "Menzo", "status": "called",
            "workload": "editorial_director_duplicate_gate",
            "provider_attempt_id": "a1", "estimated_cost": "0.0012",
        },
        {
            "timestamp": (NOW - timedelta(minutes=30)).isoformat(),
            "agent": "Menzo", "status": "called",
            "workload": "editorial_director_duplicate_confirmation",
            "provider_attempt_id": "a2", "estimated_cost": "0.0008",
        },
    ]
    result, meta = build_pr131_cache_metrics(
        rows, gemini, SINCE, NOW, canonical_healthy=True, gemini_available=True
    )
    assert meta["complete_window"] is True
    assert result["coverage"] == "full"
    assert result["lookups"] == 3
    assert result["hits"] == 2
    assert result["misses"] == 1
    assert result["hit_rate"] == 2 / 3
    assert result["entries_stored"] == 1
    # Two pair hits saved one logical provider call, not two.
    assert result["provider"]["gemini_calls_avoided"] == 1
    assert result["provider"]["duplicate_gate_real_attempts"] == 1
    assert result["provider"]["duplicate_confirmation_real_attempts"] == 1
    assert result["provider"]["known_actual_cost"] == "0.0020"
    assert result["diagnostic_mismatches"] == []


def test_pr131_partial_coverage_never_turns_observed_counts_into_authoritative_zeroes():
    rows = [
        event("duplicate_pair_cache_observed", ts=NOW - timedelta(hours=2), result="loaded"),
        event("duplicate_pair_cache_lookup", result="hit", pair_id="p1"),
    ]
    result, meta = build_pr131_cache_metrics(
        rows, [], SINCE, NOW, canonical_healthy=True, gemini_available=True
    )
    assert meta["complete_window"] is False
    assert result["coverage"] == "partial"
    assert result["hits"] is None
    assert result["lookups"] is None
    assert result["observed_window"]["hits"] == 1
    assert result["provider"]["gemini_calls_avoided"] is None
    assert result["provider"]["observed_gemini_calls_avoided"] == 0


def test_pr131_cross_ledger_avoided_call_mismatch_is_diagnostic():
    rows = [
        event("duplicate_pair_cache_observed", ts=SINCE - timedelta(minutes=1), result="loaded"),
        event("model_attempt_avoided", reason="pr131_duplicate_pair_cache_gate_full_hit", agent="Gemini"),
    ]
    result, _ = build_pr131_cache_metrics(
        rows, [], SINCE, NOW, canonical_healthy=True, gemini_available=True
    )
    assert result["diagnostic_mismatches"] == [
        "pr131_avoided_call_ledger_mismatch:canonical=1:gemini=0"
    ]


def test_pr131_report_section_labels_actual_cost_and_avoided_calls_without_fake_savings():
    pr131 = {
        "coverage": "full",
        "evaluations_observed": 4,
        "lookups": 10,
        "hits": 6,
        "misses": 4,
        "hit_rate": 0.6,
        "entries_stored": 4,
        "store_failures": 0,
        "load_status_counts": {"loaded": 4},
        "provider": {
            "gemini_calls_avoided": 3,
            "duplicate_gate_real_attempts": 4,
            "duplicate_confirmation_real_attempts": 2,
            "known_actual_cost": "0.0142",
            "cost_coverage": 1.0,
            "currency": "USD",
        },
    }
    text = "\n".join(_render_pr131_lines(pr131))
    assert "Hits / misses / hit rate: 6 / 4 / 60.0%" in text
    assert "Gemini calls avoided by PR131: 3" in text
    assert "Actual duplicate workload cost: 0.0142 USD" in text
    assert "Counterfactual dollars saved are intentionally not estimated" in text


def test_email_summary_surfaces_pr131_at_a_glance():
    report = {
        "top_discarded": [],
        "news_published_count": 12,
        "reports_published_count": 1,
        "judgment": "BUONO",
        "day_type": "normale",
        "hard_count": 7,
        "soft_count": 5,
        "pr131_cache": {
            "coverage": "full", "hits": 5, "misses": 3, "hit_rate": 0.625,
            "provider": {"gemini_calls_avoided": 2, "known_actual_cost": "0.0100", "currency": "USD"},
        },
    }
    text = email_summary(report)
    assert "PR131 cache: coverage=full" in text
    assert "hits/misses=5/3" in text
    assert "hit-rate=62.5%" in text
    assert "Gemini calls avoided=2" in text
    assert "actual duplicate cost=0.0100 USD" in text
