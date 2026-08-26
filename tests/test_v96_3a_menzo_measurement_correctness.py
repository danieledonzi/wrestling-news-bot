import json
from datetime import datetime, timedelta, timezone

from agents import menzo_duplicate_cache as cache
from agents import menzo_policy_v93_15 as menzo
from agents import source_body
from agents.master_log_v93_19 import compact_duplicate_arbitration
from scripts.observability_snapshot import aggregate_duplicate_arbitration
from scripts.observability_snapshot import V96_3A_DUPLICATE_COUNTERS


def article(url, title, summary=None):
    return {"source_url":url,"url":url,"title":title,"summary":summary or title,
            "decision":"selected","priority":"hard","score":90}


def board(*items): return {"selected":list(items),"pending":[],"skipped":[],"postprocess":{}}


def isolate(monkeypatch,tmp_path):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    monkeypatch.setattr(menzo,"publisher_history_file",lambda:tmp_path/"history.json")
    def hydrate(item):
        if source_body.contract_text(item): return True,"canonical_cache"
        text=(str(item.get("summary") or item.get("title"))+" complete factual body with participants timing and outcome")*5
        item["canonical_source_body"]=source_body.contract_from_elements(item["source_url"],[{"type":"text","text":text}],
            {"stage":"extraction_finished","extraction_finished":True,"body_complete":True,"body_complete_reason":"fixture",
             "clean_element_count":1,"root_text_chars":len(text),"extracted_text_chars":len(text),"root_coverage_ratio":1.0,
             "structured_article_body_chars":0,"structured_coverage_ratio":None,"truncation_access_markers":[]})
        return True,"fixture"
    monkeypatch.setattr(menzo.source_body,"hydrate",hydrate)


def history_record(stamp):
    return {"source_url":"https://old/punk","title":"CM Punk knee injury WWE","summary":"CM Punk knee injury WWE",
            "status":"published","published_at":stamp.isoformat()}


def response():
    return {"comparisons":[{"current_id":"c0","published_id":"p0","decision":"NO_MATCH","shared_facts":[],
            "new_fact":"","temporal_basis":"","temporal_evidence_excerpt":"","reason":"different central fact"}]}


def current(): return article("https://new/punk","Breaking CM Punk knee injury WWE","Doctors discuss CM Punk knee injury WWE")


def test_recent_cooldown_hits_are_read_only_expiry_retries_and_material_bypasses(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc)
    (tmp_path/"history.json").write_text(json.dumps([history_record(now)]))
    calls=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda *a,**k:calls.append(k["phase"]) or ({"bad":True},menzo.DUPLICATE_BATCH_MODEL))
    first=board(current()); menzo.apply_recent_published_duplicate_guard(first)
    state=json.loads((tmp_path/"cache.json").read_text()); failure=next(iter(state["failures"].values())); assert failure["attempt_count"]==1
    original=dict(failure); count=len(calls); assert count==2 and first["skipped"]
    for _ in range(3):
        out=board(current()); menzo.apply_recent_published_duplicate_guard(out); assert out["skipped"]
    state=json.loads((tmp_path/"cache.json").read_text()); failure=next(iter(state["failures"].values()))
    assert len(calls)==count and failure["failed_at"]==original["failed_at"] and failure["retry_after"]==original["retry_after"] and failure["attempt_count"]==1
    assert out["postprocess"]["duplicate_failure_cooldown_calls_avoided"]==1
    assert any(x["event"]=="fail_closed" and x["cause"]=="failure_cooldown" and x["grain"]=="candidate" for x in out["postprocess"]["menzo_duplicate_arbitration_diagnostics"])
    # Deterministically expire the persisted deadline; no sleeping.
    key=next(iter(state["failures"])); state["failures"][key]["retry_after"]=(now-timedelta(seconds=1)).isoformat(); (tmp_path/"cache.json").write_text(json.dumps(state))
    menzo.apply_recent_published_duplicate_guard(board(current())); assert len(calls)==count+2
    changed=current(); changed["summary"] += " changed material"
    menzo.apply_recent_published_duplicate_guard(board(changed)); assert len(calls)==count+4


def test_recent_timestamp_invalidates_but_identical_temporal_material_reuses(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc); calls=[]
    (tmp_path/"history.json").write_text(json.dumps([history_record(now)]))
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda *a,**k:calls.append(k["phase"]) or (response(),menzo.DUPLICATE_BATCH_MODEL))
    live=board(current()); menzo.apply_recent_published_duplicate_guard(live)
    cached=board(current()); menzo.apply_recent_published_duplicate_guard(cached)
    assert len(calls)==1 and cached["postprocess"]["duplicate_cache_v2_hits"]==1
    assert live["selected"][0]["menzo_duplicate_decision"]==cached["selected"][0]["menzo_duplicate_decision"]=="NO_MATCH"
    (tmp_path/"history.json").write_text(json.dumps([history_record(now-timedelta(minutes=1))]))
    menzo.apply_recent_published_duplicate_guard(board(current())); assert len(calls)==2


def test_contract_transition_and_same_run_hash_stability():
    record={"id":"p0","title":"x","published_at":"2026-01-01T00:00:00+00:00"}
    changed={**record,"published_at":"2026-01-01T01:00:00+00:00"}
    assert cache.candidate_material_hash(record)==cache.candidate_material_hash(changed)
    assert cache.published_material_hash(record)!=cache.published_material_hash(changed)
    assert cache.MENZO_DUPLICATE_ARBITRATION_CONTRACT_VERSION.startswith("v96.3a")
    c=cache.empty_cache(); pairs=[("candidate","material")]; key=cache.request_key("same_run_component",pairs)
    decision={field:"" for field in cache.REQUIRED_DECISION_FIELDS}; decision["disposition"]={field:"" for field in cache.REQUIRED_DISPOSITION_FIELDS}
    assert cache.store(c,key,"same_run_component",{"candidate":decision},candidates=pairs)
    c["entries"][key]["contract_fingerprint"]="pre-v96.3a"
    assert cache.lookup(c,key,candidates=pairs) is None


def test_repair_and_windowed_diagnostics(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); now=datetime.now(timezone.utc); (tmp_path/"history.json").write_text(json.dumps([history_record(now)]))
    replies=iter([({"bad":True},menzo.DUPLICATE_BATCH_MODEL),(response(),menzo.DUPLICATE_BATCH_MODEL)])
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda *a,**k:next(replies))
    out=board(current()); menzo.apply_recent_published_duplicate_guard(out)
    repair=next(x for x in out["postprocess"]["menzo_duplicate_arbitration_diagnostics"] if x["event"]=="repair")
    assert repair["repair_trigger_reason"]=="matches_not_list" and repair["primary_validation_result"]=="validation_failed"
    assert repair["terminal_validation_result"]=="valid" and repair["comparison_count"]==1
    compact=compact_duplicate_arbitration(out["postprocess"]); assert compact["diagnostics"][0]["unit_identity"]
    run={"recorded_at":now.isoformat(),"menzo":{"duplicate_arbitration":compact}}
    aggregate,_,_=aggregate_duplicate_arbitration([run],now-timedelta(hours=1),now+timedelta(hours=1))
    assert aggregate["repair_trigger_reasons"]["recent_history:matches_not_list"]==1
    assert aggregate["terminal_validation_results"]["recent_history:valid"]==1


def test_diagnostic_instrumentation_failure_is_fail_open():
    class Broken(dict):
        def setdefault(self, *args, **kwargs): raise OSError("diagnostic storage unavailable")
    menzo._v963a_diagnostic(Broken(), {"event":"repair"})


def test_same_run_component_incident_and_affected_unit_grains(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path)
    monkeypatch.setattr(menzo,"hydrate_complete_article_bodies",lambda items:(False,[]))
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda *a,**k:(_ for _ in ()).throw(AssertionError("no provider call")))
    out=board(article("https://a/1","CM Punk knee injury WWE"),
              article("https://a/2","CM Punk suffers knee injury WWE"),
              article("https://a/3","CM Punk reports knee injury WWE"))
    menzo.apply_same_story_duplicate_guard(out,{})
    rows=[x for x in out["postprocess"]["menzo_duplicate_arbitration_diagnostics"]
          if x["event"]=="fail_closed" and x["cause"]=="body_unavailable"]
    assert len(rows)==1 and rows[0]["affected_unit_count"]==3
    now=datetime.now(timezone.utc); compact=compact_duplicate_arbitration(out["postprocess"])
    run={"recorded_at":now.isoformat(),"menzo":{"duplicate_arbitration":compact}}
    aggregate,_,_=aggregate_duplicate_arbitration([run],now-timedelta(minutes=1),now+timedelta(minutes=1))
    key="same_run:component:body_unavailable"
    assert aggregate["fail_closed_incidents_by_scope_grain_cause"][key]==1
    assert aggregate["fail_closed_affected_units_by_scope_grain_cause"][key]==3


def test_same_run_micro_unresolved_reports_actual_candidate(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); calls=[]
    def invalid(*args,**kwargs): calls.append(kwargs["phase"]); return {"bad":True},menzo.DUPLICATE_BATCH_MODEL
    monkeypatch.setattr(menzo,"call_gemini_json_model",invalid)
    out=board(article("https://a/1","CM Punk knee injury WWE"),article("https://a/2","CM Punk suffers knee injury WWE"))
    menzo.apply_same_story_duplicate_guard(out,{})
    assert calls==["duplicate_arbitration_same_run_batch","duplicate_arbitration_same_run_repair","duplicate_arbitration_same_run_micro"]
    assert out["postprocess"]["menzo_duplicate_arbitration_fail_closed"]==1
    rows=[x for x in out["postprocess"]["menzo_duplicate_arbitration_diagnostics"] if x.get("cause")=="micro_fallback_unresolved"]
    assert len(rows)==1 and rows[0]["affected_unit_count"]==1 and rows[0]["unit_identity"]


def test_windowed_diagnostic_omission_is_explicitly_partial():
    now=datetime.now(timezone.utc)
    payload={"menzo_duplicate_arbitration_fail_closed":2,"diagnostics":[],"diagnostics_omitted":2}
    run={"recorded_at":now.isoformat(),"menzo":{"duplicate_arbitration":payload}}
    aggregate,_,_=aggregate_duplicate_arbitration([run],now-timedelta(minutes=1),now+timedelta(minutes=1))
    assert aggregate["diagnostic_covered_runs"]==aggregate["diagnostic_total_runs"]==1
    assert aggregate["diagnostics_omitted"]==2
    assert aggregate["diagnostic_distributions_complete"] is False
    assert aggregate["fail_closed_incidents_by_scope_grain_cause"]=={}


def test_windowed_diagnostic_coverage_pre_cutover_is_not_complete():
    now=datetime.now(timezone.utc)
    legacy={"menzo_duplicate_arbitration_fail_closed":0}
    run={"recorded_at":now.isoformat(),"menzo":{"duplicate_arbitration":legacy}}
    aggregate,_,_=aggregate_duplicate_arbitration([run],now-timedelta(minutes=1),now+timedelta(minutes=1))
    assert aggregate["available"] is True
    assert aggregate["diagnostic_covered_runs"]==0 and aggregate["diagnostic_total_runs"]==1
    assert aggregate["diagnostic_distributions_complete"] is False


def test_windowed_diagnostic_coverage_straddling_cutover_is_partial():
    now=datetime.now(timezone.utc)
    payloads=[{"menzo_duplicate_arbitration_fail_closed":0},
              {"menzo_duplicate_arbitration_fail_closed":0,"diagnostics":[],"diagnostics_omitted":0}]
    runs=[{"recorded_at":(now+timedelta(seconds=i)).isoformat(),"menzo":{"duplicate_arbitration":payload}}
          for i,payload in enumerate(payloads)]
    aggregate,_,_=aggregate_duplicate_arbitration(runs,now-timedelta(minutes=1),now+timedelta(minutes=1))
    assert aggregate["diagnostic_covered_runs"]==1 and aggregate["diagnostic_total_runs"]==2
    assert aggregate["diagnostic_distributions_complete"] is False


def test_windowed_diagnostic_coverage_full_with_zero_events_is_complete():
    now=datetime.now(timezone.utc)
    payload={"menzo_duplicate_arbitration_fail_closed":0,"diagnostics":[],"diagnostics_omitted":0}
    runs=[{"recorded_at":(now+timedelta(seconds=i)).isoformat(),"menzo":{"duplicate_arbitration":dict(payload)}}
          for i in range(2)]
    aggregate,_,_=aggregate_duplicate_arbitration(runs,now-timedelta(minutes=1),now+timedelta(minutes=1))
    assert aggregate["diagnostic_covered_runs"]==aggregate["diagnostic_total_runs"]==2
    assert aggregate["diagnostic_distributions_complete"] is True
    assert aggregate["repair_trigger_reasons"]=={}
    assert aggregate["fail_closed_incidents_by_scope_grain_cause"]=={}


def v96_3a_counters(value=0): return {key:value for key in V96_3A_DUPLICATE_COUNTERS}


def test_windowed_v96_3a_counter_coverage_pre_cutover_is_incomplete():
    now=datetime.now(timezone.utc)
    payload={"menzo_duplicate_arbitration_fail_closed":0}
    run={"recorded_at":now.isoformat(),"menzo":{"duplicate_arbitration":payload}}
    aggregate,_,_=aggregate_duplicate_arbitration([run],now-timedelta(minutes=1),now+timedelta(minutes=1))
    assert aggregate["available"] is True
    assert aggregate["v96_3a_counter_covered_runs"]==0 and aggregate["v96_3a_counter_total_runs"]==1
    assert aggregate["v96_3a_counter_stream_complete"] is False


def test_windowed_v96_3a_counter_coverage_straddling_is_incomplete():
    now=datetime.now(timezone.utc)
    payloads=[{"menzo_duplicate_arbitration_fail_closed":0},
              {"menzo_duplicate_arbitration_fail_closed":0,**v96_3a_counters()}]
    runs=[{"recorded_at":(now+timedelta(seconds=i)).isoformat(),"menzo":{"duplicate_arbitration":payload}}
          for i,payload in enumerate(payloads)]
    aggregate,_,_=aggregate_duplicate_arbitration(runs,now-timedelta(minutes=1),now+timedelta(minutes=1))
    assert aggregate["v96_3a_counter_covered_runs"]==1 and aggregate["v96_3a_counter_total_runs"]==2
    assert aggregate["v96_3a_counter_stream_complete"] is False


def test_windowed_v96_3a_counter_coverage_full_zero_is_legitimate():
    now=datetime.now(timezone.utc); payload={"menzo_duplicate_arbitration_fail_closed":0,**v96_3a_counters()}
    runs=[{"recorded_at":(now+timedelta(seconds=i)).isoformat(),"menzo":{"duplicate_arbitration":dict(payload)}} for i in range(2)]
    aggregate,_,_=aggregate_duplicate_arbitration(runs,now-timedelta(minutes=1),now+timedelta(minutes=1))
    assert aggregate["v96_3a_counter_covered_runs"]==aggregate["v96_3a_counter_total_runs"]==2
    assert aggregate["v96_3a_counter_stream_complete"] is True
    assert all(aggregate["counters"][key]==0 for key in V96_3A_DUPLICATE_COUNTERS)


def test_windowed_v96_3a_counter_coverage_full_nonzero_aggregates():
    now=datetime.now(timezone.utc)
    runs=[{"recorded_at":(now+timedelta(seconds=i)).isoformat(),"menzo":{"duplicate_arbitration":v96_3a_counters(value)}}
          for i,value in enumerate((1,2))]
    aggregate,_,_=aggregate_duplicate_arbitration(runs,now-timedelta(minutes=1),now+timedelta(minutes=1))
    assert aggregate["v96_3a_counter_stream_complete"] is True
    assert all(aggregate["counters"][key]==3 for key in V96_3A_DUPLICATE_COUNTERS)


def miss_counters():
    return {"duplicate_cache_misses":0,"duplicate_cache_v2_misses":0,
            "duplicate_cache_contract_changed":0,"duplicate_cache_v2_contract_invalidations":0,
            "duplicate_cache_v2_other_misses":0}


def historical_entry(scope,pairs,comparison,fingerprint="old-contract"):
    pairs=sorted(pairs)
    return {"scope":scope,"contract_fingerprint":fingerprint,
            "evaluated_candidate_ids":[identity for identity,_ in pairs],
            "candidate_material_hashes":dict(pairs),"comparison_hash":comparison}


def classify(cache_state,scope,pairs,comparison):
    pp=miss_counters()
    menzo._cache_miss(pp,cache_state,scope=scope,candidates=pairs,comparisons=comparison)
    return pp


def test_contract_miss_old_root_without_corresponding_entry_is_other():
    state=cache.empty_cache(); state["contract_fingerprint"]="old-root"
    pp=classify(state,"same_run_component",[("candidate-a","material-a")],"comparison-a")
    assert pp["duplicate_cache_v2_misses"]==1
    assert pp["duplicate_cache_v2_contract_invalidations"]==0
    assert pp["duplicate_cache_v2_other_misses"]==1


def test_contract_miss_matching_old_entry_is_entry_evidenced():
    pairs=[("candidate-a","material-a")]; comparison="comparison-a"; state=cache.empty_cache()
    state["entries"]["old-key"]=historical_entry("same_run_component",pairs,comparison)
    current_key=cache.request_key("same_run_component",pairs,comparison)
    assert cache.lookup(state,current_key,candidates=pairs,comparisons=comparison) is None
    pp=classify(state,"same_run_component",pairs,comparison)
    assert pp["duplicate_cache_v2_contract_invalidations"]==1
    assert pp["duplicate_cache_v2_other_misses"]==0
    assert pp["duplicate_cache_contract_changed"]==1


def test_contract_miss_old_entry_survives_root_update():
    first=[("candidate-a","material-a")]; second=[("candidate-b","material-b")]; state=cache.empty_cache()
    state["contract_fingerprint"]="old-root"
    state["entries"]={"old-a":historical_entry("same_run_component",first,"comparison-a"),
                      "old-b":historical_entry("same_run_component",second,"comparison-b")}
    assert classify(state,"same_run_component",first,"comparison-a")["duplicate_cache_v2_contract_invalidations"]==1
    assert cache.store(state,cache.request_key("same_run_component",first,"comparison-a"),
                       "same_run_component",{},candidates=first,comparisons="comparison-a")
    assert state["contract_fingerprint"]==cache.contract_fingerprint()
    pp=classify(state,"same_run_component",second,"comparison-b")
    assert pp["duplicate_cache_v2_contract_invalidations"]==1 and pp["duplicate_cache_v2_other_misses"]==0


def test_contract_miss_classification_is_order_independent():
    old=[("candidate-old","material-old")]; new=[("candidate-new","material-new")]
    def evaluate(order):
        state=cache.empty_cache(); state["contract_fingerprint"]="old-root"
        state["entries"]["old-key"]=historical_entry("same_run_component",old,"old-comparison")
        totals={"contract":0,"other":0}
        for pairs,comparison in order:
            pp=classify(state,"same_run_component",pairs,comparison)
            totals["contract"]+=pp["duplicate_cache_v2_contract_invalidations"]
            totals["other"]+=pp["duplicate_cache_v2_other_misses"]
            cache.store(state,cache.request_key("same_run_component",pairs,comparison),
                        "same_run_component",{},candidates=pairs,comparisons=comparison)
        return totals
    assert evaluate([(old,"old-comparison"),(new,"new-comparison")]) == evaluate([(new,"new-comparison"),(old,"old-comparison")]) == {"contract":1,"other":1}


def test_contract_miss_genuinely_new_request_on_mixed_cache_is_other():
    state=cache.empty_cache(); old=[("old","old-material")]; current=[("current","current-material")]
    state["entries"]["old-key"]=historical_entry("same_run_component",old,"old-comparison")
    state["entries"]["current-key"]=historical_entry("same_run_component",current,"current-comparison",cache.contract_fingerprint())
    pp=classify(state,"recent_history_suspicious_set",[("new","new-material")],"new-comparison")
    assert pp["duplicate_cache_v2_contract_invalidations"]==0 and pp["duplicate_cache_v2_other_misses"]==1
