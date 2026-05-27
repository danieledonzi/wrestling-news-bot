from __future__ import annotations

import html as html_lib
import json
import mimetypes
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from google import genai
except Exception:  # pragma: no cover
    genai = None

REQUEST_TIMEOUT = int(os.getenv("V92_REQUEST_TIMEOUT", "12"))
REQUEST_TIMEOUT_WP = int(os.getenv("V92_WP_TIMEOUT", "25"))
DEFAULT_NEWS_MODEL_CHAIN = os.getenv(
    "GEMINI_NEWS_MODEL_CHAIN",
    os.getenv("GEMINI_MODEL_CHAIN", "gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash-lite,gemini-2.5-flash"),
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)
_category_cache: Dict[str, Optional[int]] = {}
_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}


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


def extract_article_text_and_media(url: str) -> Tuple[str, Optional[str]]:
    res = session.get(url, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    for node in soup.select("script, style, noscript, nav, footer, aside, form"):
        node.decompose()
    container = parse_content_container(soup, url)
    featured = extract_meta_image(soup, url)
    parts: List[str] = []
    for el in container.find_all(["h2", "h3", "p", "li", "blockquote"]):
        txt = clean_text(el.get_text(" ", strip=True))
        if should_skip_text(txt):
            continue
        if el.name in {"h2", "h3"}:
            parts.append(f"## {txt}")
        elif el.name == "blockquote":
            parts.append(f"> {txt}")
        else:
            parts.append(txt)
    article_text = "\n\n".join(parts)
    if len(article_text) < 400:
        title = soup.find("h1")
        fallback = clean_text(container.get_text(" ", strip=True))
        article_text = (clean_text(title.get_text(" ", strip=True)) + "\n\n" if title else "") + fallback[:8000]
    return article_text[:18000], featured


def gemini_client():
    if genai is None:
        raise RuntimeError("google-genai non disponibile")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY mancante")
    return genai.Client(api_key=key)


def model_chain() -> List[str]:
    return [m.strip() for m in DEFAULT_NEWS_MODEL_CHAIN.split(",") if m.strip()]


def gemini_generate(prompt: str, *, purpose: str) -> Tuple[str, str]:
    client = gemini_client()
    last_error: Optional[Exception] = None
    for model in model_chain():
        try:
            print(f"[NEWS v92] Provo modello: {model} | purpose={purpose}", flush=True)
            response = client.models.generate_content(model=model, contents=prompt)
            text = getattr(response, "text", None) or ""
            if text.strip():
                print(f"[NEWS v92] Modello scelto: {model} | purpose={purpose}", flush=True)
                return text.strip(), model
        except Exception as exc:
            last_error = exc
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


def translate_news(source_title: str, source_text: str, source: str) -> Tuple[str, str, str]:
    prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Non fare una traduzione letterale: devi trasformare il materiale in italiano giornalistico naturale, mantenendo fatti, nomi, date e citazioni.

Regole obbligatorie:
- Non inventare informazioni non presenti nel testo.
- Non aggiungere opinioni personali.
- Mantieni tutte le citazioni attribuite: se nel testo originale ci sono virgolette o dichiarazioni, riportale in italiano in modo fedele.
- Non scrivere introduzioni tipo "ecco la traduzione".
- Non citare la fonte nel corpo: la fonte viene aggiunta automaticamente dal sistema.
- Titolo italiano: naturale, giornalistico, non clickbait, massimo 95 caratteri.
- Corpo: articolo completo in italiano, con paragrafi leggibili.
- Evita stile AI, frasi gonfie, ripetizioni inutili e formule generiche.

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
    raw, model = gemini_generate(prompt, purpose="news_translate_title")
    data = extract_json(raw)
    title = clean_text(str(data.get("title") or source_title))[:120]
    body = str(data.get("body_html") or "").strip()
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model


def resolve_category_id(name: str) -> Optional[int]:
    key = name.lower().strip()
    if key in _category_cache:
        return _category_cache[key]
    res = wp_request_with_retry("get", wp_categories_url(), params={"search": name, "per_page": 20}, auth=wp_auth())
    if res.status_code != 200:
        _category_cache[key] = None
        return None
    cats = res.json()
    exact = [c for c in cats if str(c.get("name", "")).lower() == key]
    chosen = exact[0] if exact else (cats[0] if cats else None)
    cid = int(chosen["id"]) if chosen and chosen.get("id") else None
    _category_cache[key] = cid
    return cid


def resolve_category_ids(names: List[str]) -> List[int]:
    out: List[int] = []
    for name in names:
        cid = resolve_category_id(name)
        if cid and cid not in out:
            out.append(cid)
    return out


def upload_media(image_url: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    if not image_url:
        return None, None
    if image_url in _media_cache:
        return _media_cache[image_url]
    try:
        img = session.get(image_url, timeout=REQUEST_TIMEOUT)
        img.raise_for_status()
        content_type = img.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            _media_cache[image_url] = (None, image_url)
            return None, image_url
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        filename = f"owtv_news_{os.urandom(4).hex()}{ext}"
        headers = {"Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"'}
        res = wp_request_with_retry("post", wp_media_url(), auth=wp_auth(), headers=headers, data=img.content)
        if res.status_code == 201:
            data = res.json()
            media_id = int(data.get("id"))
            src = data.get("source_url") or image_url
            _media_cache[image_url] = (media_id, src)
            return media_id, src
    except Exception as exc:
        print(f"[NEWS v92] Upload media fallito: {image_url} | {exc}", flush=True)
    _media_cache[image_url] = (None, image_url)
    return None, image_url


def append_source(content: str, source: str, url: str) -> str:
    label = html_lib.escape(source_label(source))
    href = html_lib.escape(url or "")
    if not href:
        return content
    return content + f'\n<p class="owtv-source-attribution"><em>Fonte: <a href="{href}" target="_blank" rel="nofollow noopener">{label}</a>.</em></p>'


def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    media_id, _src = upload_media(image_url)
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


def run_news_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:
    print(f"[NEWS v92] Avvio workshop news: {job.get('news_key')} url={job.get('source_url')}", flush=True)
    source_text, image_url = extract_article_text_and_media(str(job["source_url"]))
    print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)}", flush=True)
    title, body_html, model = translate_news(str(job.get("source_title") or ""), source_text, str(job.get("source") or ""))
    print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    (review_dir / f"news_{slug}.prepublish.html").write_text(body_html, encoding="utf-8")
    post_id, post_json = publish_news(job, title, body_html, image_url)
    (published_dir / f"news_{slug}.html").write_text(body_html, encoding="utf-8")
    return post_id, post_json
