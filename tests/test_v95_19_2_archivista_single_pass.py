from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agents.archivista as archivista
import newsroom_runner


def test_safe_agent_supports_keyword_only_agent_calls(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def keyword_only(*, value: int) -> dict:
        captured["value"] = value
        return {"overall_status": "ok", "summary": {"anomalies": 0}}

    monkeypatch.setattr(newsroom_runner, "ARTIFACT_DIR", tmp_path)
    timeline: list[dict[str, str]] = []

    result = newsroom_runner.safe_agent(
        timeline=timeline,
        agent="Archivista",
        phase="audit_ready",
        import_fn=lambda: keyword_only,
        call_kwargs={"value": 7},
        artifact_name="archivista_report.json",
        default_handoff={"overall_status": "error"},
        note_fn=lambda row: f"status={row.get('overall_status')}",
    )

    assert captured == {"value": 7}
    assert result["overall_status"] == "ok"
    assert [item["phase"] for item in timeline] == ["audit_ready"]


def test_archivista_ledger_is_idempotent_per_newsroom_run_id(tmp_path: Path, monkeypatch) -> None:
    ledger_path = tmp_path / "archivista_ledger.json"
    monkeypatch.setattr(archivista, "ARCHIVISTA_LEDGER_FILE", ledger_path)
    monkeypatch.setattr(archivista, "LEDGER_HOURS", 48)

    now = datetime.now(timezone.utc)
    first = {
        "generated_at": (now - timedelta(seconds=1)).isoformat(),
        "run_id": "run-123",
        "published": 2,
    }
    second = {
        "generated_at": now.isoformat(),
        "run_id": "run-123",
        "published": 3,
    }

    assert len(archivista.update_ledger(first)) == 1
    rows = archivista.update_ledger(second)

    assert rows == [second]
    assert json.loads(ledger_path.read_text(encoding="utf-8")) == [second]


def test_newsroom_main_contains_one_archivista_execution_path() -> None:
    source = Path(newsroom_runner.__file__).read_text(encoding="utf-8")
    main_source = source[source.index("def main() -> int:") :]

    assert main_source.count('agent="Archivista"') == 1
    assert "audit_context_refreshed" not in main_source
    assert '"timeline": timeline' in main_source
    assert '"run_summary": run_summary' in main_source
