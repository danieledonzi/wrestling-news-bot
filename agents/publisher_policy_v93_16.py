from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from agents import publisher as base

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
PUBLISHER_STATUS_FILE = NEWSROOM_STATE_DIR / "publisher_status_latest.json"
ARTIFACT_PUBLISHER_FILE = ARTIFACT_DIR / "publisher_result.json"

VERSION = "v93_27_publisher_embed_dedupe_normalized"

CATEGORY_PRIORITY = {
    "Business": ["Business", "World"],
    "NXT": ["NXT", "WWE"],
    "TNA": ["TNA", "World"],
    "ROH": ["ROH", "AEW"],
    "AEW": ["AEW"],
    "WWE": ["WWE"],
    "World": ["World"],
    "Editoriali": ["Editoriali"],
}

EMBED_URL_PATTERN = r"https?://(?:www\.)?(?:x\.com|twitter\.com|instagram\.com|youtube\.com|youtube-nocookie\.com|youtu\.be|tiktok\.com|threads\.net|facebook\.com|bsky\.app)/\S+"
EMBED_LINE_RE = re.compile(rf"(?m)^\s*({EMBED_URL_PATTERN})\s*$", re.I)
P_ONLY_EMBED_RE = re.compile(rf"<p>\s*({EMBED_URL_PATTERN})\s*</p>", re.I)
P_START_EMBED_RE = re.compile(rf"<p>\s*({EMBED_URL_PATTERN})\s*(?:<br\s*/?>|\n|\r\n)+\s*(.*?)</p>", re.I | re.S)
P_URL_THEN_TEXT_RE = re.compile(rf"<p>\s*({EMBED_URL_PATTERN})\s+([^<].*?)</p>", re.I | re.S)
WP_EMBED_BLOCK_RE = re.compile(r"<!-- wp:embed [\s\S]*?<!-- /wp:embed -->", re.I)
EMBED_URL_ANY_RE = re.compile(rf"({EMBED_URL_PATTERN})", re.I)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def category_names_for_hint(hint: str, article: dict[str, Any]) -> list[str]:
    hint = str(hint or "").strip()
    title_blob = f"{article.get('title_it','')} {article.get('source_title','')} {article.get('source_url','')}`".lower()
    if hint == "World" and any(x in title_blob for x in ["ratings", "ascolti", "viewership", "netflix", "tko", "media rights", "tv deal"]):
        return CATEGORY_PRIORITY["Business"]
    return CATEGORY_PRIORITY.get(hint, [hint or "World"])


def resolve_category_ids_for_article(article: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for name in category_names_for_hint(str(article.get("category_hint") or ""), article):
        cid = base.resolve_category_id(name)
        if cid and cid not in out:
            out.append(cid)
    return out


def embed_provider(url: str) -> tuple[str, str, str]:
    host = urlparse(url).netloc.lower().replace("www.", "")
    if host in {"x.com", "twitter.com"}:
        return "twitter", "rich", "is-type-rich is-provider-twitter wp-block-embed-twitter"
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        return "youtube", "video", "is-type-video is-provider-youtube wp-block-embed-youtube"
    if host == "instagram.com":
        return "instagram", "rich", "is-type-rich is-provider-instagram wp-block-instagram"
    if host == "tiktok.com":
        return "tiktok", "rich", "is-type-rich is-provider-tiktok wp-block-embed-tiktok"
    if host == "facebook.com":
        return "facebook", "rich", "is-type-rich is-provider-facebook wp-block-embed-facebook"
    if host == "threads.net":
        return "threads", "rich", "is-type-rich is-provider-threads wp-block-embed-threads"
    if host == "bsky.app":
        return "bluesky", "rich", "is-type-rich is-provider-bluesky wp-block-embed-bluesky"
    return "", "rich", "is-type-rich"


def clean_url(url: str) -> str:
    return html.unescape(str(url or "").strip()).rstrip(".,;:)]}\u201d\u2019</p>")


def canonical_embed_key(url: str) -> str:
    clean = clean_url(url)
    parsed = urlparse(clean)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.strip("/")
    query = parse_qs(parsed.query)
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        video_id = ""
        if host == "youtu.be":
            video_id = path.split("/", 1)[0]
        elif path.startswith("watch"):
            video_id = (query.get("v") or [""])[0]
        elif path.startswith("embed/"):
            video_id = path.split("/", 1)[1].split("/", 1)[0]
        if video_id:
            return f"youtube:{video_id.lower()}"
    if host in {"x.com", "twitter.com"}:
        parts = [p for p in path.split("/") if p]
        if "status" in parts:
            i = parts.index("status")
            if i + 1 < len(parts):
                return f"twitter:{parts[i + 1].lower()}"
    return f"{host}:{path.lower()}"


def display_embed_url(url: str) -> str:
    clean = clean_url(url)
    parsed = urlparse(clean)
    host = parsed.netloc.lower().replace("www.", "")
    key = canonical_embed_key(clean)
    if key.startswith("youtube:"):
        video_id = key.split(":", 1)[1]
        return f"https://www.youtube.com/watch?v={video_id}"
    return clean


def gutenberg_embed_block(url: str) -> str:
    clean = display_embed_url(url)
    provider, embed_type, classes = embed_provider(clean)
    json_attr = json.dumps({"url": clean, "type": embed_type, "providerNameSlug": provider, "responsive": True}, ensure_ascii=False, separators=(",", ":"))
    safe_url = html.escape(clean)
    return (
        f"<!-- wp:embed {json_attr} -->\n"
        f"<figure class=\"wp-block-embed {classes}\"><div class=\"wp-block-embed__wrapper\">\n"
        f"{safe_url}\n"
        f"</div></figure>\n"
        f"<!-- /wp:embed -->"
    )


def remove_duplicate_embed_urls_preserve_first(text: str) -> str:
    seen: set[str] = set()

    def block_repl(match: re.Match[str]) -> str:
        block = match.group(0)
        found = EMBED_URL_ANY_RE.search(block)
        if not found:
            return block
        key = canonical_embed_key(found.group(1))
        if key in seen:
            return ""
        seen.add(key)
        return block

    text = WP_EMBED_BLOCK_RE.sub(block_repl, text)

    def p_repl(match: re.Match[str]) -> str:
        key = canonical_embed_key(match.group(1))
        if key in seen:
            return ""
        seen.add(key)
        return match.group(0)

    text = P_ONLY_EMBED_RE.sub(p_repl, text)
    text = EMBED_LINE_RE.sub(lambda m: "" if canonical_embed_key(m.group(1)) in seen else m.group(0), text)
    return text


def convert_plain_embed_urls_to_blocks(content: str) -> str:
    text = content or ""

    def repl_p_start(match: re.Match[str]) -> str:
        url = clean_url(match.group(1))
        rest = (match.group(2) or "").strip()
        block = "\n\n" + gutenberg_embed_block(url) + "\n\n"
        if rest:
            return block + f"<p>{rest}</p>"
        return block

    def repl_p_only(match: re.Match[str]) -> str:
        return "\n\n" + gutenberg_embed_block(match.group(1)) + "\n\n"

    def repl_line(match: re.Match[str]) -> str:
        return "\n\n" + gutenberg_embed_block(match.group(1)) + "\n\n"

    text = P_START_EMBED_RE.sub(repl_p_start, text)
    text = P_URL_THEN_TEXT_RE.sub(repl_p_start, text)
    text = P_ONLY_EMBED_RE.sub(repl_p_only, text)
    text = EMBED_LINE_RE.sub(repl_line, text)
    text = remove_duplicate_embed_urls_preserve_first(text)
    text = re.sub(r"(<!-- /wp:embed -->)\s*(<p>)", r"\1\n\n\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def run_publisher(alfred_result: dict[str, Any] | None = None) -> dict[str, Any]:
    original_resolve = base.resolve_category_ids
    original_clean = base.clean_body_for_wordpress

    def clean_with_gutenberg_embeds(body_html: str) -> str:
        cleaned = original_clean(body_html)
        return convert_plain_embed_urls_to_blocks(cleaned)

    base.clean_body_for_wordpress = clean_with_gutenberg_embeds
    try:
        alfred = alfred_result if isinstance(alfred_result, dict) else base.load_json(base.ALFRED_REVIEW_FILE, {})
        articles = alfred.get("approved_articles", []) if isinstance(alfred, dict) else []
        if isinstance(articles, list):
            for article in articles:
                if isinstance(article, dict):
                    article["publisher_category_names"] = category_names_for_hint(str(article.get("category_hint") or ""), article)
        original_publish = base.publish_article

        def patched_publish(article: dict[str, Any], history: dict[str, Any], wp_ok: bool) -> dict[str, Any]:
            if wp_ok:
                article["_forced_category_ids"] = resolve_category_ids_for_article(article)
            result = original_publish(article, history, wp_ok)
            if article.get("_forced_category_ids") and result.get("status") in {"published", "dry_run", "wp_not_ready"}:
                result["category_names_priority"] = article.get("publisher_category_names")
            return result

        holder: dict[str, Any] = {"article": None}

        def contextual_publish(article: dict[str, Any], history: dict[str, Any], wp_ok: bool) -> dict[str, Any]:
            holder["article"] = article
            try:
                return patched_publish(article, history, wp_ok)
            finally:
                holder["article"] = None

        def contextual_resolve(category_hint: str) -> list[int]:
            article = holder.get("article")
            if isinstance(article, dict) and article.get("_forced_category_ids"):
                return list(article.get("_forced_category_ids") or [])
            return original_resolve(category_hint)

        base.resolve_category_ids = contextual_resolve
        base.publish_article = contextual_publish
        result = base.run_publisher(alfred)
    finally:
        base.resolve_category_ids = original_resolve
        base.clean_body_for_wordpress = original_clean
        if "original_publish" in locals():
            base.publish_article = original_publish
    result["version"] = VERSION
    result.setdefault("policy", {})["category_priority"] = CATEGORY_PRIORITY
    result.setdefault("policy", {})["business_preferred_over_world_for_data_reports"] = True
    result.setdefault("policy", {})["plain_social_urls_rendered_as_gutenberg_embed_blocks"] = True
    result.setdefault("policy", {})["paragraph_wrapped_social_urls_rendered_as_gutenberg_embed_blocks"] = True
    result.setdefault("policy", {})["duplicate_trailing_embed_urls_removed_preserve_first"] = True
    result.setdefault("policy", {})["youtube_watch_and_embed_urls_deduped_as_same_video"] = True
    result.setdefault("policy", {})["post_embed_spacing_enforced"] = True
    write_json(ARTIFACT_PUBLISHER_FILE, result)
    write_json(PUBLISHER_STATUS_FILE, result)
    return result
