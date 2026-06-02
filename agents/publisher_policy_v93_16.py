from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from agents import publisher as base

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
PUBLISHER_STATUS_FILE = NEWSROOM_STATE_DIR / "publisher_status_latest.json"
ARTIFACT_PUBLISHER_FILE = ARTIFACT_DIR / "publisher_result.json"

VERSION = "v93_17_publisher_gutenberg_embed_blocks"

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

EMBED_LINE_RE = re.compile(
    r"(?m)^\s*(https?://(?:www\.)?(?:x\.com|twitter\.com|instagram\.com|youtube\.com|youtube-nocookie\.com|youtu\.be|tiktok\.com|threads\.net|facebook\.com|bsky\.app)/\S+)\s*$",
    re.I,
)


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
        return "instagram", "rich", "is-type-rich is-provider-instagram wp-block-embed-instagram"
    if host == "tiktok.com":
        return "tiktok", "rich", "is-type-rich is-provider-tiktok wp-block-embed-tiktok"
    if host == "facebook.com":
        return "facebook", "rich", "is-type-rich is-provider-facebook wp-block-embed-facebook"
    if host == "threads.net":
        return "threads", "rich", "is-type-rich is-provider-threads wp-block-embed-threads"
    if host == "bsky.app":
        return "bluesky", "rich", "is-type-rich is-provider-bluesky wp-block-embed-bluesky"
    return "", "rich", "is-type-rich"


def gutenberg_embed_block(url: str) -> str:
    clean_url = html.unescape(str(url or "").strip())
    provider, embed_type, classes = embed_provider(clean_url)
    json_attr = json.dumps({"url": clean_url, "type": embed_type, "providerNameSlug": provider, "responsive": True}, ensure_ascii=False, separators=(",", ":"))
    safe_url = html.escape(clean_url)
    return (
        f"<!-- wp:embed {json_attr} -->\n"
        f"<figure class=\"wp-block-embed {classes}\"><div class=\"wp-block-embed__wrapper\">\n"
        f"{safe_url}\n"
        f"</div></figure>\n"
        f"<!-- /wp:embed -->"
    )


def convert_plain_embed_urls_to_blocks(content: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return "\n" + gutenberg_embed_block(match.group(1)) + "\n"

    return EMBED_LINE_RE.sub(repl, content or "")


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
    write_json(ARTIFACT_PUBLISHER_FILE, result)
    write_json(PUBLISHER_STATUS_FILE, result)
    return result
