from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import owtv_gemini_ledger_report as runtime_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_installer_resolves_relative_repository_root(
    tmp_path: Path,
) -> None:
    target = tmp_path / "owtv_gemini_ledger_report.py"

    env = os.environ.copy()
    env["OWTV_REPO_ROOT"] = "."
    env["OWTV_RUNTIME_REPORT_TARGET"] = str(target)

    subprocess.run(
        ["bash", "scripts/install_runtime_reporting_links.sh"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert target.is_symlink()
    assert target.resolve() == (
        REPO_ROOT / "scripts" / "owtv_gemini_ledger_report.py"
    ).resolve()


def test_future_ledger_records_are_excluded(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ledger = tmp_path / "gemini_call_ledger.jsonl"
    future_timestamp = (
        datetime.now(timezone.utc) + timedelta(days=1)
    ).isoformat()

    ledger.write_text(
        json.dumps(
            {
                "timestamp": future_timestamp,
                "status": "called",
                "agent": "Bob",
                "model": "gemini-test",
                "run_id": "future-run",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(runtime_report, "LEDGER", ledger)
    monkeypatch.setattr(
        sys,
        "argv",
        ["owtv_gemini_ledger_report.py", "12"],
    )

    assert runtime_report.main() == 0

    output = capsys.readouterr().out
    assert "- Ledger records: 0" in output
    assert "- Gemini calls total: 0" in output
