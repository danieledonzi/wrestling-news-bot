from __future__ import annotations

import base64
import html
import json
import os
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.gemini_ledger import record_gemini_event
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

MENZO_DECISIONS_FILE = NEWSROOM_STATE_DIR / "menzo_decisions_latest.json"
BOB_ARTICLES_FILE = NEWSROOM_STATE_DIR / "bob_articles_latest.json"
SIMONE_REPORT_STATUS_FILE = NEWSROOM_STATE_DIR / "simone_report_publish_latest.json"
ARTIFACT_BOB_FILE = ARTIFACT_DIR / "bob_articles.json"

BOB_VERSION = "v94_13_2_preserve_valid_x_status_embeds"
REQUEST_TIMEOUT = int(os.getenv("V93_BOB_REQUEST_TIMEOUT", "18"))
MAX_ARTICLES_PER_RUN = int(os.getenv("V93_BOB_MAX_ARTICLES_PER_RUN", "5"))
MAX_ARTICLES_WITH_REPORT = int(os.getenv("V93_BOB_MAX_ARTICLES_WITH_REPORT", "4"))
POST_SHOW_MAX_ARTICLES = int(os.getenv("V93_BOB_POST_SHOW_MAX_ARTICLES", "6"))
AUDIT_CHARS = int(os.getenv("V93_BOB_AUDIT_CHARS", "24000"))
DEFAULT_BOB_MODEL_CHAIN = "gemini-3.1-flash-lite,gemini-3.5-flash,gemini-2.5-flash-lite,gemini-2.5-flash"
BOB_TITLE_CHAIN_MODE = "same_as_body_translation"
MODEL_CHAIN = [
    m.strip()
    for m in os.getenv("BOB_GEMINI_MODEL_CHAIN", os.getenv("GEMINI_MODEL_CHAIN", DEFAULT_BOB_MODEL_CHAIN)).split(",")
    if m.strip()
]

ARTICLE_SELECTORS = ["article", "main article", ".article-body", ".post-content", ".entry-content", ".content", "main"]
TRANSLATABLE_TYPES = {"text", "heading", "quote"}
EMBED_DOMAINS = ["x.com", "twitter.com", "instagram.com", "youtube.com", "youtube-nocookie.com", "youtu.be", "tiktok.com", "threads.net", "facebook.com", "bsky.app"]

BIO_PATTERNS = [
    re.compile(r"\babout\s+the\s+author\b", re.I),
    re.compile(r"\bfounder\s+of\s+ringside\s+news\b", re.I),
    re.compile(r"\bfelix\s+upton\b.*\bringside\s+news\b", re.I),
    re.compile(r"\bsteve\s+carrier\b.*\bringside\s+news\b", re.I),
    re.compile(r"\bfollow\s+.+\s+on\s+(twitter|x|instagram|facebook|bluesky)\b", re.I),
    re.compile(r"\bhas\s+(over\s+)?\d+\s+years\s+of\s+experience\b", re.I),
    re.compile(r"\bhas\s+been\s+(reporting\s+on|covering)\s+(pro\s+)?wrestling\b", re.I),
    re.compile(r"\bhis\s+(stories|work)\s+(have\s+been\s+featured|at|on)\b", re.I),
    re.compile(r"\bher\s+(stories|work)\s+(have\s+been\s+featured|at|on)\b", re.I),
    re.compile(r"\b(tmz|forbes|bleacher\s+report)\b.*\b(ringside\s+news|featured)\b", re.I),
    re.compile(r"\bdelivering\s+trusted\s+news\s+and\s+backstage\s+updates\b", re.I),
    re.compile(r"\b(more|read more)\s+from\s+[A-Z][a-z]+", re.I),
    re.compile(r"\bthanks\s+to\s+.+\s+for\s+the\s+transcription\b", re.I),
    re.compile(r"\bplease\s+credit\b", re.I),
    re.compile(r"\bh/?t\s+to\b", re.I),
    re.compile(r"\bfor\s+the\s+transcription\b", re.I),
    re.compile(r"\bwe\s+at\s+wrestling\s+inc\.?\s+wish\b", re.I),
]
CTA_PATTERNS = [
    re.compile(r"\bconnect\s+with\s+us\s+on\s+(bluesky|twitter|x|facebook|instagram)\b", re.I),
    re.compile(r"\badd\s+as\s+a\s+preferred\s+source\s+on\s+google\b", re.I),
    re.compile(r"\bsound\s+off\s+in\s+the\s+comments\b", re.I),
    re.compile(r"\b(let\s+us\s+know|share\s+your\s+thoughts|please\s+share\s+your\s+thoughts)\b", re.I),
    re.compile(r"^\s*what\s+do\s+you\s+think\b", re.I),
    re.compile(r"\bso\s+it\s+remains\s+to\s+be\s+seen\b", re.I),
    re.compile(r"\bstay\s+tuned\b", re.I),
    re.compile(r"\bsubscribe\b|\bnewsletter\b|\bclick\s+here\b", re.I),
]
FOOTER_START_PATTERNS = [
    re.compile(r"\babout\s+the\s+author\b", re.I),
    re.compile(r"\bfounder\s+of\s+ringside\s+news\b", re.I),
    re.compile(r"\badd\s+as\s+a\s+preferred\s+source\s+on\s+google\b", re.I),
    re.compile(r"\bhas\s+(over\s+)?\d+\s+years\s+of\s+experience\b", re.I),
    re.compile(r"\bhas\s+been\s+(reporting\s+on|covering)\s+(pro\s+)?wrestling\b", re.I),
    re.compile(r"\bhis\s+(stories|work)\s+(have\s+been\s+featured|at|on)\b", re.I),
    re.compile(r"^\s*spotlight\b", re.I),
    re.compile(r"\bspotlight\s+(wwe|aew|nxt|tna|roh)?\s*(videos|news)?\b", re.I),
    re.compile(r"\brelated\s+(articles|posts|news)\b", re.I),
    re.compile(r"\bmore\s+(wwe|aew|nxt|tna|roh)\s+news\b", re.I),
]
SOURCE_INTRO_PATTERNS = [re.compile(r"^\s*according\s+to\s+.+?:\s*$", re.I), re.compile(r"^\s*per\s+.+?:\s*$", re.I)]
SOURCE_SELF_REFERENCE_SITE_RE = r"(?:ringside\s+news|wrestling\s*inc\.?|fightful|pwinsider|f4wonline|wrestling\s+observer|sescoops|ewrestlingnews|411mania|bodyslam\.net)"
SOURCE_SELF_REFERENCE_PATTERNS = [
    re.compile(rf"\b{SOURCE_SELF_REFERENCE_SITE_RE}\s+(?:will\s+)?(?:continue|continuerà|continueranno)\s+(?:(?:to|a)\s+)?(?:monitor|follow|cover|provide|seguire|monitorare|fornire)\b", re.I),
    re.compile(rf"\bstay\s+tuned\s+(?:to\s+)?{SOURCE_SELF_REFERENCE_SITE_RE}\b", re.I),
    re.compile(rf"\bwe\s+at\s+{SOURCE_SELF_REFERENCE_SITE_RE}\b", re.I),
    re.compile(rf"\b{SOURCE_SELF_REFERENCE_SITE_RE}\s+(?:will\s+)?bring\s+you\s+(?:more\s+)?updates\b", re.I),
]

def is_source_self_reference_text(text: str) -> bool:
    cleaned = clean_text(text)
    if not cleaned:
        return False
    return any(pattern.search(cleaned) for pattern in SOURCE_SELF_REFERENCE_PATTERNS)
QUOTE_RE = re.compile(r"[“\"]([^”\"]{60,})[”\"]")
EMBED_URL_RE = re.compile(r"https?://(?:www\.)?(?:x\.com|twitter\.com|instagram\.com|youtube\.com|youtube-nocookie\.com|youtu\.be|tiktok\.com|threads\.net|facebook\.com|bsky\.app)/[^\s\"'<>\\]+", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", value).strip()


def text_key(value: str) -> str:
    value = clean_text(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def absolute_url(base: str, value: str) -> str:
    return urljoin(base, value or "").strip()


def fetch_html(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36", "Accept-Language": "en-US,en;q=0.9,it;q=0.8"}
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def image_signature(url: str) -> str:
    parsed = urlparse(url or "")
    name = parsed.path.lower().replace("/wp-content/smush-avif/", "/wp-content/uploads/").rsplit("/", 1)[-1]
    name = re.sub(r"\.(avif|webp|jpg|jpeg|png)$", "", name)
    return re.sub(r"^l-", "", name)


def same_image(a: str, b: str) -> bool:
    if not a or not b:
        return False
    pa = urlparse(a)
    pb = urlparse(b)
    if (pa.netloc.lower(), pa.path.rstrip("/")) == (pb.netloc.lower(), pb.path.rstrip("/")):
        return True
    return bool(image_signature(a) and image_signature(a) == image_signature(b))


def extract_meta(soup: BeautifulSoup, url: str) -> dict[str, str]:
    def meta(prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return clean_text(tag.get("content", "")) if tag else ""
    title = meta("og:title") or (clean_text(soup.title.get_text(" ")) if soup.title else "")
    image = meta("og:image")
    return {"source_title": title, "description": meta("og:description") or meta("description"), "featured_image": absolute_url(url, image) if image else ""}


def choose_article_root(soup: BeautifulSoup) -> Tag:
    for selector in ARTICLE_SELECTORS:
        found = soup.select_one(selector)
        if found and len(clean_text(found.get_text(" "))) > 500:
            return found
    return soup.body or soup


def node_classes(node: Tag) -> str:
    vals: list[str] = []
    for attr in ["class", "id", "aria-label", "role"]:
        raw = node.get(attr, "")
        vals.extend(raw if isinstance(raw, list) else [str(raw)])
    return " ".join(str(v) for v in vals).lower()


def canonical_embed_url(url: str) -> str:
    url = html.unescape((url or "").replace("\\/", "/").strip())
    url = url.replace("https://twitter.com/", "https://x.com/").replace("http://twitter.com/", "https://x.com/")
    if "x.com/" in url or "twitter.com/" in url:
        url = re.sub(r"\?.*$", "", url)
    return url.rstrip("/")



def is_valid_x_status_url(url: str) -> bool:
    url = canonical_embed_url(url)
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path
    if host not in {"x.com", "twitter.com"}:
        return False
    if "intent/tweet" in url.lower() or "/intent/" in path.lower():
        return False
    return bool(re.fullmatch(r"/[^/?#]+/status/\d+", path.rstrip("/")))

def is_valid_editorial_embed_url(url: str) -> bool:
    url = canonical_embed_url(url)
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.lower()
    query = parsed.query.lower()
    if not host or not path:
        return False
    if any(bad in url.lower() for bad in ["intent/tweet", "sharer.php", "share?", "/profile.php", "addthis", "mailto:"]):
        return False
    if host in {"x.com", "twitter.com"}:
        return is_valid_x_status_url(url)
    if host == "bsky.app":
        return "/post/" in path
    if host == "instagram.com":
        return path.startswith(("/p/", "/reel/", "/tv/"))
    if host in {"youtube.com", "youtube-nocookie.com"}:
        return path.startswith(("/watch", "/embed/", "/shorts/")) and ("v=" in query or path.startswith(("/embed/", "/shorts/")))
    if host == "youtu.be":
        return len(path.strip("/")) > 4
    if host == "tiktok.com":
        return "/video/" in path
    if host == "threads.net":
        return "/post/" in path or "/t/" in path
    if host == "facebook.com":
        return any(token in path for token in ["/posts/", "/videos/", "/watch/"])
    return False


def is_cta_text(text: str) -> bool:
    return any(p.search(text or "") for p in CTA_PATTERNS)


def is_footer_start_text(text: str) -> bool:
    return any(p.search(text or "") for p in FOOTER_START_PATTERNS)


def is_bio_or_footer_text(text: str) -> bool:
    text = clean_text(text)
    if not text or len(text) < 20:
        return True
    return is_cta_text(text) or any(p.search(text) for p in BIO_PATTERNS)


def is_probable_long_quote(text: str) -> bool:
    text = clean_text(text)
    return len(text) >= 90 and (text.startswith(("\"", "“", "'")) or bool(QUOTE_RE.search(text)))


def decode_possible_rsn_lazy_embed_html(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def pick_srcset_url(value: str) -> str:
    raw = html.unescape(str(value or "").replace("\\/", "/")).strip()
    if not raw:
        return ""
    best_url = ""
    best_width = -1
    for part in raw.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0].strip()
        width = 0
        if len(bits) > 1:
            m = re.search(r"(\d+)w", bits[1])
            if m:
                width = int(m.group(1))
        if width >= best_width:
            best_url = url
            best_width = width
    return best_url


def normalize_ringside_image_url(url: str) -> str:
    u = html.unescape(str(url or "").replace("\\/", "/")).strip()
    if not u or u.startswith("data:"):
        return ""
    u = re.sub(r"\?.*$", "", u)
    u = u.replace("/wp-content/smush-avif/", "/wp-content/uploads/")
    if u.lower().endswith(".avif"):
        u = u[:-5]
    return u


def image_url_from_node(node: Tag, base_url: str) -> str:
    candidates: list[str] = []
    for attr in ["src", "data-src", "data-lazy-src", "data-original", "data-orig-src"]:
        value = node.get(attr)
        if value:
            candidates.append(str(value))
    for attr in ["srcset", "data-srcset", "data-lazy-srcset", "data-original-srcset"]:
        value = node.get(attr)
        if value:
            picked = pick_srcset_url(str(value))
            if picked:
                candidates.append(picked)
    for raw in candidates:
        url = normalize_ringside_image_url(absolute_url(base_url, raw))
        if url:
            return url
    return ""


def extract_embed_urls_from_text(raw: str, base_url: str) -> list[str]:
    text = html.unescape((raw or "").replace("\\/", "/"))
    out: list[str] = []
    seen: set[str] = set()
    for match in EMBED_URL_RE.findall(text):
        url = canonical_embed_url(absolute_url(base_url, match))
        if is_valid_editorial_embed_url(url) and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def extract_embed_url(node: Tag, base_url: str) -> str:
    candidates: list[str] = []
    for attr in ["src", "href", "cite", "data-url", "data-href", "data-src", "data-lazy-src", "data-embed-url", "data-permalink", "data-instgrm-permalink"]:
        value = node.get(attr)
        if value:
            candidates.append(str(value))
    lazy_html = decode_possible_rsn_lazy_embed_html(str(node.get("data-rsn-html") or ""))
    if lazy_html:
        candidates.extend(extract_embed_urls_from_text(lazy_html, base_url))
        try:
            lazy_soup = BeautifulSoup(lazy_html, "html.parser")
            for tag in lazy_soup.find_all(True):
                for attr in ["href", "src", "data-instgrm-permalink", "data-permalink"]:
                    value = tag.get(attr)
                    if value:
                        candidates.append(str(value))
        except Exception:
            pass
    for link in node.find_all("a", href=True):
        candidates.append(str(link.get("href")))
    candidates.extend(extract_embed_urls_from_text(str(node), base_url))
    for raw in candidates:
        url = canonical_embed_url(absolute_url(base_url, raw))
        if is_valid_editorial_embed_url(url):
            return url
    return ""


def table_rows(node: Tag) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in node.find_all("tr"):
        cells = [clean_text(cell.get_text(" ")) for cell in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    return rows


def render_table(rows: list[list[str]], translations: dict[str, str], table_id: str) -> str:
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    out = ["<table class=\"owtv-data-table\">"]
    for ridx, row in enumerate(rows):
        tag = "th" if ridx == 0 else "td"
        row = (row + [""] * max_cols)[:max_cols]
        out.append("<tr>" + "".join(f"<{tag}>{html.escape(translations.get(f'{table_id}_r{ridx}_c{cidx}', value))}</{tag}>" for cidx, value in enumerate(row)) + "</tr>")
    out.append("</table>")
    return "".join(out)


def table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    rows = [(r + [""] * max_cols)[:max_cols] for r in rows]
    return "\n".join([" | ".join(rows[0]), " | ".join(["---"] * max_cols)] + [" | ".join(r) for r in rows[1:]])


def element_from_node(node: Tag, base_url: str) -> dict[str, Any] | None:
    name = (node.name or "").lower()
    classes = node_classes(node)
    if any(token in classes for token in ["share", "social-share", "gb-social", "follow", "newsletter"]):
        return None
    embed_url = extract_embed_url(node, base_url)
    if embed_url and (name in {"iframe", "blockquote", "figure", "div"} or any(x in classes for x in ["twitter", "tweet", "instagram", "embed", "youtube", "tiktok", "video"])):
        return {"type": "embed", "url": embed_url, "source_tag": name}
    if name in {"p", "li"}:
        text = clean_text(node.get_text(" "))
        if is_bio_or_footer_text(text) or is_source_self_reference_text(text) or any(p.search(text) for p in SOURCE_INTRO_PATTERNS):
            return None
        # v93.26: do not infer quote blocks from quotation marks in normal paragraphs.
        # Only original source <blockquote> nodes are rendered as blockquotes.
        return {"type": "text", "text": text}
    if name in {"h2", "h3", "h4"}:
        text = clean_text(node.get_text(" "))
        if not text or is_bio_or_footer_text(text) or is_source_self_reference_text(text) or is_footer_start_text(text):
            return None
        return {"type": "heading", "level": int(name[1]), "text": text}
    if name == "blockquote":
        text = clean_text(node.get_text(" "))
        if len(text) < 8 or is_cta_text(text) or is_source_self_reference_text(text):
            return None
        return {"type": "quote", "text": text, "source_tag": "blockquote"}
    if name == "table":
        rows = table_rows(node)
        if rows:
            return {"type": "table", "rows": rows, "markdown": table_to_markdown(rows)}
    if name == "img":
        src = image_url_from_node(node, base_url)
        if not src:
            return None
        return {"type": "image", "url": src, "alt": clean_text(node.get("alt", ""))}
    return None


def sanitize_elements(elements: list[dict[str, Any]], featured_image: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cleaned: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    first_image_seen = False
    seen_embeds: set[str] = set()
    for idx, item in enumerate(elements, start=1):
        kind = item.get("type")
        text = clean_text(item.get("text", "")) if kind in {"text", "heading", "quote"} else ""
        reason = ""
        stop_after = False
        if kind == "embed":
            url = canonical_embed_url(str(item.get("url") or ""))
            item["url"] = url
            if not url or url in seen_embeds:
                reason = "duplicate_or_empty_embed"
            elif not is_valid_editorial_embed_url(url):
                reason = "non_editorial_embed_or_social_bar"
            else:
                seen_embeds.add(url)
        elif text and is_footer_start_text(text):
            reason = "footer_start"
            stop_after = True
        elif text and any(p.search(text) for p in BIO_PATTERNS):
            reason = "bio_or_credit"
            stop_after = True
        elif text and is_cta_text(text):
            reason = "cta_or_comment_bait"
        elif kind == "image" and not first_image_seen:
            first_image_seen = True
            if same_image(item.get("url", ""), featured_image):
                reason = "duplicate_featured_image"
        elif kind == "image" and same_image(item.get("url", ""), featured_image) and cleaned:
            reason = "duplicate_featured_image"
        if reason:
            removed.append({"index": idx, "reason": reason, "item": item})
            if stop_after:
                break
            continue
        cleaned.append(item)
    return cleaned, removed



def recover_valid_x_status_embeds(raw_elements: list[dict[str, Any]], clean_elements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    recovered: list[dict[str, Any]] = []
    recovered_debug: list[dict[str, Any]] = []
    clean_by_identity = {id(item) for item in clean_elements}
    clean_x_urls = {canonical_embed_url(str(item.get("url") or "")) for item in clean_elements if item.get("type") == "embed" and is_valid_x_status_url(str(item.get("url") or ""))}
    emitted_x_urls: set[str] = set()
    for idx, item in enumerate(raw_elements, start=1):
        if id(item) in clean_by_identity:
            recovered.append(item)
            if item.get("type") == "embed":
                emitted_x_urls.add(canonical_embed_url(str(item.get("url") or "")))
            continue
        if item.get("type") != "embed":
            continue
        url = canonical_embed_url(str(item.get("url") or ""))
        if not is_valid_x_status_url(url) or url in clean_x_urls or url in emitted_x_urls:
            continue
        recovered_item = dict(item)
        recovered_item["url"] = url
        recovered.append(recovered_item)
        emitted_x_urls.add(url)
        recovered_debug.append({"raw_index": idx, "reason": "recovered_valid_x_status_embed", "item": recovered_item})
    return recovered, recovered_debug

def extract_elements(source_url: str, raw_html: str) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    diagnostics: dict[str, Any] = {"dom_noise_reduction_enabled": False, "stage": "parse_html", "global_embed_recovery_enabled": False}
    soup = BeautifulSoup(raw_html, "html.parser")
    meta = extract_meta(soup, source_url)
    root = choose_article_root(soup)
    raw_elements: list[dict[str, Any]] = []
    removed_by_node: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    scan_nodes = list(root.find_all(["h2", "h3", "h4", "p", "li", "blockquote", "table", "img", "iframe", "figure", "div"], recursive=True)) if root else []
    for node_idx, node in enumerate(scan_nodes, start=1):
        try:
            name = (node.name or "").lower()
            if name not in {"blockquote", "table", "figure", "div", "iframe"} and node.find_parent(["blockquote", "table", "figure"]):
                continue
            classes = node_classes(node)
            if name not in {"table", "blockquote", "iframe", "figure", "div"} and any(t in classes for t in ["share", "social", "newsletter", "related", "author-bio", "authorbox", "recommended", "spotlight"]):
                removed_by_node.append({"node_index": node_idx, "reason": "node_class_noise", "node_name": node.name, "classes": classes[:500], "text_preview": clean_text(node.get_text(" "))[:500]})
                continue
            item = element_from_node(node, source_url)
            if not item:
                continue
            if item["type"] in {"text", "heading", "quote"}:
                key = text_key(item.get("text", ""))
                if not key or key in seen_text:
                    continue
                seen_text.add(key)
            if item["type"] == "table":
                key = text_key(item.get("markdown", ""))
                if not key or key in seen_text:
                    continue
                seen_text.add(key)
            raw_elements.append(item)
        except Exception as exc:
            removed_by_node.append({"node_index": node_idx, "reason": "node_exception", "node_name": getattr(node, "name", ""), "error": str(exc)[:1000]})
    clean_elements, removed_by_sanitize = sanitize_elements(raw_elements, meta.get("featured_image", ""))
    clean_elements, recovered_x_embeds = recover_valid_x_status_embeds(raw_elements, clean_elements)
    diagnostics.update({
        "root_name": getattr(root, "name", ""),
        "root_text_chars": len(clean_text(root.get_text(" "))) if root else 0,
        "candidate_node_count": len(scan_nodes),
        "raw_element_count": len(raw_elements),
        "clean_element_count": len(clean_elements),
        "removed_by_node_count": len(removed_by_node),
        "removed_by_sanitize_count": len(removed_by_sanitize),
        "recovered_valid_x_status_embed_count": len(recovered_x_embeds),
        "table_count": sum(1 for e in clean_elements if e.get("type") == "table"),
        "quote_count": sum(1 for e in clean_elements if e.get("type") == "quote"),
        "embed_count": sum(1 for e in clean_elements if e.get("type") == "embed"),
        "stage": "complete",
    })
    return meta, raw_elements, clean_elements, removed_by_node + removed_by_sanitize + recovered_x_embeds, diagnostics


def build_translation_units(elements: list[dict[str, Any]]) -> list[dict[str, str]]:
    units: list[dict[str, str]] = []
    for idx, item in enumerate(elements, start=1):
        item["block_id"] = f"b{idx}"
        kind = item.get("type")
        if kind in TRANSLATABLE_TYPES:
            units.append({"id": item["block_id"], "type": str(kind), "text": str(item.get("text") or "")})
        elif kind == "table":
            rows = item.get("rows") if isinstance(item.get("rows"), list) else []
            for ridx, row in enumerate(rows):
                if isinstance(row, list):
                    for cidx, cell in enumerate(row):
                        if clean_text(str(cell)):
                            units.append({"id": f"{item['block_id']}_r{ridx}_c{cidx}", "type": "table_cell", "text": str(cell)})
    return units


def call_gemini(prompt: str, *, ledger_context: dict[str, Any] | None = None) -> tuple[str, str, list[str]]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    attempts: list[str] = []
    if not api_key:
        return "", "missing_api_key", attempts
    last_error = ""
    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=api_key)
        for model in MODEL_CHAIN:
            attempts.append(model)
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                text = getattr(response, "text", "") or ""
                record_gemini_event(agent="Bob", phase="translate_article", model=model, status="called", reason="generate_translate_article", result="text" if text.strip() else "empty_response", **(ledger_context or {}))
                if text.strip():
                    return text.strip(), model, attempts
            except Exception as exc:
                last_error = f"{model}: {exc}"
                record_gemini_event(agent="Bob", phase="translate_article", model=model, status="failed", reason="generate_translate_article", result=str(exc)[:500], **(ledger_context or {}))
    except Exception as exc:
        last_error = f"genai_import_or_client_error: {exc}"
    return "", last_error or "empty_response", attempts


def build_translation_prompt(item: dict[str, Any], meta: dict[str, str], units: list[dict[str, str]]) -> str:
    return f"""Sei Bob, traduttore di OpenWrestlingTV.

Traduci in italiano naturale e giornalistico SOLO i blocchi testuali indicati. Non devi ricostruire l'articolo completo: la sequenza HTML sara' ricostruita dal sistema preservando immagini, embed e tabelle.

REGOLE
- Non riassumere e non aggiungere informazioni.
- Bob non deve cercare media con Gemini: immagini, YouTube, Instagram/Reel, X/Twitter e altri embed sono estratti dal DOM prima della traduzione e vanno preservati nella sequenza originale.
- Conserva fedelmente il significato di ogni blocco.
- Le citazioni vanno tradotte integralmente.
- Rimuovi qualunque frase autoreferenziale della fonte originale che prometta monitoraggio, copertura futura, aggiornamenti o inviti a seguire Ringside News, WrestlingInc, Fightful o altri siti. Non tradurla.
- Mantieni nomi propri, promotion, show e termini wrestling quando appropriato.
- Usa terminologia wrestling italiana corretta e naturale.
- Rispondi SOLO in JSON valido.

Forma richiesta:
{{
  "title_it": "titolo italiano breve e non clickbait",
  "excerpt_it": "excerpt italiano breve",
  "translations": {{"b1": "traduzione blocco 1"}},
  "notes": []
}}

Metadati fonte:
URL: {item.get('url') or item.get('source_url')}
Titolo feed: {item.get('title')}
Titolo pagina: {meta.get('source_title')}
Descrizione: {meta.get('description')}
Categoria suggerita: {item.get('category_hint')}

BLOCCHI DA TRADURRE:
{json.dumps(units, ensure_ascii=False, indent=2)}
"""


def parse_bob_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.I).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"title_it": "", "excerpt_it": "", "translations": {}, "notes": ["bob_json_parse_failed"], "raw": raw[:4000]}


def render_body(elements: list[dict[str, Any]], translations: dict[str, str]) -> str:
    out: list[str] = []
    for item in elements:
        kind = item.get("type")
        block_id = str(item.get("block_id") or "")
        if kind == "heading":
            level = int(item.get("level") or 2)
            out.append(f"<h{level}>{html.escape(translations.get(block_id, str(item.get('text') or '')))}</h{level}>")
        elif kind == "text":
            out.append(f"<p>{html.escape(translations.get(block_id, str(item.get('text') or '')))}</p>")
        elif kind == "quote":
            out.append(f"<blockquote>{html.escape(translations.get(block_id, str(item.get('text') or '')))}</blockquote>")
        elif kind == "table":
            rows = item.get("rows") if isinstance(item.get("rows"), list) else []
            out.append(render_table(rows, translations, block_id))
        elif kind == "image":
            out.append(f"<!--IMAGE:{item.get('url', '')}-->")
        elif kind == "embed":
            url = canonical_embed_url(str(item.get("url") or ""))
            if is_valid_editorial_embed_url(url):
                out.append("\n" + html.escape(url) + "\n")
    return "\n".join(x for x in out if x).strip()


def report_was_published_or_attempted() -> bool:
    data = load_json(SIMONE_REPORT_STATUS_FILE, {})
    if not isinstance(data, dict):
        return False
    handoff = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
    if int(handoff.get("published", 0) or 0) > 0:
        return True
    if int(handoff.get("already_published", 0) or 0) > 0:
        return True
    # If Simone had ready reports but WordPress was not ready, keep the next news batch slightly smaller.
    # This avoids overloading the first good run after a report window while keeping the report as the editorial anchor.
    if int(handoff.get("wp_not_ready", 0) or 0) > 0:
        return True
    return False


def is_post_show_candidate(item: dict[str, Any]) -> bool:
    blob = " ".join(str(item.get(k) or "") for k in ["title", "source_title", "category_hint", "article_type", "reason", "ai_editorial_reason", "event_key"]).lower()
    show_terms = ["raw", "smackdown", "nxt", "dynamite", "collision", "clash", "forbidden door", "summer blockbuster", "paris", "king of the ring", "queen of the ring"]
    factual_terms = ["result", "results", "wins", "defeats", "title match", "match confirmed", "match revealed", "added", "returns", "return", "injury", "infortun", "announced", "scheduled", "set for", "confermato", "rivelato", "vittoria", "titolo"]
    article_type = str(item.get("article_type") or "").lower()
    if article_type in {"event_outcome", "match_announcement", "injury_update", "hard_news"}:
        return True
    return any(t in blob for t in show_terms) and any(t in blob for t in factual_terms)


def dynamic_article_capacity(decision: dict[str, Any], selected: list[dict[str, Any]]) -> tuple[int, str]:
    if report_was_published_or_attempted():
        return max(0, MAX_ARTICLES_WITH_REPORT), "report_run"
    post_show_count = sum(1 for item in selected if isinstance(item, dict) and is_post_show_candidate(item))
    if post_show_count >= 3:
        return max(MAX_ARTICLES_PER_RUN, POST_SHOW_MAX_ARTICLES), "post_show_event_heavy"
    return MAX_ARTICLES_PER_RUN, "normal"


def report_was_published_or_attempted() -> bool:
    data = load_json(SIMONE_REPORT_STATUS_FILE, {})
    if not isinstance(data, dict):
        return False
    handoff = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
    if int(handoff.get("published", 0) or 0) > 0:
        return True
    if int(handoff.get("already_published", 0) or 0) > 0:
        return True
    # If Simone had ready reports but WordPress was not ready, keep the next news batch slightly smaller.
    # This avoids overloading the first good run after a report window while keeping the report as the editorial anchor.
    if int(handoff.get("wp_not_ready", 0) or 0) > 0:
        return True
    return False


def is_post_show_candidate(item: dict[str, Any]) -> bool:
    blob = " ".join(str(item.get(k) or "") for k in ["title", "source_title", "category_hint", "article_type", "reason", "ai_editorial_reason", "event_key"]).lower()
    show_terms = ["raw", "smackdown", "nxt", "dynamite", "collision", "clash", "forbidden door", "summer blockbuster", "paris", "king of the ring", "queen of the ring"]
    factual_terms = ["result", "results", "wins", "defeats", "title match", "match confirmed", "match revealed", "added", "returns", "return", "injury", "infortun", "announced", "scheduled", "set for", "confermato", "rivelato", "vittoria", "titolo"]
    article_type = str(item.get("article_type") or "").lower()
    if article_type in {"event_outcome", "match_announcement", "injury_update", "hard_news"}:
        return True
    return any(t in blob for t in show_terms) and any(t in blob for t in factual_terms)


def dynamic_article_capacity(decision: dict[str, Any], selected: list[dict[str, Any]]) -> tuple[int, str]:
    if report_was_published_or_attempted():
        return max(0, MAX_ARTICLES_WITH_REPORT), "report_run"
    post_show_count = sum(1 for item in selected if isinstance(item, dict) and is_post_show_candidate(item))
    if post_show_count >= 3:
        return max(MAX_ARTICLES_PER_RUN, POST_SHOW_MAX_ARTICLES), "post_show_event_heavy"
    return MAX_ARTICLES_PER_RUN, "normal"


def report_was_published_or_attempted() -> bool:
    data = load_json(SIMONE_REPORT_STATUS_FILE, {})
    if not isinstance(data, dict):
        return False
    handoff = data.get("handoff") if isinstance(data.get("handoff"), dict) else {}
    if int(handoff.get("published", 0) or 0) > 0:
        return True
    if int(handoff.get("already_published", 0) or 0) > 0:
        return True
    # If Simone had ready reports but WordPress was not ready, keep the next news batch slightly smaller.
    # This avoids overloading the first good run after a report window while keeping the report as the editorial anchor.
    if int(handoff.get("wp_not_ready", 0) or 0) > 0:
        return True
    return False


def is_post_show_candidate(item: dict[str, Any]) -> bool:
    blob = " ".join(str(item.get(k) or "") for k in ["title", "source_title", "category_hint", "article_type", "reason", "ai_editorial_reason", "event_key"]).lower()
    show_terms = ["raw", "smackdown", "nxt", "dynamite", "collision", "clash", "forbidden door", "summer blockbuster", "paris", "king of the ring", "queen of the ring"]
    factual_terms = ["result", "results", "wins", "defeats", "title match", "match confirmed", "match revealed", "added", "returns", "return", "injury", "infortun", "announced", "scheduled", "set for", "confermato", "rivelato", "vittoria", "titolo"]
    article_type = str(item.get("article_type") or "").lower()
    if article_type in {"event_outcome", "match_announcement", "injury_update", "hard_news"}:
        return True
    return any(t in blob for t in show_terms) and any(t in blob for t in factual_terms)


def dynamic_article_capacity(decision: dict[str, Any], selected: list[dict[str, Any]]) -> tuple[int, str]:
    if report_was_published_or_attempted():
        return max(0, MAX_ARTICLES_WITH_REPORT), "report_run"
    post_show_count = sum(1 for item in selected if isinstance(item, dict) and is_post_show_candidate(item))
    if post_show_count >= 3:
        return max(MAX_ARTICLES_PER_RUN, POST_SHOW_MAX_ARTICLES), "post_show_event_heavy"
    return MAX_ARTICLES_PER_RUN, "normal"


def article_package(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url") or item.get("source_url") or "")
    package: dict[str, Any] = {"source_url": url, "source": item.get("source"), "source_title": item.get("title"), "category_hint": item.get("category_hint"), "menzo_score": item.get("score"), "status": "error", "created_at": utc_now(), "diagnostic_stage": "start"}
    try:
        raw = fetch_html(url)
        package["fetched_html_chars"] = len(raw)
        package["source_html_contains_embed_hint"] = bool(re.search(r"twitter-tweet|x\.com/.+?/status|twitter\.com/.+?/status|instagram\.com/(p|reel)|youtube\.com/(watch|embed|shorts)|youtu\.be/|iframe|youtube-nocookie", raw, re.I))
        meta, raw_elements, elements, removed, extraction_diag = extract_elements(url, raw)
        units = build_translation_units(elements)
        package.update({
            "meta": meta,
            "extraction_diagnostics": extraction_diag,
            "raw_element_count": len(raw_elements),
            "clean_element_count": len(elements),
            "translation_unit_count": len(units),
            "removed_before_gemini": len(removed),
            "removed_elements_debug": removed[:30],
            "raw_elements_preview": raw_elements[:30],
            "elements": elements,
            "element_counts": {kind: sum(1 for e in elements if e.get("type") == kind) for kind in ["text", "heading", "quote", "table", "image", "embed"]},
        })
        if not elements or not units:
            package["status"] = "extraction_empty"
            package["diagnostic_stage"] = "extraction_empty"
            return package
        prompt = build_translation_prompt(item, meta, units)
        package["translation_prompt_preview"] = prompt[:AUDIT_CHARS]
        translated, model_or_error, attempts = call_gemini(prompt, ledger_context={"url": url, "title": item.get("title") or meta.get("source_title"), "candidate_id": item.get("candidate_id") or item.get("id") or item.get("semantic_id"), "source_id": item.get("source_id") or item.get("source")})
        package["translation_chain_attempted"] = attempts
        package["translation_model"] = model_or_error
        package["translation_used"] = bool(translated)
        if translated:
            package["translation_raw_response_preview"] = translated[:AUDIT_CHARS]
            data = parse_bob_json(translated)
            translations = data.get("translations") if isinstance(data.get("translations"), dict) else {}
            translations = {str(k): str(v) for k, v in translations.items()}
            package["title_it"] = clean_text(data.get("title_it") or meta.get("source_title") or item.get("title") or "")
            package["body_html"] = render_body(elements, translations)
            package["excerpt_it"] = clean_text(data.get("excerpt_it") or meta.get("description") or "")
            package["bob_notes"] = data.get("notes") if isinstance(data.get("notes"), list) else []
            package["translation_missing_units"] = [u["id"] for u in units if u["id"] not in translations]
            package["status"] = "ready_for_alfred"
            package["diagnostic_stage"] = "ready_for_alfred"
        else:
            fallback = {u["id"]: u["text"] for u in units}
            package["title_it"] = meta.get("source_title") or item.get("title") or ""
            package["body_html"] = render_body(elements, fallback)
            package["excerpt_it"] = meta.get("description", "")
            package["bob_notes"] = ["translation_unavailable", model_or_error]
            package["status"] = "extraction_ready_translation_pending"
            package["diagnostic_stage"] = "translation_pending"
    except Exception as exc:
        package["error"] = str(exc)[:1200]
        package["traceback_preview"] = traceback.format_exc()[-4000:]
        package["status"] = "error"
    return package


def run_bob(menzo_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = menzo_decision if isinstance(menzo_decision, dict) else load_json(MENZO_DECISIONS_FILE, {})
    selected = decision.get("selected", []) if isinstance(decision, dict) else []
    if not isinstance(selected, list):
        selected = []
    selected_total = len(selected)
    capacity, capacity_reason = dynamic_article_capacity(decision if isinstance(decision, dict) else {}, selected)
    selected = selected[:capacity]
    publishable_left_out_by_capacity = max(0, selected_total - len(selected))
    print(f"[BOB v93.39] Avvio traduzione a blocchi | selected={len(selected)}/{selected_total} capacity={capacity} reason={capacity_reason} left_out={publishable_left_out_by_capacity}", flush=True)
    articles = [article_package(item) for item in selected if isinstance(item, dict)]
    result = {
        "agent": "Bob",
        "version": BOB_VERSION,
        "generated_at": utc_now(),
        "mode": "block_translation_prudent_embed_cleanup",
        "policy": {
            "clean_before_gemini": True,
            "gemini_receives_only_text_units": True,
            "preserve_sequence_outside_gemini": True,
            "preserve_embeds_as_plain_url_lines": True,
            "filter_source_social_bars": True,
            "filter_author_bios_before_gemini": True,
            "filter_cta_before_gemini": True,
            "recover_embeds_from_raw_html": False,
            "embed_urls_require_post_or_video_shape": True,
            "preserve_quotes_as_blockquote": "source_blockquote_only",
            "preserve_tables_as_html_tables": True,
            "ordered_elements": ["text", "heading", "quote", "table", "image", "embed"],
            "model_chain": MODEL_CHAIN,
            "bob_title_chain_mode": BOB_TITLE_CHAIN_MODE,
            "max_articles_per_run": MAX_ARTICLES_PER_RUN,
            "max_articles_with_report": MAX_ARTICLES_WITH_REPORT,
            "post_show_max_articles": POST_SHOW_MAX_ARTICLES,
            "dynamic_article_capacity": True,
            "max_articles_with_report": MAX_ARTICLES_WITH_REPORT,
            "post_show_max_articles": POST_SHOW_MAX_ARTICLES,
            "dynamic_article_capacity": True,
            "max_articles_with_report": MAX_ARTICLES_WITH_REPORT,
            "post_show_max_articles": POST_SHOW_MAX_ARTICLES,
            "dynamic_article_capacity": True,
            "prompt_family": "v92_historical_natural_full_translation_blocks",
            "diagnostic_mode": True,
            "fallback_mode": False,
        },
        "input": {"menzo_version": decision.get("version") if isinstance(decision, dict) else None, "selected_count": selected_total, "selected_processed": len(selected), "capacity": capacity, "capacity_reason": capacity_reason},
        "articles": articles,
        "handoff": {
            "ready_for_alfred": sum(1 for a in articles if a.get("status") == "ready_for_alfred"),
            "translation_pending": sum(1 for a in articles if a.get("status") == "extraction_ready_translation_pending"),
            "errors": sum(1 for a in articles if a.get("status") == "error"),
            "extraction_empty": sum(1 for a in articles if a.get("status") == "extraction_empty"),
            "publishable_left_out_by_capacity": publishable_left_out_by_capacity,
        },
        "postprocess": {"capacity": capacity, "capacity_reason": capacity_reason, "selected_total_before_capacity": selected_total, "selected_processed": len(selected), "publishable_left_out_by_capacity": publishable_left_out_by_capacity},
    }
    write_json(ARTIFACT_BOB_FILE, result)
    write_json(BOB_ARTICLES_FILE, result)
    print("[BOB v93.12] Pacchetti pronti | ready={ready} pending={pending} empty={empty} errors={errors}".format(ready=result["handoff"]["ready_for_alfred"], pending=result["handoff"]["translation_pending"], empty=result["handoff"]["extraction_empty"], errors=result["handoff"]["errors"]), flush=True)
    return result


if __name__ == "__main__":
    out = run_bob()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
