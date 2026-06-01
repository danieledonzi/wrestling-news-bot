from __future__ import annotations

import html
import json
import os
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

MENZO_DECISIONS_FILE = NEWSROOM_STATE_DIR / "menzo_decisions_latest.json"
BOB_ARTICLES_FILE = NEWSROOM_STATE_DIR / "bob_articles_latest.json"
ARTIFACT_BOB_FILE = ARTIFACT_DIR / "bob_articles.json"

BOB_VERSION = "v93_10_block_translation_preserve_embeds"
REQUEST_TIMEOUT = int(os.getenv("V93_BOB_REQUEST_TIMEOUT", "18"))
MAX_ARTICLES_PER_RUN = int(os.getenv("V93_BOB_MAX_ARTICLES_PER_RUN", "3"))
AUDIT_CHARS = int(os.getenv("V93_BOB_AUDIT_CHARS", "24000"))
MODEL_CHAIN = [m.strip() for m in os.getenv(
    "GEMINI_MODEL_CHAIN",
    "gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash-lite,gemini-2.5-flash",
).split(",") if m.strip()]

ARTICLE_SELECTORS = ["article", "main article", ".article-body", ".post-content", ".entry-content", ".content", "main"]
TRANSLATABLE_TYPES = {"text", "heading", "quote"}

BIO_PATTERNS = [
    re.compile(r"\babout\s+the\s+author\b", re.I),
    re.compile(r"\bfollow\s+.+\s+on\s+(twitter|x|instagram|facebook|bluesky)\b", re.I),
    re.compile(r"\bhas\s+been\s+covering\s+(pro\s+)?wrestling\b", re.I),
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
    re.compile(r"\bsubscribe\b|\bnewsletter\b|\bclick\s+here\b", re.I),
]
FOOTER_START_PATTERNS = [
    re.compile(r"\badd\s+as\s+a\s+preferred\s+source\s+on\s+google\b", re.I),
    re.compile(r"\bhas\s+been\s+covering\s+(pro\s+)?wrestling\b", re.I),
    re.compile(r"^\s*spotlight\b", re.I),
    re.compile(r"\bspotlight\s+wwe\s+news\b", re.I),
    re.compile(r"\brelated\s+(articles|posts|news)\b", re.I),
    re.compile(r"\bmore\s+(wwe|aew|nxt|tna|roh)\s+news\b", re.I),
]
SOURCE_INTRO_PATTERNS = [re.compile(r"^\s*according\s+to\s+.+?:\s*$", re.I), re.compile(r"^\s*per\s+.+?:\s*$", re.I)]
SOCIAL_OR_NOISE_DOMAINS = ["bsky.app", "twitter.com", "x.com", "facebook.com", "instagram.com", "threads.net", "google.com/preferences/source", "news.google.com"]
EMBED_DOMAINS = ["x.com", "twitter.com", "instagram.com", "youtube.com", "youtu.be", "tiktok.com", "threads.net", "facebook.com", "bsky.app"]
QUOTE_RE = re.compile(r"[“\"]([^”\"]{60,})[”\"]")


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
    value = re.sub(r"\s+", " ", value).strip()
    return value


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
    path = parsed.path.lower().replace("/wp-content/smush-avif/", "/wp-content/uploads/")
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r"\.(avif|webp|jpg|jpeg|png)$", "", name)
    name = re.sub(r"\.(avif|webp)$", "", name)
    name = re.sub(r"^l-", "", name)
    return name


def same_image(a: str, b: str) -> bool:
    if not a or not b:
        return False
    pa = urlparse(a)
    pb = urlparse(b)
    if (pa.netloc.lower(), pa.path.rstrip("/")) == (pb.netloc.lower(), pb.path.rstrip("/")):
        return True
    sig_a = image_signature(a)
    sig_b = image_signature(b)
    return bool(sig_a and sig_b and sig_a == sig_b)


def extract_meta(soup: BeautifulSoup, url: str) -> dict[str, str]:
    def meta(prop: str) -> str:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        return clean_text(tag.get("content", "")) if tag else ""
    title = meta("og:title") or (clean_text(soup.title.get_text(" ")) if soup.title else "")
    description = meta("og:description") or meta("description")
    image = meta("og:image")
    if image:
        image = absolute_url(url, image)
    return {"source_title": title, "description": description, "featured_image": image}


def choose_article_root(soup: BeautifulSoup) -> Tag:
    for selector in ARTICLE_SELECTORS:
        found = soup.select_one(selector)
        if found and len(clean_text(found.get_text(" "))) > 500:
            return found
    return soup.body or soup


def is_embed_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(domain in lowered for domain in EMBED_DOMAINS)


def canonical_embed_url(url: str) -> str:
    url = html.unescape((url or "").strip())
    url = re.sub(r"\?.*$", "", url) if "x.com/" in url or "twitter.com/" in url else url
    url = url.replace("https://twitter.com/", "https://x.com/").replace("http://twitter.com/", "https://x.com/")
    return url


def is_social_or_noise_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(domain in lowered for domain in SOCIAL_OR_NOISE_DOMAINS)


def is_cta_text(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in CTA_PATTERNS)


def is_footer_start_text(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in FOOTER_START_PATTERNS)


def is_bio_or_footer_text(text: str) -> bool:
    if not text or len(text) < 20:
        return True
    if is_cta_text(text):
        return True
    return any(pattern.search(text) for pattern in BIO_PATTERNS)


def node_classes(node: Tag) -> str:
    values: list[str] = []
    for attr in ["class", "id", "aria-label", "role"]:
        raw = node.get(attr, "")
        if isinstance(raw, list):
            values.extend(str(x) for x in raw)
        else:
            values.append(str(raw))
    return " ".join(values).lower()


def is_probable_long_quote(text: str) -> bool:
    text = clean_text(text)
    if len(text) < 90:
        return False
    if text.startswith(("\"", "“", "'")):
        return True
    return bool(QUOTE_RE.search(text))


def extract_embed_url(node: Tag, base_url: str) -> str:
    candidates: list[str] = []
    for attr in ["src", "href", "cite", "data-url", "data-href", "data-src", "data-embed-url", "data-permalink"]:
        value = node.get(attr)
        if value:
            candidates.append(str(value))
    for link in node.find_all("a", href=True):
        candidates.append(str(link.get("href")))
    text = str(node)
    candidates.extend(re.findall(r"https?://(?:www\.)?(?:x\.com|twitter\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com|threads\.net|facebook\.com|bsky\.app)/[^\s\"'<>]+", text, flags=re.I))
    for raw in candidates:
        url = canonical_embed_url(absolute_url(base_url, raw))
        if is_embed_url(url):
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
        cells = []
        for cidx, value in enumerate(row):
            unit_id = f"{table_id}_r{ridx}_c{cidx}"
            cells.append(f"<{tag}>{html.escape(translations.get(unit_id, value))}</{tag}>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


def table_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    rows = [(r + [""] * max_cols)[:max_cols] for r in rows]
    lines = [" | ".join(rows[0]), " | ".join(["---"] * max_cols)]
    lines.extend(" | ".join(r) for r in rows[1:])
    return "\n".join(lines)


def element_from_node(node: Tag, base_url: str) -> dict[str, Any] | None:
    name = (node.name or "").lower()
    embed_url = extract_embed_url(node, base_url)
    classes = node_classes(node)
    if embed_url and (name in {"iframe", "blockquote", "figure", "div"} or any(x in classes for x in ["twitter", "tweet", "instagram", "embed", "youtube", "tiktok"])):
        return {"type": "embed", "url": embed_url, "source_tag": name}
    if name in {"p", "li"}:
        text = clean_text(node.get_text(" "))
        if is_bio_or_footer_text(text) or any(pattern.search(text) for pattern in SOURCE_INTRO_PATTERNS):
            return None
        if is_probable_long_quote(text):
            return {"type": "quote", "text": text, "source_tag": name}
        return {"type": "text", "text": text}
    if name in {"h2", "h3", "h4"}:
        text = clean_text(node.get_text(" "))
        if not text or is_bio_or_footer_text(text) or is_footer_start_text(text):
            return None
        return {"type": "heading", "level": int(name[1]), "text": text}
    if name == "blockquote":
        text = clean_text(node.get_text(" "))
        if len(text) < 8:
            return None
        if is_cta_text(text):
            return None
        return {"type": "quote", "text": text, "source_tag": "blockquote"}
    if name == "table":
        rows = table_rows(node)
        if rows:
            return {"type": "table", "rows": rows, "markdown": table_to_markdown(rows)}
    if name == "img":
        src = node.get("src") or node.get("data-src") or node.get("data-lazy-src") or ""
        if not src:
            srcset = node.get("srcset") or ""
            if srcset:
                src = srcset.split(",")[0].strip().split(" ")[0]
        src = absolute_url(base_url, src)
        if not src or src.startswith("data:") or is_social_or_noise_url(src):
            return None
        return {"type": "image", "url": src, "alt": clean_text(node.get("alt", ""))}
    if name == "iframe" and embed_url:
        return {"type": "embed", "url": embed_url, "source_tag": "iframe"}
    return None


def sanitize_elements(elements: list[dict[str, Any]], featured_image: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cleaned: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    first_image_seen = False
    seen_embeds: set[str] = set()
    for idx, item in enumerate(elements, start=1):
        kind = item.get("type")
        text = clean_text(item.get("text", "")) if kind in {"text", "heading", "quote"} else ""
        remove_reason = ""
        stop_after = False
        if kind == "embed":
            url = canonical_embed_url(str(item.get("url") or ""))
            item["url"] = url
            if not url or url in seen_embeds:
                remove_reason = "duplicate_or_empty_embed"
            else:
                seen_embeds.add(url)
        elif text and is_footer_start_text(text):
            remove_reason = "footer_start"
            stop_after = True
        elif text and any(pattern.search(text) for pattern in BIO_PATTERNS):
            remove_reason = "bio_or_credit"
            stop_after = True
        elif text and is_cta_text(text):
            remove_reason = "cta_or_comment_bait"
        elif kind == "image" and not first_image_seen:
            first_image_seen = True
            if same_image(item.get("url", ""), featured_image):
                remove_reason = "duplicate_featured_image"
        elif kind == "image" and same_image(item.get("url", ""), featured_image) and cleaned:
            remove_reason = "duplicate_featured_image"
        if remove_reason:
            removed.append({"index": idx, "reason": remove_reason, "item": item})
            if stop_after:
                break
            continue
        cleaned.append(item)
    return cleaned, removed


def extract_elements(source_url: str, raw_html: str) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    diagnostics: dict[str, Any] = {"dom_noise_reduction_enabled": False, "stage": "parse_html"}
    soup = BeautifulSoup(raw_html, "html.parser")
    diagnostics["stage"] = "extract_meta"
    meta = extract_meta(soup, source_url)
    diagnostics["stage"] = "choose_article_root"
    root = choose_article_root(soup)
    diagnostics["root_name"] = getattr(root, "name", "")
    diagnostics["root_text_chars"] = len(clean_text(root.get_text(" "))) if root else 0
    diagnostics["stage"] = "scan_nodes"
    raw_elements: list[dict[str, Any]] = []
    removed_by_node: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    scan_nodes = list(root.find_all(["h2", "h3", "h4", "p", "li", "blockquote", "table", "img", "iframe", "figure", "div"], recursive=True)) if root else []
    diagnostics["candidate_node_count"] = len(scan_nodes)
    for node_idx, node in enumerate(scan_nodes, start=1):
        try:
            name = (node.name or "").lower()
            if name not in {"blockquote", "table", "figure", "div", "iframe"} and node.find_parent(["blockquote", "table", "figure"]):
                continue
            classes = node_classes(node)
            if name not in {"table", "blockquote", "iframe", "figure", "div"} and any(token in classes for token in ["share", "social", "newsletter", "related", "author-bio", "authorbox", "recommended", "spotlight"]):
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
    diagnostics.update({
        "raw_element_count": len(raw_elements),
        "clean_element_count": len(clean_elements),
        "removed_by_node_count": len(removed_by_node),
        "removed_by_sanitize_count": len(removed_by_sanitize),
        "table_count": sum(1 for e in clean_elements if e.get("type") == "table"),
        "quote_count": sum(1 for e in clean_elements if e.get("type") == "quote"),
        "embed_count": sum(1 for e in clean_elements if e.get("type") == "embed"),
        "stage": "complete",
    })
    return meta, raw_elements, clean_elements, removed_by_node + removed_by_sanitize, diagnostics


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
                if not isinstance(row, list):
                    continue
                for cidx, cell in enumerate(row):
                    if clean_text(str(cell)):
                        units.append({"id": f"{item['block_id']}_r{ridx}_c{cidx}", "type": "table_cell", "text": str(cell)})
    return units


def call_gemini(prompt: str) -> tuple[str, str, list[str]]:
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
                if text.strip():
                    return text.strip(), model, attempts
            except Exception as exc:
                last_error = f"{model}: {exc}"
    except Exception as exc:
        last_error = f"genai_import_or_client_error: {exc}"
    return "", last_error or "empty_response", attempts


def build_translation_prompt(item: dict[str, Any], meta: dict[str, str], units: list[dict[str, str]]) -> str:
    return f"""Sei Bob, traduttore di OpenWrestlingTV.

Traduci in italiano naturale e giornalistico SOLO i blocchi testuali indicati. Non devi ricostruire l'articolo completo: la sequenza HTML sara' ricostruita dal sistema preservando immagini, embed e tabelle.

REGOLE
- Non riassumere e non aggiungere informazioni.
- Conserva fedelmente il significato di ogni blocco.
- Le citazioni vanno tradotte integralmente.
- Mantieni nomi propri, promotion, show e termini wrestling quando appropriato.
- Usa terminologia wrestling italiana corretta e naturale.
- Rispondi SOLO in JSON valido.

Forma richiesta:
{{
  "title_it": "titolo italiano breve e non clickbait",
  "excerpt_it": "excerpt italiano breve",
  "translations": {{
    "b1": "traduzione blocco 1",
    "b2": "traduzione blocco 2"
  }},
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
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
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
            text = translations.get(block_id, str(item.get("text") or ""))
            level = int(item.get("level") or 2)
            out.append(f"<h{level}>{html.escape(text)}</h{level}>")
        elif kind == "text":
            text = translations.get(block_id, str(item.get("text") or ""))
            out.append(f"<p>{html.escape(text)}</p>")
        elif kind == "quote":
            text = translations.get(block_id, str(item.get("text") or ""))
            out.append(f"<blockquote>{html.escape(text)}</blockquote>")
        elif kind == "table":
            rows = item.get("rows") if isinstance(item.get("rows"), list) else []
            out.append(render_table(rows, translations, block_id))
        elif kind == "image":
            out.append(f"<!--IMAGE:{item.get('url', '')}-->")
        elif kind == "embed":
            url = canonical_embed_url(str(item.get("url") or ""))
            if url:
                out.append("\n" + html.escape(url) + "\n")
    return "\n".join(x for x in out if x).strip()


def article_package(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url") or item.get("source_url") or "")
    package: dict[str, Any] = {"source_url": url, "source": item.get("source"), "source_title": item.get("title"), "category_hint": item.get("category_hint"), "menzo_score": item.get("score"), "status": "error", "created_at": utc_now(), "diagnostic_stage": "start"}
    try:
        package["diagnostic_stage"] = "fetch_html"
        raw = fetch_html(url)
        package["fetched_html_chars"] = len(raw)
        package["source_html_contains_embed_hint"] = bool(re.search(r"twitter-tweet|x\.com|twitter\.com|instagram\.com|youtube\.com|youtu\.be|iframe", raw, re.I))
        package["diagnostic_stage"] = "extract_elements"
        meta, raw_elements, elements, removed, extraction_diag = extract_elements(url, raw)
        units = build_translation_units(elements)
        package["meta"] = meta
        package["extraction_diagnostics"] = extraction_diag
        package["raw_element_count"] = len(raw_elements)
        package["clean_element_count"] = len(elements)
        package["translation_unit_count"] = len(units)
        package["removed_before_gemini"] = len(removed)
        package["removed_elements_debug"] = removed[:30]
        package["raw_elements_preview"] = raw_elements[:30]
        package["elements"] = elements
        package["element_counts"] = {kind: sum(1 for e in elements if e.get("type") == kind) for kind in ["text", "heading", "quote", "table", "image", "embed"]}
        if not elements or not units:
            package["status"] = "extraction_empty"
            package["diagnostic_stage"] = "extraction_empty"
            return package
        prompt = build_translation_prompt(item, meta, units)
        package["translation_prompt_preview"] = prompt[:AUDIT_CHARS]
        package["diagnostic_stage"] = "call_gemini"
        translated, model_or_error, attempts = call_gemini(prompt)
        package["translation_chain_attempted"] = attempts
        package["translation_model"] = model_or_error
        package["translation_used"] = bool(translated)
        if translated:
            package["translation_raw_response_preview"] = translated[:AUDIT_CHARS]
            package["diagnostic_stage"] = "parse_json"
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
            fallback_translations = {u["id"]: u["text"] for u in units}
            package["title_it"] = meta.get("source_title") or item.get("title") or ""
            package["body_html"] = render_body(elements, fallback_translations)
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
    selected = selected[:MAX_ARTICLES_PER_RUN]
    print(f"[BOB v93.10] Avvio traduzione a blocchi | selected={len(selected)}", flush=True)
    articles = [article_package(item) for item in selected if isinstance(item, dict)]
    result = {
        "agent": "Bob",
        "version": BOB_VERSION,
        "generated_at": utc_now(),
        "mode": "block_translation_preserve_non_text_elements",
        "policy": {
            "clean_before_gemini": True,
            "gemini_receives_only_text_units": True,
            "preserve_sequence_outside_gemini": True,
            "preserve_embeds_as_plain_url_lines": True,
            "preserve_quotes_as_blockquote": True,
            "preserve_tables_as_html_tables": True,
            "ordered_elements": ["text", "heading", "quote", "table", "image", "embed"],
            "model_chain": MODEL_CHAIN,
            "max_articles_per_run": MAX_ARTICLES_PER_RUN,
            "prompt_family": "v92_historical_natural_full_translation_blocks",
            "diagnostic_mode": True,
            "fallback_mode": False,
        },
        "input": {"menzo_version": decision.get("version") if isinstance(decision, dict) else None, "selected_count": len(decision.get("selected", [])) if isinstance(decision, dict) and isinstance(decision.get("selected"), list) else len(selected)},
        "articles": articles,
        "handoff": {
            "ready_for_alfred": sum(1 for article in articles if article.get("status") == "ready_for_alfred"),
            "translation_pending": sum(1 for article in articles if article.get("status") == "extraction_ready_translation_pending"),
            "errors": sum(1 for article in articles if article.get("status") == "error"),
            "extraction_empty": sum(1 for article in articles if article.get("status") == "extraction_empty"),
        },
    }
    write_json(ARTIFACT_BOB_FILE, result)
    write_json(BOB_ARTICLES_FILE, result)
    print("[BOB v93.10] Pacchetti pronti | ready={ready} pending={pending} empty={empty} errors={errors}".format(ready=result["handoff"]["ready_for_alfred"], pending=result["handoff"]["translation_pending"], empty=result["handoff"]["extraction_empty"], errors=result["handoff"]["errors"]), flush=True)
    return result


if __name__ == "__main__":
    out = run_bob()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
