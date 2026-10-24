"""Render owned YouTube blocks without depending on WordPress's oEmbed cache."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


_EMBED_BLOCK = re.compile(r'<!-- wp:embed\s+(\{.*?\})\s*-->(.*?)<!-- /wp:embed -->', re.S)
_OWNED_BLOCK = re.compile(
    r'<!-- wp:html -->\s*<figure class="owtv-youtube-embed" data-video-id="([A-Za-z0-9_-]{11})"[^>]*>.*?</figure>\s*<!-- /wp:html -->',
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
        source = html.escape('https://www.youtube.com/watch?v=' + video_id, quote=True)
        return (
            '<!-- wp:html -->\n'
            f'<figure class="owtv-youtube-embed" data-video-id="{video_id}" data-source-url="{source}">'
            '<div style="position:relative;width:100%;height:0;padding-bottom:56.25%;overflow:hidden;">'
            f'<iframe src="https://www.youtube.com/embed/{video_id}" title="Video YouTube" '
            'width="560" height="315" loading="lazy" '
            'style="position:absolute;top:0;left:0;width:100%;height:100%;border:0;" '
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" '
            'referrerpolicy="strict-origin-when-cross-origin" allowfullscreen></iframe>'
            '</div>' + (str(caption) if caption else '') + '</figure>\n<!-- /wp:html -->'
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
