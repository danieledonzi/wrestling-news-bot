from __future__ import annotations

import html as html_lib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.gemini_ledger import record_gemini_event
from urllib.parse import urljoin, urlparse
import time
import base64

import requests
from bs4 import BeautifulSoup
from google import genai

V92_REPORT_QUALITY_PATCH = True
V92_REPORT_PROMPT_STRATEGY_PATCH = True
V92_REPORT_RUNTIME_TWEAKS = True
V92_REPORT_LEGACY_TRANSLATION_PROMPT = True
V92_REPORT_SOURCE_INTRO_FILTER = True
V92_REPORT_CHUNKED_TRANSLATION = True
V92_RINGSIDE_EMBED_RECOVERY = True
V92_RINGSIDE_BASE64_EMBED_PATCH = True
V92_RINGSIDE_BROAD_FINAL_CLEANUP = True
V92_WP_RESILIENCE_PATCH = True
SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]
REQUEST_TIMEOUT = int(os.getenv("V92_REQUEST_TIMEOUT", "12"))
REQUEST_TIMEOUT_WP = int(os.getenv("V92_REQUEST_TIMEOUT_WP", "12"))
REPORT_TRANSLATION_BATCH_SIZE = int(os.getenv("V92_REPORT_TRANSLATION_BATCH_SIZE", "24"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_MODEL_CHAIN_V95_2 = "gemini-3.1-flash-lite,gemini-3.5-flash,gemini-2.5-flash-lite,gemini-2.5-flash"
DEFAULT_REPORT_MODEL_CHAIN_V95_2 = "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash,gemini-2.5-flash-lite"
MODEL_CHAIN = [m.strip() for m in os.getenv(
    "GEMINI_MODEL_CHAIN",
    DEFAULT_MODEL_CHAIN_V95_2,
).split(",") if m.strip()]
REPORT_MODEL_CHAIN = [m.strip() for m in os.getenv(
    "REPORT_GEMINI_MODEL_CHAIN",
    os.getenv("GEMINI_REPORT_MODEL_CHAIN", DEFAULT_REPORT_MODEL_CHAIN_V95_2),
).split(",") if m.strip()]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)
category_cache: Dict[str, Optional[int]] = {}
media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}
V92_BLOCK_NOISE_EMBED_PATCH = True
V92_MEDIA_DEGRADED_PATCH = True
MEDIA_UPLOAD_FAILURES = 0
MEDIA_UPLOAD_DISABLED = False
MEDIA_UPLOAD_FAILURE_LIMIT = int(os.getenv("V92_MEDIA_UPLOAD_FAILURE_LIMIT", "2"))


def wp_root() -> str:
    raw = os.getenv("WP_URL", "").strip().rstrip("/")
    if "/wp-json" in raw:
        return raw.split("/wp-json", 1)[0].rstrip("/")
    return raw


def wp_posts_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/posts"


def wp_categories_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/categories"


def wp_media_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/media"


def wp_auth() -> Tuple[str, str]:
    return os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", "")


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    return normalize_text(text).replace(" ", "-")[:120] or "report"


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def normalize_social_url(url: str) -> str:
    return re.sub(r"^https?://x\.com/", "https://twitter.com/", (url or "").strip(), flags=re.I)


def parse_content_container(soup: BeautifulSoup, url: str):
    domain = get_domain(url)
    if "ringsidenews.com" in domain:
        selectors = ["div.cntn-wrp.artl-cnt", "div.sp-cnt", "article", "main"]
    elif "wrestlinginc.com" in domain:
        selectors = ["article.news-post", "article", "div.post-content", "div.entry-content", "main"]
    else:
        selectors = ["article", "div.post-content", "div.entry-content", "main", "body"]
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return node
    return soup.body


def remove_noise(content) -> None:
    if not content:
        return
    for trash in content(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        trash.decompose()
    for bad_sel in [
        ".social_holder", ".social_icons", ".breadcrumbs", ".breadcrumb", "#pagination",
        ".related_link", ".amp-ad-wrapper", "amp-ad", ".newsletter", ".adthrive-ad",
        ".sharing", ".share", ".byline-container", ".author-bio", ".comments-area",
    ]:
        for node in content.select(bad_sel):
            node.decompose()


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def best_img_src(img, base_url: str) -> str:
    for attr in ["data-src", "data-original", "src"]:
        val = img.get(attr)
        if val:
            return urljoin(base_url, val)
    srcset = img.get("srcset") or img.get("data-srcset") or ""
    if srcset:
        first = srcset.split(",")[-1].strip().split(" ")[0]
        if first:
            return urljoin(base_url, first)
    return ""


def extract_meta_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    for attrs in ({"property": "og:image"}, {"name": "twitter:image"}, {"name": "thumbnail"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return urljoin(base_url, tag["content"])
    return None


def is_source_intro_text(text: str) -> bool:
    probe = normalize_text(text or "")
    if not probe:
        return False
    source_intro_patterns = [
        "welcome to wrestling inc",
        "welcome to wrestlinginc",
        "wrestling inc live coverage",
        "wrestling inc s live coverage",
        "wrestlinginc live coverage",
        "benvenuti al report di wrestling inc",
        "benvenuti alla copertura live di wrestling inc",
        "benvenuti ai risultati di wrestling inc",
        "benvenuti al live coverage di wrestling inc",
        "ringside news live coverage",
        "benvenuti alla copertura live di ringside news",
    ]
    if any(pattern in probe for pattern in source_intro_patterns):
        return True
    # Source-branded dateline intros add no editorial value in our report.
    if probe.startswith("benvenuti") and ("wrestling inc" in probe or "ringside news" in probe):
        return True
    if probe.startswith("welcome") and ("wrestling inc" in probe or "ringside news" in probe):
        return True
    return False


def social_embed_key(url: str) -> str:
    u = normalize_social_url(url or "").strip().lower()
    u = u.split("?", 1)[0].rstrip("/")
    # Tweet/status id is the strongest canonical key.
    m = re.search(r"/(?:status|statuses)/(\d+)", u)
    if m:
        return "tweet:" + m.group(1)
    return re.sub(r"\W+", "", u)


def looks_like_social_embed_url(url: str) -> bool:
    u = normalize_social_url(url or "")
    if not re.search(r"(?:twitter\.com|x\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com)", u, re.I):
        return False
    if re.search(r"/(share|intent|hashtag|search)(?:/|\?|$)", u, re.I):
        return False
    return True


def extract_social_urls_from_html_fragment(fragment: str) -> List[str]:
    out: List[str] = []
    if not fragment:
        return out
    decoded_candidates = decode_possible_base64_html(str(fragment)) if "decode_possible_base64_html" in globals() else [str(fragment)]
    raw = html_lib.unescape(" ".join(decoded_candidates))
    try:
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup.find_all(["a", "iframe", "blockquote"]):
            for attr in ["href", "src", "cite", "data-href", "data-url"]:
                val = tag.get(attr)
                if val and looks_like_social_embed_url(val):
                    out.append(normalize_social_url(val))
    except Exception:
        pass
    for m in re.finditer(r"https?://[^\s'\"<>]+", raw, flags=re.I):
        u = m.group(0).rstrip("),.;]")
        if looks_like_social_embed_url(u):
            out.append(normalize_social_url(u))
    deduped: List[str] = []
    seen: set[str] = set()
    for u in out:
        key = social_embed_key(u)
        if key and key not in seen:
            seen.add(key)
            deduped.append(u)
    return deduped


def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:
    domain = get_domain(base_url)
    if "ringsidenews.com" not in domain:
        return []
    root = content or soup
    blocks: List[Dict[str, str]] = []
    seen: set[str] = set()

    def add_urls(urls: List[str], paragraph_anchor: int, source: str) -> None:
        for url in urls:
            key = social_embed_key(url)
            if not key or key in seen:
                continue
            seen.add(key)
            blocks.append({
                "type": "embed",
                "url": normalize_social_url(url),
                "paragraph_anchor": str(paragraph_anchor),
                "source": source,
            })

    paragraph_count = 0
    try:
        for el in root.find_all(True):
            if el.name in {"p", "h2", "h3", "blockquote", "li"}:
                txt = clean_text(el.get_text(" ", strip=True))
                if len(txt) >= 20:
                    paragraph_count += 1
            attrs_to_scan = []
            for attr in ["data-rsn-html", "data-rsn_html", "data-html", "data-embed", "data-lazy", "data-src", "data-url", "href", "src", "cite"]:
                val = el.get(attr)
                if val:
                    attrs_to_scan.append((attr, val))
            cls = " ".join(el.get("class") or [])
            if "rsn-lazy" in cls or attrs_to_scan:
                for attr, val in attrs_to_scan:
                    urls = extract_social_urls_from_html_fragment(val)
                    if urls:
                        add_urls(urls, paragraph_count, f"{el.name}:{attr}")
            if "rsn-lazy" in cls:
                urls = extract_social_urls_from_html_fragment(str(el))
                if urls:
                    add_urls(urls, paragraph_count, f"{el.name}:outer_html")
    except Exception as exc:
        print(f"[RSN EMBED v92] Warning broad extraction failed: {exc}", flush=True)
    try:
        global_urls = extract_social_urls_from_html_fragment(str(root))
        add_urls(global_urls, paragraph_count, "global_html")
    except Exception as exc:
        print(f"[RSN EMBED v92] Warning broad global fallback failed: {exc}", flush=True)
    print(f"[RSN EMBED v92] Estratti broad Ringside embed: {len(blocks)} url={base_url}", flush=True)
    return blocks


def merge_ringside_embeds_by_position(blocks: List[Dict[str, str]], rsn_embeds: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not rsn_embeds:
        return blocks
    existing_keys = {social_embed_key(b.get("url", "")) for b in blocks if b.get("type") == "embed"}
    new_embeds = [e for e in rsn_embeds if social_embed_key(e.get("url", "")) not in existing_keys]
    if not new_embeds:
        print(f"[RSN EMBED v92] Nessun embed Ringside aggiuntivo da reinserire", flush=True)
        return blocks

    out: List[Dict[str, str]] = []
    text_seen = 0
    pending = sorted(new_embeds, key=lambda e: int(e.get("paragraph_anchor") or 0))
    inserted = 0
    for block in blocks:
        out.append(block)
        if block.get("type") in {"heading", "paragraph", "quote"}:
            text_seen += 1
            while pending and int(pending[0].get("paragraph_anchor") or 0) <= text_seen:
                out.append(pending.pop(0))
                inserted += 1
    for e in pending:
        out.append(e)
        inserted += 1
    print(
        f"[RSN EMBED v92] Positional merge: existing={len(existing_keys)} added={inserted} total_expected={len(existing_keys) + inserted}",
        flush=True,
    )
    return out


def node_blob(node) -> str:
    if not node:
        return ""
    attrs = []
    try:
        attrs.extend(node.get("class", []) or [])
        attrs.append(str(node.get("id", "")))
        attrs.append(str(node.get("aria-label", "")))
        attrs.append(str(node.get("role", "")))
        for k, v in getattr(node, "attrs", {}).items():
            if isinstance(v, str) and k.startswith("data"):
                attrs.append(v)
    except Exception:
        pass
    try:
        txt = node.get_text(" ", strip=True)
    except Exception:
        txt = ""
    return normalize_text(" ".join(attrs) + " " + txt)


def text_len_of_node(node) -> int:
    try:
        return len(clean_text(node.get_text(" ", strip=True)))
    except Exception:
        return 0


def is_core_content_node(node) -> bool:
    blob = node_blob(node)
    core_terms = [
        "entry content", "rsn single content", "post content", "article content",
        "article body", "single post content", "td post content",
    ]
    return any(term in blob for term in core_terms) or text_len_of_node(node) > 900


def is_ringside_noise_node(node) -> bool:
    blob = node_blob(node)
    if not blob:
        return False
    if is_core_content_node(node):
        return False
    noise_terms = [
        "posts by ringsidenews", "tweets by ringsidenews", "follow us", "connect with us",
        "share this", "social share", "share buttons", "post share", "rsn social", "ringside social",
        "please credit ringside news", "please cite ringside news", "if you use the transcription",
        "author bio", "author box", "derek holloway", "ringsidenewscom", "youtube com channel",
        "instagram com ringsidenewscom", "twitter com intent tweet", "x com ringsidenews",
        "related articles", "recommended", "newsletter", "comments", "subscribe",
    ]
    return any(term in blob for term in noise_terms)


def is_local_noise_node(node) -> bool:
    if not node or is_core_content_node(node):
        return False
    blob = node_blob(node)
    txt_len = text_len_of_node(node)
    # Whole article wrappers can contain noisy footer text; only decompose compact
    # blocks or explicit service/sidebar/author/share containers.
    classes = " ".join(node.get("class", []) if hasattr(node, "get") else []).lower()
    node_id = str(node.get("id", "") if hasattr(node, "get") else "").lower()
    explicit = any(x in f"{classes} {node_id}" for x in [
        "rsn-social", "ringside-social", "social", "share", "follow", "author", "bio",
        "byline", "profile", "newsletter", "related", "recommended", "comments", "widget", "sidebar",
    ])
    if explicit:
        return True
    compact_noise = any(term in blob for term in [
        "posts by ringsidenews", "tweets by ringsidenews", "follow us", "connect with us",
        "please credit ringside news", "please cite ringside news", "if you use the transcription",
        "derek holloway", "twitter com intent tweet", "youtube com channel", "instagram com ringsidenewscom",
    ])
    return compact_noise and txt_len < 500


def remove_block_noise(content) -> None:
    remove_noise(content)
    selectors = [
        ".rsn-social", ".ringside-social", ".social-links", ".social-share",
        ".post-share", ".share-buttons", ".follow-us",
        ".author-box", ".author-bio", ".byline", ".post-author", ".user-profile",
        ".newsletter", ".related", ".recommended", ".comments-area", ".widget", ".sidebar",
    ]
    for sel in selectors:
        for node in list(content.select(sel)):
            if not is_core_content_node(node):
                node.decompose()
    # Work from leaves upward and never decompose article-sized containers.
    candidates = list(content.find_all(["p", "li", "figure", "blockquote", "ul", "div", "section", "aside", "nav", "footer"]))
    for node in reversed(candidates):
        if node is content:
            continue
        if is_local_noise_node(node):
            node.decompose()


def normalize_url_for_embed(raw_url: str, base_url: str = "") -> str:
    url = html_lib.unescape((raw_url or "").strip())
    if not url:
        return ""
    url = urljoin(base_url, url)
    url = re.sub(r"[\s\"'<>]+$", "", url).rstrip(".,;:)]}")
    if url.startswith("//"):
        url = "https:" + url
    return url


def is_short_social_url(url: str) -> bool:
    low = (url or "").lower()
    return "pic.twitter.com/" in low or "t.co/" in low


def resolve_short_social_url(url: str) -> str:
    if not is_short_social_url(url):
        return url
    try:
        res = session.get(url, timeout=8, allow_redirects=True)
        final_url = normalize_url_for_embed(res.url)
        if final_url:
            print(f"[BLOCK EMBED v92] Shortlink risolto: {url} -> {final_url}", flush=True)
            return final_url
    except Exception as exc:
        print(f"[BLOCK EMBED v92] Warning shortlink non risolto: {url} | {exc}", flush=True)
    return url


def canonical_embed_url(raw_url: str, base_url: str = "") -> str:
    url = normalize_url_for_embed(raw_url, base_url)
    if not url:
        return ""
    url = resolve_short_social_url(url)
    low = url.lower()
    reject_terms = [
        "twitter.com/intent/", "x.com/intent/", "twitter.com/share", "x.com/share",
        "facebook.com/sharer", "mailto:", "youtube.com/channel/", "youtube.com/user/",
        "youtube.com/c/", "instagram.com/ringsidenewscom", "x.com/ringsidenews", "twitter.com/ringsidenews",
    ]
    if any(term in low for term in reject_terms):
        return ""
    if "twitter.com/" in low or "x.com/" in low:
        if "/status/" not in low:
            return ""
        return normalize_social_url(url)
    if "pic.twitter.com/" in low or "t.co/" in low:
        return ""
    if "instagram.com/" in low:
        if not any(x in low for x in ["/p/", "/reel/", "/tv/"]):
            return ""
        return url
    if "youtube.com/" in low:
        if not any(x in low for x in ["/watch", "/embed/", "/shorts/"]):
            return ""
        return url
    if "youtu.be/" in low:
        return url
    if "tiktok.com/" in low:
        if "/video/" not in low and "vm.tiktok.com/" not in low:
            return ""
        return url
    if "bsky.app/" in low or "threads.net/" in low:
        if "/post/" not in low:
            return ""
        return url
    return ""


def extract_embed_from_node(node, base_url: str) -> str:
    if not node or is_local_noise_node(node):
        return ""
    iframe = node if getattr(node, "name", "") == "iframe" else node.find("iframe")
    if iframe and iframe.get("src"):
        url = canonical_embed_url(iframe.get("src"), base_url)
        if url:
            return url
    cite = node.get("cite") if hasattr(node, "get") else None
    if cite:
        url = canonical_embed_url(cite, base_url)
        if url:
            return url
    for k, v in getattr(node, "attrs", {}).items():
        if isinstance(v, str) and any(token in k.lower() for token in ["url", "href", "src", "embed", "permalink"]):
            url = canonical_embed_url(v, base_url)
            if url:
                return url
    links: List[str] = []
    for a in node.find_all("a", href=True) if hasattr(node, "find_all") else []:
        url = canonical_embed_url(a.get("href"), base_url)
        if url:
            links.append(url)
    return links[0] if links else ""


def is_bad_inline_image(src: str, img=None) -> bool:
    low = (src or "").lower()
    bad_terms = ["avatar", "avatar_user", "author", "profile", "user_", "96x96", "80x80", "150x150", "derek%20holloway", "derek-holloway"]
    if any(term in low for term in bad_terms):
        return True
    if img is not None:
        try:
            w = int(str(img.get("width") or "0").replace("px", "") or 0)
            h = int(str(img.get("height") or "0").replace("px", "") or 0)
            if w and h and max(w, h) <= 180:
                return True
        except Exception:
            pass
    return False


def should_skip_block_text(text: str) -> bool:
    norm = normalize_text(text)
    if not norm:
        return True
    skip_phrases = [
        "posts by ringsidenews", "tweets by ringsidenews", "follow us", "connect with us",
        "please credit ringside news", "please cite ringside news", "if you use the transcription",
        "derek holloway is a writer", "ringside news specializing", "youtube com channel",
        "instagram com ringsidenewscom", "twitter com intent tweet", "source ringside news",
    ]
    return any(p in norm for p in skip_phrases)


def is_standalone_quote_text(text: str) -> bool:
    t = clean_text(text)
    if len(t) < 35:
        return False
    return (t.startswith('"') and t.endswith('"')) or (t.startswith("“") and t.endswith("”"))


def extract_blocks(content, base_url: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    if not content:
        return blocks
    remove_block_noise(content)
    seen_images: set[str] = set()
    seen_embeds: set[str] = set()
    allowed = ["h2", "h3", "p", "blockquote", "li", "img", "picture", "amp-img", "iframe", "figure", "a"]
    for el in content.find_all(allowed):
        if el.find_parent(["script", "style", "nav", "footer", "header", "aside", "form"]):
            continue
        # Skip if inside a compact noise block, but do not skip simply because a
        # high-level article wrapper contains noisy footer text elsewhere.
        if any(is_local_noise_node(parent) for parent in el.parents if parent is not content):
            continue

        embed_url = extract_embed_from_node(el, base_url)
        if embed_url:
            if embed_url not in seen_embeds:
                seen_embeds.add(embed_url)
                blocks.append({"type": "embed", "url": embed_url})
            continue

        if el.name in {"img", "amp-img"}:
            src = best_img_src(el, base_url)
            if src and not is_bad_inline_image(src, el) and src not in seen_images:
                seen_images.add(src)
                alt = clean_text(el.get("alt") or "")
                blocks.append({"type": "image", "src": src, "alt": alt})
            continue

        if el.name == "picture":
            img = el.find(["img", "amp-img"])
            if img:
                src = best_img_src(img, base_url)
                if src and not is_bad_inline_image(src, img) and src not in seen_images:
                    seen_images.add(src)
                    alt = clean_text(img.get("alt") or "")
                    blocks.append({"type": "image", "src": src, "alt": alt})
            continue

        if el.name in {"figure", "iframe", "a"}:
            continue

        text = clean_text(el.get_text(" ", strip=True))
        if len(text) < 20 or should_skip_block_text(text):
            continue
        if el.name in {"h2", "h3"}:
            blocks.append({"type": "heading", "level": el.name, "text": text})
        elif el.name == "blockquote" or is_standalone_quote_text(text):
            blocks.append({"type": "quote", "text": text.strip('“”\"')})
        else:
            blocks.append({"type": "paragraph", "text": text})
    return blocks


def scrape_article(url: str) -> Tuple[List[Dict[str, str]], str, Optional[str]]:
    res = session.get(url, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    html = res.text
    soup = BeautifulSoup(html, "html.parser")
    content = parse_content_container(soup, url)
    featured = extract_meta_image(soup, url)
    blocks = extract_blocks(content, url)
    rsn_embeds = extract_ringside_embed_blocks(soup, content, url)
    blocks = merge_ringside_embeds_by_position(blocks, rsn_embeds)
    return blocks, html, featured


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    raw = (raw_text or "").strip().replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end <= start:
        raise ValueError("JSON object non trovato")
    return json.loads(raw[start:end])


def is_temporary_gemini_error(exc: Exception) -> bool:
    text = str(exc or "").lower()
    markers = (
        "429", "500", "503", "unavailable", "resource_exhausted",
        "quota", "rate limit", "rate-limit", "high demand",
        "service unavailable", "timeout", "temporarily",
    )
    return any(marker in text for marker in markers)


def generate_json(prompt: str, chain_name: str = "unknown", cooldown_models: Optional[set[str]] = None) -> Tuple[Dict[str, Any], str]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY mancante")
    is_report_chain = chain_name.startswith("report_")
    active_models = REPORT_MODEL_CHAIN if is_report_chain else MODEL_CHAIN
    print(f"[TRANSLATE v92] Chain attiva: {chain_name} | modelli={','.join(active_models)}", flush=True)
    if is_report_chain:
        print(f"[REPORT v95.2] Gemini chain attiva: {','.join(active_models)}", flush=True)
    client = genai.Client(api_key=GEMINI_API_KEY)
    last: Optional[Exception] = None
    cooldown_models = cooldown_models if cooldown_models is not None else set()
    for model in active_models:
        if is_report_chain and model in cooldown_models:
            record_gemini_event(agent="Bob", phase=chain_name, model=model, status="skipped", reason="report_translation_cooldown", result="cooldown_skipped", pipeline="report", cooldown_skipped=True)
            print(f"[REPORT v95.2] model cooldown skip model={model}", flush=True)
            continue
        try:
            print(f"[TRANSLATE v92] Provo modello: {model} | chain={chain_name}", flush=True)
            res = client.models.generate_content(model=model, contents=prompt)
            data = extract_json_object(res.text)
            record_gemini_event(agent="Bob", phase=chain_name, model=model, status="called", reason="report_translation", result="valid_json", pipeline="report" if is_report_chain else None)
            if is_report_chain:
                print(f"[REPORT v95.2] model selected model={model} purpose={chain_name}", flush=True)
            print(f"[TRANSLATE v92] Modello scelto: {model} | chain={chain_name}", flush=True)
            return data, model
        except Exception as exc:
            last = exc
            temporary = is_report_chain and is_temporary_gemini_error(exc)
            if temporary:
                cooldown_models.add(model)
                print(f"[REPORT v95.2] model cooldown set model={model} reason={str(exc)[:180]}", flush=True)
            record_gemini_event(agent="Bob", phase=chain_name, model=model, status="failed", reason="report_translation_temporary" if temporary else "report_translation", result=str(exc)[:500], pipeline="report" if is_report_chain else None, cooldown_applied=temporary or None)
            print(f"[TRANSLATE v92] Modello fallito: {model} | chain={chain_name} | error={str(exc)[:220]}", flush=True)
            continue
    raise last if last else RuntimeError("Nessun modello disponibile")


def text_blocks(blocks: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        if block["type"] in {"heading", "paragraph", "quote"}:
            out.append({"i": idx, "type": block["type"], "level": block.get("level"), "text": block.get("text", "")})
    return out


def translate_report_blocks(source_title: str, blocks: List[Dict[str, str]], deterministic_title: str) -> Dict[int, str]:
    items = text_blocks(blocks)
    if not items:
        raise ValueError("Nessun blocco testuale da tradurre")

    translated: Dict[int, str] = {}
    total = len(items)
    batch_size = max(8, REPORT_TRANSLATION_BATCH_SIZE)
    print(f"[TRANSLATE v92] Avvio chain report_blocks_legacy_prompt | blocchi_testuali={total} | batch_size={batch_size}", flush=True)
    print("[REPORT v95.2] title policy deterministic, Gemini title chain not used", flush=True)
    cooldown_models: set[str] = set()

    for start in range(0, total, batch_size):
        batch = items[start:start + batch_size]
        batch_indexes = [int(item["i"]) for item in batch]
        batch_no = (start // batch_size) + 1
        batch_total = (total + batch_size - 1) // batch_size

        prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Non fare una traduzione letterale: devi trasformare il materiale in italiano giornalistico naturale, mantenendo fatti e citazioni.

Stai lavorando su un report risultati/recap di uno show, non su una news breve.
Il titolo del report e' gia' deterministico e NON deve essere riscritto.

OBIETTIVO:
- trasformare i blocchi sorgente in italiano fluido, naturale e credibile per una testata italiana di wrestling;
- mantenere tutti i fatti, i match, i segmenti, i risultati, le citazioni e gli sviluppi presenti nei blocchi;
- rispettare l'ordine cronologico dello show;
- non saltare l'ultimo segmento;
- non inventare dettagli e non aggiungere commenti personali;
- non inserire frasi promozionali della fonte, call to action, domande ai lettori o inviti ai commenti.

REGOLE DI TRADUZIONE:
- non tradurre parola per parola se la frase italiana risulterebbe artificiale;
- se una frase inglese e' idiomatica, rendila con una formulazione italiana naturale;
- mantieni nomi propri, ring name, stable, show, eventi, sigle, date e numeri;
- mantieni in inglese i nomi ufficiali di titoli e cinture, come Intercontinental Championship, World Heavyweight Championship, Women's Tag Team Championship, United States Championship, WWE Championship, NXT Championship, AEW World Championship;
- mantieni in inglese i match type e le stipulazioni riconoscibili, come tag team match, triple threat match, fatal four-way match, Last Man Standing, WarGames, Hell in a Cell, ladder match, title match;
- mantieni le mosse riconoscibili in inglese, ma costruisci la frase in italiano naturale;
- release/released/roster cuts non e' rilascio: usa licenziamento, licenziato/licenziata, addio o uscita secondo contesto;
- retirement non e' pensione: usa ritiro o ritirarsi;
- cleared/not cleared significa autorizzato/non autorizzato a lottare;
- promo e' maschile: un promo, mai una promo;
- chop e' femminile: le chop, delle chop;
- grudge match non va tradotto letteralmente: usa regolamento di conti o resa dei conti.

REGOLE DI BLOCCO:
- ricevi solo un batch di blocchi testuali del report completo;
- devi restituire lo stesso numero di item ricevuti in questo batch;
- conserva esattamente l'indice i di ogni item;
- traduci ogni blocco separatamente;
- non fondere blocchi diversi;
- non cambiare ordine;
- non aggiungere link, immagini, tweet o placeholder: media ed embed sono reinseriti dal codice;
- per heading restituisci solo testo tradotto, senza tag HTML;
- per paragraph/quote restituisci solo testo italiano naturale, senza markdown.

STILE DA EVITARE:
- evita calchi come "SmackDown di WWE", "durante l'episodio di WWE Raw", "si e' aperto riguardo", "ha affrontato una sfida", "ha ottenuto una vittoria", "match di ripicca", "giocatore di main event";
- non lasciare inglese generico come "kick out" dentro frasi italiane: usa "si libera", "esce dal conteggio" o "alza la spalla";
- non usare virgolette inutili attorno ai nomi degli show;
- preferisci "puntata di Raw" o "Raw" a formule rigide come "WWE Raw" quando il contesto e' chiaro.

Rispondi solo con JSON valido in una riga:
{{"items":[{{"i":0,"text":"..."}}]}}

TITOLO DETERMINISTICO DA NON MODIFICARE:
{deterministic_title}

TITOLO FONTE:
{source_title}

BATCH:
{batch_no}/{batch_total}

BLOCCHI JSON:
{json.dumps(batch, ensure_ascii=False)}
"""
        print(f"[TRANSLATE v92] Batch report_blocks_legacy_prompt {batch_no}/{batch_total} | items={len(batch)} | indici={batch_indexes[0]}-{batch_indexes[-1]}", flush=True)
        data, model = generate_json(prompt, chain_name="report_blocks_legacy_prompt", cooldown_models=cooldown_models)
        arr = data.get("items") or []
        batch_translated: Dict[int, str] = {}
        for item in arr:
            try:
                i = int(item.get("i"))
                txt = clean_text(str(item.get("text") or ""))
                if txt:
                    batch_translated[i] = txt
            except Exception:
                continue
        expected_batch = set(batch_indexes)
        missing_batch = expected_batch.difference(batch_translated)
        if missing_batch:
            raise ValueError(f"Traduzione batch incompleta: batch={batch_no}/{batch_total} mancanti={sorted(list(missing_batch))} model={model}")
        translated.update(batch_translated)
        print(f"[TRANSLATE v92] Batch completato: {batch_no}/{batch_total} | modello={model} | blocchi={len(batch_translated)}/{len(expected_batch)}", flush=True)

    expected = {int(item["i"]) for item in items}
    missing = expected.difference(translated)
    if missing:
        raise ValueError(f"Traduzione a blocchi incompleta: mancanti={sorted(list(missing))[:20]}")
    print(f"[TRANSLATE v92] Chain completata: report_blocks_legacy_prompt | blocchi_tradotti={len(translated)}/{len(expected)}", flush=True)
    return translated


def upload_media(image_url: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    global MEDIA_UPLOAD_FAILURES, MEDIA_UPLOAD_DISABLED
    if not image_url:
        return None, None
    if MEDIA_UPLOAD_DISABLED:
        print(f"[MEDIA v92] Upload media disabilitato per failure consecutive: skip {image_url}", flush=True)
        return None, None
    if image_url in media_cache:
        return media_cache[image_url]
    try:
        img_res = session.get(image_url, timeout=REQUEST_TIMEOUT)
        img_res.raise_for_status()
        content_type = img_res.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            media_cache[image_url] = (None, None)
            return None, None
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"
            content_type = "image/jpeg"
        filename = f"owtv_report_{os.urandom(4).hex()}{ext}"
        headers = {"Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"'}
        if "wp_request_with_retry" in globals():
            res = wp_request_with_retry("post", wp_media_url(), auth=wp_auth(), headers=headers, data=img_res.content, retries=1)
        else:
            res = session.post(wp_media_url(), auth=wp_auth(), headers=headers, data=img_res.content, timeout=REQUEST_TIMEOUT_WP)
        if res.status_code == 201:
            MEDIA_UPLOAD_FAILURES = 0
            data = res.json()
            media_id = int(data.get("id"))
            src = data.get("source_url") or image_url
            media_cache[image_url] = (media_id, src)
            return media_id, src
        MEDIA_UPLOAD_FAILURES += 1
        print(f"[MEDIA v92] Upload media non riuscito status={res.status_code} failures={MEDIA_UPLOAD_FAILURES}/{MEDIA_UPLOAD_FAILURE_LIMIT}: {image_url}", flush=True)
    except Exception as exc:
        MEDIA_UPLOAD_FAILURES += 1
        print(f"[MEDIA v92] Upload media errore failures={MEDIA_UPLOAD_FAILURES}/{MEDIA_UPLOAD_FAILURE_LIMIT}: {image_url} | {exc}", flush=True)
    if MEDIA_UPLOAD_FAILURES >= MEDIA_UPLOAD_FAILURE_LIMIT:
        MEDIA_UPLOAD_DISABLED = True
        print("[MEDIA v92] Modalita degradata: stop upload immagini inline, continuo pubblicazione senza immagini", flush=True)
    media_cache[image_url] = (None, None)
    return None, None


def normalize_media_identity(url: Optional[str]) -> str:
    raw = (url or "").split("?", 1)[0].strip().lower().rstrip("/")
    return raw


def render_blocks(blocks: List[Dict[str, str]], translated: Dict[int, str], featured_image_url: Optional[str] = None) -> str:
    parts: List[str] = []
    first_inline_image_seen = False
    for idx, block in enumerate(blocks):
        btype = block["type"]
        if btype == "heading":
            level = block.get("level") or "h2"
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            parts.append(f"<{level}>{txt}</{level}>")
        elif btype == "paragraph":
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            parts.append(f"<p>{txt}</p>")
        elif btype == "quote":
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            parts.append(f"<blockquote>{txt}</blockquote>")
        elif btype == "image":
            raw_src = block.get("src")
            if featured_image_url and not first_inline_image_seen:
                first_inline_image_seen = True
                print(f"[MEDIA v92] Skip prima immagine inline per featured attiva: {raw_src}", flush=True)
                continue
            first_inline_image_seen = True
            if featured_image_url and normalize_media_identity(raw_src) == normalize_media_identity(featured_image_url):
                print(f"[MEDIA v92] Skip immagine inline gia usata come featured: {raw_src}", flush=True)
                continue
            _mid, src = upload_media(raw_src)
            if src:
                alt = html_lib.escape(block.get("alt") or "")
                parts.append(f'<figure class="wp-block-image owtv-inline-image"><img src="{html_lib.escape(src)}" alt="{alt}" /></figure>')
        elif btype == "embed":
            url = normalize_social_url(block.get("url", ""))
            if url:
                parts.append(f"\n\n{url}\n\n")
    return "\n".join(parts)


def content_with_embeds(html: str) -> str:
    content = re.sub(r"https?://x\.com/", "https://twitter.com/", html or "", flags=re.I)
    for domain in SOCIAL_DOMAINS:
        pattern = rf'(?<!["\'>])(https?://[^\s<"]*{re.escape(domain)}[^\s<"]*)'
        content = re.sub(pattern, r"\n\n\1\n\n", content)
    return content


def wp_request_with_retry(method: str, url: str, *, retries: int = 3, sleep_seconds: int = 6, **kwargs):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            print(f"[WP v92] {method.upper()} tentativo {attempt}/{retries}: {url}", flush=True)
            res = session.request(method, url, timeout=max(REQUEST_TIMEOUT_WP, 25), **kwargs)
            if res.status_code in {408, 429, 500, 502, 503, 504} and attempt < retries:
                print(f"[WP v92] status temporaneo {res.status_code}, retry...", flush=True)
                time.sleep(sleep_seconds)
                continue
            return res
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            print(f"[WP v92] errore temporaneo attempt {attempt}/{retries}: {exc}", flush=True)
            if attempt < retries:
                time.sleep(sleep_seconds)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("wp_request_with_retry fallito senza risposta")


def resolve_category_id(name: str) -> Optional[int]:
    key = name.lower().strip()
    if key in category_cache:
        return category_cache[key]
    res = wp_request_with_retry("get", wp_categories_url(), params={"search": name, "per_page": 20}, auth=wp_auth())
    if res.status_code != 200:
        category_cache[key] = None
        return None
    cats = res.json()
    exact = [c for c in cats if str(c.get("name", "")).lower() == key]
    chosen = exact[0] if exact else (cats[0] if cats else None)
    cid = int(chosen["id"]) if chosen and chosen.get("id") else None
    category_cache[key] = cid
    return cid


def resolve_category_ids(names: List[str]) -> List[int]:
    out: List[int] = []
    for name in names:
        cid = resolve_category_id(name)
        if cid and cid not in out:
            out.append(cid)
    return out


def source_label(job: Dict[str, Any]) -> str:
    src = str(job.get("source") or "").lower()
    if src == "wrestlinginc":
        return "Wrestling Inc."
    if src == "ringsidenews":
        return "Ringside News"
    return str(job.get("source") or "fonte originale")


def append_source_attribution(content: str, job: Dict[str, Any]) -> str:
    label = html_lib.escape(source_label(job))
    url = html_lib.escape(str(job.get("source_url") or ""))
    if not url:
        return content
    attribution = f'<p class="owtv-source-attribution"><em>Fonte: <a href="{url}" target="_blank" rel="nofollow noopener">{label}</a>.</em></p>'
    return content + "\n" + attribution


def is_bad_ringside_render_line(line: str) -> bool:
    raw = (line or '').strip()
    low = raw.lower()
    if not raw:
        return False
    if 'tweets by ringsidenews' in low:
        return True
    if 'sanjay thakur' in low and ('wwe' in low or 'aew' in low or 'risultati' in low or 'results' in low):
        return True
    if 'riporta i risultati in diretta degli show wwe e aew' in low:
        return True
    if 'provides live results for wwe and aew shows' in low:
        return True
    # Social/channel/profile lines are not article content. Keep only concrete tweet/status URLs.
    if re.match(r'^https?://', raw, re.I):
        if re.search(r'(twitter\.com|x\.com)', raw, re.I):
            return not bool(re.search(r'/(status|statuses)/\d+', raw, re.I))
        if re.search(r'(youtube\.com/channel|youtube\.com/@|instagram\.com/ringsidenews|instagram\.com/ringsidenewscom|facebook\.com|linkedin\.com|pinterest\.com|t\.me)', raw, re.I):
            return True
    return False


def cleanup_ringside_rendered_html(content: str, job: Dict[str, Any]) -> str:
    if str(job.get('source') or '').lower() != 'ringsidenews':
        return content
    lines = (content or '').splitlines()
    cleaned: List[str] = []
    removed = 0
    for line in lines:
        if is_bad_ringside_render_line(line):
            removed += 1
            continue
        cleaned.append(line)
    out = '\n'.join(cleaned)
    # Remove simple paragraphs/blocks containing known boilerplate if translation wrapped them.
    out = re.sub(r'<p>[^<]*Sanjay Thakur[^<]*(?:WWE|AEW)[^<]*</p>\s*', '', out, flags=re.I)
    out = re.sub(r'<p>[^<]*riporta i risultati in diretta degli show WWE e AEW[^<]*</p>\s*', '', out, flags=re.I)
    if removed:
        print(f"[RSN CLEAN v92] Rimosse righe/link social spurie post-render: {removed}", flush=True)
    return out


def publish_report(job: Dict[str, Any], content: str, featured_image_url: Optional[str]) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    content = cleanup_ringside_rendered_html(content, job)
    content = append_source_attribution(content_with_embeds(content), job)
    payload: Dict[str, Any] = {
        "title": job["title"],
        "content": content,
        "status": "publish",
        "meta": {"original_url": job.get("source_url"), "report_key": job.get("report_key")},
    }
    category_ids = resolve_category_ids(job.get("categories", []))
    if category_ids:
        payload["categories"] = category_ids
    media_id, _media_src = upload_media(featured_image_url)
    if media_id:
        payload["featured_media"] = media_id
    res = wp_request_with_retry("post", wp_posts_url(), json=payload, auth=wp_auth())
    if res.status_code == 201:
        data = res.json()
        return int(data.get("id")), data
    raise RuntimeError(f"WordPress publish failed {res.status_code}: {res.text[:500]}")


def run_report_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:
    blocks, _html, featured_image = scrape_article(job["source_url"])
    print(f"[REPORT v92] Blocchi estratti: total={len(blocks)} text={len([b for b in blocks if b.get('type') in {'heading','paragraph','quote'}])} images={len([b for b in blocks if b.get('type') == 'image'])} embeds={len([b for b in blocks if b.get('type') == 'embed'])} featured={bool(featured_image)}", flush=True)
    translated = translate_report_blocks(job.get("source_title") or job.get("title") or "", blocks, job["title"])
    content = render_blocks(blocks, translated, featured_image)
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(job.get("title") or job.get("report_key") or "report")
    (published_dir / f"{slug}.prepublish.html").write_text(content, encoding="utf-8")
    print(f"[REPORT v92] Salvato artifact prepublish: {published_dir / (slug + '.prepublish.html')}", flush=True)
    post_id, post_json = publish_report(job, content, featured_image)
    (published_dir / f"{slug}.html").write_text(content, encoding="utf-8")
    (review_dir / f"{slug}.json").write_text(json.dumps({
        "job": job,
        "post": post_json,
        "blocks": blocks[:120],
        "featured_image": featured_image,
        "translated_indexes": sorted(translated.keys()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(post_id), post_json or {}
