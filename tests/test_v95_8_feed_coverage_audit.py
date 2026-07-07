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
    assert "duplicate_recap_risk" in text


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
    assert "- Post-show duplicate recap risks: 0" in text
    assert "## 8. Post-show duplicate recap risks\n\n- None detected." in text


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
    assert "- Post-show duplicate recap risks: 0" in text


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
    assert "- Post-show duplicate recap risks: 1" in text
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
    assert "- Post-show duplicate recap risks: 0" in text


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
    assert "- Post-show duplicate recap risks: 0" in text


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


def test_window_artifacts_aggregate_multiple_runs_into_24h_audit(tmp_path, monkeypatch):
    runs = tmp_path / "artifacts" / "newsroom_runs"
    write(runs / "run1" / "massy_board.json", {"news_candidates_for_menzo": [
        {"source": "Fightful", "title": "First WWE item", "url": "https://e.test/first"}
    ]})
    write(runs / "run2" / "massy_board.json", {"news_candidates_for_menzo": [
        {"source": "WON", "title": "Second WWE item", "url": "https://e.test/second"}
    ]})
    write(runs / "run2" / "menzo_decisions.json", {"selected": [
        {"title": "Second WWE item", "url": "https://e.test/second", "decision": "selected", "score": 82, "article_type": "hard_news"}
    ], "pending": [], "skipped": []})
    text = run(tmp_path, monkeypatch)
    assert "mode: historical_window" in text
    assert "Feed URLs seen: 2" in text
    assert "First WWE item" in text and "Second WWE item" in text
    assert "Feed URLs with Menzo decision: 1" in text


def test_latest_only_fallback_emits_mode_and_warning(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [
        {"source": "Fightful", "title": "Latest snapshot item", "url": "https://e.test/latest"}
    ]})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "pending": [], "skipped": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    text = run(tmp_path, monkeypatch)
    assert "mode: latest_snapshot_fallback" in text
    assert "published coverage may be incomplete" in text


def test_published_count_recovers_when_massy_and_publisher_are_different_runs(tmp_path, monkeypatch):
    runs = tmp_path / "artifacts" / "newsroom_runs"
    item = {"source": "Fightful", "title": "CM Punk wins title", "url": "https://e.test/punk-title"}
    write(runs / "run1" / "massy_board.json", {"news_candidates_for_menzo": [item]})
    write(runs / "run2" / "publisher_status.json", {"generated_at": audit.utc_now().isoformat(), "results": [
        {"source_url": "https://e.test/punk-title", "title_it": "CM Punk wins title", "status": "published", "wp_link": "https://owtv.test/punk-title"}
    ]})
    text = run(tmp_path, monkeypatch)
    assert "Feed URLs published: 1" in text
    assert "| Final published | 1 |" in text
    assert "CM Punk wins title" in text


def test_source_coverage_publish_rate_recovered_from_per_run_artifacts(tmp_path, monkeypatch):
    runs = tmp_path / "artifacts" / "newsroom_runs"
    write(runs / "run1" / "massy_board.json", {"news_candidates_for_menzo": [
        {"source": "Fightful", "title": "Published one", "url": "https://e.test/pub"},
        {"source": "Fightful", "title": "Unpublished one", "url": "https://e.test/unpub"},
    ]})
    write(runs / "run2" / "publisher_status.json", {"generated_at": audit.utc_now().isoformat(), "results": [
        {"source_url": "https://e.test/pub", "title_it": "Published one", "status": "published", "wp_link": "https://owtv.test/pub"}
    ]})
    text = run(tmp_path, monkeypatch)
    assert "Feed URLs published: 1" in text
    assert "| Fightful | 2 | 1 | 0 | 0 | 1 | 50% | 0 |" in text


def test_raw_report_does_not_overlap_with_aew_dynamite_article(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/dynamite", "title_it": "AEW Dynamite results new champion wins title", "status": "published"},
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title": "WWE Raw results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 0" in text


def test_raw_report_overlaps_raw_title_change_result_article(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/raw-change", "title_it": "WWE Raw results new champion wins title", "status": "published"},
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title": "WWE Raw results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 1" in text
    assert "WWE Raw results new champion wins title" in text


def test_old_generated_at_artifact_with_fresh_mtime_is_excluded(tmp_path, monkeypatch):
    runs = tmp_path / "artifacts" / "newsroom_runs"
    write(runs / "old" / "massy_board.json", {
        "generated_at": "2000-01-01T00:00:00Z",
        "news_candidates_for_menzo": [
            {"source": "Old", "title": "Old generated item", "url": "https://e.test/old-generated"}
        ],
    })
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "pending": [], "skipped": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    text = run(tmp_path, monkeypatch)
    assert "Old generated item" not in text
    assert "mode: latest_snapshot_fallback" in text


def test_artifact_without_embedded_timestamp_can_use_mtime_fallback(tmp_path, monkeypatch):
    runs = tmp_path / "artifacts" / "newsroom_runs"
    write(runs / "mtime" / "massy_board.json", {"news_candidates_for_menzo": [
        {"source": "Fightful", "title": "Fresh mtime item", "url": "https://e.test/fresh-mtime"}
    ]})
    text = run(tmp_path, monkeypatch)
    assert "mode: historical_window" in text
    assert "Fresh mtime item" in text


def test_publisher_rows_inherit_trusted_parent_generated_at(tmp_path, monkeypatch):
    runs = tmp_path / "artifacts" / "newsroom_runs"
    item = {"source": "Fightful", "title": "Trusted parent publish", "url": "https://e.test/trusted-parent"}
    write(runs / "run1" / "massy_board.json", {"news_candidates_for_menzo": [item]})
    write(runs / "run2" / "publisher_status.json", {
        "generated_at": audit.utc_now().isoformat(),
        "results": [
            {"source_url": "https://e.test/trusted-parent", "title_it": "Trusted parent publish", "status": "published", "wp_link": "https://owtv.test/trusted-parent"}
        ],
    })
    text = run(tmp_path, monkeypatch)
    assert "Feed URLs published: 1" in text
    assert "Trusted parent publish" in text


def test_irrelevant_fresh_json_does_not_disable_latest_fallback(tmp_path, monkeypatch):
    write(tmp_path / "artifacts" / "newsroom_runs" / "run1" / "diagnostic.json", {"generated_at": audit.utc_now().isoformat(), "note": "not a stage"})
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [
        {"source": "Fightful", "title": "Latest still used", "url": "https://e.test/latest-used"}
    ]})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "pending": [], "skipped": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    text = run(tmp_path, monkeypatch)
    assert "mode: latest_snapshot_fallback" in text
    assert "Latest still used" in text


def test_historical_mode_activates_only_when_useful_stage_is_merged(tmp_path, monkeypatch):
    write(tmp_path / "artifacts" / "newsroom_runs" / "run1" / "massy_board.json", {
        "generated_at": audit.utc_now().isoformat(),
        "news_candidates_for_menzo": [
            {"source": "Fightful", "title": "Useful historical item", "url": "https://e.test/useful-historical"}
        ],
    })
    text = run(tmp_path, monkeypatch)
    assert "mode: historical_window" in text
    assert "Useful historical item" in text


def test_tna_impact_report_overlaps_impact_result_article(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/impact", "title_it": "TNA Impact results new champion wins title", "status": "published"},
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title": "TNA Impact results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 1" in text
    assert "TNA Impact results new champion wins title" in text


def test_duplicate_arbitration_loser_with_related_published_survivor_is_not_potential_miss(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    loser = {"source":"Fightful", "title":"WWE Raw new champion wins title", "url":"https://e.test/loser"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [loser]})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [
        {**loser, "decision":"skip", "score":92, "priority":"hard", "article_type":"title", "reason":"ai_cross_source_duplicate_arbitration_loser"}
    ], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url":"https://e.test/survivor", "title_it":"WWE Raw new champion wins title", "status":"published"}
    ]})
    text = run(tmp_path, monkeypatch)
    assert "- Potential must-publish missed: 0" in text
    assert "duplicate loser; verify survivor coverage" in text
    assert "must_publish_candidate" not in text


def test_duplicate_arbitration_loser_without_known_survivor_is_review_not_must_publish(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    loser = {"source":"Fightful", "title":"WWE Raw new champion wins title", "url":"https://e.test/loser"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [loser]})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [
        {**loser, "decision":"skip", "score":92, "priority":"hard", "article_type":"title", "reason":"duplicate_arbitration_loser"}
    ], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    text = run(tmp_path, monkeypatch)
    assert "duplicate_loser_review" in text
    assert "- Potential must-publish missed: 0" in text
    assert "potential_miss" not in text


def test_published_html_without_source_url_counts_in_final_published(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    artifact = tmp_path / "published_html_review" / "v93_news_orphan-published.html"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("<html><title>Orphan published item</title></html>", encoding="utf-8")
    text = run(tmp_path, monkeypatch)
    assert "| Final published | 1 |" in text
    assert "Orphan published item" in text


def test_report_candidate_and_simone_published_report_collapse_to_one_overlap_source(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url":"https://e.test/raw", "title_it":"WWE Raw results highlights", "status":"published"}
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title":"WWE Raw results July 6", "generated_at": audit.utc_now().isoformat()}]})
    write(ns / "simone_report_publish_latest.json", {"results": [{"title":"WWE Raw results July 6", "status":"published", "wp_link":"https://owtv.test/raw-report", "published_at": audit.utc_now().isoformat()}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 1" in text


def test_raw_title_change_article_not_labeled_duplicate_recap_risk(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url":"https://e.test/raw-title", "title_it":"WWE Raw title change crowns new champion", "status":"published"}
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title":"WWE Raw results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 0" in text
    assert "WWE Raw title change crowns new champion` — duplicate_recap_risk" not in text


def test_diagnostics_show_stage_file_counts_and_merged_record_counts(tmp_path, monkeypatch):
    runs = tmp_path / "artifacts" / "newsroom_runs"
    write(runs / "run1" / "massy_board.json", {"news_candidates_for_menzo": [
        {"source":"Fightful", "title":"Diagnostic item", "url":"https://e.test/diag"}
    ]})
    write(runs / "run1" / "publisher_status.json", {"generated_at": audit.utc_now().isoformat(), "results": [
        {"source_url":"https://e.test/diag", "title_it":"Diagnostic item", "status":"published"}
    ]})
    text = run(tmp_path, monkeypatch)
    assert "Historical artifact discovery diagnostics" in text
    assert "| Historical files scanned |" in text
    assert "| Historical files inside window |" in text
    assert "| Useful Massy records merged | 1 |" in text
    assert "| Useful Publisher records merged | 1 |" in text
    assert "| Publisher published records before dedupe | 1 |" in text


def test_source_less_simone_report_publish_does_not_count_as_feed_story(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": []})
    write(ns / "simone_report_publish_latest.json", {
        "generated_at": audit.utc_now().isoformat(),
        "results": [{"title": "WWE Raw del 6 luglio 2026", "status": "published", "wp_link": "https://owtv.test/raw-report"}],
    })
    text = run(tmp_path, monkeypatch)
    assert "- Feed URLs seen: 0" in text
    assert "- Feed URLs published: 0" in text
    assert "| Final published | 0 |" in text
    assert "published-artifact:wwe-raw-del-6-luglio-2026" not in text


def test_source_less_simone_report_publish_remains_available_for_overlap(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/raw-angle", "title_it": "WWE Raw title change crowns new champion", "status": "published"}
    ]})
    write(ns / "simone_report_publish_latest.json", {
        "generated_at": audit.utc_now().isoformat(),
        "results": [{"title": "WWE Raw del 6 luglio 2026", "status": "published", "wp_link": "https://owtv.test/raw-report"}],
    })
    text = run(tmp_path, monkeypatch)
    assert "- Feed URLs published: 1" in text
    assert "- Post-show duplicate recap risks: 0" in text
    assert "WWE Raw title change crowns new champion` — duplicate_recap_risk" not in text


def test_raw_report_candidate_and_simone_report_collapse_without_child_timestamps(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/raw-title", "title_it": "WWE Raw title change crowns new champion", "status": "published"}
    ]})
    parent_time = "2026-07-06T23:00:00Z"
    write(ns / "simone_reports_latest.json", {"generated_at": parent_time, "reports": [
        {"title": "WWE Raw Results 7/6 full report"}
    ]})
    write(ns / "simone_report_publish_latest.json", {"generated_at": parent_time, "results": [
        {"title": "WWE Raw del 6 luglio 2026", "status": "published", "wp_link": "https://owtv.test/raw-report"}
    ]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 0" in text
    assert text.count("Report `WWE Raw del 6 luglio 2026` vs `WWE Raw title change crowns new champion`") == 0


def test_raw_reports_from_different_dates_do_not_collapse(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": "https://e.test/raw-title", "title_it": "WWE Raw title change crowns new champion", "status": "published"}
    ]})
    write(ns / "simone_reports_latest.json", {"generated_at": "2026-07-06T23:00:00Z", "reports": [
        {"title": "WWE Raw Results 7/6 full report"},
        {"title": "WWE Raw Results 7/7 full report"},
    ]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 0" in text


def test_raw_report_does_not_flag_required_standalone_major_event_news(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    articles = [
        ("https://e.test/cm-punk", "CM Punk conquista l’Undisputed WWE Championship"),
        ("https://e.test/cody", "Cody Rhodes rimosso dal title match dopo l’attacco di Gunther"),
        ("https://e.test/brock", "Il ritorno di Brock Lesnar e i match annunciati per la prossima Raw"),
        ("https://e.test/sol", "Sol Ruca batte Raquel Rodriguez e mantiene il Women’s Intercontinental Championship"),
    ]
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": url, "title_it": title, "status": "published"} for url, title in articles
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title": "WWE Raw results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 0" in text
    for _, title in articles:
        assert f"`{title}` — duplicate_recap_risk" not in text


def test_raw_report_flags_required_generic_duplicate_recap_titles(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    titles = [
        "WWE Raw Results 7/6",
        "WWE Raw risultati e momenti salienti",
        "WWE Raw recap",
        "WWE Raw highlights",
        "WWE RAW 7/6: 3 Things We Hated & 3 Things We Loved",
        "WWE Raw live coverage",
        "WWE Raw live blog",
        "WWE Raw play-by-play",
        "WWE Raw live updates",
    ]
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected": [], "skipped": [], "pending": []})
    write(ns / "publisher_status_latest.json", {"results": [
        {"source_url": f"https://e.test/generic-{i}", "title_it": title, "status": "published"}
        for i, title in enumerate(titles)
    ]})
    write(ns / "simone_reports_latest.json", {"reports": [{"title": "WWE Raw results July 6"}]})
    text = run(tmp_path, monkeypatch)
    assert "- Post-show duplicate recap risks: 9" in text
    for title in titles:
        assert f"`{title}` — duplicate_recap_risk" in text


def test_v95_8_5_exact_source_url_match(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source":"WrestlingInc", "title":"Star signs with WWE", "url":"https://wrestlinginc.com/exact"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [item]})
    write(ns / "menzo_decisions_latest.json", {"selected":[{**item,"score":90,"article_type":"roster"}], "skipped":[], "pending":[]})
    write(ns / "publisher_status_latest.json", {"results":[{"source_url":"https://wrestlinginc.com/exact", "title_it":"Star signs with WWE", "status":"published"}]})
    text = run(tmp_path, monkeypatch)
    assert "published_exact_source_url" in text


def test_v95_8_5_already_published_classification(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source":"RingsideNews", "title":"Seen again", "url":"https://ringsidenews.com/seen", "decision":"hard_skip", "reason":"url_already_published"}
    write(ns / "massy_board_latest.json", {"hard_skipped": [item]})
    write(ns / "menzo_decisions_latest.json", {"selected":[], "skipped":[], "pending":[]})
    write(ns / "publisher_status_latest.json", {"results":[]})
    text = run(tmp_path, monkeypatch)
    assert "already_published_before_window_or_seen_again" in text


def test_v95_8_5_duplicate_loser_has_survivor_not_missed(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    loser = {"source":"WrestlingInc", "title":"CM Punk title update", "url":"https://wrestlinginc.com/loser"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [loser]})
    write(ns / "menzo_decisions_latest.json", {"selected":[], "pending":[], "skipped":[{**loser,"decision":"skip","score":85,"article_type":"title","reason":"ai_cross_source_duplicate_arbitration_loser","duplicate_of":"cm-punk-title-update"}]})
    write(ns / "publisher_status_latest.json", {"results":[{"title_it":"CM Punk title update", "status":"published", "path":"cm-punk-title-update.html"}]})
    text = run(tmp_path, monkeypatch)
    assert "duplicate_loser_covered" in text
    assert "CM Punk title update" in text and "candidate_not_published_review" not in text


def test_v95_8_5_low_value_social_reaction_skipped(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source":"RingsideNews", "title":"Fans react to star photo", "url":"https://ringsidenews.com/react"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [item]})
    write(ns / "menzo_decisions_latest.json", {"selected":[], "pending":[], "skipped":[{**item,"decision":"skip","score":20,"article_type":"reaction","reason":"low_value social reaction"}]})
    write(ns / "publisher_status_latest.json", {"results":[]})
    text = run(tmp_path, monkeypatch)
    assert "skipped_correctly_likely" in text


def test_v95_8_5_hard_news_unmatched_is_review(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source":"WrestlingInc", "title":"Major star signs with WWE", "url":"https://wrestlinginc.com/hard"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [item]})
    write(ns / "menzo_decisions_latest.json", {"selected":[{**item,"decision":"selected","score":91,"priority":"hard","article_type":"roster"}], "pending":[], "skipped":[]})
    write(ns / "publisher_status_latest.json", {"results":[]})
    text = run(tmp_path, monkeypatch)
    assert "candidate_not_published_review" in text
    assert "What might we have missed" in text


def test_v95_8_5_published_artifact_without_source_url_is_trace_issue_only(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": []})
    write(ns / "menzo_decisions_latest.json", {"selected":[], "pending":[], "skipped":[]})
    write(ns / "publisher_status_latest.json", {"results":[{"title_it":"No source story", "status":"published", "path":"no-source-story.html"}]})
    text = run(tmp_path, monkeypatch)
    assert "source_url_missing" in text
    assert "Published without source attribution" in text
    assert "published-artifact:" not in text


def test_v95_8_5_slug_title_match_is_alternate(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    item = {"source":"RingsideNews", "title":"CM Punk injury update", "url":"https://ringsidenews.com/original"}
    write(ns / "massy_board_latest.json", {"news_candidates_for_menzo": [item]})
    write(ns / "menzo_decisions_latest.json", {"selected":[{**item,"score":88,"article_type":"injury"}], "pending":[], "skipped":[]})
    write(ns / "publisher_status_latest.json", {"results":[{"title_it":"CM Punk injury update", "status":"published", "path":"cm-punk-injury-update.html"}]})
    text = run(tmp_path, monkeypatch)
    assert "published_by_alternate_source_or_slug" in text


def test_v95_8_5_report_candidates_not_missed_and_raw_news_normal(tmp_path, monkeypatch):
    seed_required(tmp_path)
    ns = tmp_path / "state" / "newsroom"
    report = {"source":"WrestlingInc", "title":"WWE Raw results recap", "url":"https://wrestlinginc.com/report", "decision":"report_candidate", "reason":"report_candidate"}
    raw_news = {"source":"RingsideNews", "title":"New champion wins title on WWE Raw", "url":"https://ringsidenews.com/raw-title"}
    write(ns / "massy_board_latest.json", {"report_candidates":[report], "news_candidates_for_menzo":[raw_news]})
    write(ns / "menzo_decisions_latest.json", {"selected":[{**raw_news,"score":90,"article_type":"title"}], "pending":[], "skipped":[]})
    write(ns / "publisher_status_latest.json", {"results":[{"source_url":"https://ringsidenews.com/raw-title", "title_it":"New champion wins title on WWE Raw", "status":"published"}]})
    text = run(tmp_path, monkeypatch)
    assert "skipped_correctly_likely" in text
    assert "published_exact_source_url" in text
