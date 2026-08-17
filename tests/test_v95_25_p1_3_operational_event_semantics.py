import json
from datetime import datetime, timezone
from agents.canonical_event_ledger import (CanonicalEventLedger, OperationalAIRequest,
    clear_active_ledger, install_active_ledger)
from scripts.validate_canonical_operational_semantics import analyze

URL={"source_url":"https://example.test/story"}
def read(p): return [json.loads(x) for x in p.read_text().splitlines()]

def test_retry_recovery_and_unique_attempts(tmp_path):
    ledger=CanonicalEventLedger("run",tmp_path/"events"); install_active_ledger(ledger)
    try:
        req=OperationalAIRequest("Bob","translation_generation",item=URL)
        one=req.start("gemini-a"); req.failed(one,error_class="upstream",error_terminal=False)
        two=req.start("gemini-a"); req.completed(two,0)
    finally: clear_active_ledger()
    rows=read(ledger.path); out=analyze(rows)
    assert one["logical_request_id"]==two["logical_request_id"]
    assert one["attempt_id"]!=two["attempt_id"] and two["attempt_number"]==2
    assert out["logical_requests_recovered"]==1 and not out["lifecycle_errors"]

def test_fallback_repair_terminal_and_avoided(tmp_path):
    ledger=CanonicalEventLedger("run",tmp_path/"events"); install_active_ledger(ledger)
    try:
        req=OperationalAIRequest("Menzo","duplicate_arbitration")
        a=req.start("primary"); req.failed(a,error_class="validation",error_terminal=False)
        b=req.start("fallback",fallback=True,repair=True); req.completed(b)
        avoided=OperationalAIRequest("Menzo","duplicate_arbitration"); avoided.avoided("cache_hit")
        terminal=OperationalAIRequest("Menzo","duplicate_arbitration"); c=terminal.start("primary"); terminal.failed(c,error_class="upstream",error_terminal=True)
    finally: clear_active_ledger()
    out=analyze(read(ledger.path))
    assert out["fallbacks_started"]==out["repairs_started"]==1
    assert out["logical_requests_avoided"]==out["logical_requests_terminal_failed"]==1

def test_occurrence_and_item_level_normalization(tmp_path):
    ledger=CanonicalEventLedger("run",tmp_path/"events")
    ledger.observe_alfred({"reviews":[{**URL,"decision":"approved","warnings":[
        {"code":"A","severity":"warning"},{"code":"A","severity":"warning"}],
        "issues":[{"code":"B","severity":"blocker"}]}]})
    ledger.observe_publisher({"results":[{**URL,"status":"publish_error"}]})
    ledger.observe_simone({}, {"errors":1,"results":[]})
    out=analyze(read(ledger.path))
    assert out["warning_occurrences"]==2 and out["warning_occurrences_by_code"]=={"A":2}
    assert out["warning_articles_distinct"]==1
    assert out["blocker_occurrences"]==1 and out["publication_failures"]==1
    assert out["blocker_occurrences_by_code"]=={"B":1}
    assert out["report_failures"]==0

def _native(kind, **facts):
    return {"run_id":"run","event_type":kind,"logical_request_id":"lrq_test",**facts}

def test_validator_requires_alfred_identity_without_logical_request():
    warning={"run_id":"run","event_type":"warning_recorded","reason_code":""}
    blocker={"run_id":"run","event_type":"blocker_recorded"}
    out=analyze([warning,blocker])
    assert len(out["identity_errors"])==2

def test_validator_requires_creation_and_contiguous_attempt_numbers():
    def attempt(number, suffix):
        facts={"attempt_id":"att_"+suffix,"attempt_number":number,
               "model_name":"m","model_role":"duplicate_arbitration"}
        return [_native("model_attempt_started",**facts),
                _native("model_attempt_completed",**facts)]
    missing=analyze(attempt(1,"one"))
    assert any("logical_ai_request_created" in error for error in missing["lifecycle_errors"])
    skipped=analyze([_native("logical_ai_request_created")]+attempt(1,"one")+attempt(3,"three"))
    assert any("contiguous" in error for error in skipped["identity_errors"])
    starts_at_two=analyze([_native("logical_ai_request_created")]+attempt(2,"two"))
    assert any("contiguous" in error for error in starts_at_two["identity_errors"])

def test_validator_rejects_duplicate_terminal_events():
    facts={"attempt_id":"att_duplicate","attempt_number":1,
           "model_name":"m","model_role":"translation_generation"}
    created=_native("logical_ai_request_created")
    started=_native("model_attempt_started",**facts)
    completed=_native("model_attempt_completed",**facts)
    duplicate_completed=analyze([created,started,completed,dict(completed)])
    assert any("exactly one terminal event" in error for error in duplicate_completed["lifecycle_errors"])
    failed=_native("model_attempt_failed",error_class="upstream",error_terminal=True,**facts)
    duplicate_failed=analyze([created,started,failed,dict(failed)])
    assert any("exactly one terminal event" in error for error in duplicate_failed["lifecycle_errors"])

def test_publisher_missing_url_still_emits_identity_free_validation_failure(tmp_path):
    ledger=CanonicalEventLedger("run",tmp_path/"events")
    ledger.observe_publisher({"results":[{"title":"Present","status":"skipped",
        "reason":"missing_url_or_title"}]})
    rows=read(ledger.path)
    assert len(rows)==1 and rows[0]["event_type"]=="stage_failed"
    assert rows[0]["error_class"]=="validation" and rows[0]["error_terminal"] is True
    assert rows[0]["reason_code"]=="missing_url_or_title"
    assert "content_id" not in rows[0] and "correlation_id" not in rows[0]

def test_bob_client_initialization_failure_closes_logical_request(monkeypatch,tmp_path):
    from agents import bob
    from google import genai
    monkeypatch.setenv("GEMINI_API_KEY","fake")
    monkeypatch.setattr(genai,"Client",lambda **kwargs:(_ for _ in ()).throw(RuntimeError("init")))
    ledger=CanonicalEventLedger("run",tmp_path/"events"); install_active_ledger(ledger)
    try:
        text,status,attempted=bob.call_gemini("prompt",ledger_context=URL,model_chain=["model"])
    finally: clear_active_ledger()
    rows=read(ledger.path)
    assert text=="" and status.startswith("genai_import_or_client_error:") and attempted==[]
    assert [row["event_type"] for row in rows]==["logical_ai_request_created","stage_failed"]
    assert rows[0]["logical_request_id"]==rows[1]["logical_request_id"]
    assert rows[1]["error_class"]=="upstream" and rows[1]["error_terminal"] is True
    assert not any(row["event_type"].startswith("model_attempt_") for row in rows)

def test_deferred_semantic_validation_reuses_request_for_repair(tmp_path):
    ledger=CanonicalEventLedger("run",tmp_path/"events"); install_active_ledger(ledger)
    try:
        req=OperationalAIRequest("Menzo","duplicate_arbitration")
        first=req.start("model"); req.defer(first,0); req.resolve_deferred(False,error_terminal=False)
        second=req.start("model",repair=True); req.defer(second,0); req.resolve_deferred(True,error_terminal=True)
    finally: clear_active_ledger()
    rows=read(ledger.path); out=analyze(rows)
    assert out["logical_requests"]==1 and out["logical_requests_recovered"]==1
    assert out["repairs_started"]==1 and not out["lifecycle_errors"]

def _article(url, title):
    return {"source_url":url,"url":url,"title":title,"summary":title,
            "decision":"selected","priority":"hard","score":90,
            "published_at":datetime.now(timezone.utc).isoformat()}

def _board(*items):
    return {"selected":list(items),"pending":[],"skipped":[],"postprocess":{}}

def _production_fixture(monkeypatch,tmp_path,responses):
    import agents.menzo_policy_v93_15 as menzo
    from agents import source_body
    from google import genai
    monkeypatch.setenv("GEMINI_API_KEY","fake")
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    monkeypatch.setattr(menzo,"publisher_history_file",lambda:tmp_path/"history.json")
    monkeypatch.setattr(menzo,"record_gemini_attempt",lambda **kwargs: None)
    def hydrate(item):
        if source_body.contract_text(item): return True,"canonical_cache"
        text=(item.get("summary") or item.get("title") or "fixture") + " Complete factual source body with participants chronology context outcome and editorial details."*3
        item["canonical_source_body"]=source_body.contract_from_elements(item["source_url"],[{"type":"text","text":text}],
            {"stage":"extraction_finished","extraction_finished":True,"body_complete":True,
             "body_complete_reason":"fixture","clean_element_count":1,"root_text_chars":len(text),
             "extracted_text_chars":len(text),"root_coverage_ratio":1.0,
             "structured_article_body_chars":0,"structured_coverage_ratio":None,"truncation_access_markers":[]})
        return True,"fixture"
    monkeypatch.setattr(menzo.source_body,"hydrate",hydrate)
    calls=[]
    class Models:
        def generate_content(self,*,model,contents):
            calls.append((model,contents))
            value=responses.pop(0)
            return type("Response",(),{"text":json.dumps(value)})()
    monkeypatch.setattr(genai,"Client",lambda api_key:type("Client",(),{"models":Models()})())
    return menzo,calls

def _model_rows(rows):
    return [row for row in rows if row["event_type"].startswith("model_attempt") or
            row["event_type"] in {"logical_ai_request_created","repair_started"}]

def test_production_same_run_repair_success(monkeypatch,tmp_path):
    responses=[{"decision":"syntactic_only"},{"duplicate_groups":[]}]
    menzo,calls=_production_fixture(monkeypatch,tmp_path,responses)
    ledger=CanonicalEventLedger("run",tmp_path/"events"); install_active_ledger(ledger)
    out=_board(_article("https://a/1","CM Punk knee injury WWE"),_article("https://a/2","CM Punk suffers knee injury WWE"))
    try: menzo.apply_same_story_duplicate_guard(out,{})
    finally: clear_active_ledger()
    rows=_model_rows(read(ledger.path)); summary=analyze(rows)
    created=[r for r in rows if r["event_type"]=="logical_ai_request_created"]
    starts=[r for r in rows if r["event_type"]=="model_attempt_started"]
    failed=[r for r in rows if r["event_type"]=="model_attempt_failed"]
    assert len(calls)==2 and len(created)==1 and len(starts)==2
    assert [r["attempt_number"] for r in starts]==[1,2] and starts[0]["attempt_id"]!=starts[1]["attempt_id"]
    assert failed[0]["error_class"]=="validation" and failed[0]["error_terminal"] is False
    assert sum(r["event_type"]=="repair_started" for r in rows)==1
    assert sum(r["event_type"]=="model_attempt_completed" for r in rows)==1
    assert summary["logical_requests_recovered"]==1 and not summary["identity_errors"] and not summary["lifecycle_errors"]
    assert len(out["selected"])==2 and not out["skipped"]

def test_production_same_run_terminal_batch_then_separate_micro(monkeypatch,tmp_path):
    responses=[{"bad":1},{"bad":2},{"decision":"NO_DUPLICATE"}]
    menzo,calls=_production_fixture(monkeypatch,tmp_path,responses)
    ledger=CanonicalEventLedger("run",tmp_path/"events"); install_active_ledger(ledger)
    out=_board(_article("https://a/1","CM Punk knee injury WWE"),_article("https://a/2","CM Punk suffers knee injury WWE"))
    try: menzo.apply_same_story_duplicate_guard(out,{})
    finally: clear_active_ledger()
    rows=_model_rows(read(ledger.path)); summary=analyze(rows)
    requests={r["logical_request_id"] for r in rows if r.get("logical_request_id")}
    starts=[r for r in rows if r["event_type"]=="model_attempt_started"]
    batch_id=starts[0]["logical_request_id"]; batch=[r for r in rows if r.get("logical_request_id")==batch_id]
    micro=[r for r in starts if r["logical_request_id"]!=batch_id]
    failures=[r for r in batch if r["event_type"]=="model_attempt_failed"]
    assert len(calls)==3 and len(requests)==2 and [r["attempt_number"] for r in starts[:2]]==[1,2]
    assert [r["error_terminal"] for r in failures]==[False,True]
    assert all(r["error_class"]=="validation" for r in failures)
    assert len(micro)==1 and micro[0]["attempt_number"]==1 and micro[0]["attempt_id"] not in {r["attempt_id"] for r in starts[:2]}
    assert summary["logical_requests_terminal_failed"]==1 and not summary["identity_errors"] and not summary["lifecycle_errors"]
    assert len(out["selected"])==2 and not out["skipped"]

def test_production_recent_history_repair_success(monkeypatch,tmp_path):
    valid={"comparisons":[{"current_id":"c0","published_id":"p0","decision":"NO_MATCH","shared_facts":[],"new_fact":"","reason":"distinct"}]}
    responses=[{"decision":"syntactic_only"},valid]
    menzo,calls=_production_fixture(monkeypatch,tmp_path,responses)
    old={"source_url":"https://old/p","title":"CM Punk knee injury WWE","summary":"CM Punk knee injury WWE",
         "status":"published","published_at":datetime.now(timezone.utc).isoformat()}
    (tmp_path/"history.json").write_text(json.dumps([old]))
    ledger=CanonicalEventLedger("run",tmp_path/"events"); install_active_ledger(ledger)
    out=_board(_article("https://new/p","Breaking CM Punk knee injury WWE"))
    try: menzo.apply_recent_published_duplicate_guard(out)
    finally: clear_active_ledger()
    rows=_model_rows(read(ledger.path)); summary=analyze(rows)
    starts=[r for r in rows if r["event_type"]=="model_attempt_started"]
    assert len(calls)==2 and len({r["logical_request_id"] for r in starts})==1
    assert [r["attempt_number"] for r in starts]==[1,2] and starts[0]["attempt_id"]!=starts[1]["attempt_id"]
    assert summary["logical_requests_recovered"]==1 and not summary["identity_errors"] and not summary["lifecycle_errors"]
    assert len(out["selected"])==1 and not out["skipped"]

def test_production_cooldown_and_saved_call_cache_isolation(monkeypatch,tmp_path):
    menzo,calls=_production_fixture(monkeypatch,tmp_path,[])
    monkeypatch.setattr(menzo.duplicate_cache_v2,"failure_in_cooldown",lambda cache,key:True)
    ledger=CanonicalEventLedger("run",tmp_path/"cooldown-events"); install_active_ledger(ledger)
    values=[_article("https://a/1","CM Punk knee injury WWE"),_article("https://a/2","CM Punk suffers knee injury WWE")]
    try: menzo.apply_same_story_duplicate_guard(_board(*[dict(x) for x in values]),{})
    finally: clear_active_ledger()
    rows=_model_rows(read(ledger.path)); summary=analyze(rows)
    avoided=[r for r in rows if r["event_type"]=="model_attempt_avoided"]
    assert not calls and len(rows)==2 and len(avoided)==1
    assert avoided[0]["reason_code"]=="duplicate_failure_cooldown"
    assert not ({"attempt_id","attempt_number","latency_ms"}&set(avoided[0]))
    assert summary["logical_requests_avoided"]==1

    # A real cache hit replays legacy saved-call accounting but creates no canonical request.
    monkeypatch.setattr(menzo.duplicate_cache_v2,"failure_in_cooldown",lambda cache,key:False)
    responses=[{"duplicate_groups":[]}]; menzo,calls2=_production_fixture(monkeypatch,tmp_path,responses)
    install_active_ledger(CanonicalEventLedger("seed",tmp_path/"seed-events"))
    try: menzo.apply_same_story_duplicate_guard(_board(*[dict(x) for x in values]),{})
    finally: clear_active_ledger()
    cache_ledger=CanonicalEventLedger("cache",tmp_path/"cache-events"); install_active_ledger(cache_ledger)
    cached=_board(*[dict(x) for x in values])
    try: menzo.apply_same_story_duplicate_guard(cached,{})
    finally: clear_active_ledger()
    assert len(calls2)==1 and not cache_ledger.path.exists()
    assert cached["postprocess"]["gemini_duplicate_calls_avoided"]==1
