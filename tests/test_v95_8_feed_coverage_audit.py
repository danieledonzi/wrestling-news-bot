import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import owtv_feed_coverage_audit as audit


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def run(tmp_path, monkeypatch):
    monkeypatch.setenv("OWTV_REPORTS_DIR", str(tmp_path / "reports"))
    text, out = audit.build_audit(24, root=tmp_path)
    assert out.exists()
    return text


def seed_required(tmp_path):
    ns = tmp_path / "state" / "newsroom"
    write(ns / "andrea_pre_bob_latest.json", {"blocked_items": [], "passed_items": []})
    write(ns / "bob_articles_latest.json", {"articles": []})
    write(ns / "alfred_review_latest.json", {"reviews": [], "approved_articles": []})
    write(ns / "simone_reports_latest.json", {"reports": []})
    write(ns / "simone_report_publish_latest.json", {"results": []})


def test_published_low_skip_high_skip_unknown_and_missing_inputs(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    feed = [
        {"source":"Fightful","title":"Star signs with WWE","url":"https://e.test/published"},
        {"source":"Blog","title":"Old podcast reaction","url":"https://e.test/low"},
        {"source":"Fightful","title":"Major title change","url":"https://e.test/high"},
        {"source":"Source","title":"Disappeared feed item","url":"https://e.test/unknown"},
    ]
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": feed})
    write(ns / "menzo_decisions_latest.json", {
        "selected": [{**feed[0], "decision":"selected", "score":88, "priority":"hard", "article_type":"roster"}],
        "skipped": [
            {**feed[1], "decision":"skip", "score":20, "priority":"skip", "article_type":"low_value", "reason":"low_score"},
            {**feed[2], "decision":"skip", "score":91, "priority":"hard", "article_type":"title", "reason":"ai_duplicate_of:c1"},
        ],
        "pending": [],
    })
    write(ns / "publisher_status_latest.json", {"results": [{"source_url":"https://e.test/published", "title_it":"Star signs with WWE", "status":"published", "wp_link":"https://owtv.test/published"}]})
    text = run(tmp_path, monkeypatch)
    assert "Feed URLs published: 1" in text
    assert "Major title change" in text and "must_publish_candidate" in text
    assert "Disappeared feed item" in text and "unknown" in text
    assert "missing_input:" in text


def test_story_thread_overcoverage_and_report_overlap(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    feed = [
        {"source":"A","title":"WWE Raw results Cody wins title","url":"https://e.test/a"},
        {"source":"B","title":"WWE Raw results Cody wins title follow up","url":"https://e.test/b"},
    ]
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": feed})
    write(ns / "menzo_decisions_latest.json", {"selected":[{**x,"decision":"selected","score":75,"article_type":"result_event"} for x in feed], "skipped":[], "pending":[]})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url":"https://e.test/a", "title_it":"WWE Raw results Cody wins title", "status":"published"},
        {"source_url":"https://e.test/b", "title_it":"WWE Raw results Cody wins title follow up", "status":"published"},
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title":"WWE Raw report"}]})
    text = run(tmp_path, monkeypatch)
    assert "possible_overcoverage" in text
    assert "possible_report_duplicate" in text or "likely_valid_major_angle" in text


def test_missing_input_files_do_not_crash(tmp_path, monkeypatch):
    text = run(tmp_path, monkeypatch)
    assert "Feed URLs seen: 0" in text
    assert "Input warnings" in text


def test_massy_routing_decisions_are_preserved(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {
        "report_candidates": [{"source":"A", "title":"Raw results", "url":"https://e.test/report", "decision":"report_candidate", "assigned_to":"Simone", "reason":"report_like_title"}],
        "already_worked": [{"source":"B", "title":"Seen", "url":"https://e.test/seen", "decision":"already_worked", "reason":"history_match"}],
        "hard_skipped": [{"source":"C", "title":"Skipped", "url":"https://e.test/skip", "decision":"hard_skip", "reason":"url_already_published"}],
    })
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    text = run(tmp_path, monkeypatch)
    assert "report_candidate" in text
    assert "already_seen" in text
    assert "hard_skip/url_already_published" in text
    assert "https://e.test/report" in text and "| unknown |" not in text.split("https://e.test/report", 1)[1].splitlines()[0]


def test_andrea_blocked_selected_high_score_is_not_potential_miss(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source":"Fightful", "title":"Major star signs with WWE", "url":"https://e.test/andrea"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [item]})
    write(ns / "menzo_decisions_latest.json", {"selected": [{**item, "decision":"selected", "score":94, "priority":"hard", "article_type":"roster"}], "skipped": [], "pending": []})
    write(ns / "andrea_pre_bob_latest.json", {"blocked_items": [{**item, "status":"blocked", "reason":"insufficient_content", "andrea_blocked_before_bob": True}]})
    write(ns / "publisher_status_latest.json", {"results": []})
    text = run(tmp_path, monkeypatch)
    assert "blocked_by_andrea" in text
    assert "blocked/insufficient_content" in text
    assert "- Potential must-publish missed: 0" in text
    assert "potential_miss" not in text


def test_report_overlap_ignores_unpublished_publisher_records(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source":"A", "title":"WWE Raw results not published", "url":"https://e.test/unpub"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [item]})
    write(ns / "menzo_decisions_latest.json", {"selected": [{**item, "decision":"selected", "score":75, "article_type":"result_event"}], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url":"https://e.test/unpub", "title_it":"WWE Raw results not published", "status":"wp_not_ready"}
    ], "skipped_approved_articles": [
        {"source_url":"https://e.test/capacity", "title_it":"WWE Raw results capacity", "status":"skipped_capacity"}
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title":"WWE Raw report"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show/report overlap risks: 0" in text
    assert "## 7. Report/post-show overlap\n\n- None detected." in text


def test_pipeline_artifact_variants_collapse_to_one_published_item(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"title_it": "CM Punk title details", "status": "published", "path": "v93_news_cm-punk-title-details.html"},
        {"title_it": "CM Punk title details", "status": "published", "path": "v93_publisher_cm-punk-title-details.html"},
    ]})
    text = run(tmp_path, monkeypatch)
    assert "- Potential story-thread overcoverage: 0" in text


def test_prepublish_artifact_is_not_extra_publication(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"title_it": "Vikingo injury surgery", "status": "published", "path": "v93_news_vikingo-injury-surgery.html"},
        {"title_it": "Vikingo injury surgery", "status": "published", "path": "v93_news_vikingo-injury-surgery.prepublish.html"},
    ]})
    text = run(tmp_path, monkeypatch)
    assert "- Potential story-thread overcoverage: 0" in text


def test_hard_skip_url_already_published_matches_published_trace(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source": "Fightful", "title": "Star signs with WWE", "url": "https://e.test/already"}
    write(ns / "massy_board_latest.json", {"hard_skipped": [{**item, "decision": "hard_skip", "reason": "url_already_published"}]})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/already", "title_it": "Star signs with WWE", "status": "published", "wp_link": "https://owtv.test/already"}
    ]})
    text = run(tmp_path, monkeypatch)
    assert "Feed URLs published: 1" in text
    assert "| Fightful | Star signs with WWE | https://e.test/already" in text
    assert "| published |" in text


def test_report_overlap_ignores_unrelated_published_articles(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/tko", "title_it": "TKO business update on company earnings", "status": "published"},
        {"source_url": "https://e.test/sheamus", "title_it": "Sheamus contract update emerges", "status": "published"},
        {"source_url": "https://e.test/aew", "title_it": "Chris Jericho AEW backstage note", "status": "published"},
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title": "WWE Raw results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show/report overlap risks: 0" in text


def test_report_overlap_detects_raw_title_change_candidate(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/raw-title", "title_it": "WWE Raw results new champion wins title on July 6", "status": "published"},
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title": "WWE Raw results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show/report overlap risks: 1" in text
    assert "WWE Raw results new champion wins title on July 6" in text


def test_source_coverage_publish_rate_uses_published_artifact_trace(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source": "Fightful", "title": "CM Punk title details", "url": "https://e.test/cm-punk-title-details"}
    write(ns / "massy_board_latest.json", {"hard_skipped": [{**item, "decision": "hard_skip", "reason": "url_already_published"}]})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    artifact = tmp_path / "published_html_review" / "v93_news_cm-punk-title-details.html"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("<html><title>CM Punk title details</title></html>", encoding="utf-8")
    text = run(tmp_path, monkeypatch)
    assert "Feed URLs published: 1" in text
    assert "| Fightful | 1 | 1 | 0 | 0 | 0 | 100% | 0 |" in text


def test_artifacts_newsroom_massy_board_is_not_published_story(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    write(tmp_path / "artifacts" / "newsroom" / "massy_board.json", {
        "news_candidates_for_menzo": [{"title": "Not a published story", "url": "https://e.test/not-published"}]
    })
    text = run(tmp_path, monkeypatch)
    assert "Not a published story" not in text
    assert "- Post-show/report overlap risks: 0" in text


def test_artifacts_newsroom_publisher_result_without_metadata_is_not_published_story(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    write(tmp_path / "artifacts" / "newsroom" / "publisher_result.json", {
        "source_url": "https://e.test/unpublished",
        "title_it": "Raw results not actually published",
    })
    write(ns / "simone_reports_latest.json", {"reports": [{"title": "WWE Raw results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "Raw results not actually published" not in text
    assert "- Post-show/report overlap risks: 0" in text


def test_publisher_source_url_and_publisher_html_slug_collapse(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://source.test/cm-punk-title-details", "title_it": "CM Punk title details", "status": "published", "wp_link": "https://owtv.test/cm-punk-title-details"},
    ]})
    artifact = tmp_path / "published_html_review" / "v93_publisher_cm-punk-title-details.html"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("<html><title>CM Punk title details</title></html>", encoding="utf-8")
    text = run(tmp_path, monkeypatch)
    assert "- Potential story-thread overcoverage: 0" in text


def test_news_and_publisher_html_artifacts_collapse_by_slug(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    for name in ["v93_news_cm-punk-title-details.html", "v93_publisher_cm-punk-title-details.html"]:
        artifact = tmp_path / "published_html_review" / name
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("<html><title>CM Punk title details</title></html>", encoding="utf-8")
    text = run(tmp_path, monkeypatch)
    assert "- Potential story-thread overcoverage: 0" in text


def test_overcoverage_ignores_duplicated_local_artifacts_for_same_slug(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    for directory, name in [
        ("published", "v93_news_vikingo-injury-surgery.html"),
        ("published_html_review", "v93_publisher_vikingo-injury-surgery.html"),
    ]:
        artifact = tmp_path / directory / name
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("<html><title>Vikingo injury surgery</title></html>", encoding="utf-8")
    text = run(tmp_path, monkeypatch)
    assert "- Potential story-thread overcoverage: 0" in text
