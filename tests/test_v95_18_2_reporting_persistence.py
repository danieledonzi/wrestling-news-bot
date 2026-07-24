from __future__ import annotations

import sys
from pathlib import Path

from scripts import owtv_gemini_ledger_report as runtime_report


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
    assert "## Gemini / AI Cost Ledger 6h" in output
    assert "## Gemini / AI Detailed Ledger 6h" in output
    assert "6h ledger duplicate_arbitration_cache_hit avoided records" in output
    assert "## Gemini / AI Detailed Ledger 24h" not in output
