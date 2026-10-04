from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from scripts.daily_editorial_judgment import _render_pr131_lines, email_summary
from agents.canonical_event_ledger import CanonicalEventLedger
from scripts.observability_snapshot import build_pr131_cache_metrics, build_pr2_telemetry_coverage, build_snapshot

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(hours=24)


def event(kind, *, ts=None, result=None, reason=None, pair_id=None, agent="Menzo"):
    row = {
        "timestamp_utc": (ts or NOW - timedelta(hours=1)).isoformat(),
        "run_id": "run",
        "event_type": kind,
        "agent": agent,
        "stage": (
            "runtime" if kind == "telemetry_contract_observed"
            else ("duplicate" if kind.startswith("duplicate_pair_cache") else "model")
        ),
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


def pr2_marker(ts):
    return event(
        "telemetry_contract_observed", ts=ts, result="v96_5_pr2",
        reason="pr2_missing_telemetry_closure", agent="Jarvis",
    )


def test_pr2_marker_makes_zero_activity_authoritative_after_full_window():
    rows = [pr2_marker(SINCE - timedelta(minutes=1))]
    coverage, reason, meta = build_pr2_telemetry_coverage(
        rows, SINCE, NOW, canonical_healthy=True
    )
    assert coverage == "full"
    assert reason is None
    assert meta["complete_window"] is True

    result, result_meta = build_pr131_cache_metrics(
        rows, [], SINCE, NOW,
        pr2_coverage=coverage, pr2_reason=reason, gemini_available=True,
    )
    assert result_meta["complete_window"] is True
    assert result["coverage"] == "full"
    assert result["evaluations_observed"] == 0
    assert result["lookups"] == 0
    assert result["hits"] == 0
    assert result["misses"] == 0
    assert result["hit_rate"] is None
    assert result["entries_stored"] == 0
    assert result["store_failures"] == 0
    assert result["load_status_counts"] == {}
    assert result["provider"]["gemini_calls_avoided"] == 0


def test_pr2_marker_inside_window_is_partial_even_with_no_tracked_outcomes():
    rows = [pr2_marker(NOW - timedelta(hours=2))]
    coverage, reason, meta = build_pr2_telemetry_coverage(
        rows, SINCE, NOW, canonical_healthy=True
    )
    assert coverage == "partial"
    assert reason == "pr2_telemetry_cutover_inside_window"
    assert meta["complete_window"] is False


def test_bob_and_simone_pr2_zero_or_failure_metrics_do_not_depend_on_cache_activity(tmp_path):
    path = tmp_path / "state" / "newsroom" / "canonical_event_ledger.jsonl"
    ledger = CanonicalEventLedger("run-pr2", path)
    assert ledger.event(
        "telemetry_contract_observed", "Jarvis", "runtime", "success",
        result="v96_5_pr2", reason_code="pr2_missing_telemetry_closure",
    )
    ledger.observe_bob_generated({"articles": [{
        "source_url": "https://example.test/bob-failure",
        "status": "extraction_empty",
    }]})
    ledger.observe_simone({}, {"results": [{
        "report_key": "wwe_raw_2026_10_04",
        "status": "already_published",
    }]})

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["timestamp_utc"] = (SINCE - timedelta(minutes=1)).isoformat()
    for row in rows[1:]:
        row["timestamp_utc"] = (NOW - timedelta(hours=1)).isoformat()
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )

    snapshot = build_snapshot(SINCE, NOW, tmp_path)
    authoritative = snapshot["authoritative"]
    assert snapshot["section_metadata"]["pr2_telemetry"]["complete_window"] is True
    assert snapshot["pr131_cache"]["coverage"] == "full"
    assert snapshot["pr131_cache"]["lookups"] == 0
    assert authoritative["bob"]["item_failures"] == 1
    assert authoritative["bob"]["failure_reasons"] == {"extraction_empty": 1}
    assert authoritative["simone"]["already_present_events"] == 1
    assert authoritative["bob"]["metadata"]["complete_window"] is True


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
        rows, gemini, SINCE, NOW,
        pr2_coverage="full", pr2_reason=None, gemini_available=True
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
        rows, [], SINCE, NOW,
        pr2_coverage="partial", pr2_reason="pr2_telemetry_cutover_inside_window",
        gemini_available=True
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
        rows, [], SINCE, NOW,
        pr2_coverage="full", pr2_reason=None, gemini_available=True
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
