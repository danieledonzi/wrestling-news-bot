from __future__ import annotations

import html
import json
import os
import re
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

BOB_VERSION = "v93_4_bob_article_writer"
REQUEST_TIMEOUT = int(os.getenv("V93_BOB_REQUEST_TIMEOUT", "18"))
MAX_ARTICLES_PER_RUN = int(os.getenv("V93_BOB_MAX_ARTICLES_PER_RUN", "3"))
MODEL_CHAIN = [m.strip() for m in os.getenv(
    "GEMINI_MODEL_CHAIN",
    "gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash-lite,gemini-2.5-flash",
).split(",") if m.strip()]

DROP_CONTAINER_SELECTORS = [
    "script", "style", "noscript", "iframe[src*='googletagmanager']", "form",
    ".ad", ".ads", ".advertisement", ".newsletter", ".related", ".read-more",
    ".author-bio", ".bio", ".article-footer", ".post-footer", ".share", ".social-share",
]

ARTICLE_SELECTORS = [
    "article",
    "main article",
    ".article-body",
    ".post-content",
    ".entry-content",
    ".content",
    "main",
]

BIO_PATTERNS = [
    re.compile(r"\babout\s+the\s+author\b", re.I),
    re.compile(r"\bfollow\s+.+\s+on\s+(twitter|x|instagram|facebook)\b", re.I),
    re.compile(r"\bhas\s+been\s+covering\s+(wrestling|sports entertainment)\b", re.I),
    re.compile(r"\b(more|read more)\s+from\s+[A-Z][a-z]+", re.I),
    re.compile(r"\bthanks\s+to\s+.+\s+for\s+the\s+transcription\b", re.I),
]

SOURCE_INTRO_PATTERNS = [
    re.compile(r"^\s*according\s+to\s+.+?:\s*$", re.I),
    re.compile(r"^\s*per\s+.+?:\s*$", re.I),
]


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


def same_image(a: str, b: str) -> bool:
    if not a or not b:
        return False
    pa = urlparse(a)
    pb = urlparse(b)
    return (pa.netloc.lower(), pa.path.rstrip("/")) == (pb.netloc.lower(), pb.path.rstrip("/"))


def absolute_url(base: str, value: str) -> str:
    return urljoin(base, value or "").strip()


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
    }
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


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


def remove_noise(root: Tag) -> None:
    for selector in DROP_CONTAINER_SELECTORS:
        for node in root.select(selector):
            node.decompose()


def is_bio_or_footer_text(text: str) -> bool:
    if not text:
        return True
    if len(text) < 20:
        return True
    return any(pattern.search(text) for pattern in BIO_PATTERNS)


def element_from_node(node: Tag, base_url: str) -> dict[str, Any] | None:
    name = (node.name or "").lower()
    if name in {"p", "li"}:
        text = clean_text(node.get_text(" "))
        if is_bio_or_footer_text(text):
            return None
        if any(pattern.search(text) for pattern in SOURCE_INTRO_PATTERNS):
            return None
        return {"type": "text", "text": text}
    if name in {"h2", "h3", "h4"}:
        text = clean_text(node.get_text(" "))
        if not text or is_bio_or_footer_text(text):
            return None
        return {"type": "heading", "level": int(name[1]), "text": text}
    if name == "blockquote":
        text = clean_text(node.get_text(" "))
        cite_url = ""
        link = node.find("a", href=True)
        if link:
            cite_url = absolute_url(base_url, link.get("href", ""))
        if len(text) < 8 and not cite_url:
            return None
        return {"type": "quote", "text": text, "url": cite_url}
    if name == "img":
        src = node.get("src") or node.get("data-src") or node.get("data-lazy-src") or ""
        if not src:
            srcset = node.get("srcset") or ""
            if srcset:
                src = srcset.split(",")[0].strip().split(" ")[0]
        src = absolute_url(base_url, src)
        if not src or src.startswith("data:"):
            return None
        alt = clean_text(node.get("alt", ""))
        return {"type": "image", "url": src, "alt": alt}
    if name == "iframe":
        src = absolute_url(base_url, node.get("src", ""))
        if src:
            return {"type": "embed", "url": src}
    if name == "a":
        href = absolute_url(base_url, node.get("href", ""))
        text = clean_text(node.get_text(" "))
        if href and text and len(text) > 20:
            return {"type": "link", "text": text, "url": href}
    return None


def extract_elements(source_url: str, raw_html: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    soup = BeautifulSoup(raw_html, "html.parser")
    meta = extract_meta(soup, source_url)
    root = choose_article_root(soup)
    remove_noise(root)

    elements: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    for node in root.find_all(["h2", "h3", "h4", "p", "li", "blockquote", "img", "iframe", "a"], recursive=True):
        item = element_from_node(node, source_url)
        if not item:
            continue
        if item["type"] in {"text", "heading", "quote", "link"}:
            key = text_key(item.get("text", ""))
            if not key or key in seen_text:
                continue
            seen_text.add(key)
        elements.append(item)

    # Remove first inline image when it duplicates the featured image.
    featured = meta.get("featured_image", "")
    cleaned: list[dict[str, Any]] = []
    first_image_seen = False
    for item in elements:
        if item.get("type") == "image" and not first_image_seen:
            first_image_seen = True
            if same_image(item.get("url", ""), featured):
                continue
        cleaned.append(item)

    # Trim trailing author/bio/footer text blocks.
    while cleaned and cleaned[-1].get("type") == "text" and is_bio_or_footer_text(cleaned[-1].get("text", "")):
        cleaned.pop()
    return meta, cleaned


def elements_to_translation_source(elements: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, item in enumerate(elements, start=1):
        kind = item.get("type")
        if kind in {"text", "heading", "quote", "link"}:
            lines.append(f"[{idx}|{kind}] {item.get('text', '')}")
        elif kind == "image":
            lines.append(f"[{idx}|image] {item.get('url', '')} ALT={item.get('alt', '')}")
        elif kind == "embed":
            lines.append(f"[{idx}|embed] {item.get('url', '')}")
    return "\n".join(lines)


def call_gemini(prompt: str) -> tuple[str, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "", "missing_api_key"
    last_error = ""
    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=api_key)
        for model in MODEL_CHAIN:
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                text = getattr(response, "text", "") or ""
                if text.strip():
                    return text.strip(), model
            except Exception as exc:
                last_error = f"{model}: {exc}"
    except Exception as exc:
        last_error = f"genai_import_or_client_error: {exc}"
    return "", last_error or "empty_response"


def build_translation_prompt(item: dict[str, Any], meta: dict[str, str], elements: list[dict[str, Any]]) -> str:
    source = elements_to_translation_source(elements)
    return f"""Sei Bob, traduttore e redattore di OpenWrestlingTV.

Obiettivo: trasformare una news americana di wrestling in un articolo italiano naturale, fedele e pubblicabile.

Regole editoriali:
- Non riassumere: conserva tutte le informazioni rilevanti presenti nel testo fonte.
- Traduci integralmente le frasi tra virgolette, senza inventare dichiarazioni.
- Mantieni tono giornalistico naturale italiano, non meccanico.
- Non aggiungere dettagli non presenti nella fonte.
- Non includere bio autore, call to action del sito fonte, disclaimer, blocchi pubblicitari o finali editoriali estranei.
- Mantieni una sequenza ordinata di blocchi. Per immagini/embed restituisci placeholder HTML comment: <!--IMAGE:URL--> o <!--EMBED:URL-->.
- Se una citazione è attribuita, conserva attribuzione e contesto.
- Titolo italiano breve, chiaro, SEO-friendly ma non clickbait.

Rispondi SOLO in JSON valido con questa forma:
{{
  "title_it": "...",
  "body_html": "<p>...</p>",
  "excerpt_it": "...",
  "notes": ["..."]
}}

Metadati fonte:
URL: {item.get('url') or item.get('source_url')}
Titolo feed: {item.get('title')}
Titolo pagina: {meta.get('source_title')}
Descrizione: {meta.get('description')}
Categoria suggerita: {item.get('category_hint')}

Blocchi ordinati estratti:
{source}
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
    return {"title_it": "", "body_html": "", "excerpt_it": "", "notes": ["bob_json_parse_failed"], "raw": raw[:4000]}


def fallback_body(elements: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for item in elements:
        kind = item.get("type")
        if kind == "heading":
            out.append(f"<h{item.get('level', 2)}>{html.escape(item.get('text', ''))}</h{item.get('level', 2)}>")
        elif kind == "text":
            out.append(f"<p>{html.escape(item.get('text', ''))}</p>")
        elif kind == "quote":
            out.append(f"<blockquote>{html.escape(item.get('text', ''))}</blockquote>")
        elif kind == "image":
            out.append(f"<!--IMAGE:{item.get('url', '')}-->")
        elif kind == "embed":
            out.append(f"<!--EMBED:{item.get('url', '')}-->")
    return "\n".join(out)


def article_package(item: dict[str, Any]) -> dict[str, Any]:
    url = str(item.get("url") or item.get("source_url") or "")
    package: dict[str, Any] = {
        "source_url": url,
        "source": item.get("source"),
        "source_title": item.get("title"),
        "category_hint": item.get("category_hint"),
        "menzo_score": item.get("score"),
        "status": "error",
        "created_at": utc_now(),
    }
    try:
        raw = fetch_html(url)
        meta, elements = extract_elements(url, raw)
        package["meta"] = meta
        package["elements"] = elements
        package["element_counts"] = {kind: sum(1 for e in elements if e.get("type") == kind) for kind in ["text", "heading", "quote", "image", "embed", "link"]}
        if not elements:
            package["status"] = "extraction_empty"
            return package
        prompt = build_translation_prompt(item, meta, elements)
        translated, model_or_error = call_gemini(prompt)
        package["translation_model"] = model_or_error
        if translated:
            data = parse_bob_json(translated)
            package["title_it"] = clean_text(data.get("title_it") or meta.get("source_title") or item.get("title") or "")
            package["body_html"] = data.get("body_html") or fallback_body(elements)
            package["excerpt_it"] = clean_text(data.get("excerpt_it") or "")
            package["bob_notes"] = data.get("notes") if isinstance(data.get("notes"), list) else []
            package["status"] = "ready_for_alfred"
        else:
            package["title_it"] = meta.get("source_title") or item.get("title") or ""
            package["body_html"] = fallback_body(elements)
            package["excerpt_it"] = meta.get("description", "")
            package["bob_notes"] = ["translation_unavailable", model_or_error]
            package["status"] = "extraction_ready_translation_pending"
    except Exception as exc:
        package["error"] = str(exc)[:1200]
        package["status"] = "error"
    return package


def run_bob(menzo_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = menzo_decision if isinstance(menzo_decision, dict) else load_json(MENZO_DECISIONS_FILE, {})
    selected = decision.get("selected", []) if isinstance(decision, dict) else []
    if not isinstance(selected, list):
        selected = []
    selected = selected[:MAX_ARTICLES_PER_RUN]
    print(f"[BOB v93.4] Avvio scrittura articoli | selected={len(selected)}", flush=True)
    articles = [article_package(item) for item in selected if isinstance(item, dict)]
    result = {
        "agent": "Bob",
        "version": BOB_VERSION,
        "generated_at": utc_now(),
        "mode": "article_package_writer",
        "policy": {
            "drop_duplicate_first_featured_image": True,
            "drop_author_bio_and_footer": True,
            "ordered_elements": ["text", "heading", "quote", "image", "embed", "link"],
            "model_chain": MODEL_CHAIN,
            "max_articles_per_run": MAX_ARTICLES_PER_RUN,
        },
        "input": {
            "menzo_version": decision.get("version") if isinstance(decision, dict) else None,
            "selected_count": len(decision.get("selected", [])) if isinstance(decision, dict) and isinstance(decision.get("selected"), list) else len(selected),
        },
        "articles": articles,
        "handoff": {
            "ready_for_alfred": sum(1 for article in articles if article.get("status") == "ready_for_alfred"),
            "translation_pending": sum(1 for article in articles if article.get("status") == "extraction_ready_translation_pending"),
            "errors": sum(1 for article in articles if article.get("status") == "error"),
        },
    }
    write_json(ARTIFACT_BOB_FILE, result)
    write_json(BOB_ARTICLES_FILE, result)
    print(
        "[BOB v93.4] Pacchetti pronti | "
        f"ready={result['handoff']['ready_for_alfred']} pending={result['handoff']['translation_pending']} errors={result['handoff']['errors']}",
        flush=True,
    )
    return result


if __name__ == "__main__":
    out = run_bob()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
