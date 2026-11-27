import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents.duplicate_pair_identity import article_id, same_run_pair_id, recent_history_pair_id
from modules.editorial_duplicate_links import (
    INDEX_NAME, MANIFEST_NAME, SCHEMA, refresh_duplicate_index, duplicate_link_records,
)
from modules.editorial_internal_links import resolve_internal_links, source_identity

ROOT_URL = "https://news.openwrestlingtv.com"
LOSER = "https://www.ringsidenews.com/rich-swann-snags-tna-bound-glory-title-shot-victory-917-impact/"
WINNER = "https://www.wrestlinginc.com/2261972/tna-bound-for-glory-2026-rich-swann-earns-spot-x-division-title-match/"
OTHER = "https://www.ringsidenews.com/other-article/"
CURRENT = "https://www.wrestlinginc.com/1234567/new-story/"
TARGET = ROOT_URL + "/tna/rich-swann/"
REPORT = "https://www.wrestleview.com/report/"
REPORT_TARGET = ROOT_URL + "/tna/report/"


def aid(url):
    return article_id({"url": url})


def relation(left=LOSER, right=WINNER, scope="recent_history", decision="DUPLICATE", **kw):
    a,b=aid(left),aid(right)
    return {"left_id":a,"right_id":b,"scope":scope,
            "pair_id":recent_history_pair_id(a,b) if scope=="recent_history" else same_run_pair_id(a,b),
            "decision":decision,"new_fact":None,**kw}


def package(url=LOSER, winner=WINNER, *, scope="recent_history", relations=None,
            authority="semantic_duplicate_gate", status="VALIDATED", **kw):
    rels=relations if relations is not None else [relation(url,winner,scope)]
    candidate={"url":url,"candidate_id":aid(url),"semantic_duplicate_of":aid(winner),
               "semantic_duplicate_scope":scope,"semantic_duplicate_evidence_pair_ids":[r["pair_id"] for r in rels]}
    return {"artifact_schema_version":SCHEMA,"candidate":candidate,"run_id":"run-1",
            "decision_authority":authority,"validation_status":status,"director_output":None,
            "semantic_duplicate_scope":scope,"semantic_duplicate_of":aid(winner),"relations":rels,**kw}


def append(root, p):
    state=root/"state/newsroom"
    folder=state/"material_chain"/"run"/"candidate"
    folder.mkdir(parents=True,exist_ok=True)
    data=json.dumps(p).encode()
    sha=hashlib.sha256(data).hexdigest()
    path=folder/("editorial-director-active-"+sha+".json")
    path.write_bytes(data)
    row={"producer_agent":"Menzo","producer_stage":"selection","semantic_roles":["selection_decision"],
         "artifact_schema_version":{"status":"known","version":SCHEMA},"persistence_class":"immutable_archive",
         "mutation_mode":"immutable","authority_claims":[{"purpose":"pipeline_observability","level":"authoritative"}],
         "path":str(path.relative_to(root)),"size_bytes":len(data),"sha256":sha,
         "run_id":p["run_id"],"article_id":p["candidate"]["candidate_id"]}
    with (state/MANIFEST_NAME).open("a") as f:f.write(json.dumps(row)+"\n")
    return state,path


def published(url=WINNER, id=123, link=TARGET, status="publish"):
    return {"source_url":url,"wp_post_id":id,"wp_link":link,"status":status}


def records(root, history=None):
    state=root/"state/newsroom"
    return duplicate_link_records(refresh_duplicate_index(state,root), {"winner":published()} if history is None else history)


def wp_row(id=123, link=TARGET, status="publish"):
    return {"id":id,"status":status,"link":link,"type":"post","content":{"protected":False}}


def resolve(body, rec, history=None, report=None, wp=None):
    calls=[]
    def fetch(url, **kw):
        calls.append((url,kw))
        return SimpleNamespace(status_code=200,json=lambda:[wp_row()] if wp is None else wp)
    out,d=resolve_internal_links(body,history if history is not None else {"w":published()},source_url=CURRENT,
            root=ROOT_URL,enabled=True,fetch=fetch,duplicate_records=rec,report_records=report)
    return out,d,calls


@pytest.mark.parametrize("scope",["same_run","recent_history"])
def test_direct_validated_pair_and_byte_preservation(tmp_path,scope):
    append(tmp_path,package(scope=scope))
    rec=records(tmp_path)
    assert list(rec)==[source_identity(LOSER)]
    body=f'<p>prima <a href="{LOSER}">Rich Swann</a>.</p>\n<p><a href="{LOSER}" target="_blank">fonte</a></p>'
    out,d,calls=resolve(body,rec)
    assert out==body.replace(f'href="{LOSER}">',f'href="{TARGET}">')
    assert d["duplicate_matched"]==d["duplicate_rewritten"]==1 and len(calls)==1


def test_index_incremental_and_conflicting_later_relation(tmp_path):
    state,_=append(tmp_path,package())
    rec=records(tmp_path)
    before=(state/INDEX_NAME).read_bytes()
    assert rec and records(tmp_path)==rec
    assert (state/INDEX_NAME).read_bytes()==before
    append(tmp_path,package(authority="editorial_director",relations=[relation(decision="NO_MATCH")]))
    assert records(tmp_path)=={}
    assert json.loads((state/INDEX_NAME).read_text())["stats"]["artifacts"]==2


@pytest.mark.parametrize("decision",["MATERIAL_UPDATE","REAL_UPDATE","DISTINCT_STORY","NO_MATCH","RELATED"])
def test_nonduplicate_not_alias(tmp_path,decision):
    append(tmp_path,package(relations=[relation(decision=decision)]))
    assert records(tmp_path)=={}


@pytest.mark.parametrize("mode",["unvalidated","shadow","transitive","reverse","wrong_evidence","covered_update","new_fact","different_winner"])
def test_only_explicit_direct_validated_gate(tmp_path,mode):
    p=package()
    if mode=="unvalidated":p["validation_status"]="FAILED"
    elif mode=="shadow":p["decision_authority"]="editorial_director_shadow"
    elif mode=="transitive":p=package(relations=[relation(LOSER,OTHER,"same_run"),relation(OTHER,WINNER)])
    elif mode=="reverse":p=package(relations=[relation(WINNER,LOSER)])
    elif mode=="wrong_evidence":p["candidate"]["semantic_duplicate_evidence_pair_ids"]=[]
    elif mode=="covered_update":p["candidate"]["semantic_duplicate_reason"]="semantic_same_run_duplicate_covered_by_update"
    elif mode=="new_fact":p["relations"][0]["new_fact"]="different development"
    elif mode=="different_winner":p["candidate"]["semantic_duplicate_of"]=aid(OTHER)
    append(tmp_path,p)
    assert records(tmp_path)=={}


def test_multiple_winners_and_nonterminal_representative(tmp_path):
    append(tmp_path,package())
    append(tmp_path,package(winner=OTHER))
    assert records(tmp_path,{"w":published(),"o":published(OTHER,456,ROOT_URL+"/other/")})=={}
    d=tmp_path/"separate"
    append(d,package())
    append(d,package(url=WINNER,winner=OTHER))
    rec=records(d,{"w":published(),"o":published(OTHER,456,ROOT_URL+"/other/")})
    assert source_identity(LOSER) not in rec


def test_query_and_normalized_id_collisions(tmp_path):
    append(tmp_path,package())
    assert records(tmp_path,{"w":published(WINNER+"?id=2")})=={}
    assert records(tmp_path,{"w":published(),"w2":published(WINNER+"?id=2",456)})=={}
    append(tmp_path,package(url=LOSER+"?edition=2",authority="editorial_director"))
    assert records(tmp_path)=={}


def test_loser_already_published_never_duplicate(tmp_path):
    append(tmp_path,package())
    assert records(tmp_path,{"w":published(),"l":published(LOSER,456,ROOT_URL+"/loser/")})=={}
    assert records(tmp_path,{})=={}


def test_bad_manifest_digest_does_not_use_stale_index(tmp_path):
    state,_=append(tmp_path,package())
    assert records(tmp_path)
    p=package(winner=OTHER)
    _,path=append(tmp_path,p)
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError):records(tmp_path)
    assert json.loads((state/INDEX_NAME).read_text())["stats"]["artifacts"]==1


def test_manifest_replacement_rebuilds(tmp_path):
    state,_=append(tmp_path,package())
    assert records(tmp_path)
    manifest=state/MANIFEST_NAME
    manifest.unlink()
    append(tmp_path,package(authority="editorial_director"))
    assert records(tmp_path)=={}


def test_news_report_duplicate_share_wp_request(tmp_path):
    append(tmp_path,package())
    rec=records(tmp_path)
    report={source_identity(REPORT,report=True):[published(REPORT,456,REPORT_TARGET)]}
    body=f'<p><a href="{LOSER}">alias</a> <a href="{WINNER}">exact</a> <a href="{REPORT}">report</a></p>'
    out,d,calls=resolve(body,rec,report=report,wp=[wp_row(),wp_row(456,REPORT_TARGET)])
    assert out==body.replace(LOSER,TARGET).replace(WINNER,TARGET).replace(REPORT,REPORT_TARGET)
    assert d["matched"]==3 and d["report_rewritten"]==1 and d["duplicate_rewritten"]==1
    assert len(calls)==1 and calls[0][1]["params"]["include"]=="123,456"
    report[source_identity(LOSER)]=[published(LOSER,456,REPORT_TARGET)]
    out,d,calls=resolve(body,rec,report=report,wp=[wp_row(),wp_row(456,REPORT_TARGET)])
    assert d["duplicate_rewritten"]==0 and d["report_rewritten"]==2


def test_wp_draft_and_conflicting_history(tmp_path):
    append(tmp_path,package())
    body=f'<p><a href="{LOSER}">alias</a></p>'
    assert resolve(body,records(tmp_path),wp=[wp_row(status="draft")])[0]==body
    rec=records(tmp_path,{"w":published(),"bad":published(id=999,link=ROOT_URL+"/other/")})
    out,d,calls=resolve(body,rec)
    assert out==body and not calls
    rec=records(tmp_path,{"w":published(status="draft")})
    assert resolve(body,rec)[0]==body


def test_publisher_payload_integration(tmp_path,monkeypatch):
    from agents import publisher
    from modules import wordpress_tags
    state,_=append(tmp_path,package())
    monkeypatch.setattr(publisher,"NEWSROOM_STATE_DIR",state)
    monkeypatch.setattr(publisher,"ROOT",tmp_path)
    monkeypatch.setattr(publisher,"DRY_RUN",False)
    monkeypatch.setattr(publisher,"POST_STATUS","publish")
    monkeypatch.setattr(publisher,"wp_root",lambda:ROOT_URL)
    monkeypatch.setattr(publisher,"PUBLISHED_DIR",state/"published")
    monkeypatch.setattr(publisher,"REVIEW_DIR",state/"review")
    monkeypatch.setattr(publisher,"PUBLISHED_TRACE_DIR",state/"traces")
    monkeypatch.setattr(publisher,"candidate_featured_image",lambda *_:"")
    monkeypatch.setattr(publisher,"resolve_category_ids",lambda *_:[])
    monkeypatch.setattr(wordpress_tags,"assign_tags",lambda *_a,**_k:None)
    monkeypatch.setattr(publisher.requests,"get",lambda *_a,**_k:SimpleNamespace(status_code=200,json=lambda:[wp_row()]))
    payloads=[]
    def publish(method,url,**kw):
        assert method=="post"
        payloads.append(kw["json"])
        return SimpleNamespace(status_code=201,json=lambda:{"id":987,"link":ROOT_URL+"/new/"})
    monkeypatch.setattr(publisher,"wp_request",publish)
    article={"source_url":CURRENT,"source":"wrestlinginc","title_it":"Nuovo articolo","body_html":f'<p><a href="{LOSER}">Rich Swann</a></p>'}
    result=publisher.publish_article(article,{"w":published()},True)
    assert result["internal_links"]["duplicate_rewritten"]==1
    assert f'href="{TARGET}">Rich Swann' in payloads[0]["content"]
    assert f'href="{CURRENT}" target="_blank"' in payloads[0]["content"]
