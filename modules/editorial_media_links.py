"""Keep editorial media references attached to their translated paragraph."""
from __future__ import annotations

import copy
import html
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import NavigableString

from modules.meta_embeds import canonical_meta_url

def media_url(raw: str, base: str = "") -> str:
    try:
        raw = urljoin(base, html.unescape(str(raw or "").strip()))
        p = urlsplit(raw)
        if p.scheme not in {"http", "https"} or p.username or p.password or p.port:
            return ""
        meta = canonical_meta_url(raw)
        if meta:
            return meta
        host = (p.hostname or "").lower().removeprefix("www.")
        path = p.path.rstrip("/")
        if host in {"x.com", "twitter.com"} and re.fullmatch(r"/[^/]+/status/\d+", path):
            return "https://twitter.com" + path
        if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
            value = path[1:] if host == "youtu.be" else (parse_qs(p.query).get("v") or [""])[0] if path == "/watch" else path.rsplit("/", 1)[-1] if path.startswith(("/embed/", "/shorts/")) else ""
            if re.fullmatch(r"[A-Za-z0-9_-]{5,64}", value):
                return "https://www.youtube.com/watch?v=" + value
        if host == "tiktok.com" and re.fullmatch(r"/@[^/]+/video/\d+", path):
            return "https://www.tiktok.com" + path
        if host in {"threads.net", "threads.com"} and re.fullmatch(r"/(?:@[^/]+/post|t)/[A-Za-z0-9_-]+", path):
            return "https://www.threads.com" + path
        if host == "bsky.app" and re.fullmatch(r"/profile/[^/]+/post/[A-Za-z0-9]+", path):
            return "https://bsky.app" + path
    except (ValueError, TypeError):
        pass
    return ""


def provider_label(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return {"instagram.com": "Instagram", "facebook.com": "Facebook", "twitter.com": "X",
            "youtube.com": "YouTube", "tiktok.com": "TikTok", "threads.com": "Threads",
            "bsky.app": "Bluesky"}.get(host, "sito originale")


def strip_link_markers(text: str) -> str:
    return re.sub(r"\[?/?OWTVLINK\d+\]?", "", text)


def capture_inline_media(item: dict, node, base: str) -> list[str]:
    """URLs stay in metadata; only balanced local markers enter the existing call."""
    text = str(item.get("text") or "")
    clone = copy.deepcopy(node)
    links = []
    for anchor in clone.find_all("a", href=True):
        url = media_url(anchor["href"], base)
        label = anchor.get_text(" ", strip=True)
        if not url or not label or label not in text:
            continue
        index = len(links)
        links.append({"index": index, "url": url})
        anchor.replace_with(NavigableString(f"[OWTVLINK{index}]" + label + f"[/OWTVLINK{index}]"))
    if links:
        item["inline_media_links"] = links
        marked = re.sub(r"\s+", " ", clone.get_text(" ")).strip()
        if strip_link_markers(marked) == text and not re.search(r"OWTVLINK\d+", text):
            item["translation_text"] = marked
    return list(dict.fromkeys(link["url"] for link in links))


def render_linked_text(item: dict, translated: str) -> str:
    links = item.get("inline_media_links") or []
    if not links:
        return html.escape(translated)
    rendered = html.escape(translated)
    missing = []
    for link in links:
        url = media_url(link.get("url", ""))
        if not url:
            continue
        index = link["index"]
        opening, closing = f"[OWTVLINK{index}]", f"[/OWTVLINK{index}]"
        pattern = re.escape(opening) + r"(.*?)" + re.escape(closing)
        matches = list(re.finditer(pattern, rendered, re.S))
        if len(matches) == 1 and matches[0][1].strip() and "OWTVLINK" not in matches[0][1]:
            rendered = re.sub(pattern, lambda m: '<a data-owtv-media-url="' + html.escape(url, quote=True) + '" href="' + html.escape(url, quote=True) + '">' + m[1] + '</a>', rendered, count=1, flags=re.S)
        else:
            missing.append(url)
    rendered = strip_link_markers(rendered)
    for url in dict.fromkeys(missing):
        rendered += ' <span data-owtv-media-url="' + html.escape(url, quote=True) + '" data-owtv-fallback-only="1">(contenuto originale su ' + provider_label(url) + ')</span>'
    return rendered
