from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents import publisher as base

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
PUBLISHER_STATUS_FILE = NEWSROOM_STATE_DIR / "publisher_status_latest.json"
ARTIFACT_PUBLISHER_FILE = ARTIFACT_DIR / "publisher_result.json"

VERSION = "v93_16_publisher_category_priority"

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


def run_publisher(alfred_result: dict[str, Any] | None = None) -> dict[str, Any]:
    original_resolve = base.resolve_category_ids

    def patched_resolve(category_hint: str) -> list[int]:
        return original_resolve(category_hint)

    base.resolve_category_ids = patched_resolve
    try:
        alfred = alfred_result if isinstance(alfred_result, dict) else base.load_json(base.ALFRED_REVIEW_FILE, {})
        articles = alfred.get("approved_articles", []) if isinstance(alfred, dict) else []
        if isinstance(articles, list):
            for article in articles:
                if isinstance(article, dict):
                    article["publisher_category_names"] = category_names_for_hint(str(article.get("category_hint") or ""), article)
        # Monkey-patch publish_article instead of the global category resolver so it can see the article context.
        original_publish = base.publish_article

        def patched_publish(article: dict[str, Any], history: dict[str, Any], wp_ok: bool) -> dict[str, Any]:
            if wp_ok:
                article["_forced_category_ids"] = resolve_category_ids_for_article(article)
            result = original_publish(article, history, wp_ok)
            if article.get("_forced_category_ids") and result.get("status") in {"published", "dry_run", "wp_not_ready"}:
                result["category_names_priority"] = article.get("publisher_category_names")
            return result

        # Patch base.resolve_category_ids to use the ids precomputed on the current article via a small holder.
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
        if "original_publish" in locals():
            base.publish_article = original_publish
    result["version"] = VERSION
    result.setdefault("policy", {})["category_priority"] = CATEGORY_PRIORITY
    result.setdefault("policy", {})["business_preferred_over_world_for_data_reports"] = True
    write_json(ARTIFACT_PUBLISHER_FILE, result)
    write_json(PUBLISHER_STATUS_FILE, result)
    return result
