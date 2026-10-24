"""WordPress-owned oEmbed eligibility; unavailable media becomes a contextual link."""
from __future__ import annotations

import collections
import json
import re
import time
from typing import Callable

from bs4 import BeautifulSoup

from modules.editorial_media_links import media_url, provider_label

_CACHE = {}


def probe_wordpress(url: str, *, root: str, auth, session) -> dict:
    key = (root, str(auth[0]), url)
    now = time.monotonic()
    if key in _CACHE and _CACHE[key][0] > now:
        return {**_CACHE[key][1], "cache_hit": True}
    try:
        response = session.get(root.rstrip("/") + "/wp-json/oembed/1.0/proxy",
                               params={"url": url, "discover": "false"}, auth=auth, timeout=5)
        data = response.json()
        error = data.get("error") or {}
        markup = data.get("html")
        if response.status_code == 200 and isinstance(markup, str) and re.search(r"<(?:iframe|blockquote|video|audio|div|figure|script)\b", markup, re.I):
            result = {"state": "available", "reason": "oembed_html"}
        elif error.get("error_subcode") == 2207046 or error.get("error_user_title") == "Private Media":
            result = {"state": "unavailable", "reason": "private_media"}
        elif error.get("code") == 190 or response.status_code in {401, 403}:
            result = {"state": "temporary", "reason": "provider_configuration"}
        elif response.status_code == 429 or response.status_code >= 500 or error.get("is_transient"):
            result = {"state": "temporary", "reason": "provider_temporary"}
        else:
            result = {"state": "unavailable", "reason": "unsupported_or_unavailable"}
    except Exception:
        result = {"state": "temporary", "reason": "probe_unavailable"}
    ttl = 3600 if result["state"] == "available" else 60 if result["state"] == "temporary" else 600
    _CACHE[key] = (now + ttl, result)
    return {**result, "cache_hit": False}


def resolve_media_fallbacks(content: str, probe: Callable | None = None) -> tuple[str, dict]:
    blocks = []
    prefix = "OWTVMEDIAPLACEHOLDER"
    while prefix in content:
        prefix += "X"

    def protect(match):
        original = match[0]
        shortcode = re.search(r"\[embed(?:\s+[^\]]*)?\](.*?)\[/embed\]", original, re.S)
        raw = shortcode[1] if shortcode else ""
        if not raw:
            attrs = re.search(r"<!-- wp:embed\s+(\{.*?\})\s*-->", original, re.S)
            if attrs:
                try:
                    raw = json.loads(attrs[1]).get("url", "")
                except (ValueError, AttributeError):
                    pass
        blocks.append((media_url(raw), original))
        return f'<owtv-media data-token="{prefix}" data-index="{len(blocks)-1}"></owtv-media>'

    masked = re.sub(r"<!-- wp:(embed|shortcode)\b.*?<!-- /wp:\1 -->|\[embed(?:\s+[^\]]*)?\].*?\[/embed\]", protect, content, flags=re.S)
    soup = BeautifulSoup(masked, "html.parser")
    references = soup.find_all(attrs={"data-owtv-media-url": True})
    urls = list(dict.fromkeys([u for u,_ in blocks if u] + [media_url(n.get("data-owtv-media-url")) for n in references]))
    urls = [u for u in urls if u]
    outcomes = {}
    for url in urls:
        try:
            outcome = probe(url) if probe else {"state": "unverified", "reason": "probe_disabled"}
            if not isinstance(outcome, dict) or outcome.get("state") not in {"available", "unavailable", "temporary", "unverified"}:
                raise ValueError("invalid probe result")
        except Exception:
            outcome = {"state": "temporary", "reason": "probe_unavailable"}
        outcomes[url] = outcome
    diagnostics = {"media_urls": len(urls), "available": sum(x["state"] == "available" for x in outcomes.values()),
                   "fallback": sum(x["state"] in {"unavailable", "temporary"} for x in outcomes.values()),
                   "cache_hits": sum(bool(x.get("cache_hit")) for x in outcomes.values()),
                   "reasons": dict(collections.Counter(x.get("reason") for x in outcomes.values()))}
    if not references and not diagnostics["fallback"]:
        return content, diagnostics
    linked = set()
    for node in references:
        url = media_url(node.get("data-owtv-media-url"))
        state = outcomes.get(url, {}).get("state", "unverified")
        fallback_only = node.has_attr("data-owtv-fallback-only")
        if state == "available" or fallback_only and state == "unverified":
            node.decompose() if fallback_only else node.unwrap()
        elif url:
            node.name = "a"
            node.attrs = {"href": url, "target": "_blank", "rel": "noopener"}
            linked.add(url)
        else:
            node.unwrap()
    kept = {}
    for node in soup.find_all("owtv-media", attrs={"data-token": prefix}):
        index = int(node["data-index"])
        url, original = blocks[index]
        if outcomes.get(url, {}).get("state") not in {"unavailable", "temporary"}:
            token = prefix + str(index) + "END"
            kept[token] = original
            node.replace_with(token)
            continue
        if url not in linked:
            link = soup.new_tag("a", href=url, target="_blank", rel="noopener")
            link.string = "contenuto originale su " + provider_label(url)
            paragraph = node.find_previous(["p", "li", "blockquote"])
            if paragraph and "owtv-source-attribution" not in (paragraph.get("class") or []):
                paragraph.append(" ("); paragraph.append(link); paragraph.append(")")
            else:
                paragraph = soup.new_tag("p"); paragraph.append(link); node.insert_before(paragraph)
            linked.add(url)
        # Captions are editorial text even when the actual media cannot render.
        caption = BeautifulSoup(original, "html.parser").find("figcaption")
        if caption:
            caption.name = "p"; node.insert_before(caption)
        parent = node.parent
        node.decompose()
        if parent and "owtv-report-media" in (parent.get("class") or []) and not parent.get_text(strip=True) and not parent.find(True):
            parent.decompose()
    rendered = str(soup)
    for token, original in kept.items():
        rendered = rendered.replace(token, original)
    return rendered, diagnostics


def for_wordpress(content: str, *, root: str, auth, session, enabled: bool = True) -> tuple[str, dict]:
    probe = (lambda url: probe_wordpress(url, root=root, auth=auth, session=session)) if enabled and root and all(auth) else None
    rendered, diagnostics = resolve_media_fallbacks(content, probe)
    if diagnostics["media_urls"]:
        print("[MEDIA FALLBACK] " + json.dumps(diagnostics, sort_keys=True), flush=True)
    return rendered, diagnostics
