import json
from datetime import datetime, timedelta, timezone

from agents import menzo_duplicate_cache as cache
from agents import menzo_duplicate_scorer as scorer
from agents import menzo_policy_v93_15 as menzo
from agents import source_body


def article(url, title, summary=None):
    return {"source_url":url,"url":url,"title":title,"summary":summary or title,
            "decision":"selected","priority":"hard","score":90,"published_at":datetime.now(timezone.utc).isoformat()}


def board(*items): return {"selected":list(items),"pending":[],"skipped":[],"postprocess":{}}


def isolate(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    monkeypatch.setattr(menzo,"publisher_history_file",lambda:tmp_path/"publisher_history.json")
    def hydrate(item):
        if source_body.contract_text(item): return True,"canonical_cache"
        text=str(item.get("summary") or item.get("title") or item.get("title_it") or "fixture body")
        text += " Complete fixture source body containing the full factual sequence, participants, context, outcome, timing, and editorial details for arbitration." * 2
        item["canonical_source_body"]=source_body.contract_from_elements(str(item.get("source_url") or item.get("url") or ""),[{"type":"text","text":text}],{"stage":"extraction_finished","extraction_finished":True,"body_complete":True,"body_complete_reason":"verified_test_fixture","clean_element_count":1,"root_text_chars":len(text),"extracted_text_chars":len(text),"root_coverage_ratio":1.0,"structured_article_body_chars":0,"structured_coverage_ratio":None,"truncation_access_markers":[]})
        return True,"fixture_bob_extraction"
    monkeypatch.setattr(menzo.source_body,"hydrate",hydrate)


def test_formula_threshold_and_same_subject_different_fact(monkeypatch):
    monkeypatch.delenv("MENZO_DUPLICATE_SUSPECT_THRESHOLD",raising=False); monkeypatch.delenv("MASSY_DUPLICATE_SUSPECT_THRESHOLD",raising=False)
    assert scorer.effective_threshold()==.55
    monkeypatch.setenv("MASSY_DUPLICATE_SUSPECT_THRESHOLD",".61"); assert scorer.effective_threshold()==.61
    old=cache.contract_fingerprint(); monkeypatch.setenv("MENZO_DUPLICATE_SUSPECT_THRESHOLD",".72")
    assert scorer.effective_threshold()==.72 and cache.contract_fingerprint()!=old
    value=scorer.score_pair(article("https://x/match","CM Punk match announced"),article("https://y/interview","CM Punk comments in personal interview"),.55)
    expected=sum(scorer.WEIGHTS[k]*value["components"][k] for k in scorer.WEIGHTS)-sum(value["penalties"].values())
    assert value["score"]==round(max(0,min(1,expected)),6) and not value["above_threshold"]


def test_distinct_trio_never_calls_gemini(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); calls=[]; monkeypatch.setattr(menzo,"call_gemini_json_model",lambda *a,**k:calls.append(a) or ({},"model"))
    out=board(article("https://x/a","CM Punk signs contract"),article("https://x/b","Rhea Ripley suffers injury"),article("https://x/c","Cody Rhodes comments in interview"))
    menzo.apply_same_story_duplicate_guard(out,{})
    assert out["postprocess"]["same_run_pairs_theoretical"]==3
    assert out["postprocess"]["same_run_pairs_above_threshold"]==0 and calls==[]
    assert all("menzo_duplicate_checked" not in x for x in out["selected"])


def test_only_suspicious_component_is_prompted(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); prompts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,*a,**k:prompts.append(prompt) or ({"duplicate_groups":[]},menzo.DUPLICATE_BATCH_MODEL))
    out=board(article("https://x/a","CM Punk suffers knee injury WWE"),article("https://y/a","CM Punk knee injury reported WWE"),article("https://z/a","CM Punk signs new contract WWE"))
    menzo.apply_same_story_duplicate_guard(out,{})
    assert len(prompts)==1 and "https://x/a" in prompts[0] and "https://y/a" in prompts[0] and "https://z/a" not in prompts[0]


def test_exact_duplicate_is_deterministic(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); monkeypatch.setattr(menzo,"call_gemini_json_model",lambda *a,**k:(_ for _ in ()).throw(AssertionError("Gemini called")))
    out=board(article("https://x/a?utm_source=z","CM Punk injury","short"),article("https://x/a","CM Punk injury","a much richer substantive injury report"))
    menzo.apply_same_story_duplicate_guard(out,{})
    assert len(out["selected"])==1 and len(out["skipped"])==1 and out["postprocess"]["same_run_exact_duplicates"]==1


def test_authoritative_history_filter(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc); path=tmp_path/"publisher_history.json"
    good={"source_url":"https://x/good","status":"published","published_at":now.isoformat(),"wp_link":"https://wp/good","title":"Good"}
    records=[good,{**good,"title":"less"},{**good,"published_at":(now-timedelta(minutes=1)).isoformat()},
             {"source_url":"https://x/old","status":"published","published_at":(now-timedelta(hours=13)).isoformat()},
             {"source_url":"https://x/fail","status":"failed","published_at":now.isoformat()},
             {"source_url":"https://x/dry","status":"published","published_at":now.isoformat(),"dry_run":True},
             {"status":"published","published_at":now.isoformat()}]
    path.write_text(json.dumps(records),encoding="utf-8")
    loaded=menzo.load_authoritative_publisher_history(now=now)
    assert len(loaded)==1 and loaded[0]["source_url"]=="https://x/good"


def test_recent_sends_only_suspicious_publication_and_cache_hits(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc)
    history=[{"source_url":"https://old/punk","title":"CM Punk knee injury WWE","summary":"CM Punk knee injury WWE","status":"published","published_at":now.isoformat()},
             {"source_url":"https://old/cody","title":"Cody Rhodes contract AEW","summary":"Cody Rhodes contract AEW","status":"published","published_at":now.isoformat()}]
    (tmp_path/"publisher_history.json").write_text(json.dumps(history),encoding="utf-8"); prompts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda prompt,*a,**k:prompts.append(prompt) or ({"comparisons":[{"current_id":"c0","published_id":"p0","decision":"DUPLICATE","shared_facts":["same injury"],"new_fact":"","reason":"same injury"}]},menzo.DUPLICATE_BATCH_MODEL))
    current=article("https://new/punk","Breaking CM Punk knee injury WWE","Doctors report CM Punk suffered a knee injury in WWE")
    first=board(dict(current)); menzo.apply_recent_published_duplicate_guard(first)
    assert len(prompts)==1 and "https://old/punk" in prompts[0] and "https://old/cody" not in prompts[0] and first["skipped"]
    second=board(dict(current)); menzo.apply_recent_published_duplicate_guard(second)
    assert len(prompts)==1 and second["postprocess"]["duplicate_cache_hits"]==1 and second["skipped"][0]["menzo_authorized"] is False


def test_two_components_are_two_requests(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); prompts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:prompts.append(p) or ({"duplicate_groups":[]},m))
    out=board(article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE"),
              article("https://b/1","Cody Rhodes signs AEW contract"),article("https://b/2","Cody Rhodes contract signing AEW"))
    menzo.apply_same_story_duplicate_guard(out,{})
    assert len(prompts)==2 and all(not ("CM Punk" in p and "Cody Rhodes" in p) for p in prompts)


def test_exact_class_order_independent(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); monkeypatch.setattr(menzo,"call_gemini_json_model",lambda *a,**k:(_ for _ in()).throw(AssertionError()))
    values=[article("https://x/a","Punk injury","tiny"),article("https://x/a?utm=1","Punk injury","the richest factual body available"),article("https://x/a#x","Punk injury","medium body")]
    winners=[]
    for order in (values,list(reversed(values))):
        out=board(*[dict(x) for x in order]); menzo.apply_same_story_duplicate_guard(out,{}); winners.append(out["selected"][0]["summary"])
        assert len(out["skipped"])==2 and out["postprocess"]["gemini_duplicate_calls_executed"]==0
    assert winners[0]==winners[1]


def test_publisher_compatibility_shapes(monkeypatch,tmp_path):
    from agents import publisher
    isolate(monkeypatch,tmp_path)
    ordinary=article("https://x/o","Rhea Ripley injury")
    assert publisher.valid_menzo_duplicate_resolution(ordinary)==(True,"ordinary_article")
    winner=dict(ordinary,menzo_duplicate_checked=True,menzo_duplicate_scope="same_run",menzo_duplicate_decision="DUPLICATE",menzo_authorized=True,menzo_winner_url="https://x/o")
    loser=dict(winner,source_url="https://x/l",url="https://x/l",menzo_authorized=False)
    update=dict(ordinary,menzo_duplicate_checked=True,menzo_duplicate_scope="recent_history",menzo_duplicate_decision="REAL_UPDATE",menzo_authorized=True,menzo_compared_with_url="https://old/o",menzo_new_fact="WWE officially changed the match date")
    assert publisher.valid_menzo_duplicate_resolution(winner)[0]
    assert publisher.valid_menzo_duplicate_resolution(loser)[0]
    assert publisher.valid_menzo_duplicate_resolution(update)[0]
    kept,skipped=publisher.publisher_duplicate_safety_filter([ordinary,winner,loser,update],{})
    assert kept==[ordinary,winner,update] and len(skipped)==1


def test_audit_is_bounded_and_final(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); monkeypatch.setattr(menzo,"V9518_DUPLICATE_AUDIT_MAX",1)
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"duplicate_groups":[]},m))
    out=board(article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE"),article("https://a/3","CM Punk reports knee injury WWE"))
    menzo.apply_same_story_duplicate_guard(out,{})
    assert len(out["postprocess"]["duplicate_suspicion_audit"])==1 and out["postprocess"]["duplicate_suspicion_audit_omitted"]>=1
    assert out["postprocess"]["duplicate_suspicion_audit"][0]["final_disposition"]!=""
    assert out["postprocess"]["same_run_pairs_theoretical"]==sum(out["postprocess"][k] for k in ("same_run_exact_duplicates","same_run_pairs_below_threshold","same_run_pairs_above_threshold"))


def test_scorer_calibration_structured_and_surname():
    cases=[
      ({"title":"CM Punk injured","summary":"Punk suffers knee injury","promotion":"WWE"},{"title":"Punk injury update","central_fact":"knee injury","company":"WWE"},True),
      ({"title":"Cody Rhodes match announced","event":"SummerSlam","promotion":"WWE"},{"title":"Rhodes personal interview","event":"SummerSlam","promotion":"WWE"},False),
      ({"title":"Sparse","summary":"Jon Moxley suffered an injury at AEW Dynamite"},{"title":"Backstage Update On Moxley","story_footprint":"Jon Moxley injury AEW Dynamite"},True),
    ]
    for left,right,expected in cases:
        value=scorer.score_pair(left,right,.55)
        assert set(value["components"])==set(scorer.WEIGHTS) and value["above_threshold"] is expected


def test_death_action_admits_real_andy_williams_pair_without_subject_only_false_positives():
    candidate = {
        "title": "TMZ Confirms The Butcher Andy Williams Died After Collapsing at Wrestling Show"
    }
    published = {
        "title": "New Details Emerge After The Death of The Butcher Andy Williams"
    }

    value = scorer.score_pair(candidate, published)

    assert scorer.DEFAULT_THRESHOLD == .55
    assert value["components"]["entity_subject"] == 1.0
    assert value["components"]["central_fact_action"] == 1.0
    assert value["score"] >= scorer.DEFAULT_THRESHOLD
    assert value["above_threshold"]

    unrelated = [
        scorer.score_pair(
            published,
            {"title": "The Butcher Andy Williams Discusses His Wrestling Career In Interview"},
        ),
        scorer.score_pair(
            {"title": "The Butcher Andy Williams Backstage Photos"},
            {"title": "The Butcher Andy Williams Wrestling Profile"},
        ),
    ]
    assert all(pair["components"]["entity_subject"] == 1.0 for pair in unrelated)
    assert all(not pair["above_threshold"] for pair in unrelated)


def test_death_action_recognizes_legitimate_italian_title_input():
    value = scorer.score_pair(
        {"title": "Andy Williams Died After Collapsing at Wrestling Show"},
        {"title_it": "Andy Williams è morto dopo il malore durante lo show di wrestling"},
    )
    assert value["components"]["central_fact_action"] == 1.0
    euphemism = scorer.score_pair(
        {"title": "Andy Williams Has Passed Away"},
        {"title": "Andy Williams Passing Confirmed"},
    )
    assert euphemism["components"]["central_fact_action"] == 1.0


def test_non_casting_subject_grounding_uses_full_titles():
    value=scorer.score_pair(
        {"title":"Paul Heyman Reacts To Roman Reigns Injury"},
        {"title":"Roman Reigns Injury Draws Reaction From Paul Heyman"})
    assert value["components"]["entity_subject"] == 1.0
    assert value["components"]["central_fact_action"] == 1.0
    assert value["above_threshold"]


def test_recent_bilingual_history_uses_preserved_source_title_for_scoring():
    current={"source_url":"https://current.test/daria",
             "title":"Daria Rae Lands Pro Wrestler Role In Netflix Series"}
    history={"source_url":"https://history.test/daria",
             "source_title":"Daria Rae Lands Pro Wrestler Role In Netflix Series",
             "title_it":"Daria Rae ottiene un ruolo da wrestler in una serie Netflix"}
    value=scorer.score_pair(current, history)
    assert value["components"]["entity_subject"] == 1.0
    assert value["components"]["central_fact_action"] == 1.0
    assert value["above_threshold"]


def test_shared_production_scorer_admits_contextual_entertainment_casting_without_broad_bonus():
    left=article("https://casting.test/one",
        "TNA's Daria Rae (Fka WWE's Sonya Deville) Reportedly Lands Role In Netflix Series")
    right=article("https://casting.test/two",
        "TNA’s Daria Rae Lands Pro Wrestler Role in Netflix Series ‘Myron Bolitar’")
    value=scorer.score_pair(left,right)
    assert scorer.DEFAULT_THRESHOLD == .55
    assert value["components"]["central_fact_action"] == 1.0
    assert value["score"] >= scorer.DEFAULT_THRESHOLD and value["above_threshold"]
    assert scorer is menzo.duplicate_scorer
    lowercase=scorer.score_pair(
        article("https://casting.test/lower-a", "daria rae lands role in streaming series"),
        article("https://casting.test/lower-b", "daria rae cast in pro wrestler role for streaming series"))
    assert lowercase["components"]["entity_subject"] == 1.0 and lowercase["above_threshold"]
    mononym=scorer.score_pair(
        article("https://casting.test/sting-a", "Sting Lands Role In Drama Series"),
        article("https://casting.test/sting-b", "Sting Cast In Wrestler Role For Drama Series"))
    assert mononym["components"]["entity_subject"] == 1.0 and mononym["above_threshold"]
    unrelated=scorer.score_pair(article("https://casting.test/a", "Alex Smith lands wrestling role backstage"),
                                article("https://casting.test/b", "Alex Smith discusses contract in interview"))
    assert unrelated["score"] < scorer.DEFAULT_THRESHOLD
    different_subjects=scorer.score_pair(
        article("https://casting.test/c", "john cena lands role in netflix series"),
        article("https://casting.test/d", "daria rae lands role in amazon series"))
    assert different_subjects["components"]["central_fact_action"] == 1.0
    assert different_subjects["components"]["entity_subject"] == 0.0
    assert different_subjects["score"] < scorer.DEFAULT_THRESHOLD
    title_case=scorer.score_pair(
        article("https://casting.test/e", "John Cena Lands Role In Netflix Series"),
        article("https://casting.test/f", "Daria Rae Lands Role In Amazon Series"))
    assert title_case["components"]["central_fact_action"] == 1.0
    assert title_case["components"]["entity_subject"] == 0.0
    assert title_case["score"] < scorer.DEFAULT_THRESHOLD
    shared_platform=scorer.score_pair(
        article("https://casting.test/g", "John Cena Lands Role In Netflix Series"),
        article("https://casting.test/h", "Daria Rae Lands Role In Netflix Series"))
    assert shared_platform["components"]["central_fact_action"] == 1.0
    assert shared_platform["components"]["entity_subject"] == 0.0
    assert shared_platform["score"] < scorer.DEFAULT_THRESHOLD
    post_action_context=scorer.score_pair(
        article("https://casting.test/i", "John Cena Lands Role In Netflix Original Series"),
        article("https://casting.test/j", "Daria Rae Lands Role In Netflix Original Film"))
    assert post_action_context["components"]["central_fact_action"] == 1.0
    assert post_action_context["components"]["entity_subject"] == 0.0
    assert post_action_context["score"] < scorer.DEFAULT_THRESHOLD
    casing=scorer.score_pair(
        article("https://casting.test/k", "John Cena Lands Role In Netflix Film"),
        article("https://casting.test/l", "john cena lands role in netflix film"))
    assert casing["components"]["entity_subject"] == 1.0 and casing["above_threshold"]
    different_action=scorer.score_pair(
        article("https://casting.test/m", "John Cena Joins Survivor Series Match"),
        article("https://casting.test/n", "John Cena Lands Role In Netflix Series"))
    assert not different_action["above_threshold"]
    generic_context=scorer.score_pair(
        article("https://casting.test/o", "Former WWE Superstar John Cena Lands Role In Netflix Series"),
        article("https://casting.test/p", "Former WWE Superstar Daria Rae Lands Role In Amazon Series"))
    assert generic_context["components"]["entity_subject"] == 0.0
    assert not generic_context["above_threshold"]


def test_subject_anchor_and_explicit_incompatibility_bound_non_exact_suspicion():
    incompatible=scorer.score_pair({"title":"CM Punk suffers injury at WWE Raw"},
                                   {"title":"CM Punk suffers injury at AEW Dynamite"})
    assert incompatible["components"]["entity_subject"] == 1.0
    assert incompatible["penalties"]["incompatible_promotion"] == 0.0
    assert incompatible["penalties"]["incompatible_event"] > 0
    assert not incompatible["above_threshold"]


def test_same_run_failure_cooldown_avoids_retry(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); calls=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:calls.append(k["phase"]) or ({"bad":True},m))
    values=[article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE")]
    first=board(*[dict(x) for x in values]); menzo.apply_same_story_duplicate_guard(first,{})
    count=len(calls); assert count==3 and first["skipped"]
    second=board(*[dict(x) for x in values]); menzo.apply_same_story_duplicate_guard(second,{})
    assert len(calls)==count and second["postprocess"]["duplicate_failure_cooldown_hit"]==1
    assert second["postprocess"]["gemini_duplicate_calls_avoided"]>=1


def test_recent_material_update_and_failure_cooldown(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc)
    old={"source_url":"https://old/p","title":"CM Punk match rumored WWE","summary":"CM Punk match rumored for WWE","status":"published","published_at":now.isoformat()}
    (tmp_path/"publisher_history.json").write_text(json.dumps([old]),encoding="utf-8")
    current=article("https://new/p","WWE officially announced CM Punk match today","Today WWE officially announced CM Punk match")
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"comparisons":[{"current_id":"c0","published_id":"p0","decision":"MATERIAL_UPDATE","shared_facts":["same CM Punk match"],"temporal_basis":"BECAME_KNOWN_AFTER","temporal_evidence_excerpt":"Today WWE officially announced CM Punk match","new_fact":"Today WWE officially announced CM Punk match","reason":"official today"}]},m))
    out=board(dict(current)); menzo.apply_recent_published_duplicate_guard(out)
    assert out["selected"][0]["menzo_duplicate_decision"]=="REAL_UPDATE" and out["selected"][0]["menzo_authorized"] is True
    # Changed material creates a separate suspicious-set identity and invalid output
    # is cooled without affecting an unrelated ordinary candidate.
    calls=[]; monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:calls.append(k["phase"]) or ({"bad":True},m))
    changed=dict(current,summary=current["summary"]+" changed")
    first=board(changed,article("https://new/r","Rhea Ripley contract AEW")); menzo.apply_recent_published_duplicate_guard(first); n=len(calls)
    second=board(dict(changed),article("https://new/r","Rhea Ripley contract AEW")); menzo.apply_recent_published_duplicate_guard(second)
    assert n==2 and len(calls)==n and second["postprocess"]["duplicate_failure_cooldown_hit"]==1
    assert any(x["source_url"]=="https://new/r" for x in second["selected"])


def _only_cache_entry(path):
    entries=json.loads(path.read_text(encoding="utf-8"))["entries"]
    assert len(entries)==1
    return next(iter(entries.values()))


def test_actual_request_counts_batch_repair_and_two_micro(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); calls=[]
    def batch_only(prompt,model,**kwargs):
        calls.append(kwargs["phase"]); return {"duplicate_groups":[]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",batch_only)
    pair=[article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE")]
    menzo.apply_same_story_duplicate_guard(board(*pair),{})
    assert _only_cache_entry(tmp_path/"cache.json")["actual_gemini_request_count"]==1

    (tmp_path/"cache.json").unlink(); calls.clear()
    def repaired(prompt,model,**kwargs):
        calls.append(kwargs["phase"])
        return ({"duplicate_groups":[]} if len(calls)==2 else {"bad":True}),model
    monkeypatch.setattr(menzo,"call_gemini_json_model",repaired)
    menzo.apply_same_story_duplicate_guard(board(*[dict(x) for x in pair]),{})
    assert _only_cache_entry(tmp_path/"cache.json")["actual_gemini_request_count"]==2
    hit=board(*[dict(x) for x in pair]); menzo.apply_same_story_duplicate_guard(hit,{})
    assert len(calls)==2 and hit["postprocess"]["gemini_duplicate_calls_avoided"]==2

    (tmp_path/"cache.json").unlink(); calls.clear()
    def micros(prompt,model,**kwargs):
        calls.append(kwargs["phase"])
        return ({"decision":"NO_DUPLICATE"} if "micro" in kwargs["phase"] else {"bad":True}),model
    monkeypatch.setattr(menzo,"call_gemini_json_model",micros)
    trio=[article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE"),article("https://a/3","CM Punk reports knee injury WWE")]
    menzo.apply_same_story_duplicate_guard(board(*trio),{})
    assert _only_cache_entry(tmp_path/"cache.json")["actual_gemini_request_count"]==4


def test_recent_explicit_no_match_cached_avoidance_and_truthful_audit(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc)
    history={"source_url":"https://old/p","title":"CM Punk knee injury WWE","summary":"CM Punk knee injury WWE","status":"published","published_at":now.isoformat()}
    (tmp_path/"publisher_history.json").write_text(json.dumps([history]),encoding="utf-8")
    current=article("https://new/p","Breaking CM Punk knee injury WWE","Doctors report CM Punk suffered a knee injury in WWE")
    calls=[]
    response={"comparisons":[{"current_id":"c0","published_id":"p0","decision":"NO_MATCH","shared_facts":["CM Punk"],"new_fact":"","reason":"different central fact"}]}
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:calls.append(k["phase"]) or (response,m))
    first=board(dict(current)); menzo.apply_recent_published_duplicate_guard(first)
    assert _only_cache_entry(tmp_path/"cache.json")["actual_gemini_request_count"]==1
    second=board(dict(current)); menzo.apply_recent_published_duplicate_guard(second)
    assert len(calls)==1 and second["postprocess"]["gemini_duplicate_calls_avoided"]==1
    audit=second["postprocess"]["duplicate_suspicion_audit"][0]
    assert audit["cache"]=="hit" and audit["gemini_decision"]=="NO_MATCH" and audit["final_disposition"]=="ordinary_pair"

def test_cached_duplicate_audit_reconstructs_semantics(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); calls=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:calls.append(1) or ({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]},m))
    values=[article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE")]
    menzo.apply_same_story_duplicate_guard(board(*[dict(x) for x in values]),{})
    hit=board(*[dict(x) for x in values]); menzo.apply_same_story_duplicate_guard(hit,{})
    audit=hit["postprocess"]["duplicate_suspicion_audit"][0]
    assert len(calls)==1 and hit["postprocess"]["gemini_duplicate_calls_avoided"]==1
    assert audit["gemini_decision"]=="DUPLICATE" and audit["final_disposition"]=="duplicate_applied"
    assert sorted(audit["endpoint_dispositions"].values())==["loser_blocked","winner_authorized"]


def test_bilingual_publisher_titles_and_recent_prompt(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc)
    injury=article("https://new/punk","CM Punk suffers a knee injury in WWE")
    old_injury={"source_url":"https://old/punk","title_it":"CM Punk infortunato: lesione al ginocchio in WWE","status":"published","published_at":now.isoformat(),"wp_link":"https://wp/punk"}
    contract=article("https://new/cody","Cody Rhodes signs a new WWE contract")
    old_contract={"source_url":"https://old/cody","title_it":"Cody Rhodes firma un nuovo contratto con la WWE","status":"published","published_at":now.isoformat(),"wp_link":"https://wp/cody"}
    assert scorer.score_pair(injury,old_injury)["above_threshold"]
    assert scorer.score_pair(contract,old_contract)["above_threshold"]
    assert not scorer.score_pair(injury,{**old_contract,"title_it":"CM Punk firma un nuovo contratto con la WWE"})["above_threshold"]
    unrelated={"source_url":"https://old/rhea","title_it":"Rhea Ripley rilascia una intervista sul suo futuro","status":"published","published_at":now.isoformat(),"wp_link":"https://wp/rhea"}
    (tmp_path/"publisher_history.json").write_text(json.dumps([old_injury,unrelated]),encoding="utf-8")
    prompts=[]; monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:prompts.append(p) or ({"comparisons":[{"current_id":"c0","published_id":"p0","decision":"NO_MATCH","shared_facts":[],"new_fact":"","reason":"distinct"}]},m))
    menzo.apply_recent_published_duplicate_guard(board(dict(injury)))
    assert len(prompts)==1 and "https://old/punk" in prompts[0] and "https://old/rhea" not in prompts[0]


def test_unit_cooldown_identity_and_real_call_count(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); menzo.MENZO_MODEL_COOLDOWN_FAILURES.clear(); seen=[]; first=[None]
    def fake(prompt,model,ledger_context=None,**kwargs):
        context=dict(ledger_context or {}); seen.append(context); token=(model,context.get("cluster_id"))
        if first[0] is None: first[0]=token
        if token==first[0]:
            if token in menzo.MENZO_MODEL_COOLDOWN_FAILURES: return None,f"model_cooldown_after_failure:{model}"
            menzo.MENZO_MODEL_COOLDOWN_FAILURES.add(token); return None,"api_error:503 unavailable"
        return {"duplicate_groups":[]},model
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    out=board(article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE"),
              article("https://b/1","Cody Rhodes contract signing AEW"),article("https://b/2","Cody Rhodes signs AEW contract"))
    try:
        menzo.apply_same_story_duplicate_guard(out,{})
        cluster_ids=[x["cluster_id"] for x in seen]
        assert len(set(cluster_ids))==2 and all(x.get("scope")=="same_run" for x in seen)
        assert out["postprocess"]["gemini_duplicate_calls_executed"]==2
        assert out["postprocess"]["menzo_duplicate_arbitration_fail_closed"]>=1
    finally: menzo.MENZO_MODEL_COOLDOWN_FAILURES.clear()


def test_failed_unit_counts_only_real_503(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); menzo.MENZO_MODEL_COOLDOWN_FAILURES.clear(); first=[True]
    def fake(prompt,model,ledger_context=None,**kwargs):
        token=(model,(ledger_context or {})["cluster_id"])
        if first[0]: first[0]=False; menzo.MENZO_MODEL_COOLDOWN_FAILURES.add(token); return None,"api_error:503 unavailable"
        return None,f"model_cooldown_after_failure:{model}"
    monkeypatch.setattr(menzo,"call_gemini_json_model",fake)
    try:
        out=board(article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE")); menzo.apply_same_story_duplicate_guard(out,{})
        assert out["postprocess"]["gemini_duplicate_calls_executed"]==1 and out["skipped"]
        assert not json.loads((tmp_path/"cache.json").read_text())["entries"]
    finally: menzo.MENZO_MODEL_COOLDOWN_FAILURES.clear()


def test_pair_specific_audit_fresh_and_cache(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path)
    original=scorer.score_pair
    edges={("https://a","https://b"),("https://b","https://c")}
    def scored(left,right,threshold=None):
        value=original(left,right,threshold); pair=tuple(sorted((left["url"],right["url"])))
        value.update(score=.8 if pair in edges else .1,above_threshold=pair in edges,exact_duplicate=False,exact_reason="")
        return value
    monkeypatch.setattr(menzo.duplicate_scorer,"score_pair",scored)
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]},m))
    values=[article("https://a","A"),article("https://b","B"),article("https://c","C")]
    first=board(*[dict(x) for x in values]); menzo.apply_same_story_duplicate_guard(first,{})
    second=board(*[dict(x) for x in values]); menzo.apply_same_story_duplicate_guard(second,{})
    for out,cache_status in ((first,"miss"),(second,"hit")):
        audits={tuple(x["identities"]):x for x in out["postprocess"]["duplicate_suspicion_audit"]}
        assert audits[("https://a","https://b")]["gemini_decision"]=="DUPLICATE"
        bc=audits[("https://b","https://c")]
        assert bc["cache"]==cache_status and bc["gemini_decision"]=="NO_MATCH" and bc["final_disposition"]=="ordinary_pair"
        assert bc["endpoint_dispositions"]["https://c"]=="ordinary" and bc["endpoint_dispositions"]["https://b"] in {"blocked_due_to_other_edge","winner_authorized"}


def test_three_member_group_marks_every_suspicious_edge_duplicate(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path)
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1","c2"],"reason":"same"}]},m))
    out=board(article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE"),article("https://a/3","CM Punk reports knee injury WWE"))
    menzo.apply_same_story_duplicate_guard(out,{})
    assert len(out["postprocess"]["duplicate_suspicion_audit"])==3
    assert all(x["gemini_decision"]=="DUPLICATE" and x["final_disposition"]=="duplicate_applied" for x in out["postprocess"]["duplicate_suspicion_audit"])


def test_recent_candidates_use_distinct_cooldown_keys(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc)
    history=[{"source_url":"https://old/p","title_it":"CM Punk ha subito un infortunio in WWE","status":"published","published_at":now.isoformat()},
             {"source_url":"https://old/c","title_it":"Cody Rhodes firma un contratto con AEW","status":"published","published_at":now.isoformat()}]
    (tmp_path/"publisher_history.json").write_text(json.dumps(history),encoding="utf-8"); contexts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,ledger_context=None,**k:contexts.append(dict(ledger_context or {})) or ({"comparisons":[{"current_id":"c0","published_id":"p0","decision":"NO_MATCH","shared_facts":[],"new_fact":"","reason":"distinct"}]},m))
    out=board(article("https://new/p","CM Punk suffers a WWE injury"),article("https://new/c","Cody Rhodes signs an AEW contract")); menzo.apply_recent_published_duplicate_guard(out)
    assert len(contexts)==2 and len({x["cluster_id"] for x in contexts})==2
    assert {x["url"] for x in contexts}=={"https://new/p","https://new/c"} and all(x["scope"]=="recent_history" for x in contexts)


def test_recent_pair_audit_fresh_cache_and_material_update(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc)
    publications=[{"source_url":"https://old/p1","title_it":"CM Punk ha subito un infortunio al ginocchio in WWE","status":"published","published_at":now.isoformat()},
                  {"source_url":"https://old/p2","title_it":"CM Punk infortunato al ginocchio: operazione WWE","status":"published","published_at":now.isoformat()}]
    (tmp_path/"publisher_history.json").write_text(json.dumps(publications),encoding="utf-8")
    current=article("https://new/p","CM Punk suffers a WWE knee injury and surgery")
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"comparisons":[{"current_id":"c0","published_id":"p0","decision":"DUPLICATE","shared_facts":["injury"],"new_fact":"","reason":"same"},{"current_id":"c0","published_id":"p1","decision":"NO_MATCH","shared_facts":[],"new_fact":"","reason":"different"}]},m))
    fresh=board(dict(current)); menzo.apply_recent_published_duplicate_guard(fresh)
    hit=board(dict(current)); menzo.apply_recent_published_duplicate_guard(hit)
    for out,status in ((fresh,"miss"),(hit,"hit")):
        audits={x["identities"][1]:x for x in out["postprocess"]["duplicate_suspicion_audit"]}
        assert audits["https://old/p1"]["cache"]==status and audits["https://old/p1"]["gemini_decision"]=="DUPLICATE" and audits["https://old/p1"]["final_disposition"]=="blocked"
        assert audits["https://old/p2"]["gemini_decision"]=="NO_MATCH" and audits["https://old/p2"]["final_disposition"]=="ordinary_pair"

    (tmp_path/"cache.json").unlink()
    update=article("https://new/u","WWE officially confirmed CM Punk surgery today","Today WWE officially confirmed CM Punk surgery")
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"comparisons":[{"current_id":"c0","published_id":"p0","decision":"NO_MATCH","shared_facts":["injury"],"new_fact":"","reason":"distinct"},{"current_id":"c0","published_id":"p1","decision":"MATERIAL_UPDATE","temporal_basis":"BECAME_KNOWN_AFTER","temporal_evidence_excerpt":"Today WWE officially confirmed CM Punk surgery","shared_facts":["surgery"],"new_fact":"Today WWE officially confirmed CM Punk surgery","reason":"official today"}]},m))
    out=board(update); menzo.apply_recent_published_duplicate_guard(out)
    audits={x["identities"][1]:x for x in out["postprocess"]["duplicate_suspicion_audit"]}
    assert audits["https://old/p1"]["gemini_decision"]=="NO_MATCH" and audits["https://old/p1"]["final_disposition"]=="ordinary_pair"
    assert audits["https://old/p2"]["gemini_decision"]=="MATERIAL_UPDATE" and audits["https://old/p2"]["final_disposition"]=="material_update"


def test_recent_pair_audit_no_match_all_publications(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc)
    history=[{"source_url":f"https://old/{n}","title_it":f"CM Punk infortunato al ginocchio WWE rapporto {n}","status":"published","published_at":now.isoformat()} for n in (1,2)]
    (tmp_path/"publisher_history.json").write_text(json.dumps(history),encoding="utf-8")
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"comparisons":[{"current_id":"c0","published_id":f"p{i}","decision":"NO_MATCH","shared_facts":[],"new_fact":"","reason":"distinct"} for i in range(2)]},m))
    out=board(article("https://new/p","CM Punk suffers a WWE knee injury")); menzo.apply_recent_published_duplicate_guard(out)
    assert all(x["gemini_decision"]=="NO_MATCH" and x["final_disposition"]=="ordinary_pair" for x in out["postprocess"]["duplicate_suspicion_audit"])
