import html
import pytest
from bs4 import BeautifulSoup
from agents import bob, alfred, publisher
from agents.publisher_policy_v93_16 import convert_plain_embed_urls_to_blocks
from modules.editorial_media_links import capture_news_links, editorial_href, render_news_linked_text, media_url
from modules.wordpress_media_fallback import resolve_media_fallbacks
from modules.report_content import extract_report_blocks

STORY = "https://www.instagram.com/stories/its.annaray/4038667006218989629/"
BASE = "https://www.ringsidenews.com/identity-woman-andrade-kissed-november-25-aew-dynamite/"
IG = "https://www.instagram.com/p/De4fS_wlNNF/"
OTHER = "https://www.ringsidenews.com/previous-article/"
PAR = 'After Dynamite, the identity of Andrade’s latest selfie partner was revealed. Independent wrestler Anna Ray confirmed on <a href="' + STORY + '">her Instagram Story</a> that she was the woman involved in the ringside interaction. Ray isn’t simply a fan who happened to get some camera time either. She’s an independent wrestler who has competed for promotions including the NWA, PWS, PXW and DREAMWAVE, among others.'
IT = 'Dopo Dynamite è stata rivelata l’identità della compagna di selfie di Andrade. La wrestler indipendente Anna Ray ha confermato tramite [OWTVLINK0]una storia su Instagram[/OWTVLINK0] di essere la donna coinvolta nell’interazione. Ray non è semplicemente una fan che si è trovata davanti alle telecamere: è una wrestler indipendente che ha lottato in diverse federazioni, tra cui NWA, PWS, PXW e DREAMWAVE.'


def item_for(markup):
    node=BeautifulSoup(markup,"html.parser").p
    item={"type":"text","text":bob.clean_text(node.get_text(" "))}
    urls=capture_news_links(item,node,BASE)
    return item,urls


def test_andrade_end_to_end():
    source='<article><div class="entry-content"><p>'+PAR+'</p><p>Earlier reports mentioned <a href="'+OTHER+'">Leah Night</a> and <a href="/previous-kelly/">Kelly Madan</a>.</p><p>Follow us on Instagram <a href="https://example.org/subscribe/">here</a>.</p></div></article>'
    _,_,elements,_,_=bob.extract_elements(BASE,source)
    units=bob.build_translation_units(elements)
    assert len(units)==2
    assert "[OWTVLINK0]her Instagram Story[/OWTVLINK0]" in units[0]["text"]
    assert STORY not in units[0]["text"]
    assert not [e for e in elements if e["type"]=="embed"]
    translated={units[0]["id"]:IT,units[1]["id"]:"Le notizie precedenti citavano [OWTVLINK0]Leah Night[/OWTVLINK0] e [OWTVLINK1]Kelly Madan[/OWTVLINK1]."}
    body=bob.render_body(elements,translated)
    review=alfred.review_article({"status":"ready_for_alfred","title_it":"Svelata l’identità della donna baciata da Andrade","body_html":body,"elements":elements,"element_counts":{"text":2}})
    assert review["decision"]=="approved", review["issues"]
    final=publisher.clean_body_for_wordpress(review["approved_article"]["body_html"],wp_ok=False)
    final=convert_plain_embed_urls_to_blocks(final)
    final,diag=resolve_media_fallbacks(final,lambda _:pytest.fail("Unexpected media probe"))
    soup=BeautifulSoup(final,"html.parser")
    assert soup.find("a",href=STORY).get_text()=="una storia su Instagram"
    assert [a["href"] for a in soup.find_all("a")]==[STORY,OTHER,"https://www.ringsidenews.com/previous-kelly/"]
    assert "OWTVLINK" not in final and "data-owtv-media" not in final and "[embed" not in final
    assert diag["media_urls"]==0
    assert elements[0]["ordinary_link_render"]=={"captured":1,"inline":1,"fallback":0,"lost":0}


@pytest.mark.parametrize("translated",["Conferma su Instagram.","Conferma [OWTVLINK0]su Instagram.","Conferma [OWTVLINK0][/OWTVLINK0].","Conferma [OWTVLINK0]A[/OWTVLINK0] e [OWTVLINK0]B[/OWTVLINK0].","Conferma [OWTVLINK0]A[OWTVLINK9]B[/OWTVLINK9][/OWTVLINK0].","Conferma [owtvlink0]A[/owtvlink0]."])
def test_marker_failures(translated):
    item,_=item_for("<p>"+PAR+"</p>")
    out=render_news_linked_text(item,translated)
    soup=BeautifulSoup(out,"html.parser")
    assert soup.a["href"]==STORY and soup.a.get_text()=="riferimento originale"
    assert "owtvlink" not in out.lower()
    assert item["ordinary_link_render"]["fallback"]==1


def test_mixed_media_and_reordered_ordinary():
    item,urls=item_for('<p>News <a href="'+STORY+'">story</a> and <a href="'+IG+'">video</a> and <a href="'+OTHER+'">report</a>.</p>')
    assert urls==[IG]
    out=render_news_linked_text(item,"[OWTVLINK2]articolo[/OWTVLINK2], [OWTVLINK1]video[/OWTVLINK1] e [OWTVLINK0]storia[/OWTVLINK0].")
    soup=BeautifulSoup(out,"html.parser")
    assert [a["href"] for a in soup.find_all("a")]==[OTHER,IG,STORY]
    assert soup.find("a",href=IG).has_attr("data-owtv-media-url")
    assert not soup.find("a",href=STORY).has_attr("data-owtv-media-url")


def test_partial_word_and_repeated_labels():
    item,_=item_for('<p>T<a href="'+OTHER+'">hat woman</a> and <a href="'+STORY+'">her</a> and <a href="/another/">her</a>.</p>')
    assert len(item["inline_editorial_links"])==3
    out=render_news_linked_text(item,"[OWTVLINK2]lei[/OWTVLINK2] e [OWTVLINK1]lei[/OWTVLINK1], [OWTVLINK0]quella donna[/OWTVLINK0].")
    assert [a["href"] for a in BeautifulSoup(out,"html.parser").find_all("a")]==["https://www.ringsidenews.com/another/",STORY,OTHER]


@pytest.mark.parametrize("raw",["javascript:alert(1)","data:text/html,x","file:///etc/passwd","https://user@evil.com/a","https://example.com/a b","https://example.com/a?affiliate=1","/author/john/","#comments","https://instagram.com/wwe/","https://example.com/[embed]"])
def test_ineligible(raw):
    assert not editorial_href(raw,BASE)


def test_exact_url_and_noise():
    url="https://example.org/Case/File?doc=AbC&version=2#Section"
    assert editorial_href(url,BASE)==url
    item,_=item_for('<p>News <a href="'+html.escape(url)+'">court filing</a> and <a class="sponsored-link" href="https://example.org/ad">sponsor</a>.</p>')
    assert len(item["inline_editorial_links"])==1
    out=render_news_linked_text(item,"Notizia [OWTVLINK0]&lt;test&gt;[/OWTVLINK0] e sponsor.")
    assert BeautifulSoup(out,"html.parser").a["href"]==url
    assert not BeautifulSoup(out,"html.parser").find("test")


def test_report_does_not_capture_ordinary():
    blocks=extract_report_blocks('<article><div class="entry-content"><p>'+PAR+'</p></div></article>',BASE)
    assert not any(b.get("inline_editorial_links") or "OWTVLINK" in str(b.get("translation_text","")) for b in blocks)


# Exact editorial paragraphs from the browser-saved Ringside News article.
# The surrounding advertising, scripts and page chrome are intentionally omitted.
ANDRADE_BODY = """<article><div class="entry-content rsn-single-content">
<p>Andrade El Idolo is still doing his ringside selfie routine, but he took things a little further this time. During the <a href="https://www.ringsidenews.com/aew-dynamite-thanksgiving-eve-results-highlights-key-moments-november-25-2026/">November 25 episode of AEW Dynamite</a>, Andrade stopped in the middle of his match with Kyle Fletcher to pose with another woman at ringside — and even gave her a kiss on the cheek.</p>
<p>The moment happened when Andrade made his way toward the crowd during the match. A woman sitting at ringside pulled out her phone for a selfie, and Andrade happily posed before leaning over and kissing her on the cheek while she took the photo. Right after that, Andrade returned his attention to Fletcher and nailed him with a flying rana.</p>
<p>After Dynamite, the identity of Andrade’s latest selfie partner was revealed. Independent wrestler Anna Ray confirmed on <a href="https://www.instagram.com/stories/its.annaray/4038667006218989629/">her Instagram Story</a> that she was the woman involved in the ringside interaction. Ray isn’t simply a fan who happened to get some camera time either. She’s an independent wrestler who has competed for promotions including the NWA, PWS, PXW and DREAMWAVE, among others.</p>
<p>This is already a pretty recognizable part of Andrade’s AEW act. During the October 24 episode of <em>Collision</em>, he stopped for a selfie with another woman at ringside before Tommaso Ciampa interrupted the moment by attacking him. T<a href="https://www.ringsidenews.com/identity-woman-who-took-selfie-andrade-1024-aew-collision/">hat woman was later revealed to be indie wrestler Leah Night</a>.</p>
<p>Andrade has done the same thing with several other women during his AEW appearances, including <a href="https://www.ringsidenews.com/identity-woman-who-took-selfie-andrade-aew-wrestledream/">Madisyn Maxxwell</a> and <a href="https://www.ringsidenews.com/identity-woman-who-took-selfie-andrade-october-14-aew-dynamite/">Kelly Madan</a>. At WrestleDream, he even kissed Maxxwell on the cheek during their ringside selfie.</p>
<p>So the selfie itself wasn’t exactly new on Dynamite. The fun part was Andrade casually kissing Ray on the cheek and then immediately turning around to hit Fletcher with a flying rana like he hadn’t just stopped his match for a photo opportunity. At this point, spotting who Andrade picks for his next ringside selfie is becoming its own little side story whenever he wrestles.</p>
<p>Who do you think Andrade will find at ringside next? Let us know in the comments.</p>
</div></article>"""


def test_original_editorial_paragraphs_and_canonical_contract(monkeypatch):
    from agents import source_body
    from modules import editorial_media_links
    _,_,new_elements,_,new_diag=bob.extract_elements(BASE,ANDRADE_BODY)
    with monkeypatch.context() as m:
        m.setattr(editorial_media_links,"capture_news_links",editorial_media_links.capture_inline_media)
        _,_,old_elements,_,old_diag=bob.extract_elements(BASE,ANDRADE_BODY)
    assert [e["text"] for e in new_elements]==[e["text"] for e in old_elements]
    assert len(new_elements)==6
    new_contract=source_body.contract_from_elements(BASE,new_elements,new_diag)
    old_contract=source_body.contract_from_elements(BASE,old_elements,old_diag)
    assert new_contract is not None and new_contract==old_contract
    units=bob.build_translation_units(new_elements)
    assert len(units)==6
    # Identity translation isolates deterministic transport and rendering.
    body=bob.render_body(new_elements,{u["id"]:u["text"] for u in units})
    expected=[a["href"] for a in BeautifulSoup(ANDRADE_BODY,"html.parser").find_all("a")]
    assert len(expected)==5
    assert [a["href"] for a in BeautifulSoup(body,"html.parser").find_all("a")]==expected
    assert "OWTVLINK" not in body and "[embed" not in body and "data-owtv-media" not in body


def test_mixed_malformed_ordinary_keeps_independent_media_pair():
    item,_=item_for('<p>News <a href="'+STORY+'">story</a> and <a href="'+IG+'">video</a>.</p>')
    out=render_news_linked_text(item,"[OWTVLINK0]storia e [OWTVLINK1]video[/OWTVLINK1].")
    soup=BeautifulSoup(out,"html.parser")
    assert soup.find("a",href=IG).get_text()=="video"
    assert soup.find("a",href=STORY).get_text()=="riferimento originale"
    assert "OWTVLINK" not in out
