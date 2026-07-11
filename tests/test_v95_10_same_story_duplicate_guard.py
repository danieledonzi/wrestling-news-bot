import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import menzo_policy_v93_15 as menzo
from agents import publisher


def item(title, url, summary="", *, section="selected", score=90):
    return {
        "title": title,
        "source_title": title,
        "url": url,
        "source_url": url,
        "summary": summary or title,
        "body_html": "<p>" + (summary or title) + "</p>",
        "source": "Example",
        "score": score,
        "ai_priority_label": "high",
        "decision": section,
        "priority": "hard" if section == "selected" else "soft",
    }


def result(items):
    return {"selected": [x for x in items if x.get("decision") == "selected"], "pending": [x for x in items if x.get("decision") == "pending"], "skipped": [], "postprocess": {}}


def test_same_run_duplicate_keeps_a_discards_b_leaves_c_metadata_free(monkeypatch):
    calls = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: calls.append(k.get("phase")) or ({"duplicate_groups": [{"keep_id": "c0", "discard_ids": ["c1"], "reason": "same announcement"}]}, "gemini-3.1-flash-lite"))
    r = result([item("A", "https://e.test/a"), item("B", "https://e.test/b"), item("C", "https://e.test/c")])
    menzo.apply_same_story_duplicate_guard(r, {"suspicious_story_clusters": [{"records": [{}, {}]}] * 12})
    assert [x["source_url"] for x in r["selected"]] == ["https://e.test/a", "https://e.test/c"]
    assert r["skipped"][0]["source_url"] == "https://e.test/b"
    assert r["skipped"][0]["reason"] == "skip:duplicate_same_run"
    assert r["selected"][0]["menzo_winner_url"] == "https://e.test/a"
    assert not any(k.startswith("menzo_duplicate") or k == "menzo_authorized" for k in r["selected"][1])
    assert calls == ["duplicate_arbitration_same_run_batch"]
    assert r["postprocess"]["menzo_same_run_batch_calls"] == 1


def test_no_same_run_duplicates_leaves_all_candidates_metadata_free(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: ({"duplicate_groups": []}, "gemini-3.1-flash-lite"))
    r = result([item("A", "https://e.test/a"), item("B", "https://e.test/b")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert [x["source_url"] for x in r["selected"]] == ["https://e.test/a", "https://e.test/b"]
    assert all("menzo_duplicate_checked" not in x for x in r["selected"])


def test_old_same_run_response_shape_repaired_before_any_apply(monkeypatch):
    calls = []
    def fake(*a, **k):
        calls.append(k.get("phase"))
        if len(calls) == 1:
            return {"decision": "DUPLICATE", "reason": "legacy"}, "gemini-3.1-flash-lite"
        return {"duplicate_groups": []}, "gemini-3.1-flash-lite"
    monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
    r = result([item("A", "https://e.test/a"), item("B", "https://e.test/b")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert r["skipped"] == []
    assert all("menzo_duplicate_checked" not in x for x in r["selected"])
    assert calls == ["duplicate_arbitration_same_run_batch", "duplicate_arbitration_same_run_repair"]


def test_recent_history_duplicate_material_update_and_no_match(monkeypatch):
    history = [item("Old duplicate", "https://old.test/dup"), item("Rumored Punk match", "https://old.test/update", "CM Punk vs Cody Rhodes was rumored for SummerSlam.")]
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda *a, **k: history)
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: ({"matches": [
        {"current_id": "c0", "published_id": "p0", "decision": "DUPLICATE", "reason": "same fact"},
        {"current_id": "c1", "published_id": "p1", "decision": "MATERIAL_UPDATE", "new_fact": "WWE officially announced CM Punk vs Cody Rhodes match.", "reason": "rumor official"},
    ]}, "gemini-3.1-flash-lite"))
    r = result([
        item("Duplicate", "https://new.test/dup"),
        item("Official Punk match", "https://new.test/update", "WWE officially announced CM Punk vs Cody Rhodes match for SummerSlam."),
        item("Ordinary", "https://new.test/ordinary"),
    ])
    menzo.apply_recent_published_duplicate_guard(r)
    assert [x["source_url"] for x in r["selected"]] == ["https://new.test/update", "https://new.test/ordinary"]
    assert r["selected"][0]["menzo_duplicate_decision"] == "REAL_UPDATE"
    assert r["selected"][0]["menzo_compared_with_url"] == "https://old.test/update"
    assert "menzo_duplicate_checked" not in r["selected"][1]
    assert r["skipped"][0]["reason"] == "skip:duplicate_recently_published"


def test_old_recent_history_response_shape_repaired_before_any_apply(monkeypatch):
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda *a, **k: [item("Old", "https://old.test/a")])
    calls = []
    def fake(*a, **k):
        calls.append(k.get("phase"))
        if len(calls) == 1:
            return {"decision": "DUPLICATE", "reason": "legacy"}, "gemini-3.1-flash-lite"
        return {"matches": []}, "gemini-3.1-flash-lite"
    monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
    r = result([item("A", "https://new.test/a")])
    menzo.apply_recent_published_duplicate_guard(r)
    assert r["skipped"] == []
    assert "menzo_duplicate_checked" not in r["selected"][0]
    assert calls == ["duplicate_arbitration_recent_history_batch", "duplicate_arbitration_recent_history_repair"]


def test_publisher_blocks_malformed_and_allows_complete_shapes(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(publisher, "DRY_RUN", True)
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "test"))
    monkeypatch.setattr(publisher, "publish_article", lambda article, history, wp_ok: calls.append(article) or {"status": "dry_run", "source_url": article.get("source_url")})
    monkeypatch.setattr(publisher, "PUBLISHER_HISTORY_FILE", tmp_path / "publisher_history.json")
    monkeypatch.setattr(publisher, "ARTIFACT_PUBLISHER_FILE", tmp_path / "publisher_result.json")
    monkeypatch.setattr(publisher, "PUBLISHER_STATUS_FILE", tmp_path / "publisher_status.json")
    winner = {"title_it": "Winner", "source_url": "https://e.test/winner", "menzo_duplicate_checked": True, "menzo_duplicate_scope": "same_run", "menzo_duplicate_decision": "DUPLICATE", "menzo_authorized": True, "menzo_winner_url": "https://e.test/winner"}
    update = {"title_it": "Update", "source_url": "https://e.test/update", "menzo_duplicate_checked": True, "menzo_duplicate_scope": "recent_history", "menzo_duplicate_decision": "REAL_UPDATE", "menzo_authorized": True, "menzo_new_fact": "WWE officially announced the match.", "menzo_compared_with_url": "https://old.test/update"}
    malformed = {"title_it": "Bad", "source_url": "https://e.test/bad", "menzo_duplicate_checked": True, "menzo_duplicate_scope": "recent_history", "menzo_duplicate_decision": "REAL_UPDATE", "menzo_authorized": True, "menzo_new_fact": "WWE officially announced the match."}
    ordinary = {"title_it": "Ordinary", "source_url": "https://e.test/ordinary"}
    out = publisher.run_publisher({"approved_articles": [winner, update, malformed, ordinary]})
    assert [x["source_url"] for x in calls] == ["https://e.test/winner", "https://e.test/update", "https://e.test/ordinary"]
    assert any(x.get("source_url") == "https://e.test/bad" and x.get("reason") == "skip:duplicate_arbitration_unresolved" for x in out["results"])


def test_single_unrelated_article_avoids_duplicate_gemini(monkeypatch):
    calls = []
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda *a, **k: [])
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: calls.append(1) or ({"duplicate_groups": []}, "gemini-3.1-flash-lite"))
    r = result([item("Unrelated", "https://e.test/one")])
    menzo.apply_same_story_duplicate_guard(r, {})
    menzo.apply_recent_published_duplicate_guard(r)
    assert len(r["selected"]) == 1
    assert calls == []
