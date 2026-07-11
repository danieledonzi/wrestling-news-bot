import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import massy
from agents import menzo_policy_v93_15 as menzo
from agents import publisher


def item(title, url, summary="", body_html="", score=90, source="Example"):
    return {
        "title": title,
        "source_title": title,
        "url": url,
        "source_url": url,
        "summary": summary or title,
        "body_html": body_html or summary or title,
        "score": score,
        "ai_priority_label": "high",
        "decision": "selected",
        "source": source,
    }


def result(items):
    return {"selected": items, "pending": [], "skipped": [], "postprocess": {}, "daily_policy": {}}


def patch_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_FILE", tmp_path / "cache.json")


def test_massy_only_forwards_suspicious_same_run_pairs():
    a = item("Baron Corbin Makes WWE Return During 7/10 SmackDown", "https://example.test/c1", "Baron Corbin returned on SmackDown.")
    b = item("Baron Corbin Returns On WWE SmackDown, Takes Out Trick Williams And Carmelo Hayes", "https://example.test/c2", "Baron Corbin returned on SmackDown and took out Trick Williams and Carmelo Hayes.")
    c = item("Rhea Ripley Confronts Iyo Sky During WWE SmackDown", "https://example.test/rhea")
    clusters = massy.suspicious_duplicate_clusters([a, b, c])
    assert len(clusters) == 1
    assert clusters[0]["scope"] == "same_run"
    assert {r["url"] for r in clusters[0]["records"]} == {a["url"], b["url"]}


def test_same_run_duplicate_uses_one_gemini_call_and_authorizes_one_winner(monkeypatch, tmp_path):
    patch_cache(monkeypatch, tmp_path)
    calls = []
    lean = item("Baron Corbin Makes WWE Return During 7/10 SmackDown", "https://example.test/c1", "Baron Corbin returned on SmackDown.")
    rich = item("Baron Corbin Returns On WWE SmackDown, Takes Out Trick Williams And Carmelo Hayes", "https://example.test/c2", "Baron Corbin returned on SmackDown and took out Trick Williams and Carmelo Hayes after the segment.")
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: calls.append(1) or ({"decision": "DUPLICATE", "reason": "same return segment"}, "gemini-3.1-flash-lite"))
    r = result([lean, rich])

    menzo.apply_same_story_duplicate_guard(r, {"suspicious_story_clusters": [{"records": [lean, rich], "deterministic_duplicate_score": 0.9}]})

    assert len(calls) == 1
    assert len(r["selected"]) == 1
    assert r["selected"][0]["url"] == rich["url"]
    assert r["selected"][0]["menzo_authorized"] is True
    assert r["skipped"][0]["reason"] == "skip:duplicate_same_run"
    assert r["skipped"][0]["menzo_authorized"] is False
    assert r["postprocess"]["menzo_duplicates_blocked_same_run"] == 1


def test_same_run_distinct_reaction_allows_both_after_gemini(monkeypatch, tmp_path):
    patch_cache(monkeypatch, tmp_path)
    calls = []
    factual = item("Baron Corbin Returns On SmackDown", "https://example.test/return")
    reaction = item("Fans React Negatively To Baron Corbin's SmackDown Return", "https://example.test/reaction")
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: calls.append(1) or ({"decision": "DISTINCT", "reason": "reaction is a separate editorial story"}, "gemini-3.1-flash-lite"))
    r = result([factual, reaction])

    menzo.apply_same_story_duplicate_guard(r, {"suspicious_story_clusters": [{"records": [factual, reaction], "deterministic_duplicate_score": 0.8}]})

    assert len(calls) == 1
    assert len(r["selected"]) == 2
    assert all(x["menzo_authorized"] is True for x in r["selected"])
    assert r["postprocess"]["menzo_distinct_stories_allowed"] == 2


def test_same_run_gemini_failure_authorizes_at_most_one(monkeypatch, tmp_path):
    patch_cache(monkeypatch, tmp_path)
    a = item("Seth Rollins Returns On Raw", "https://example.test/seth-a")
    b = item("Rollins Makes WWE Comeback During Raw", "https://example.test/seth-b")
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (None, "timeout"))
    r = result([a, b])

    menzo.apply_same_story_duplicate_guard(r, {"suspicious_story_clusters": [{"records": [a, b], "deterministic_duplicate_score": 0.8}]})

    assert len(r["selected"]) <= 1
    assert r["skipped"][0]["reason"] == "skip:duplicate_arbitration_unresolved"
    assert r["postprocess"]["menzo_duplicate_arbitration_fail_closed"] == 1


def test_cross_run_duplicate_blocks_later_candidate(monkeypatch, tmp_path):
    patch_cache(monkeypatch, tmp_path)
    old = item("CM Punk’s SummerSlam Undisputed Title Match Booked During 7/10 WWE SmackDown", "https://old.test/punk", "CM Punk vs Cody Rhodes was booked for SummerSlam.")
    old["published_at"] = datetime.now(timezone.utc).isoformat()
    old["wp_link"] = "https://openwrestling.tv/punk"
    new = item("CM Punk's WWE Title Challenger For SummerSlam 2026 Officially Revealed On SmackDown", "https://new.test/punk", "Cody Rhodes was officially revealed as CM Punk's SummerSlam WWE title challenger on SmackDown.")
    calls = []
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [old])
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: calls.append(1) or ({"decision": "DUPLICATE", "new_fact": "", "reason": "same Punk vs Cody announcement"}, "gemini-3.1-flash-lite"))
    r = result([new])

    menzo.apply_recent_published_duplicate_guard(r)

    assert len(calls) == 1
    assert r["selected"] == []
    assert r["skipped"][0]["reason"] == "skip:duplicate_recently_published"
    assert r["skipped"][0]["menzo_authorized"] is False
    assert r["postprocess"]["menzo_duplicates_blocked_recent_history"] == 1


def test_cross_run_real_update_authorized_with_new_fact(monkeypatch, tmp_path):
    patch_cache(monkeypatch, tmp_path)
    prior = item("CM Punk vs Cody Rhodes reportedly planned for SummerSlam", "https://old.test/rumor", "CM Punk vs Cody Rhodes was reportedly planned for SummerSlam.")
    prior["published_at"] = datetime.now(timezone.utc).isoformat()
    later = item("WWE officially announced CM Punk vs Cody Rhodes for SummerSlam", "https://new.test/official", "WWE officially announced CM Punk vs Cody Rhodes for SummerSlam.")
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [prior])
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: ({"decision": "REAL_UPDATE", "new_fact": "WWE officially announced the match.", "reason": "rumor became official"}, "gemini-3.1-flash-lite"))
    r = result([later])

    menzo.apply_recent_published_duplicate_guard(r)

    assert len(r["selected"]) == 1
    assert r["selected"][0]["menzo_duplicate_decision"] == "REAL_UPDATE"
    assert r["selected"][0]["menzo_new_fact"] == "WWE officially announced the match."
    assert r["postprocess"]["menzo_real_updates_allowed"] == 1


def test_cross_run_more_details_duplicate_blocked(monkeypatch, tmp_path):
    patch_cache(monkeypatch, tmp_path)
    old = item("CM Punk vs Cody Rhodes announced for SummerSlam", "https://old.test/punk", "CM Punk vs Cody Rhodes announced for SummerSlam.")
    old["published_at"] = datetime.now(timezone.utc).isoformat()
    later = item("More Details On CM Punk vs Cody Rhodes At SummerSlam", "https://new.test/punk", "More background and quotes about CM Punk vs Cody Rhodes at SummerSlam.")
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [old])
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: ({"decision": "DUPLICATE", "new_fact": "", "reason": "more details only"}, "gemini-3.1-flash-lite"))
    r = result([later])

    menzo.apply_recent_published_duplicate_guard(r)

    assert r["selected"] == []
    assert r["skipped"][0]["reason"] == "skip:duplicate_recently_published"


def test_cross_run_gemini_failure_blocks_or_pending(monkeypatch, tmp_path):
    patch_cache(monkeypatch, tmp_path)
    old = item("CM Punk vs Cody Rhodes announced for SummerSlam", "https://old.test/punk")
    old["published_at"] = datetime.now(timezone.utc).isoformat()
    later = item("CM Punk vs Cody Rhodes SummerSlam Match Update", "https://new.test/punk")
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [old])
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (None, "timeout"))
    r = result([later])

    menzo.apply_recent_published_duplicate_guard(r)

    assert r["selected"] == []
    assert r["skipped"][0]["reason"] == "skip:duplicate_arbitration_unresolved"
    assert r["postprocess"]["menzo_duplicate_arbitration_fail_closed"] == 1


def test_invalid_same_run_ai_result_not_cached(monkeypatch, tmp_path):
    patch_cache(monkeypatch, tmp_path)
    a = item("CM Punk Discusses SummerSlam Match With Cody Rhodes", "https://new.test/a")
    b = item("CM Punk Talks About Cody Rhodes SummerSlam Title Match", "https://new.test/b")
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: ({"decision": "SAME_STORY_DUPLICATE"}, "gemini-3.1-flash-lite"))
    r = result([a, b])

    menzo.apply_same_story_duplicate_guard(r, {"suspicious_story_clusters": [{"records": [a, b], "deterministic_duplicate_score": 0.8}]})

    assert len(r["selected"]) <= 1
    assert not (tmp_path / "cache.json").exists()


def test_publisher_enforces_unauthorized_and_allows_authorized(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(publisher, "DRY_RUN", True)
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "test"))
    monkeypatch.setattr(publisher, "publish_article", lambda article, history, wp_ok: calls.append(article) or {"status": "dry_run", "source_url": article.get("source_url")})
    monkeypatch.setattr(publisher, "PUBLISHER_HISTORY_FILE", tmp_path / "publisher_history.json")
    monkeypatch.setattr(publisher, "ARTIFACT_PUBLISHER_FILE", tmp_path / "publisher_result.json")
    monkeypatch.setattr(publisher, "PUBLISHER_STATUS_FILE", tmp_path / "publisher_status.json")
    blocked = {"title_it": "Blocked", "source_url": "https://example.test/blocked", "menzo_duplicate_checked": True, "menzo_authorized": False, "menzo_duplicate_reason": "skip:duplicate_recently_published"}
    winner = {"title_it": "Winner", "source_url": "https://example.test/winner", "menzo_duplicate_checked": True, "menzo_authorized": True, "menzo_duplicate_decision": "DUPLICATE"}
    update = {"title_it": "Update", "source_url": "https://example.test/update", "menzo_duplicate_checked": True, "menzo_authorized": True, "menzo_duplicate_decision": "REAL_UPDATE", "menzo_new_fact": "Official announcement"}

    out = publisher.run_publisher({"approved_articles": [blocked, winner, update]})

    assert [x["source_url"] for x in calls] == [winner["source_url"], update["source_url"]]
    assert any(r.get("reason") == "skip:duplicate_recently_published" for r in out["results"])
    assert out["handoff"]["publisher_unauthorized_duplicate_blocks"] == 1


def test_normal_unrelated_article_no_duplicate_gemini(monkeypatch):
    calls = []
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [])
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: calls.append(1) or ({"decision": "DUPLICATE"}, "gemini"))
    r = result([item("Rhea Ripley Confronts Iyo Sky During SmackDown", "https://example.test/rhea")])

    menzo.apply_same_story_duplicate_guard(r, {"suspicious_story_clusters": []})
    menzo.apply_recent_published_duplicate_guard(r)

    assert len(r["selected"]) == 1
    assert calls == []
