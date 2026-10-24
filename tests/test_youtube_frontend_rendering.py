import sys
from pathlib import Path

from bs4 import BeautifulSoup
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.publisher_policy_v93_16 import convert_plain_embed_urls_to_blocks, gutenberg_embed_block


@pytest.mark.parametrize('url', [
    'https://www.youtube.com/watch?v=3MfNh-p5zhY',
    'https://youtu.be/3MfNh-p5zhY',
    'https://www.youtube.com/embed/3MfNh-p5zhY',
    'https://www.youtube-nocookie.com/embed/3MfNh-p5zhY',
    'https://www.youtube.com/shorts/3MfNh-p5zhY',
])
def test_youtube_uses_native_shortcode_that_survives_rest_sanitization(url):
    result = convert_plain_embed_urls_to_blocks('<p>Prima.</p>\n<p>' + url + '</p>\n<p>Dopo.</p>')
    assert result.count('[embed]https://youtu.be/3MfNh-p5zhY[/embed]') == 1
    assert '<iframe' not in result
    assert 'wp:embed ' not in result
    assert result.index('Prima.') < result.index('[embed]') < result.index('Dopo.')
    assert '<!-- wp:shortcode -->' in result


def test_reprocessing_retains_one_player_and_text():
    first = convert_plain_embed_urls_to_blocks('<p>https://youtu.be/3MfNh-p5zhY</p>')
    assert convert_plain_embed_urls_to_blocks(first) == first
    result = convert_plain_embed_urls_to_blocks(first + '\n<p>https://www.youtube.com/watch?v=3MfNh-p5zhY</p>')
    assert result.count('[embed]') == 1


def test_two_videos_keep_source_order_and_mixed_case_ids():
    result = convert_plain_embed_urls_to_blocks('<p>https://youtu.be/3MfNh-p5zhY</p>\n<p>Tra.</p>\n<p>https://youtu.be/Ao-lugrL_cs</p>')
    assert result.index('[embed]https://youtu.be/3MfNh-p5zhY') < result.index('Tra.')
    assert result.index('Tra.') < result.index('[embed]https://youtu.be/Ao-lugrL_cs')
    assert result.count('[embed]') == 2



@pytest.mark.parametrize('url', ['https://x.com/WWE/status/12345', 'https://www.instagram.com/p/Example/'])
def test_other_providers_still_use_original_gutenberg_markup(url):
    from agents.wordpress_youtube_embed import render_youtube_blocks
    block = gutenberg_embed_block(url)
    assert render_youtube_blocks(block) == block


def test_existing_youtube_block_preserves_caption():
    from agents.wordpress_youtube_embed import render_youtube_blocks
    block = gutenberg_embed_block('https://youtu.be/3MfNh-p5zhY').replace(
        '</div></figure>', '</div><figcaption>Il podcast originale.</figcaption></figure>')
    result = render_youtube_blocks(block)
    soup = BeautifulSoup(result, 'html.parser')
    assert result.count('[embed]') == 1
    assert soup.find('p', class_='wp-element-caption').get_text() == 'Il podcast originale.'


@pytest.mark.parametrize('url', ['https://youtube.com.evil.test/watch?v=3MfNh-p5zhY',
                                 'https://www.youtube.com/watch?v=bad%22id',
                                 'https://www.youtube.com/channel/UCexample'])
def test_unknown_or_invalid_urls_never_create_iframe(url):
    from agents.wordpress_youtube_embed import render_youtube_blocks
    block = gutenberg_embed_block(url)
    assert render_youtube_blocks(block) == block
    assert '<iframe' not in render_youtube_blocks(block)


def test_real_mixed_article_does_not_change_non_youtube_content():
    from agents.wordpress_youtube_embed import render_youtube_blocks
    video = gutenberg_embed_block('https://youtu.be/3MfNh-p5zhY')
    prefix = '<p>Testo e citazione: &quot;non cambiare&quot;.</p>\n'
    suffix = '\n[embed]https://www.instagram.com/p/CSpMmbTpcC8[/embed]\n<img src="photo.jpg"><p>Fine.</p>'
    result = render_youtube_blocks(prefix + video + suffix)
    assert result.startswith(prefix)
    assert result.endswith(suffix)
    assert 'wp-block-embed__wrapper' not in result


def test_existing_gutenberg_youtube_never_nests_or_leaves_orphan_closers():
    block = gutenberg_embed_block('https://youtu.be/3MfNh-p5zhY')
    result = convert_plain_embed_urls_to_blocks(block)
    assert result.count('[embed]') == 1
    assert 'wp:embed' not in result
    assert '</figure>' not in result
    assert '</div>' not in result
    assert convert_plain_embed_urls_to_blocks(result) == result
