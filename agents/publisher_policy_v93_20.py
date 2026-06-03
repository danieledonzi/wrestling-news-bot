from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agents import publisher_policy_v93_16 as previous

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
PUBLISHER_STATUS_FILE = NEWSROOM_STATE_DIR / "publisher_status_latest.json"
ARTIFACT_PUBLISHER_FILE = ARTIFACT_DIR / "publisher_result.json"
RETRY_QUEUE_FILE = NEWSROOM_STATE_DIR / "publish_retry_queue.json"

VERSION = "v93_20_1_publisher_retry_queue_recursion_fix"
RETRY_TTL_HOURS = 36
MAX_QUEUE_ITEMS = 30

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

WWE_PERSONAL_LEGAL_RE = re.compile(
    r"\b(wwe|raw|smackdown|nxt|ludwig\s+kaiser|bron\s+breakker|seth\s+rollins|roman\s+reigns|cody\s+rhodes|becky\s+lynch|iyo\s+sky|iyo\s+skye|liv\s+morgan|finn\s+b[áa]lor|chad\s+gable|gunther|bayley)\b",
    re.I,
)
LEGAL_RE = re.compile(r"\b(legal|lawsuit|court|arrest|arrested|case|charges|trial|sentenza|causa|legale|tribunale|accuse|processo)\b", re.I)
BUSINESS_LEGAL_RE = re.compile(r"\b(shareholder|azionist|tko|merger|acquisition|acquisizione|sec|investor|investitori|class action|antitrust|diritti tv|media rights)\b", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


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


def article_blob(article: dict[str, Any]) -> str:
    return " ".join(str(article.get(k) or "") for k in ["title_it", "source_title", "source_url", "excerpt_it", "category_hint"])


def fallback_category_names_for_hint(hint: str, article: dict[str, Any]) -> list[str]:
    normalized = str(hint or "").strip()
    blob = article_blob(article).lower()
    if normalized == "World" and any(x in blob for x in ["ratings", "ascolti", "viewership", "netflix", "tko", "media rights", "tv deal"]):
        return CATEGORY_PRIORITY["Business"]
    return CATEGORY_PRIORITY.get(normalized, [normalized or "World"])


def category_names_for_hint(hint: str, article: dict[str, Any]) -> list[str]:
    blob = article_blob(article)
    if LEGAL_RE.search(blob) and WWE_PERSONAL_LEGAL_RE.search(blob) and not BUSINESS_LEGAL_RE.search(blob):
        return ["WWE", "World"]
    return fallback_category_names_for_hint(hint, article)


def load_queue() -> list[dict[str, Any]]:
    raw = load_json(RETRY_QUEUE_FILE, {"items": []})
    items = raw.get("items", []) if isinstance(raw, dict) else []
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        added = parse_dt(entry.get("added_at")) or now
        if now - added <= timedelta(hours=int(entry.get("ttl_hours") or RETRY_TTL_HOURS)):
            article = entry.get("article") if isinstance(entry.get("article"), dict) else None
            if article:
                entry = dict(entry)
                entry["article"] = dict(article)
                out.append(entry)
    return out


def save_queue(items: list[dict[str, Any]]) -> None:
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        article = item.get("article") if isinstance(item.get("article"), dict) else {}
        key = source_key(article.get("source_url") or item.get("source_url") or "")
        if key:
            unique[key] = item
    ordered = sorted(unique.values(), key=lambda x: str(x.get("added_at") or ""))[-MAX_QUEUE_ITEMS:]
    write_json(RETRY_QUEUE_FILE, {"version": VERSION, "updated_at": utc_now(), "ttl_hours": RETRY_TTL_HOURS, "items": ordered})


def queue_entry(article: dict[str, Any], status: str, reason: str = "") -> dict[str, Any]:
    return {
        "source_url": article.get("source_url"),
        "title_it": article.get("title_it"),
        "added_at": article.get("retry_added_at") or utc_now(),
        "last_seen_at": utc_now(),
        "attempts": int(article.get("retry_attempts", 0) or 0) + 1,
        "last_status": status,
        "last_reason": reason,
        "ttl_hours": RETRY_TTL_HOURS,
        "article": article,
    }


def prepare_alfred_with_queue(alfred: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], set[str]]:
    queued = load_queue()
    queued_articles: list[dict[str, Any]] = []
    queued_keys: set[str] = set()
    for entry in queued:
        article = entry.get("article") if isinstance(entry.get("article"), dict) else None
        if not article:
            continue
        article = dict(article)
        article["from_publish_retry_queue"] = True
        article["retry_attempts"] = int(entry.get("attempts", 0) or 0)
        article["retry_added_at"] = entry.get("added_at")
        queued_articles.append(article)
        queued_keys.add(source_key(article.get("source_url") or ""))

    current_articles = alfred.get("approved_articles", []) if isinstance(alfred.get("approved_articles"), list) else []
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for article in queued_articles + [x for x in current_articles if isinstance(x, dict)]:
        key = source_key(article.get("source_url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(article)
    out = dict(alfred)
    out["approved_articles"] = merged
    out.setdefault("retry_queue", {})["injected"] = len(queued_articles)
    return out, queued, queued_keys


def update_queue_after_run(input_articles: list[dict[str, Any]], results: list[dict[str, Any]], previous_queue: list[dict[str, Any]]) -> dict[str, Any]:
    article_by_key = {source_key(a.get("source_url") or ""): a for a in input_articles if isinstance(a, dict)}
    result_by_key = {source_key(r.get("source_url") or ""): r for r in results if isinstance(r, dict)}
    next_entries: list[dict[str, Any]] = []
    resolved = 0
    retained = 0
    added = 0
    for key, article in article_by_key.items():
        result = result_by_key.get(key, {})
        status = str(result.get("status") or "")
        if status in {"published", "already_published", "dry_run"}:
            resolved += 1
            continue
        if status in {"wp_not_ready", "publish_error"}:
            next_entries.append(queue_entry(article, status, str(result.get("reason") or result.get("error") or "")))
            if article.get("from_publish_retry_queue"):
                retained += 1
            else:
                added += 1
    attempted = set(article_by_key)
    for entry in previous_queue:
        article = entry.get("article") if isinstance(entry.get("article"), dict) else {}
        key = source_key(article.get("source_url") or entry.get("source_url") or "")
        if key and key not in attempted:
            next_entries.append(entry)
    save_queue(next_entries)
    return {"added": added, "retained": retained, "resolved": resolved, "size": len(load_queue())}


def run_publisher(alfred_result: dict[str, Any] | None = None) -> dict[str, Any]:
    original_category = previous.category_names_for_hint
    previous.category_names_for_hint = category_names_for_hint
    try:
        alfred = alfred_result if isinstance(alfred_result, dict) else previous.base.load_json(previous.base.ALFRED_REVIEW_FILE, {})
        alfred_for_publish, old_queue, queued_keys = prepare_alfred_with_queue(alfred if isinstance(alfred, dict) else {})
        input_articles = [x for x in alfred_for_publish.get("approved_articles", []) if isinstance(x, dict)]
        result = previous.run_publisher(alfred_for_publish)
        queue_stats = update_queue_after_run(input_articles, result.get("results", []) if isinstance(result.get("results"), list) else [], old_queue)
    finally:
        previous.category_names_for_hint = original_category
    result["version"] = VERSION
    result.setdefault("policy", {})["publish_retry_queue"] = "state/newsroom/publish_retry_queue.json"
    result.setdefault("policy", {})["retry_queue_before_new_articles"] = True
    result.setdefault("policy", {})["personal_wwe_legal_cases_category"] = ["WWE", "World"]
    result["retry_queue"] = {"injected": len(queued_keys), **queue_stats}
    write_json(ARTIFACT_PUBLISHER_FILE, result)
    write_json(PUBLISHER_STATUS_FILE, result)
    print("[PUBLISHER v93.20] Retry queue | injected={injected} added={added} retained={retained} resolved={resolved} size={size}".format(injected=len(queued_keys), **queue_stats), flush=True)
    return result
