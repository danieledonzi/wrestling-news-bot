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
