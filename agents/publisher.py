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
from urllib.parse import parse_qs, urlparse

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

PUBLISHER_VERSION = "v94_10_1_internal_media_preserve_author_filter_clean"
REQUEST_TIMEOUT = int(os.getenv("V93_PUBLISHER_TIMEOUT", "25"))
MAX_POSTS_PER_RUN = int(os.getenv("V93_PUBLISHER_MAX_POSTS_PER_RUN", os.getenv("V93_BOB_MAX_ARTICLES_PER_RUN", "5")))
POST_STATUS = os.getenv("V93_PUBLISHER_POST_STATUS", "publish").strip() or "publish"
DRY_RUN = str(os.getenv("V93_PUBLISHER_DRY_RUN", "0")).strip().lower() in {"1", "true", "yes", "on"}

session = requests.Session()
session.headers.update({"User-Agent": "OpenWrestlingTV-v93-Publisher/1.0"})
_category_cache: dict[str, int | None] = {}
_media_cache: dict[str, tuple[int | None, str | None]] = {}

IMAGE_PLACEHOLDER_RE = re.compile(r"<!--IMAGE:([^>]+)-->")
EMBED_PLACEHOLDER_RE = re.compile(r"<!--EMBED:([^>]+)-->")
EMBED_URL_PATTERN = r"https?://(?:www\.)?(?:x\.com|twitter\.com|instagram\.com|youtube\.com|youtube-nocookie\.com|youtu\.be|tiktok\.com|threads\.net|facebook\.com|bsky\.app)/\S+"
PLAIN_EMBED_URL_RE = re.compile(rf"(?m)^\s*({EMBED_URL_PATTERN})\s*$", re.I)
P_ONLY_EMBED_RE = re.compile(rf"<p>\s*({EMBED_URL_PATTERN})\s*</p>", re.I)
P_START_EMBED_RE = re.compile(rf"<p>\s*({EMBED_URL_PATTERN})\s*(?:<br\s*/?>|\n|\r\n)+\s*(.*?)</p>", re.I | re.S)
P_URL_THEN_TEXT_RE = re.compile(rf"<p>\s*({EMBED_URL_PATTERN})\s+([^<].*?)</p>", re.I | re.S)
WP_EMBED_BLOCK_RE = re.compile(r"<!-- wp:embed [\s\S]*?<!-- /wp:embed -->", re.I)
EMBED_URL_ANY_RE = re.compile(rf"({EMBED_URL_PATTERN})", re.I)

CATEGORY_ALIASES = {
    "WWE": ["WWE"],
    "NXT": ["NXT", "WWE"],
    "AEW": ["AEW"],
    "TNA": ["TNA", "World"],
    "ROH": ["ROH", "AEW"],
    "Business": ["Business", "World"],
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
            print(f"[PUBLISHER v93.10] WP {method.upper()} attempt {attempt}/{retries}: {url}", flush=True)
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

def clean_url(url: str) -> str:
    return html.unescape(str(url or "").strip()).rstrip(".,;:)]}\u201d\u2019</p>")


def embed_key(url: str) -> str:
    u = clean_url(url)
    parsed = urlparse(u)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.strip("/")
    q = parse_qs(parsed.query)
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        vid = ""
        if host == "youtu.be":
            vid = path.split("/", 1)[0]
        elif path.startswith("watch"):
            vid = (q.get("v") or [""])[0]
        elif path.startswith("embed/"):
            vid = path.split("/", 1)[1].split("/", 1)[0]
        if vid:
            return "youtube:" + vid
    if host in {"x.com", "twitter.com"}:
        parts = [x for x in path.split("/") if x]
        if "status" in parts:
            i = parts.index("status")
            if i + 1 < len(parts):
                return "twitter:" + parts[i + 1].lower()
        if len(parts) >= 3 and parts[0] == "i" and parts[1] == "status":
            return "twitter:" + parts[2].lower()
    return host + ":" + path.lower()


def display_embed_url(url: str) -> str:
    u = clean_url(url)
    parsed = urlparse(u)
    host = parsed.netloc.lower().replace("www.", "")
    k = embed_key(u)
    if k.startswith("youtube:"):
        return "https://www.youtube.com/watch?v=" + k.split(":", 1)[1]
    if k.startswith("twitter:") and host in {"x.com", "twitter.com"}:
        parts = [x for x in parsed.path.strip("/").split("/") if x]
        if len(parts) >= 3 and parts[1] == "status":
            return "https://twitter.com/" + parts[0] + "/status/" + parts[2]
        if len(parts) >= 3 and parts[0] == "i" and parts[1] == "status":
            return "https://twitter.com/i/status/" + parts[2]
    return u


def embed_block(url: str) -> str:
    u = display_embed_url(url)
    host = urlparse(u).netloc.lower().replace("www.", "")
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        # v93.33: YouTube embeds work best in WordPress as a plain URL on its own line.
        # This avoids an ugly Shortcode block in the editor while preserving front-end oEmbed.
        return html.escape(u)
    # v93.33: social embeds are kept as shortcode blocks because plain X/Twitter URLs
    # often remain plain text until a manual editor conversion.
    return '<!-- wp:shortcode -->\n[embed]' + html.escape(u) + '[/embed]\n<!-- /wp:shortcode -->'


def convert_embed_urls(body_html: str) -> str:
    seen: set[str] = set()
    def repl(match):
        url = match.group(1)
        k = embed_key(url)
        if k in seen:
            return ""
        seen.add(k)
        rest = match.group(2).strip() if len(match.groups()) > 1 and match.group(2) else ""
        out = "\n\n" + embed_block(url) + "\n\n"
        return out + ("<p>" + rest + "</p>" if rest else "")
    text = body_html or ""
    text = P_START_EMBED_RE.sub(repl, text)
    text = P_URL_THEN_TEXT_RE.sub(repl, text)
    text = P_ONLY_EMBED_RE.sub(repl, text)
    text = PLAIN_EMBED_URL_RE.sub(repl, text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def is_author_or_boilerplate_image_url(image_url: str) -> bool:
    """v94.10.1 safety net: avoid rendering author/avatar/sidebar/footer images."""
    u = clean_url(image_url).lower()
    if not u:
        return True
    bad_terms = [
        "avatar", "gravatar", "author", "profile", "bio",
        "headshot", "userphoto", "user-photo", "wp-user-avatar",
        "derek%20holloway", "derek-holloway",
        "ringside-text-footer", "footer"
    ]
    if any(term in u for term in bad_terms):
        return True
    if any(size in u for size in ["-64x64.", "-70x70.", "-88x88.", "-96x96.", "-120x120.", "-128x128.", "-150x150.", "-192x192."]):
        return True
    return False


def image_block(image_url: str, *, wp_ok: bool = True) -> str:
    """v94.9: preserve standard-news internal images in the article body.

    Bob renders source images as <!--IMAGE:url--> placeholders.
    Before v94.9 Publisher stripped those placeholders. Now Publisher rehydrates
    them as WordPress image figures, uploading to Media Library when possible.
    """
    image_url = clean_url(image_url)
    if not image_url:
        return ""
    if is_author_or_boilerplate_image_url(image_url):
        print(f"[PUBLISHER v94.10.1] Immagine autore/boilerplate scartata: {image_url}", flush=True)
        return ""
    media_id = None
    src = image_url
    if wp_ok:
        media_id, uploaded_src = upload_media(image_url)
        if uploaded_src:
            src = uploaded_src
    safe_src = html.escape(src, quote=True)
    wp_id_class = f" wp-image-{media_id}" if media_id else ""
    return (
        f'<figure class="owtv-inline-image{wp_id_class}">'
        f'<img src="{safe_src}" alt="" loading="lazy" />'
        f'</figure>'
    )


def render_image_placeholders(body_html: str, *, wp_ok: bool = True) -> str:
    def repl(match: re.Match[str]) -> str:
        url = match.group(1).strip()
        block = image_block(url, wp_ok=wp_ok)
        if block:
            print(f"[PUBLISHER v94.10.1] Immagine interna preservata: {url}", flush=True)
            return "\n\n" + block + "\n\n"
        return ""
    return IMAGE_PLACEHOLDER_RE.sub(repl, body_html or "")



def normalized_story_blob(article: dict[str, Any]) -> str:
    parts = [article.get("title_it"), article.get("source_title"), article.get("excerpt_it"), article.get("source_url")]
    meta = article.get("meta") if isinstance(article.get("meta"), dict) else {}
    parts.extend([meta.get("title"), meta.get("source_title")])
    blob = " ".join(str(x or "") for x in parts).lower()
    return re.sub(r"\s+", " ", blob)


def story_signature(article: dict[str, Any]) -> str:
    blob = normalized_story_blob(article)
    if "mjf" in blob and any(x in blob for x in ["injury", "infortun", "pulled", "rimosso", "rinunciare", "booking"]) and any(x in blob for x in ["indie", "independent", "evento indipendente", "beyond wrestling"]):
        return "story:aew:mjf:indie_injury"
    if "liv morgan" in blob and "dominik" in blob and any(x in blob for x in ["frustration", "frustrazione", "booking"]):
        return "story:wwe:liv_morgan_dominik_booking_frustration"
    if "jim ross" in blob and "lawsuit" in blob and any(x in blob for x in ["vince", "shareholder", "azionisti"]):
        return "story:wwe:vince_shareholder_lawsuit_jim_ross"
    return ""


def existing_story_duplicate(history: dict[str, Any], signature: str) -> dict[str, Any] | None:
    if not signature:
        return None
    for item in history.values():
        if isinstance(item, dict) and item.get("story_signature") == signature:
            return item
    return None

def clean_body_for_wordpress(body_html: str, *, wp_ok: bool = True) -> str:
    body_html = render_image_placeholders(body_html or "", wp_ok=wp_ok)
    body_html = EMBED_PLACEHOLDER_RE.sub(lambda m: "\n" + html.escape(m.group(1).strip()) + "\n", body_html)
    body_html = PLAIN_EMBED_URL_RE.sub(lambda m: "\n" + html.escape(m.group(1).strip()) + "\n", body_html)
    body_html = convert_embed_urls(body_html)
    body_html = re.sub(r"<p>\s*</p>", "", body_html)
    body_html = re.sub(r"\n{3,}", "\n\n", body_html)
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
        print(f"[PUBLISHER v93.10] Upload media non riuscito: status={res.status_code} body={res.text[:300]}", flush=True)
    except Exception as exc:
        print(f"[PUBLISHER v93.10] Upload media fallito: {image_url} | {exc}", flush=True)
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
    sig = story_signature(article)
    duplicate = existing_story_duplicate(history, sig)
    if duplicate:
        return {"source_url": url, "title_it": title, "status": "already_published", "reason": "semantic_story_duplicate", "story_signature": sig, "duplicate_of": duplicate.get("source_url"), "wp_post_id": duplicate.get("wp_post_id")}

    cleaned_body = clean_body_for_wordpress(str(article.get("body_html") or ""), wp_ok=wp_ok)
    content = append_source(cleaned_body, source, url)
    image_url = candidate_featured_image(article)
    categories = resolve_category_ids(str(article.get("category_hint") or "")) if wp_ok else []
    payload: dict[str, Any] = {
        "title": title,
        "content": content,
        "status": POST_STATUS,
        "categories": categories,
        "excerpt": str(article.get("excerpt_it") or "")[:500],
        "meta": {"original_url": url, "owtv_source": source, "owtv_pipeline": PUBLISHER_VERSION},
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
        return {"source_url": url, "title_it": title, "status": "dry_run" if DRY_RUN else "wp_not_ready", "wp_ready": wp_ok, "payload_preview": {k: v for k, v in payload.items() if k != "content"}, "content_chars": len(content), "image_url": image_url, "media_id": media_id}

    res = wp_request("post", wp_posts_url(), json=payload, auth=wp_auth())
    if res.status_code not in {200, 201}:
        return {"source_url": url, "title_it": title, "status": "publish_error", "error": f"WP post failed {res.status_code}: {res.text[:600]}"}
    data = res.json()
    post_id = int(data.get("id"))
    post_link = data.get("link") or ""
    history[key] = {"source_url": url, "title_it": title, "wp_post_id": post_id, "wp_link": post_link, "published_at": utc_now(), "status": POST_STATUS, "source": source, "story_signature": story_signature(article)}
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLISHED_DIR / f"v93_news_{review_slug}.html").write_text(content, encoding="utf-8")
    return {"source_url": url, "title_it": title, "status": "published", "wp_post_id": post_id, "wp_link": post_link, "featured_media": media_id, "categories": categories}


def run_publisher(alfred_result: dict[str, Any] | None = None) -> dict[str, Any]:
    alfred = alfred_result if isinstance(alfred_result, dict) else load_json(ALFRED_REVIEW_FILE, {})
    all_articles = alfred.get("approved_articles", []) if isinstance(alfred, dict) else []
    if not isinstance(all_articles, list):
        all_articles = []
    valid_articles = [article for article in all_articles if isinstance(article, dict)]
    approved_total = len(valid_articles)
    articles = valid_articles[:MAX_POSTS_PER_RUN]
    overflow_articles = valid_articles[MAX_POSTS_PER_RUN:]
    wp_ok, wp_reason = wp_ready()
    history = load_json(PUBLISHER_HISTORY_FILE, {})
    if not isinstance(history, dict):
        history = {}

    print(f"[PUBLISHER v93.40] Avvio pubblicazione | approved_total={approved_total} attempted={len(articles)} max={MAX_POSTS_PER_RUN} wp_ok={wp_ok} dry_run={DRY_RUN}", flush=True)
    results = [publish_article(article, history, wp_ok) for article in articles if isinstance(article, dict)]
    capacity_skipped = [
        {
            "source_url": str(article.get("source_url") or ""),
            "title_it": str(article.get("title_it") or ""),
            "status": "skipped_capacity",
            "reason": f"publisher_max_posts_per_run:{MAX_POSTS_PER_RUN}",
        }
        for article in overflow_articles
    ]
    results_for_audit = results + capacity_skipped
    if not DRY_RUN and wp_ok:
        write_json(PUBLISHER_HISTORY_FILE, history)

    result = {
        "agent": "Publisher",
        "version": PUBLISHER_VERSION,
        "generated_at": utc_now(),
        "mode": "wordpress_publisher_mixed_embed_blocks",
        "input": {"alfred_version": alfred.get("version") if isinstance(alfred, dict) else None, "approved_articles": approved_total, "attempted_articles": len(articles), "max_posts_per_run": MAX_POSTS_PER_RUN, "capacity_skipped": len(capacity_skipped)},
        "wp": {"ready": wp_ok, "reason": wp_reason, "post_status": POST_STATUS, "dry_run": DRY_RUN},
        "results": results,
        "skipped_approved_articles": capacity_skipped,
        "skipped_approved_articles": capacity_skipped,
        "skipped_approved_articles": capacity_skipped,
        "handoff": {
            "published": sum(1 for r in results if r.get("status") == "published"),
            "already_published": sum(1 for r in results if r.get("status") == "already_published"),
            "dry_run": sum(1 for r in results if r.get("status") == "dry_run"),
            "wp_not_ready": sum(1 for r in results if r.get("status") == "wp_not_ready"),
            "errors": sum(1 for r in results if r.get("status") == "publish_error"),
            "skipped_capacity": len(capacity_skipped),
            "approved_not_attempted": len(capacity_skipped),
            "approved_accounted_for": len(results_for_audit),
            "skipped_capacity": len(capacity_skipped),
            "approved_not_attempted": len(capacity_skipped),
            "approved_accounted_for": len(results_for_audit),
            "skipped_capacity": len(capacity_skipped),
            "approved_not_attempted": len(capacity_skipped),
            "approved_accounted_for": len(results_for_audit),
        },
        "policy": {"source_attribution": True, "strip_inline_image_placeholders": True, "plain_youtube_urls_for_wordpress_oembed": True, "plain_instagram_urls_for_wordpress_oembed": True, "social_embed_shortcode_blocks": True, "normalized_embed_dedupe": True, "semantic_story_dedupe": True, "featured_image_source": "meta.featured_image_or_first_placeholder", "idempotency": "state/newsroom/publisher_history.json by source_url"},
    }
    write_json(ARTIFACT_PUBLISHER_FILE, result)
    write_json(PUBLISHER_STATUS_FILE, result)
    print("[PUBLISHER v93.40] Pubblicazione completata | published={published} already={already} dry={dry} wp_not_ready={wp_not_ready} errors={errors} skipped_capacity={skipped_capacity} accounted={accounted}/{approved}".format(published=result["handoff"]["published"], already=result["handoff"]["already_published"], dry=result["handoff"]["dry_run"], wp_not_ready=result["handoff"]["wp_not_ready"], errors=result["handoff"]["errors"], skipped_capacity=result["handoff"].get("skipped_capacity", 0), accounted=result["handoff"].get("approved_accounted_for", 0), approved=approved_total), flush=True)
    return result


if __name__ == "__main__":
    out = run_publisher()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
