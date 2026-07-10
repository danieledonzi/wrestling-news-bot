from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
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


def test_vps_reports_directory_is_preferred_over_repo_reports(tmp_path: Path, monkeypatch) -> None:
    import scripts.daily_editorial_judgment as dej

    repo = tmp_path / "repo"
    external = tmp_path / "owtv_reports"
    (repo / "reports").mkdir(parents=True)
    external.mkdir(parents=True)
    write_json(repo / "reports/story_cluster_audit_v94_7_1_2099.json", {"counts": {"story_reviews": 1}})
    write_json(external / "story_cluster_audit_v94_7_1_20260710.json", {"counts": {"story_reviews": 7}})
    monkeypatch.setattr(dej, "ROOT", repo)
    monkeypatch.setattr(dej, "VPS_REPORTS_DIR", external)
    data = dej.load_inputs()
    assert data["story_cluster_audit"]["counts"]["story_reviews"] == 7


def test_repo_judgment_outputs_do_not_mask_external_inputs(tmp_path: Path, monkeypatch) -> None:
    import scripts.daily_editorial_judgment as dej

    repo = tmp_path / "repo"
    external = tmp_path / "owtv_reports"
    (repo / "reports").mkdir(parents=True)
    external.mkdir(parents=True)
    (repo / "reports/owtv_daily_editorial_judgment_24h_20260710.md").write_text("old output", encoding="utf-8")
    (external / "owtv_editorial_audit_v1_1_24h_20260710.md").write_text("news published: 15\nreports published: 1\n", encoding="utf-8")
    write_json(external / "story_cluster_audit_v94_7_1_20260710.json", {"counts": {"story_review": 2}})
    monkeypatch.setattr(dej, "ROOT", repo)
    monkeypatch.setattr(dej, "VPS_REPORTS_DIR", external)
    report = dej.build_report(dej.load_inputs())
    payload = dej.structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 15
    assert "editorial_audit" not in payload["missing_artifacts"]
    assert "story_cluster_audit" not in payload["missing_artifacts"]


def test_latest_timestamped_reports_are_selected(tmp_path: Path, monkeypatch) -> None:
    import scripts.daily_editorial_judgment as dej

    external = tmp_path / "owtv_reports"
    external.mkdir()
    (external / "owtv_operational_report_24h_20260709.md").write_text("news published: 1", encoding="utf-8")
    (external / "owtv_operational_report_24h_20260710.md").write_text("news published: 15", encoding="utf-8")
    (external / "owtv_editorial_audit_v1_1_24h_20260709.md").write_text("reports published: 0", encoding="utf-8")
    (external / "owtv_editorial_audit_v1_1_24h_20260710.md").write_text("reports published: 1", encoding="utf-8")
    write_json(external / "story_cluster_audit_v94_7_1_20260709.json", {"counts": {"story_review": 1}})
    write_json(external / "story_cluster_audit_v94_7_1_20260710.json", {"counts": {"story_review": 4}})
    monkeypatch.setattr(dej, "ROOT", tmp_path / "repo")
    monkeypatch.setattr(dej, "VPS_REPORTS_DIR", external)
    report = dej.build_report(dej.load_inputs())
    payload = dej.structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 15
    assert payload["daily_numbers"]["reports_published"] == 1
    assert payload["redundancy_risks"]["story_review_count"] == 4


def test_real_style_markdown_parses_counts_warnings_and_article_types() -> None:
    md = """EXIT 0
news published: 15
report show published: 1
Menzo first decision selected/pending/skipped: 15/2/3
article types: {'hard_news': 9, 'news_generica': 6}
Alfred warnings/blockers: 2/0
"""
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": md}})
    payload = json.loads(json.dumps(__import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)))
    assert payload["daily_numbers"]["news_published"] == 15
    assert payload["daily_numbers"]["reports_published"] == 1
    assert payload["daily_numbers"]["alfred"]["warnings"] == 2
    assert payload["daily_numbers"]["article_types"]["hard_news"] == 9
    assert payload["daily_numbers"]["hard_news_count"] == 9
    assert payload["daily_numbers"]["soft_news_count"] == 6
    assert payload["hard_soft_balance"]["source"] == "article_types_markdown"


def test_markdown_fallback_without_article_types_keeps_hard_soft_nd() -> None:
    md = "news published: 15\nreports published: 1\n"
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": md}})
    text = render_markdown(report)
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 15
    assert payload["daily_numbers"]["hard_news_count"] is None
    assert payload["daily_numbers"]["soft_news_count"] is None
    assert "- hard news count: n.d." in text
    assert "- soft news count: n.d." in text


def test_parsed_runs_completed_is_used_in_markdown_and_json() -> None:
    md = "runs completed: 47\nnews published: 15\narticle types: {'hard_news': 9, 'news_generica': 6}\n"
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": md}})
    text = render_markdown(report)
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert "- runs completed: 47" in text
    assert payload["daily_numbers"]["runs_completed"] == 47


def test_no_false_run_count_when_unavailable() -> None:
    md = "news published: 15\nreports published: 1\narticle types: {'hard_news': 9, 'news_generica': 6}\n"
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": md}})
    text = render_markdown(report)
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert "- runs completed: n.d." in text
    assert payload["daily_numbers"]["runs_completed"] is None


def test_published_placeholder_records_do_not_force_hard_soft_zero() -> None:
    md = "news published: 15\n"
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": md}})
    assert report["news"][0]["_placeholder_from_markdown"] is True
    assert report["hard_count"] is None
    assert report["soft_count"] is None


def test_story_cluster_json_from_external_reports_schema_is_parsed(tmp_path: Path, monkeypatch) -> None:
    import scripts.daily_editorial_judgment as dej

    external = tmp_path / "owtv_reports"
    external.mkdir()
    write_json(external / "story_cluster_audit_v94_7_1_20260710.json", {"counts": {"story_review": 5, "same_story_cluster": 3, "duplicate_candidate": 2, "pairs_above_threshold": 8}})
    monkeypatch.setattr(dej, "ROOT", tmp_path / "repo")
    monkeypatch.setattr(dej, "VPS_REPORTS_DIR", external)
    payload = dej.structured_json(dej.build_report(dej.load_inputs()))
    assert payload["daily_numbers"]["duplicate_candidates"] == 2
    assert payload["redundancy_risks"]["same_story_cluster_count"] == 3
    assert payload["redundancy_risks"]["story_review_count"] == 5
    assert payload["redundancy_risks"]["pairs_above_threshold"] == 8


def test_gemini_35_count_is_limited_to_24h_window() -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    data = load_inputs({
        "gemini_ledger": write_json(Path("/tmp") / "unused.json", {}),
    }, now=now)
    data["gemini_ledger"] = {"records": [
        {"timestamp": (now - timedelta(hours=2)).isoformat(), "model": "gemini-3.5-pro", "status": "called"},
        {"timestamp": (now - timedelta(hours=26)).isoformat(), "model": "gemini-3.5-pro", "status": "called"},
        {"timestamp": (now - timedelta(hours=1)).isoformat(), "model": "gemini-3.5-pro", "status": "avoided"},
    ]}
    assert build_report(data)["gemini_called"] == 1


def test_real_vps_italian_markdown_labels_are_parsed_with_operational_preference() -> None:
    operational = """# Report operativo
- Run completate: 48
- Run con EXIT 0: 48
- Articoli/news pubblicati da Publisher: 24
- Report pubblicati da Simone: 1
- Alfred blockers: 1
- Alfred warnings: 20
- Gemini 3.5 called total: 0
"""
    editorial = """# Audit editoriale
## 3. Tipologia contenuti pubblicati/rilevati
- news_generica: 12
- risultato_match/evento: 4
- contratti/roster: 2
- dichiarazione/reazione: 2
- report_show: 1
- Alfred warnings: 20
- Blocker Alfred: 1
"""
    report = build_report({
        "operational_report": {"_format": "markdown", "_markdown": operational},
        "editorial_audit": {"_format": "markdown", "_markdown": editorial},
        "__artifact_status__": {"used": ["operational_report", "editorial_audit"], "missing": []},
    })
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["runs_completed"] == 48
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["daily_numbers"]["reports_published"] == 1
    assert payload["daily_numbers"]["article_types"] == {
        "news_generica": 12,
        "risultato_match/evento": 4,
        "contratti/roster": 2,
        "dichiarazione/reazione": 2,
        "report_show": 1,
    }
    assert payload["daily_numbers"]["alfred"] == {"warnings": 20, "blockers": 1}
    assert payload["daily_numbers"]["gemini_3_5_called_total"] == 0
    assert payload["hard_soft_balance"]["source"] == "article_types_markdown"
    assert payload["missing_artifacts"] == []


def test_missing_italian_publication_label_does_not_create_false_zero() -> None:
    operational = """- Run completate: 48
- Articoli/news pubblicati da Publisher: 24
"""
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": operational}})
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["daily_numbers"]["reports_published"] is None
    assert "reports_published_count_not_available" in payload["schema_warnings"]


def test_markdown_only_report_count_keeps_news_unknown() -> None:
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": "- Report pubblicati da Simone: 1\n"}})
    text = render_markdown(report)
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] is None
    assert payload["daily_numbers"]["reports_published"] == 1
    assert "- news published: n.d." in text
    assert "- reports published: 1" in text
    assert "news_published_count_not_available" in payload["schema_warnings"]


def test_markdown_only_news_count_keeps_reports_unknown() -> None:
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": "- Articoli/news pubblicati da Publisher: 24\n"}})
    text = render_markdown(report)
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["daily_numbers"]["reports_published"] is None
    assert "- news published: 24" in text
    assert "- reports published: n.d." in text
    assert "reports_published_count_not_available" in payload["schema_warnings"]


def test_markdown_both_italian_publication_counts_are_available() -> None:
    md = "- Articoli/news pubblicati da Publisher: 24\n- Report pubblicati da Simone: 1\n"
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": md}})
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["daily_numbers"]["reports_published"] == 1
    assert "news_published_count_not_available" not in payload["schema_warnings"]
    assert "reports_published_count_not_available" not in payload["schema_warnings"]


def test_markdown_without_publication_labels_keeps_both_counts_unknown() -> None:
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": "- Alfred warnings: 20\n"}})
    text = render_markdown(report)
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] is None
    assert payload["daily_numbers"]["reports_published"] is None
    assert "- news published: n.d." in text
    assert "- reports published: n.d." in text
    assert "news_published_count_not_available" in payload["schema_warnings"]
    assert "reports_published_count_not_available" in payload["schema_warnings"]


def test_placeholder_report_records_do_not_create_false_news_zero() -> None:
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": "- Report pubblicati da Simone: 1\n"}})
    assert report["reports"][0]["_placeholder_from_markdown"] is True
    assert report["news"] == []
    assert report["news_published_count"] is None
    assert report["reports_published_count"] == 1


def test_empty_master_log_does_not_override_italian_markdown_publication_counts() -> None:
    md = "- Articoli/news pubblicati da Publisher: 24\n- Report pubblicati da Simone: 1\n"
    report = build_report({
        "operational_report": {"_format": "markdown", "_markdown": md},
        "master_log": {"publisher": {}, "simone": {}},
    })
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert report["news_records"] == []
    assert report["report_records"] == []
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["daily_numbers"]["reports_published"] == 1
    assert payload["daily_numbers"]["news_published_count"] == 24
    assert payload["daily_numbers"]["reports_published_count"] == 1
    assert payload["redundancy_risks"]["show_report_integration"] == "post-show presente"
    assert "24 news e 1 report show" in payload["summary"]


def test_report_placeholder_count_drives_markdown_show_integration() -> None:
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": "- Report pubblicati da Simone: 1\n"}})
    text = render_markdown(report)
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert report["report_records"] == []
    assert payload["redundancy_risks"]["show_report_integration"] == "post-show presente"
    assert "pubblicazione post-show presente" in text


def test_markdown_news_count_placeholders_do_not_create_borderline_published() -> None:
    report = build_report({"operational_report": {"_format": "markdown", "_markdown": "- Articoli/news pubblicati da Publisher: 24\n"}})
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    text = render_markdown(report)
    assert report["news_published_count"] == 24
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["borderline_published"] == []
    assert "Senza titolo" not in text
    assert "Senza titolo" not in str(payload["borderline_published"])
    assert "24 news" in payload["summary"]
    assert "Nessun articolo pubblicato borderline valutabile perché sono disponibili solo conteggi aggregati." in text


def test_placeholder_records_are_excluded_but_concrete_low_score_news_is_borderline() -> None:
    report = build_report({
        "operational_report": {"_format": "markdown", "_markdown": "- Articoli/news pubblicati da Publisher: 24\n"},
        "master_log": {"publisher": {"published": [
            {"title": "Concrete soft item", "url": "https://example.test/news", "source": "Example", "score": 42, "article_type": "news_generica"}
        ]}},
    })
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert report["news_published_count"] == 1
    assert payload["borderline_published"] == [{
        "title": "Concrete soft item",
        "source": "Example",
        "url": "https://example.test/news",
        "score": 42,
        "article_type": "news_generica",
        "priority": "",
        "menzo_decision": "",
        "menzo_reason": "",
        "automatic_judgment": "",
    }]


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_master_log_jsonl_window_produces_deduped_concrete_news_records(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    master = write_jsonl(tmp_path / "state/newsroom/master_log.jsonl", [
        {"recorded_at": (now - timedelta(hours=26)).isoformat(), "publisher": {"published": [{"title": "Old", "source_url": "https://example.test/old"}]}},
        {"recorded_at": (now - timedelta(hours=2)).isoformat(), "publisher": {"published": [
            {"title": "Jim Ross update", "source_url": "https://example.test/jr", "wp_link": "https://owrestling.test/jr"},
            {"title": "Jim Ross duplicate", "source_url": "https://example.test/jr", "wp_link": "https://owrestling.test/jr-2"},
        ], "results": [{"title": "Published result", "status": "published", "source_url": "https://example.test/result"}] }},
    ])
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(
        build_report(load_inputs({"master_log": master}, hours=24, now=now))
    )
    assert payload["daily_numbers"]["news_published"] == 2
    assert payload["daily_numbers"]["published_records_source"] == "master_log"
    assert [item["title"] for item in payload["daily_numbers"]["news_records"]] == ["Jim Ross update", "Published result"]
    assert payload["daily_numbers"]["news_records"][0]["wp_link"] == "https://owrestling.test/jr"


def test_master_log_jsonl_window_excludes_records_after_explicit_now(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    master = write_jsonl(tmp_path / "state/newsroom/master_log.jsonl", [
        {"recorded_at": (now - timedelta(hours=25)).isoformat(), "publisher": {"published": [{"title": "Before since", "source_url": "https://example.test/before"}]}},
        {"recorded_at": (now - timedelta(hours=1)).isoformat(), "publisher": {"published": [{"title": "Inside window", "source_url": "https://example.test/inside"}]}},
        {"recorded_at": (now + timedelta(minutes=1)).isoformat(), "publisher": {"published": [{"title": "Future skew", "source_url": "https://example.test/future"}]}},
    ])
    report = build_report(load_inputs({
        "operational_report": write_json(tmp_path / "reports/op.json", {"_markdown": "- Articoli/news pubblicati da Publisher: 24\n"}),
        "master_log": master,
    }, hours=24, now=now))
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["daily_numbers"]["concrete_news_record_count"] == 1
    assert [item["title"] for item in payload["daily_numbers"]["news_records"]] == ["Inside window"]
    assert "Future skew" not in str(payload["daily_numbers"]["news_records"])


def test_tail_partial_records_do_not_override_official_markdown_count(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    tail = write_jsonl(tmp_path / "artifacts/newsroom/master_log_tail.jsonl", [
        {"recorded_at": (now - timedelta(hours=1)).isoformat(), "publisher": {"published": [
            {"title": "One", "source_url": "https://example.test/1"},
            {"title": "Two", "source_url": "https://example.test/2"},
        ]}},
    ])
    report = build_report(load_inputs({
        "operational_report": write_json(tmp_path / "reports/op.json", {"_markdown": "- Articoli/news pubblicati da Publisher: 24\n"}),
        "master_log": tail,
    }, hours=24, now=now))
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["daily_numbers"]["concrete_news_record_count"] == 2
    assert payload["daily_numbers"]["published_records_source"] == "master_log_tail_partial"
    assert "published_record_count_differs_from_official_count" in payload["schema_warnings"]


def test_master_log_concrete_count_matching_official_count_has_no_diff_warning(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    master = write_jsonl(tmp_path / "state/newsroom/master_log.jsonl", [
        {"recorded_at": now.isoformat(), "publisher": {"published": [
            {"title": f"News {idx}", "source_url": f"https://example.test/{idx}"} for idx in range(24)
        ]}},
    ])
    report = build_report(load_inputs({
        "operational_report": write_json(tmp_path / "reports/op.json", {"_markdown": "- Articoli/news pubblicati da Publisher: 24\n"}),
        "master_log": master,
    }, now=now))
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["news_published"] == 24
    assert payload["daily_numbers"]["concrete_news_record_count"] == 24
    assert "published_record_count_differs_from_official_count" not in payload["schema_warnings"]


def test_editorial_audit_article_types_win_over_concrete_records_for_hard_soft() -> None:
    operational = "- Articoli/news pubblicati da Publisher: 1\n"
    editorial = """## 3. Tipologia contenuti pubblicati/rilevati
- news_generica: 1
"""
    report = build_report({
        "operational_report": {"_format": "markdown", "_markdown": operational},
        "editorial_audit": {"_format": "markdown", "_markdown": editorial},
        "master_log": {"publisher": {"published": [{"title": "Hard injury", "source_url": "https://example.test/injury", "article_type": "injury"}]}},
    })
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert payload["daily_numbers"]["article_types"] == {"news_generica": 1}
    assert payload["hard_soft_balance"]["source"] == "article_types_markdown"
    assert payload["daily_numbers"]["hard_news_count"] == 0
    assert payload["daily_numbers"]["soft_news_count"] == 1


def test_report_records_are_extracted_from_master_log_simone_published_reports(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    master = write_jsonl(tmp_path / "state/newsroom/master_log.jsonl", [
        {"run": {"ended_at": now.isoformat()}, "simone": {"published_reports": [
            {"title": "Show report", "status": "published", "wp_link": "https://owrestling.test/show"},
            {"title": "Already show", "status": "already_published", "wp_link": "https://owrestling.test/already"},
            {"title": "Draft show", "status": "wp_not_ready", "wp_link": "https://owrestling.test/draft"},
        ]}},
    ])
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(
        build_report(load_inputs({"master_log": master}, now=now))
    )
    assert payload["daily_numbers"]["reports_published"] == 2
    assert [item["title"] for item in payload["daily_numbers"]["report_records"]] == ["Show report", "Already show"]


def test_markdown_alfred_counts_override_master_log_and_are_integers() -> None:
    operational = """- Alfred blockers: 1
- Alfred warnings: 20
"""
    master = {"alfred": {"handoff": {"warnings": 2, "blockers": "0"}}}
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(
        build_report({"operational_report": {"_format": "markdown", "_markdown": operational}, "master_log": master})
    )
    assert payload["daily_numbers"]["alfred"] == {"warnings": 20, "blockers": 1}
    assert isinstance(payload["daily_numbers"]["alfred"]["warnings"], int)
    assert isinstance(payload["daily_numbers"]["alfred"]["blockers"], int)


def test_published_records_are_enriched_from_menzo_selected_by_source_url(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    master = write_jsonl(tmp_path / "state/newsroom/master_log.jsonl", [
        {"recorded_at": now.isoformat(), "menzo": {"selected": [
            {"title": "Menzo Finn", "source_url": "https://example.test/finn", "score": 100, "priority": "hard", "article_type": "hard_news", "decision": "selected", "reason": "major injury angle", "source": "Fightful", "category_hint": "wwe", "ai_priority_label": "high"},
            {"title": "Menzo Kenny", "source_url": "https://example.test/kenny", "deterministic_score": 72, "priority": "soft", "article_type": "hard_news", "decision": "selected", "reason": "not urgent", "source": "WON"},
            {"title": "Menzo Jack", "source_url": "https://example.test/jack", "score": 88, "priority": "hard", "article_type": "hard_news", "decision": "selected", "reason": "strong item", "source": "PWInsider"},
        ]}, "publisher": {"published": [
            {"title": "Finn Balor published", "source_url": "https://example.test/finn", "wp_link": "https://owrestling.test/finn"},
            {"title": "Kenny Omega published", "source_url": "https://example.test/kenny", "wp_link": "https://owrestling.test/kenny"},
            {"title": "Jack Perry published", "source_url": "https://example.test/jack", "wp_link": "https://owrestling.test/jack"},
        ]}},
    ])
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(
        build_report(load_inputs({"master_log": master}, now=now))
    )
    records = {item["source_url"]: item for item in payload["daily_numbers"]["news_records"]}
    assert records["https://example.test/finn"]["title"] == "Finn Balor published"
    assert records["https://example.test/finn"]["wp_link"] == "https://owrestling.test/finn"
    assert records["https://example.test/finn"]["score"] == 100
    assert records["https://example.test/finn"]["priority"] == "hard"
    assert records["https://example.test/finn"]["article_type"] == "hard_news"
    assert records["https://example.test/finn"]["menzo_decision"] == "selected"
    assert records["https://example.test/finn"]["menzo_reason"] == "major injury angle"
    assert records["https://example.test/kenny"]["score"] == 72
    assert records["https://example.test/kenny"]["priority"] == "soft"
    assert records["https://example.test/jack"]["score"] == 88


def test_null_score_is_not_borderline_without_meaningful_metadata_and_enriched_soft_can_be_borderline() -> None:
    report = build_report({"master_log": {"menzo": {"selected": [
        {"source_url": "https://example.test/soft", "score": 72, "priority": "soft", "article_type": "strategic_discussion", "decision": "selected", "reason": "discussion piece"}
    ]}, "publisher": {"published": [
        {"title": "No metadata", "source_url": "https://example.test/no-meta"},
        {"title": "Vince Russo", "source_url": "https://example.test/soft"},
    ]}}})
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert [item["title"] for item in payload["daily_numbers"]["news_records"]] == ["No metadata", "Vince Russo"]
    assert payload["daily_numbers"]["news_records"][0]["score"] is None
    assert payload["borderline_published"] == [{
        "title": "Vince Russo",
        "source": "",
        "url": "https://example.test/soft",
        "score": 72,
        "article_type": "strategic_discussion",
        "priority": "soft",
        "menzo_decision": "selected",
        "menzo_reason": "discussion piece",
        "automatic_judgment": "",
        "source_url": "https://example.test/soft",
    }]


def test_menzo_enriched_published_records_do_not_double_count_aggregate_hard_soft(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    selected = [
        {"title": f"Selected {idx}", "source_url": f"https://example.test/hard-{idx}", "score": 90 + idx, "priority": "hard", "article_type": "hard_news", "decision": "selected", "reason": "hard item"}
        for idx in range(3)
    ]
    master = write_jsonl(tmp_path / "state/newsroom/master_log.jsonl", [
        {"recorded_at": now.isoformat(), "menzo": {"selected": selected}, "publisher": {"published": [
            {"title": f"Published {idx}", "source_url": f"https://example.test/hard-{idx}", "wp_link": f"https://owrestling.test/hard-{idx}"}
            for idx in range(3)
        ]}},
    ])
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(
        build_report(load_inputs({"master_log": master}, now=now))
    )
    assert payload["daily_numbers"]["hard_news_count"] == 3
    assert payload["daily_numbers"]["soft_news_count"] == 0
    assert payload["daily_numbers"]["article_types"] == {"hard_news": 3}
    assert payload["hard_soft_balance"]["source"] == "records"
    assert [item["wp_link"] for item in payload["daily_numbers"]["news_records"]] == [
        "https://owrestling.test/hard-0",
        "https://owrestling.test/hard-1",
        "https://owrestling.test/hard-2",
    ]
    assert payload["daily_numbers"]["news_records"][0]["score"] == 90


def test_markdown_article_types_still_override_deduped_record_aggregates(tmp_path: Path) -> None:
    now = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    master = write_jsonl(tmp_path / "state/newsroom/master_log.jsonl", [
        {"recorded_at": now.isoformat(), "menzo": {"selected": [
            {"title": "Selected hard", "source_url": "https://example.test/hard", "score": 90, "priority": "hard", "article_type": "hard_news"}
        ]}, "publisher": {"published": [
            {"title": "Published hard", "source_url": "https://example.test/hard", "wp_link": "https://owrestling.test/hard"}
        ]}},
    ])
    editorial = """## 3. Tipologia contenuti pubblicati/rilevati
- news_generica: 2
"""
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(
        build_report(load_inputs({"master_log": master, "editorial_audit": write_json(tmp_path / "reports/audit.json", {"_markdown": editorial})}, now=now))
    )
    assert payload["daily_numbers"]["article_types"] == {"news_generica": 2}
    assert payload["daily_numbers"]["hard_news_count"] == 0
    assert payload["daily_numbers"]["soft_news_count"] == 2
    assert payload["hard_soft_balance"]["source"] == "article_types_markdown"


def test_borderline_published_dedupes_enriched_published_duplicates() -> None:
    report = build_report({"master_log": {"menzo": {"selected": [
        {"source_url": "https://example.test/soft-dupe", "score": 72, "priority": "soft", "article_type": "hard_news", "decision": "selected", "reason": "soft priority"}
    ]}, "publisher": {"published": [
        {"title": "Soft published", "source_url": "https://example.test/soft-dupe", "wp_link": "https://owrestling.test/soft-dupe"},
        {"title": "Soft published duplicate", "source_url": "https://example.test/soft-dupe", "wp_link": "https://owrestling.test/soft-dupe-2"},
    ]}}})
    payload = __import__("scripts.daily_editorial_judgment", fromlist=["structured_json"]).structured_json(report)
    assert len(payload["borderline_published"]) == 1
    assert payload["borderline_published"][0]["source_url"] == "https://example.test/soft-dupe"
    assert payload["borderline_published"][0]["score"] == 72


def test_daily_email_summary_reads_nested_alfred_counts(tmp_path: Path) -> None:
    from send_daily_report import daily_editorial_judgment_body_section

    latest = write_json(tmp_path / "latest.json", {
        "judgment": "GOOD",
        "day_type": "intensa",
        "summary": "Strong news day",
        "daily_numbers": {
            "news_published": 12,
            "reports_published": 2,
            "alfred": {"warnings": 20, "blockers": 1},
            "gemini_3_5_called_total": 4,
        },
    })

    summary = daily_editorial_judgment_body_section(latest)

    assert "- judgment: GOOD" in summary
    assert "- day_type: intensa" in summary
    assert "- summary: Strong news day" in summary
    assert "- news_published: 12" in summary
    assert "- reports_published: 2" in summary
    assert "- Alfred warnings/blockers: 20/1" in summary
    assert "- gemini_3_5_called_total: 4" in summary


def test_daily_email_summary_uses_legacy_flat_alfred_fallback(tmp_path: Path) -> None:
    from send_daily_report import daily_editorial_judgment_body_section

    latest = write_json(tmp_path / "latest.json", {
        "judgment": "OK",
        "day_type": "normale",
        "summary": "Normal day",
        "daily_numbers": {
            "news_published": 5,
            "reports_published": 1,
            "alfred_warnings": 7,
            "alfred_blockers": 2,
            "gemini_3_5_called_total": 3,
        },
    })

    summary = daily_editorial_judgment_body_section(latest)

    assert "- Alfred warnings/blockers: 7/2" in summary
    assert "- judgment: OK" in summary
    assert "- day_type: normale" in summary
    assert "- summary: Normal day" in summary
    assert "- news_published: 5" in summary
    assert "- reports_published: 1" in summary
    assert "- gemini_3_5_called_total: 3" in summary


def test_daily_email_summary_missing_alfred_values_render_nd(tmp_path: Path) -> None:
    from send_daily_report import daily_editorial_judgment_body_section

    latest = write_json(tmp_path / "latest.json", {
        "judgment": "LOW",
        "day_type": "scarica",
        "summary": "Quiet day",
        "daily_numbers": {
            "news_published": 0,
            "reports_published": 0,
            "alfred": "unexpected",
            "gemini_3_5_called_total": 0,
        },
    })

    summary = daily_editorial_judgment_body_section(latest)

    assert "- Alfred warnings/blockers: n.d./n.d." in summary
    assert "- judgment: LOW" in summary
    assert "- day_type: scarica" in summary
    assert "- summary: Quiet day" in summary
    assert "- news_published: 0" in summary
    assert "- reports_published: 0" in summary
    assert "- gemini_3_5_called_total: 0" in summary
