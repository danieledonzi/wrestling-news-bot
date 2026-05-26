from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from google import genai

SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]
REQUEST_TIMEOUT = int(os.getenv("V92_REQUEST_TIMEOUT", "12"))
REQUEST_TIMEOUT_WP = int(os.getenv("V92_REQUEST_TIMEOUT_WP", "12"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_CHAIN = [m.strip() for m in os.getenv(
    "GEMINI_MODEL_CHAIN",
    "gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash-lite,gemini-2.5-flash",
).split(",") if m.strip()]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)
model_fail_counts = {model: 0 for model in MODEL_CHAIN}
category_cache: Dict[str, Optional[int]] = {}


def wp_root() -> str:
    raw = os.getenv("WP_URL", "").strip().rstrip("/")
    if "/wp-json" in raw:
        return raw.split("/wp-json", 1)[0].rstrip("/")
    return raw


def wp_posts_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/posts"


def wp_categories_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/categories"


def wp_auth() -> Tuple[str, str]:
    return os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", "")


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    return (normalize_text(text).replace(" ", "-")[:120] or "report")


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
        selectors = ["article", "div.post-content", "div.entry-content", "main"]
    else:
        selectors = ["article", "div.post-content", "div.entry-content", "main", "body"]
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return node
    return soup.body


def clean_article_text(content) -> str:
    if not content:
        return ""
    for trash in content(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        trash.decompose()
    for bad_sel in [".social_holder", ".social_icons", ".breadcrumbs", ".breadcrumb", "#pagination", ".related_link", ".amp-ad-wrapper", "amp-ad"]:
        for node in content.select(bad_sel):
            node.decompose()
    parts: List[str] = []
    for el in content.find_all(["p", "blockquote", "h2", "h3", "li", "a"]):
        if el.name == "a":
            href = (el.get("href") or "").strip()
            if href and any(domain in href for domain in SOCIAL_DOMAINS):
                parts.append(normalize_social_url(href))
        else:
            text = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()
            if len(text) > 20:
                parts.append(text)
    return "\n\n".join(parts)[:35000]


def scrape_article(url: str) -> Tuple[str, str]:
    res = session.get(url, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    html = res.text
    soup = BeautifulSoup(html, "html.parser")
    content = parse_content_container(soup, url)
    return clean_article_text(content), html


def extract_json_object(raw_text: str) -> Dict[str, Any]:
    raw = (raw_text or "").strip().replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end <= start:
        raise ValueError("JSON object non trovato")
    return json.loads(raw[start:end])


def generate_json(prompt: str) -> Tuple[Dict[str, Any], str]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY mancante")
    client = genai.Client(api_key=GEMINI_API_KEY)
    last: Optional[Exception] = None
    for model in MODEL_CHAIN:
        try:
            res = client.models.generate_content(model=model, contents=prompt)
            return extract_json_object(res.text), model
        except Exception as exc:
            last = exc
            continue
    raise last if last else RuntimeError("Nessun modello disponibile")


def translate_report(source_title: str, text: str, deterministic_title: str) -> Dict[str, str]:
    prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Traduci e rielabora in italiano un report risultati.
Non scrivere o cambiare il titolo: il titolo e' gia' deciso.
Mantieni match, segmenti, risultati, citazioni e URL social.
Non inventare e non riassumere in modo eccessivo.
Usa HTML semplice con <p>, <h2>, <h3>, <blockquote>, <b>, <a>.
Restituisci solo JSON valido in una riga: {{"testo":"html"}}

TITOLO DETERMINISTICO:
{deterministic_title}

TITOLO FONTE:
{source_title}

TESTO SORGENTE:
{text[:32000]}
"""
    data, model = generate_json(prompt)
    html = str(data.get("testo") or "").strip()
    plain = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    if len(plain) < 500:
        raise ValueError("Traduzione report troppo corta")
    return {"titolo": deterministic_title, "testo": html, "model": model}


def content_with_embeds(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if any(sp in href for sp in SOCIAL_DOMAINS):
            a.replace_with(f"\n\n{normalize_social_url(href)}\n\n")
    content = re.sub(r"https?://x\.com/", "https://twitter.com/", str(soup), flags=re.I)
    for domain in SOCIAL_DOMAINS:
        pattern = rf'(?<!["\'>])(https?://[^\s<"]*{re.escape(domain)}[^\s<"]*)'
        content = re.sub(pattern, r"\n\n\1\n\n", content)
    return content


def resolve_category_id(name: str) -> Optional[int]:
    key = name.lower().strip()
    if key in category_cache:
        return category_cache[key]
    res = session.get(wp_categories_url(), params={"search": name, "per_page": 20}, auth=wp_auth(), timeout=REQUEST_TIMEOUT_WP)
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


def publish_report(job: Dict[str, Any], translated: Dict[str, str]) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    payload: Dict[str, Any] = {
        "title": translated["titolo"],
        "content": content_with_embeds(translated["testo"]),
        "status": "publish",
        "meta": {"original_url": job.get("source_url"), "report_key": job.get("report_key")},
    }
    category_ids = resolve_category_ids(job.get("categories", []))
    if category_ids:
        payload["categories"] = category_ids
    res = session.post(wp_posts_url(), json=payload, auth=wp_auth(), timeout=REQUEST_TIMEOUT_WP)
    if res.status_code == 201:
        data = res.json()
        return int(data.get("id")), data
    raise RuntimeError(f"WordPress publish failed {res.status_code}: {res.text[:500]}")


def run_report_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:
    text, html = scrape_article(job["source_url"])
    translated = translate_report(job.get("source_title") or job.get("title") or "", text, job["title"])
    post_id, post_json = publish_report(job, translated)
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(job.get("title") or job.get("report_key") or "report")
    (published_dir / f"{slug}.html").write_text(translated["testo"], encoding="utf-8")
    (review_dir / f"{slug}.json").write_text(json.dumps({"job": job, "post": post_json, "source_excerpt": text[:4000], "model": translated.get("model")}, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(post_id), post_json or {}
