from types import SimpleNamespace

import pytest

from modules.editorial_internal_links import MAX_VERIFY_IDS, resolve_internal_links, source_identity

ROOT = "https://news.openwrestlingtv.com"
SRC = "https://www.wrestlinginc.com/2045349/john-cena-spent-8-hours-wwe-star-training-camp-bayley/"
CURRENT = "https://www.wrestlinginc.com/2324464/wwe-bayley-lodestone-helped-reconnect-indie-wrestling-missed/"
TARGET = ROOT + "/wwe/bayley-e-john-cena/"
SOCIAL = "https://www.instagram.com/stories/its.annaray/4038667006218989629/"


def record(source=SRC, id=123, link=TARGET, status="publish"):
    return {"source_url": source, "wp_post_id": id, "wp_link": link, "status": status}


def row(id=123, link=TARGET, status="publish", protected=False, type="post"):
    return {"id": id, "link": link, "status": status, "content": {"protected": protected}, "type": type}


def resolve(content, history, rows=None, *, enabled=True, status=200, source=CURRENT):
    calls = []
    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=status, json=lambda: rows if rows is not None else [row()])
    out, diag = resolve_internal_links(content, history, source_url=source, root=ROOT, enabled=enabled, fetch=fetch)
    return out, diag, calls


def test_byte_preservation_and_batch_deduplication():
    html = f'<!-- wp:paragraph -->\n<p>La <a href="{SRC}">notizia</a>, già <a href="{SRC}">pubblicata</a>. <a href="{SOCIAL}">Storia</a>.</p>\n<!-- /wp:paragraph -->\n<p class="owtv-source-attribution"><em>Fonte: <a href="{SRC}">Wrestling Inc.</a>.</em></p>'
    expected = html.replace(f'<a href="{SRC}">notizia', f'<a href="{TARGET}">notizia').replace(f'<a href="{SRC}">pubblicata', f'<a href="{TARGET}">pubblicata')
    out,d,calls = resolve(html, {"x":record()})
    assert out == expected and d["rewritten"] == 2
    assert d["requests"] == 1 and len(calls) == 1
    url,kw=calls[0]
    assert url==ROOT+"/wp-json/wp/v2/posts"
    assert kw["params"]["include"]=="123"
    assert kw["params"]["status"]=="publish" and kw["timeout"]==(3,5)
    assert kw["allow_redirects"] is False and "auth" not in kw


def test_unpublished_bayley_link_is_unchanged_no_wp_request():
    html=f'<p><a href="{SRC}">La serie di seminari Lodestone</a>.</p>'
    out,d,calls=resolve(html, {"current":record(CURRENT,15962,ROOT+"/wwe/bayley-e-limportanza-dei-seminari-lodestone/")})
    assert out==html and d["matched"]==0 and not calls


@pytest.mark.parametrize("rows", [[], [row(status="draft")], [row(status="private")], [row(protected=True)], [row(type="page")], [row(link="https://evil.test/path/")], [row(link=ROOT+"/wrong/")], [row(id=321)], [row(),row()], [{"id":123,"status":"publish","link":TARGET,"type":"post"}]])
def test_nonpublic_or_mismatched_wp_keeps_source(rows):
    html=f'<p><a href="{SRC}">notizia</a></p>'
    out,d,calls=resolve(html,{"x":record()},rows)
    assert out==html and d["rewritten"]==0 and d["unverified"]==1 and len(calls)==1


@pytest.mark.parametrize("status", [301,403,404,429,500,503])
def test_http_failure_keeps_source(status):
    html=f'<p><a href="{SRC}">notizia</a></p>'
    out,d,calls=resolve(html,{"x":record()},status=status)
    assert out==html and d["rewritten"]==0 and d["requests"]==1


def test_exception_keeps_source():
    html=f'<p><a href="{SRC}">notizia</a></p>'
    def fetch(*a,**kw):
        raise TimeoutError()
    out,d=resolve_internal_links(html,{"x":record()},source_url=CURRENT,root=ROOT,enabled=True,fetch=fetch)
    assert out==html and d["reason"]=="resolution_error" and d["requests"]==1


@pytest.mark.parametrize("history", [{"x":record(status="draft")},{"x":record(link="https://evil.test/x/")},{"x":record(id=True)},{"x":record(),"y":record(id=456)},{"x":record(),"y":record(status="draft")}])
def test_invalid_or_ambiguous_history_no_wp_request(history):
    html=f'<p><a href="{SRC}">notizia</a></p>'
    out,d,calls=resolve(html,history)
    assert out==html and not calls


def test_identity_is_conservative():
    assert source_identity(SRC)==source_identity(SRC.rstrip("/").replace("www.",""))
    for u in [SRC+"?id=2",SRC+"#chapter",SRC.replace("john-cena","John-Cena"),SRC.replace("https:","http:")]:
        assert source_identity(u)!=source_identity(SRC)
    assert source_identity(SOCIAL) is None
    assert source_identity("https://example.org/court/filing.pdf") is None
    assert source_identity("https://www.fightful.com/wrestling/news/") is not None
    assert source_identity("javascript:alert(1)") is None
    assert source_identity(42) is None


def test_skip_protected_markup_self_and_preview():
    html=f'''<!-- <p><a href="{SRC}">comment</a></p> -->
<figure><p><a href="{SRC}">figure</a></p></figure>
<p><a data-owtv-media-url="{SRC}" href="{SRC}">media</a> <a href="{SRC}" target="_blank">legacy media</a> <a href="{CURRENT}">self</a></p>
<p class="owtv-source-attribution"><a href="{SRC}">source</a></p>
<code><p><a href="{SRC}">code</a></p></code>
<p><a href="{SRC}?id=2">other query</a> <a href="{SRC}#chapter">section</a></p>'''
    out,d,calls=resolve(html,{"x":record(),"y":record(CURRENT,456)})
    assert out==html and not calls
    plain=f'<p><a href="{SRC}">plain</a></p>'
    assert resolve(plain,{"x":record()},enabled=False)[0]==plain
    assert not resolve(plain,{"x":record()},enabled=False)[2]


def test_budget_and_partial_success():
    urls=[f"https://www.wrestlinginc.com/{10000+i}/article/" for i in range(MAX_VERIFY_IDS+2)]
    history={u:record(u,i+1,ROOT+f"/wwe/article-{i+1}/") for i,u in enumerate(urls)}
    body="<p>"+" ".join(f'<a href="{u}">link{i}</a>' for i,u in enumerate(urls))+"</p>"
    out,d,calls=resolve(body,history,[row(1,ROOT+"/wwe/article-1/")])
    assert out.count(ROOT)==1 and d["matched"]==MAX_VERIFY_IDS+2
    assert d["budget_skipped"]==2 and d["rewritten"]==1 and d["unverified"]==MAX_VERIFY_IDS-1
    assert len(calls)==1 and calls[0][1]["params"]["per_page"]==MAX_VERIFY_IDS


def test_query_and_html_entity_exact_matching():
    src=SRC+"?id=AbC&v=2"
    html=f'<p>prima\n<a href="{src.replace("&","&amp;")}">testo</a> poi.</p>'
    out,d,calls=resolve(html,{"x":record(src)})
    assert out==f'<p>prima\n<a href="{TARGET}">testo</a> poi.</p>'
    assert d["rewritten"]==1


def test_no_cross_post_id_or_unknown_returned_row():
    a=SRC
    b="https://www.wrestlinginc.com/12345/other/"
    html=f'<p><a href="{a}">a</a> <a href="{b}">b</a></p>'
    out,d,calls=resolve(html,{"a":record(a,123,TARGET),"b":record(b,456,ROOT+"/other/")},[row(123,ROOT+"/other/"),row(456,TARGET),row(999,TARGET)])
    assert out==html and d["rewritten"]==0


def test_publisher_payload_and_trace_end_to_end(monkeypatch, tmp_path):
    import json
    from agents import publisher
    from modules import wordpress_tags

    monkeypatch.setattr(publisher, "DRY_RUN", False)
    monkeypatch.setattr(publisher, "POST_STATUS", "publish")
    monkeypatch.setattr(publisher, "wp_root", lambda: ROOT)
    monkeypatch.setattr(publisher, "PUBLISHED_DIR", tmp_path / "published")
    monkeypatch.setattr(publisher, "REVIEW_DIR", tmp_path / "review")
    monkeypatch.setattr(publisher, "PUBLISHED_TRACE_DIR", tmp_path / "traces")
    monkeypatch.setattr(publisher, "resolve_category_ids", lambda *_: [])
    monkeypatch.setattr(publisher, "candidate_featured_image", lambda *_: "")
    monkeypatch.setattr(wordpress_tags, "assign_tags", lambda *_a, **_k: None)
    public_checks = []
    payloads = []
    def public_get(url, **kw):
        public_checks.append((url, kw))
        return SimpleNamespace(status_code=200, json=lambda: [row()])
    def wp_request(method, url, **kw):
        assert method == "post"
        payloads.append(kw["json"])
        return SimpleNamespace(status_code=201, json=lambda: {"id": 456, "link": ROOT+"/wwe/current/"})
    monkeypatch.setattr(publisher.requests, "get", public_get)
    monkeypatch.setattr(publisher, "wp_request", wp_request)
    article={"source_url":CURRENT, "source":"wrestlinginc", "title_it":"Bayley e Lodestone", "body_html":f'<p>Vedi <a href="{SRC}">la notizia</a>.</p>'}
    history={"old":record()}
    result=publisher.publish_article(article,history,True)
    assert result["status"]=="published" and len(public_checks)==1 and len(payloads)==1
    assert result["internal_links"]["rewritten"]==1
    assert f'<a href="{TARGET}">la notizia</a>' in payloads[0]["content"]
    assert f'href="{CURRENT}" target="_blank" rel="nofollow noopener"' in payloads[0]["content"]
    trace=json.loads(next((tmp_path/"traces").glob("*.json")).read_text())
    assert trace["internal_links"]==result["internal_links"]
    assert result["published_cleaned_full_text"]=="Vedi la notizia ."
