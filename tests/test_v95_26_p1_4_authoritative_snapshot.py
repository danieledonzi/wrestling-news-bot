import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agents.canonical_artifact_index import CanonicalArtifactIndex
from agents.canonical_artifact_reader import REPORT_SCOPE_REASON, read_artifact_index, resolve_material_chain
from agents.canonical_event_ledger import CanonicalEventLedger, clear_active_ledger, install_active_ledger
from agents import source_body
from scripts.observability_snapshot import build_snapshot, _artifact_snapshot, _coverage_from_cutover
from scripts.translation_quality_audit import discover
from scripts.daily_editorial_judgment import (resolve_editorial_classifications, resolve_p1_1_headline,
                                               resolve_p1_4_canonical_payloads)


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _report_runtime(monkeypatch, tmp_path, outcomes, models=("primary", "fallback")):
    import modules.report_workshop_v92 as workshop
    monkeypatch.setattr(workshop, "GEMINI_API_KEY", "fixture")
    monkeypatch.setattr(workshop, "REPORT_MODEL_CHAIN", list(models))
    monkeypatch.setattr(workshop, "record_gemini_attempt", lambda **kwargs: None)
    monkeypatch.setattr(workshop, "record_gemini_event", lambda **kwargs: None)
    calls = []

    class Models:
        def generate_content(self, *, model, contents):
            calls.append(model)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return type("Response", (), {"text": json.dumps(outcome)})()

    monkeypatch.setattr(workshop.genai, "Client", lambda **kwargs: type("Client", (), {"models": Models()})())
    ledger = CanonicalEventLedger("run", tmp_path / "events.jsonl")
    install_active_ledger(ledger)
    return workshop, ledger, calls


def test_report_translation_single_success(monkeypatch, tmp_path):
    workshop, ledger, calls = _report_runtime(monkeypatch, tmp_path, [{"items": []}])
    try:
        workshop.generate_json("prompt", "report_blocks_legacy_prompt", ledger_context={"report_key": "r", "batch": "1/1"})
    finally:
        clear_active_ledger()
    rows = _rows(ledger.path)
    assert calls == ["primary"]
    assert [r["event_type"] for r in rows] == ["logical_ai_request_created", "model_attempt_started", "model_attempt_completed"]
    assert {r.get("model_role") for r in rows} == {"report_translation"}
    assert next(r for r in rows if r["event_type"] == "model_attempt_completed")["latency_ms"] >= 0


def test_report_translation_missing_key_closes_pre_attempt_intention(monkeypatch, tmp_path):
    import modules.report_workshop_v92 as workshop
    monkeypatch.setattr(workshop, "GEMINI_API_KEY", "")
    ledger = CanonicalEventLedger("run", tmp_path / "events.jsonl"); install_active_ledger(ledger)
    try:
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            workshop.generate_json("prompt", "report_blocks_legacy_prompt", ledger_context={"report_key": "r"})
    finally:
        clear_active_ledger()
    rows = _rows(ledger.path)
    assert [row["event_type"] for row in rows] == ["logical_ai_request_created", "stage_failed"]
    assert rows[-1]["reason_code"] == "missing_api_key"


def test_report_translation_fallback_terminal_and_cooldown(monkeypatch, tmp_path):
    workshop, ledger, calls = _report_runtime(monkeypatch, tmp_path, [RuntimeError("503"), {"items": []}], ("cool", "real", "last"))
    try:
        workshop.generate_json("prompt", "report_blocks_legacy_prompt", cooldown_models={"cool"},
                               ledger_context={"report_key": "r", "batch": "1/1"})
    finally:
        clear_active_ledger()
    rows = _rows(ledger.path)
    starts = [r for r in rows if r["event_type"] == "model_attempt_started"]
    assert calls == ["real", "last"] and [r["attempt_number"] for r in starts] == [1, 2]
    assert len({r["logical_request_id"] for r in starts}) == 1
    assert sum(r["event_type"] == "model_attempt_avoided" for r in rows) == 1
    assert sum(r["event_type"] == "fallback_started" for r in rows) == 1
    assert next(r for r in rows if r["event_type"] == "model_attempt_failed")["error_terminal"] is False


def test_report_translation_terminal_failure(monkeypatch, tmp_path):
    workshop, ledger, _calls = _report_runtime(monkeypatch, tmp_path, [RuntimeError("fatal")], ("only",))
    try:
        with pytest.raises(RuntimeError):
            workshop.generate_json("prompt", "report_blocks_legacy_prompt", ledger_context={"report_key": "r"})
    finally:
        clear_active_ledger()
    failure = next(r for r in _rows(ledger.path) if r["event_type"] == "model_attempt_failed")
    assert failure["attempt_number"] == 1 and failure["error_terminal"] is True


def test_report_translation_batches_are_distinct_intentions(monkeypatch, tmp_path):
    workshop, ledger, _calls = _report_runtime(monkeypatch, tmp_path, [
        {"items": [{"i": i, "text": f"tradotto {i}"} for i in range(8)]},
        {"items": [{"i": 8, "text": "tradotto 8"}]}
    ], ("only",))
    monkeypatch.setattr(workshop, "REPORT_TRANSLATION_BATCH_SIZE", 1)
    blocks = [{"type": "paragraph", "text": f"source {i}"} for i in range(9)]
    try:
        assert workshop.translate_report_blocks("source", blocks, "report") == {i: f"tradotto {i}" for i in range(9)}
    finally:
        clear_active_ledger()
    created = [r for r in _rows(ledger.path) if r["event_type"] == "logical_ai_request_created"]
    assert len(created) == 2 and len({r["logical_request_id"] for r in created}) == 2


def _contract(url):
    text = "Complete source material " * 20
    return source_body.contract_from_elements(url, [{"type": "text", "text": text}], {
        "stage": "extraction_finished", "extraction_finished": True, "body_complete": True,
        "body_complete_reason": "fixture", "clean_element_count": 1,
    })


def test_artifact_reader_resolves_roles_by_content_id_only(tmp_path):
    index = CanonicalArtifactIndex("run", tmp_path / "state/newsroom/canonical_artifact_index.jsonl",
                                   tmp_path / "materials", repository_root=tmp_path)
    url = "https://example.test/one"
    bob = {"source_url": url, "title": "Duplicate", "status": "ready_for_alfred",
           "canonical_source_body": _contract(url), "body_html": "<p>Bob</p>"}
    index.observe_bob({"articles": [bob]})
    index.observe_alfred({"reviews": [{"source_url": url, "title": "Duplicate", "decision": "approved",
        "approved_article": {"source_url": url, "body_html": "<p>Alfred</p>"}}]})
    index.observe_publisher({"results": [{"source_url": url, "title": "Duplicate", "status": "published",
        "published_cleaned_full_text": "Final"}]})
    other_url = "https://example.test/two"
    index.observe_bob({"articles": [{"source_url": other_url, "title": "Duplicate", "status": "ready_for_alfred",
        "canonical_source_body": _contract(other_url), "body_html": "<p>Other Bob</p>"}]})
    loaded = read_artifact_index(tmp_path)
    cid = next(key for key, values in loaded["rows_by_content_id"].items()
               if any(row.get("source_url") == url for row in values) or len(values) >= 4)
    chain = resolve_material_chain(tmp_path, cid, index=loaded)
    assert chain["roles"]["source_material"]["available"]
    assert chain["roles"]["translated_candidate"]["available"]
    assert chain["roles"]["final_published_material"]["text"] == "Final"
    other = next(key for key in loaded["rows_by_content_id"] if key != cid)
    assert resolve_material_chain(tmp_path, other, index=loaded)["roles"]["final_published_material"]["available"] is False
    assert resolve_material_chain(tmp_path, "cnt_missing", index=loaded)["reason"] == "content_id_not_indexed"
    assert resolve_material_chain(tmp_path, "report", content_kind="report")["reason"] == REPORT_SCOPE_REASON


def test_artifact_reader_never_synthesizes_chain_across_correlations(tmp_path):
    path = tmp_path / "state/newsroom/canonical_artifact_index.jsonl"
    run_one = CanonicalArtifactIndex("run-one", path, tmp_path / "materials", repository_root=tmp_path)
    run_two = CanonicalArtifactIndex("run-two", path, tmp_path / "materials", repository_root=tmp_path)
    url = "https://example.test/repeated"
    run_one.observe_bob({"articles": [{"source_url": url, "status": "ready_for_alfred",
        "canonical_source_body": _contract(url), "body_html": "<p>candidate</p>"}]})
    run_two.observe_publisher({"results": [{"source_url": url, "status": "published",
        "published_cleaned_full_text": "final"}]})
    loaded = read_artifact_index(tmp_path); cid = next(iter(loaded["rows_by_content_id"]))
    chain = resolve_material_chain(tmp_path, cid, index=loaded)
    assert len(chain["chain_instances"]) == 2
    assert chain["roles"]["final_published_material"]["available"] is True
    assert chain["roles"]["source_material"]["available"] is False
    assert chain["roles"]["translated_candidate"]["available"] is False


def test_translation_audit_joins_publication_and_material_by_content_id(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    state = tmp_path / "state/newsroom"; state.mkdir(parents=True)
    url = "https://example.test/audit-one"
    index = CanonicalArtifactIndex("run", state / "canonical_artifact_index.jsonl",
                                   tmp_path / "materials", repository_root=tmp_path)
    item = {"source_url": url, "title": "Same title", "status": "ready_for_alfred",
            "canonical_source_body": _contract(url), "body_html": "<p>candidate</p>"}
    index.observe_bob({"articles": [item]})
    index.observe_alfred({"reviews": [{"source_url": url, "decision": "approved",
        "approved_article": {"source_url": url, "body_html": "<p>approved</p>"}}]})
    index.observe_publisher({"results": [{"source_url": url, "status": "published",
        "published_cleaned_full_text": "final"}]})
    unpublished_url = "https://example.test/audit-unpublished"
    index.observe_bob({"articles": [{"source_url": unpublished_url, "title": "Unpublished", "status": "ready_for_alfred",
        "canonical_source_body": _contract(unpublished_url), "body_html": "<p>unpublished candidate</p>"}]})
    index.observe_alfred({"reviews": [{"source_url": unpublished_url, "decision": "approved",
        "approved_article": {"source_url": unpublished_url, "body_html": "<p>unpublished approved</p>"}}]})
    run = {"schema_version": "v93_19_fixture", "recorded_at": now.isoformat(),
           "run": {"run_id": "run", "started_at": now.isoformat(), "ended_at": now.isoformat(), "runtime_exit_code": 0},
           "publisher": {"results": [{"source_url": url, "title": "Same title", "status": "published",
                                        "published_at": now.isoformat(), "wp_link": "https://wp.test/one"}]}}
    (state / "master_log.jsonl").write_text(json.dumps(run) + "\n")
    events = CanonicalEventLedger("run", state / "canonical_event_ledger.jsonl")
    events.event("run_started", "Jarvis", "runtime", "started")
    events.event("publication_completed", "Publisher", "publication", "success", item={"source_url": url})
    event_rows = _rows(events.path)
    event_rows[0]["timestamp_utc"] = (now - timedelta(hours=25)).isoformat()
    event_rows[1]["timestamp_utc"] = now.isoformat()
    events.path.write_text("\n".join(json.dumps(row) for row in event_rows) + "\n")
    rows = discover(tmp_path, 24, None)
    canonical = [row for row in rows if row.key.startswith("cnt_")]
    assert len(canonical) == 1
    row = canonical[0]
    assert row.wp_link == "https://wp.test/one" and row.source_material_available
    assert row.translated_candidate_material_available and row.final_published_material_available
    assert row.comparative_pair_available


def test_snapshot_unique_windowing_zero_and_partial(tmp_path):
    path = tmp_path / "state/newsroom/canonical_event_ledger.jsonl"
    ledger = CanonicalEventLedger("old", path)
    old = datetime.now(timezone.utc) - timedelta(hours=60)
    ledger.event("candidate_selected", "Menzo", "selection", "success", item={"source_url": "https://x/a"})
    rows = _rows(path)
    rows[0]["timestamp_utc"] = old.isoformat()
    coverage_marker = dict(rows[0], event_type="run_started", agent="Jarvis", stage="runtime",
                           status="started", timestamp_utc=(old - timedelta(hours=10)).isoformat())
    coverage_marker.pop("content_id", None); coverage_marker.pop("correlation_id", None); coverage_marker.pop("article_id", None)
    duplicate = dict(rows[0], run_id="new", timestamp_utc=(old + timedelta(hours=40)).isoformat())
    publication = dict(duplicate, event_type="publication_completed", agent="Publisher", stage="publication")
    path.write_text("\n".join(json.dumps(x) for x in [coverage_marker, rows[0], duplicate, publication]) + "\n")
    until = old + timedelta(hours=50)
    full = build_snapshot(until - timedelta(hours=24), until, tmp_path)
    assert full["authoritative"]["funnel"]["metrics"]["menzo_unique_selected"] == {
        "event_count": 1, "unique_content_count": 1, "content_ids": [rows[0]["content_id"]]}
    assert full["authoritative"]["publication"]["unique_news_publications"] == 1
    partial = build_snapshot(until - timedelta(hours=72), until, tmp_path)
    assert partial["section_metadata"]["canonical_events"]["coverage"] == "partial"
    assert partial["authoritative"]["publication"]["unique_news_publications"] is None
    assert partial["authoritative"]["publication"]["news"]["content_ids"] is None
    assert partial["authoritative"]["runs"]["event_count"] is None
    assert partial["authoritative"]["funnel"]["metrics"]["menzo_unique_selected"]["event_count"] is None
    assert partial["authoritative"]["funnel"]["metrics"]["menzo_unique_selected"]["content_ids"] is None


def test_section_specific_cutover_actionable_ai_and_final_blockers(tmp_path):
    path = tmp_path / "state/newsroom/canonical_event_ledger.jsonl"
    ledger = CanonicalEventLedger("run", path)
    now = datetime.now(timezone.utc); since = now - timedelta(hours=24)
    selected = {"source_url": "https://x/selected"}; skipped = {"source_url": "https://x/skipped"}
    ledger.event("candidate_selected", "Menzo", "selection", "success", item=selected)
    ledger.event("candidate_skipped", "Menzo", "selection", "skipped", item=skipped, reason_code="low")
    rows = _rows(path)
    rows[0]["timestamp_utc"] = (since - timedelta(hours=1)).isoformat()
    rows[1]["timestamp_utc"] = (since + timedelta(hours=1)).isoformat()
    marker = dict(rows[0], event_type="run_started", agent="Jarvis", stage="runtime", status="started",
                  timestamp_utc=(since + timedelta(hours=12)).isoformat(), code_commit="ca0fdf1ca9a3d27e94f13570c754047c7203251f")
    for key in ("content_id", "correlation_id", "article_id"):
        marker.pop(key, None)
    path.write_text("\n".join(json.dumps(row) for row in [rows[0], rows[1], marker]) + "\n")
    snap = build_snapshot(since, now, tmp_path)
    assert snap["section_metadata"]["p1_1_lifecycle"]["coverage"] == "full"
    assert snap["section_metadata"]["p1_3_core_ai_operations"]["coverage"] == "partial"
    assert snap["section_metadata"]["p1_3_ai_operations"]["coverage"] == "unavailable"
    assert snap["authoritative"]["ai_operations"]["real_attempts"] is None
    assert snap["authoritative"]["alfred"]["warning_occurrences"] is None
    assert snap["authoritative"]["funnel"]["unique_actionable_candidates"] == 0
    assert "unique_hard_skipped" not in snap["authoritative"]["funnel"]["metrics"]

    # Post-cutover request ownership includes its terminal row after the requested boundary.
    ledger = CanonicalEventLedger("later", path); install_active_ledger(ledger)
    try:
        from agents.canonical_event_ledger import OperationalAIRequest
        request = OperationalAIRequest("Bob", "report_translation")
        attempt = request.start("model"); request.completed(attempt, 7)
    finally:
        clear_active_ledger()
    emitted = _rows(path)
    for row in emitted[-3:]:
        row["timestamp_utc"] = (since + timedelta(hours=13)).isoformat()
        row["code_commit"] = "ca0fdf1ca9a3d27e94f13570c754047c7203251f"
    path.write_text("\n".join(json.dumps(row) for row in emitted) + "\n")
    post = build_snapshot(since + timedelta(hours=13), now, tmp_path)
    assert post["authoritative"]["ai_operations"]["real_attempts"] == 1
    assert post["authoritative"]["ai_operations"]["successful_attempts"] == 1
    assert post["authoritative"]["ai_operations"]["failed_attempts"] == 0


def test_full_active_ai_cutover_before_crossing_and_after_windows():
    base = datetime(2026, 8, 18, tzinfo=timezone.utc)
    rows = [{"timestamp_utc": base.isoformat(), "event_type": "logical_ai_request_created",
             "model_role": "report_translation"}]
    assert _coverage_from_cutover(rows, True, base - timedelta(hours=2), base - timedelta(hours=1),
                                  family="full_active_ai")[0] == "unavailable"
    assert _coverage_from_cutover(rows, True, base - timedelta(hours=1), base + timedelta(hours=1),
                                  family="full_active_ai")[0] == "partial"
    assert _coverage_from_cutover(rows, True, base, base + timedelta(hours=1),
                                  family="full_active_ai")[0] == "full"
    core = [{"timestamp_utc": (base - timedelta(days=1)).isoformat(),
             "event_type": "logical_ai_request_created", "model_role": "translation_generation"}]
    combined = core + rows
    assert _coverage_from_cutover(combined, True, base - timedelta(hours=1), base + timedelta(hours=1),
                                  family="p1_3_core")[0] == "full"
    assert _coverage_from_cutover(combined, True, base - timedelta(hours=1), base + timedelta(hours=1),
                                  family="full_active_ai")[0] == "partial"


def test_warning_events_are_reviews_not_occurrences(tmp_path):
    path = tmp_path / "state/newsroom/canonical_event_ledger.jsonl"; now = datetime.now(timezone.utc)
    ledger = CanonicalEventLedger("run", path)
    for item, count in (({"source_url": "https://x/a"}, 3), ({"source_url": "https://x/b"}, 1)):
        for number in range(count):
            ledger.event("warning_recorded", "Alfred", "audit", "success", item=item,
                         reason_code=f"w{number}", result="warning")
    rows = _rows(path)
    for number, row in enumerate(rows):
        row["timestamp_utc"] = (now - timedelta(minutes=30) + timedelta(seconds=number)).isoformat()
        row["code_commit"] = "ca0fdf1ca9a3d27e94f13570c754047c7203251f"
    marker = dict(rows[0], event_type="run_started", agent="Jarvis", stage="runtime", status="started",
                  timestamp_utc=(now - timedelta(hours=2)).isoformat())
    for key in ("content_id", "correlation_id", "article_id", "reason_code", "result"):
        marker.pop(key, None)
    path.write_text("\n".join(json.dumps(row) for row in [marker] + rows) + "\n")
    alfred = build_snapshot(now - timedelta(hours=1), now, tmp_path)["authoritative"]["alfred"]
    assert alfred["articles_with_warnings"] == 2
    assert alfred["warning_events"] == 2
    assert alfred["warning_occurrences"] == 4


def test_malformed_canonical_ledger_suppresses_all_authoritative_totals(tmp_path):
    path = tmp_path / "state/newsroom/canonical_event_ledger.jsonl"; path.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    ledger = CanonicalEventLedger("run", path)
    ledger.event("candidate_selected", "Menzo", "selection", "success", item={"source_url": "https://x/a"})
    rows = _rows(path)
    rows[0]["timestamp_utc"] = (now - timedelta(hours=2)).isoformat()
    path.write_text(json.dumps(rows[0]) + "\n{malformed\n")
    snap = build_snapshot(now - timedelta(hours=1), now, tmp_path)
    assert snap["section_metadata"]["p1_1_lifecycle"]["available"] is False
    assert snap["section_metadata"]["p1_1_lifecycle"]["unavailability_reason"] == "canonical_event_ledger_malformed_json"
    assert snap["authoritative"]["publication"]["unique_news_publications"] is None
    assert snap["authoritative"]["funnel"]["metrics"]["menzo_unique_selected"]["event_count"] is None
    assert snap["authoritative"]["funnel"]["metrics"]["menzo_unique_selected"]["content_ids"] is None


@pytest.mark.parametrize("conditional", [False, True])
def test_schema_invalid_canonical_event_invalidates_authority(tmp_path, conditional):
    path = tmp_path / "state/newsroom/canonical_event_ledger.jsonl"; path.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc); ledger = CanonicalEventLedger("run", path)
    ledger.event("run_started", "Jarvis", "runtime", "started")
    rows = _rows(path); rows[0]["timestamp_utc"] = (now - timedelta(hours=2)).isoformat()
    invalid = dict(rows[0]) if not conditional else {
        **rows[0], "event_type": "model_attempt_started", "agent": "Gemini", "stage": "model", "status": "started"}
    if conditional:
        invalid.pop("content_id", None); invalid.pop("correlation_id", None)
    else:
        invalid.pop("run_id")
    invalid["timestamp_utc"] = (now - timedelta(minutes=10)).isoformat()
    path.write_text("\n".join(json.dumps(row) for row in [rows[0], invalid]) + "\n")
    snap = build_snapshot(now - timedelta(hours=1), now, tmp_path)
    metadata = snap["section_metadata"]["p1_1_lifecycle"]
    assert metadata["available"] is False
    assert metadata["unavailability_reason"] == "canonical_event_ledger_schema_invalid"
    assert any("canonical_event_ledger_schema_invalid" in item for item in metadata["diagnostic_mismatches"])


def test_daily_headline_obeys_present_p1_1_authority_boundary():
    authoritative = {"runs": {"value": 2},
        "publication": {"unique_news_publications": 3, "unique_report_publications": 1}}
    legacy = (9, 10, 11)
    assert resolve_p1_1_headline({}, authoritative, legacy) == legacy
    assert resolve_p1_1_headline({"p1_1_lifecycle": {"complete_window": True}}, authoritative, legacy) == (2, 3, 1)
    assert resolve_p1_1_headline({"p1_1_lifecycle": {"complete_window": False}}, authoritative, legacy) == (None, None, None)
    assert resolve_p1_1_headline({"p1_1_lifecycle": {"available": False}}, authoritative, legacy) == (None, None, None)


def test_canonical_payload_boundaries_and_classifications():
    legacy = {name: {"legacy": 9} for name in ("menzo", "alfred", "gemini", "simone")}
    authoritative = {"funnel": {"p1": 1}, "alfred": {"p1": 2},
                     "ai_operations": {"p1": 3}, "simone": {"p1": 4}}
    assert resolve_p1_4_canonical_payloads({}, authoritative, legacy) == legacy
    full = {"p1_1_lifecycle": {"complete_window": True},
            "p1_3_warning_occurrences": {"complete_window": True},
            "p1_3_failure_semantics": {"complete_window": True},
            "p1_3_ai_operations": {"complete_window": True}}
    assert resolve_p1_4_canonical_payloads(full, authoritative, legacy) == {
        "menzo": authoritative["funnel"], "alfred": authoritative["alfred"],
        "gemini": authoritative["ai_operations"], "simone": authoritative["simone"]}
    incomplete = {family: {"complete_window": False} for family in full}
    assert resolve_p1_4_canonical_payloads(incomplete, authoritative, legacy) == {
        "menzo": {}, "alfred": {}, "gemini": {}, "simone": {}}
    assert resolve_editorial_classifications({}, 20, 1, 12, 5, False) == ("post-show", "OTTIMO")
    assert resolve_editorial_classifications(incomplete, 20, 1, 12, 5, False) == (None, None)


@pytest.mark.parametrize("damage,expected", [("valid", 1), ("missing", 0), ("sha", 0)])
def test_artifact_snapshot_counts_only_verified_bytes(tmp_path, damage, expected):
    path = tmp_path / "state/newsroom/canonical_artifact_index.jsonl"
    index = CanonicalArtifactIndex("run", path, tmp_path / "materials", repository_root=tmp_path)
    url = "https://example.test/verified"
    index.observe_bob({"articles": [{"source_url": url, "status": "ready_for_alfred",
        "canonical_source_body": _contract(url), "body_html": "<p>candidate</p>"}]})
    rows = _rows(path); candidate = next(row for row in rows if row["semantic_roles"] == ["translated_candidate"])
    now = datetime.now(timezone.utc)
    source = next(row for row in rows if row["semantic_roles"] == ["source_material"])
    source["manifested_at_utc"] = (now - timedelta(hours=2)).isoformat()
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    if damage == "missing":
        (tmp_path / candidate["path"]).unlink()
    elif damage == "sha":
        (tmp_path / candidate["path"]).write_text("tampered")
    snapshot, metadata = _artifact_snapshot(tmp_path, now - timedelta(hours=1), now + timedelta(hours=1))
    assert snapshot["role_coverage"]["translated_candidate"]["artifact_count"] == expected
    assert bool(metadata["diagnostic_mismatches"]) is (damage != "valid")


def test_artifact_counts_are_null_for_partial_and_unavailable_coverage(tmp_path):
    path = tmp_path / "state/newsroom/canonical_artifact_index.jsonl"
    index = CanonicalArtifactIndex("run", path, tmp_path / "materials", repository_root=tmp_path)
    index.observe_bob({"articles": [{"source_url": "https://x/partial", "status": "ready_for_alfred",
        "canonical_source_body": _contract("https://x/partial"), "body_html": "<p>candidate</p>"}]})
    now = datetime.now(timezone.utc)
    partial, partial_metadata = _artifact_snapshot(tmp_path, now - timedelta(hours=1), now + timedelta(hours=1))
    assert partial_metadata["coverage"] == "partial"
    assert partial["role_coverage"]["translated_candidate"] == {"artifact_count": None, "unique_content_count": None}
    unavailable, unavailable_metadata = _artifact_snapshot(tmp_path / "missing", now - timedelta(hours=1), now)
    assert unavailable_metadata["coverage"] == "unavailable"
    assert unavailable["role_coverage"]["translated_candidate"] == {"artifact_count": None, "unique_content_count": None}


def test_artifact_index_read_failures_are_fail_open(tmp_path, monkeypatch):
    directory_root = tmp_path / "directory-case"
    directory_index = directory_root / "state/newsroom/canonical_artifact_index.jsonl"
    directory_index.mkdir(parents=True)
    directory = read_artifact_index(directory_root)
    assert directory["available"] is False and directory["reason"] == "canonical_artifact_index_unreadable"
    snapshot, metadata = _artifact_snapshot(directory_root, datetime.now(timezone.utc) - timedelta(hours=1),
                                            datetime.now(timezone.utc))
    assert metadata["available"] is False and snapshot["role_coverage"]

    index_path = tmp_path / "state/newsroom/canonical_artifact_index.jsonl"
    index_path.parent.mkdir(parents=True); index_path.write_text("{}\n")
    original = Path.read_text
    def denied(self, *args, **kwargs):
        if self == index_path:
            raise PermissionError("denied")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", denied)
    unreadable = read_artifact_index(tmp_path)
    assert unreadable["available"] is False
    assert unreadable["reason"] == "canonical_artifact_index_unreadable"
    assert unreadable["diagnostic_mismatches"] == ["index_read_failed:PermissionError"]
    _snapshot, denied_metadata = _artifact_snapshot(tmp_path, datetime.now(timezone.utc) - timedelta(hours=1),
                                                    datetime.now(timezone.utc))
    assert denied_metadata["available"] is False
    assert discover(tmp_path, 24, None) == []


def test_artifact_index_never_seeds_fallback_publication_population(tmp_path):
    path = tmp_path / "state/newsroom/canonical_artifact_index.jsonl"
    recent = CanonicalArtifactIndex("recent", path, tmp_path / "materials", repository_root=tmp_path)
    old = CanonicalArtifactIndex("old", path, tmp_path / "materials", repository_root=tmp_path)
    recent.observe_bob({"articles": [{"source_url": "https://x/unpublished", "status": "ready_for_alfred",
        "canonical_source_body": _contract("https://x/unpublished"), "body_html": "<p>candidate</p>"}]})
    old.observe_bob({"articles": [{"source_url": "https://x/old", "status": "ready_for_alfred",
        "canonical_source_body": _contract("https://x/old"), "body_html": "<p>old</p>"}]})
    assert [row for row in discover(tmp_path, 24, None) if row.key.startswith("cnt_")] == []


def test_translation_audit_rejects_legacy_publication_when_canonical_partial(tmp_path):
    now = datetime.now(timezone.utc); state = tmp_path / "state/newsroom"; state.mkdir(parents=True)
    url = "https://x/legacy-only"
    run = {"schema_version": "v93_19_fixture", "recorded_at": now.isoformat(),
           "run": {"run_id": "run", "started_at": now.isoformat(), "ended_at": now.isoformat(), "runtime_exit_code": 0},
           "publisher": {"results": [{"source_url": url, "status": "published", "published_at": now.isoformat()}]}}
    (state / "master_log.jsonl").write_text(json.dumps(run) + "\n")
    events = CanonicalEventLedger("run", state / "canonical_event_ledger.jsonl")
    events.event("publication_completed", "Publisher", "publication", "success", item={"source_url": url})
    assert [row for row in discover(tmp_path, 24, None) if row.key.startswith("cnt_")] == []


def test_translation_audit_uses_canonical_publication_without_master_log(tmp_path):
    now = datetime.now(timezone.utc); state = tmp_path / "state/newsroom"; state.mkdir(parents=True)
    url = "https://x/canonical-only"
    index = CanonicalArtifactIndex("run", state / "canonical_artifact_index.jsonl",
                                   tmp_path / "materials", repository_root=tmp_path)
    index.observe_bob({"articles": [{"source_url": url, "status": "ready_for_alfred",
        "canonical_source_body": _contract(url), "body_html": "<p>candidate</p>"}]})
    index.observe_publisher({"results": [{"source_url": url, "status": "published",
        "published_cleaned_full_text": "final"}]})
    events = CanonicalEventLedger("run", state / "canonical_event_ledger.jsonl")
    events.event("run_started", "Jarvis", "runtime", "started")
    events.event("publication_completed", "Publisher", "publication", "success", item={"source_url": url})
    rows = _rows(events.path); rows[0]["timestamp_utc"] = (now - timedelta(hours=25)).isoformat()
    rows[1]["timestamp_utc"] = now.isoformat()
    events.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    audited = [row for row in discover(tmp_path, 24, None) if row.key.startswith("cnt_")]
    assert len(audited) == 1
    assert audited[0].source_material_available and audited[0].final_published_material_available


def test_pre_attempt_and_model_terminal_requests_count_once(monkeypatch, tmp_path):
    import modules.report_workshop_v92 as workshop
    from agents.canonical_event_ledger import OperationalAIRequest
    path = tmp_path / "state/newsroom/canonical_event_ledger.jsonl"; path.parent.mkdir(parents=True)
    ledger = CanonicalEventLedger("run", path); install_active_ledger(ledger)
    now = datetime.now(timezone.utc)
    try:
        cutover = OperationalAIRequest("Bob", "report_translation")
        cutover.avoided("fixture_cutover")
        monkeypatch.setattr(workshop, "GEMINI_API_KEY", "")
        with pytest.raises(RuntimeError):
            workshop.generate_json("prompt", "report_blocks_legacy_prompt")
        monkeypatch.setattr(workshop, "GEMINI_API_KEY", "key")
        monkeypatch.setattr(workshop.genai, "Client", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("init")))
        with pytest.raises(RuntimeError):
            workshop.generate_json("prompt", "report_blocks_legacy_prompt")
        ordinary = OperationalAIRequest("Bob", "report_translation")
        attempt = ordinary.start("model"); ordinary.failed(attempt, error_class="upstream", error_terminal=True)
        ledger.event("stage_failed", "Bob", "model", "failed", logical_request_id=ordinary.logical_request_id,
                     model_role="report_translation", reason_code="duplicate_terminal_evidence",
                     error_class="upstream", error_terminal=True)
    finally:
        clear_active_ledger()
    rows = _rows(path)
    creation_times = [row for row in rows if row["event_type"] == "logical_ai_request_created"]
    cutover_time = now - timedelta(hours=2)
    for row in rows:
        row["timestamp_utc"] = (cutover_time if row.get("logical_request_id") == creation_times[0]["logical_request_id"]
                                else now - timedelta(minutes=10)).isoformat()
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    ai = build_snapshot(now - timedelta(hours=1), now, tmp_path)["authoritative"]["ai_operations"]
    assert ai["logical_requests"] == 3
    assert ai["real_attempts"] == 1
    assert ai["terminal_failures"] == 3


def test_final_blockers_resolve_only_after_later_approval_or_publication(tmp_path):
    path = tmp_path / "state/newsroom/canonical_event_ledger.jsonl"; now = datetime.now(timezone.utc)
    ledger = CanonicalEventLedger("run", path)
    resolved = {"source_url": "https://x/resolved"}; open_item = {"source_url": "https://x/open"}
    ledger.event("blocker_recorded", "Alfred", "audit", "success", item=resolved, reason_code="b", result="blocker")
    ledger.event("quality_review_completed", "Alfred", "quality", "success", item=resolved, result="approved")
    ledger.event("publication_completed", "Publisher", "publication", "success", item=resolved)
    ledger.event("blocker_recorded", "Alfred", "audit", "success", item=open_item, reason_code="b", result="blocker")
    rows = _rows(path)
    for number, row in enumerate(rows):
        row["timestamp_utc"] = (now - timedelta(hours=1) + timedelta(minutes=number)).isoformat()
        row["code_commit"] = "ca0fdf1ca9a3d27e94f13570c754047c7203251f"
    marker = dict(rows[0], event_type="run_started", agent="Jarvis", stage="runtime", status="started",
                  timestamp_utc=(now - timedelta(hours=3)).isoformat())
    for key in ("content_id", "correlation_id", "article_id", "reason_code", "result"):
        marker.pop(key, None)
    path.write_text("\n".join(json.dumps(row) for row in [marker] + rows) + "\n")
    snap = build_snapshot(now - timedelta(hours=2), now, tmp_path)
    # Cutover evidence predates the window while the lifecycle events are inside it.
    assert snap["authoritative"]["alfred"]["blocker_occurrences"] == 2
    assert snap["authoritative"]["alfred"]["final_blockers"] == 1
