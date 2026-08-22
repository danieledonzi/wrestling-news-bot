from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from owtv_report import add_gemini_detailed_ledger_to_report


def _write_ledger(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_operational_report_appends_detailed_after_cost_section_24h_heading(tmp_path: Path) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    _write_ledger(ledger, [{"timestamp": "2026-07-09T11:00:00+00:00", "status": "called", "model": "gemini-3.5-flash", "agent": "Menzo", "reason": "ai_duplicate_arbitration"}])
    report = "# Daily\n\n## Gemini / AI Cost Ledger 24h\n- Gemini calls total: 1\n\n## Agent handoff\n- ok\n"

    out = add_gemini_detailed_ledger_to_report(report, ledger_path=ledger, now=datetime(2026, 7, 9, 12, tzinfo=timezone.utc))

    assert "## Gemini / AI Call and Usage Diagnostics (NON-AUTHORITATIVE) 24h" in out
    assert "## Gemini Economic Authority and Non-Authoritative Diagnostics 24h" in out
    assert out.index("## Gemini / AI Call and Usage Diagnostics (NON-AUTHORITATIVE) 24h") < out.index("## Gemini Economic Authority and Non-Authoritative Diagnostics 24h") < out.index("## Agent handoff")
    assert "gemini-3.5-flash × Menzo: 1" in out


def test_operational_report_appends_detailed_after_cost_section_without_24h_suffix(tmp_path: Path) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    _write_ledger(ledger, [{"timestamp": "2026-07-09T11:00:00+00:00", "status": "called", "model": "gemini-3.5-flash", "agent": "Bob", "reason": "translation"}])
    report = "# Daily\n\n## Gemini / AI Cost Ledger\n- Gemini calls total: 1\n\n## Agent handoff\n- ok\n"

    out = add_gemini_detailed_ledger_to_report(report, ledger_path=ledger, now=datetime(2026, 7, 9, 12, tzinfo=timezone.utc))

    assert "## Gemini / AI Call and Usage Diagnostics (NON-AUTHORITATIVE)\n" in out
    assert "## Gemini Economic Authority and Non-Authoritative Diagnostics 24h" in out
    assert out.index("## Gemini / AI Call and Usage Diagnostics (NON-AUTHORITATIVE)") < out.index("## Gemini Economic Authority and Non-Authoritative Diagnostics 24h") < out.index("## Agent handoff")
    assert "gemini-3.5-flash × Bob: 1" in out


def test_operational_report_appends_detailed_at_end_when_cost_section_missing(tmp_path: Path) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    _write_ledger(ledger, [{"timestamp": "2026-07-09T11:00:00+00:00", "status": "called", "model": "gemini-3.5-flash", "agent": "Alfred", "reason": "analysis"}])
    report = "# Daily\n\n## Agent handoff\n- ok\n"

    out = add_gemini_detailed_ledger_to_report(report, ledger_path=ledger, now=datetime(2026, 7, 9, 12, tzinfo=timezone.utc))

    assert out.index("## Agent handoff") < out.index("## Gemini Economic Authority and Non-Authoritative Diagnostics 24h")
    assert "gemini-3.5-flash × Alfred: 1" in out


def test_operational_report_does_not_duplicate_detailed_section(tmp_path: Path) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    _write_ledger(ledger, [])
    report = "## Gemini / AI Cost Ledger 24h\n- old\n\n## Gemini Economic Authority and Non-Authoritative Diagnostics 24h\n- already here\n"

    out = add_gemini_detailed_ledger_to_report(report, ledger_path=ledger)

    assert out.count("## Gemini Economic Authority and Non-Authoritative Diagnostics 24h") == 1
    assert "already here" in out


def test_missing_or_invalid_ledger_does_not_fail_report_generation(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    report = "## Gemini / AI Cost Ledger 24h\n- old aggregate preserved\n"

    missing_out = add_gemini_detailed_ledger_to_report(report, ledger_path=missing)

    assert "- old aggregate preserved" in missing_out
    assert "## Gemini Economic Authority and Non-Authoritative Diagnostics 24h" in missing_out
    assert "ledger file missing" in missing_out

    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text("{not-json}\n", encoding="utf-8")

    invalid_out = add_gemini_detailed_ledger_to_report(report, ledger_path=invalid)

    assert "- old aggregate preserved" in invalid_out
    assert "invalid ledger JSON line 1" in invalid_out


def test_operational_report_respects_explicit_24h_window(tmp_path: Path) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    _write_ledger(
        ledger,
        [
            {"timestamp": "2026-07-08T11:59:59+00:00", "status": "called", "model": "gemini-3.5-flash", "agent": "Menzo", "reason": "old_window"},
            {"timestamp": "2026-07-08T12:00:00+00:00", "status": "called", "model": "gemini-3.5-flash", "agent": "Bob", "reason": "inside_window"},
        ],
    )
    report = "## Gemini / AI Cost Ledger 24h\n- old\n"

    out = add_gemini_detailed_ledger_to_report(
        report,
        ledger_path=ledger,
        since=datetime(2026, 7, 8, 12, tzinfo=timezone.utc),
        until=datetime(2026, 7, 9, 12, tzinfo=timezone.utc),
    )

    assert "gemini-3.5-flash × Bob: 1" in out
    assert "old_window" not in out
