import pytest
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import menzo_duplicate_cache as cache
from agents import menzo_policy_v93_15 as menzo


def article(url, title, score=90):
    return {"url": url, "source_url": url, "title": title, "source": "Test", "summary": title,
            "score": score, "decision": "selected", "priority": "hard"}


def result(items):
    return {"selected": items, "pending": [], "skipped": [], "postprocess": {}}


def test_canonical_material_is_order_and_noise_independent():
    a = menzo.compact_candidate_record(article("https://x/a?utm=1", "  A   fact ", 1), "c0")
    b = menzo.compact_candidate_record(article("https://x/a?utm=1", "A fact", 999), "c9")
    assert cache.candidate_material_hash(a) == cache.candidate_material_hash(b)
    assert cache.actionable_snapshot_hash([("b", "2"), ("a", "1")]) == cache.actionable_snapshot_hash([("a", "1"), ("b", "2")])


def test_identical_run_rehydrates_and_order_is_independent(monkeypatch, tmp_path):
    path = tmp_path / "cache.json"
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE", path)
    calls = []
    def gemini(*args, **kwargs):
        calls.append(kwargs.get("phase"))
        return {"duplicate_groups": [{"keep_id": "c0", "discard_ids": ["c1"], "reason": "same fact"}]}, menzo.DUPLICATE_BATCH_MODEL
    monkeypatch.setattr(menzo, "call_gemini_json_model", gemini)
    first = result([article("https://x/a", "A fact"), article("https://x/b", "B report")])
    menzo.apply_same_story_duplicate_guard(first, {})
    assert len(calls) == 1 and first["selected"][0]["menzo_authorized"] is True
    second = result([article("https://x/b", "B report"), article("https://x/a", "A fact")])
    menzo.apply_same_story_duplicate_guard(second, {})
    assert len(calls) == 1
    assert second["selected"][0]["url"] == "https://x/a"
    assert second["selected"][0]["menzo_winner_url"] == "https://x/a"
    assert second["skipped"][0]["menzo_authorized"] is False
    assert second["postprocess"]["gemini_duplicate_calls_executed"] == 0


def test_corruption_missing_and_atomic_write(tmp_path):
    path = tmp_path / "cache.json"
    assert cache.load_cache(path)["load_status"] == "missing"
    path.write_text("{broken", encoding="utf-8")
    assert cache.load_cache(path, warn=lambda _: None)["load_status"] == "malformed"
    value = cache.empty_cache(); cache.atomic_write(value, path)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == cache.CACHE_SCHEMA_VERSION
    assert not list(tmp_path.glob("*.tmp"))


def test_failure_cooldown_is_request_specific(monkeypatch):
    value = cache.empty_cache(); key = cache.request_key("same_run", [("a", "one")])
    cache.record_failure(value, key, "api")
    assert cache.failure_in_cooldown(value, key)
    assert not cache.failure_in_cooldown(value, cache.request_key("same_run", [("a", "changed")]))


def test_incomplete_decision_is_not_valid():
    value = cache.empty_cache()
    assert not cache.store(value, "key", "same_run", {"a": {"menzo_duplicate_checked": True}})
    assert value["entries"] == {}


def complete_decision():
    value={field: (True if field in {"menzo_duplicate_checked", "menzo_authorized"} else "") for field in cache.REQUIRED_DECISION_FIELDS}
    value["disposition"]={field:"" for field in cache.REQUIRED_DISPOSITION_FIELDS}
    return value


def test_explicit_no_match_and_completeness_validation():
    value=cache.empty_cache(); pairs=[("https://x/a","hash-a")]; key=cache.request_key("recent_history",pairs,"history")
    assert cache.store(value,key,"recent_history",{},candidates=pairs,comparisons="history",actual_request_count=1)
    assert cache.lookup(value,key,candidates=pairs,comparisons="history")["outcome"] == "validated_no_matches"
    broken=dict(value["entries"][key]); broken.pop("outcome"); value["entries"][key]=broken
    assert cache.lookup(value,key,candidates=pairs,comparisons="history") is None
    value["entries"][key]={"contract_fingerprint":cache.contract_fingerprint(),"decisions":{}}
    assert cache.lookup(value,key,candidates=pairs,comparisons="history") is None
    assert cache.lookup(value,key,candidates=[("https://x/b","hash-a")],comparisons="history") is None


def test_partial_decision_and_missing_evaluated_candidate_rejected():
    value=cache.empty_cache(); pairs=[("a","one"),("b","two")]; key=cache.request_key("same",pairs)
    assert cache.store(value,key,"same",{"a":complete_decision()},candidates=pairs,actual_request_count=2)
    value["entries"][key]["decisions"]["a"].pop("menzo_winner_url")
    assert cache.lookup(value,key,candidates=pairs,comparisons="") is None
    value["entries"][key]["decisions"]["a"]=complete_decision(); value["entries"][key]["evaluated_candidate_ids"]=["a"]
    assert cache.lookup(value,key,candidates=pairs,comparisons="") is None


def test_new_candidate_delta_excludes_cached_loser(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    prompts=[]
    def fake(prompt,model,**kwargs):
        prompts.append(prompt)
        if len(prompts)==1: return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]},model
        return {"duplicate_groups":[]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    menzo.apply_same_story_duplicate_guard(result([article("https://x/winner","CM Punk signs WWE deal"),article("https://x/loser","CM Punk signs WWE contract")]),{})
    second=result([article("https://x/winner","CM Punk signs WWE deal"),article("https://x/loser","CM Punk signs WWE contract"),article("https://x/new","CM Punk contract officially confirmed")])
    menzo.apply_same_story_duplicate_guard(second,{})
    assert len(prompts)==2 and "https://x/loser" not in prompts[1]
    assert "https://x/winner" in prompts[1] and "https://x/new" in prompts[1]
    assert any(x["url"]=="https://x/loser" and x["menzo_authorized"] is False for x in second["skipped"])


def test_recent_history_unrelated_stable_and_relevant_change_is_affected_only(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    current=article("https://new/punk","CM Punk officially signs WWE contract")
    relevant=article("https://old/punk","CM Punk reportedly signs WWE contract")
    history=[relevant]; monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:list(history))
    prompts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: prompts.append(prompt) or ({"matches":[]},model))
    menzo.apply_recent_published_duplicate_guard(result([dict(current)])); assert len(prompts)==1
    history.append(article("https://old/arena","AEW announces a new London arena"))
    menzo.apply_recent_published_duplicate_guard(result([dict(current)])); assert len(prompts)==2 and "https://old/punk" not in prompts[-1]
    history.append(article("https://old/punk-two","CM Punk contract with WWE officially confirmed"))
    menzo.apply_recent_published_duplicate_guard(result([dict(current)])); assert len(prompts)==3
    assert "https://old/arena" not in prompts[-1] and "https://old/punk-two" in prompts[-1]


def test_prompt_retains_score_and_published_at_but_cache_ignores_noise(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); prompts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: prompts.append(prompt) or ({"duplicate_groups":[]},model))
    a=article("https://noise/a","CM Punk contract",7); a["published_at"]="2026-01-01"
    b=article("https://noise/b","AEW arena",8); b["published_at"]="2026-01-02"
    menzo.apply_same_story_duplicate_guard(result([a,b]),{})
    assert '"score": 7' in prompts[0] and '"published_at": "2026-01-01"' in prompts[0]
    a2=article("https://noise/a","CM Punk contract",999); a2["published_at"]="2030-01-01"
    b2=article("https://noise/b","AEW arena",1); b2["published_at"]="2030-01-02"
    menzo.apply_same_story_duplicate_guard(result([a2,b2]),{}); assert len(prompts)==1


def test_delta_ignores_old_only_group(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); n=[0]
    def fake(prompt,model,**k):
        n[0]+=1
        if n[0]==1: return {"duplicate_groups":[]},model
        return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"new relation"},{"keep_id":"c2","discard_ids":["c3"],"reason":"old only"}]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    menzo.apply_same_story_duplicate_guard(result([article("https://old/a","CM Punk WWE contract"),article("https://old/b","CM Punk WWE deal"),article("https://old/d","CM Punk contract report")]),{})
    out=result([article("https://old/a","CM Punk WWE contract"),article("https://old/b","CM Punk WWE deal"),article("https://old/d","CM Punk contract report"),article("https://new/c","CM Punk contract confirmed")]); menzo.apply_same_story_duplicate_guard(out,{})
    # c0 is the changed/new candidate; the old-only c1/c2 group is discarded.
    assert len(out["skipped"])==1 and out["skipped"][0]["url"]=="https://old/a"
    assert any(x["url"]=="https://old/b" for x in out["selected"])


def test_changed_group_members_are_in_delta_and_unrelated_loser_is_not(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); prompts=[]
    def fake(prompt,model,**k):
        prompts.append(prompt)
        if len(prompts)==1: return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]},model
        return {"duplicate_groups":[]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    first=result([article("https://g/rep","CM Punk contract"),article("https://g/loser","CM Punk deal"),article("https://u/standalone","AEW arena")]); menzo.apply_same_story_duplicate_guard(first,{})
    second=result([article("https://g/rep","CM Punk contract changed"),article("https://g/loser","CM Punk deal"),article("https://u/standalone","AEW arena")]); menzo.apply_same_story_duplicate_guard(second,{})
    assert "https://g/rep" in prompts[1] and "https://g/loser" in prompts[1]
    # The unrelated standalone may appear once as the authorized comparison representative, never its loser.
    third=result([article("https://g/rep","CM Punk contract"),article("https://g/loser","CM Punk deal changed"),article("https://u/standalone","AEW arena")]); menzo.apply_same_story_duplicate_guard(third,{})
    assert "https://g/loser" in prompts[2] and "https://g/rep" in prompts[2]


def test_delta_failure_does_not_fail_close_comparison_representative(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); calls=[0]
    def fake(prompt,model,**k):
        calls[0]+=1
        return ({"duplicate_groups":[]} if calls[0]==1 else {"bad":True}),model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    menzo.apply_same_story_duplicate_guard(result([article("https://old/a","CM Punk WWE contract"),article("https://old/b","Roman Reigns WWE return")]),{})
    out=result([article("https://old/a","CM Punk WWE contract"),article("https://old/b","Roman Reigns WWE return"),article("https://new/c","CM Punk WWE contract updated")]); menzo.apply_same_story_duplicate_guard(out,{})
    assert any(x["url"]=="https://old/a" for x in out["selected"]) and any(x["url"]=="https://old/b" for x in out["selected"])
    assert any(x["url"]=="https://new/c" and x["reason"]=="skip:duplicate_arbitration_unresolved" for x in out["skipped"])
    before=calls[0]; cooldown=result([article("https://old/a","CM Punk WWE contract"),article("https://old/b","Roman Reigns WWE return"),article("https://new/c","CM Punk WWE contract updated")]); menzo.apply_same_story_duplicate_guard(cooldown,{})
    assert calls[0]==before and all(x["url"].startswith("https://old/") for x in cooldown["selected"])


def test_disjoint_recent_sets_never_share_prompt_and_group_hit_avoids_once(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    a=article("https://new/punk","CM Punk signs WWE contract"); b=article("https://new/mox","Jon Moxley suffers AEW injury")
    olda=article("https://old/punk","CM Punk WWE contract reported"); oldb=article("https://old/mox","Jon Moxley AEW injury update")
    monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:[olda,oldb]); prompts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: prompts.append(prompt) or ({"matches":[]},model))
    first=result([dict(a),dict(b)]); menzo.apply_recent_published_duplicate_guard(first)
    assert len(prompts)==1 and "https://old/punk" in prompts[0] and "https://old/mox" in prompts[0]
    second=result([dict(a),dict(b)]); menzo.apply_recent_published_duplicate_guard(second)
    assert len(prompts)==1 and second["postprocess"]["gemini_duplicate_calls_avoided"]==0


def test_recent_group_one_batch_avoided_once_and_cooldown_isolated(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    history=[article("https://old/punk","CM Punk WWE contract")]; monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:history)
    candidates=[article(f"https://new/punk-{i}","CM Punk WWE contract") for i in range(3)]; calls=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: calls.append(prompt) or ({"matches":[]},model))
    menzo.apply_recent_published_duplicate_guard(result([dict(x) for x in candidates])); assert len(calls)==1
    again=result([dict(x) for x in candidates]); menzo.apply_recent_published_duplicate_guard(again)
    assert len(calls)==1 and again["postprocess"]["gemini_duplicate_calls_avoided"]==0


def test_recent_history_failure_cooldown_and_material_change_bypass(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    old=article("https://old/punk","CM Punk WWE contract"); monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:[old]); calls=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: calls.append(prompt) or ({"bad":True},model))
    cur=article("https://new/punk","CM Punk WWE contract update")
    menzo.apply_recent_published_duplicate_guard(result([dict(cur)])); first=len(calls); assert first==3
    cooled=result([dict(cur)]); menzo.apply_recent_published_duplicate_guard(cooled)
    assert len(calls)==first and cooled["postprocess"]["duplicate_failure_cooldown_hit"]==1
    old["summary"]="CM Punk WWE contract history materially changed"
    menzo.apply_recent_published_duplicate_guard(result([dict(cur)])); assert len(calls)>first


def test_changed_loser_includes_representative(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); prompts=[]
    def fake(prompt,model,**k):
        prompts.append(prompt)
        return ({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]} if len(prompts)==1 else {"duplicate_groups":[]}),model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    menzo.apply_same_story_duplicate_guard(result([article("https://g/rep","CM Punk contract"),article("https://g/loser","CM Punk deal")]),{})
    menzo.apply_same_story_duplicate_guard(result([article("https://g/rep","CM Punk contract"),article("https://g/loser","CM Punk deal changed")]),{})
    assert "https://g/rep" in prompts[1] and "https://g/loser" in prompts[1]


def test_new_winner_reparents_cached_group_members(monkeypatch,tmp_path):
    path=tmp_path/"cache.json"; monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",path); calls=[0]
    def fake(prompt,model,**k):
        calls[0]+=1
        if calls[0]==1: return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"old group"}]},model
        # Delta ordering is new candidate followed by the cached representative.
        return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"new winner"}]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    menzo.apply_same_story_duplicate_guard(result([article("https://g/old-rep","CM Punk contract"),article("https://g/old-loser","CM Punk deal")]),{})
    out=result([article("https://g/old-rep","CM Punk contract"),article("https://g/old-loser","CM Punk deal"),article("https://g/new","CM Punk officially signs")]); menzo.apply_same_story_duplicate_guard(out,{})
    losers={x["url"]:x for x in out["skipped"]}
    assert losers["https://g/old-rep"]["menzo_winner_url"]=="https://g/new"
    assert losers["https://g/old-loser"]["menzo_winner_url"]=="https://g/new"
    state=json.loads(path.read_text())["same_run_state"]
    group=next(iter(state["groups"].values()))
    assert group["authorized_representative"]=="https://g/new" and set(group["member_candidate_ids"])=={"https://g/new","https://g/old-rep","https://g/old-loser"}


def test_removed_winner_does_not_rehydrate_loser_or_leave_reference(monkeypatch,tmp_path):
    path=tmp_path/"cache.json"; monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",path); calls=[]
    def fake(prompt,model,**k):
        calls.append(prompt); return ({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]} if len(calls)==1 else {"duplicate_groups":[]}),model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    menzo.apply_same_story_duplicate_guard(result([article("https://g/a","CM Punk WWE contract"),article("https://g/b","CM Punk WWE deal")]),{})
    out=result([article("https://g/b","CM Punk WWE deal"),article("https://u/c","AEW arena announced")]); menzo.apply_same_story_duplicate_guard(out,{})
    b=next(x for x in out["selected"] if x["url"]=="https://g/b")
    assert b.get("menzo_winner_url") in {None,""} and b.get("menzo_authorized") is not False
    state=json.loads(path.read_text())["same_run_state"]; assert "https://g/a" not in json.dumps(state)


def test_removed_loser_and_entire_group_are_pruned_without_unrelated_recompute(monkeypatch,tmp_path):
    path=tmp_path/"cache.json"; monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",path); prompts=[]
    def fake(prompt,model,**k):
        prompts.append(prompt); return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    menzo.apply_same_story_duplicate_guard(result([article("https://g/a","CM Punk WWE contract"),article("https://g/b","CM Punk WWE deal"),article("https://u/c","AEW arena announced")]),{})
    out=result([article("https://g/a","CM Punk WWE contract"),article("https://u/c","AEW arena announced")]); menzo.apply_same_story_duplicate_guard(out,{})
    assert len(prompts)==2 and "https://g/b" not in json.dumps(json.loads(path.read_text())["same_run_state"])
    # Removing the remainder of the group only prunes state; unrelated C is a cache hit.
    out2=result([article("https://u/c","AEW arena announced"),article("https://u/d","TNA signs new venue")]); menzo.apply_same_story_duplicate_guard(out2,{})
    assert len(prompts)==3 and "https://g/a" not in json.dumps(json.loads(path.read_text())["same_run_state"])


@pytest.mark.parametrize("mutate",[
    lambda state: "not-a-dictionary",
    lambda state: {k:v for k,v in state.items() if k!="outcomes"},
    lambda state: (state["outcomes"]["https://g/a"]["disposition"].pop("reason"),state)[1],
    lambda state: (next(iter(state["groups"].values())).__setitem__("member_candidate_ids",["https://g/b"]),state)[1],
    lambda state: (state["outcomes"]["https://g/b"].__setitem__("menzo_winner_url","https://wrong/winner"),state)[1],
    lambda state: (state["groups"].__setitem__("duplicate-group",dict(next(iter(state["groups"].values())),group_id="duplicate-group")),state)[1],
])
def test_malformed_same_run_state_falls_back_to_fresh_arbitration(monkeypatch,tmp_path,mutate):
    path=tmp_path/"cache.json"; monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",path); calls=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: calls.append(prompt) or ({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]},model))
    items=[article("https://g/a","CM Punk WWE contract"),article("https://g/b","CM Punk WWE deal")]
    menzo.apply_same_story_duplicate_guard(result([dict(x) for x in items]),{})
    payload=json.loads(path.read_text()); payload["same_run_state"]=mutate(payload["same_run_state"]); path.write_text(json.dumps(payload))
    menzo.apply_same_story_duplicate_guard(result([dict(x) for x in items]),{})
    assert len(calls)==2


def test_meaningful_slug_relevance_rules():
    wwe=article("https://x/wwe-latest-news","Roman Reigns charity appearance")
    other=article("https://y/wwe-exclusive-report","Seth Rollins movie role")
    assert menzo._plausible_history(wwe,[other])==[]
    assert menzo._plausible_history(article("https://x/aew-update","MJF interview"),[article("https://y/aew-update","Darby Allin skateboard")])==[]
    punk=article("https://x/cm-punk-contract-details","CM Punk discussion")
    assert menzo._plausible_history(punk,[article("https://y/cm-punk-contract-status","Contract discussion")])
    # Existing semantic signals remain sufficient without URL continuity.
    signal=article("https://x/alpha","CM Punk officially signs WWE contract")
    assert menzo._plausible_history(signal,[article("https://y/bravo","CM Punk signs WWE contract")])


def test_transitive_invalidated_member_moves_to_skipped_once(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); calls=[0]
    def fake(prompt,model,**k):
        calls[0]+=1
        if calls[0]==1: return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"old"}]},model
        return {"duplicate_groups":[{"keep_id":"c1","discard_ids":["c0"],"reason":"replacement"}]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    menzo.apply_same_story_duplicate_guard(result([article("https://g/rep","CM Punk WWE contract"),article("https://g/member","CM Punk WWE deal")]),{})
    rep=article("https://g/rep","CM Punk WWE contract changed"); member=article("https://g/member","CM Punk WWE deal"); member["decision"]="pending"; member["priority"]="soft"
    out={"selected":[rep,article("https://g/new","CM Punk WWE contract confirmed")],"pending":[member],"skipped":[],"postprocess":{}}
    menzo.apply_same_story_duplicate_guard(out,{})
    assert all(x["url"]!="https://g/member" for x in out["selected"]+out["pending"])
    matches=[x for x in out["skipped"] if x["url"]=="https://g/member"]
    assert len(matches)==1 and matches[0]["menzo_winner_url"]=="https://g/new"


def test_unrelated_generic_wwe_publication_preserves_recent_cache_hit(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    current=article("https://new/cm-punk-contract-details","CM Punk officially signs WWE contract")
    history=[article("https://old/cm-punk-contract-status","CM Punk WWE contract reported")]
    monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:list(history)); prompts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: prompts.append(prompt) or ({"matches":[]},model))
    menzo.apply_recent_published_duplicate_guard(result([dict(current)])); assert len(prompts)==1
    history.append(article("https://old/wwe-latest-news-update","Roman Reigns charity appearance"))
    out=result([dict(current)]); menzo.apply_recent_published_duplicate_guard(out)
    assert len(prompts)==2 and "https://old/cm-punk-contract-status" not in prompts[-1]


def test_same_run_semantic_mismatch_still_sends_all_authorized_survivors(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); prompts=[]
    monkeypatch.setattr(menzo,"same_story_signal",lambda *a:("clearly_distinct",[],0.0))
    def fake(prompt,model,**k):
        prompts.append(prompt)
        if len(prompts)==1: return {"duplicate_groups":[]},model
        # c0 is new C, c1/c2/c3 are cached A/B/D. Apply C/A; ignore old-only B/D.
        return {"duplicate_groups":[{"keep_id":"c1","discard_ids":["c0"],"reason":"semantic match"},{"keep_id":"c2","discard_ids":["c3"],"reason":"old only"}]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    a=article("https://same/a","WWE agreement with Seth Rollins expires"); b=article("https://same/b","AEW announces arena renovation"); d=article("https://same/d","TNA schedules a media event")
    menzo.apply_same_story_duplicate_guard(result([dict(a),dict(b),dict(d)]),{})
    c=article("https://same/c","Seth Rollins departs the promotion"); out=result([dict(a),dict(b),dict(d),c]); menzo.apply_same_story_duplicate_guard(out,{})
    assert len(prompts)==2 and all(url in prompts[-1] for url in ["https://same/a","https://same/b","https://same/c","https://same/d"])
    assert any(x["url"]=="https://same/c" for x in out["skipped"])
    assert any(x["url"]=="https://same/b" for x in out["selected"])


def test_recent_wording_mismatch_always_reaches_gemini(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); monkeypatch.setattr(menzo,"same_story_signal",lambda *a:("clearly_distinct",[],0.0)); prompts=[]
    history=[article("https://history/agreement-expiry","WWE agreement with Seth Rollins expires")]
    monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:history)
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: prompts.append(prompt) or ({"matches":[]},model))
    menzo.apply_recent_published_duplicate_guard(result([article("https://current/departure","Seth Rollins departs the promotion")]))
    assert len(prompts)==1 and "Seth Rollins departs" in prompts[0] and "agreement with Seth Rollins expires" in prompts[0]


def test_history_frontier_new_changed_and_removed_records(monkeypatch,tmp_path):
    path=tmp_path/"cache.json"; monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",path); prompts=[]
    h1=article("https://h/one","History one"); history=[h1]; monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:list(history))
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: prompts.append(prompt) or ({"matches":[]},model))
    candidate=article("https://c/one","Current story")
    menzo.apply_recent_published_duplicate_guard(result([dict(candidate)])); assert len(prompts)==1 and "https://h/one" in prompts[-1]
    menzo.apply_recent_published_duplicate_guard(result([dict(candidate)])); assert len(prompts)==1
    history.extend([article("https://h/two","History two"),article("https://h/three","History three")])
    menzo.apply_recent_published_duplicate_guard(result([dict(candidate)])); assert len(prompts)==2 and "https://h/one" not in prompts[-1] and all(x in prompts[-1] for x in ["https://h/two","https://h/three"])
    history[1]=article("https://h/two","History two materially changed")
    menzo.apply_recent_published_duplicate_guard(result([dict(candidate)])); assert len(prompts)==3 and "https://h/two" in prompts[-1] and "https://h/three" not in prompts[-1]
    history.pop(2)
    menzo.apply_recent_published_duplicate_guard(result([dict(candidate)])); assert len(prompts)==3
    state=json.loads(path.read_text())["recent_history_state"]["candidates"]["https://c/one"]["reviewed_history"]
    assert "https://h/three" not in state


def test_history_frontier_new_and_changed_candidate_get_full_history_only(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); prompts=[]
    history=[article("https://h/one","One"),article("https://h/two","Two")]; monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:history)
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: prompts.append(prompt) or ({"matches":[]},model))
    old=article("https://c/old","Old candidate"); menzo.apply_recent_published_duplicate_guard(result([dict(old)]))
    new=article("https://c/new","New candidate"); menzo.apply_recent_published_duplicate_guard(result([dict(old),dict(new)]))
    assert len(prompts)==2 and "https://c/new" in prompts[-1] and "https://c/old" not in prompts[-1] and all(x["url"] in prompts[-1] for x in history)
    changed=dict(old); changed["summary"]="Old candidate changed"; menzo.apply_recent_published_duplicate_guard(result([changed,dict(new)]))
    assert len(prompts)==3 and "https://c/old" in prompts[-1] and "https://c/new" not in prompts[-1] and all(x["url"] in prompts[-1] for x in history)


def test_removed_matched_history_clears_stale_decision_without_resending(monkeypatch,tmp_path):
    path=tmp_path/"cache.json"; monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",path); prompts=[]
    matched=article("https://h/matched","Matched history"); other=article("https://h/other","Other history"); history=[matched,other]
    monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:list(history))
    def fake(prompt,model,**k):
        prompts.append(prompt); return {"matches":[{"current_id":"c0","published_id":"p0","decision":"DUPLICATE","reason":"same"}]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    candidate=article("https://c/item","Current"); menzo.apply_recent_published_duplicate_guard(result([dict(candidate)])); assert len(prompts)==1
    history.pop(0); out=result([dict(candidate)]); menzo.apply_recent_published_duplicate_guard(out)
    assert len(prompts)==1 and out["selected"][0].get("menzo_compared_with_url") in {None,""}
    entry=json.loads(path.read_text())["recent_history_state"]["candidates"]["https://c/item"]
    assert entry["outcome"]=={"validated_no_match":True} and entry["matched_published_identity"]==""


def test_history_frontier_batches_one_new_record_once_for_three_candidates(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json"); prompts=[]
    history=[article("https://h/old","Old")]; monkeypatch.setattr(menzo,"load_cross_run_story_history",lambda *a,**k:list(history))
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,model,**k: prompts.append(prompt) or ({"matches":[]},model))
    candidates=[article(f"https://c/{i}",f"Candidate {i}") for i in range(3)]
    menzo.apply_recent_published_duplicate_guard(result([dict(x) for x in candidates])); assert len(prompts)==1
    history.append(article("https://h/new","New publication")); second=result([dict(x) for x in candidates]); menzo.apply_recent_published_duplicate_guard(second)
    assert len(prompts)==2 and "https://h/new" in prompts[-1] and "https://h/old" not in prompts[-1]
    assert second["postprocess"]["gemini_duplicate_calls_executed"]==1
    third=result([dict(x) for x in candidates]); menzo.apply_recent_published_duplicate_guard(third); assert len(prompts)==2
