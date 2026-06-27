import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import newsroom_runner
from agents import gemini_ledger


def patch_ledger_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", tmp_path / "state" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", tmp_path / "artifacts" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", tmp_path / "state" / "newsroom" / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", tmp_path / "artifacts" / "newsroom" / "gemini_call_ledger_latest.json")
    monkeypatch.setenv("NEWSROOM_RUN_ID", "run-test")


def test_gemini_ledger_records_called_and_andrea_avoided(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)

    gemini_ledger.record_gemini_event(agent="Menzo", phase="duplicate_arbitration", model="gemini-test", status="called", reason="ai_duplicate_arbitration")
    gemini_ledger.record_andrea_avoided({"title": "Blocked", "url": "https://example.test/a", "source": "Feed"})

    lines = gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["status"] == "called"
    assert records[1]["status"] == "avoided"
    assert records[1]["agent"] == "Andrea"
    assert records[1]["would_have_agent"] == "Bob"
    assert records[1]["saved_gemini_call"] is True

    latest = json.loads(gemini_ledger.LATEST_FILE.read_text(encoding="utf-8"))
    assert latest["summary"]["gemini_calls_total"] == 1
    assert latest["summary"]["gemini_calls_by_agent"] == {"Menzo": 1}
    assert latest["summary"]["gemini_calls_avoided_total"] == 1
    assert latest["summary"]["gemini_calls_avoided_by_andrea"] == 1


def test_andrea_blocked_items_drive_avoided_ledger(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)
    andrea_result = {
        "handoff": {"andrea_checked": 3, "andrea_passed": 1, "andrea_blocked": 2, "saved_gemini_calls": 2},
        "blocked_items": [
            {"title": "Too thin 1", "url": "https://example.test/1", "reason": "insufficient_content"},
            {"title": "Too thin 2", "url": "https://example.test/2", "reason": "insufficient_content"},
        ],
        "selected": [{"title": "Passed", "url": "https://example.test/3"}],
    }

    newsroom_runner.record_andrea_avoids_from_result(andrea_result)
    summary = gemini_ledger.write_latest_snapshot()["summary"]

    assert newsroom_runner.andrea_blocked_count(andrea_result) == 2
    assert summary["gemini_calls_avoided_by_andrea"] == andrea_result["handoff"]["andrea_blocked"]
    assert summary["gemini_calls_avoided_total"] == andrea_result["handoff"]["andrea_blocked"]


def test_andrea_count_only_creates_synthetic_avoided_records(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)
    andrea_result = {"handoff": {"andrea_blocked": 3, "saved_gemini_calls": 3}}

    newsroom_runner.record_andrea_avoids_from_result(andrea_result)
    records = gemini_ledger.latest_for_run()["records"]

    assert len(records) == 3
    assert all(record["agent"] == "Andrea" for record in records)
    assert all(record["status"] == "avoided" for record in records)
    assert gemini_ledger.summarize(records)["gemini_calls_avoided_by_andrea"] == 3
