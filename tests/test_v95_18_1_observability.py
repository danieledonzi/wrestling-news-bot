from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.gemini_diagnostics import (
    build_gemini_diagnostics,
    render_gemini_diagnostics_markdown,
)
from owtv_report import (
    add_gemini_detailed_ledger_to_report,
    render_gemini_detailed_ledger_24h,
)


def test_v9518_latest_run_snapshot_is_exposed(tmp_path: Path) -> None:
    decisions = tmp_path / "menzo_decisions_latest.json"
    decisions.write_text(
        json.dumps(
            {
                "postprocess": {
                    "duplicate_scorer_version": "v95.18-test",
                    "duplicate_suspect_threshold": 0.55,
                    "same_run_pairs_theoretical": 10,
                    "same_run_exact_duplicates": 1,
                    "same_run_pairs_below_threshold": 7,
                    "same_run_pairs_above_threshold": 2,
                    "same_run_suspicious_components": 1,
                    "same_run_candidates_sent_to_gemini": 2,
                    "recent_history_candidates": 4,
                    "recent_history_publications_12h": 20,
                    "recent_history_pairs_theoretical": 80,
                    "recent_history_exact_duplicates": 0,
                    "recent_history_pairs_below_threshold": 76,
                    "recent_history_pairs_above_threshold": 4,
                    "recent_history_candidates_sent_to_gemini": 2,
                    "recent_history_publications_sent_to_gemini": 4,
                    "duplicate_cache_hits": 1,
                    "duplicate_cache_misses": 2,
                    "gemini_duplicate_calls_planned": 3,
                    "gemini_duplicate_calls_executed": 2,
                    "gemini_duplicate_calls_avoided": 1,
                    "menzo_recent_history_material_updates": 1,
                    "menzo_duplicate_arbitration_fail_closed": 0,
                    "duplicate_suspicion_audit_omitted": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    diag = build_gemini_diagnostics(
        [],
        tmp_path / "missing-cache.json",
        menzo_decisions_paths=(decisions,),
    )
    markdown = render_gemini_diagnostics_markdown(diag, hours=12)

    assert diag["menzo_v9518_available"] is True
    assert "## Gemini / AI Detailed Ledger 12h" in markdown
    assert "### Menzo Duplicate Gate v95.18" in markdown
    assert "- theoretical pairs: 10" in markdown
    assert "- below threshold: 7" in markdown
    assert "- above threshold: 2" in markdown
    assert "- Gemini calls executed: 2" in markdown


def test_35_successes_and_failures_are_distinguished() -> None:
    diag = build_gemini_diagnostics(
        [
            {
                "status": "called",
                "model": "gemini-3.5-flash",
                "agent": "Bob",
                "reason": "translation",
            },
            {
                "status": "failed",
                "actual_model": "gemini-3.5-flash",
                "caller": "Bob",
                "purpose": "translation",
            },
        ]
    )
    markdown = render_gemini_diagnostics_markdown(diag)

    assert diag["attempted_35_total"] == 2
    assert diag["called_35_total"] == 1
    assert diag["failed_35_total"] == 1
    assert "- 3.5 attempts total: 2" in markdown
    assert "- 3.5 successful calls: 1" in markdown
    assert "- 3.5 failed attempts: 1" in markdown


def test_missing_title_uses_stable_ledger_identity() -> None:
    diag = build_gemini_diagnostics(
        [
            {
                "status": "called",
                "model": "gemini-3.5-flash",
                "agent": "Menzo",
                "reason": "ai_duplicate_arbitration",
                "current_url": "https://example.test/story",
            }
        ]
    )

    assert diag["called_35_rows"][0]["title"] == "https://example.test/story"
    assert (
        diag["top_repeated_35_titles"][0]["title"]
        == "httpsexampleteststory"
    )


def test_operational_report_uses_actual_12h_heading(tmp_path: Path) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    report = "## Gemini / AI Cost Ledger 12h\n- aggregate\n"

    out = add_gemini_detailed_ledger_to_report(
        report,
        ledger_path=ledger,
        since=datetime(2026, 7, 24, 0, tzinfo=timezone.utc),
        until=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
    )

    assert "## Gemini / AI Detailed Ledger 12h" in out
    assert "## Gemini / AI Detailed Ledger 24h" not in out


def test_existing_dynamic_detailed_heading_is_not_duplicated(
    tmp_path: Path,
) -> None:
    report = (
        "## Gemini / AI Cost Ledger 12h\n"
        "- aggregate\n\n"
        "## Gemini / AI Detailed Ledger 12h\n"
        "- existing\n"
    )

    out = add_gemini_detailed_ledger_to_report(
        report,
        ledger_path=tmp_path / "missing.jsonl",
    )

    assert out.count("## Gemini / AI Detailed Ledger 12h") == 1
    assert "- existing" in out

def test_since_only_uses_current_time_for_dynamic_heading(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    since = datetime.now(timezone.utc) - timedelta(hours=6)

    output = render_gemini_detailed_ledger_24h(
        ledger_path=ledger,
        since=since,
    )

    assert "## Gemini / AI Detailed Ledger 6h" in output
