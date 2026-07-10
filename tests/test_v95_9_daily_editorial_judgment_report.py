from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.daily_editorial_judgment import (
    build_report,
    day_type,
    email_summary,
    generate_daily_editorial_judgment_outputs,
    generate_daily_editorial_judgment_report,
    load_inputs,
    render_markdown,
    top_discarded,
)


def write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_report_generated_with_available_audit_artifacts(tmp_path: Path) -> None:
    menzo = write_json(tmp_path / "menzo.json", {"selected": [{"title": "WWE contract update", "url": "https://x/a", "score": 82, "article_type": "hard_news"}], "pending": [], "skipped": []})
    story = write_json(tmp_path / "story.json", {"same_story_clusters": [{"id": "c1"}], "story_review": [{"title": "Review duplicate"}]})
    out = generate_daily_editorial_judgment_report({"menzo_latest": menzo, "story_cluster_audit": story}, tmp_path / "reports", datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
    text = out.read_text(encoding="utf-8")
    assert out.name == "owtv_daily_editorial_judgment_24h_20260710_120000.md"
    assert "## Daily Editorial Judgment" in text
    assert "Story_review inclusi" in text


def test_structured_json_companion_and_latest_state_are_written(tmp_path: Path) -> None:
    menzo = write_json(tmp_path / "menzo.json", {"selected": [], "pending": [{"title": "WWE title change", "url": "https://x/title", "score": 88, "article_type": "hard_news"}], "skipped": []})
    outputs = generate_daily_editorial_judgment_outputs(
        {"menzo_latest": menzo, "master_log": tmp_path / "missing-master.json"},
        output_dir=tmp_path / "reports",
        state_dir=tmp_path / "state" / "reports",
        now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
    )
    payload = json.loads(outputs["json"].read_text(encoding="utf-8"))
    latest = json.loads(outputs["latest_json"].read_text(encoding="utf-8"))
    assert outputs["markdown"].name == "owtv_daily_editorial_judgment_24h_20260710_120000.md"
    assert outputs["json"].name == "owtv_daily_editorial_judgment_24h_20260710_120000.json"
    assert latest == payload
    assert set(payload) >= {
        "judgment",
        "day_type",
        "summary",
        "daily_numbers",
        "hard_soft_balance",
        "top_discarded_candidates",
        "borderline_published",
        "redundancy_risks",
        "recommended_actions",
        "generated_at",
        "source_artifacts_used",
        "missing_artifacts",
    }
    assert payload["top_discarded_candidates"][0]["url"] == "https://x/title"
    assert payload["daily_numbers"]["news_published"] is None
    assert any("missing-master.json" in item or item == "master_log" for item in payload["missing_artifacts"])
    assert "schema_warnings" in payload


def test_missing_artifacts_are_non_fatal(tmp_path: Path) -> None:
    data = load_inputs({"menzo_latest": tmp_path / "missing.json", "story_cluster_audit": tmp_path / "nope.json"})
    text = render_markdown(build_report(data))
    assert "news published: n.d." in text
    assert "Nessun forte candidato" in text


def test_top_3_discarded_candidates_are_selected_from_skipped_pending_high_score_items() -> None:
    menzo = {"skipped": [{"title": "Low", "url": "l", "score": 10}], "pending": [
        {"title": "AEW injury", "url": "a", "score": 70, "article_type": "hard_news"},
        {"title": "WWE roster move", "url": "b", "score": 68, "priority": "high"},
        {"title": "Contract business", "url": "c", "score": 66, "article_type": "contract"},
        {"title": "Soft interview", "url": "d", "score": 90, "article_type": "soft_news"},
    ]}
    urls = [x["url"] for x in top_discarded(menzo)]
    assert urls == ["a", "b", "c"]


def test_no_discarded_candidates_case() -> None:
    report = build_report({"menzo_latest": {"selected": [], "pending": [], "skipped": []}})
    assert report["top_discarded"] == []
    assert "Nessun forte candidato" in render_markdown(report)


def test_day_type_classification_intensa_normale_scarica_post_show() -> None:
    assert day_type(20, 0, 3) == "intensa"
    assert day_type(8, 0, 3) == "normale"
    assert day_type(2, 0, 1) == "scarica"
    assert day_type(2, 1, 1) == "post-show"


def test_softpool_used_not_used_explanation() -> None:
    used = build_report({"menzo_latest": {"selected": [{"title": "Soft", "from_softpool": True, "article_type": "soft_news"}], "pending": [], "skipped": []}})
    not_used = build_report({"menzo_latest": {"selected": [], "pending": [], "skipped": []}})
    assert "softpool usato" in used["summary"]
    assert "Softpool non usato" in render_markdown(not_used)


def test_story_review_inclusion() -> None:
    report = build_report({"story_cluster_audit": {"story_reviews": [{"title": "Same story"}]}})
    assert "Same story" in render_markdown(report)


def test_email_summary_generation_if_implemented() -> None:
    report = build_report({"menzo_latest": {"selected": [], "pending": [{"title": "WWE title", "url": "https://x/top", "score": 88, "article_type": "hard_news"}], "skipped": []}})
    summary = email_summary(report)
    assert "Judgment:" in summary
    assert "Top discarded URL: https://x/top" in summary


def test_default_input_discovery_with_real_style_artifact_names(tmp_path: Path, monkeypatch) -> None:
    import scripts.daily_editorial_judgment as dej

    (tmp_path / "state/newsroom").mkdir(parents=True)
    (tmp_path / "artifacts/newsroom").mkdir(parents=True)
    (tmp_path / "reports").mkdir(parents=True)
    write_json(tmp_path / "state/newsroom/menzo_decisions_latest.json", {"selected": [], "pending": [], "skipped": []})
    (tmp_path / "artifacts/newsroom/master_log_tail.jsonl").write_text(json.dumps({"publisher": {"published": []}, "simone": {"published_reports": []}}) + "\n", encoding="utf-8")
    write_json(tmp_path / "reports/story_cluster_audit_v94_7_1_2026-07-10_12-00.json", {"counts": {"duplicate_candidates": 2, "same_story_clusters": 1, "same_event_clusters": 1, "story_reviews": 3, "pairs_above_threshold": 4}, "pairs": []})
    (tmp_path / "state/newsroom/gemini_call_ledger.jsonl").write_text(json.dumps({"model": "gemini-3.5-pro", "status": "called"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(dej, "ROOT", tmp_path)
    data = dej.load_inputs()
    assert any("master_log_tail.jsonl" in p for p in data["__artifact_status__"]["used"])
    assert data["story_cluster_audit"]["counts"]["duplicate_candidates"] == 2
    assert data["gemini_ledger"]["records"][0]["model"] == "gemini-3.5-pro"


def test_missing_defaults_do_not_produce_misleading_zero_published_day(tmp_path: Path, monkeypatch) -> None:
    import scripts.daily_editorial_judgment as dej

    monkeypatch.setattr(dej, "ROOT", tmp_path)
    report = dej.build_report(dej.load_inputs())
    payload = dej.structured_json(report)
    assert payload["daily_numbers"]["news_published"] is None
    assert "published_counts_not_available" in payload["schema_warnings"]
    assert payload["missing_artifacts"]


def test_story_cluster_real_schema_counts_and_pairs_are_parsed_correctly() -> None:
    report = build_report({"story_cluster_audit": {"counts": {"duplicate_candidates": 2, "same_story_clusters": 3, "same_event_clusters": 1, "story_reviews": 4, "pairs_above_threshold": 7}, "pairs": [
        {"cluster_type": "same_story_cluster", "score": 0.91, "title_a": "A", "title_b": "B", "reason": "same"},
        {"cluster_type": "story_review", "score": 0.55, "title_a": "C", "title_b": "D", "reason": "review"},
    ]}})
    payload = json.loads(json.dumps(__import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)))
    assert payload["daily_numbers"]["duplicate_candidates"] == 2
    assert payload["redundancy_risks"]["same_story_cluster_count"] == 3
    assert payload["redundancy_risks"]["same_event_cluster_count"] == 1
    assert payload["redundancy_risks"]["story_review_count"] == 4
    assert payload["redundancy_risks"]["pairs_above_threshold"] == 7
    assert payload["redundancy_risks"]["top_suspicious_pairs"][0]["title_a"] == "A"


def test_story_cluster_markdown_fallback_counts() -> None:
    md = """# audit\n- Coppie sopra soglia diagnostica: 9\n- Duplicate candidate: 2\n- Same story cluster: 3\n- Same event cluster: 4\n- Story review: 5\n"""
    report = build_report({"story_cluster_audit": {"_format": "markdown", "_markdown": md}})
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["duplicate_candidates"] == 2
    assert payload["redundancy_risks"]["story_review_count"] == 5
    assert payload["redundancy_risks"]["pairs_above_threshold"] == 9


def test_simone_report_counts_filter_only_published_status() -> None:
    master = {"publisher": {"published": []}, "simone": {"published_reports": [
        {"title": "Published", "status": "published"},
        {"title": "Ready only", "status": "wp_not_ready"},
        {"title": "Dry", "status": "dry_run"},
        {"title": "Error", "status": "publish_error"},
        {"title": "Already", "status": "already_published"},
    ]}}
    report = build_report({"master_log": master})
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["reports_published"] == 1
    assert payload["daily_numbers"]["report_status_counts"]["already_published"] == 1
    assert report["day_type"] == "post-show"


def test_non_published_simone_reports_do_not_create_post_show_day() -> None:
    master = {"publisher": {"published": []}, "simone": {"published_reports": [
        {"title": "Ready only", "status": "wp_not_ready"},
        {"title": "Dry", "status": "dry_run"},
        {"title": "Error", "status": "publish_error"},
        {"title": "Already", "status": "already_published"},
    ]}}
    report = build_report({"master_log": master})
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["reports_published"] == 0
    assert report["day_type"] != "post-show"
