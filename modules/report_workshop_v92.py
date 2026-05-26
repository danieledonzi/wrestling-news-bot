from __future__ import annotations

import html as html_lib
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

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
category_cache: Dict[str, Optional[int]] = {}
media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}


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


def extract_blocks(content, base_url: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    if not content:
        return blocks
    remove_noise(content)
    seen_images: set[str] = set()
    allowed = ["h2", "h3", "p", "blockquote", "li", "img", "picture", "amp-img", "a"]
    for el in content.find_all(allowed):
        if el.find_parent(["script", "style", "nav", "footer", "header", "aside", "form"]):
            continue
        if el.name in {"img", "amp-img"}:
            src = best_img_src(el, base_url)
            if src and src not in seen_images:
                seen_images.add(src)
                alt = clean_text(el.get("alt") or "")
                blocks.append({"type": "image", "src": src, "alt": alt})
            continue
        if el.name == "picture":
            img = el.find(["img", "amp-img"])
            if img:
                src = best_img_src(img, base_url)
                if src and src not in seen_images:
                    seen_images.add(src)
                    alt = clean_text(img.get("alt") or "")
                    blocks.append({"type": "image", "src": src, "alt": alt})
            continue
        if el.name == "a":
            href = (el.get("href") or "").strip()
            if href and any(domain in href for domain in SOCIAL_DOMAINS):
                blocks.append({"type": "embed", "url": normalize_social_url(href)})
            continue
        text = clean_text(el.get_text(" ", strip=True))
        if len(text) < 20:
            continue
        if el.name in {"h2", "h3"}:
            blocks.append({"type": "heading", "level": el.name, "text": text})
        elif el.name == "blockquote":
            blocks.append({"type": "quote", "text": text})
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
    return blocks, html, featured


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
    prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Traduci in italiano i blocchi di un report risultati, senza riassumere.
Regole obbligatorie:
- restituisci lo stesso numero di item ricevuti;
- conserva l'indice i di ogni item;
- traduci ogni blocco separatamente;
- non unire blocchi diversi;
- non inventare nulla;
- non modificare il titolo deterministico;
- per heading usa solo testo tradotto, senza tag HTML;
- per paragraph/quote usa testo italiano naturale, senza markdown.
Rispondi solo con JSON valido in una riga: {{"items":[{{"i":0,"text":"..."}}]}}

TITOLO DETERMINISTICO:
{deterministic_title}

TITOLO FONTE:
{source_title}

BLOCCHI JSON:
{json.dumps(items, ensure_ascii=False)}
"""
    data, model = generate_json(prompt)
    arr = data.get("items") or []
    translated: Dict[int, str] = {}
    for item in arr:
        try:
            i = int(item.get("i"))
            txt = clean_text(str(item.get("text") or ""))
            if txt:
                translated[i] = txt
        except Exception:
            continue
    expected = {int(item["i"]) for item in items}
    missing = expected.difference(translated)
    if len(missing) > max(3, int(len(expected) * 0.15)):
        raise ValueError(f"Traduzione a blocchi incompleta: mancanti={sorted(list(missing))[:20]} model={model}")
    return translated


def upload_media(image_url: Optional[str]) -> Tuple[Optional[int], Optional[str]]:
    if not image_url:
        return None, None
    if image_url in media_cache:
        return media_cache[image_url]
    try:
        img_res = session.get(image_url, timeout=REQUEST_TIMEOUT)
        img_res.raise_for_status()
        content_type = img_res.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            media_cache[image_url] = (None, image_url)
            return None, image_url
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        if ext == ".jpe":
            ext = ".jpg"
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"
            content_type = "image/jpeg"
        filename = f"owtv_report_{os.urandom(4).hex()}{ext}"
        headers = {"Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"'}
        res = session.post(wp_media_url(), auth=wp_auth(), headers=headers, data=img_res.content, timeout=REQUEST_TIMEOUT_WP)
        if res.status_code == 201:
            data = res.json()
            media_id = int(data.get("id"))
            src = data.get("source_url") or image_url
            media_cache[image_url] = (media_id, src)
            return media_id, src
    except Exception:
        pass
    media_cache[image_url] = (None, image_url)
    return None, image_url


def render_blocks(blocks: List[Dict[str, str]], translated: Dict[int, str]) -> str:
    parts: List[str] = []
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
            _mid, src = upload_media(block.get("src"))
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


def publish_report(job: Dict[str, Any], content: str, featured_image_url: Optional[str]) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
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
    res = session.post(wp_posts_url(), json=payload, auth=wp_auth(), timeout=REQUEST_TIMEOUT_WP)
    if res.status_code == 201:
        data = res.json()
        return int(data.get("id")), data
    raise RuntimeError(f"WordPress publish failed {res.status_code}: {res.text[:500]}")


def run_report_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:
    blocks, _html, featured_image = scrape_article(job["source_url"])
    translated = translate_report_blocks(job.get("source_title") or job.get("title") or "", blocks, job["title"])
    content = render_blocks(blocks, translated)
    post_id, post_json = publish_report(job, content, featured_image)
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(job.get("title") or job.get("report_key") or "report")
    (published_dir / f"{slug}.html").write_text(content, encoding="utf-8")
    (review_dir / f"{slug}.json").write_text(json.dumps({
        "job": job,
        "post": post_json,
        "blocks": blocks[:120],
        "featured_image": featured_image,
        "translated_indexes": sorted(translated.keys()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(post_id), post_json or {}
