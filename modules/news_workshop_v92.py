from __future__ import annotations

import html as html_lib
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.gemini_ledger import make_operation_id, record_gemini_attempt, record_gemini_event
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from google import genai
except Exception:  # pragma: no cover
    genai = None

REQUEST_TIMEOUT = int(os.getenv("V92_REQUEST_TIMEOUT", "12"))
REQUEST_TIMEOUT_WP = int(os.getenv("V92_WP_TIMEOUT", "25"))
DEFAULT_NEWS_MODEL_CHAIN_V95_2 = "gemini-3.1-flash-lite,gemini-3.5-flash,gemini-2.5-flash-lite,gemini-2.5-flash"
DEFAULT_NEWS_TITLE_MODEL_CHAIN_V95_2 = "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-2.5-flash"
DEFAULT_NEWS_MODEL_CHAIN = os.getenv(
    "NEWS_GEMINI_MODEL_CHAIN",
    os.getenv("GEMINI_NEWS_MODEL_CHAIN", os.getenv("GEMINI_MODEL_CHAIN", DEFAULT_NEWS_MODEL_CHAIN_V95_2)),
)
DEFAULT_NEWS_TITLE_MODEL_CHAIN = os.getenv("NEWS_TITLE_GEMINI_MODEL_CHAIN", DEFAULT_NEWS_TITLE_MODEL_CHAIN_V95_2)
V92_NEWS_SCORING_V2_WORKSHOP = True
V92_BUSINESS_PLE_CARD_PROMPT = True
V92_BUSINESS_LEGAL_CATEGORY_PROMPT = True
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)
_category_cache: Dict[str, Optional[int]] = {}
_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}
V92_NEWS_BLOCK_WORKSHOP_PATCH = True
V92_NEWS_ROBUST_SCRAPER_PATCH = True
V92_NEWS_SCRAPE_DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug" / "news_scrape"
V92_NEWS_FACTUAL_GUARDRAILS_PATCH = True
V92_MIN_NEWS_SOURCE_CHARS = int(os.getenv("V92_MIN_NEWS_SOURCE_CHARS", "650"))
V92_NEWS_EMBED_HANDLING_PATCH = True
V92_NEWS_PLACEHOLDER_CLEANUP_PATCH = True
V92_NEWS_QUOTE_CLEANUP_PATCH = True
V92_NEWS_TRANSLATION_GLOSSARY_PATCH = True
V92_NEWS_MEDIA_DIAGNOSTICS_PATCH = True
V92_DETERMINISTIC_CATEGORY_RESOLUTION = True
_ALL_CATEGORY_CACHE: Optional[List[Dict[str, Any]]] = None


def wp_root() -> str:
    raw = os.getenv("WP_URL", "").strip().rstrip("/")
    if "/wp-json" in raw:
        raw = raw.split("/wp-json", 1)[0].rstrip("/")
    return raw


def wp_auth() -> Tuple[str, str]:
    return os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", "")


def wp_posts_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/posts"


def wp_media_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/media"


def wp_categories_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/categories"


def wp_request_with_retry(method: str, url: str, *, retries: int = 3, sleep_seconds: int = 5, **kwargs):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            print(f"[WP NEWS v92] {method.upper()} tentativo {attempt}/{retries}: {url}", flush=True)
            res = session.request(method, url, timeout=REQUEST_TIMEOUT_WP, **kwargs)
            if res.status_code in {408, 429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(sleep_seconds)
                continue
            return res
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            print(f"[WP NEWS v92] errore temporaneo attempt {attempt}/{retries}: {exc}", flush=True)
            if attempt < retries:
                time.sleep(sleep_seconds)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("wp_request_with_retry failed")


def clean_text(text: str) -> str:
    text = html_lib.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def cleanup_news_translation(title: str, body_html: str) -> Tuple[str, str]:
    """Final deterministic cleanup for wrestling terminology in news."""
    def clean_terms(value: str) -> str:
        out = value or ""
        replacements = [
            (r"\bpartita\b", "match"),
            (r"\bpartite\b", "match"),
            (r"\bincontro\b", "match"),
            (r"\bincontri\b", "match"),
            (r"\bgioco\b", "match"),
            (r"\bgiochi\b", "match"),
        ]
        for pattern, repl in replacements:
            out = re.sub(pattern, repl, out, flags=re.I)
        # Common awkward title/body phrasing from literal outputs.
        out = re.sub(r"non devono farsi spezzare da un errore", "devono reagire agli errori", out, flags=re.I)
        out = re.sub(r"non devono farsi abbattere da un errore", "devono reagire agli errori", out, flags=re.I)
        return out
    return clean_terms(title), clean_terms(body_html)


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    s = normalize_text(text).replace(" ", "-")
    return s[:100] or "news"


def get_domain(url: str) -> str:
    return urlparse(url or "").netloc.lower().replace("www.", "")


def source_label(source: str) -> str:
    src = (source or "").lower()
    if src == "wrestlinginc":
        return "Wrestling Inc."
    if src == "ringsidenews":
        return "Ringside News"
    if src == "fightful":
        return "Fightful"
    return source or "fonte originale"


def parse_content_container(soup: BeautifulSoup, url: str):
    selectors = [
        "article",
        "main article",
        ".article-content",
        ".entry-content",
        ".post-content",
        ".article-body",
        "main",
    ]
    for sel in selectors:
        found = soup.select_one(sel)
        if found:
            return found
    return soup.body or soup


def extract_meta_image(soup: BeautifulSoup, url: str) -> Optional[str]:
    for selector in ["meta[property='og:image']", "meta[name='twitter:image']"]:
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            return urljoin(url, tag["content"].strip())
    img = soup.find("img")
    if img and img.get("src"):
        return urljoin(url, img["src"])
    return None


_EMBED_WARNING_CACHE: set[str] = set()


def warn_embed_once(message: str) -> None:
    if message in _EMBED_WARNING_CACHE:
        return
    _EMBED_WARNING_CACHE.add(message)
    print(message, flush=True)



def canonical_youtube_embed_url_preserve_case(raw_url: str) -> Optional[str]:
    url = html_lib.unescape((raw_url or "").strip())
    if not url:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.strip("/")
    video_id = ""
    if host == "youtu.be":
        video_id = path.split("/", 1)[0]
    elif host in {"youtube.com", "youtube-nocookie.com"}:
        if path.startswith("watch"):
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif path.startswith(("embed/", "shorts/")):
            video_id = path.split("/", 1)[1].split("/", 1)[0]
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}"

def normalize_embed_url(raw_url: str) -> Optional[str]:
    url = html_lib.unescape((raw_url or "").strip())
    if not url:
        return None
    url = re.sub(r"[\s\"'<>]+$", "", url)
    url = url.rstrip("/.,)]}")
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith(("http://", "https://")):
        return None
    youtube_url = canonical_youtube_embed_url_preserve_case(url)
    if youtube_url:
        return youtube_url
    url = url.split("?", 1)[0]
    return url


def is_short_social_url(url: str) -> bool:
    low = (url or "").lower()
    return "pic.twitter.com/" in low or "t.co/" in low


def is_embed_url(url: str) -> bool:
    low = (url or "").lower()
    domains = [
        "twitter.com/", "x.com/", "pic.twitter.com/", "t.co/",
        "instagram.com/", "youtube.com/", "youtu.be/", "tiktok.com/",
        "facebook.com/", "threads.net/", "bsky.app/",
    ]
    if not any(d in low for d in domains):
        return False
    if "twitter.com/share" in low or "x.com/share" in low:
        return False
    return True


def is_canonical_embed_url(url: str) -> bool:
    low = (url or "").lower()
    if "twitter.com/" in low or "x.com/" in low:
        return "/status/" in low
    if "youtube.com/" in low:
        return any(x in low for x in ["/watch", "/embed/", "/shorts/"])
    if "youtu.be/" in low:
        return True
    if "instagram.com/" in low:
        return any(x in low for x in ["/p/", "/reel/", "/tv/"])
    if "tiktok.com/" in low:
        return "/video/" in low or "vm.tiktok.com/" in low
    if "facebook.com/" in low:
        return any(x in low for x in ["/posts/", "/videos/", "/watch/"])
    if "threads.net/" in low:
        return "/post/" in low
    if "bsky.app/" in low:
        return "/post/" in low
    return False


def canonicalize_embed_url(raw_url: str) -> Optional[str]:
    url = normalize_embed_url(raw_url)
    if not url or not is_embed_url(url):
        return None
    low = url.lower()
    if is_short_social_url(url):
        try:
            res = session.get(url, timeout=8, allow_redirects=True)
            final_url = normalize_embed_url(res.url)
            if final_url and is_embed_url(final_url):
                print(f"[NEWS v92] Embed shortlink risolto: {url} -> {final_url}", flush=True)
                url = final_url
                low = url.lower()
        except Exception as exc:
            warn_embed_once(f"[NEWS v92] WARNING: impossibile risolvere shortlink embed {url}: {exc}")
    if "pic.twitter.com/" in low or "t.co/" in low:
        warn_embed_once(f"[NEWS v92] WARNING: embed shortlink non canonico scartato: {url}")
        return None
    if not is_canonical_embed_url(url):
        warn_embed_once(f"[NEWS v92] WARNING: URL embed non canonico scartato: {url}")
        return None
    return url


def is_social_noise_node(node) -> bool:
    if not getattr(node, "name", None):
        return False
    classes = " ".join(node.get("class", []) if hasattr(node, "get") else []).lower()
    node_id = str(node.get("id", "") if hasattr(node, "get") else "").lower()
    aria = str(node.get("aria-label", "") if hasattr(node, "get") else "").lower()
    data_attrs = " ".join(str(v).lower() for k, v in getattr(node, "attrs", {}).items() if isinstance(v, str) and k.startswith("data"))
    blob = f"{classes} {node_id} {aria} {data_attrs}"
    noise_terms = [
        "share", "sharing", "social", "follow", "follow-us", "follow us", "connect", "newsletter",
        "author", "bio", "profile", "sidebar", "widget", "related", "recommended", "comments",
        "ringside-social", "rsn-social", "social-links", "social-share", "post-share", "share-buttons",
    ]
    if any(term in blob for term in noise_terms):
        return True
    text = clean_text(node.get_text(" ", strip=True)) if hasattr(node, "get_text") else ""
    low_text = text.lower()
    if any(phrase in low_text for phrase in ["follow us", "connect with us", "tweets by", "subscribe", "share this"]):
        return True
    return False


def remove_social_noise(container) -> None:
    for node in list(container.select(".rsn-social, .ringside-social, .social, .social-links, .social-share, .post-share, .share, .share-buttons, .follow, .follow-us, .author-box, .author-bio, .sidebar, .widget")):
        node.decompose()
    for node in list(container.find_all(["div", "section", "aside", "ul", "nav", "footer"])):
        if is_social_noise_node(node):
            node.decompose()


def extract_embed_url(node, base_url: str) -> Optional[str]:
    iframe = node if getattr(node, "name", "") == "iframe" else node.find("iframe")
    if iframe and iframe.get("src"):
        candidate = canonicalize_embed_url(urljoin(base_url, iframe.get("src")))
        if candidate:
            return candidate

    cite = node.get("cite") if hasattr(node, "get") else None
    if cite:
        candidate = canonicalize_embed_url(urljoin(base_url, cite))
        if candidate:
            return candidate

    if hasattr(node, "attrs"):
        for key, value in list(node.attrs.items()):
            if not isinstance(value, str):
                continue
            if "url" in key.lower() or "href" in key.lower() or "src" in key.lower() or "embed" in key.lower():
                candidate = canonicalize_embed_url(urljoin(base_url, value))
                if candidate:
                    return candidate

    links: List[str] = []
    for a in node.find_all("a", href=True) if hasattr(node, "find_all") else []:
        candidate = canonicalize_embed_url(urljoin(base_url, a.get("href")))
        if candidate:
            links.append(candidate)
    for candidate in links:
        low = candidate.lower()
        if "/status/" in low or "/p/" in low or "/reel/" in low or "youtu" in low:
            return candidate
    return links[0] if links else None


def is_social_embed_node(node, base_url: str) -> bool:
    if not getattr(node, "name", None):
        return False
    if is_social_noise_node(node):
        return False
    classes = " ".join(node.get("class", []) if hasattr(node, "get") else []).lower()
    if any(marker in classes for marker in ["twitter-tweet", "instagram-media", "tiktok-embed", "wp-block-embed", "embed"]):
        return bool(extract_embed_url(node, base_url))
    if node.name in {"iframe", "figure", "blockquote"} and extract_embed_url(node, base_url):
        return True
    return False


def make_embed_placeholder(index: int) -> str:
    return f"[[OWTV_EMBED_{index}]]"


def provider_slug_for_embed(url: str) -> str:
    low = (url or "").lower()
    if "twitter.com/" in low or "x.com/" in low:
        return "twitter"
    if "instagram.com/" in low:
        return "instagram"
    if "youtube.com/" in low or "youtu.be/" in low:
        return "youtube"
    if "tiktok.com/" in low:
        return "tiktok"
    if "facebook.com/" in low:
        return "facebook"
    return "embed"


def render_wp_embed(url: str) -> str:
    canonical = canonicalize_embed_url(url)
    if not canonical:
        return ""
    safe_url = html_lib.escape(canonical)
    provider = provider_slug_for_embed(canonical)
    return (
        f'<!-- wp:embed {{"url":"{safe_url}","type":"rich","providerNameSlug":"{provider}"}} -->\n'
        f'<figure class="wp-block-embed is-type-rich is-provider-{provider} wp-block-embed-{provider}">'
        f'<div class="wp-block-embed__wrapper">\n{safe_url}\n</div></figure>\n'
        f'<!-- /wp:embed -->'
    )


def strip_internal_placeholders(body_html: str) -> str:
    out = body_html or ""
    before = out
    # Remove exact placeholders and common Gemini-mutated variants.
    patterns = [
        r"\[\[\s*OWTV[_\s-]*EMBED[_\s-]*\d+\s*\]\]",
        r"\[\s*OWTV[_\s-]*EMBED[_\s-]*\d*\s*\]",
        r"OWTV[_\s-]*EMBED[_\s-]*\d+",
        r"\[\[\s*OWTV[_\s-]*EMBED\s*\]\]",
    ]
    for pattern in patterns:
        out = re.sub(pattern, "", out, flags=re.I)
    # Remove empty paragraphs left behind.
    out = re.sub(r"<p>\s*</p>", "", out, flags=re.I)
    out = re.sub(r"\n{3,}", "\n\n", out)
    if before != out:
        print("[NEWS v92] WARNING: rimossi placeholder interni OWTV_EMBED dal corpo finale", flush=True)
    return out.strip()


def inject_news_embeds(body_html: str, embeds: List[Dict[str, str]]) -> str:
    out = body_html or ""
    for embed in embeds:
        placeholder = embed.get("placeholder", "")
        url = embed.get("url", "")
        embed_html = render_wp_embed(url)
        if not embed_html:
            print(f"[NEWS v92] WARNING: embed non renderizzato, URL non valido per oEmbed: {url}", flush=True)
            continue
        if placeholder and placeholder in out:
            out = re.sub(rf"<p>\s*{re.escape(placeholder)}\s*</p>", embed_html, out)
            out = out.replace(placeholder, embed_html)
        else:
            print(f"[NEWS v92] WARNING: placeholder embed perso da Gemini, non appendo per evitare doppioni: {placeholder} -> {url}", flush=True)
    return out


def should_skip_text(text: str) -> bool:
    low = normalize_text(text)
    if len(low) < 20:
        return True
    boilerplate = [
        "advertisement",
        "continue reading",
        "subscribe to",
        "follow us",
        "share this article",
        "sign up",
        "privacy policy",
        "terms of use",
        "related articles",
    ]
    return any(x in low for x in boilerplate)


def node_text_len(node) -> int:
    if node is None:
        return 0
    try:
        txt = clean_text(node.get_text(" ", strip=True))
    except Exception:
        return 0
    norm = normalize_text(txt)
    if not norm:
        return 0
    noise = ["advertisement", "follow us", "share this", "related articles", "subscribe", "comments"]
    if any(x in norm for x in noise) and len(norm) < 800:
        return 0
    return len(txt)


def find_best_news_container(soup: BeautifulSoup, url: str):
    # Ringside single articles put the real body here. Prefer it over generic
    # article/main containers, which can include wrappers, social bars or empty
    # layout nodes.
    preferred_selectors = [
        ".entry-content.rsn-single-content",
        ".rsn-single-content",
        "article .entry-content",
        ".entry-content",
    ]
    diagnostics: List[Tuple[int, str]] = []
    for sel in preferred_selectors:
        nodes = soup.select(sel)
        best = None
        best_score = 0
        for node in nodes:
            score = node_text_len(node)
            diagnostics.append((score, sel))
            if score > best_score:
                best_score = score
                best = node
        if best is not None and best_score >= 250:
            print(f"[NEWS v92] Scraper container preferito: selector={sel} chars={best_score} url={url}", flush=True)
            return best

    selectors = [
        "article",
        "main article",
        ".article-content",
        ".post-content",
        ".article-body",
        ".single-post-content",
        ".td-post-content",
        ".content-area article",
        "main",
    ]
    candidates = []
    for sel in selectors:
        for node in soup.select(sel):
            score = node_text_len(node)
            diagnostics.append((score, sel))
            if score:
                candidates.append((score, sel, node))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        score, sel, node = candidates[0]
        diag = "; ".join(f"{s}:{c}" for c, s in sorted(diagnostics, reverse=True)[:8])
        print(f"[NEWS v92] Scraper container scelto: selector={sel} chars={score} url={url} | candidates={diag}", flush=True)
        return node
    diag = "; ".join(f"{s}:{c}" for c, s in sorted(diagnostics, reverse=True)[:8])
    print(f"[NEWS v92] WARNING: nessun container testuale forte trovato, uso body url={url} | candidates={diag}", flush=True)
    return soup.body or soup


def extract_jsonld_article_text(soup: BeautifulSoup) -> str:
    bodies: List[str] = []

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            typ = obj.get("@type") or obj.get("type") or ""
            typ_blob = " ".join(typ) if isinstance(typ, list) else str(typ)
            if any(x in typ_blob.lower() for x in ["article", "newsarticle", "blogposting"]):
                for key in ["articleBody", "description"]:
                    value = obj.get(key)
                    if isinstance(value, str) and len(clean_text(value)) > 250:
                        bodies.append(clean_text(value))
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            for item in obj:
                visit(item)

    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            visit(data)
        except Exception:
            continue
    if not bodies:
        return ""
    bodies = sorted(set(bodies), key=len, reverse=True)
    print(f"[NEWS v92] JSON-LD articleBody fallback disponibile: chars={len(bodies[0])}", flush=True)
    return bodies[0]


def extract_meta_description_text(soup: BeautifulSoup) -> str:
    chunks: List[str] = []
    for selector in ["meta[property='og:description']", "meta[name='description']", "meta[name='twitter:description']"]:
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            val = clean_text(tag.get("content"))
            if len(val) > 120:
                chunks.append(val)
    return "\n\n".join(dict.fromkeys(chunks))


def save_weak_scrape_debug_html(url: str, html: str, article_text: str, soup: BeautifulSoup) -> None:
    try:
        V92_NEWS_SCRAPE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        slug = slugify(urlparse(url).path.strip("/") or "news")[:100]
        html_path = V92_NEWS_SCRAPE_DEBUG_DIR / f"{slug}.html"
        meta_path = V92_NEWS_SCRAPE_DEBUG_DIR / f"{slug}.debug.txt"
        html_path.write_text(html or "", encoding="utf-8", errors="ignore")
        selector_lines = []
        for sel in [
            ".entry-content.rsn-single-content", ".rsn-single-content", "article .entry-content",
            ".entry-content", "article", "main article", "main", "body",
        ]:
            nodes = soup.select(sel)
            scores = [node_text_len(n) for n in nodes[:5]]
            selector_lines.append(f"{sel}: count={len(nodes)} scores={scores}")
        h1 = soup.find("h1")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_path.write_text(
            "\n".join([
                f"url={url}",
                f"html_chars={len(html or '')}",
                f"article_chars={len(article_text or '')}",
                f"title={title}",
                f"h1={clean_text(h1.get_text(' ', strip=True)) if h1 else ''}",
                *selector_lines,
            ]),
            encoding="utf-8",
        )
        print(f"[NEWS v92] Debug scrape salvato: {html_path} | {meta_path}", flush=True)
    except Exception as exc:
        print(f"[NEWS v92] WARNING: impossibile salvare debug scrape: {exc}", flush=True)


def safe_remove_social_noise(container) -> None:
    fn = globals().get("remove_social_noise")
    if callable(fn):
        try:
            fn(container)
        except Exception as exc:
            print(f"[NEWS v92] WARNING: remove_social_noise fallita: {exc}", flush=True)


def is_embed_node_safe(el, url: str) -> bool:
    fn = globals().get("is_social_embed_node")
    if callable(fn):
        try:
            return bool(fn(el, url))
        except Exception:
            return False
    return False


def extract_embed_url_safe(el, url: str) -> Optional[str]:
    fn = globals().get("extract_embed_url")
    if callable(fn):
        try:
            return fn(el, url)
        except Exception:
            return None
    return None


def make_embed_placeholder_safe(index: int) -> str:
    fn = globals().get("make_embed_placeholder")
    if callable(fn):
        return fn(index)
    return f"[[OWTV_EMBED_{index}]]"


def extract_article_text_and_media(url: str) -> Tuple[str, Optional[str], List[Dict[str, str]]]:
    res = session.get(url, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    raw_html = res.text
    print(f"[NEWS v92] Scrape fetch status={res.status_code} content_type={res.headers.get('content-type', '')} html_chars={len(raw_html or '')} url={url}", flush=True)
    soup = BeautifulSoup(raw_html, "html.parser")
    for node in soup.select("script:not([type*='ld+json']), style, noscript, nav, footer, aside, form"):
        node.decompose()
    container = find_best_news_container(soup, url)
    safe_remove_social_noise(container)
    featured = extract_meta_image(soup, url)
    parts: List[str] = []
    embeds: List[Dict[str, str]] = []

    for el in container.find_all(["h2", "h3", "p", "li", "blockquote", "figure", "iframe", "div"]):
        if any(is_embed_node_safe(parent, url) for parent in el.parents if parent is not container):
            continue

        if is_embed_node_safe(el, url):
            embed_url = extract_embed_url_safe(el, url)
            if embed_url and not any(e.get("url") == embed_url for e in embeds):
                placeholder = make_embed_placeholder_safe(len(embeds) + 1)
                embeds.append({"placeholder": placeholder, "url": embed_url})
                parts.append(placeholder)
                print(f"[NEWS v92] Embed rilevato: {placeholder} -> {embed_url}", flush=True)
            continue

        if el.name in {"figure", "iframe", "div"}:
            continue

        txt = clean_text(el.get_text(" ", strip=True))
        if should_skip_text(txt):
            continue
        if el.name in {"h2", "h3"}:
            parts.append(f"## {txt}")
        elif el.name == "blockquote":
            parts.append(f"> {txt}")
        else:
            parts.append(txt)

    article_text = "\n\n".join(dict.fromkeys([p for p in parts if p.strip()]))

    if len(article_text) < 400:
        jsonld_text = extract_jsonld_article_text(soup)
        if len(jsonld_text) > len(article_text):
            article_text = jsonld_text

    if len(article_text) < 250:
        meta_text = extract_meta_description_text(soup)
        if len(meta_text) > len(article_text):
            article_text = meta_text

    if len(article_text) < 250:
        fallback = clean_text(container.get_text(" ", strip=True))
        if len(fallback) > len(article_text):
            article_text = fallback[:8000]

    if embeds:
        print(f"[NEWS v92] Embed totali estratti: {len(embeds)}", flush=True)
    if len(article_text) < 650:
        print(f"[NEWS v92] WARNING: estrazione news debole chars={len(article_text)} url={url}", flush=True)
        save_weak_scrape_debug_html(url, raw_html, article_text, soup)
    return article_text[:18000], featured, embeds


def gemini_client():
    if genai is None:
        raise RuntimeError("google-genai non disponibile")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY mancante")
    return genai.Client(api_key=key)


def model_chain(purpose: str = "") -> List[str]:
    raw = DEFAULT_NEWS_TITLE_MODEL_CHAIN if purpose == "news_translate_title" else DEFAULT_NEWS_MODEL_CHAIN
    return [m.strip() for m in raw.split(",") if m.strip()]


def gemini_generate(prompt: str, *, purpose: str, ledger_context: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    client = gemini_client()
    last_error: Optional[Exception] = None
    context = ledger_context or {}
    operation_id = make_operation_id("Bob" if purpose.startswith("news_translate") else "Menzo", purpose, context.get("article_id") or context.get("candidate_id") or context.get("url") or context.get("source_url") or purpose)
    for attempt_index, model in enumerate(model_chain(purpose)):
        try:
            print(f"[NEWS v92] Provo modello: {model} | purpose={purpose}", flush=True)
            response = client.models.generate_content(model=model, contents=prompt)
            text = getattr(response, "text", None) or ""
            record_gemini_attempt(response=response, agent="Bob" if purpose.startswith("news_translate") else "Menzo", phase=purpose, model_requested=model, status="called", reason=purpose, result="text" if text.strip() else "empty_response", operation_id=operation_id, attempt_index=attempt_index, fallback=attempt_index > 0, purpose=purpose, **context)
            if text.strip():
                print(f"[NEWS v92] Modello scelto: {model} | purpose={purpose}", flush=True)
                return text.strip(), model
        except Exception as exc:
            last_error = exc
            record_gemini_attempt(response=None, agent="Bob" if purpose.startswith("news_translate") else "Menzo", phase=purpose, model_requested=model, status="failed", reason=purpose, result=str(exc)[:500], operation_id=operation_id, attempt_index=attempt_index, fallback=attempt_index > 0, purpose=purpose, **context)
            print(f"[NEWS v92] Modello fallito: {model} | purpose={purpose} | error={exc}", flush=True)
            continue
    raise RuntimeError(f"Nessun modello Gemini disponibile per {purpose}: {last_error}")


def extract_json(raw: str) -> Dict[str, Any]:
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?", "", txt, flags=re.I).strip()
    txt = re.sub(r"```$", "", txt).strip()
    start = txt.find("{")
    end = txt.rfind("}")
    if start >= 0 and end > start:
        txt = txt[start:end + 1]
    return json.loads(txt)


def analyze_news_editorial(source_title: str, summary: str, source: str, url: str, local_score: int, local_reason: str) -> Dict[str, Any]:
    """Light editorial analysis for v92 news scoring.

    Gemini returns semantic fields; the final score is still computed in bot_v92.py.
    """
    prompt = f"""
Sei un editor italiano esperto di wrestling. Devi valutare se una news merita pubblicazione su OpenWrestlingTV.
Non devi tradurre l'articolo. Devi solo classificarlo editorialmente.

Classi ammesse:
- hard_news: sviluppo concreto, urgente o rilevante
- event_outcome: risultato/evento autonomo rilevante, non report completo
- strategic_discussion: business, TV deal, WWE/AEW/TKO, problemi organizzativi, direzione creativa rilevante
- standard_useful: intervista o dettaglio utile ma non urgente
- soft_news: curiosità o dichiarazione interessante ma leggera
- opinion: opinione/commentary/listicle
- report_like: report/results/recap show, da non trattare come news normale
- low_value: contenuto debole, marginale, evergreen o non adatto

Restituisci SOLO JSON valido:
{{
  "article_type": "hard_news | event_outcome | strategic_discussion | standard_useful | soft_news | opinion | report_like | low_value",
  "priority": "hard | soft | skip",
  "category": "WWE | AEW | NXT | TNA | World | Business",
  "main_entities": ["..."],
  "story_core": "slug-breve-del-nucleo-notizia",
  "news_action": "azione_narrativa_breve",
  "freshness": "fresh | stale | evergreen",
  "editorial_notes": "motivo sintetico"
}}

Criteri:
- hard solo se c'e' uno sviluppo concreto o molto rilevante.
- soft per interviste, curiosita' backstage, dichiarazioni interessanti ma non decisive.
- skip per report/results/recap, listicle leggero, opinione senza fatto nuovo, rumor troppo vago, contenuto marginale.
- Non penalizzare automaticamente una news solo perche' parla dello stesso personaggio di altre.
- Se una news riguarda ownership, acquisizioni, vendita, parent company, merger, ricavi, media rights, TV deal o accordi corporate, usa category Business anche se riguarda NJPW, AAA, ROH, NOAH, MLW o altre realta' normalmente World.
- Non usare category Business per arresti, cauzioni, problemi legali personali, infortuni, salute mentale o vicende mediche di un wrestler: in quei casi usa la federazione pertinente (WWE, AEW, NXT, TNA) salvo che la notizia riguardi direttamente la societa', un contratto, una causa corporate o un accordo economico.
- Le card complete o aggiornate dei PLE/PPV WWE e AEW hanno valore editoriale e SEO medio-alto: non classificarle come low_value o preview generica.
- Un aggiornamento card PLE/PPV con match aggiunto, rimosso o modificato puo' essere hard_news/event_outcome se riguarda titolo, top name o stipulazione importante; altrimenti standard_useful o soft_news alta.

Fonte: {source_label(source)}
URL: {url}
Titolo: {source_title}
Summary feed: {summary}
Pre-score locale: {local_score}/100
Motivo pre-score: {local_reason}
""".strip()
    raw, model = gemini_generate(prompt, purpose="news_editorial_analysis", ledger_context={"source_url": url, "url": url, "title": source_title, "candidate_id": url})
    data = extract_json(raw)
    data["analysis_model"] = model
    return data


def cleanup_news_html(body_html: str) -> str:
    """Normalize Gemini HTML before publishing.

    In particular, prevent blockquotes from being nested inside paragraphs.
    """
    html = str(body_html or "").strip()
    if not html:
        return html
    # Common malformed pattern: <p>text <blockquote>quote</blockquote></p>
    html = re.sub(
        r"<p>([^<]*?)\s*<blockquote>(.*?)</blockquote>\s*</p>",
        lambda m: (f"<p>{m.group(1).strip()}</p>" if m.group(1).strip() else "") + f"<blockquote>{m.group(2).strip()}</blockquote>",
        html,
        flags=re.I | re.S,
    )
    # If there are still blockquotes inside p tags, split conservatively.
    html = re.sub(r"<p>\s*(<blockquote>.*?</blockquote>)\s*</p>", r"\1", html, flags=re.I | re.S)
    html = re.sub(r"</blockquote>\s*</p>", "</blockquote>", html, flags=re.I)
    html = re.sub(r"<p>\s*<blockquote>", "<blockquote>", html, flags=re.I)
    return html


def source_context_blob(source_title: str, source_text: str) -> str:
    return normalize_text(f"{source_title} {source_text}")


def protected_event_instructions(source_title: str, source_text: str) -> str:
    blob = source_context_blob(source_title, source_text)
    rules: List[str] = []
    if "clash in italy" in blob:
        rules.append("- Nome evento protetto: scrivi sempre e solo 'Clash in Italy'. Non trasformarlo mai in 'Clash at the Castle', 'Clash in the Castle' o varianti simili.")
    if "clash at the castle" in blob:
        rules.append("- Nome evento protetto: se il testo originale dice 'Clash at the Castle', mantieni esattamente 'Clash at the Castle'.")
    if "all in" in blob:
        rules.append("- Nome evento protetto: 'All In' resta 'All In'.")
    if "double or nothing" in blob:
        rules.append("- Nome evento protetto: 'Double or Nothing' resta 'Double or Nothing'.")
    if "forbidden door" in blob:
        rules.append("- Nome evento protetto: 'Forbidden Door' resta 'Forbidden Door'.")
    if "worlds end" in blob or "world's end" in blob:
        rules.append("- Nome evento protetto: 'Worlds End' resta 'Worlds End'.")
    return "\n".join(rules)


def cleanup_protected_event_names(title: str, body_html: str, source_title: str, source_text: str) -> Tuple[str, str]:
    blob = source_context_blob(source_title, source_text)
    out_title = title or ""
    out_body = body_html or ""
    if "clash in italy" in blob:
        patterns = [
            r"\bWWE\s+Clash\s+at\s+the\s+Castle\s+in\s+Italia\b",
            r"\bWWE\s+Clash\s+in\s+the\s+Castle\s+in\s+Italia\b",
            r"\bClash\s+at\s+the\s+Castle\s+in\s+Italia\b",
            r"\bClash\s+in\s+the\s+Castle\s+in\s+Italia\b",
            r"\bWWE\s+Clash\s+at\s+the\s+Castle\b",
            r"\bWWE\s+Clash\s+in\s+the\s+Castle\b",
            r"\bClash\s+at\s+the\s+Castle\b",
            r"\bClash\s+in\s+the\s+Castle\b",
        ]
        for pattern in patterns:
            out_title = re.sub(pattern, "WWE Clash in Italy", out_title, flags=re.I)
            out_body = re.sub(pattern, "WWE Clash in Italy", out_body, flags=re.I)
    return out_title, out_body


def validate_no_event_hallucination(title: str, body_html: str, source_title: str, source_text: str) -> None:
    src = source_context_blob(source_title, source_text)
    out = normalize_text(f"{title} {body_html}")
    if "clash at the castle" in out and "clash at the castle" not in src:
        raise RuntimeError("Factual guardrail: output contiene Clash at the Castle non presente nella fonte")
    if "clash in the castle" in out and "clash in the castle" not in src:
        raise RuntimeError("Factual guardrail: output contiene Clash in the Castle non presente nella fonte")


def validate_source_text_quality(source_text: str, source_url: str) -> None:
    chars = len(source_text or "")
    if chars < V92_MIN_NEWS_SOURCE_CHARS:
        raise RuntimeError(f"Source extraction too short for safe translation: chars={chars} url={source_url}")


def translate_news(source_title: str, source_text: str, source: str) -> Tuple[str, str, str]:
    prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Non fare una traduzione letterale: devi trasformare il materiale in italiano giornalistico naturale, mantenendo fatti, nomi, date e citazioni.

Regole obbligatorie:
- Non inventare informazioni non presenti nel testo.
- Non aggiungere opinioni personali.
- Mantieni tutte le citazioni attribuite: se nel testo originale ci sono virgolette o dichiarazioni, riportale in italiano in modo fedele.
- Le citazioni dirette lunghe o isolate devono essere in <blockquote>, non in un normale <p>. Non aggiungere un punto dopo la chiusura della citazione o del blockquote.
- Non scrivere introduzioni tipo "ecco la traduzione".
- Non citare la fonte nel corpo: la fonte viene aggiunta automaticamente dal sistema.
- Se nel testo trovi placeholder come [[OWTV_EMBED_1]], [[OWTV_EMBED_2]], mantienili identici, da soli, senza tradurli e senza trasformarli in citazioni.
- Non trasformare tweet, post social, iframe o embed in blockquote testuali: gli embed vengono reinseriti automaticamente dal sistema.
- Titolo italiano: naturale, giornalistico, non clickbait, massimo 95 caratteri.
- Corpo: articolo completo in italiano, con paragrafi leggibili.
- Evita stile AI, frasi gonfie, ripetizioni inutili e formule generiche.
- Regola ferrea di glossario: nel wrestling "match" resta sempre "match". Non tradurlo mai con partita, incontro, gara o gioco.
- Mantieni naturali termini come match, promo, segment, storyline, push, turn, feud, stable, tag team, heel, face, main event.
- "Botch" puo' restare botch se il contesto e' tecnico; altrimenti usa errore sul ring, ma non costruire titoli goffi.
- Evita titoli letterali o melodrammatici come "non devono farsi spezzare": preferisci formule giornalistiche naturali.
- Regola ferrea di glossario: nel wrestling "match" resta sempre "match". Non tradurlo mai con partita, incontro, gara o gioco.
- Mantieni naturali termini come match, promo, segment, storyline, push, turn, feud, stable, tag team, heel, face, main event.
- "Botch" puo' restare botch se il contesto e' tecnico; altrimenti usa errore sul ring, ma non costruire titoli goffi.
- Evita titoli letterali o melodrammatici come "non devono farsi spezzare": preferisci formule giornalistiche naturali.
{protected_event_instructions(source_title, source_text)}
- Regola ferrea di glossario: nel wrestling "match" resta sempre "match". Non tradurlo mai con partita, incontro, gara o gioco.
- Mantieni naturali termini come match, promo, segment, storyline, push, turn, feud, stable, tag team, heel, face, main event.
- "Botch" puo' restare botch se il contesto e' tecnico; altrimenti usa errore sul ring, ma non costruire titoli goffi.
- Evita titoli letterali o melodrammatici come "non devono farsi spezzare": preferisci formule giornalistiche naturali.

Restituisci SOLO JSON valido con questa struttura:
{{
  "title": "titolo italiano",
  "body_html": "corpo articolo in HTML semplice con <p>, <h2>, <blockquote> se utile"
}}

Fonte: {source_label(source)}
Titolo originale: {source_title}

TESTO ORIGINALE:
{source_text}
""".strip()
    raw, model = gemini_generate(prompt, purpose="news_translate_title", ledger_context={"source_url": url, "url": url, "title": source_title, "candidate_id": url})
    data = extract_json(raw)
    title = clean_text(str(data.get("title") or source_title))[:120]
    body = cleanup_news_html(str(data.get("body_html") or "").strip())
    title, body = cleanup_protected_event_names(title, body, source_title, source_text)
    validate_no_event_hallucination(title, body, source_title, source_text)
    body = cleanup_news_quotes(body)
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model


def category_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def fetch_all_categories() -> List[Dict[str, Any]]:
    global _ALL_CATEGORY_CACHE
    if _ALL_CATEGORY_CACHE is not None:
        return _ALL_CATEGORY_CACHE
    cats: List[Dict[str, Any]] = []
    page = 1
    while page <= 5:
        res = wp_request_with_retry("get", wp_categories_url(), params={"per_page": 100, "page": page}, auth=wp_auth())
        if res.status_code != 200:
            break
        chunk = res.json()
        if not isinstance(chunk, list) or not chunk:
            break
        cats.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    _ALL_CATEGORY_CACHE = cats
    print(f"[NEWS v92] Categorie WP caricate: {len(cats)}", flush=True)
    return cats


def create_category(name: str) -> Optional[int]:
    global _ALL_CATEGORY_CACHE
    res = wp_request_with_retry("post", wp_categories_url(), json={"name": name, "slug": category_slug(name)}, auth=wp_auth())
    if res.status_code in {200, 201}:
        data = res.json()
        cid = int(data.get("id")) if data.get("id") else None
        _ALL_CATEGORY_CACHE = None
        print(f"[NEWS v92] Categoria WP creata: {name} -> {cid}", flush=True)
        return cid
    print(f"[NEWS v92] Creazione categoria WP fallita: {name} status={res.status_code} body={res.text[:200]}", flush=True)
    return None


def resolve_category_id(name: str) -> Optional[int]:
    clean = (name or "").strip()
    if not clean:
        return None
    key = clean.lower()
    if key in _category_cache:
        return _category_cache[key]

    target_slug = category_slug(clean)
    cats = fetch_all_categories()

    # Exact name first.
    for cat in cats:
        if str(cat.get("name", "")).strip().lower() == key:
            cid = int(cat["id"])
            _category_cache[key] = cid
            print(f"[NEWS v92] Categoria risolta exact-name: {clean} -> {cid}", flush=True)
            return cid

    # Exact slug second.
    for cat in cats:
        if str(cat.get("slug", "")).strip().lower() == target_slug:
            cid = int(cat["id"])
            _category_cache[key] = cid
            print(f"[NEWS v92] Categoria risolta exact-slug: {clean}/{target_slug} -> {cid}", flush=True)
            return cid

    # Never use fuzzy first result. Create missing expected category instead.
    cid = create_category(clean)
    _category_cache[key] = cid
    return cid


def resolve_category_ids(names: List[str]) -> List[int]:
    out: List[int] = []
    clean_names = [str(name).strip() for name in names if str(name).strip()]
    print(f"[NEWS v92] Categorie richieste: {clean_names}", flush=True)
    for name in clean_names:
        cid = resolve_category_id(name)
        if cid and cid not in out:
            out.append(cid)
    print(f"[NEWS v92] Categorie risolte ids: {out}", flush=True)
    return out


def upload_media(image_url: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    if not image_url:
        print("[NEWS v92] Featured image assente: nessun upload media", flush=True)
        return None, None
    print(f"[NEWS v92] Featured image candidata: {image_url}", flush=True)
    if image_url in _media_cache:
        cached_id, cached_src = _media_cache[image_url]
        print(f"[NEWS v92] Featured image cache hit: media_id={cached_id} src={cached_src}", flush=True)
        # Successful cache hits are fine. Failed cache hits are retried once because
        # they may have been transient network/content-type failures in the same run.
        if cached_id:
            return cached_id, cached_src
        print(f"[NEWS v92] Featured image cache failure precedente: ritento upload {image_url}", flush=True)
    try:
        img = session.get(image_url, timeout=REQUEST_TIMEOUT)
        print(f"[NEWS v92] Featured image fetch status={img.status_code} content_type={img.headers.get('Content-Type', '')} bytes={len(img.content or b'')}", flush=True)
        img.raise_for_status()
        content_type = img.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            print(f"[NEWS v92] Featured image scartata: content-type non immagine ({content_type}) url={image_url}", flush=True)
            return None, image_url
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        filename = f"owtv_news_{os.urandom(4).hex()}{ext}"
        headers = {"Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"'}
        res = wp_request_with_retry("post", wp_media_url(), auth=wp_auth(), headers=headers, data=img.content)
        print(f"[NEWS v92] Featured image WP upload status={res.status_code} url={image_url}", flush=True)
        if res.status_code == 201:
            data = res.json()
            media_id = int(data.get("id"))
            src = data.get("source_url") or image_url
            _media_cache[image_url] = (media_id, src)
            print(f"[NEWS v92] Featured image caricata: media_id={media_id} src={src}", flush=True)
            return media_id, src
        print(f"[NEWS v92] Featured image upload fallito status={res.status_code} body={res.text[:300]}", flush=True)
    except Exception as exc:
        print(f"[NEWS v92] Upload media fallito: {image_url} | {exc}", flush=True)
    # Do not cache failed uploads as final truth. Let a future run/retry attempt again.
    return None, image_url


def append_source(content: str, source: str, url: str) -> str:
    label = html_lib.escape(source_label(source))
    href = html_lib.escape(url or "")
    if not href:
        return content
    return content + f'\n<p class="owtv-source-attribution"><em>Fonte: <a href="{href}" target="_blank" rel="nofollow noopener">{label}</a>.</em></p>'


def cleanup_news_quotes(body_html: str) -> str:
    out = body_html or ""
    before = out

    # No punctuation after a closed blockquote generated by Gemini.
    out = re.sub(r"(</blockquote>)\s*[\.]", r"\1", out, flags=re.I)
    out = re.sub(r"(</figure>)\s*[\.]", r"\1", out, flags=re.I)

    # Remove stray period after a closing quote before paragraph/block closing.
    out = re.sub(r"([”\"])\s*\.\s*(</p>)", r"\1\2", out, flags=re.I)

    # Convert standalone quoted paragraphs into blockquotes. This intentionally
    # targets only paragraphs that start and end with quotes, so normal prose with
    # partial quoted phrases remains untouched.
    def convert_quoted_paragraph(match):
        inner = match.group(1).strip()
        plain = re.sub(r"<[^>]+>", "", inner).strip()
        if len(plain) < 35:
            return match.group(0)
        if not re.match(r"^[\"“].*[\"”]$", plain, flags=re.S):
            return match.group(0)
        return f"<blockquote><p>{inner}</p></blockquote>"

    out = re.sub(r"<p>\s*((?:[\"“])[^<]{35,}(?:[\"”]))\s*</p>", convert_quoted_paragraph, out, flags=re.I | re.S)

    # Clean accidental empty paragraphs after conversions.
    out = re.sub(r"<p>\s*</p>", "", out, flags=re.I)
    if out != before:
        print("[NEWS v92] Quote cleanup applicato", flush=True)
    return out.strip()


def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    from modules.simone_report_integrity import cleanup_rendered_html
    body_html = cleanup_news_quotes(body_html)
    media_id, _src = upload_media(image_url)
    body_html = cleanup_news_html(body_html)
    body_html, cleanup_diagnostics = cleanup_rendered_html(body_html, str(job.get("source") or ""))
    if cleanup_diagnostics["final_boilerplate_blocks_removed"]:
        print(f"[NEWS CLEAN v95.13.1] final_boilerplate_blocks_removed={cleanup_diagnostics['final_boilerplate_blocks_removed']}", flush=True)
    payload: Dict[str, Any] = {
        "title": translated_title,
        "content": append_source(body_html, str(job.get("source") or ""), str(job.get("source_url") or "")),
        "status": "publish",
        "categories": resolve_category_ids(list(job.get("categories") or [])),
        "meta": {"original_url": job.get("source_url"), "news_key": job.get("news_key")},
    }
    if media_id:
        payload["featured_media"] = media_id
    res = wp_request_with_retry("post", wp_posts_url(), json=payload, auth=wp_auth())
    if res.status_code not in {200, 201}:
        raise RuntimeError(f"WP post news failed: {res.status_code} {res.text[:500]}")
    data = res.json()
    return int(data.get("id")), data


def news_text_blocks(blocks: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        if block.get("type") in {"heading", "paragraph", "quote"}:
            txt = clean_text(str(block.get("text") or ""))
            if txt:
                items.append({
                    "i": idx,
                    "type": block.get("type"),
                    "level": block.get("level"),
                    "text": txt,
                })
    return items


def validate_news_blocks_quality(blocks: List[Dict[str, str]], source_url: str) -> None:
    text_chars = sum(len(str(b.get("text") or "")) for b in blocks if b.get("type") in {"heading", "paragraph", "quote"})
    text_count = len([b for b in blocks if b.get("type") in {"heading", "paragraph", "quote"}])
    embed_count = len([b for b in blocks if b.get("type") == "embed"])
    image_count = len([b for b in blocks if b.get("type") == "image"])
    print(f"[NEWS v92] Blocchi news estratti: total={len(blocks)} text={text_count} images={image_count} embeds={embed_count} chars={text_chars}", flush=True)
    if text_chars < int(os.getenv("V92_MIN_NEWS_SOURCE_CHARS", "650")):
        raise RuntimeError(f"News block extraction too short for safe publication: chars={text_chars} url={source_url}")


def protected_news_event_rules(source_title: str, blocks: List[Dict[str, str]]) -> str:
    blob = normalize_text(source_title + " " + " ".join(str(b.get("text") or b.get("url") or "") for b in blocks))
    rules: List[str] = []
    if "clash in italy" in blob:
        rules.append("- Nome evento protetto: scrivi sempre e solo 'Clash in Italy'. Non trasformarlo mai in 'Clash at the Castle' o varianti simili.")
    if "clash at the castle" in blob:
        rules.append("- Nome evento protetto: mantieni esattamente 'Clash at the Castle' solo se presente nella fonte.")
    if "all in" in blob:
        rules.append("- Nome evento protetto: 'All In' resta 'All In'.")
    if "double or nothing" in blob:
        rules.append("- Nome evento protetto: 'Double or Nothing' resta 'Double or Nothing'.")
    if "forbidden door" in blob:
        rules.append("- Nome evento protetto: 'Forbidden Door' resta 'Forbidden Door'.")
    return "\n".join(rules)


def translate_news_blocks(source_title: str, blocks: List[Dict[str, str]], source: str) -> Tuple[str, Dict[int, str], str]:
    items = news_text_blocks(blocks)
    if not items:
        raise RuntimeError("Nessun blocco testuale news da tradurre")
    prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Devi adattare in italiano i blocchi di una news mantenendo la struttura originale.

Regole obbligatorie:
- NON riassumere.
- NON comprimere più blocchi in uno solo.
- Restituisci lo stesso numero di item ricevuti.
- Conserva l'indice i di ogni item.
- Traduci ogni blocco separatamente.
- Mantieni fatti, nomi, date, show, titoli e citazioni.
- Non inventare informazioni non presenti nella fonte.
- Match resta sempre "match", non partita/incontro/gara/gioco.
- Per heading usa solo testo tradotto, senza tag HTML.
- Per paragraph/quote usa testo italiano naturale, senza markdown.
- Le quote restano quote: non trasformarle in paragrafo narrativo.
- Non citare la fonte nel corpo: la fonte viene aggiunta automaticamente dal sistema.
- Titolo italiano: naturale, giornalistico, non clickbait, massimo 95 caratteri.
{protected_news_event_rules(source_title, blocks)}

Rispondi SOLO con JSON valido:
{{"title":"titolo italiano","items":[{{"i":0,"text":"..."}}]}}

Fonte: {source_label(source)}
Titolo originale: {source_title}

BLOCCHI JSON:
{json.dumps(items, ensure_ascii=False)}
""".strip()
    raw, model = gemini_generate(prompt, purpose="news_translate_blocks", ledger_context={"source_url": url, "url": url, "title": source_title, "candidate_id": url})
    data = extract_json(raw)
    title = clean_text(str(data.get("title") or source_title))[:120]
    arr = data.get("items") or []
    translated: Dict[int, str] = {}
    for item in arr:
        try:
            idx = int(item.get("i"))
            txt = clean_text(str(item.get("text") or ""))
            if txt:
                translated[idx] = txt
        except Exception:
            continue
    expected = {int(item["i"]) for item in items}
    missing = expected.difference(translated)
    if len(missing) > max(2, int(len(expected) * 0.12)):
        raise RuntimeError(f"Traduzione news a blocchi incompleta: mancanti={sorted(list(missing))[:20]} model={model}")
    source_blob = normalize_text(source_title + " " + " ".join(str(b.get("text") or "") for b in blocks))
    out_blob = normalize_text(title + " " + " ".join(translated.values()))
    if "clash in italy" in source_blob and ("clash at the castle" in out_blob or "clash in the castle" in out_blob):
        raise RuntimeError("Factual guardrail: Clash in Italy trasformato in Clash at the Castle")
    return title, translated, model


def normalize_news_embed_url(url: str) -> str:
    try:
        from modules import report_workshop_v92 as report_engine
        return report_engine.normalize_social_url(url)
    except Exception:
        return re.sub(r"^https?://x\.com/", "https://twitter.com/", (url or "").strip(), flags=re.I)


def render_news_blocks(blocks: List[Dict[str, str]], translated: Dict[int, str]) -> str:
    parts: List[str] = []
    for idx, block in enumerate(blocks):
        btype = block.get("type")
        if btype == "heading":
            level = block.get("level") or "h2"
            if level not in {"h2", "h3"}:
                level = "h2"
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            if txt:
                parts.append(f"<{level}>{txt}</{level}>")
        elif btype == "paragraph":
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            if txt:
                parts.append(f"<p>{txt}</p>")
        elif btype == "quote":
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            if txt:
                parts.append(f"<blockquote><p>{txt}</p></blockquote>")
        elif btype == "image":
            media_id, src = upload_media(block.get("src"))
            if src:
                alt = html_lib.escape(block.get("alt") or "")
                parts.append(f'<figure class="wp-block-image owtv-inline-image"><img src="{html_lib.escape(src)}" alt="{alt}" /></figure>')
        elif btype == "embed":
            url = normalize_news_embed_url(block.get("url", ""))
            if url:
                parts.append(f"\n\n{html_lib.escape(url)}\n\n")
    html = "\n".join(parts)
    # Reuse cleanup helpers when previous patches have installed them.
    for fn_name in ["cleanup_news_quotes", "strip_internal_placeholders"]:
        fn = globals().get(fn_name)
        if callable(fn):
            html = fn(html)
    return html


def run_news_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:
    print(f"[NEWS v92] Avvio workshop news BLOCK: {job.get('news_key')} url={job.get('source_url')}", flush=True)
    from modules import report_workshop_v92 as report_engine
    from modules.simone_report_integrity import cleanup_blocks
    blocks, _html, featured_image = report_engine.scrape_article(str(job["source_url"]))
    blocks, cleanup_diagnostics = cleanup_blocks(blocks, str(job.get("source") or ""))
    if cleanup_diagnostics["author_bio_blocks_removed"]:
        print(f"[NEWS CLEAN v95.13.1] author_bio_blocks_removed={cleanup_diagnostics['author_bio_blocks_removed']}", flush=True)
    validate_news_blocks_quality(blocks, str(job.get("source_url") or ""))
    title, translated, model = translate_news_blocks(str(job.get("source_title") or ""), blocks, str(job.get("source") or ""))
    body_html = render_news_blocks(blocks, translated)
    print(f"[NEWS v92] Traduzione news blocchi completata: modello={model} title={title}", flush=True)
    if not body_html or len(clean_text(re.sub(r"<[^>]+>", " ", body_html))) < 300:
        raise RuntimeError("Body HTML news troppo corto dopo render a blocchi")
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    (review_dir / f"news_{slug}.blocks.json").write_text(json.dumps({
        "job": job,
        "blocks": blocks[:120],
        "translated_indexes": sorted(translated.keys()),
        "featured_image": featured_image,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (review_dir / f"news_{slug}.prepublish.html").write_text(body_html, encoding="utf-8")
    post_id, post_json = publish_news(job, title, body_html, featured_image)
    (published_dir / f"news_{slug}.html").write_text(body_html, encoding="utf-8")
    return post_id, post_json
