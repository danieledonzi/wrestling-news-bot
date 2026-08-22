from __future__ import annotations

import sys
from pathlib import Path

from scripts import owtv_gemini_ledger_report as runtime_report
from owtv_report import add_gemini_detailed_ledger_to_report


def test_runtime_gemini_report_uses_requested_window(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    ledger.write_text("", encoding="utf-8")

    monkeypatch.setattr(runtime_report, "LEDGER", ledger)
    monkeypatch.setattr(
        sys,
        "argv",
        ["owtv_gemini_ledger_report.py", "6"],
    )

    assert runtime_report.main() == 0

    output = capsys.readouterr().out
    assert "## Gemini / AI Call and Usage Diagnostics (NON-AUTHORITATIVE) 6h" in output
    assert "## Gemini Economic Authority and Non-Authoritative Diagnostics 6h" in output
    assert "6h ledger duplicate_arbitration_cache_hit avoided records" in output
    assert "## Gemini Economic Authority and Non-Authoritative Diagnostics 24h" not in output
    converged = add_gemini_detailed_ledger_to_report(output, ledger_path=ledger)
    assert converged.count("## Gemini Economic Authority and Non-Authoritative Diagnostics 6h") == 1
    assert "## Gemini / AI Cost Ledger" not in converged
