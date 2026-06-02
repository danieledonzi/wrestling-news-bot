from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agents import menzo as base

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

MENZO_DECISIONS_FILE = NEWSROOM_STATE_DIR / "menzo_decisions_latest.json"
V92_ALLOWED_URLS_FILE = NEWSROOM_STATE_DIR / "v92_allowed_news_urls.json"
ARTIFACT_DECISIONS_FILE = ARTIFACT_DIR / "menzo_decisions.json"
SOFTPOOL_FILE = NEWSROOM_STATE_DIR / "menzo_softpool.json"
HARD_SKIP_FILE = NEWSROOM_STATE_DIR / "menzo_hard_skips.json"

MENZO_VERSION = "v93_15_forced_priority_label_softpool"
VALID_LABELS = {"high", "medium", "low", "skip"}
LABEL_SCORE = {"high": 92, "medium": 72, "low": 48, "skip": 0}
SOFTPOOL_TTL_HOURS = int(os.getenv("V93_MENZO_SOFTPOOL_TTL_HOURS", "36"))
HARD_SKIP_TTL_HOURS = int(os.getenv("V93_MENZO_HARD_SKIP_TTL_HOURS", "168"))
MIN_SELECTED_SCORE = int(os.getenv("V93_MENZO_MIN_SELECTED_SCORE", "65"))
MAX_DATA_REPORTS = int(os.getenv("V93_MENZO_MAX_DATA_REPORTS_PER_RUN", "1"))


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


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def normalize_text(value: str) -> str:
    return base.normalize(value)


def priority_label_from_review(review: dict[str, Any]) -> str:
    label = str(review.get("priority_label") or "").strip().lower()
    if label in VALID_LABELS:
        return label
    try:
        numeric = int(review.get("priority", 0))
    except Exception:
        numeric = 0
    if numeric >= 80:
        return "high"
    if numeric >= 50:
        return "medium"
    if numeric > 0:
        return "medium" if numeric >= 2 else "low"
    return "skip"


def sort_item(item: dict[str, Any]) -> tuple[int, float, str]:
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    try:
        age = float(item.get("age_hours", 999999) or 999999)
    except Exception:
        age = 999999.0
    return score, -age, str(item.get("published") or "")


def load_softpool() -> list[dict[str, Any]]:
    raw = load_json(SOFTPOOL_FILE, {"items": []})
    items = raw.get("items", []) if isinstance(raw, dict) else []
    now = datetime.now(timezone.utc)
    active: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        added = parse_dt(item.get("softpool_added_at")) or now
        if now - added <= timedelta(hours=SOFTPOOL_TTL_HOURS):
            clone = dict(item)
            clone["from_softpool"] = True
            active.append(clone)
    return active


def augment_board_with_softpool(board: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(board or {})
    candidates = list(cloned.get("news_candidates_for_menzo", []) or [])
    seen = {source_key(x.get("url") or x.get("source_url") or "") for x in candidates if isinstance(x, dict)}
    added = 0
    for item in load_softpool():
        key = source_key(item.get("url") or item.get("source_url") or "")
        if key and key not in seen:
            candidates.append(item)
            seen.add(key)
            added += 1
    cloned["news_candidates_for_menzo"] = candidates
    cloned.setdefault("softpool", {})["injected_candidates"] = added
    return cloned


def normalize_ai_fields(result: dict[str, Any]) -> None:
    reviews = ((result.get("menzo_ai") or {}).get("reviews") or []) if isinstance(result.get("menzo_ai"), dict) else []
    review_by_id = {str(r.get("id")): r for r in reviews if isinstance(r, dict) and r.get("id")}
    for section in ["selected", "pending", "skipped"]:
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else review_by_id.get(str(item.get("ai_id")), {})
            if isinstance(review, dict) and review:
                label = priority_label_from_review(review)
                review["priority_label"] = label
                if str(review.get("duplicate_of") or "").strip() == str(item.get("ai_id")):
                    review["duplicate_of"] = ""
                    item.pop("duplicate_of", None)
                item["menzo_ai_review"] = review
                item["ai_priority_label"] = label
                item["ai_priority"] = LABEL_SCORE[label]
                det = int(item.get("deterministic_score", item.get("score", 0)) or 0)
                item["score"] = int(round(det * 0.55 + LABEL_SCORE[label] * 0.45))
            else:
                score = int(item.get("score", 0) or 0)
                item.setdefault("ai_priority_label", "high" if score >= 75 else ("medium" if score >= 60 else ("low" if score >= 45 else "skip")))


def rebuild_decisions(result: dict[str, Any]) -> None:
    all_items: list[dict[str, Any]] = []
    for section in ["selected", "pending", "skipped"]:
        all_items.extend([x for x in result.get(section, []) if isinstance(x, dict)])
    selected: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in all_items:
        label = str(item.get("ai_priority_label") or "").lower()
        score = int(item.get("score", 0) or 0)
        if item.get("article_type") == "duplicate" or item.get("duplicate_of"):
            item["decision"] = "skip"
            item["priority"] = "skip"
            skipped.append(item)
        elif label == "high" or score >= MIN_SELECTED_SCORE:
            item["decision"] = "selected"
            item["priority"] = "hard" if score >= 75 else "soft"
            selected.append(item)
        elif label == "medium" or 50 <= score < MIN_SELECTED_SCORE:
            item["decision"] = "pending"
            item["priority"] = "soft"
            pending.append(item)
        else:
            item["decision"] = "skip"
            item["priority"] = "skip"
            skipped.append(item)
    selected = sorted(selected, key=sort_item, reverse=True)
    pending = sorted(pending, key=sort_item, reverse=True)
    kept: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    data_count = 0
    for item in selected:
        if str(item.get("article_type")) == "data_report":
            data_count += 1
            if data_count > MAX_DATA_REPORTS:
                item = dict(item)
                item["decision"] = "pending"
                item["priority"] = "soft"
                item["reason"] = f"data_report_cap:{MAX_DATA_REPORTS}; {item.get('reason', '')}"
                moved.append(item)
                continue
        kept.append(item)
    result["selected"] = kept
    result["pending"] = sorted(pending + moved, key=sort_item, reverse=True)
    result["skipped"] = skipped
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in kept if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(kept), "pending": len(result["pending"]), "skipped": len(skipped)}


def save_softpool(result: dict[str, Any]) -> None:
    now = utc_now()
    previous = load_softpool()
    by_url: dict[str, dict[str, Any]] = {source_key(x.get("url") or x.get("source_url") or ""): x for x in previous if isinstance(x, dict)}
    for item in result.get("pending", []) if isinstance(result.get("pending"), list) else []:
        key = source_key(item.get("url") or item.get("source_url") or "")
        if not key:
            continue
        clone = dict(item)
        clone.setdefault("softpool_added_at", now)
        clone["last_seen_at"] = now
        clone["softpool_reason"] = "medium_or_borderline_candidate"
        by_url[key] = clone
    # Remove selected/skipped from softpool unless still pending.
    for section in ["selected", "skipped"]:
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            key = source_key(item.get("url") or item.get("source_url") or "")
            if key in by_url:
                by_url.pop(key, None)
    active = []
    now_dt = datetime.now(timezone.utc)
    for item in by_url.values():
        added = parse_dt(item.get("softpool_added_at")) or now_dt
        if now_dt - added <= timedelta(hours=SOFTPOOL_TTL_HOURS):
            active.append(item)
    write_json(SOFTPOOL_FILE, {"version": MENZO_VERSION, "updated_at": now, "ttl_hours": SOFTPOOL_TTL_HOURS, "items": sorted(active, key=sort_item, reverse=True)})


def save_hard_skips(result: dict[str, Any]) -> None:
    now = utc_now()
    old = load_json(HARD_SKIP_FILE, {"items": []})
    items = old.get("items", []) if isinstance(old, dict) else []
    by_url: dict[str, dict[str, Any]] = {}
    now_dt = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict):
            continue
        added = parse_dt(item.get("added_at")) or now_dt
        if now_dt - added <= timedelta(hours=HARD_SKIP_TTL_HOURS):
            key = source_key(item.get("url") or item.get("source_url") or "")
            if key:
                by_url[key] = item
    for item in result.get("skipped", []) if isinstance(result.get("skipped"), list) else []:
        key = source_key(item.get("url") or item.get("source_url") or "")
        if not key:
            continue
        by_url[key] = {
            "url": item.get("url") or item.get("source_url"),
            "normalized_url": key,
            "title": item.get("title", ""),
            "reason": item.get("reason", "menzo_skip"),
            "article_type": item.get("article_type"),
            "added_at": now,
            "expires_after_hours": HARD_SKIP_TTL_HOURS,
        }
    write_json(HARD_SKIP_FILE, {"version": MENZO_VERSION, "updated_at": now, "ttl_hours": HARD_SKIP_TTL_HOURS, "items": list(by_url.values())})


def run_menzo(massy_board: dict[str, Any] | None = None) -> dict[str, Any]:
    board = augment_board_with_softpool(massy_board if isinstance(massy_board, dict) else base.load_json(base.MASSY_BOARD_FILE, {}))
    result = base.run_menzo(board)
    normalize_ai_fields(result)
    rebuild_decisions(result)
    result["version"] = MENZO_VERSION
    result["mode"] = "forced_priority_label_softpool"
    result.setdefault("policy", {})["priority_schema"] = "priority_label_high_medium_low_skip"
    result.setdefault("policy", {})["selected_requires_high_label_or_min_score"] = MIN_SELECTED_SCORE
    result.setdefault("policy", {})["softpool_enabled"] = True
    result.setdefault("policy", {})["menzo_hard_skips_exported_to_massy"] = True
    save_softpool(result)
    save_hard_skips(result)
    write_json(ARTIFACT_DECISIONS_FILE, result)
    write_json(MENZO_DECISIONS_FILE, result)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": MENZO_VERSION, "allowed_urls": result.get("allowed_urls_for_v92", [])})
    print(f"[MENZO v93.15] Decisione forzata | selected={len(result.get('selected', []))} pending={len(result.get('pending', []))} skipped={len(result.get('skipped', []))} softpool={len(load_softpool())}", flush=True)
    return result


if __name__ == "__main__":
    print(json.dumps(run_menzo().get("handoff", {}), ensure_ascii=False, indent=2))
