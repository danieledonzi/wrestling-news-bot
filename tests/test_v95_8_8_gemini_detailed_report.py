from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.gemini_diagnostics import (
    build_email_gemini_summary,
    build_gemini_diagnostics,
    load_menzo_cache,
    render_gemini_diagnostics_markdown,
)


def test_called_vs_avoided_and_grouping() -> None:
    records = [
        {"status": "called", "model": "gemini-3.5-flash", "agent": "Menzo", "reason": "ai_duplicate_arbitration", "title": "Sami Zayn update"},
        {"status": "avoided", "model": "gemini-3.5-flash", "agent": "Menzo", "reason": "duplicate_arbitration_cache_hit", "title": "Sami Zayn update"},
        {"status": "failed", "actual_model": "gemini-2.5-flash", "caller": "Bob", "purpose": "translation"},
    ]
    diag = build_gemini_diagnostics(records)
    assert diag["called_total"] == 1
    assert diag["avoided_total"] == 1
    assert diag["failed_total"] == 1
    assert diag["called_by_model_agent"] == {"gemini-3.5-flash × Menzo": 1}
    assert diag["called_by_model_agent_reason"] == {"gemini-3.5-flash × Menzo × ai_duplicate_arbitration": 1}
    assert diag["called_by_agent_reason"] == {"Menzo × ai_duplicate_arbitration": 1}


def test_35_called_list_and_email_summary() -> None:
    records = [
        {"timestamp": "2026-07-08T01:00:00+00:00", "status": "called", "model": "gemini-3.5-flash", "agent": "Menzo", "reason": "ai_duplicate_arbitration", "title": "Sami Zayn repeated", "url": "https://example.test/a", "run_id": "r1"},
        {"timestamp": "2026-07-08T02:00:00+00:00", "status": "called", "model": "gemini-3.5-flash", "agent": "Menzo", "reason": "ai_duplicate_arbitration", "title": "Sami Zayn repeated", "url": "https://example.test/b", "run_id": "r1"},
    ]
    diag = build_gemini_diagnostics(records)
    assert diag["called_35_total"] == 2
    assert len(diag["called_35_rows"]) == 2
    assert diag["top_repeated_35_titles"][0]["called_count"] == 2
    email = build_email_gemini_summary(diag)
    assert "Gemini 3.5 called total: 2" in email
    assert "Top repeated 3.5 title: sami zayn repeated (2 calls)" in email


def test_cache_file_present_missing_and_markdown(tmp_path: Path) -> None:
    missing = load_menzo_cache(tmp_path / "missing.json")
    assert missing["present"] is False
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"a": {"created_at": "2026-07-08T00:00:00+00:00", "expires_at": "2099-01-01T00:00:00+00:00", "model_used": "gemini-3.5-flash", "decision": "duplicate", "candidate_title_normalized": "sami zayn"}}), encoding="utf-8")
    present = load_menzo_cache(cache)
    assert present["present"] is True
    assert present["entries_total"] == 1
    assert present["entries_valid"] == 1
    diag = build_gemini_diagnostics([{"status": "avoided", "agent": "Menzo", "reason": "duplicate_arbitration_cache_hit"}], cache)
    md = render_gemini_diagnostics_markdown(diag)
    assert "## Gemini / AI Detailed Ledger 24h" in md
    assert "cache file present: yes" in md

def test_menzo_postprocess_supplies_miss_expired_when_ledger_lacks_them(tmp_path: Path) -> None:
    decisions = tmp_path / "menzo_decisions_latest.json"
    decisions.write_text(json.dumps({"postprocess": {"duplicate_arbitration_cache_hit": 4, "duplicate_arbitration_cache_miss": 7, "duplicate_arbitration_cache_expired": 2, "gemini_calls_avoided_by_duplicate_arbitration_cache": 4}}), encoding="utf-8")
    diag = build_gemini_diagnostics([], tmp_path / "missing-cache.json", menzo_decisions_paths=(decisions,))
    assert diag["ledger_duplicate_arbitration_cache_hit_24h"] == 0
    assert diag["menzo_latest_cache_hit"] == 4
    assert diag["menzo_latest_cache_miss"] == 7
    assert diag["menzo_latest_cache_expired"] == 2
    assert diag["menzo_latest_cache_avoided"] == 4


def test_menzo_hits_are_not_double_counted_between_ledger_and_postprocess(tmp_path: Path) -> None:
    decisions = tmp_path / "menzo_decisions_latest.json"
    decisions.write_text(json.dumps({"postprocess": {"duplicate_arbitration_cache_hit": 3, "duplicate_arbitration_cache_miss": 1, "duplicate_arbitration_cache_expired": 0, "gemini_calls_avoided_by_duplicate_arbitration_cache": 3}}), encoding="utf-8")
    records = [{"status": "avoided", "agent": "Menzo", "reason": "duplicate_arbitration_cache_hit"}]
    diag = build_gemini_diagnostics(records, tmp_path / "missing-cache.json", menzo_decisions_paths=(decisions,))
    assert diag["ledger_duplicate_arbitration_cache_hit_24h"] == 1
    assert diag["menzo_latest_cache_hit"] == 3
    assert diag["menzo_latest_cache_avoided"] == 3
    email = build_email_gemini_summary(diag)
    assert "latest=3 / 3; 24h ledger hits=1" in email


def test_missing_menzo_postprocess_is_non_fatal_and_rendered_not_available(tmp_path: Path) -> None:
    diag = build_gemini_diagnostics([], tmp_path / "missing-cache.json", menzo_decisions_paths=(tmp_path / "missing-decisions.json",))
    assert diag["menzo_postprocess"]["available"] is False
    assert diag["menzo_latest_cache_miss"] == "not_available"
    md = render_gemini_diagnostics_markdown(diag)
    assert "24h ledger duplicate_arbitration_cache_hit avoided records: 0" in md
    assert "latest Menzo run duplicate_arbitration_cache_miss: not_available" in md
