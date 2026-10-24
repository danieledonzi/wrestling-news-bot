import pytest

from agents import bob
from agents.publisher_policy_v93_16 import convert_plain_embed_urls_to_blocks, gutenberg_embed_block
from modules.meta_embeds import canonical_meta_url, render_meta_embeds
from modules.report_content import extract_report_blocks, safe_embed_url


IG = 'https://www.instagram.com/p/De4fS_wlNNF/'
FB = 'https://www.facebook.com/WWE/posts/pfbidABC123/'


@pytest.mark.parametrize('raw,expected', [
    (IG + '?utm_source=x&img_index=2', IG),
    ('https://instagram.com/reel/Ab_CD-12/?igsh=abc', 'https://www.instagram.com/reel/Ab_CD-12/'),
    (IG + 'embed/captioned/', IG),
    (FB + '?mibextid=abc', FB),
    ('https://www.facebook.com/WWE/posts/the-announcement/12345/', 'https://www.facebook.com/WWE/posts/12345/'),
    ('https://m.facebook.com/WWE/videos/12345/', 'https://www.facebook.com/WWE/videos/12345/'),
    ('https://facebook.com/reel/12345/?share=abc', 'https://www.facebook.com/reel/12345/'),
    ('https://facebook.com/watch/?v=12345&utm_source=abc', 'https://www.facebook.com/watch/?v=12345'),
    ('https://facebook.com/permalink.php?story_fbid=pfbidABC&id=123', 'https://www.facebook.com/123/posts/pfbidABC/'),
    ('https://www.facebook.com/plugins/post.php?href=https%3A%2F%2Fwww.facebook.com%2FWWE%2Fposts%2FpfbidABC123%2F', FB),
])
def test_meta_permalink_identity_preserves_case_and_required_query(raw, expected):
    assert canonical_meta_url(raw) == expected
    assert safe_embed_url(raw, 'https://source.test/story') == expected


@pytest.mark.parametrize('raw', [
    'https://instagram.com/WWE/', 'https://facebook.com/WWE/',
    'https://instagram.com/stories/WWE/123/', 'https://facebook.com/sharer.php?u=x',
    'https://facebook.com/share/v/abc/', 'https://facebook.com.evil.test/WWE/posts/123/',
    'https://evil.test/?url=' + IG, 'javascript:alert(1)',
    'https://user:pass@instagram.com/p/AbC/', 'https://instagram.com:99999/p/AbC/',
    'https://instagram.com/p/AbC/more/',
])
def test_non_content_and_untrusted_urls_are_not_promoted(raw):
    assert canonical_meta_url(raw) == ''
    assert safe_embed_url(raw, 'https://source.test/story') == ''


@pytest.mark.parametrize('url', [IG, FB, 'https://www.facebook.com/reel/12345/'])
def test_publisher_converts_anchor_paragraph_and_keeps_order(url):
    source = '<p>Prima.</p><p><a href="' + url + '?utm_source=x">' + url + '</a></p><p>Dopo.</p>'
    result = convert_plain_embed_urls_to_blocks(source)
    assert result.count('[embed]' + url + '[/embed]') == 1
    assert result.index('Prima.') < result.index('[embed]') < result.index('Dopo.')
    assert '<iframe' not in result and '<script' not in result
    assert convert_plain_embed_urls_to_blocks(result) == result


def test_inline_link_preserves_prose_and_one_media_at_first_position():
    source = '<p>Joseph ha <a href="' + IG + '?utm_source=x">annunciato lo show</a>.</p><p>Segue.</p>' + gutenberg_embed_block(IG)
    result = render_meta_embeds(source)
    assert '<p>Joseph ha <a href=' in result and 'annunciato lo show</a>.</p>' in result
    assert result.count('[embed]') == 1
    assert result.index('annunciato lo show') < result.index('[embed]') < result.index('Segue.')
    assert render_meta_embeds(result) == result


def test_existing_meta_block_preserves_caption_and_case_sensitive_distinct_posts():
    source = gutenberg_embed_block(IG).replace('</div></figure>', '</div><figcaption>Didascalia.</figcaption></figure>')
    result = render_meta_embeds(source + '\n<p>https://www.instagram.com/p/de4fS_wlNNF/</p>')
    assert result.count('[embed]') == 2
    assert 'Didascalia.' in result


def test_wordpress_paragraph_comments_do_not_contain_nested_shortcode_blocks():
    source = '<!-- wp:paragraph --><p>Annuncio <a href="' + IG + '">su Instagram</a>.</p><!-- /wp:paragraph -->'
    result = render_meta_embeds(source)
    assert result.index('<!-- /wp:paragraph -->') < result.index('<!-- wp:shortcode -->')
    assert render_meta_embeds(result) == result
    bare = '<!-- wp:paragraph --><p><a href="' + IG + '">' + IG + '</a></p><!-- /wp:paragraph -->'
    assert 'wp:paragraph' not in render_meta_embeds(bare)


def test_existing_shortcode_dimensions_are_preserved_without_duplicate_media():
    source = '<!-- wp:shortcode -->[embed width="600" height="420"]' + IG + '?utm_source=x[/embed]<!-- /wp:shortcode --><p>' + IG + '</p>'
    result = render_meta_embeds(source)
    assert result.count(IG) == 1
    assert '[embed width="600" height="420"]' + IG + '[/embed]' in result
    assert render_meta_embeds(result) == result


@pytest.mark.parametrize('extractor', ['news', 'report'])
def test_source_inline_links_keep_full_paragraph_and_media_sequence(extractor):
    source = '<article><div class="entry-content"><p>Prima: notizia e contesto della puntata.</p><p>Joseph <a href="' + IG + '?utm_source=x">announced the new project on Instagram</a>, revealing that Beyond the Bell is coming soon to The CW.</p><p>Dopo, altre informazioni sul progetto.</p><p>Il video <a href="' + FB + '">pubblicato su Facebook</a> contiene altri dettagli.</p><p>Chiusura della notizia.</p></div></article>'
    if extractor == 'news':
        blocks = bob.extract_elements('https://www.ringsidenews.com/test-story/', source)[2]
    else:
        blocks = extract_report_blocks(source, 'https://www.ringsidenews.com/test-story/')
    urls = [b['url'] for b in blocks if b['type'] == 'embed']
    assert urls == [IG, FB]
    ig_pos = next(i for i,b in enumerate(blocks) if b.get('url') == IG)
    assert 'Beyond the Bell' in blocks[ig_pos-1]['text']
    assert 'Dopo' in blocks[ig_pos+1]['text']


def test_other_provider_markup_and_plain_profiles_remain_unchanged():
    source = gutenberg_embed_block('https://x.com/WWE/status/12345') + '\n<p><a href="https://instagram.com/WWE/">Profilo</a></p>\n<p>Testo &amp; citazioni.</p>'
    assert render_meta_embeds(source) == source


def test_news_ignores_source_cta_links():
    source = '<article><div class="entry-content"><p>Questa notizia contiene fatti e dettagli editoriali.</p><p>Follow us on Instagram <a href="' + IG + '">here</a>.</p></div></article>'
    blocks = bob.extract_elements('https://www.ringsidenews.com/test/', source)[2]
    assert not any(b['type'] == 'embed' for b in blocks)


def test_report_source_link_and_later_embedded_same_post_appear_once():
    source = '<article><div class="entry-content"><p>Joseph annuncia <a href="' + IG + '">Beyond the Bell</a>.</p><p>Altri dettagli.</p><blockquote class="instagram-media"><a href="' + IG + '">Instagram</a></blockquote><p>Chiusura.</p></div></article>'
    blocks = extract_report_blocks(source, 'https://www.ringsidenews.com/test/')
    assert [b['url'] for b in blocks if b['type'] == 'embed'] == [IG]
    assert blocks[0]['text'].startswith('Joseph') and blocks[1]['type'] == 'embed'
    assert 'Altri dettagli' in blocks[2]['text']
