from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from agents.canonical_event_ledger import (CanonicalEventLedger, content_id,
    correlation_id, report_correlation_id, validate_event)
from agents.duplicate_pair_identity import article_id
from scripts.validate_canonical_event_ledger import validate_ledger

URL = "https://example.com/news/item?utm_source=x#part"


def base_event(**changes):
    row = {"schema_version": "owtv_event_schema_v1", "policy_version": "v95.22_a2",
           "timestamp_utc": "2026-01-01T00:00:00+00:00", "run_id": "run",
           "stage": "intake", "agent": "Massy", "event_type": "candidate_seen",
           "status": "success", "artifact_refs": []}
    row.update(changes)
    return row


def rows(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_schema_valid_and_mutations():
    assert validate_event(base_event()) == []
    for change, needle in [({"extra": 1}, "unknown"), ({"stage": "bad"}, "stage"),
                           ({"event_type": "bad"}, "event_type"),
                           ({"agent": "Bob"}, "agent"),
                           ({"artifact_refs": [{"path": "x", "relation": "bad"}]}, "artifact")]:
        assert any(needle in error for error in validate_event(base_event(**change)))
    missing = base_event(); del missing["run_id"]
    assert validate_event(missing)


@pytest.mark.parametrize("timestamp", [
    "2026-08-15T19:30:00+00:00",
    "2026-08-15T19:30:00Z",
    "2026-08-15T19:30:00.123456+00:00",
])
def test_rfc3339_utc_timestamp_is_valid(timestamp):
    assert validate_event(base_event(timestamp_utc=timestamp)) == []


@pytest.mark.parametrize("timestamp", [
    "not-a-date",
    "2026-08-15",
    "2026-08-15T19:30:00",
    "2026-08-15 19:30:00",
    "2026-08-15T19:30:00+02:00",
    "2026-02-30T19:30:00+00:00",
])
def test_non_rfc3339_or_non_utc_timestamp_is_invalid(timestamp):
    assert any("timestamp_utc" in error for error in validate_event(base_event(timestamp_utc=timestamp)))


@pytest.mark.parametrize("extra", [
    {},
    {"artifact_type": "json"},
    {"schema_version": "massy_board_v1"},
    {"sha256": "a" * 64},
])
def test_a2_artifact_ref_optional_fields(extra):
    ref = {"path": "artifacts/newsroom/massy_board.json", "relation": "evidence", **extra}
    assert validate_event(base_event(artifact_refs=[ref])) == []


@pytest.mark.parametrize("extra", [{"unknown": "x"}, {"sha256": "ABC"}, {"sha256": "a" * 63}])
def test_a2_artifact_ref_rejects_unknown_or_malformed_sha(extra):
    ref = {"path": "artifact.json", "relation": "evidence", **extra}
    assert any("artifact_refs" in error for error in validate_event(base_event(artifact_refs=[ref])))


def test_content_article_and_correlation_identity():
    plain = {"url": "https://example.com/news/item"}
    assert content_id({"url": URL}) == content_id(plain)
    assert content_id(plain) != content_id({"url": "https://example.com/other"})
    assert content_id({"title": "same"}) == ""
    assert article_id(plain).removeprefix("art_") == content_id(plain).removeprefix("cnt_")
    cid = content_id(plain)
    assert correlation_id("r", cid) == correlation_id("r", cid)
    assert correlation_id("r", cid) != correlation_id("r2", cid)
    assert correlation_id("r", cid) != correlation_id("r", content_id({"url": "https://example.com/2"}))


def test_story_not_derived_from_titles(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l.jsonl")
    ledger.event("candidate_seen", "Massy", "intake", "success", item={"url": URL, "title": "Jim Ross"})
    ledger.event("candidate_seen", "Massy", "intake", "success", item={"url": "https://example.com/2", "title": "Jim Ross news"})
    assert all("story_id" not in row for row in rows(ledger.path))


def test_massy_universe_dedupe_and_no_aggregate_synthesis(tmp_path):
    path = tmp_path / "l.jsonl"; ledger = CanonicalEventLedger("r", path)
    board = {"news_candidates_for_menzo": [{"url": "https://x.test/n"}, {"url": "https://x.test/n"}],
             "report_candidates": [{"url": "https://x.test/r"}],
             "hard_skipped": [{"url": "https://x.test/h", "reason": "low_value"}],
             "already_worked": [{"url": "https://x.test/a", "reason": "url_present_in_state"}],
             "found_urls": 99}
    original = copy.deepcopy(board); ledger.observe_massy(board)
    assert board == original
    result = rows(path)
    assert sum(row["event_type"] == "candidate_seen" for row in result) == 4
    assert sum(row["event_type"] == "candidate_skipped" for row in result) == 2
    empty = CanonicalEventLedger("r", tmp_path / "empty"); empty.observe_massy({"found_urls": 20})
    assert not empty.path.exists()


def test_end_to_end_observers_keep_one_identity_and_do_not_mutate(tmp_path):
    path = tmp_path / "l"; ledger = CanonicalEventLedger("run-1", path)
    item = {"url": URL, "source_url": URL, "title": "A"}
    massy = {"news_candidates_for_menzo": [item]}; menzo = {"selected": [item]}
    before = copy.deepcopy((massy, menzo))
    ledger.observe_massy(massy); ledger.observe_menzo(menzo)
    ledger.observe_bob_requested(menzo)
    ledger.observe_bob_generated({"articles": [{**item, "status": "ready_for_alfred"}]})
    ledger.observe_alfred({"reviews": [{**item, "decision": "approved"}]})
    ledger.observe_publisher({"results": [{**item, "status": "published"}], "handoff": {"published": 50}})
    assert (massy, menzo) == before
    expected = {"candidate_seen", "candidate_selected", "article_generation_requested", "article_generated",
                "quality_review_completed", "publication_attempted", "publication_completed"}
    traced = [row for row in rows(path) if row["event_type"] in expected]
    assert {row["event_type"] for row in traced} == expected
    assert len({row["content_id"] for row in traced}) == len({row["correlation_id"] for row in traced}) == 1


def test_pending_skipped_and_aggregate_guards(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    a = {"url": "https://x.test/a"}; b = {"url": "https://x.test/b", "reason": "below_threshold"}
    ledger.observe_menzo({"pending": [a], "skipped": [b]})
    ledger.observe_andrea({"handoff": {"andrea_checked": 20}})
    ledger.observe_bob_generated({"handoff": {"ready_for_alfred": 20}})
    ledger.observe_publisher({"handoff": {"published": 20}})
    assert [r["event_type"] for r in rows(ledger.path)] == ["candidate_pending", "candidate_skipped"]


@pytest.mark.parametrize("status, expected", [
    ("ready_for_alfred", 1),
    ("extraction_empty", 0),
    ("extraction_ready_translation_pending", 0),
    ("error", 0),
])
def test_bob_generated_requires_ready_package(tmp_path, status, expected):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    ledger.observe_bob_generated({"articles": [{"url": URL, "status": status}]})
    output = rows(ledger.path) if ledger.path.exists() else []
    assert len(output) == expected
    assert all(row["event_type"] == "article_generated" and row["status"] == "success" for row in output)


def test_bob_mixed_articles_emit_only_ready_packages(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    statuses = ["ready_for_alfred", "extraction_empty", "ready_for_alfred", "error"]
    ledger.observe_bob_generated({"articles": [
        {"url": f"https://example.test/{index}", "status": status}
        for index, status in enumerate(statuses)
    ], "handoff": {"ready_for_alfred": 99}})
    assert len(rows(ledger.path)) == 2


def test_andrea_alfred_item_evidence_no_warning_normalization(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    item = {"source_url": URL, "decision": "passed_with_exception", "ok": True, "warnings": ["prose"]}
    ledger.observe_andrea({"andrea": {"items": [item]}})
    ledger.observe_alfred({"reviews": [{**item, "decision": "approved"}]})
    output = rows(ledger.path)
    assert output[0]["result"] == "passed_with_exception"
    assert all(row["event_type"] != "warning_recorded" for row in output)


def test_report_only_identity_and_explicit_publish_only(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    report = {"report_key": "raw-2026", "status": "ready"}
    decision = {"ready_reports": [report], "waiting_reports": [], "skipped_reports": [], "handoff": {"ready": 1}}
    ledger.observe_simone(decision, {"results": [{"report_key": "raw-2026", "status": "published"}, {"report_key": "x", "status": "dry_run"}]})
    output = rows(ledger.path)
    assert [r["event_type"] for r in output] == ["report_selected", "report_published"]
    assert all(r["report_key"] == "raw-2026" and "content_id" not in r for r in output)
    assert {r["correlation_id"] for r in output} == {report_correlation_id("r", "raw-2026")}


def test_url_backed_report_keeps_content_correlation_across_massy_and_simone(tmp_path):
    path = tmp_path / "l"; ledger = CanonicalEventLedger("report-run", path)
    report = {"source_url": "https://example.test/report", "report_key": "raw-2026"}
    massy = {"report_candidates": [report]}
    ledger.observe_items(massy, ("report_candidates",), "report_candidate_seen", "Simone", "reporting", "success", "artifacts/newsroom/massy_board.json")
    decision = {"ready_reports": [report], "waiting_reports": [], "skipped_reports": [], "handoff": {"ready": 1}}
    ledger.observe_simone(decision, {"results": [{**report, "status": "published"}]})
    output = rows(path)
    assert [row["event_type"] for row in output] == ["report_candidate_seen", "report_selected", "report_published"]
    assert len({row["content_id"] for row in output}) == len({row["correlation_id"] for row in output}) == 1
    assert all(row.get("report_key") == "raw-2026" for row in output[1:])


def test_bob_request_references_andrea_evidence(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    ledger.observe_bob_requested({"selected": [{"url": URL}]})
    refs = rows(ledger.path)[0]["artifact_refs"]
    assert refs == [{"path": "artifacts/newsroom/andrea_pre_bob_latest.json", "relation": "evidence"}]


def test_publisher_attempts_come_only_from_actual_result_rows(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    result = {
        "results": [
            {"source_url": "https://example.test/one", "status": "dry_run"},
            {"source_url": "https://example.test/two", "status": "wp_not_ready"},
        ],
        "skipped_approved_articles": [
            {"source_url": "https://example.test/capacity", "status": "skipped_capacity"},
        ],
        "handoff": {"approved": 3, "attempted_articles": 2},
    }
    ledger.observe_publisher(result)
    output = rows(ledger.path)
    assert len(output) == 2
    assert all(row["event_type"] == "publication_attempted" for row in output)


def test_publisher_safety_exclusions_are_not_attempts(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    ledger.observe_publisher({"results": [
        {"source_url": "https://example.test/duplicate", "status": "skipped", "reason": "skip:duplicate_story"},
        {"source_url": "https://example.test/unavailable", "status": "skipped", "reason": "skip:publisher_same_story_safety_unavailable"},
    ]})
    assert not ledger.path.exists()


def test_publisher_missing_title_row_is_an_attempt_when_url_resolves(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    ledger.observe_publisher({"results": [{
        "source_url": "https://example.test/missing-title",
        "status": "skipped",
        "reason": "missing_url_or_title",
    }]})
    assert [row["event_type"] for row in rows(ledger.path)] == ["publication_attempted"]


def test_publisher_retry_and_success_outcomes_retain_identity(tmp_path):
    ledger = CanonicalEventLedger("r", tmp_path / "l")
    ledger.observe_publisher({"results": [
        {"source_url": "https://example.test/retry", "status": "published"},
        {"source_url": "https://example.test/already", "status": "already_published"},
    ]})
    output = rows(ledger.path)
    assert [row["event_type"] for row in output] == [
        "publication_attempted", "publication_completed",
        "publication_attempted", "publication_already_present",
    ]
    for attempt, outcome in zip(output[::2], output[1::2]):
        assert attempt["content_id"] == outcome["content_id"]
        assert attempt["correlation_id"] == outcome["correlation_id"]
        assert attempt["artifact_refs"][0]["path"] == "artifacts/newsroom/publisher_result.json"


@pytest.mark.parametrize("status", ["publish_error", "wp_not_ready", "dry_run"])
def test_publisher_non_success_attempt_has_no_invented_failure(tmp_path, status):
    ledger = CanonicalEventLedger("r", tmp_path / status)
    ledger.observe_publisher({"results": [{"source_url": URL, "status": status}]})
    assert [row["event_type"] for row in rows(ledger.path)] == ["publication_attempted"]


def test_append_only_flag_fail_open_and_invalid(tmp_path, monkeypatch):
    path = tmp_path / "l"; ledger = CanonicalEventLedger("r", path)
    assert ledger.event("run_started", "Jarvis", "runtime", "started")
    first = path.read_bytes()
    assert ledger.event("run_completed", "Jarvis", "runtime", "success")
    assert path.read_bytes().startswith(first) and len(rows(path)) == 2
    assert not ledger.event("not_real", "Jarvis", "runtime", "success")
    assert ledger.summary()["validation_errors"] == 1
    disabled = CanonicalEventLedger("r", tmp_path / "off", enabled=False)
    assert not disabled.event("run_started", "Jarvis", "runtime", "started") and not disabled.path.exists()
    bad = CanonicalEventLedger("r", tmp_path / "directory", enabled=True); bad.path.mkdir()
    assert not bad.event("run_started", "Jarvis", "runtime", "started")
    assert bad.summary()["write_errors"] == 1


@pytest.mark.parametrize("mutation", ["malformed", "schema", "identity"])
def test_validator_rejects_invalid_ledgers(tmp_path, mutation):
    path = tmp_path / "l"; ledger = CanonicalEventLedger("r", path)
    ledger.event("candidate_seen", "Massy", "intake", "success", item={"url": URL})
    if mutation == "malformed": path.write_text(path.read_text() + "{\n")
    elif mutation == "schema": path.write_text(path.read_text() + json.dumps(base_event(extra=1)) + "\n")
    else:
        row = rows(path)[0]; row["correlation_id"] = "corr_wrong"
        path.write_text(path.read_text() + json.dumps(row) + "\n")
    assert validate_ledger(path)[0] == 1


def test_validator_accepts_storyless_ledger(tmp_path):
    path = tmp_path / "l"; ledger = CanonicalEventLedger("r", path)
    ledger.event("candidate_seen", "Massy", "intake", "success", item={"url": URL})
    code, summary = validate_ledger(path)
    assert code == 0 and summary["valid_rows"] == 1 and summary["distinct_content_ids"] == 1


def test_validator_rejects_invalid_timestamp_without_bounds(tmp_path):
    path = tmp_path / "l"
    path.write_text(json.dumps(base_event(timestamp_utc="not-a-date")) + "\n")
    code, summary = validate_ledger(path)
    assert code == 1 and summary["invalid_rows"] == 1
    assert summary["first_timestamp"] is summary["last_timestamp"] is None


@pytest.mark.parametrize("kind", ["wrong_content", "missing_content", "wrong_report"])
def test_validator_rejects_non_deterministic_single_row(tmp_path, kind):
    path = tmp_path / "l"
    cid = content_id({"url": URL})
    row = base_event(content_id=cid, correlation_id=correlation_id("run", cid))
    if kind == "wrong_content": row["correlation_id"] = "corr_wrong"
    elif kind == "missing_content": row.pop("correlation_id")
    else:
        row.pop("content_id"); row["report_key"] = "report-1"; row["correlation_id"] = "corr_wrong"
    path.write_text(json.dumps(row) + "\n")
    assert validate_ledger(path)[0] == 1


def test_validator_accepts_deterministic_report_only_correlation(tmp_path):
    path = tmp_path / "l"
    row = base_event(report_key="report-1", correlation_id=report_correlation_id("run", "report-1"))
    path.write_text(json.dumps(row) + "\n")
    assert validate_ledger(path)[0] == 0


def test_newsroom_runner_integration_traces_item_without_network(tmp_path, monkeypatch):
    import newsroom_runner as runner
    item = {"url": "https://example.test/source", "source_url": "https://example.test/source", "title": "Source"}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OWTV_CANONICAL_LEDGER_PATH", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setenv("NEWSROOM_RUN_ID", "integration-run")
    monkeypatch.setattr(runner, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(runner, "import_massy", lambda: lambda: {"news_candidates_for_menzo": [item], "handoff": {}})
    monkeypatch.setattr(runner, "import_simone", lambda: lambda board: {"ready_reports": [], "waiting_reports": [], "skipped_reports": [], "handoff": {}})
    monkeypatch.setattr(runner, "import_simone_report_publisher", lambda: lambda decision: {"results": [], "handoff": {}})
    monkeypatch.setattr(runner, "import_menzo", lambda: lambda board: {"selected": [item], "pending": [], "skipped": [], "handoff": {}})
    monkeypatch.setattr(runner, "import_andrea", lambda: lambda decision: {**decision, "andrea": {"items": [{**item, "ok": True, "decision": "pass_to_bob"}]}})
    monkeypatch.setattr(runner, "import_bob", lambda: lambda decision: {"articles": [{**item, "status": "ready_for_alfred"}], "handoff": {}})
    monkeypatch.setattr(runner, "import_alfred", lambda: lambda bob: {"reviews": [{**item, "decision": "approved"}], "approved_articles": [item], "handoff": {}})
    monkeypatch.setattr(runner, "import_publisher", lambda: lambda alfred: {"results": [{**item, "status": "published"}], "handoff": {}})
    monkeypatch.setattr(runner, "import_archivista", lambda: lambda **kwargs: {"overall_status": "ok", "summary": {}})
    monkeypatch.setattr(runner, "gemini_ledger_summary", lambda: {})
    monkeypatch.setattr(runner, "write_master_log_safe", lambda *args, **kwargs: {})
    assert runner.main() == 0
    trace_types = {"candidate_seen", "candidate_selected", "article_generation_requested", "article_generated",
                   "quality_review_completed", "publication_attempted", "publication_completed"}
    trace = [row for row in rows(tmp_path / "ledger.jsonl") if row["event_type"] in trace_types]
    assert {row["event_type"] for row in trace} == trace_types
    assert len({row["content_id"] for row in trace}) == len({row["correlation_id"] for row in trace}) == 1


def test_newsroom_runner_initialization_failure_is_fail_open(tmp_path, monkeypatch):
    import newsroom_runner as runner
    reached = {"publisher": False}
    item = {"url": "https://example.test/source", "source_url": "https://example.test/source"}
    monkeypatch.chdir(tmp_path); monkeypatch.setenv("NEWSROOM_RUN_ID", "failed-init-run")
    monkeypatch.setattr(runner, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(runner, "canonical_ledger_factory", lambda _run_id: (_ for _ in ()).throw(RuntimeError("forced init failure")))
    monkeypatch.setattr(runner, "import_massy", lambda: lambda: {"news_candidates_for_menzo": [item], "handoff": {}})
    monkeypatch.setattr(runner, "import_simone", lambda: lambda board: {"ready_reports": [], "waiting_reports": [], "skipped_reports": [], "handoff": {}})
    monkeypatch.setattr(runner, "import_simone_report_publisher", lambda: lambda decision: {"results": [], "handoff": {}})
    monkeypatch.setattr(runner, "import_menzo", lambda: lambda board: {"selected": [item], "handoff": {}})
    monkeypatch.setattr(runner, "import_andrea", lambda: lambda decision: decision)
    monkeypatch.setattr(runner, "import_bob", lambda: lambda decision: {"articles": [{**item, "status": "ready_for_alfred"}], "handoff": {}})
    monkeypatch.setattr(runner, "import_alfred", lambda: lambda bob: {"reviews": [], "approved_articles": [item], "handoff": {}})
    def publish(_alfred):
        reached["publisher"] = True
        return {"results": [], "handoff": {}}
    monkeypatch.setattr(runner, "import_publisher", lambda: publish)
    monkeypatch.setattr(runner, "import_archivista", lambda: lambda **kwargs: {"overall_status": "ok", "summary": {}})
    monkeypatch.setattr(runner, "gemini_ledger_summary", lambda: {})
    monkeypatch.setattr(runner, "write_master_log_safe", lambda *args, **kwargs: {})
    assert runner.main() == 0 and reached["publisher"]
    summary = json.loads((tmp_path / "artifacts" / "run_summary.json").read_text())
    diagnostic = summary["canonical_event_ledger"]
    assert diagnostic["enabled"] is False and diagnostic["unavailable"] is True
    assert "forced init failure" in diagnostic["initialization_error"]
