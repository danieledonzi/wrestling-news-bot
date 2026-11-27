import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.editorial_internal_links import resolve_internal_links, source_identity
from modules.report_internal_links import load_report_link_records, refresh_report_aliases, INDEX_NAME

ROOT = "https://news.openwrestlingtv.com"
SRC = "https://www.wrestlinginc.com/2329268/aew-collision-thanksgiving-november-26-2027-results/"
CANONICAL = "https://www.wrestleview.com/top-story/398441-aew-collision-thanksgiving-night-results-11-26-26-title-match-continental-classic-tournament-matches"
NEWS = "https://www.wrestlinginc.com/2329551/aew-continental-classic-2026-update-night-4-thanksgiving-collision/"
GARCIA = "https://www.wrestlinginc.com/2329444/daniel-garcia-injury/"
TARGET = ROOT + "/aew/aew-collision-del-26-novembre-2026-risultati-e-momenti-salienti/"
KEY = "aew_collision_2026_11_26"
STAMP = "Thu, 26 Nov 2026 23:00:00 +0000"
TITLE = "AEW Collision Thanksgiving Results 11/26/26 W/ Live Updates"


def write(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v), encoding="utf-8")


def observation(**kw):
    return {"url":SRC,"source":"wrestlinginc","title":TITLE,"published":STAMP,
            "show_hint":"AEW Collision","reason":"report_source_not_preferred",
            "original_report_reason":"weekly_show_results",**kw}


def published(**kw):
    return {"report_key":KEY,"source_url":CANONICAL,"published_at":"2026-11-27T07:40:28+00:00",
            "wp_post_id":15959,"wp_link":TARGET,
            "report_completion":{"version":"totem-r01-completion-v1","report_key":KEY,"date":"2026-11-26","report_id":"aew_collision"},**kw}


@pytest.fixture
def env(tmp_path):
    s=tmp_path/"state"; c=Path(__file__).resolve().parents[1]/"config"
    write(s/"simone_report_history.json",{KEY:published()})
    write(s/"massy_board_latest.json",{"hard_skipped":[observation()]})
    return s,c


def wp_row(post_id=15959,link=TARGET,status="publish"):
    return {"id":post_id,"link":link,"status":status,"type":"post","content":{"protected":False}}


def resolve(body, records, rows=None, news=None):
    calls=[]
    def fetch(url, **kw):
        calls.append((url,kw))
        return SimpleNamespace(status_code=200,json=lambda: [wp_row()] if rows is None else rows)
    out,d=resolve_internal_links(body,news or {},source_url=NEWS,root=ROOT,enabled=True,fetch=fetch,report_records=records)
    return out,d,calls


def test_real_collision_case_and_same_source(env):
    s,c=env
    rec=load_report_link_records(s,c)
    body=f'<p><a href="{SRC}">Collision</a> / <a href="{CANONICAL}">risultati</a>.</p>'
    out,d,calls=resolve(body,rec)
    assert out==body.replace(SRC,TARGET).replace(CANONICAL,TARGET)
    assert d["report_rewritten"]==2 and d["report_matched"]==2 and d["requests"]==1
    assert calls[0][1]["params"]["include"]=="15959"
    assert not (s/INDEX_NAME).exists()


def test_alias_persisted_after_feed_moves_on(env):
    s,c=env
    refresh_report_aliases(s,c)
    snapshot=(s/INDEX_NAME).read_bytes()
    assert json.loads(snapshot)["items"][SRC][KEY]["title"]==TITLE
    refresh_report_aliases(s,c)
    assert (s/INDEX_NAME).read_bytes()==snapshot
    write(s/"massy_board_latest.json",{})
    rec=load_report_link_records(s,c)
    assert source_identity(SRC,report=True) in rec
    assert resolve(f'<p><a href="{SRC}">Collision</a></p>',rec)[1]["report_rewritten"]==1


@pytest.mark.parametrize("change",[
    {"title":"AEW Collision Thanksgiving spoilers 11/26/26"},
    {"title":"AEW Collision Thanksgiving Results 11/25/26"},
    {"title":"AEW Collision Thanksgiving Results 11/26/27"},
    {"title":"AEW Collision Results 11/26/26 and 11/27/26"},
    {"title":"AEW Collision Results"},
    {"title":"AEW Collision match results 11/26/26"},
    {"title":"Daniel Garcia on AEW Collision Results 11/26/26"},
    {"title":"Fired TNA referee reportedly generating interest from independent promotions"},
    {"show_hint":"AEW Dynamite"},
    {"published":"2026-11-01T00:00:00+00:00"},
    {"published":""},
    {"url":"https://example.com/report/"},
    {"original_report_reason":"ordinary_news"},
    {"special_event_match":{"report_key":"special_event_conflict_2026_11_26"}},
])
def test_reject_nonreport_or_wrong_identity(env,change):
    s,c=env
    write(s/"massy_board_latest.json",{"hard_skipped":[observation(**change)]})
    rec=load_report_link_records(s,c)
    assert source_identity(SRC,report=True) not in rec


def test_ambiguous_alias_and_conflicting_report_record(env):
    s,c=env
    refresh_report_aliases(s,c)
    old=json.loads((s/INDEX_NAME).read_text())
    old["items"][SRC]["aew_collision_2026_11_27"]={"title":"AEW Collision Results 11/27/26","published":"2026-11-27T23:00:00+00:00"}
    write(s/INDEX_NAME,old)
    assert source_identity(SRC,report=True) not in load_report_link_records(s,c)
    (s/INDEX_NAME).unlink()
    write(s/"report_publication_registry.json",{"items":[published(wp_post_id=999,wp_link=ROOT+"/wrong/")]})
    rec=load_report_link_records(s,c)
    body=f'<p><a href="{SRC}">Collision</a></p>'
    out,d,calls=resolve(body,rec)
    assert out==body and not calls and d["report_rewritten"]==0


def test_wrong_wp_or_no_public_report(env):
    s,c=env
    rec=load_report_link_records(s,c)
    body=f'<p><a href="{SRC}">Collision</a></p>'
    assert resolve(body,rec,rows=[])[0]==body
    assert resolve(body,rec,rows=[wp_row(status="draft")])[0]==body
    assert resolve(body,rec,rows=[wp_row(link=ROOT+"/wrong/")])[0]==body
    write(s/"simone_report_history.json",{KEY:published(status="draft")})
    assert source_identity(SRC,report=True) not in load_report_link_records(s,c)


def test_news_match_precedence_and_single_request(env):
    s,c=env
    rec=load_report_link_records(s,c)
    body=f'<p><a href="{SRC}">Collision</a> <a href="{GARCIA}">Garcia</a></p>'
    garcia=ROOT+"/aew/garcia/"
    news={"g":{"source_url":GARCIA,"wp_post_id":777,"wp_link":garcia,"status":"publish"}}
    out,d,calls=resolve(body,rec,rows=[wp_row(),wp_row(777,garcia)],news=news)
    assert out==body.replace(SRC,TARGET).replace(GARCIA,garcia)
    assert d["rewritten"]==2 and d["report_rewritten"]==1 and len(calls)==1
    news["collision"]={"source_url":SRC,"wp_post_id":888,"wp_link":ROOT+"/news-exact/","status":"publish"}
    out,d,calls=resolve(body,rec,rows=[wp_row(888,ROOT+"/news-exact/"),wp_row(777,garcia)],news=news)
    assert "/news-exact/" in out and d["report_matched"]==0
    news["collision"]["status"]="draft"
    assert SRC in resolve(body,rec,rows=[wp_row(),wp_row(777,garcia)],news=news)[0]


def test_special_structured_night_and_wrong_date(env):
    s,c=env
    c=s.parent/"config"
    write(c/"reports_v92.json",{"reports":[]})
    day="2026-11-26"
    special="special_event_aew_example_night_1_2026_11_26"
    registry={"events":[{"status":"confirmed","event_name":"AEW Example","nights":[{"night_key":"aew_example_night_1","date_local":day}]}]}
    write(c/"special_events.json",registry)
    write(s/"simone_report_history.json",{special:{"report_key":special,"source_url":CANONICAL,"published_at":"2026-11-27T07:40:28+00:00","wp_post_id":15959,"wp_link":TARGET}})
    row=observation(title="AEW Example Results 11/26/26",original_report_reason="special_event_results",special_event_match={"report_key":special,"date_local":day})
    write(s/"massy_board_latest.json",{"hard_skipped":[row]})
    assert source_identity(SRC,report=True) in load_report_link_records(s,c)
    row["title"]="AEW Example Results 11/27/26"
    write(s/"massy_board_latest.json",{"hard_skipped":[row]})
    assert source_identity(SRC,report=True) not in load_report_link_records(s,c)


def test_publisher_real_payload_integration(env, monkeypatch):
    from agents import publisher
    from modules import wordpress_tags
    s,c=env
    monkeypatch.setattr(publisher,"NEWSROOM_STATE_DIR",s)
    monkeypatch.setattr(publisher,"ROOT",c.parent)
    monkeypatch.setattr(publisher,"DRY_RUN",False)
    monkeypatch.setattr(publisher,"POST_STATUS","publish")
    monkeypatch.setattr(publisher,"wp_root",lambda:ROOT)
    monkeypatch.setattr(publisher,"PUBLISHED_DIR",s/"published")
    monkeypatch.setattr(publisher,"REVIEW_DIR",s/"review")
    monkeypatch.setattr(publisher,"PUBLISHED_TRACE_DIR",s/"traces")
    monkeypatch.setattr(publisher,"candidate_featured_image",lambda *_:"")
    monkeypatch.setattr(publisher,"resolve_category_ids",lambda *_:[])
    monkeypatch.setattr(wordpress_tags,"assign_tags",lambda *_a,**_k:None)
    monkeypatch.setattr(publisher.requests,"get",lambda *_a,**_k:SimpleNamespace(status_code=200,json=lambda:[wp_row()]))
    payloads=[]
    def publish(method,url,**kw):
        assert method=="post"
        payloads.append(kw["json"])
        return SimpleNamespace(status_code=201,json=lambda:{"id":15986,"link":ROOT+"/aew/current/"})
    monkeypatch.setattr(publisher,"wp_request",publish)
    article={"source_url":NEWS,"source":"wrestlinginc","title_it":"Continental Classic","body_html":f'<p><a href="{SRC}">Collision</a></p>'}
    result=publisher.publish_article(article,{},True)
    assert result["internal_links"]["report_rewritten"]==1
    assert f'href="{TARGET}">Collision' in payloads[0]["content"]
    assert f'href="{NEWS}" target="_blank"' in payloads[0]["content"]
