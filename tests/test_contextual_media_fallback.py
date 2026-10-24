import html
from types import SimpleNamespace

from bs4 import BeautifulSoup
import pytest

from agents import bob
from agents.publisher_policy_v93_16 import convert_plain_embed_urls_to_blocks, gutenberg_embed_block
from modules.editorial_media_links import capture_inline_media, media_url, render_linked_text
from modules.report_content import extract_report_blocks
from modules.report_workshop_v92 import render_blocks, text_blocks
from modules import wordpress_media_fallback as fallback

IG = 'https://www.instagram.com/p/De4fS_wlNNF/'
PUBLIC = 'https://www.instagram.com/p/CSpMmbTpcC8/'
YT = 'https://www.youtube.com/watch?v=3MfNh-p5zhY'


@pytest.mark.parametrize('url', [IG, 'https://www.facebook.com/WWE/posts/12345/',
    'https://x.com/WWE/status/12345', YT, 'https://www.tiktok.com/@wwe/video/12345',
    'https://www.threads.net/@wwe/post/AbC123', 'https://bsky.app/profile/wwe.com/post/AbC123'])
def test_source_association_survives_translation_and_unavailable_media(url):
    node = BeautifulSoup('<p>Joseph announced the project <a href="' + url + '">on social media</a>, with more details.</p>', 'html.parser').p
    item = {'type':'text','text':node.get_text(' ',strip=True)}
    capture_inline_media(item,node,'https://source.test/story')
    assert item['text'] == node.get_text(' ',strip=True)
    assert '[OWTVLINK0]' in item['translation_text']
    translated = 'Joseph ha annunciato il progetto [OWTVLINK0]sui social[/OWTVLINK0], aggiungendo altri dettagli.'
    rendered = '<p>' + render_linked_text(item,translated) + '</p>\n[embed]' + html.escape(url) + '[/embed]'
    output,diag = fallback.resolve_media_fallbacks(rendered,lambda _: {'state':'unavailable','reason':'private_media'})
    soup = BeautifulSoup(output,'html.parser')
    assert soup.p.get_text() == 'Joseph ha annunciato il progetto sui social, aggiungendo altri dettagli.'
    assert soup.p.a.get_text() == 'sui social'
    assert soup.p.a['href'] == media_url(url)
    assert '[embed' not in output and 'OWTVLINK' not in output and 'data-owtv-' not in output
    assert diag['fallback'] == 1


def test_available_media_retains_original_embed_and_unwraps_inline_reference():
    item={'inline_media_links':[{'index':0,'url':PUBLIC}]}
    block=gutenberg_embed_block(PUBLIC)
    content='<p>'+render_linked_text(item,'Annuncio [OWTVLINK0]su Instagram[/OWTVLINK0].')+'</p>'+block
    output,diag=fallback.resolve_media_fallbacks(content,lambda _: {'state':'available','reason':'oembed_html'})
    assert block in output
    assert '<p>Annuncio su Instagram.</p>' in output
    assert 'data-owtv-' not in output and diag['fallback']==0


@pytest.mark.parametrize('translated', ['Annuncio su Instagram.', 'Annuncio [OWTVLINK0]su Instagram.', 'Annuncio [OWTVLINK0][/OWTVLINK0].'])
def test_lost_or_partial_markers_do_not_block_or_lose_prose(translated):
    item={'inline_media_links':[{'index':0,'url':IG}]}
    content='<p>'+render_linked_text(item,translated)+'</p>\n[embed]'+IG+'[/embed]'
    output,_=fallback.resolve_media_fallbacks(content,lambda _: {'state':'temporary','reason':'provider_temporary'})
    assert 'Annuncio' in output and 'OWTVLINK' not in output
    assert BeautifulSoup(output,'html.parser').p.a['href']==IG


def test_standalone_media_falls_back_inside_nearby_prose_and_preserves_caption():
    content='<p>Prima del video.</p><div class="owtv-report-media">[embed]'+YT+'[/embed]</div><p>Dopo.</p>'
    output,_=fallback.resolve_media_fallbacks(content,lambda _: {'state':'unavailable','reason':'unsupported_or_unavailable'})
    soup=BeautifulSoup(output,'html.parser')
    assert soup.p.a['href']==YT and soup.p.get_text().startswith('Prima del video.')
    assert not soup.select('.owtv-report-media')
    captioned=gutenberg_embed_block(IG).replace('</div></figure>','</div><figcaption>La didascalia.</figcaption></figure>')
    output,_=fallback.resolve_media_fallbacks(captioned,lambda _: {'state':'unavailable','reason':'private_media'})
    assert 'La didascalia.' in output and '<figure' not in output


def test_public_youtube_and_x_markup_is_byte_identical_and_urls_probed_once():
    content=convert_plain_embed_urls_to_blocks('<p>'+YT+'</p>')+gutenberg_embed_block('https://x.com/WWE/status/12345')
    calls=[]
    def probe(url):
        calls.append(url);return {'state':'available','reason':'oembed_html'}
    output,_=fallback.resolve_media_fallbacks(content,probe)
    assert output==content and len(calls)==2


def test_no_probe_in_preview_no_network_and_no_editorial_mutation():
    content='[embed]'+IG+'[/embed]'
    output,diag=fallback.for_wordpress(content,root='https://site.test',auth=('u','p'),session=SimpleNamespace(),enabled=False)
    assert output==content and diag['reasons']=={'probe_disabled':1}


@pytest.mark.parametrize('code,payload,state,reason', [
    (200,{'html':'<blockquote>Post</blockquote>'},'available','oembed_html'),
    (200,{'error':{'code':200,'error_subcode':2207046}},'unavailable','private_media'),
    (200,{'error':{'code':190}},'temporary','provider_configuration'),
    (429,{},'temporary','provider_temporary'),
    (503,{},'temporary','provider_temporary'),
    (404,{},'unavailable','unsupported_or_unavailable'),
])
def test_provider_outcomes_are_not_all_mislabelled_private(monkeypatch,code,payload,state,reason):
    monkeypatch.setattr(fallback,'_CACHE',{})
    calls=[]
    session=SimpleNamespace(get=lambda *a,**k: calls.append(k) or SimpleNamespace(status_code=code,json=lambda:payload))
    first=fallback.probe_wordpress(IG,root='https://site.test',auth=('u','p'),session=session)
    second=fallback.probe_wordpress(IG,root='https://site.test',auth=('u','p'),session=session)
    assert first['state']==state and first['reason']==reason
    assert second['cache_hit'] and len(calls)==1


def test_temporary_outcome_expires_without_terminal_memory(monkeypatch):
    monkeypatch.setattr(fallback,'_CACHE',{});clock=[100.0]
    monkeypatch.setattr(fallback.time,'monotonic',lambda:clock[0])
    count=[]
    def get(*args,**kwargs):
        count.append(1)
        if len(count)==1:raise TimeoutError()
        return SimpleNamespace(status_code=200,json=lambda:{'html':'<iframe></iframe>'})
    args={'root':'https://site.test','auth':('u','p'),'session':SimpleNamespace(get=get)}
    assert fallback.probe_wordpress(IG,**args)['state']=='temporary'
    clock[0]+=61
    assert fallback.probe_wordpress(IG,**args)['state']=='available'


@pytest.mark.parametrize('mode',['news','report'])
def test_complete_source_and_single_existing_translation_call_contract(mode):
    source='<article><div class="entry-content"><p>Joseph <a href="'+IG+'">announced the project on Instagram</a>, revealing that Beyond the Bell is coming to The CW.</p><p>Full additional context follows here.</p></div></article>'
    if mode=='news':
        blocks=bob.extract_elements('https://www.ringsidenews.com/story/',source)[2]
        units=bob.build_translation_units(blocks)
        assert 'inline_media_markers' in units[0]
    else:
        blocks=extract_report_blocks(source,'https://www.ringsidenews.com/story/')
        units=text_blocks(blocks)
    assert '[OWTVLINK0]' in units[0]['text'] and 'Beyond the Bell' in units[0]['text']
    assert IG not in units[0]['text']
    translations={i:'Joseph [OWTVLINK0]ha annunciato il progetto su Instagram[/OWTVLINK0], aggiungendo tutti i dettagli.' for i,b in enumerate(blocks) if b['type'] in {'paragraph','text','quote'}}
    if mode=='news':
        body=bob.render_body(blocks,{b['block_id']:translations[i] for i,b in enumerate(blocks) if i in translations})
        body=convert_plain_embed_urls_to_blocks(body)
    else:
        body=render_blocks(blocks,translations)
    output,_=fallback.resolve_media_fallbacks(body,lambda _: {'state':'unavailable','reason':'private_media'})
    assert BeautifulSoup(output,'html.parser').p.a['href']==IG


def test_untrusted_and_profile_urls_never_reach_probe():
    calls=[]
    for url in ['https://youtube.com.evil.test/watch?v=12345','https://instagram.com/wwe/','javascript:alert(1)']:
        content='[embed]'+url+'[/embed]'
        output,_=fallback.resolve_media_fallbacks(content,lambda u:calls.append(u))
        assert output==content
    assert calls==[]
