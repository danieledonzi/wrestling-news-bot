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

BOB_VERSION = "v93_4_1_bob_clean_source_writer"
REQUEST_TIMEOUT = int(os.getenv("V93_BOB_REQUEST_TIMEOUT", "18"))
MAX_ARTICLES_PER_RUN = int(os.getenv("V93_BOB_MAX_ARTICLES_PER_RUN", "3"))
AUDIT_CHARS = int(os.getenv("V93_BOB_AUDIT_CHARS", "24000"))
MODEL_CHAIN = [m.strip() for m in os.getenv(
    "GEMINI_MODEL_CHAIN",
    "gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash-lite,gemini-2.5-flash",
).split(",") if m.strip()]

DROP_CONTAINER_SELECTORS = [
    "script", "style", "noscript", "iframe[src*='googletagmanager']", "form",
    ".ad", ".ads", ".advertisement", ".newsletter", ".related", ".read-more",
    ".author-bio", ".bio", ".article-footer", ".post-footer", ".share", ".social-share",
    ".sharedaddy", ".jp-relatedposts", ".yarpp-related", ".more-stories", ".recommended",
    ".spotlight", ".trending", ".popular-posts", ".author-box", ".byline-box",
    "[class*='social']", "[class*='share']", "[class*='newsletter']", "[class*='related']",
    "[id*='social']", "[id*='share']", "[id*='newsletter']", "[id*='related']",
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
    re.compile(r"\bfollow\s+.+\s+on\s+(twitter|x|instagram|facebook|bluesky)\b", re.I),
    re.compile(r"\bhas\s+been\s+covering\s+(pro\s+)?wrestling\b", re.I),
    re.compile(r"\bdelivering\s+trusted\s+news\s+and\s+backstage\s+updates\b", re.I),
    re.compile(r"\b(more|read more)\s+from\s+[A-Z][a-z]+", re.I),
    re.compile(r"\bthanks\s+to\s+.+\s+for\s+the\s+transcription\b", re.I),
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

SOURCE_INTRO_PATTERNS = [
    re.compile(r"^\s*according\s+to\s+.+?:\s*$", re.I),
    re.compile(r"^\s*per\s+.+?:\s*$", re.I),
]

SOCIAL_OR_NOISE_DOMAINS = [
    "bsky.app", "twitter.com", "x.com", "facebook.com", "instagram.com", "threads.net",
    "google.com/preferences/source", "news.google.com",
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


def image_signature(url: str) -> str:
    parsed = urlparse(url or "")
    path = parsed.path.lower()
    path = path.replace("/wp-content/smush-avif/", "/wp-content/uploads/")
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r"\.(avif|webp|jpg|jpeg|png)$", "", name)
    name = re.sub(r"\.(avif|webp)$", "", name)
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
    for node in list(root.find_all(True)):
        attrs = " ".join(str(node.get(attr, "")) for attr in ["class", "id", "aria-label", "role"]).lower()
        if any(token in attrs for token in ["share", "social", "newsletter", "related", "author-bio", "authorbox", "recommended", "spotlight"]):
            node.decompose()
            continue
        text = clean_text(node.get_text(" "))
        if text and any(pattern.search(text) for pattern in FOOTER_START_PATTERNS):
            # remove compact widgets without deleting the whole article root
            if len(text) < 900 or node.name in {"aside", "section", "div"}:
                node.decompose()


def is_social_or_noise_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(domain in lowered for domain in SOCIAL_OR_NOISE_DOMAINS)


def is_cta_text(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in CTA_PATTERNS)


def is_footer_start_text(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in FOOTER_START_PATTERNS)


def is_bio_or_footer_text(text: str) -> bool:
    if not text:
        return True
    if len(text) < 20:
        return True
    if is_cta_text(text):
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
        if not text or is_bio_or_footer_text(text) or is_footer_start_text(text):
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
        if is_cta_text(text) or is_social_or_noise_url(cite_url):
            return None
        return {"type": "quote", "text": text, "url": cite_url}
    if name == "img":
        src = node.get("src") or node.get("data-src") or node.get("data-lazy-src") or ""
        if not src:
            srcset = node.get("srcset") or ""
            if srcset:
                src = srcset.split(",")[0].strip().split(" ")[0]
        src = absolute_url(base_url, src)
        if not src or src.startswith("data:") or is_social_or_noise_url(src):
            return None
        alt = clean_text(node.get("alt", ""))
        return {"type": "image", "url": src, "alt": alt}
    if name == "iframe":
        src = absolute_url(base_url, node.get("src", ""))
        if src and not is_social_or_noise_url(src):
            return {"type": "embed", "url": src}
    return None


def sanitize_elements(elements: list[dict[str, Any]], featured_image: str) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    first_image_seen = False
    for item in elements:
        kind = item.get("type")
        text = clean_text(item.get("text", "")) if kind in {"text", "heading", "quote"} else ""
        if text and is_footer_start_text(text):
            break
        if text and (is_cta_text(text) or any(pattern.search(text) for pattern in BIO_PATTERNS)):
            # comment bait can be skipped; author bio/spotlight starts footer and stops extraction
            if is_footer_start_text(text) or any(pattern.search(text) for pattern in BIO_PATTERNS):
                break
            continue
        if kind == "image" and not first_image_seen:
            first_image_seen = True
            if same_image(item.get("url", ""), featured_image):
                continue
        if kind == "image" and same_image(item.get("url", ""), featured_image) and cleaned:
            continue
        cleaned.append(item)
    return cleaned


def extract_elements(source_url: str, raw_html: str) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, Any]]]:
    soup = BeautifulSoup(raw_html, "html.parser")
    meta = extract_meta(soup, source_url)
    root = choose_article_root(soup)
    remove_noise(root)

    raw_elements: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    for node in root.find_all(["h2", "h3", "h4", "p", "li", "blockquote", "img", "iframe"], recursive=True):
        item = element_from_node(node, source_url)
        if not item:
            continue
        if item["type"] in {"text", "heading", "quote"}:
            key = text_key(item.get("text", ""))
            if not key or key in seen_text:
                continue
            seen_text.add(key)
        raw_elements.append(item)

    clean_elements = sanitize_elements(raw_elements, meta.get("featured_image", ""))
    return meta, raw_elements, clean_elements


def elements_to_translation_source(elements: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for idx, item in enumerate(elements, start=1):
        kind = item.get("type")
        if kind in {"text", "heading", "quote"}:
            lines.append(f"[{idx}|{kind}] {item.get('text', '')}")
        elif kind == "image":
            lines.append(f"[{idx}|image] {item.get('url', '')} ALT={item.get('alt', '')}")
        elif kind == "embed":
            lines.append(f"[{idx}|embed] {item.get('url', '')}")
    return "\n".join(lines)


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


def build_translation_prompt(item: dict[str, Any], meta: dict[str, str], elements: list[dict[str, Any]]) -> str:
    source = elements_to_translation_source(elements)
    return f"""Sei Bob, traduttore e redattore di OpenWrestlingTV.

Usa la linea editoriale storica della pipeline v92: traduzione completa, naturale, fedele, non meccanica, con tono giornalistico italiano e massima attenzione al contesto wrestling.

OBIETTIVO
Trasforma la news americana in un articolo italiano pubblicabile su OpenWrestlingTV.

REGOLE NON NEGOZIABILI
- Non riassumere: lavora tutto il contenuto pulito fornito nei blocchi ordinati.
- Non inventare nulla e non aggiungere dettagli non presenti nella fonte.
- Mantieni tutte le informazioni sostanziali presenti nella fonte.
- Le frasi tra virgolette vanno tradotte integralmente e fedelmente, senza parafrasi libera.
- Conserva attribuzioni, fonti citate e relazioni logiche tra soggetti.
- Usa italiano naturale, fluido, giornalistico, non letterale e non scolastico.
- Usa terminologia wrestling corretta: main roster, premium live event, stable, storyline, push, turn, title shot, booking, campione/campionessa, cintura/titolo solo quando appropriato.
- Non inserire CTA, domande ai lettori, inviti a commentare, bio autore, social bar, disclaimer o blocchi Spotlight/related. Se li vedi, ignorali.
- Mantieni la sequenza degli elementi. Per immagini/embed usa placeholder HTML comment: <!--IMAGE:URL--> o <!--EMBED:URL-->.
- Non tradurre nomi propri, nomi degli show, nomi delle promotion o hashtag se non necessario.
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

TESTO PULITO DA TRADURRE, GIA' RIPULITO DA CTA, BIO, SOCIAL BAR E BLOCCHI RELATED:
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
        meta, raw_elements, elements = extract_elements(url, raw)
        package["meta"] = meta
        package["raw_element_count"] = len(raw_elements)
        package["removed_before_gemini"] = max(0, len(raw_elements) - len(elements))
        package["elements"] = elements
        package["element_counts"] = {kind: sum(1 for e in elements if e.get("type") == kind) for kind in ["text", "heading", "quote", "image", "embed"]}
        if not elements:
            package["status"] = "extraction_empty"
            return package
        prompt = build_translation_prompt(item, meta, elements)
        package["translation_prompt_preview"] = prompt[:AUDIT_CHARS]
        translated, model_or_error, attempts = call_gemini(prompt)
        package["translation_chain_attempted"] = attempts
        package["translation_model"] = model_or_error
        package["translation_used"] = bool(translated)
        if translated:
            package["translation_raw_response_preview"] = translated[:AUDIT_CHARS]
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
        "mode": "clean_source_article_package_writer",
        "policy": {
            "clean_before_gemini": True,
            "drop_cta_comment_bait_social_bars_before_gemini": True,
            "drop_spotlight_related_blocks_before_gemini": True,
            "drop_duplicate_first_featured_image": True,
            "drop_author_bio_and_footer": True,
            "ordered_elements": ["text", "heading", "quote", "image", "embed"],
            "model_chain": MODEL_CHAIN,
            "max_articles_per_run": MAX_ARTICLES_PER_RUN,
            "prompt_family": "v92_historical_natural_full_translation",
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
