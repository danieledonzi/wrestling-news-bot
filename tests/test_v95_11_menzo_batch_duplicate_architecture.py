import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import alfred, alfred_policy_v93_20, bob, publisher
from agents import andrea_policy_v94_15 as andrea
from agents import menzo_policy_v93_15 as menzo


def item(url, title, summary=None, section="selected", score=90):
    summary = summary or title
    return {"url": url, "source_url": url, "title": title, "source_title": title, "source": "Test", "summary": summary, "description": summary, "body_html": "<p>" + summary + "</p>", "score": score, "decision": section, "priority": "hard" if section == "selected" else "soft", "ai_priority_label": "high"}


def result(items):
    return {"selected": [x for x in items if x["decision"] == "selected"], "pending": [x for x in items if x["decision"] == "pending"], "skipped": [], "postprocess": {}}


def test_runtime_order_has_one_budget_after_duplicate_guards(monkeypatch):
    order = []
    base = {"selected": [], "pending": [], "skipped": [], "postprocess": {}, "policy": {}}
    monkeypatch.setattr(menzo, "_wp_ready_for_costly_work", lambda: (True, "ok"))
    monkeypatch.setattr(menzo.base, "run_menzo", lambda board: dict(base))
    monkeypatch.setattr(menzo, "normalize_ai_fields", lambda r: None)
    monkeypatch.setattr(menzo, "rebuild_decisions", lambda r: None)
    for name in ["apply_betting_odds_policy", "apply_source_opinion_policy", "apply_medical_brand_policy", "apply_story_footprint_policy", "enforce_ai_skip_binding", "apply_generalized_fingerprint_policy"]:
        monkeypatch.setattr(menzo, name, lambda r, _name=name: order.append(_name))
    for name in ["apply_softpool_decay", "apply_same_story_duplicate_guard", "apply_recent_published_duplicate_guard", "apply_dynamic_editorial_budget", "enforce_selected_cap", "enforce_capacity_buffer", "enforce_final_menzo_duplicate_authorization"]:
        monkeypatch.setattr(menzo, name, lambda *a, _name=name, **k: order.append(_name))
    monkeypatch.setattr(menzo, "save_softpool", lambda r: None)
    monkeypatch.setattr(menzo, "save_hard_skips", lambda r: None)
    monkeypatch.setattr(menzo, "remember_stories", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_footprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_fingerprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "write_json", lambda *a, **k: None)
    menzo.run_menzo({})
    required = ["apply_softpool_decay", "apply_same_story_duplicate_guard", "apply_recent_published_duplicate_guard", "apply_dynamic_editorial_budget", "enforce_selected_cap", "enforce_capacity_buffer", "enforce_final_menzo_duplicate_authorization"]
    assert [x for x in order if x in required] == required
    assert order.count("apply_dynamic_editorial_budget") == 1


def test_same_run_ab_duplicate_c_distinct_one_batch_and_massy_ignored(monkeypatch):
    calls=[]
    def fake(prompt, model, **k):
        calls.append((prompt, k.get("phase"), model))
        return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same story"}]}, model
    monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
    r=result([item("https://t/A","A"), item("https://t/B","B"), item("https://t/C","C")])
    menzo.apply_same_story_duplicate_guard(r, {"suspicious_story_clusters":[{"records":[{}]}]*12})
    assert [x["url"] for x in r["selected"]] == ["https://t/A", "https://t/C"]
    assert r["skipped"][0]["url"] == "https://t/B"
    assert "menzo_duplicate_checked" not in r["selected"][1]
    assert len(calls) == 1 and calls[0][1] == "duplicate_arbitration_same_run_batch" and "https://t/C" in calls[0][0]


def test_no_same_run_duplicates_and_two_independent_groups(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: ({"duplicate_groups": []}, "gemini-3.1-flash-lite"))
    r=result([item("https://t/A","A"), item("https://t/B","B")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert len(r["selected"]) == 2 and all("menzo_duplicate_checked" not in x for x in r["selected"])
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: ({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"one"},{"keep_id":"c2","discard_ids":["c3"],"reason":"two"}]}, "gemini-3.1-flash-lite"))
    r=result([item("https://t/A","A"), item("https://t/B","B"), item("https://t/C","C"), item("https://t/D","D")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert [x["url"] for x in r["selected"]] == ["https://t/A", "https://t/C"]
    assert {x["url"] for x in r["skipped"]} == {"https://t/B", "https://t/D"}


def test_malformed_batch_repair_and_legacy_shape_never_applied(monkeypatch):
    calls=[]
    def fake(*a, **k):
        calls.append(k.get("phase"))
        if len(calls) == 1:
            return {"decision":"DUPLICATE"}, "gemini-3.1-flash-lite"
        return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"fixed"}]}, "gemini-3.1-flash-lite"
    monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
    r=result([item("https://t/A","A"), item("https://t/B","B"), item("https://t/C","C")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert [x["url"] for x in r["selected"]] == ["https://t/A", "https://t/C"]
    assert calls == ["duplicate_arbitration_same_run_batch", "duplicate_arbitration_same_run_repair"]


def test_same_run_micro_survivor_wins_current_wins_invalids_and_failure(monkeypatch):
    # both batch attempts invalid; survivor wins over B; C replaces A; D compares only against C; E invalid fail-closes
    responses = [({"bad": True}, "gemini-3.1-flash-lite"), ({"bad": True}, "gemini-3.1-flash-lite"),
                 ({"decision":"DUPLICATE_OF", "matched_id":"c0", "keep_id":"c0", "reason":"A better"}, "gemini-3.1-flash-lite"),
                 ({"decision":"DUPLICATE_OF", "matched_id":"c0", "keep_id":"c2", "reason":"C better"}, "gemini-3.1-flash-lite"),
                 ({"decision":"NO_DUPLICATE"}, "gemini-3.1-flash-lite"),
                 ({"decision":"DUPLICATE_OF", "matched_id":"c0", "keep_id":"c0", "reason":"discarded survivor invalid"}, "gemini-3.1-flash-lite")]
    prompts=[]
    def fake(prompt, model, **k):
        prompts.append((k.get("phase"), prompt))
        return responses.pop(0)
    monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
    r=result([item("https://t/A","A"), item("https://t/B","B"), item("https://t/C","C"), item("https://t/D","D"), item("https://t/E","E")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert [x["url"] for x in r["selected"]] == ["https://t/C", "https://t/D"]
    assert {x["url"] for x in r["skipped"]} == {"https://t/B", "https://t/A", "https://t/E"}
    assert r["postprocess"]["menzo_duplicate_arbitration_fail_closed"] == 1
    d_prompt = [p for phase,p in prompts if phase == "duplicate_arbitration_same_run_micro"][2]
    assert '"id": "c0"' not in d_prompt and '"id": "c2"' in d_prompt


def test_same_run_micro_invalid_matched_keep_missing_and_unresolved_only_current(monkeypatch):
    for bad_response in [
        {"decision":"DUPLICATE_OF", "matched_id":"future", "keep_id":"future", "reason":"bad"},
        {"decision":"DUPLICATE_OF", "matched_id":"c0", "keep_id":"c9", "reason":"bad"},
        {"decision":"DUPLICATE_OF", "keep_id":"c0", "reason":"bad"},
        None,
    ]:
        responses=[({"bad": True}, "gemini-3.1-flash-lite"), ({"bad": True}, "gemini-3.1-flash-lite"), (bad_response, "gemini-3.1-flash-lite")]
        monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: responses.pop(0))
        r=result([item("https://t/A","A"), item("https://t/B","B")])
        menzo.apply_same_story_duplicate_guard(r, {})
        assert [x["url"] for x in r["selected"]] == ["https://t/A"]
        assert r["skipped"][0]["url"] == "https://t/B"
        assert r["skipped"][0]["reason"] == "skip:duplicate_arbitration_unresolved"


def test_recent_history_batch_duplicate_update_no_match_and_one_call(monkeypatch):
    history=[item("https://old/dup","old dup"), item("https://old/upd","old rumor", "CM Punk match was rumored.")]
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda *a, **k: history)
    calls=[]
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: calls.append(k.get("phase")) or ({"matches":[{"current_id":"c0","published_id":"p0","decision":"DUPLICATE","reason":"same"},{"current_id":"c1","published_id":"p1","decision":"MATERIAL_UPDATE","new_fact":"WWE officially announced CM Punk match.","reason":"official"}]}, "gemini-3.1-flash-lite"))
    r=result([item("https://new/dup","dup"), item("https://new/upd","WWE officially announced CM Punk match.", "WWE officially announced CM Punk match."), item("https://new/o","ordinary")])
    menzo.apply_recent_published_duplicate_guard(r)
    assert [x["url"] for x in r["selected"]] == ["https://new/upd", "https://new/o"]
    assert r["selected"][0]["menzo_duplicate_decision"] == "REAL_UPDATE"
    assert "menzo_duplicate_checked" not in r["selected"][1]
    assert calls == ["duplicate_arbitration_recent_history_batch"]


def test_recent_history_micro_requires_explicit_valid_published_id(monkeypatch):
    history=[item("https://old/a","old", "Old match was rumored.")]
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda *a, **k: history)
    for resp in [{"decision":"DUPLICATE", "reason":"missing"}, {"decision":"DUPLICATE", "published_id":"p9", "reason":"unknown"}]:
        responses=[({"bad": True}, "gemini-3.1-flash-lite"), ({"bad": True}, "gemini-3.1-flash-lite"), (resp, "gemini-3.1-flash-lite")]
        monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: responses.pop(0))
        r=result([item("https://new/a","new")])
        menzo.apply_recent_published_duplicate_guard(r)
        assert r["selected"] == [] and r["skipped"][0]["reason"] == "skip:duplicate_arbitration_unresolved"
    responses=[({"bad": True}, "gemini-3.1-flash-lite"), ({"bad": True}, "gemini-3.1-flash-lite"), ({"decision":"DUPLICATE", "published_id":"p0", "reason":"same"}, "gemini-3.1-flash-lite")]
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: responses.pop(0))
    r=result([item("https://new/a","new")])
    menzo.apply_recent_published_duplicate_guard(r)
    assert r["selected"] == [] and r["skipped"][0]["reason"] == "skip:duplicate_recently_published"


def test_grounded_material_update_validation(monkeypatch):
    old = {"id":"p0", "title":"Old", "summary":"CM Punk match was rumored.", "body_excerpt":"CM Punk match was rumored."}
    current = {"id":"c0", "title":"Official", "summary":"WWE officially announced CM Punk match.", "body_excerpt":"WWE officially announced CM Punk match."}
    assert not menzo.material_update_is_grounded("several additional details", current, old)
    assert not menzo.material_update_is_grounded("WWE officially changed the match opponent.", current, old)
    assert not menzo.material_update_is_grounded("CM Punk match was rumored.", current, old)
    assert menzo.material_update_is_grounded("WWE officially announced CM Punk match.", current, old)


def test_call_counters_actual_calls_missing_key_and_cooldown(monkeypatch):
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda *a, **k: [])
    for status, expected_calls, expected_avoided in [("gemini-3.1-flash-lite", 1, 0), ("missing_api_key", 0, 1), ("model_cooldown_after_failure:gemini-3.1-flash-lite", 0, 1)]:
        monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, _status=status, **k: ({"duplicate_groups": []}, _status))
        r=result([item("https://t/A","A"), item("https://t/B","B")])
        menzo.apply_same_story_duplicate_guard(r, {})
        assert r["postprocess"]["menzo_same_run_batch_calls"] == expected_calls
        assert r["postprocess"]["menzo_same_run_batch_calls_avoided"] == expected_avoided
        assert r["postprocess"]["gemini_calls_used_for_duplicate_arbitration"] == expected_calls


def test_final_allowed_urls_only_valid_selected(monkeypatch):
    good = item("https://t/good", "Good")
    ordinary = item("https://t/ordinary", "Ordinary")
    bad = item("https://t/bad", "Bad")
    menzo.mark_menzo_duplicate(good, checked=True, scope="same_run", decision="DUPLICATE", authorized=True, winner=good)
    bad.update({"menzo_duplicate_checked": True, "menzo_duplicate_scope": "same_run", "menzo_duplicate_decision": "DUPLICATE", "menzo_authorized": True, "menzo_winner_url": "https://t/other"})
    r=result([good, ordinary, bad])
    menzo.enforce_final_menzo_duplicate_authorization(r)
    assert r["allowed_urls_for_v92"] == ["https://t/good", "https://t/ordinary"]
    assert r["skipped"][0]["url"] == "https://t/bad"


def test_metadata_propagation_actual_andrea_bob_alfred_publisher(monkeypatch, tmp_path):
    src = item("https://t/win", "Winner", "Questo articolo contiene informazioni editoriali complete e verificate sulla notizia principale. " * 8)
    menzo.mark_menzo_duplicate(src, checked=True, scope="same_run", decision="DUPLICATE", authorized=True, winner=src, reason="same")
    menzo_out = {"version":"test", "selected":[src], "pending":[], "skipped":[], "handoff":{}}
    andrea_out = andrea.run_andrea(menzo_out)
    assert andrea_out["selected"][0]["menzo_duplicate_scope"] == "same_run"
    monkeypatch.setattr(bob, "fetch_html", lambda url: "<html><head><title>Winner</title></head><body><article><p>" + ("Questo articolo contiene informazioni editoriali complete e verificate sulla notizia principale. " * 8) + "</p></article></body></html>")
    monkeypatch.setattr(bob, "call_gemini", lambda *a, **k: (json.dumps({"title_it":"Titolo italiano valido completo", "excerpt_it":"Estratto completo", "translations":{"u0":"Questo articolo contiene informazioni editoriali complete e verificate sulla notizia principale. " * 8}, "notes":[]}), "gemini-test", ["gemini-test"]))
    package = bob.article_package(andrea_out["selected"][0])
    assert package["menzo_duplicate_decision"] == "DUPLICATE"
    review = alfred.review_article(package)
    assert review["approved_article"]["menzo_duplicate_scope"] == "same_run"
    wrapped = alfred_policy_v93_20._approved_article_from_source({"title_it":"Titolo italiano valido completo"}, package)
    assert wrapped["menzo_winner_url"] == "https://t/win"
    calls=[]
    monkeypatch.setattr(publisher, "DRY_RUN", True)
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "test"))
    monkeypatch.setattr(publisher, "publish_article", lambda article, history, wp_ok: calls.append(article) or {"status":"dry_run", "source_url": article.get("source_url")})
    monkeypatch.setattr(publisher, "PUBLISHER_HISTORY_FILE", tmp_path / "publisher_history.json")
    monkeypatch.setattr(publisher, "ARTIFACT_PUBLISHER_FILE", tmp_path / "publisher_result.json")
    monkeypatch.setattr(publisher, "PUBLISHER_STATUS_FILE", tmp_path / "publisher_status.json")
    malformed = {"title_it":"Bad", "source_url":"https://t/bad", "menzo_duplicate_checked": True, "menzo_duplicate_scope":"same_run", "menzo_duplicate_decision":"DUPLICATE", "menzo_authorized": True, "menzo_winner_url":"https://t/other"}
    out = publisher.run_publisher({"approved_articles":[wrapped, malformed]})
    assert [x["source_url"] for x in calls] == ["https://t/win"]
    assert any(x.get("source_url") == "https://t/bad" and x.get("reason") == "skip:duplicate_arbitration_unresolved" for x in out["results"])
