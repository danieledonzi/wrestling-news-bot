import json
import sys
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from agents import menzo_policy_v93_15 as menzo
from agents import publisher, source_body
from agents import publisher_history as publisher_history_retention

FIXTURE=Path(__file__).parent/"fixtures/v95_20_full_body/vaquer_lynch_raw.json"

def board(*items): return {"selected":list(items),"pending":[],"skipped":[],"postprocess":{}}

def canonical(text):
    padded=(text + " This complete source report includes the full sequence, participants, timing, outcome, quotations, context, and all editorial facts needed for comparison.")
    return source_body.contract_from_elements("https://source.test/article", [{"type":"text","text":padded}], {"stage":"extraction_finished","extraction_finished":True,"body_complete":True,"body_complete_reason":"verified_test_fixture","clean_element_count":1,"root_text_chars":len(text),"extracted_text_chars":len(text),"root_coverage_ratio":1.0,"structured_article_body_chars":0,"structured_coverage_ratio":None,"truncation_access_markers":[]})

def with_body(item, text):
    return {**item, "canonical_source_body":canonical(text)}

def force_suspicious(monkeypatch):
    monkeypatch.setattr(menzo.duplicate_scorer,"score_pair",lambda *a,**k:{"score":.9,"threshold":.6,"above_threshold":True,"exact_duplicate":False,"exact_reason":"","signal_breakdown":{}})

def isolate(monkeypatch,tmp_path,history=None):
    monkeypatch.setattr(menzo,"MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE",tmp_path/"cache.json")
    monkeypatch.setattr(menzo,"publisher_history_file",lambda:tmp_path/"history.json")
    if history is not None: (tmp_path/"history.json").write_text(json.dumps(history),encoding="utf-8")

def test_full_body_precedes_rss_summary_in_gemini_prompt(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); force_suspicious(monkeypatch); prompts=[]
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:prompts.append(p) or ({"duplicate_groups":[]},m))
    a=with_body({"url":"https://a","title":"Same segment","summary":"MISLEADING RSS A"},"Complete body A with the actual return segment and every reported fact.")
    b=with_body({"url":"https://b","title":"Same segment report","summary":"MISLEADING RSS B"},"Complete body B with the actual return segment and every reported fact.")
    menzo.apply_same_story_duplicate_guard(board(a,b))
    assert len(prompts)==1 and "Complete body A" in prompts[0] and "Complete body B" in prompts[0]
    assert "MISLEADING RSS" not in prompts[0] and "body_excerpt" not in prompts[0]

def test_same_run_duplicate_keeps_deterministic_richer_body(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); force_suspicious(monkeypatch)
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same segment"}]},m))
    short=with_body({"url":"https://short","title":"Identical return title","source":"equal"},"Vaquer and Lynch returned to challenge Morgan.")
    rich=with_body({"url":"https://rich","title":"Identical return title","source":"equal"},"Vaquer and Lynch returned to challenge Morgan. Lynch entered first. Vaquer followed. Morgan retreated after both challenges and the crowd reacted loudly. The report also fully describes the opening exchange and the closing shot.")
    out=board(short,rich); menzo.apply_same_story_duplicate_guard(out)
    assert [x["url"] for x in out["selected"]]==["https://rich"]
    assert out["skipped"][0]["reason"]=="skip:duplicate_same_run"

def test_vaquer_lynch_recent_history_duplicate_is_blocked_with_audit(monkeypatch,tmp_path):
    case=json.loads(FIXTURE.read_text()); old=with_body({**case["published"],"published_at":datetime.now(timezone.utc).isoformat()},case["published"]["cleaned_full_text"]); candidate=with_body(case["candidate"],case["candidate"]["body_text"])
    isolate(monkeypatch,tmp_path,[old]); force_suspicious(monkeypatch); prompts=[]
    response={"comparisons":[{"current_id":"c0","published_id":"p0","decision":"DUPLICATE","shared_facts":["Vaquer and Lynch returned and challenged Morgan in the same Raw segment"],"new_fact":"","reason":"Only entrances and crowd reaction were added"}]}
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:prompts.append(p) or (response,m))
    out=board(candidate); menzo.apply_recent_published_duplicate_guard(out)
    assert out["selected"]==[] and out["skipped"][0]["menzo_duplicate_decision"]==case["expected_decision"]
    audit=out["skipped"][0]["menzo_duplicate_audit"]
    assert audit["candidate_url"]==case["candidate"]["source_url"] and audit["compared_url"]==old["source_url"] and audit["reason"]
    assert source_body.contract_text(old) in prompts[0] and source_body.contract_text(candidate) in prompts[0]

def test_concrete_later_fact_is_material_update(monkeypatch,tmp_path):
    current_dt=datetime.now(timezone.utc); old=with_body({"source_url":"https://old","title_it":"Punk injured","status":"published","published_at":(current_dt-timedelta(hours=2)).isoformat()},"CM Punk suffered a knee injury and his status was unknown.")
    cur=with_body({"source_url":"https://new","title":"Punk surgery confirmed","published_at":current_dt.isoformat()},"Today WWE officially confirmed CM Punk underwent knee surgery after the earlier injury.")
    isolate(monkeypatch,tmp_path,[old]); force_suspicious(monkeypatch)
    response={"comparisons":[{"current_id":"c0","published_id":"p0","decision":"MATERIAL_UPDATE","temporal_basis":"BECAME_KNOWN_AFTER","temporal_evidence_excerpt":"Today WWE officially confirmed CM Punk underwent knee surgery","shared_facts":["knee injury"],"new_fact":"Today WWE officially confirmed CM Punk underwent knee surgery","reason":"Surgery became known after publication"}]}
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:(response,m))
    out=board(cur); menzo.apply_recent_published_duplicate_guard(out)
    assert out["selected"][0]["menzo_duplicate_decision"]=="REAL_UPDATE" and out["selected"][0]["menzo_new_fact"]

def test_unavailable_body_fails_closed_without_gemini(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc).isoformat(); old={"source_url":"https://old","title_it":"Same return","summary":"feed only","status":"published","published_at":now}
    cur={"source_url":"https://new","title":"Same return","summary":"candidate feed only"}
    isolate(monkeypatch,tmp_path,[old]); force_suspicious(monkeypatch); calls=[]
    monkeypatch.setattr(menzo.source_body,"hydrate",lambda item:(False,"incomplete_extraction")); monkeypatch.setattr(menzo,"call_gemini_json_model",lambda *a,**k:calls.append(1))
    out=board(cur); menzo.apply_recent_published_duplicate_guard(out)
    assert calls==[] and out["skipped"][0]["reason"]=="skip:duplicate_arbitration_unresolved"

def test_publisher_persists_complete_cleaned_text_and_trace(monkeypatch,tmp_path):
    history={}; monkeypatch.setattr(publisher,"DRY_RUN",False); monkeypatch.setattr(publisher,"POST_STATUS","publish")
    monkeypatch.setattr(publisher,"PUBLISHED_DIR",tmp_path/"published"); monkeypatch.setattr(publisher,"REVIEW_DIR",tmp_path/"review"); monkeypatch.setattr(publisher,"PUBLISHED_TRACE_DIR",tmp_path/"traces")
    monkeypatch.setattr(publisher,"resolve_category_ids",lambda x:[]); monkeypatch.setattr(publisher,"wp_request",lambda *a,**k:type("R",(),{"status_code":201,"json":lambda s:{"id":7,"link":"https://wp/7"}})())
    article=with_body({"source_url":"https://source/article","title_it":"Titolo","source":"Test","body_html":"<p>Complete published editorial body.</p><p>Second factual paragraph.</p>"},"Complete original source body with every factual paragraph from the source article.")
    result=publisher.publish_article(article,history,True)
    saved=next(iter(history.values()))
    assert "published_cleaned_full_text" not in saved and "source_cleaned_full_text" not in saved
    assert saved["canonical_source_body"]==article["canonical_source_body"]
    trace=json.loads(next((tmp_path/"traces").glob("*.json")).read_text())
    assert trace["source_cleaned_full_text"]==source_body.contract_text(article)
    assert trace["cleaned_full_text"]=="Complete published editorial body. Second factual paragraph."
    assert trace["published_cleaned_full_text"]=="Complete published editorial body. Second factual paragraph."
    assert result["canonical_source_body"]==saved["canonical_source_body"]

def test_lazy_hydration_uses_shared_bob_contract_before_prompt(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); force_suspicious(monkeypatch); prompts=[]; hydrated=[]
    def hydrate(item):
        hydrated.append(item["url"]); item["canonical_source_body"]=canonical("Fetched complete body for "+item["url"]+" with the same central return segment and full factual sequence."); return True,"bob_source_extraction"
    monkeypatch.setattr(menzo.source_body,"hydrate",hydrate)
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:prompts.append(p) or ({"duplicate_groups":[]},m))
    out=board({"url":"https://feed/a","title":"Return","summary":"RSS A"},{"url":"https://feed/b","title":"Return report","summary":"RSS B"})
    menzo.apply_same_story_duplicate_guard(out)
    assert hydrated==["https://feed/a","https://feed/b"] and len(prompts)==1
    assert "Fetched complete body" in prompts[0] and "RSS A" not in prompts[0]

def test_explicit_no_match_is_authorized_cached_and_auditable(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc).isoformat(); old=with_body({"source_url":"https://old","title_it":"Raw return","status":"published","published_at":now},"A prior Raw return segment involving different wrestlers and a different challenge.")
    current=with_body({"source_url":"https://new","title":"Raw return follow-up"},"A separate Raw segment involving a new injury announcement and unrelated participants.")
    isolate(monkeypatch,tmp_path,[old]); force_suspicious(monkeypatch); calls=[]
    response={"comparisons":[{"current_id":"c0","published_id":"p0","decision":"NO_MATCH","shared_facts":["Raw episode"],"new_fact":"","reason":"Different participants and central event"}]}
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:calls.append(p) or (response,m))
    first=board(dict(current)); menzo.apply_recent_published_duplicate_guard(first)
    second=board(dict(current)); menzo.apply_recent_published_duplicate_guard(second)
    article=second["selected"][0]
    assert len(calls)==1 and article["menzo_duplicate_decision"]=="NO_MATCH" and article["menzo_authorized"] is True
    assert article["menzo_duplicate_comparisons"][0]["compared_url"].rstrip("/")=="https://old"
    cached_audit=second["postprocess"]["duplicate_suspicion_audit"][0]
    assert cached_audit["cache"]=="hit" and cached_audit["reason"]=="Different participants and central event" and cached_audit["shared_facts"]==["Raw episode"]
    assert publisher.valid_menzo_duplicate_resolution(article)[0] is True

def test_arbitrary_body_field_is_not_a_complete_contract(monkeypatch):
    item={"source_url":"https://source","body_text":"A long but untrusted field "*30,"content":"also untrusted"*30}
    assert menzo.complete_cleaned_article_body(item)==""
    monkeypatch.setattr(menzo.source_body,"hydrate",lambda record:(False,"incomplete_extraction"))
    assert menzo.hydrate_complete_article_bodies([item])[0] is False

def test_legacy_recent_history_is_lazily_backfilled_atomically(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc).isoformat(); legacy={"source_url":"https://old","title_it":"Legacy return","status":"published","published_at":now}
    current={"source_url":"https://new","title":"Legacy return details"}
    isolate(monkeypatch,tmp_path,[legacy]); force_suspicious(monkeypatch)
    def hydrate(item):
        item["canonical_source_body"]=canonical("Hydrated original source body for "+item["source_url"]+" covering the complete return segment."); return True,"bob_source_extraction"
    monkeypatch.setattr(menzo.source_body,"hydrate",hydrate)
    response={"comparisons":[{"current_id":"c0","published_id":"p0","decision":"DUPLICATE","shared_facts":["same return"],"new_fact":"","reason":"same segment"}]}
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:(response,m))
    out=board(current); menzo.apply_recent_published_duplicate_guard(out)
    migrated=json.loads((tmp_path/"history.json").read_text())
    assert source_body.valid_contract(migrated[0]["canonical_source_body"])
    assert out["skipped"][0]["menzo_duplicate_decision"]=="DUPLICATE"

def test_extraction_finished_does_not_prove_complete_body():
    from agents import bob
    partial=("This teaser paragraph describes the opening of the wrestling story but withholds the remaining report. "*7)+" Subscribe to continue reading the remaining content."
    html=f"<html><body><article><p>{partial}</p></article></body></html>"
    _meta,_raw,elements,_removed,diagnostics=bob.extract_elements("https://source.test/paywall",html)
    assert diagnostics["extraction_finished"] is True and diagnostics["body_complete"] is False
    assert "truncation_or_access_marker" in diagnostics["body_incomplete_reasons"]
    assert source_body.contract_from_elements("https://source.test/paywall",elements,diagnostics) is None

def test_structured_article_body_can_verify_document_fallback():
    from agents import bob
    body=" ".join(["Becky Lynch returned first before Stephanie Vaquer appeared to challenge Liv Morgan on Raw."]*8)
    payload=json.dumps({"@context":"https://schema.org","@type":"NewsArticle","articleBody":body})
    html=f'<html><head><script type="application/ld+json">{payload}</script></head><body><div><p>{body}</p></div></body></html>'
    _meta,_raw,elements,_removed,diagnostics=bob.extract_elements("https://source.test/structured",html)
    assert diagnostics["extraction_finished"] is True and diagnostics["structured_article_body_chars"]>=len(body)-5
    assert diagnostics["body_complete"] is True
    assert source_body.valid_contract(source_body.contract_from_elements("https://source.test/structured",elements,diagnostics))

def test_richer_winner_ignores_repeated_padding(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path); force_suspicious(monkeypatch)
    monkeypatch.setattr(menzo,"call_gemini_json_model",lambda p,m,**k:({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same event"}]},m))
    repetitive=with_body({"url":"https://repeat","title":"Identical title","source":"equal"},("The return happened on Raw. "*25))
    factual=with_body({"url":"https://facts","title":"Identical title","source":"equal"},"Becky Lynch returned on Raw, confronted Liv Morgan, issued a title challenge, and Stephanie Vaquer followed with a second challenge after SummerSlam.")
    out=board(repetitive,factual); menzo.apply_same_story_duplicate_guard(out)
    assert out["selected"][0]["url"]=="https://facts"

def test_recent_validator_rejects_semantically_empty_comparisons():
    current=menzo.compact_candidate_record(with_body({"source_url":"https://new"},"WWE confirmed a concrete surgery after the earlier injury report."),"c0")
    old=menzo.compact_published_record(with_body({"source_url":"https://old"},"The earlier publication reported an injury with no surgery known."),"p0")
    cur={"c0":current}; pub={"p0":old}
    invalid=[
        {"decision":"NO_MATCH","shared_facts":[],"new_fact":"","reason":""},
        {"decision":"DUPLICATE","shared_facts":[],"new_fact":"","reason":"same"},
        {"decision":"DUPLICATE","shared_facts":["injury"],"new_fact":"extra detail","reason":"same"},
        {"decision":"MATERIAL_UPDATE","shared_facts":["injury"],"new_fact":"WWE confirmed surgery","reason":"new","temporal_basis":"BECAME_KNOWN_AFTER","temporal_evidence_excerpt":"This became known after the earlier publication"},
        {"decision":"NO_MATCH","shared_facts":[],"new_fact":"invented","reason":"different"},
    ]
    for comparison in invalid:
        payload={"comparisons":[{"current_id":"c0","published_id":"p0",**comparison}]}
        assert menzo.validate_recent_history_batch(payload,cur,pub)[0] is None

def test_unrelated_structured_body_cannot_verify_partial_dom():
    from bs4 import BeautifulSoup
    from agents import bob
    visible="Visible teaser about Becky Lynch and Stephanie Vaquer. "*5
    unrelated="A completely different article about financial markets, quarterly revenue, investors, corporate debt, and regulatory filings. "*6
    payload=json.dumps({"@context":"https://schema.org","@type":"NewsArticle","articleBody":unrelated})
    soup=BeautifulSoup(f'<html><head><script type="application/ld+json">{payload}</script></head><body><p>{visible}</p></body></html>',"html.parser")
    diagnostics=bob.assess_body_completeness(soup.body,[{"type":"text","text":visible}],soup)
    assert diagnostics["structured_coverage_ratio"] is not None and diagnostics["structured_token_overlap_ratio"] < .75
    assert diagnostics["body_complete"] is False


@pytest.mark.parametrize("wall_text",["Continue reading with a subscription","Unlock this article"])
def test_review_access_wall_examples_force_incomplete_even_with_high_coverage(wall_text):
    from agents import bob
    article=("A complete-looking wrestling paragraph with extensive event facts and detailed chronology. "*8)+" "+wall_text
    html=f"<html><body><article><p>{article}</p></article></body></html>"
    _meta,_raw,_elements,_removed,diagnostics=bob.extract_elements("https://source.test/wall",html)
    assert diagnostics["root_coverage_ratio"]>=.55
    assert diagnostics["truncation_access_markers"] and diagnostics["body_complete"] is False


@pytest.mark.parametrize("signal",["paywall","subscriber-only","locked-content","metered-content","premium-content"])
def test_access_wall_dom_signals_force_incomplete(signal):
    from agents import bob
    article="A complete-looking wrestling report with detailed facts, chronology, quotations, participants, and outcome. "*8
    html=f'<html><body><article><p>{article}</p><div class="{signal}">Restricted</div></article></body></html>'
    _meta,_raw,_elements,_removed,diagnostics=bob.extract_elements("https://source.test/wall-class",html)
    assert diagnostics["access_wall_dom_signals"] and diagnostics["body_complete"] is False


def test_publisher_history_retains_recent_canonical_and_prunes_duplicate_copies():
    now=datetime.now(timezone.utc); contract=canonical("Recent complete source article for bounded retention.")
    record={"source_url":"https://recent","wp_post_id":7,"wp_link":"https://wp/7","status":"publish","published_at":now.isoformat(),"title_it":"Title","source":"Source","story_signature":"sig","canonical_source_body":contract,"source_cleaned_full_text":contract["cleaned_full_text"],"published_cleaned_full_text":"Final editorial body","body_html":"<p>duplicate</p>"}
    cleaned=publisher_history_retention.prune_history({"key":record},now=now)["key"]
    assert cleaned["canonical_source_body"]==contract
    assert not ({"source_cleaned_full_text","published_cleaned_full_text","body_html"} & set(cleaned))
    assert {key:cleaned[key] for key in ("source_url","wp_post_id","wp_link","status","published_at","title_it","source","story_signature")}=={key:record[key] for key in ("source_url","wp_post_id","wp_link","status","published_at","title_it","source","story_signature")}


def test_publisher_history_prunes_old_bodies_for_dict_and_legacy_list(monkeypatch):
    now=datetime.now(timezone.utc); old=(now-timedelta(hours=73)).isoformat(); contract=canonical("Old complete source article that must age out.")
    record={"source_url":"https://old","wp_post_id":9,"wp_link":"https://wp/9","status":"publish","published_at":old,"title_it":"Old","source":"Source","story_signature":"old-sig","canonical_source_body":contract,"source_cleaned_full_text":contract["cleaned_full_text"],"published_cleaned_full_text":"Old final body"}
    monkeypatch.setenv("PUBLISHER_CANONICAL_BODY_RETENTION_HOURS","72")
    for history in ({"old":record},[record]):
        cleaned=publisher_history_retention.prune_history(history,now=now)
        item=cleaned["old"] if isinstance(cleaned,dict) else cleaned[0]
        assert not (publisher_history_retention.HEAVY_BODY_FIELDS & set(item))
        assert item["source_url"]=="https://old" and item["wp_post_id"]==9 and item["story_signature"]=="old-sig"


def test_backfill_does_not_restore_body_outside_retention(monkeypatch,tmp_path):
    old_stamp=(datetime.now(timezone.utc)-timedelta(hours=80)).isoformat(); contract=canonical("Hydrated source body outside retention.")
    path=tmp_path/"history.json"; path.write_text(json.dumps([{"source_url":"https://old","published_at":old_stamp,"wp_post_id":3,"status":"publish"}]))
    menzo.persist_history_body_backfill([{"source_url":"https://old","canonical_source_body":contract}],path)
    saved=json.loads(path.read_text())[0]
    assert "canonical_source_body" not in saved and saved["wp_post_id"]==3


def test_backfill_write_prunes_unrelated_expired_heavy_fields_and_preserves_shape(monkeypatch,tmp_path):
    now=datetime.now(timezone.utc); recent_contract=canonical("Newly hydrated recent source body with complete factual reporting and chronology."*3); expired_contract=canonical("Expired unrelated source body with complete factual reporting and chronology."*3)
    recent={"source_url":"https://recent","published_at":now.isoformat(),"wp_post_id":10,"wp_link":"https://wp/10","status":"publish","title_it":"Recent","source":"Source","story_signature":"recent-sig"}
    expired={"source_url":"https://expired","published_at":(now-timedelta(hours=80)).isoformat(),"wp_post_id":11,"wp_link":"https://wp/11","status":"publish","title_it":"Expired","source":"Source","story_signature":"expired-sig","canonical_source_body":expired_contract,"source_cleaned_full_text":expired_contract["cleaned_full_text"],"published_cleaned_full_text":"final copy","body_html":"<p>heavy</p>","extracted_text":"heavy extracted copy","content":"heavy content copy"}
    monkeypatch.setenv("PUBLISHER_CANONICAL_BODY_RETENTION_HOURS","72")
    for index,history in enumerate(({"recent":recent,"expired":expired},[recent,expired])):
        path=tmp_path/f"history-{index}.json"; path.write_text(json.dumps(history))
        menzo.persist_history_body_backfill([{"source_url":"https://recent","canonical_source_body":recent_contract}],path)
        saved=json.loads(path.read_text()); assert isinstance(saved,type(history))
        recent_saved=saved["recent"] if isinstance(saved,dict) else saved[0]; expired_saved=saved["expired"] if isinstance(saved,dict) else saved[1]
        assert recent_saved["canonical_source_body"]==recent_contract
        assert not (publisher_history_retention.HEAVY_BODY_FIELDS & set(expired_saved))
        for key in ("source_url","published_at","wp_post_id","wp_link","status","title_it","source","story_signature"):
            assert expired_saved[key]==expired[key]


def test_older_descriptive_detail_in_newer_article_is_not_material_update():
    now=datetime.now(timezone.utc)
    old=with_body({"source_url":"https://old-detail","published_at":(now-timedelta(hours=2)).isoformat()},"Becky Lynch returned in the Raw segment and challenged Liv Morgan before Stephanie Vaquer followed.")
    current=with_body({"source_url":"https://new-detail","published_at":now.isoformat()},"Becky Lynch returned in the same Raw segment wearing a red coat and challenged Liv Morgan before Stephanie Vaquer followed.")
    cur=menzo.compact_candidate_record(current,"c0"); pub=menzo.compact_published_record(old,"p0")
    response={"comparisons":[{"current_id":"c0","published_id":"p0","decision":"MATERIAL_UPDATE","shared_facts":["same Raw return segment"],"new_fact":"Becky Lynch wore a red coat","temporal_basis":"BECAME_KNOWN_AFTER","temporal_evidence_excerpt":"Becky Lynch returned in the same Raw segment wearing a red coat","reason":"The later article adds the coat description"}]}
    decisions,error=menzo.validate_recent_history_batch(response,{"c0":cur},{"p0":pub})
    assert decisions is None and error=="invalid_temporal_evidence"
