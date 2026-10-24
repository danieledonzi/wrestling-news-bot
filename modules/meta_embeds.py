"""Public Meta post permalinks and WordPress native oEmbed presentation.

No fetches, source scripts or model calls. Meta Embeds supplies the WP provider.
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup


def canonical_meta_url(raw: str, base_url: str = "") -> str:
    try:
        p = urlsplit(urljoin(base_url, html.unescape(str(raw or "").strip())))
        if p.scheme not in {"http", "https"} or p.username or p.password or p.port:
            return ""
        host = (p.hostname or "").lower().removeprefix("www.")
        path = p.path.rstrip("/")
        if host == "instagram.com":
            match = re.fullmatch(r"/((?:p|reel|tv)/[A-Za-z0-9_-]+)(?:/embed(?:/captioned)?)?", path)
            return "https://www.instagram.com/" + match[1] + "/" if match else ""
        if host in {"facebook.com", "m.facebook.com", "web.facebook.com"}:
            slug_post = re.fullmatch(r"/([A-Za-z0-9_.-]+)/posts/[^/]+/([A-Za-z0-9]+)", path)
            if slug_post:
                return "https://www.facebook.com/" + slug_post[1] + "/posts/" + slug_post[2] + "/"
            if re.fullmatch(r"/plugins/(?:post|video)\.php", path):
                nested = (parse_qs(p.query).get("href") or [""])[0]
                # Only a permalink, never recursive plugin wrappers or redirects.
                if "/plugins/" not in nested:
                    return canonical_meta_url(nested)
                return ""
            if re.fullmatch(r"/(?:[A-Za-z0-9_.-]+/(?:posts|videos)/[A-Za-z0-9]+|reel/\d+)", path):
                return "https://www.facebook.com" + path + "/"
            q = parse_qs(p.query)
            field = "v" if path == "/watch" else "story_fbid" if path in {"/permalink.php", "/story.php"} else ""
            value = (q.get(field) or [""])[0]
            owner = (q.get("id") or [""])[0]
            if field and re.fullmatch(r"[A-Za-z0-9]+", value):
                if field == "v":
                    return "https://www.facebook.com/watch/?v=" + value
                if re.fullmatch(r"\d+", owner):
                    return "https://www.facebook.com/" + owner + "/posts/" + value + "/"
        return ""
    except (ValueError, TypeError):
        return ""


def linked_meta_urls(node, base_url: str = "") -> list[str]:
    return list(dict.fromkeys(url for a in node.find_all("a", href=True)
                              if (url := canonical_meta_url(a["href"], base_url))))


def render_meta_embeds(content: str) -> str:
    """Convert only Meta media fragments; preserve all other surrounding bytes.

    Protect existing blocks first, then deduplicate in document order. A source
    link inside prose keeps its text and gets its media after that paragraph.
    """
    fragments = []
    # The token contains no URL and cannot be consumed by other embed scanners.
    prefix = "OWTVMETA" + str(len(content)) + "TOKEN"
    while prefix in content:
        prefix += "X"

    def protect(url: str, original: str, caption: str = "") -> str:
        token = prefix + str(len(fragments)) + "END"
        fragments.append((url, original, caption))
        return token

    def block(match):
        original = match[0]
        soup = BeautifulSoup(original, "html.parser")
        shortcode = re.search(r"\[embed\](.*?)\[/embed\]", original, re.S)
        url = canonical_meta_url(shortcode[1]) if shortcode else ""
        if not url:
            attrs = re.search(r"<!-- wp:embed\s+(\{.*?\})\s*-->", original, re.S)
            if attrs:
                try:
                    url = canonical_meta_url(json.loads(attrs[1]).get("url", ""))
                except (ValueError, AttributeError):
                    pass
        caption = soup.find("figcaption")
        caption_html = ""
        if caption and url:
            caption.name = "p"
            caption_html = "\n" + str(caption)
        return protect(url, original, caption_html)

    text = re.sub(r"<!-- wp:(embed|shortcode)\b.*?<!-- /wp:\1 -->|\[embed\].*?\[/embed\]", block, content, flags=re.S)

    def paragraph(match):
        original = match[0]
        soup = BeautifulSoup(original, "html.parser")
        node = soup.find("p")
        urls = linked_meta_urls(node)
        plain = node.get_text(" ", strip=True)
        bare = canonical_meta_url(plain)
        if bare and bare not in urls:
            urls.append(bare)
        if not urls:
            return original
        following = text[match.end():]
        immediate_urls = set()
        while True:
            adjacent = re.match(r"\s*" + re.escape(prefix) + r"(\d+)END", following)
            if not adjacent:
                break
            immediate_urls.add(fragments[int(adjacent[1])][0])
            following = following[adjacent.end():]
        if set(urls).issubset(immediate_urls):
            return "" if bare else original
        # A bare permalink paragraph becomes just the media; prose stays intact.
        kept = "" if bare else original
        return kept + "\n" + "\n".join(protect(u, "") for u in urls)

    text = re.sub(r"<p\b[^>]*>.*?</p>", paragraph, text, flags=re.S | re.I)

    def line(match):
        url = canonical_meta_url(match[1])
        return protect(url, "") if url else match[0]

    text = re.sub(r"(?m)^\s*(https?://[^\s<>]+)\s*$", line, text)
    seen = set()

    def restore(match):
        url, original, caption = fragments[int(match[1])]
        if not url:
            return original
        if url in seen:
            return caption
        seen.add(url)
        return '<!-- wp:shortcode -->\n[embed]' + html.escape(url) + '[/embed]\n<!-- /wp:shortcode -->' + caption

    return re.sub(re.escape(prefix) + r"(\d+)END", restore, text)
