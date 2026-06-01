from __future__ import annotations

import html
import json
import mimetypes
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
PUBLISHED_DIR = ROOT / "published"
REVIEW_DIR = ROOT / "published_html_review"

ALFRED_REVIEW_FILE = NEWSROOM_STATE_DIR / "alfred_review_latest.json"
PUBLISHER_STATUS_FILE = NEWSROOM_STATE_DIR / "publisher_status_latest.json"
PUBLISHER_HISTORY_FILE = NEWSROOM_STATE_DIR / "publisher_history.json"
ARTIFACT_PUBLISHER_FILE = ARTIFACT_DIR / "publisher_result.json"

PUBLISHER_VERSION = "v93_6_publisher_wordpress"
REQUEST_TIMEOUT = int(os.getenv("V93_PUBLISHER_TIMEOUT", "25"))
MAX_POSTS_PER_RUN = int(os.getenv("V93_PUBLISHER_MAX_POSTS_PER_RUN", "3"))
POST_STATUS = os.getenv("V93_PUBLISHER_POST_STATUS", "publish").strip() or "publish"
DRY_RUN = str(os.getenv("V93_PUBLISHER_DRY_RUN", "0")).strip().lower() in {"1", "true", "yes", "on"}

session = requests.Session()
session.headers.update({"User-Agent": "OpenWrestlingTV-v93-Publisher/1.0"})
_category_cache: dict[str, int | None] = {}
_media_cache: dict[str, tuple[int | None, str | None]] = {}

IMAGE_PLACEHOLDER_RE = re.compile(r"<!--IMAGE:([^>]+)-->")
EMBED_PLACEHOLDER_RE = re.compile(r"<!--EMBED:([^>]+)-->")

CATEGORY_ALIASES = {
    "WWE": ["WWE"],
    "NXT": ["NXT", "WWE"],
    "AEW": ["AEW"],
    "TNA": ["TNA", "World"],
    "ROH": ["ROH", "AEW"],
    "World": ["World"],
    "Editoriali": ["Editoriali"],
}

SOURCE_LABELS = {
    "wrestlinginc": "Wrestling Inc.",
    "ringsidenews": "Ringside News",
    "fightful": "Fightful",
}


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


def slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:100] or "owtv-news"


def wp_root() -> str:
    raw = os.getenv("WP_URL", "").strip().rstrip("/")
    if "/wp-json" in raw:
        raw = raw.split("/wp-json", 1)[0].rstrip("/")
    return raw


def wp_auth() -> tuple[str, str]:
    return os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", "")


def wp_posts_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/posts"


def wp_media_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/media"


def wp_categories_url() -> str:
    return f"{wp_root()}/wp-json/wp/v2/categories"


def wp_ready() -> tuple[bool, str]:
    if not wp_root() or not all(wp_auth()):
        return False, "missing_wp_env"
    try:
        res = session.get(f"{wp_root()}/wp-json/", timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            return True, "ok"
        return False, f"wp_json_status_{res.status_code}"
    except Exception as exc:
        return False, f"wp_json_error:{exc}"


def wp_request(method: str, url: str, *, retries: int = 2, sleep_seconds: int = 4, **kwargs: Any) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            print(f"[PUBLISHER v93.6] WP {method.upper()} attempt {attempt}/{retries}: {url}", flush=True)
            res = session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
            if res.status_code in {408, 429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(sleep_seconds)
                continue
            return res
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(sleep_seconds)
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("wp_request failed")


def source_label(source: str) -> str:
    return SOURCE_LABELS.get((source or "").lower(), source or "fonte originale")


def source_key(url: str) -> str:
    raw = str(url or "").strip().lower()
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    return raw.rstrip("/")


def extract_image_placeholders(body_html: str) -> list[str]:
    return [m.group(1).strip() for m in IMAGE_PLACEHOLDER_RE.finditer(body_html or "") if m.group(1).strip()]


def clean_body_for_wordpress(body_html: str) -> str:
    body_html = IMAGE_PLACEHOLDER_RE.sub("", body_html or "")
    body_html = EMBED_PLACEHOLDER_RE.sub(lambda m: f'<p><a href="{html.escape(m.group(1).strip())}" target="_blank" rel="nofollow noopener">Contenuto incorporato</a></p>', body_html)
    body_html = re.sub(r"<p>\s*</p>", "", body_html)
    return body_html.strip()


def append_source(content: str, source: str, url: str) -> str:
    if not url:
        return content
    label = html.escape(source_label(source))
    href = html.escape(url)
    return content + f'\n<p class="owtv-source-attribution"><em>Fonte: <a href="{href}" target="_blank" rel="nofollow noopener">{label}</a>.</em></p>'


def candidate_featured_image(article: dict[str, Any]) -> str:
    meta = article.get("meta", {}) if isinstance(article.get("meta"), dict) else {}
    featured = str(meta.get("featured_image") or "").strip()
    if featured:
        return featured
    placeholders = extract_image_placeholders(str(article.get("body_html") or ""))
    return placeholders[0] if placeholders else ""


def resolve_category_id(name: str) -> int | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    if key in _category_cache:
        return _category_cache[key]
    try:
        res = wp_request("get", wp_categories_url(), params={"search": name, "per_page": 20}, auth=wp_auth())
        if res.status_code != 200:
            _category_cache[key] = None
            return None
        cats = res.json()
        exact = [c for c in cats if str(c.get("name", "")).strip().lower() == key]
        chosen = exact[0] if exact else (cats[0] if cats else None)
        cid = int(chosen["id"]) if chosen and chosen.get("id") else None
        _category_cache[key] = cid
        return cid
    except Exception:
        _category_cache[key] = None
        return None


def resolve_category_ids(category_hint: str) -> list[int]:
    names = CATEGORY_ALIASES.get(str(category_hint or "").strip(), [str(category_hint or "").strip() or "World"])
    out: list[int] = []
    for name in names:
        cid = resolve_category_id(name)
        if cid and cid not in out:
            out.append(cid)
    return out


def upload_media(image_url: str) -> tuple[int | None, str | None]:
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
        filename = f"owtv_v93_{os.urandom(4).hex()}{ext}"
        headers = {"Content-Type": content_type, "Content-Disposition": f'attachment; filename="{filename}"'}
        res = wp_request("post", wp_media_url(), auth=wp_auth(), headers=headers, data=img.content)
        if res.status_code == 201:
            data = res.json()
            media_id = int(data.get("id"))
            src = data.get("source_url") or image_url
            _media_cache[image_url] = (media_id, src)
            return media_id, src
        print(f"[PUBLISHER v93.6] Upload media non riuscito: status={res.status_code} body={res.text[:300]}", flush=True)
    except Exception as exc:
        print(f"[PUBLISHER v93.6] Upload media fallito: {image_url} | {exc}", flush=True)
    _media_cache[image_url] = (None, image_url)
    return None, image_url


def publish_article(article: dict[str, Any], history: dict[str, Any], wp_ok: bool) -> dict[str, Any]:
    url = str(article.get("source_url") or "")
    key = source_key(url)
    title = str(article.get("title_it") or "").strip()
    source = str(article.get("source") or "")
    if not key or not title:
        return {"source_url": url, "status": "skipped", "reason": "missing_url_or_title"}
    if key in history:
        return {"source_url": url, "status": "already_published", "wp_post_id": history[key].get("wp_post_id"), "title_it": title}

    cleaned_body = clean_body_for_wordpress(str(article.get("body_html") or ""))
    content = append_source(cleaned_body, source, url)
    image_url = candidate_featured_image(article)
    categories = resolve_category_ids(str(article.get("category_hint") or "")) if wp_ok else []
    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "status": POST_STATUS,
        "categories": categories,
        "excerpt": str(article.get("excerpt_it") or "")[:500],
        "meta": {
            "original_url": url,
            "owtv_source": source,
            "owtv_pipeline": PUBLISHER_VERSION,
        },
    }

    media_id: int | None = None
    if wp_ok and image_url:
        media_id, _src = upload_media(image_url)
        if media_id:
            payload["featured_media"] = media_id

    review_slug = slugify(title)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / f"v93_publisher_{review_slug}.html").write_text(content, encoding="utf-8")

    if DRY_RUN or not wp_ok:
        return {
            "source_url": url,
            "title_it": title,
            "status": "dry_run" if DRY_RUN else "wp_not_ready",
            "wp_ready": wp_ok,
            "payload_preview": {k: v for k, v in payload.items() if k != "content"},
            "content_chars": len(content),
            "image_url": image_url,
            "media_id": media_id,
        }

    res = wp_request("post", wp_posts_url(), json=payload, auth=wp_auth())
    if res.status_code not in {200, 201}:
        return {
            "source_url": url,
            "title_it": title,
            "status": "publish_error",
            "error": f"WP post failed {res.status_code}: {res.text[:600]}",
        }
    data = res.json()
    post_id = int(data.get("id"))
    post_link = data.get("link") or ""
    history[key] = {
        "source_url": url,
        "title_it": title,
        "wp_post_id": post_id,
        "wp_link": post_link,
        "published_at": utc_now(),
        "status": POST_STATUS,
        "source": source,
    }
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLISHED_DIR / f"v93_news_{review_slug}.html").write_text(content, encoding="utf-8")
    return {
        "source_url": url,
        "title_it": title,
        "status": "published",
        "wp_post_id": post_id,
        "wp_link": post_link,
        "featured_media": media_id,
        "categories": categories,
    }


def run_publisher(alfred_result: dict[str, Any] | None = None) -> dict[str, Any]:
    alfred = alfred_result if isinstance(alfred_result, dict) else load_json(ALFRED_REVIEW_FILE, {})
    articles = alfred.get("approved_articles", []) if isinstance(alfred, dict) else []
    if not isinstance(articles, list):
        articles = []
    articles = articles[:MAX_POSTS_PER_RUN]
    wp_ok, wp_reason = wp_ready()
    history = load_json(PUBLISHER_HISTORY_FILE, {})
    if not isinstance(history, dict):
        history = {}

    print(f"[PUBLISHER v93.6] Avvio pubblicazione | approved={len(articles)} wp_ok={wp_ok} dry_run={DRY_RUN}", flush=True)
    results = [publish_article(article, history, wp_ok) for article in articles if isinstance(article, dict)]
    if not DRY_RUN and wp_ok:
        write_json(PUBLISHER_HISTORY_FILE, history)

    result = {
        "agent": "Publisher",
        "version": PUBLISHER_VERSION,
        "generated_at": utc_now(),
        "mode": "wordpress_publisher",
        "input": {
            "alfred_version": alfred.get("version") if isinstance(alfred, dict) else None,
            "approved_articles": len(articles),
        },
        "wp": {
            "ready": wp_ok,
            "reason": wp_reason,
            "post_status": POST_STATUS,
            "dry_run": DRY_RUN,
        },
        "results": results,
        "handoff": {
            "published": sum(1 for r in results if r.get("status") == "published"),
            "already_published": sum(1 for r in results if r.get("status") == "already_published"),
            "dry_run": sum(1 for r in results if r.get("status") == "dry_run"),
            "wp_not_ready": sum(1 for r in results if r.get("status") == "wp_not_ready"),
            "errors": sum(1 for r in results if r.get("status") == "publish_error"),
        },
        "policy": {
            "source_attribution": True,
            "strip_inline_image_placeholders": True,
            "featured_image_source": "meta.featured_image_or_first_placeholder",
            "idempotency": "state/newsroom/publisher_history.json by source_url",
        },
    }
    write_json(ARTIFACT_PUBLISHER_FILE, result)
    write_json(PUBLISHER_STATUS_FILE, result)
    print(
        "[PUBLISHER v93.6] Pubblicazione completata | "
        f"published={result['handoff']['published']} already={result['handoff']['already_published']} "
        f"dry={result['handoff']['dry_run']} wp_not_ready={result['handoff']['wp_not_ready']} errors={result['handoff']['errors']}",
        flush=True,
    )
    return result


if __name__ == "__main__":
    out = run_publisher()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
