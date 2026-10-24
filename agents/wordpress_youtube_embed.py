"""Render YouTube with the WordPress native embed shortcode."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


_EMBED_BLOCK = re.compile(r'<!-- wp:embed\s+(\{.*?\})\s*-->(.*?)<!-- /wp:embed -->', re.S)
_OWNED_BLOCK = re.compile(
    r'<!-- wp:shortcode -->\s*\[embed\]https://youtu\.be/([A-Za-z0-9_-]{11})\[/embed\]\s*<!-- /wp:shortcode -->',
    re.S,
)
_VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')


def _video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != 'https':
        return ''
    host = (parsed.hostname or '').lower()
    path = parsed.path.strip('/')
    if host in {'youtu.be', 'www.youtu.be'}:
        value = path.split('/')[0]
    elif host in {'youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'}:
        if path == 'watch':
            value = (parse_qs(parsed.query).get('v') or [''])[0]
        elif path.startswith(('embed/', 'shorts/')):
            value = path.split('/')[1]
        else:
            return ''
    else:
        return ''
    return value if _VIDEO_ID.fullmatch(value) else ''


def render_youtube_blocks(content: str) -> str:
    """Replace only valid YouTube Gutenberg embeds; keep surrounding bytes intact."""
    def replace(match: re.Match[str]) -> str:
        try:
            attrs = json.loads(match.group(1))
            video_id = _video_id(str(attrs.get('url') or ''))
        except (ValueError, AttributeError, TypeError):
            return match.group(0)
        if not video_id:
            return match.group(0)
        caption = BeautifulSoup(match.group(2), 'html.parser').find('figcaption')
        # Let WordPress generate the iframe after saving: REST sanitization strips
        # raw iframes, and editor previews can hide failed Gutenberg oEmbeds.
        caption_html = ''
        if caption:
            caption.name = 'p'
            caption['class'] = 'wp-element-caption'
            caption_html = '\n' + str(caption)
        return (
            '<!-- wp:shortcode -->\n'
            f'[embed]https://youtu.be/{video_id}[/embed]\n'
            '<!-- /wp:shortcode -->' + caption_html
        )

    rendered = _EMBED_BLOCK.sub(replace, content)
    seen: set[str] = set()

    def dedupe(match: re.Match[str]) -> str:
        video_id = match.group(1)
        if video_id in seen:
            return ''
        seen.add(video_id)
        return match.group(0)

    return _OWNED_BLOCK.sub(dedupe, rendered)
