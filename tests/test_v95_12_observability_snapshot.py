from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.master_log_v93_19 import build_master_record
from scripts.observability_snapshot import build_snapshot, parse_utc_datetime, repository_diagnostics, stable_article_identity
from scripts.translation_quality_audit import ArticleAudit, discover, run_checks
import scripts.daily_editorial_judgment as dej

SINCE = datetime(2026, 7, 13, 10, tzinfo=timezone.utc)
UNTIL = datetime(2026, 7, 14, 10, tzinfo=timezone.utc)


def master_row(at: datetime, *, idx: int, selected=None, skipped=None, bob_articles=None, alfred_reviews=None, publisher_results=None, simone_results=None, postprocess=None, exit_code=0):
    row = build_master_record(
        run_summary={"started_at": (at - timedelta(minutes=4)).isoformat(), "ended_at": at.isoformat(), "runtime_exit_code": exit_code, "version": "test"},
        timeline=[],
        massy={},
        simone={},
        simone_publish={"results": simone_results or []},
        menzo={"selected": selected or [], "pending": [], "skipped": skipped or [], "postprocess": postprocess or {}},
        bob={"articles": bob_articles or []},
        alfred={"reviews": alfred_reviews or []},
        publisher={"results": publisher_results or []},
        archivista={},
    )
    row["recorded_at"] = at.isoformat()
    row["run"]["github_run_id"] = f"gh-{idx}"
    return row


def write_master(root: Path, rows: list[dict]):
    path = root / "state/newsroom/master_log.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def production_rows() -> list[dict]:
    rows = []
    published = [
        {"title": f"News {i} {'scommettere su se stesso' if i == 0 else 'mark' if i == 1 else 'fa parte del gioco' if i == 2 else ''}", "source_url": f"https://src/{i}", "wp_link": f"https://owtv/{i}", "status": "published"}
        for i in range(27)
    ]
    for i in range(47):
        at = SINCE + timedelta(minutes=20 * i)
        selected = [] if i == 46 else [{"title": "Repeated selected", "source_url": "https://src/repeated", "decision": "selected"}]
        pub = []
        sim = []
        bob = []
        reviews = []
        post = {}
        skipped = []
        if i == 1:
            pub = published[1:15]
        if i == 2:
            pub = published[15:]
        if i == 3:
            sim = [{"title": "Show report", "source_url": "https://src/report", "wp_link": "https://owtv/report", "status": "published"}]
        if i == 4:
            skipped = [{"title": "SummerSlam betting odds", "source_url": "https://src/skipped", "decision": "skip"}]
        if i == 5:
            reviews = [
                {"title": "News 0", "source_url": "https://src/0", "decision": "needs_revision", "warnings": [{"code": "copy"}], "blockers": [{"code": "needs_fix", "severity": "blocker"}]},
                {"title": "Final blocked", "source_url": "https://src/final-block", "decision": "needs_revision", "issues": [{"code": "legal", "severity": "blocker"}]},
            ]
        if i == 6:
            reviews = [{"title": "News 0", "source_url": "https://src/0", "decision": "approved"}]
        if i == 7:
            pub = [published[0]]
            bob = [{"title_it": "Bob article", "source_url": "https://src/0", "status": "ready_for_alfred"}]
            post = {"menzo_same_run_batch_calls": 2, "menzo_recent_history_duplicates_blocked": 1, "gemini_calls_used_for_duplicate_arbitration": 3, "unrelated_large_payload": 999}
        rows.append(master_row(at, idx=i, selected=selected, skipped=skipped, bob_articles=bob, alfred_reviews=reviews, publisher_results=pub, simone_results=sim, postprocess=post))
    old = master_row(SINCE - timedelta(minutes=1), idx=999, publisher_results=[{"title": "Old betting odds", "source_url": "https://src/old-betting", "wp_link": "https://owtv/old", "status": "published"}])
    return [old] + rows


def test_production_fixture_counts_exclusions_and_chronology(tmp_path):
    write_master(tmp_path, production_rows())
    # Tail contains duplicate complete rows but primary full master is authoritative.
    tail = tmp_path / "artifacts/newsroom/master_log_tail.jsonl"
    tail.parent.mkdir(parents=True)
    tail.write_text("\n".join(json.dumps(r) for r in production_rows()[:3]), encoding="utf-8")
    (tmp_path / "state/newsroom/arbitrary.json").write_text(json.dumps({"status": "published", "title": "Not authority", "source_url": "https://fake/published"}), encoding="utf-8")

    snap = build_snapshot(SINCE, UNTIL, tmp_path)

    assert snap["funnel"]["runs_seen"] == 47
    assert snap["funnel"]["runs_completed"] == 47
    assert snap["funnel"]["runs_failed"] == 0
    assert snap["publication"]["news_unique"] == 27
    assert snap["publication"]["reports_unique"] == 1
    assert snap["publication"]["total_unique"] == 28
    titles = " ".join(r["title"] for r in snap["publication"]["records"])
    assert "SummerSlam" not in titles and "Old betting" not in titles and "Not authority" not in titles
    assert snap["funnel"]["unique"]["menzo_unique_selected_for_downstream_handoff"] == 1
    assert snap["funnel"]["event_counts"]["menzo_selected_downstream"] == 46
    assert snap["funnel"]["unique"]["bob_unique_packages_produced"] == 1
    assert snap["alfred"]["events"]["warning_count"] == 1
    assert snap["alfred"]["events"]["blocker_count"] == 2
    assert snap["alfred"]["unique"]["revised_then_published"] == 1
    assert snap["alfred"]["unique"]["final_blocked"] == 1
    assert snap["duplicate_arbitration"]["available"] is True
    assert snap["duplicate_arbitration"]["covered_runs"] == 1
    assert snap["duplicate_arbitration"]["counters"]["menzo_same_run_batch_calls"] == 2
    assert snap["duplicate_arbitration"]["counters"]["gemini_calls_used_for_duplicate_arbitration"] == 3
    assert snap["artifact_sources"] == ["state/newsroom/master_log.jsonl"]


def test_exact_boundaries_and_identity_with_parent_timestamps(tmp_path):
    rows = [
        master_row(SINCE, idx=1, publisher_results=[{"title": "Lower", "source_url": "https://src/lower", "status": "published"}]),
        master_row(UNTIL, idx=2, simone_results=[{"title": "Upper report", "source_url": "https://src/upper-report", "status": "published"}]),
        master_row(SINCE - timedelta(seconds=1), idx=3, publisher_results=[{"title": "Too old", "source_url": "https://src/old", "status": "published"}]),
    ]
    write_master(tmp_path, rows)
    snap = build_snapshot(SINCE, UNTIL, tmp_path)
    assert snap["publication"]["news_unique"] == 1
    assert snap["publication"]["reports_unique"] == 1
    assert parse_utc_datetime("2026-07-13T10:00:00Z") == SINCE
    assert stable_article_identity({"source_url": "https://www.Example.com/a?utm_source=x&b=1#f"}) == "source:https://example.com/a?b=1"


def test_missing_duplicate_counter_coverage_is_not_authoritative_zero(tmp_path):
    write_master(tmp_path, [master_row(SINCE + timedelta(minutes=1), idx=1, selected=[{"source_url": "https://src/a"}])])
    snap = build_snapshot(SINCE, UNTIL, tmp_path)
    assert snap["duplicate_arbitration"] == {"available": False, "covered_runs": 0, "total_runs": 1, "counters": {}}
    assert "menzo_duplicate_arbitration_counter_stream_not_available" in snap["schema_warnings"]


def test_empty_authoritative_publication_set_means_empty_translation_audit(tmp_path):
    write_master(tmp_path, [master_row(SINCE + timedelta(minutes=1), idx=1, selected=[{"source_url": "https://src/a"}])])
    pub = tmp_path / "published_html_review"
    pub.mkdir()
    (pub / "orphan.html").write_text("<html><title>Orphan</title><p>Welcome to our coverage.</p></html>", encoding="utf-8")
    assert discover(tmp_path, hours=24, limit=None) == []


def test_malformed_master_jsonl_fails_soft_to_legacy_audit(tmp_path):
    ns = tmp_path / "state/newsroom"
    ns.mkdir(parents=True)
    (ns / "master_log.jsonl").write_text('{bad json\n', encoding="utf-8")
    pub = tmp_path / "published_html_review"
    pub.mkdir()
    (pub / "orphan.html").write_text("<html><title>Orphan</title><p>Welcome to our coverage.</p></html>", encoding="utf-8")
    snap = build_snapshot(SINCE, UNTIL, tmp_path)
    assert snap["authority_available"] is False
    assert any("malformed_jsonl" in w for w in snap["schema_warnings"])
    assert len(discover(tmp_path, hours=24, limit=None)) == 1


def test_reports_untracked_path_is_expected_runtime(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL)
    (tmp_path / "tracked.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "runtime.json").write_text("{}", encoding="utf-8")
    diag = repository_diagnostics(tmp_path)
    assert any(path == "reports/" or path.startswith("reports/") for path in diag["expected_runtime_untracked_paths"])
    assert all("reports/" not in item and "reports/runtime.json" not in item for item in diag["actual_source_modifications"])


def test_false_positive_hygiene():
    for text in ["scommettere su se stesso", "mark", "fa parte del gioco"]:
        a = ArticleAudit(key=text, title=text, published_text=text, published_text_length=len(text))
        if "gioco" in text:
            a.alfred_warnings = ["possible_match_mistranslation"]
        run_checks(a)
        assert "betting_odds_article_published" not in a.issues
        assert "untranslated_quote_or_residual_english" not in a.issues
        assert "possible_match_mistranslation" not in a.issues
        if "gioco" in text:
            assert a.possible_false_positive_warnings


def test_master_record_preserves_alfred_decision_blockers_and_menzo_counters():
    row = master_row(
        SINCE + timedelta(minutes=1),
        idx=1,
        alfred_reviews=[{"title": "Review", "source_url": "https://src/rev", "decision": "needs_revision", "issues": [{"code": "x", "severity": "blocker"}], "warnings": [{"code": "w"}], "editorial_changes": [{"code": "c"}]}],
        postprocess={"menzo_same_run_batch_calls": 4, "gemini_calls_used_for_duplicate_arbitration": 5, "unrelated_large_payload": 99},
    )
    review = row["alfred"]["reviews"][0]
    assert review["status"] == "needs_revision"
    assert review["blockers"][0]["severity"] == "blocker"
    assert row["menzo"]["duplicate_arbitration"] == {"menzo_same_run_batch_calls": 4, "gemini_calls_used_for_duplicate_arbitration": 5}


def test_daily_judgment_production_integration(tmp_path, monkeypatch):
    write_master(tmp_path, production_rows())
    monkeypatch.setattr(dej, "ROOT", tmp_path)
    monkeypatch.setattr(dej, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(dej, "STATE_REPORTS_DIR", tmp_path / "state/reports")
    outputs = dej.generate_daily_editorial_judgment_outputs(paths={"master_log": tmp_path / "state/newsroom/master_log.jsonl"}, output_dir=tmp_path / "reports", state_dir=tmp_path / "state/reports", now=UNTIL, hours=24)
    md = outputs["markdown"].read_text(encoding="utf-8")
    payload = json.loads(outputs["json"].read_text(encoding="utf-8"))
    assert "news published: 27" in md
    assert "reports published: 1" in md
    assert "runs completed: 47" in md
    obs = payload["daily_numbers"]["observability_snapshot"]
    assert obs["funnel"]["runs_completed"] == 47
    assert obs["funnel"]["unique"]["menzo_unique_selected_for_downstream_handoff"] == 1
    assert obs["alfred"]["unique"]["final_blocked"] == 1
    assert obs["duplicate_arbitration"]["available"] is True


def test_daily_judgment_snapshot_authority_overrides_markdown_mismatch(tmp_path, monkeypatch):
    write_master(tmp_path, production_rows())
    op = tmp_path / "op.json"
    op.write_text(json.dumps({"_markdown": "- Run completate: 46\n- Articoli/news pubblicati da Publisher: 26\n- Report pubblicati da Simone: 0\n- Alfred warnings: 10\n- Alfred blockers: 3\n"}), encoding="utf-8")
    monkeypatch.setattr(dej, "ROOT", tmp_path)
    report = dej.build_report(dej.load_inputs({"master_log": tmp_path / "state/newsroom/master_log.jsonl", "operational_report": op}, now=UNTIL))
    payload = dej.structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 27
    assert payload["daily_numbers"]["reports_published"] == 1
    assert payload["daily_numbers"]["runs_completed"] == 47
    assert payload["daily_numbers"]["alfred"] == {"warnings": 1, "blockers": 1}
    assert "observability_news_count_differs_from_markdown" in payload["schema_warnings"]
    assert "observability_reports_count_differs_from_markdown" in payload["schema_warnings"]


def test_daily_judgment_authoritative_zeroes_are_not_replaced(tmp_path, monkeypatch):
    empty = tmp_path / "state/newsroom/master_log.jsonl"
    empty.parent.mkdir(parents=True)
    empty.write_text("", encoding="utf-8")
    op = tmp_path / "op.json"
    op.write_text(json.dumps({"_markdown": "- Run completate: 15\n- Articoli/news pubblicati da Publisher: 15\n- Report pubblicati da Simone: 1\n- Alfred warnings: 10\n- Alfred blockers: 3\n"}), encoding="utf-8")
    monkeypatch.setattr(dej, "ROOT", tmp_path)
    report = dej.build_report(dej.load_inputs({"master_log": empty, "operational_report": op}, now=UNTIL))
    payload = dej.structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 0
    assert payload["daily_numbers"]["reports_published"] == 0
    assert payload["daily_numbers"]["runs_completed"] == 0
    assert payload["daily_numbers"]["alfred"] == {"warnings": 0, "blockers": 0}


def test_publisher_storage_views_do_not_double_count_events(tmp_path):
    row = master_row(SINCE + timedelta(minutes=1), idx=1)
    item = {"title": "Same", "source_url": "https://src/same", "wp_link": "https://owtv/same", "status": "published"}
    row["publisher"] = {"published": [item], "results": [dict(item)]}
    write_master(tmp_path, [row])
    snap = build_snapshot(SINCE, UNTIL, tmp_path)
    assert snap["publication"]["news_unique"] == 1
    assert snap["funnel"]["event_counts"]["publisher_published"] == 1
    assert snap["funnel"]["unique"]["publisher_unique_published"] == 1


def test_alfred_strict_chronology_cases(tmp_path):
    rows = [
        master_row(SINCE, idx=1, alfred_reviews=[{"source_url": "https://src/a", "decision": "needs_revision"}]),
        master_row(SINCE + timedelta(hours=1), idx=2, publisher_results=[{"source_url": "https://src/a", "title": "A", "status": "published"}]),
        master_row(SINCE, idx=3, publisher_results=[{"source_url": "https://src/b", "title": "B", "status": "published"}]),
        master_row(SINCE + timedelta(hours=1), idx=4, alfred_reviews=[{"source_url": "https://src/b", "decision": "needs_revision"}]),
        master_row(SINCE, idx=5, alfred_reviews=[{"source_url": "https://src/c", "decision": "approved"}]),
        master_row(SINCE + timedelta(hours=1), idx=6, alfred_reviews=[{"source_url": "https://src/c", "decision": "needs_revision", "blockers": [{"code": "x"}]}]),
        master_row(SINCE, idx=7, alfred_reviews=[{"source_url": "https://src/d", "decision": "needs_revision"}]),
        master_row(SINCE + timedelta(hours=1), idx=8, alfred_reviews=[{"source_url": "https://src/d", "decision": "approved"}]),
        master_row(SINCE, idx=9, alfred_reviews=[{"source_url": "https://src/e", "decision": "needs_revision", "blockers": [{"code": "x"}]}]),
        master_row(SINCE + timedelta(hours=1), idx=10, publisher_results=[{"source_url": "https://src/e", "title": "E", "status": "published"}]),
    ]
    write_master(tmp_path, rows)
    snap = build_snapshot(SINCE, UNTIL, tmp_path)
    assert snap["alfred"]["unique"]["revised_then_published"] == 2
    assert snap["alfred"]["unique"]["revised_then_approved"] == 1
    assert snap["alfred"]["unique"]["final_blocked"] == 2
    assert snap["alfred"]["unique"]["approved"] == 1


def test_translation_audit_authoritative_aliases_merge_to_one_row(tmp_path):
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    write_master(tmp_path, [master_row(now, idx=1, publisher_results=[{"title": "Alias Story", "source_url": "https://src/alias", "wp_link": "https://owtv/alias", "status": "published"}])])
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "source.json").write_text(json.dumps({"source_url": "https://src/alias", "original_text": "Original alias text " * 20}), encoding="utf-8")
    (art / "wp.json").write_text(json.dumps({"wp_link": "https://owtv/alias", "published_title": "Alias Story"}), encoding="utf-8")
    html_dir = tmp_path / "published_html_review"
    html_dir.mkdir()
    (html_dir / "v93-publisher-alias-story.html").write_text("<html><title>Alias Story</title><p>Published alias text.</p></html>", encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_url == "https://src/alias"
    assert row.wp_link == "https://owtv/alias"
    assert "Original alias text" in row.original_text
    assert "Published alias text" in row.published_text
    assert all("no_local_source_or_html_match_yet" not in p for p in row.artifact_paths)


def test_partial_primary_jsonl_keeps_valid_rows_and_health(tmp_path):
    rows = production_rows()[1:48]
    primary = tmp_path / "state/newsroom/master_log.jsonl"
    primary.parent.mkdir(parents=True)
    primary.write_text("\n".join(json.dumps(r) for r in rows) + "\n{bad\n", encoding="utf-8")
    tail = tmp_path / "artifacts/newsroom/master_log_tail.jsonl"
    tail.parent.mkdir(parents=True)
    tail.write_text("\n".join(json.dumps(r) for r in rows[:2]), encoding="utf-8")
    snap = build_snapshot(SINCE, UNTIL, tmp_path)
    assert snap["authority_available"] is True
    assert snap["funnel"]["runs_seen"] == 47
    assert snap["diagnostics"]["master_log_source"] == "primary"
    assert snap["diagnostics"]["master_log_partial"] is True
    assert snap["diagnostics"]["master_log_valid_rows"] == 47
    assert snap["diagnostics"]["master_log_malformed_lines"] == 1
    assert snap["diagnostics"]["tail_fallback_used"] is False


def test_completely_malformed_primary_uses_valid_tail_or_reports_unavailable(tmp_path):
    primary = tmp_path / "state/newsroom/master_log.jsonl"
    primary.parent.mkdir(parents=True)
    primary.write_text("{bad\n", encoding="utf-8")
    tail = tmp_path / "artifacts/newsroom/master_log_tail.jsonl"
    tail.parent.mkdir(parents=True)
    tail.write_text(json.dumps(master_row(SINCE, idx=1, publisher_results=[{"source_url": "https://src/tail", "status": "published"}])) + "\n", encoding="utf-8")
    snap = build_snapshot(SINCE, UNTIL, tmp_path)
    assert snap["authority_available"] is True
    assert snap["diagnostics"]["master_log_source"] == "tail_fallback"
    assert snap["diagnostics"]["tail_fallback_used"] is True
    assert snap["publication"]["news_unique"] == 1

    empty = tmp_path / "no_tail"
    bad = empty / "state/newsroom/master_log.jsonl"
    bad.parent.mkdir(parents=True)
    bad.write_text("{bad\n", encoding="utf-8")
    snap2 = build_snapshot(SINCE, UNTIL, empty)
    assert snap2["authority_available"] is False


def test_valid_empty_primary_is_authoritative_empty(tmp_path):
    primary = tmp_path / "state/newsroom/master_log.jsonl"
    primary.parent.mkdir(parents=True)
    primary.write_text("", encoding="utf-8")
    snap = build_snapshot(SINCE, UNTIL, tmp_path)
    assert snap["authority_available"] is True
    assert snap["publication"]["total_unique"] == 0
    assert snap["diagnostics"]["master_log_source"] == "primary"


def authoritative_publication_root(tmp_path: Path, *, title: str = "Material Story") -> tuple[Path, str, str]:
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    source_url = "https://src/material"
    wp_link = "https://owtv/material"
    write_master(tmp_path, [master_row(now, idx=321, publisher_results=[{"title": title, "source_url": source_url, "wp_link": wp_link, "status": "published"}])])
    return tmp_path, source_url, wp_link


def test_translation_audit_master_metadata_only_keeps_missing_material(tmp_path):
    authoritative_publication_root(tmp_path)
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_material_available is False
    assert row.published_material_available is False
    assert row.source_material_missing_reason == "source_material_not_found"
    assert row.published_material_missing_reason == "final_published_material_not_found"
    assert row.non_comparative_reason == "missing_source_and_final_published_material"
    assert "no_local_source_or_html_match_yet" in row.artifact_paths


def test_translation_audit_source_material_only_keeps_published_missing(tmp_path):
    _root, source_url, _wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "source.json").write_text(json.dumps({"source_url": source_url, "original_text": "Original source material " * 20}), encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_material_available is True
    assert row.published_material_available is False
    assert row.published_material_missing_reason == "final_published_material_not_found"
    assert row.non_comparative_reason == "final_published_material_missing"


def test_translation_audit_published_material_only_keeps_source_missing(tmp_path):
    authoritative_publication_root(tmp_path)
    html_dir = tmp_path / "published_html_review"
    html_dir.mkdir()
    (html_dir / "v93-publisher-material-story.html").write_text("<html><title>Material Story</title><p>Published material text.</p></html>", encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_material_available is False
    assert row.published_material_available is True
    assert row.source_material_missing_reason == "source_material_not_found"
    assert row.non_comparative_reason == "source_material_missing"


def test_translation_audit_complete_pair_has_one_canonical_comparative_row(tmp_path):
    _root, source_url, wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "source.json").write_text(json.dumps({"source_url": source_url, "original_text": "Original source material " * 20}), encoding="utf-8")
    (art / "wp_metadata.json").write_text(json.dumps({"wp_link": wp_link, "status": "published"}), encoding="utf-8")
    html_dir = tmp_path / "published_html_review"
    html_dir.mkdir()
    (html_dir / "v93-publisher-material-story.html").write_text("<html><title>Material Story</title><p>Published material text.</p></html>", encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_material_available is True
    assert row.published_material_available is True
    assert row.comparative_pair_available is True
    assert row.original_text.strip()
    assert row.published_text.strip()
    assert row.source_material_missing_reason == ""
    assert row.published_material_missing_reason == ""
    assert all("no_local_source_or_html_match_yet" not in p for p in row.artifact_paths)


def test_translation_audit_wp_metadata_alias_does_not_clear_missing_material(tmp_path):
    _root, _source_url, wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "wp_metadata.json").write_text(json.dumps({"wp_link": wp_link, "status": "published", "title": "Material Story"}), encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_material_available is False
    assert row.published_material_available is False
    assert row.source_material_missing_reason == "source_material_not_found"
    assert row.published_material_missing_reason == "final_published_material_not_found"


def test_translation_audit_coverage_summary_counts_material_availability(tmp_path):
    _root, source_url, _wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "source.json").write_text(json.dumps({"source_url": source_url, "original_text": "Original source material " * 20}), encoding="utf-8")
    payload, _latest, md = __import__("scripts.translation_quality_audit", fromlist=["build_audit"]).build_audit(hours=24, output_dir=tmp_path / "reports", root=tmp_path)
    expected = {
        "publication_authority_available": True,
        "authoritative_total": 1,
        "legacy_artifacts_inspected": 0,
        "source_material_available": 1,
        "translated_candidate_material_available": 0,
        "final_published_material_available": 0,
        "comparative_pairs_available": 0,
        "missing_source_material": 0,
        "missing_final_published_material": 1,
    }
    for key, value in expected.items():
        assert payload["coverage"][key] == value
    text = md.read_text(encoding="utf-8")
    assert "Authoritative publications: 1" in text
    assert "Source material available: 1" in text
    assert "Final published material available: 0" in text
    assert "Comparative pairs available: 0" in text


def test_translation_audit_empty_authoritative_publication_set_still_zero_rows(tmp_path):
    empty = tmp_path / "state/newsroom/master_log.jsonl"
    empty.parent.mkdir(parents=True)
    empty.write_text("", encoding="utf-8")
    assert discover(tmp_path, hours=24, limit=None) == []


def test_direct_cli_help_imports_work_from_repo_root():
    root = Path(__file__).resolve().parents[1]
    for script in ["scripts/translation_quality_audit.py", "scripts/daily_editorial_judgment.py", "scripts/observability_snapshot.py"]:
        result = subprocess.run([sys.executable, script, "--help"], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert result.returncode == 0, result.stderr
        assert "ModuleNotFoundError" not in result.stderr


def test_translation_audit_bob_body_html_is_candidate_not_final(tmp_path):
    _root, source_url, _wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "source.json").write_text(json.dumps({"source_url": source_url, "original_text": "Original source material " * 20}), encoding="utf-8")
    (art / "bob.json").write_text(json.dumps({"source_url": source_url, "body_html": "<p>Translated candidate body.</p>"}), encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_material_available is True
    assert row.translated_candidate_material_available is True
    assert row.final_published_material_available is False
    assert row.published_material_available is False
    assert row.comparative_pair_available is False
    assert row.final_published_material_missing_reason == "translated_candidate_only"


def test_translation_audit_alfred_body_html_is_candidate_not_final(tmp_path):
    _root, source_url, _wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "alfred.json").write_text(json.dumps({"approved_articles": [{"source_url": source_url, "body_html": "<p>Approved candidate body.</p>"}]}), encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.translated_candidate_material_available is True
    assert row.final_published_material_available is False
    assert row.comparative_pair_available is False


def test_translation_audit_real_published_html_makes_final_material(tmp_path):
    _root, source_url, _wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "source.json").write_text(json.dumps({"source_url": source_url, "original_text": "Original source material " * 20, "body_html": "<p>Candidate only</p>"}), encoding="utf-8")
    html_dir = tmp_path / "published_html_review"
    html_dir.mkdir()
    (html_dir / "v93-publisher-material-story.html").write_text("<html><title>Material Story</title><p>Final published text.</p></html>", encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.translated_candidate_material_available is True
    assert row.final_published_material_available is True
    assert row.comparative_pair_available is True


def test_translation_audit_explicit_source_html_counts_as_source(tmp_path):
    _root, source_url, _wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "source_html.json").write_text(json.dumps({"source_url": source_url, "source_html": "<article><p>Visible source HTML text.</p></article>"}), encoding="utf-8")
    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_material_available is True
    assert "Visible source HTML text" in row.original_text
    assert row.final_published_material_available is False


def test_translation_audit_authority_unavailable_coverage_labels_legacy_rows(tmp_path):
    ns = tmp_path / "state/newsroom"
    ns.mkdir(parents=True)
    (ns / "master_log.jsonl").write_text("{bad\n", encoding="utf-8")
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "legacy.json").write_text(json.dumps({"source_url": "https://legacy/story", "original_text": "Legacy source text " * 10}), encoding="utf-8")
    payload, _latest, md = __import__("scripts.translation_quality_audit", fromlist=["build_audit"]).build_audit(hours=24, output_dir=tmp_path / "reports", root=tmp_path)
    assert payload["coverage"]["publication_authority_available"] is False
    assert payload["coverage"]["authoritative_total"] is None
    assert payload["coverage"]["legacy_artifacts_inspected"] == 1
    text = md.read_text(encoding="utf-8")
    assert "Publication authority available: False" in text
    assert "Legacy artifacts inspected: 1" in text


def _write_published_html_review_article(root: Path, *, source_url: str, wp_link: str, title: str = "Material Story", original: str | None = None, final: str | None = None, metadata: bool = True) -> Path:
    article_dir = root / "published_html_review" / "run_test" / ("001_" + title.lower().replace(" ", "_"))
    article_dir.mkdir(parents=True, exist_ok=True)
    if metadata:
        (article_dir / "metadata.json").write_text(json.dumps({"source_url": source_url, "wp_link": wp_link, "title": title, "source_title": title}), encoding="utf-8")
    if original is not None:
        (article_dir / "original.html").write_text(original, encoding="utf-8")
    if final is not None:
        (article_dir / "final.html").write_text(final, encoding="utf-8")
    (article_dir.parent / "summary.json").write_text(json.dumps({"articles": 1}), encoding="utf-8")
    return article_dir


def test_translation_audit_real_published_html_review_original_and_final_provenance(tmp_path):
    _root, source_url, wp_link = authoritative_publication_root(tmp_path)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "bob.json").write_text(json.dumps({"source_url": source_url, "body_html": "<p>Translated candidate draft.</p>"}), encoding="utf-8")
    long_original = "<html><title>Material Story</title><p>Long English source paragraph with many details about the wrestling story and its background.</p><p>More original context.</p></html>"
    final = "<html><title>Material Story</title><p>Breve articolo finale italiano.</p></html>"
    _write_published_html_review_article(tmp_path, source_url=source_url, wp_link=wp_link, original=long_original, final=final)

    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert "Long English source paragraph" in row.original_text
    assert "Breve articolo finale italiano" in row.published_text
    assert "Long English source paragraph" not in row.published_text
    assert "Translated candidate draft" in row.translated_candidate_text
    assert row.source_material_available is True
    assert row.translated_candidate_material_available is True
    assert row.final_published_material_available is True
    assert row.comparative_pair_available is True


def test_translation_audit_published_html_review_order_independent_and_original_never_final(tmp_path):
    _root, source_url, wp_link = authoritative_publication_root(tmp_path)
    article_dir = tmp_path / "published_html_review" / "run_test" / "001_test_story"
    article_dir.mkdir(parents=True)
    # Write final before metadata/original to prove processing does not depend on creation order.
    final = "<html><title>Material Story</title><p>Finale corto.</p></html>"
    original = "<html><title>Material Story</title><p>Original English text is much longer than the final Italian page and must never replace published text.</p></html>"
    (article_dir / "final.html").write_text(final, encoding="utf-8")
    (article_dir / "original.html").write_text(original, encoding="utf-8")
    (article_dir / "metadata.json").write_text(json.dumps({"source_url": source_url, "wp_link": wp_link, "title": "Material Story"}), encoding="utf-8")

    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 1
    row = rows[0]
    assert "Original English text" in row.original_text
    assert "Finale corto" in row.published_text
    assert "Original English text" not in row.published_text
    assert row.comparative_pair_available is True


def test_translation_audit_published_html_review_original_only_is_source_not_final(tmp_path):
    _root, source_url, wp_link = authoritative_publication_root(tmp_path)
    _write_published_html_review_article(tmp_path, source_url=source_url, wp_link=wp_link, original="<p>Only original source HTML.</p>", final=None)
    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.source_material_available is True
    assert row.final_published_material_available is False
    assert row.comparative_pair_available is False


def test_translation_audit_published_html_review_final_only_is_final_not_source(tmp_path):
    _root, source_url, wp_link = authoritative_publication_root(tmp_path)
    _write_published_html_review_article(tmp_path, source_url=source_url, wp_link=wp_link, original=None, final="<p>Only final published HTML.</p>")
    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.source_material_available is False
    assert row.final_published_material_available is True
    assert row.comparative_pair_available is False


def test_translation_audit_published_html_review_metadata_only_is_not_material(tmp_path):
    _root, source_url, wp_link = authoritative_publication_root(tmp_path)
    _write_published_html_review_article(tmp_path, source_url=source_url, wp_link=wp_link, original=None, final=None)
    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.source_material_available is False
    assert row.translated_candidate_material_available is False
    assert row.final_published_material_available is False
    assert row.comparative_pair_available is False


def test_translation_audit_limit_is_detail_limit_not_coverage_limit(tmp_path):
    now = datetime.now(timezone.utc)
    rows = []
    for i in range(28):
        source_url = f"https://source.example/story-{i}"
        wp_link = f"https://owtv.example/story-{i}"
        rows.append(master_row(now, idx=1000 + i, publisher_results=[{"source_url": source_url, "wp_link": wp_link, "title": f"Story {i}", "status": "published"}]))
    write_master(tmp_path, rows)
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    for i in range(8):
        (art / f"source_{i}.json").write_text(json.dumps({"source_url": f"https://source.example/story-{i}", "original_text": "Original text " * 20}), encoding="utf-8")
        _write_published_html_review_article(tmp_path, source_url=f"https://source.example/story-{i}", wp_link=f"https://owtv.example/story-{i}", title=f"Story {i}", original=None, final=f"<p>Final text {i}.</p>")
    for i in range(8, 14):
        (art / f"source_{i}.json").write_text(json.dumps({"source_url": f"https://source.example/story-{i}", "original_text": "Original only " * 20}), encoding="utf-8")
    for i in range(14, 19):
        _write_published_html_review_article(tmp_path, source_url=f"https://source.example/story-{i}", wp_link=f"https://owtv.example/story-{i}", title=f"Story {i}", original=None, final=f"<p>Final only {i}.</p>")
    # Remaining nine are metadata-only authoritative publications.

    payload, _latest, md = __import__("scripts.translation_quality_audit", fromlist=["build_audit"]).build_audit(hours=24, limit=25, output_dir=tmp_path / "reports", root=tmp_path)
    coverage = payload["coverage"]
    assert coverage["publication_authority_available"] is True
    assert coverage["authoritative_total"] == 28
    assert coverage["audit_population_total"] == 28
    assert coverage["detailed_rows_returned"] == 25
    assert coverage["detail_limit"] == 25
    assert coverage["source_material_available"] == 14
    assert coverage["final_published_material_available"] == 13
    assert coverage["comparative_pairs_available"] == 8
    assert coverage["missing_source_material"] == 14
    assert coverage["missing_final_published_material"] == 15
    assert len(payload["articles"]) == 25
    text = md.read_text(encoding="utf-8")
    assert "Authoritative publications: 28" in text
    assert "Detailed articles shown: 25" in text


def test_translation_audit_flat_v81_triplet_uses_metadata_declared_files(tmp_path):
    _root, source_url, wp_link = authoritative_publication_root(tmp_path, title="Flat Story")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    (archive / "custom_original.html").write_text("<p>Flat original source English text.</p>", encoding="utf-8")
    (archive / "custom_final.html").write_text("<p>Flat final Italian text.</p>", encoding="utf-8")
    (archive / "flat_story_metadata.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_title": "Flat Story",
        "final_title": "Flat Story",
        "source_url": source_url,
        "wp_link": wp_link,
        "original_html_file": "custom_original.html",
        "final_html_file": "custom_final.html",
        "metadata_file": "flat_story_metadata.json",
    }), encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert "Flat original source" in row.original_text
    assert "Flat final Italian" in row.published_text
    assert row.source_material_available is True
    assert row.final_published_material_available is True
    assert row.comparative_pair_available is True


def test_translation_audit_flat_v81_original_does_not_fall_through_as_final(tmp_path):
    _root, source_url, wp_link = authoritative_publication_root(tmp_path, title="Flat Original Only")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    (archive / "flat_original_only_metadata.json").write_text(json.dumps({"source_title": "Flat Original Only", "source_url": source_url, "wp_link": wp_link}), encoding="utf-8")
    (archive / "flat_original_only_original.html").write_text("<p>Only flat source text.</p>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.source_material_available is True
    assert row.final_published_material_available is False
    assert "Only flat source text" not in row.published_text


def test_translation_audit_v93_news_and_publisher_pair_have_distinct_provenance(tmp_path):
    _root, _source_url, _wp_link = authoritative_publication_root(tmp_path, title="Pair Story")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    (archive / "v93-news-pair-story.html").write_text("<html><title>Pair Story</title><p>Candidate modular body.</p></html>", encoding="utf-8")
    (archive / "v93-publisher-pair-story.html").write_text("<html><title>Pair Story</title><p>Final modular publisher body.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert "Candidate modular body" in row.translated_candidate_text
    assert "Candidate modular body" not in row.published_text
    assert "Final modular publisher body" in row.published_text
    assert row.translated_candidate_material_available is True
    assert row.final_published_material_available is True


def test_translation_audit_v93_news_only_is_candidate_not_final(tmp_path):
    _root, _source_url, _wp_link = authoritative_publication_root(tmp_path, title="News Only")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    (archive / "v93-news_news-only.html").write_text("<html><title>News Only</title><p>Only modular news candidate.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.translated_candidate_material_available is True
    assert row.final_published_material_available is False
    assert "Only modular news candidate" not in row.published_text


def test_translation_audit_review_package_html_is_candidate_not_final(tmp_path):
    _root, _source_url, _wp_link = authoritative_publication_root(tmp_path, title="Review Package Story")
    review_dir = tmp_path / "review_packages"
    review_dir.mkdir()
    (review_dir / "translated.html").write_text("<html><title>Review Package Story</title><p>Review package draft HTML.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.translated_candidate_material_available is True
    assert row.final_published_material_available is False
    assert "Review package draft" not in row.published_text


def test_translation_audit_verified_publisher_final_rank_outranks_longer_lower_authority(tmp_path):
    _root, source_url, _wp_link = authoritative_publication_root(tmp_path, title="Rank Story")
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "lower_final.json").write_text(json.dumps({"source_url": source_url, "published_text": "lower authority final " * 300}), encoding="utf-8")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    (archive / "v93-publisher-rank-story.html").write_text("<html><title>Rank Story</title><p>Verified Publisher final.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert "Verified Publisher final" in row.published_text
    assert "lower authority final" not in row.published_text
    assert row.final_published_material_rank == 400
    assert "v93-publisher" in row.final_published_material_provenance


def test_translation_audit_v93_publisher_only_is_final_not_candidate(tmp_path):
    _root, _source_url, _wp_link = authoritative_publication_root(tmp_path, title="Publisher Only")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    (archive / "v93-publisher-publisher-only.html").write_text("<html><title>Publisher Only</title><p>Only publisher final.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.final_published_material_available is True
    assert row.translated_candidate_material_available is False
    assert "Only publisher final" in row.published_text


def test_translation_audit_review_package_original_html_is_source_only(tmp_path):
    _root, _source_url, _wp_link = authoritative_publication_root(tmp_path, title="Review Source")
    review_dir = tmp_path / "review_packages" / "pkg"
    review_dir.mkdir(parents=True)
    (review_dir / "original.html").write_text("<html><title>Review Source</title><p>Review package original source.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.source_material_available is True
    assert row.translated_candidate_material_available is False
    assert row.final_published_material_available is False
    assert "Review package original source" in row.original_text


def test_translation_audit_review_package_translated_html_is_candidate_only(tmp_path):
    _root, _source_url, _wp_link = authoritative_publication_root(tmp_path, title="Review Candidate")
    review_dir = tmp_path / "review_packages" / "pkg"
    review_dir.mkdir(parents=True)
    (review_dir / "translated.html").write_text("<html><title>Review Candidate</title><p>Review package translated draft.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.source_material_available is False
    assert row.translated_candidate_material_available is True
    assert row.final_published_material_available is False
    assert "Review package translated draft" in row.translated_candidate_text


def test_translation_audit_review_package_unknown_html_is_diagnostic_only(tmp_path):
    _root, _source_url, _wp_link = authoritative_publication_root(tmp_path, title="Review Unknown")
    review_dir = tmp_path / "review_packages" / "pkg"
    review_dir.mkdir(parents=True)
    (review_dir / "unknown.html").write_text("<html><title>Review Unknown</title><p>Unclassified review package.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.source_material_available is False
    assert row.translated_candidate_material_available is False
    assert row.final_published_material_available is False
    assert row.unclassified_html_artifacts


def test_translation_audit_unknown_published_html_review_is_diagnostic_only(tmp_path):
    _root, _source_url, _wp_link = authoritative_publication_root(tmp_path, title="Unknown Story")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    (archive / "unknown-story.html").write_text("<html><title>Unknown Story</title><p>Unknown archive HTML.</p></html>", encoding="utf-8")

    row = discover(tmp_path, hours=24, limit=None)[0]
    assert row.final_published_material_available is False
    assert row.comparative_pair_available is False
    assert any("unknown-story.html" in p for p in row.unclassified_html_artifacts)


def test_translation_audit_fallback_archive_triplets_are_window_bounded(tmp_path):
    ns = tmp_path / "state/newsroom"
    ns.mkdir(parents=True)
    (ns / "master_log.jsonl").write_text("{bad\n", encoding="utf-8")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    old = datetime.now(timezone.utc) - timedelta(days=3)
    current = datetime.now(timezone.utc)
    for base, dt, text in (("old_story", old, "Old final"), ("current_story", current, "Current final")):
        (archive / f"{base}_metadata.json").write_text(json.dumps({"created_at": dt.isoformat(), "source_url": f"https://src/{base}", "title": base.replace("_", " ")}), encoding="utf-8")
        (archive / f"{base}_original.html").write_text(f"<p>{text} source</p>", encoding="utf-8")
        (archive / f"{base}_final.html").write_text(f"<p>{text}</p>", encoding="utf-8")
    payload, _latest, _md = __import__("scripts.translation_quality_audit", fromlist=["build_audit"]).build_audit(hours=24, output_dir=tmp_path / "reports", root=tmp_path)
    assert payload["coverage"]["publication_authority_available"] is False
    assert payload["coverage"]["legacy_artifacts_inspected"] == 1
    assert len(payload["articles"]) == 1
    assert "Current final" in payload["articles"][0]["published_text"]


def test_translation_audit_fallback_v93_records_are_window_bounded(tmp_path):
    ns = tmp_path / "state/newsroom"
    ns.mkdir(parents=True)
    (ns / "master_log.jsonl").write_text("{bad\n", encoding="utf-8")
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    old_file = archive / "v93-publisher-old-v93.html"
    current_file = archive / "v93-publisher-current-v93.html"
    old_file.write_text("<html><title>Old V93</title><p>Old v93 final.</p></html>", encoding="utf-8")
    current_file.write_text("<html><title>Current V93</title><p>Current v93 final.</p></html>", encoding="utf-8")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=3)).timestamp()
    import os
    os.utime(old_file, (old_ts, old_ts))
    payload, _latest, _md = __import__("scripts.translation_quality_audit", fromlist=["build_audit"]).build_audit(hours=24, output_dir=tmp_path / "reports", root=tmp_path)
    assert payload["coverage"]["publication_authority_available"] is False
    assert payload["coverage"]["legacy_artifacts_inspected"] == 1
    assert "Current v93 final" in payload["articles"][0]["published_text"]


def test_translation_audit_mixed_archive_formats_remain_distinct_canonical_rows(tmp_path):
    now = datetime.now(timezone.utc)
    published = [
        {"source_url": "https://src/nested", "wp_link": "https://owtv/nested", "title": "Nested One", "status": "published"},
        {"source_url": "https://src/flat", "wp_link": "https://owtv/flat", "title": "Flat One", "status": "published"},
        {"source_url": "https://src/v93", "wp_link": "https://owtv/v93", "title": "V93 One", "status": "published"},
    ]
    write_master(tmp_path, [master_row(now, idx=3000, publisher_results=published)])
    _write_published_html_review_article(tmp_path, source_url="https://src/nested", wp_link="https://owtv/nested", title="Nested One", original="<p>Nested source</p>", final="<p>Nested final</p>")
    archive = tmp_path / "published_html_review"
    (archive / "flat_one_metadata.json").write_text(json.dumps({"created_at": now.isoformat(), "source_url": "https://src/flat", "wp_link": "https://owtv/flat", "title": "Flat One"}), encoding="utf-8")
    (archive / "flat_one_original.html").write_text("<p>Flat source</p>", encoding="utf-8")
    (archive / "flat_one_final.html").write_text("<p>Flat final</p>", encoding="utf-8")
    (archive / "v93-publisher-v93-one.html").write_text("<html><title>V93 One</title><p>V93 final</p></html>", encoding="utf-8")

    rows = discover(tmp_path, hours=24, limit=None)
    assert len(rows) == 3
    finals = {row.title: row.published_text for row in rows}
    assert any("Nested final" in text for text in finals.values())
    assert any("Flat final" in text for text in finals.values())
    assert any("V93 final" in text for text in finals.values())


def test_translation_audit_human_review_summary_counts_full_population_not_detail_limit(tmp_path):
    now = datetime.now(timezone.utc)
    published = []
    for i in range(28):
        title = "Limited Out Review" if i == 27 else f"Clean Detail {i:02d}"
        published.append({"source_url": f"https://src/detail-{i}", "wp_link": f"https://owtv/detail-{i}", "title": title, "status": "published"})
    write_master(tmp_path, [master_row(now, idx=4000, publisher_results=published)])
    archive = tmp_path / "published_html_review"
    archive.mkdir()
    for i in range(25):
        (archive / f"v93-publisher-clean-detail-{i:02d}.html").write_text(
            f"<html><title>Clean Detail {i:02d}</title><p>Clean final material {i} with enough text to sort before empty rows.</p></html>",
            encoding="utf-8",
        )
    art = tmp_path / "artifacts/newsroom"
    art.mkdir(parents=True)
    (art / "limited_review.json").write_text(json.dumps({
        "source_url": "https://src/detail-27",
        "title": "Limited Out Review",
        "alfred_warnings": ["blocker: needs human review"],
    }), encoding="utf-8")

    payload, _latest, md = __import__("scripts.translation_quality_audit", fromlist=["build_audit"]).build_audit(hours=24, limit=25, output_dir=tmp_path / "reports", root=tmp_path)
    text = md.read_text(encoding="utf-8")
    assert payload["coverage"]["authoritative_total"] == 28
    assert payload["coverage"]["audit_population_total"] == 28
    assert payload["coverage"]["detailed_rows_returned"] == 25
    assert payload["coverage"]["detail_limit"] == 25
    assert "Articles/reports inspected: 28" in text
    assert "Articles needing human review: 1" in text
    assert "Human-review articles shown: 0 of 1" in text
    assert "Limited Out Review" not in text
    assert len(payload["articles"]) == 25
