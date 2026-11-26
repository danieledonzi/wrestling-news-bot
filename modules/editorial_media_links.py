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


# Ordinary news hyperlinks are not media. Keep the shared report helpers above
# unchanged; Bob opts into these additional helpers explicitly.
_LINK_NOISE = re.compile(r"(?:^|[\s_-])(?:advert(?:isement|ising)?|ads?|affiliate|sponsored|share|newsletter|subscribe|related|recommended|navigation|author|footer|promo|social-share|cta)(?:$|[\s_-])", re.I)
_LINK_LABEL_NOISE = re.compile(r"^(?:go to page|read more|click here|subscribe|follow us|share(?: this)?|add as a preferred source(?: on google)?|sign up|buy now|shop now)$", re.I)
_LINK_PATH_NOISE = re.compile(r"(?:^|/)(?:author|authors|category|tag|tags|search|subscribe|newsletter|login|register|privacy-policy|terms-of-service|advertise|affiliate|affiliates|share|sharer|redirect|out|go)(?:/|$)", re.I)
_LINK_QUERY_NOISE = {"affiliate", "aff", "affid", "aff_id", "affiliate_id", "referral", "referrer", "tag", "utm_medium"}
_NEWS_MARKER = re.compile(r"\[(/?)OWTVLINK(\d+)\]")
_LOOSE_NEWS_MARKER = re.compile(r"(?:\[\s*)?/?OWTVLINK\s*\d+(?:\s*\])?", re.I)


def editorial_href(raw: str, base: str = "") -> str:
    """Validate, but do not canonicalize, the DOM href (no network access)."""
    try:
        raw = str(raw or "").strip()
        if not raw or raw.startswith("#") or re.search(r"""[\s\\<>"'\[\]\x00-\x1f\x7f]""", raw):
            return ""
        resolved = urljoin(base, raw)
        p = urlsplit(resolved)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username is not None or p.password is not None:
            return ""
        if p.port not in {None, 80, 443}:
            return ""
        host = p.hostname.lower().removeprefix("www.")
        if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", host):
            return ""
        if not p.path.strip("/") or _LINK_PATH_NOISE.search(p.path):
            return ""
        if host in {"doubleclick.net", "googlesyndication.com", "amzn.to", "bit.ly", "t.co"} or host.endswith((".doubleclick.net", ".googlesyndication.com")):
            return ""
        query = {k.lower(): v for k,v in parse_qs(p.query, keep_blank_values=True).items()}
        if any(k in query for k in _LINK_QUERY_NOISE - {"utm_medium"}) or any(v.lower() in {"affiliate", "cpc", "paid", "sponsored"} for v in query.get("utm_medium", [])):
            return ""
        if base:
            b = urlsplit(base)
            if (p.hostname.lower().removeprefix("www."), p.path.rstrip("/"), p.query) == ((b.hostname or "").lower().removeprefix("www."), b.path.rstrip("/"), b.query):
                return ""
        # Generic social profiles and share endpoints are not documentary links.
        if host == "instagram.com" and not re.fullmatch(r"/stories/[^/]+/\d+/?", p.path):
            return ""
        if host in {"facebook.com", "m.facebook.com", "web.facebook.com", "x.com", "twitter.com", "tiktok.com", "threads.com", "threads.net", "bsky.app", "youtube.com", "youtu.be", "youtube-nocookie.com"}:
            return ""
        return resolved
    except (ValueError, TypeError):
        return ""


def _ordinary_anchor(anchor, base: str) -> str:
    label = anchor.get_text(" ", strip=True)
    if not label or _LINK_LABEL_NOISE.fullmatch(label) or not re.search(r"\w", label):
        return ""
    for node in [anchor, *anchor.parents]:
        if getattr(node, "name", None) in {"nav", "aside", "footer", "header", "button"}:
            return ""
        attrs = getattr(node, "attrs", {}) or {}
        hints = " ".join([str(attrs.get("id", "")), *map(str, attrs.get("class", [])), *map(str, attrs.get("rel", []))])
        if _LINK_NOISE.search(hints) or "sponsored" in attrs.get("rel", []):
            return ""
    return editorial_href(anchor["href"], base)


def capture_news_links(item: dict, node, base: str) -> list[str]:
    """Extend only news blocks, retaining the old media return contract."""
    media = capture_inline_media(item, node, base)
    if not node.find("a", href=True):
        return media
    text = str(item.get("text") or "")
    clone = copy.deepcopy(node)
    plain = re.sub(r"\s+", " ", html.unescape(clone.get_text(" "))).strip()
    # A changed block may have had promotional sentences removed. Do not
    # resurrect their links by matching repeated labels elsewhere in the text.
    if plain != text:
        return media
    links = []
    ordinary = []
    excluded = 0
    for anchor, original in zip(clone.find_all("a", href=True), node.find_all("a", href=True)):
        label = anchor.get_text(" ", strip=True)
        murl = media_url(anchor["href"], base)
        url = murl if murl and label and label in text else _ordinary_anchor(original, base)
        if not url or not label or label not in text:
            if not murl:
                excluded += 1
            continue
        index = len(links)
        link = {"index": index, "url": url}
        if not murl:
            link["kind"] = "ordinary"
            ordinary.append(link)
        links.append(link)
        # The source extractor already inserts spaces at tag boundaries.
        # Never try to repair its plain text here; use fallback if markers
        # cannot reproduce the exact original cleaned text.
        anchor.replace_with(NavigableString(f"[OWTVLINK{index}]" + label + f"[/OWTVLINK{index}]"))
    if excluded:
        item["ordinary_links_excluded"] = excluded
    if not ordinary:
        return media
    marked = re.sub(r"\s+", " ", html.unescape(clone.get_text(" "))).strip()
    if strip_link_markers(marked) == text and not re.search(r"OWTVLINK\s*\d+", text, re.I):
        item["inline_media_links"] = [link for link in links if link.get("kind") != "ordinary"]
        item["inline_editorial_links"] = ordinary
        item["translation_text"] = marked
    else:
        # Keep the legacy media indexes and input unchanged in this case.
        start = len(item.get("inline_media_links") or [])
        item["inline_editorial_links"] = [{**link, "index": start+i, "fallback_only": True} for i,link in enumerate(ordinary)]
    return media


def render_news_linked_text(item: dict, translated: str) -> str:
    ordinary = item.get("inline_editorial_links") or []
    if not ordinary:
        return render_linked_text(item, translated)
    # Parse marker topology before replacing anything. Nested, crossed,
    # duplicated or unknown markers cannot authorize an inline association.
    media = item.get("inline_media_links") or []
    known = {str(link["index"]) for link in media + ordinary}
    tokens = list(_NEWS_MARKER.finditer(translated))
    counts = {}
    for token in tokens:
        key = (token[1], token[2])
        counts[key] = counts.get(key, 0) + 1
    pairs = {}
    for left, right in zip(tokens, tokens[1:]):
        idx = left[2]
        inner = translated[left.end():right.start()]
        if not left[1] and right[1] and right[2] == idx and idx in known and counts.get(("", idx)) == counts.get(("/", idx)) == 1 and inner.strip() and not _LOOSE_NEWS_MARKER.search(inner):
            pairs[idx] = (left.start(), right.end(), inner)
    # Any malformed nesting/overlap or unknown token invalidates ordinary
    # inline associations for this block, rather than guessing intent.
    stack = []
    invalid_topology = False
    for token in tokens:
        if token[2] not in known:
            invalid_topology = True
        if not token[1]:
            if stack:
                invalid_topology = True
            stack.append(token[2])
        elif not stack or stack.pop() != token[2]:
            invalid_topology = True
    if stack:
        invalid_topology = True
    if _LOOSE_NEWS_MARKER.search(_NEWS_MARKER.sub("", translated)):
        invalid_topology = True
    prefix = "OWTVORDINARYANCHOR"
    while prefix in translated or any(prefix in str(link.get("url", "")) for link in media + ordinary):
        prefix += "X"
    replacements = []
    fallback = []
    edits = []
    inline = 0
    for link in ordinary:
        url = editorial_href(link.get("url", ""))
        if not url:
            continue
        idx = str(link["index"])
        pair = None if invalid_topology or link.get("fallback_only") else pairs.get(idx)
        href = html.escape(url, quote=True)
        if pair:
            start, end, label = pair
            placeholder = prefix + str(len(replacements)) + "END"
            replacements.append((placeholder, f'<a href="{href}">{html.escape(label)}</a>'))
            edits.append((start, end, placeholder))
            inline += 1
        else:
            fallback.append(url)
    for start,end,placeholder in sorted(edits, reverse=True):
        translated = translated[:start] + placeholder + translated[end:]
    media_ids = {str(link["index"]) for link in media if str(link["index"]) in pairs}
    translated = _NEWS_MARKER.sub(lambda m: m[0] if m[2] in media_ids else "", translated)
    # Keep valid legacy media markers for the existing renderer; remove
    # malformed/unknown ordinary tokens without touching prose.
    translated = _LOOSE_NEWS_MARKER.sub(lambda m: m[0] if (exact := _NEWS_MARKER.fullmatch(m[0])) and exact[2] in media_ids else "", translated)
    rendered = render_linked_text(item, translated)
    for placeholder, anchor in replacements:
        rendered = rendered.replace(placeholder, anchor, 1)
    fallback_count = len(fallback)
    for url in dict.fromkeys(fallback):
        rendered += ' (<a href="' + html.escape(url, quote=True) + '">riferimento originale</a>)'
    item["ordinary_link_render"] = {"captured": len(ordinary), "inline": inline, "fallback": fallback_count, "lost": sum(not editorial_href(link.get("url", "")) for link in ordinary)}
    return rendered
