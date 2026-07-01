from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agents.gemini_ledger import record_gemini_event

from agents import menzo as base
from agents.story_dedupe_v93_32 import (
    build_generalized_fingerprint,
    dedupe_within_batch,
    find_duplicate_by_fingerprint,
    is_source_opinion,
    load_story_fingerprints,
    load_story_footprints,
    remember_fingerprints,
    remember_footprints,
    remember_stories,
    story_footprint,
    story_signature,
)

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

MENZO_DECISIONS_FILE = NEWSROOM_STATE_DIR / "menzo_decisions_latest.json"
V92_ALLOWED_URLS_FILE = NEWSROOM_STATE_DIR / "v92_allowed_news_urls.json"
ARTIFACT_DECISIONS_FILE = ARTIFACT_DIR / "menzo_decisions.json"
SOFTPOOL_FILE = NEWSROOM_STATE_DIR / "menzo_softpool.json"
HARD_SKIP_FILE = NEWSROOM_STATE_DIR / "menzo_hard_skips.json"

MENZO_VERSION = "v95.5_cross_run_story_novelty_gate"
VALID_LABELS = {"high", "medium", "low", "skip"}
LABEL_SCORE = {"high": 92, "medium": 72, "low": 48, "skip": 0}
SOFTPOOL_TTL_HOURS = int(os.getenv("V93_MENZO_SOFTPOOL_TTL_HOURS", "36"))
SOFTNEWS_TTL_HOURS = int(os.getenv("V93_MENZO_SOFTNEWS_TTL_HOURS", "6"))
SOFTPOOL_MAX_DEFERRALS = int(os.getenv("OWTV_SOFTPOOL_MAX_DEFERRALS", "4"))
SOFTPOOL_OUTRANKED_DEFERRALS = int(os.getenv("OWTV_SOFTPOOL_OUTRANKED_DEFERRALS", "3"))
DAILY_NEWS_TARGET = max(1, int(os.getenv("OWTV_DAILY_NEWS_TARGET", "30")))
HARD_SKIP_TTL_HOURS = int(os.getenv("V93_MENZO_HARD_SKIP_TTL_HOURS", "168"))
MIN_SELECTED_SCORE = int(os.getenv("V93_MENZO_MIN_SELECTED_SCORE", "65"))
MIN_SOFTPOOL_SCORE = int(os.getenv("V93_MENZO_MIN_SOFTPOOL_SCORE", "55"))
MAX_DATA_REPORTS = int(os.getenv("V93_MENZO_MAX_DATA_REPORTS_PER_RUN", "1"))
MAX_SELECTED_THIS_RUN = int(os.getenv("V93_MENZO_MAX_SELECTED_THIS_RUN", "7"))

EXCLUDED_SOFTPOOL_TYPES = {"low_value", "duplicate", "external_sports_reaction"}

# v95.5_cross_run_story_novelty_gate
MENZO_CROSS_RUN_NOVELTY_GATE_ENABLED = os.getenv("MENZO_CROSS_RUN_NOVELTY_GATE_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
MENZO_CROSS_RUN_NOVELTY_LOOKBACK_HOURS = int(os.getenv("MENZO_CROSS_RUN_NOVELTY_LOOKBACK_HOURS", "72"))
MENZO_CROSS_RUN_NOVELTY_MIN_SCORE = float(os.getenv("MENZO_CROSS_RUN_NOVELTY_MIN_SCORE", "0.62"))
MENZO_CROSS_RUN_NOVELTY_AI_ENABLED = os.getenv("MENZO_CROSS_RUN_NOVELTY_AI_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
MENZO_CROSS_RUN_NOVELTY_AI_MODEL = os.getenv("MENZO_CROSS_RUN_NOVELTY_AI_MODEL", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"
MASTER_LOG_FILE = NEWSROOM_STATE_DIR / "master_log.jsonl"


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


def brand_rank(item: dict[str, Any]) -> int:
    text = " ".join(str(item.get(k) or "") for k in ["category_hint", "title", "summary", "reason", "source", "url", "source_url"]).lower()
    if "wwe" in text or "smackdown" in text or "raw" in text:
        return 100
    if "nxt" in text:
        return 92
    if "aew" in text or "dynamite" in text or "collision" in text:
        return 90
    if "tna" in text or "impact" in text or "slammiversary" in text:
        return 72
    if "roh" in text or "cmll" in text or "stardom" in text:
        return 68
    if "ovw" in text or "ohio valley" in text:
        return 25
    if "indie" in text or "independent" in text:
        return 20
    return 40


def is_medical_return_story(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(k) or "") for k in ["title", "summary", "reason", "article_type", "url", "source_url"]).lower()
    return any(x in text for x in ["medical emergency", "medically cleared", "cleared to return", "medical return", "emergenza medica", "rientro", "ritorno sul ring"])


def apply_medical_brand_policy(result: dict[str, Any]) -> None:
    moved: list[dict[str, Any]] = []
    for section in ["selected", "pending"]:
        kept: list[dict[str, Any]] = []
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            if is_medical_return_story(item) and brand_rank(item) < 80:
                item = dict(item)
                item["decision"] = "skip"
                item["priority"] = "skip"
                item["article_type"] = "low_value"
                item["reason"] = "skip:medical_return_non_major_brand; " + str(item.get("reason") or "")
                item.setdefault("menzo_policy", {})["medical_return_major_brands_only"] = True
                moved.append(item)
            else:
                kept.append(item)
        result[section] = kept
    result.setdefault("skipped", []).extend(moved)
    result.setdefault("postprocess", {})["medical_return_non_major_brand_skipped"] = len(moved)


def sort_item(item: dict[str, Any]) -> tuple[int, int, float, str]:
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    try:
        age = float(item.get("age_hours", 999999) or 999999)
    except Exception:
        age = 999999.0
    # Brand importance is a tie-breaker after score: at equal or near-equal editorial value,
    # TNA/ROH outrank OVW/indie, and WWE/NXT/AEW outrank all.
    return score, brand_rank(item), -age, str(item.get("published") or "")


def item_ttl_hours(item: dict[str, Any]) -> int:
    if str(item.get("article_type")) == "soft_news":
        return SOFTNEWS_TTL_HOURS
    return SOFTPOOL_TTL_HOURS


def load_softpool() -> list[dict[str, Any]]:
    raw = load_json(SOFTPOOL_FILE, {"items": []})
    items = raw.get("items", []) if isinstance(raw, dict) else []
    now = datetime.now(timezone.utc)
    active: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        added = parse_dt(item.get("softpool_added_at")) or now
        ttl = int(item.get("softpool_ttl_hours") or item_ttl_hours(item))
        if now - added <= timedelta(hours=ttl) and is_softpool_eligible(item):
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



MAJOR_HARD_TERMS = {
    "breaking", "death", "passes away", "major injury", "injury", "injured", "title change",
    "new champion", "championship", "signs", "signing", "released", "release", "fired",
    "returns", "returning", "major return", "debut", "arrested", "lawsuit", "media rights", "tv deal",
}


def publisher_history_file() -> Path:
    return NEWSROOM_STATE_DIR / "publisher_history.json"


def published_today_count(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    raw = load_json(publisher_history_file(), {})
    records = raw.values() if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    count = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "publish").lower() not in {"publish", "published"}:
            continue
        dt = parse_dt(item.get("published_at") or item.get("updated_at") or item.get("created_at"))
        if dt and now - dt <= timedelta(hours=24):
            count += 1
    return count


def dynamic_soft_threshold(base_threshold: int = MIN_SELECTED_SCORE, published_count: int | None = None) -> tuple[int, dict[str, Any]]:
    count = published_today_count() if published_count is None else max(0, int(published_count))
    percent = count / DAILY_NEWS_TARGET
    if percent < 0.40:
        multiplier = 1.0
    elif percent < 0.70:
        multiplier = 1.1
    elif percent < 0.90:
        multiplier = 1.2
    elif percent <= 1.0:
        multiplier = 1.25
    else:
        multiplier = float("inf")
    threshold = 101 if multiplier == float("inf") else int(round(base_threshold * multiplier))
    meta = {
        "daily_news_target": DAILY_NEWS_TARGET,
        "published_today_count": count,
        "published_today_percent": round(percent, 4),
        "dynamic_soft_threshold": threshold,
        "dynamic_soft_threshold_multiplier": "hard_only" if multiplier == float("inf") else multiplier,
    }
    return threshold, meta


def is_major_hard_news(item: dict[str, Any]) -> bool:
    score = int(item.get("score", 0) or 0)
    label = str(item.get("ai_priority_label") or "").lower()
    article_type = str(item.get("article_type") or "").lower()
    text = normalize_text(" ".join(str(item.get(k) or "") for k in ["title", "summary", "reason", "article_type", "category_hint"])).lower()
    has_major_term = any(term in text for term in MAJOR_HARD_TERMS)
    return article_type in {"hard_news", "business_legal"} and (score >= 75 or label == "high") and has_major_term


def softpool_age_hours(item: dict[str, Any], now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    added = parse_dt(item.get("softpool_added_at")) or parse_dt(item.get("first_seen_at")) or now
    return max(0.0, (now - added).total_seconds() / 3600.0)


def softpool_deferrals(item: dict[str, Any]) -> int:
    try:
        return int(item.get("softpool_deferrals", item.get("deferrals", 0)) or 0)
    except Exception:
        return 0


def apply_softpool_decay(result: dict[str, Any]) -> None:
    expired: list[dict[str, Any]] = []
    outranked: list[dict[str, Any]] = []
    for section in ["selected", "pending"]:
        kept: list[dict[str, Any]] = []
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            if item.get("from_softpool"):
                item["softpool_age_hours"] = round(softpool_age_hours(item), 3)
                item["softpool_deferrals"] = softpool_deferrals(item)
                if item["softpool_age_hours"] > SOFTNEWS_TTL_HOURS:
                    item = dict(item, decision="skip", priority="skip", reason="softpool_expired_not_fresh")
                    item.setdefault("menzo_policy", {})["softpool_expired_not_fresh"] = True
                    expired.append(item); continue
                if item["softpool_deferrals"] >= SOFTPOOL_OUTRANKED_DEFERRALS:
                    item = dict(item, decision="skip", priority="skip", reason="softpool_repeatedly_outranked")
                    item.setdefault("menzo_policy", {})["softpool_repeatedly_outranked"] = True
                    outranked.append(item); continue
            kept.append(item)
        result[section] = kept
    result.setdefault("skipped", []).extend(expired + outranked)
    pp = result.setdefault("postprocess", {})
    pp["softpool_expired_not_fresh"] = len(expired)
    pp["softpool_repeatedly_outranked"] = len(outranked)


def apply_dynamic_editorial_budget(result: dict[str, Any], published_count: int | None = None) -> None:
    threshold, meta = dynamic_soft_threshold(MIN_SELECTED_SCORE, published_count)
    selected = [dict(x) for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [dict(x) for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    new_selected: list[dict[str, Any]] = []
    new_pending: list[dict[str, Any]] = pending
    threshold_skips = 0
    for item in selected:
        score = int(item.get("score", 0) or 0)
        is_hard = is_major_hard_news(item)
        is_soft = str(item.get("priority") or "").lower() == "soft" or str(item.get("article_type") or "").lower() in {"soft_news", "strategic_discussion", "data_report", "pending_followup", "pending_review"}
        item.setdefault("menzo_policy", {}).update(meta)
        if meta["published_today_percent"] > 1.0 and not is_hard:
            item["decision"] = "pending" if is_softpool_eligible(item) else "skip"
            item["reason"] = "skipped_by_dynamic_threshold:over_daily_target_hard_only; " + str(item.get("reason") or "")
            threshold_skips += 1
            (new_pending if item["decision"] == "pending" else skipped).append(item)
        elif is_soft and not is_hard and score < threshold:
            item["decision"] = "pending" if is_softpool_eligible(item) else "skip"
            item["reason"] = f"skipped_by_dynamic_threshold:{score}<{threshold}; " + str(item.get("reason") or "")
            threshold_skips += 1
            (new_pending if item["decision"] == "pending" else skipped).append(item)
        else:
            item["decision"] = "selected"
            new_selected.append(item)
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = skipped
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in result["selected"] if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(result["selected"]), "pending": len(result["pending"]), "skipped": len(result["skipped"])}
    result["daily_policy"] = {**(result.get("daily_policy") if isinstance(result.get("daily_policy"), dict) else {}), **meta, "not_a_hard_cap": True}
    pp = result.setdefault("postprocess", {})
    pp.update(meta)
    pp["skipped_by_dynamic_threshold"] = threshold_skips
    pp["gemini_calls_avoided_by_threshold"] = threshold_skips

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


def is_softpool_eligible(item: dict[str, Any]) -> bool:
    label = str(item.get("ai_priority_label") or "").lower()
    article_type = str(item.get("article_type") or "")
    score = int(item.get("score", 0) or 0)
    if article_type in EXCLUDED_SOFTPOOL_TYPES:
        return False
    if label != "medium":
        return False
    if score < MIN_SOFTPOOL_SCORE:
        return False
    if article_type == "data_report" and score < 60:
        return False
    return True


def apply_story_dedupe_to_result(result: dict[str, Any]) -> None:
    selected = [x for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    candidates = selected + pending
    kept, dupes = dedupe_within_batch(candidates)
    selected_urls = {source_key(x.get("url") or x.get("source_url") or "") for x in selected if isinstance(x, dict)}
    new_selected: list[dict[str, Any]] = []
    new_pending: list[dict[str, Any]] = []
    for item in kept:
        key = source_key(item.get("url") or item.get("source_url") or "")
        if key in selected_urls or str(item.get("ai_priority_label") or "").lower() == "high":
            item["decision"] = "selected"
            new_selected.append(item)
        else:
            item["decision"] = "pending"
            new_pending.append(item)
    for dupe in dupes:
        dupe["decision"] = "skip"
        dupe["priority"] = "skip"
        dupe["article_type"] = dupe.get("article_type") or "duplicate"
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = skipped + dupes
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in result["selected"] if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(result["selected"]), "pending": len(result["pending"]), "skipped": len(result["skipped"])}
    result.setdefault("postprocess", {})["story_duplicates_skipped"] = len(dupes)


def apply_source_opinion_policy(result: dict[str, Any]) -> None:
    moved: list[dict[str, Any]] = []
    for section in ["selected", "pending"]:
        kept: list[dict[str, Any]] = []
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            if is_source_opinion(item):
                item = dict(item)
                item["decision"] = "skip"
                item["priority"] = "skip"
                item["article_type"] = "source_opinion"
                item["reason"] = "skip:source_opinion_or_editorial_commentary"
                item.setdefault("menzo_policy", {})["source_opinion_not_publishable_as_news"] = True
                moved.append(item)
            else:
                kept.append(item)
        result[section] = kept
    result.setdefault("skipped", []).extend(moved)
    result.setdefault("postprocess", {})["source_opinion_skipped"] = len(moved)


def apply_story_footprint_policy(result: dict[str, Any]) -> None:
    selected = [x for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    kept, dupes = dedupe_within_batch(selected + pending)
    original_selected = {source_key(x.get("url") or x.get("source_url") or "") for x in selected}
    new_selected: list[dict[str, Any]] = []
    new_pending: list[dict[str, Any]] = []
    for item in kept:
        sig = story_signature(item)
        if sig:
            item["story_signature"] = sig
        item["story_footprint"] = story_footprint(item)
        key = source_key(item.get("url") or item.get("source_url") or "")
        if key in original_selected or str(item.get("ai_priority_label") or "").lower() == "high":
            item["decision"] = "selected"
            new_selected.append(item)
        else:
            item["decision"] = "pending"
            new_pending.append(item)
    for dupe in dupes:
        dupe = dict(dupe)
        dupe["decision"] = "skip"
        dupe["priority"] = "skip"
        dupe["article_type"] = "duplicate"
        dupe.setdefault("menzo_policy", {})["duplicate_by_story_footprint"] = True
        skipped.append(dupe)
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = skipped
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in result["selected"] if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(result["selected"]), "pending": len(result["pending"]), "skipped": len(result["skipped"])}
    result.setdefault("postprocess", {})["story_footprint_duplicates_skipped"] = len(dupes)


def ai_review_by_url(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    candidates = [x for x in result.get("candidates", []) if isinstance(x, dict)] if isinstance(result.get("candidates"), list) else []
    for item in result.get("selected", []) + result.get("pending", []) + result.get("skipped", []):
        if not isinstance(item, dict):
            continue
        url = source_key(item.get("url") or item.get("source_url") or "")
        review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
        if url and review:
            out[url] = review
    return out


def enforce_ai_skip_binding(result: dict[str, Any]) -> None:
    moved: list[dict[str, Any]] = []
    for section in ["selected", "pending"]:
        kept: list[dict[str, Any]] = []
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
            ai_decision = str(review.get("decision") or item.get("ai_decision") or "").lower()
            ai_priority = str(review.get("priority_label") or item.get("ai_priority_label") or "").lower()
            if ai_decision == "skip" or ai_priority == "skip":
                item = dict(item)
                item["decision"] = "skip"
                item["priority"] = "skip"
                item["article_type"] = item.get("article_type") or "ai_skip"
                item["reason"] = "skip:menzo_ai_binding; " + str(item.get("reason") or review.get("editorial_reason") or "")
                item.setdefault("menzo_policy", {})["ai_skip_is_binding"] = True
                moved.append(item)
            else:
                kept.append(item)
        result[section] = kept
    result.setdefault("skipped", []).extend(moved)
    result.setdefault("postprocess", {})["ai_skip_binding_moved"] = len(moved)


def apply_generalized_fingerprint_policy(result: dict[str, Any]) -> None:
    memory = load_story_fingerprints()
    selected = [x for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    new_selected: list[dict[str, Any]] = []
    new_pending: list[dict[str, Any]] = []
    dupes: list[dict[str, Any]] = []
    local_memory: list[dict[str, Any]] = list(memory)
    for item in sorted(selected + pending, key=sort_item, reverse=True):
        item = dict(item)
        item["story_fingerprint"] = build_generalized_fingerprint(item)
        duplicate, score = find_duplicate_by_fingerprint(item, local_memory)
        if duplicate:
            item["decision"] = "skip"
            item["priority"] = "skip"
            item["article_type"] = "duplicate"
            item["reason"] = f"skip:story_fingerprint_overlap:{score}"
            item["duplicate_of"] = duplicate.get("url") or duplicate.get("source_url")
            item["story_overlap_score"] = score
            item.setdefault("menzo_policy", {})["duplicate_by_generalized_story_fingerprint"] = True
            dupes.append(item)
            continue
        # Add the item to local memory immediately to dedupe within the same run.
        local_memory.append({"fingerprint": item["story_fingerprint"], "url": item.get("url") or item.get("source_url"), "title": item.get("title") or item.get("source_title")})
        if str(item.get("decision") or "").lower() == "pending":
            new_pending.append(item)
        else:
            item["decision"] = "selected"
            new_selected.append(item)
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = skipped + dupes
    result.setdefault("postprocess", {})["story_fingerprint_duplicates_skipped"] = len(dupes)


def enforce_selected_cap(result: dict[str, Any]) -> None:
    policy = result.get("daily_policy") if isinstance(result.get("daily_policy"), dict) else {}
    try:
        max_selected = max(int(policy.get("max_selected_this_run") or 0), MAX_SELECTED_THIS_RUN)
    except Exception:
        max_selected = MAX_SELECTED_THIS_RUN
    selected = sorted([x for x in result.get("selected", []) if isinstance(x, dict)], key=sort_item, reverse=True)
    overflow = selected[max_selected:]
    selected = selected[:max_selected]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)] + overflow
    for item in overflow:
        item["decision"] = "pending"
        item.setdefault("menzo_policy", {})["selected_cap_overflow_to_pending"] = True
    result["selected"] = selected
    result["pending"] = sorted(pending, key=sort_item, reverse=True)
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in selected if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(selected), "pending": len(result["pending"]), "skipped": len(result.get("skipped", []))}
    result.setdefault("postprocess", {})["selected_cap"] = max_selected
    result.setdefault("postprocess", {})["selected_overflow_to_pending"] = len(overflow)



MENZO_DUPLICATE_ARBITRATION_FIRST_MODEL = os.getenv("MENZO_DUPLICATE_ARBITRATION_FIRST_MODEL", "gemini-3.1-flash-lite").strip() or "gemini-3.1-flash-lite"
MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL = os.getenv("MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL", "gemini-3.5-flash").strip() or "gemini-3.5-flash"
MENZO_ENABLE_35_FOR_HIGH_AMBIGUITY = os.getenv("MENZO_ENABLE_35_FOR_HIGH_AMBIGUITY", "true").strip().lower() not in {"0", "false", "no", "off"}
MENZO_35_MIN_SCORE = int(os.getenv("MENZO_35_MIN_SCORE", "72"))
MENZO_35_REQUIRE_DUPLICATE_OR_SAME_STORY = os.getenv("MENZO_35_REQUIRE_DUPLICATE_OR_SAME_STORY", "true").strip().lower() not in {"0", "false", "no", "off"}
MENZO_MODEL_COOLDOWN_FAILURES: set[tuple[str, str]] = set()
AI_DEDUPE_MAX_CLUSTERS = 5
AI_DEDUPE_MAX_CANDIDATES = 4
AI_DEDUPE_MIN_OVERLAP = 0.46
RATINGS_TERMS = {"ratings", "ascolti", "viewership", "audience", "netflix"}
SHOW_TERMS = {"raw", "smackdown", "nxt", "dynamite", "collision", "impact"}
SOURCE_RELIABILITY = {"wrestlinginc": 92, "wrestling inc": 92, "fightful": 90, "pwinsider": 88, "f4wonline": 84, "ringside news": 78, "ringsidenews": 78}


def ai_dedupe_text(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    return " ".join(str(x or "") for x in [
        item.get("title"), item.get("source_title"), item.get("title_it"), item.get("summary"),
        item.get("excerpt"), item.get("excerpt_it"), item.get("category_hint"), item.get("source"),
        meta.get("title"), meta.get("source_title"), meta.get("description"),
    ])


def ai_dedupe_words(item: dict[str, Any]) -> set[str]:
    stop = {"wwe", "aew", "tna", "the", "and", "per", "con", "del", "della", "dopo", "during", "after", "news", "update", "aggiornamento"}
    return {w for w in re.findall(r"[a-z0-9àèéìòù']+", normalize_text(ai_dedupe_text(item)).lower()) if len(w) >= 3 and w not in stop}


def rating_show_key(item: dict[str, Any]) -> str:
    words = ai_dedupe_words(item)
    if not (words & RATINGS_TERMS):
        return ""
    shows = sorted(words & SHOW_TERMS)
    return shows[0] if shows else "unknown"


def deterministic_story_key(item: dict[str, Any]) -> str:
    text = normalize_text(ai_dedupe_text(item)).lower()
    if "tessa" in text and "blanchard" in text and any(x in text for x in ["lascia", "leave", "leaves", "release", "rilascio"]):
        return "tessa_blanchard_tna_departure"
    if ("iyo" in text or "io " in text) and "sky" in text and "queen of the ring" in text and any(x in text for x in ["final", "finale"]):
        return "iyo_sky_queen_of_the_ring_final"
    if "jacob" in text and "fatu" in text and "eric" in text and "andr" in text and any(x in text for x in ["splash", "aggredis", "attack", "brutal"]):
        return "jacob_fatu_eric_andre_raw_attack"
    return ""


def source_reliability_score(item: dict[str, Any]) -> int:
    source = str(item.get("source") or item.get("url") or item.get("source_url") or "").lower()
    for key, score in SOURCE_RELIABILITY.items():
        if key in source:
            return score
    return 70


def candidate_quality_score(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
    text = ai_dedupe_text(item)
    has_media = int(bool(item.get("has_image") or item.get("featured_image") or item.get("image_url") or int(item.get("embed_count") or 0)))
    quotes = text.count('"') + text.count("“") + text.count("”")
    clickbait_penalty = int(any(x in text.lower() for x in ["shocking", "you won't believe", "incredibile", "clamoroso"]))*20
    return (len(ai_dedupe_words(item)), source_reliability_score(item), has_media, quotes, -clickbait_penalty)


def lightweight_ai_record(item: dict[str, Any], item_id: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "title": item.get("title") or item.get("source_title") or item.get("title_it") or "",
        "source": item.get("source") or "",
        "url": item.get("url") or item.get("source_url") or "",
        "summary": item.get("summary") or item.get("excerpt") or item.get("excerpt_it") or "",
        "category_hint": item.get("category_hint") or "",
        "published_at": item.get("published_at") or item.get("published") or item.get("date") or "",
        "has_image": bool(item.get("has_image") or item.get("featured_image") or item.get("image_url")),
        "embed_count": int(item.get("embed_count") or 0),
        "score": item.get("score") or item.get("menzo_score") or 0,
    }


def build_ai_dedupe_prompt(records: list[dict[str, Any]]) -> str:
    return """You are Menzo's cross-source duplicate arbiter. Decide whether the NEW candidate repeats already-published or suspicious records, or has a truly new editorial angle.
Return ONLY valid JSON with this exact shape:
{
  "cluster_type": "same_story|same_core_fact_new_angle|different_story|uncertain",
  "decision": "skip_duplicate|pending_followup|selected|pending_review",
  "confidence": 0,
  "canonical_event_label": "",
  "reason": "",
  "suggested_followup_title_it": "",
  "angle_summary_it": ""
}
Rules:
- same_story + no meaningful new angle => decision skip_duplicate.
- same core fact but a useful different angle => pending_followup unless editorial value is clearly high; then selected.
- uncertain or low confidence => pending_review.
- Do not invent deterministic local rules. Judge only provided title, summary, source_url/source, event_key, excerpt/canonical_summary, and footprints/history.
- If follow-up, suggested_followup_title_it must not repeat the already-published core fact as the title angle.

Records:
""" + json.dumps(records, ensure_ascii=False, indent=2)


def build_ai_dedupe_second_pass_prompt(records: list[dict[str, Any]], history: dict[str, Any]) -> str:
    return build_ai_dedupe_prompt(records) + "\n\nSecond-pass context (publisher_history/story_footprints relevant to the suspected core fact):\n" + json.dumps(history, ensure_ascii=False, indent=2)


def needs_second_pass(ai_data: dict[str, Any] | None) -> bool:
    if not ai_data:
        return False
    try:
        confidence = int(ai_data.get("confidence", 0) or 0)
    except Exception:
        confidence = 0
    cluster_type = str(ai_data.get("cluster_type") or "").lower()
    return confidence < 75 or cluster_type in {"uncertain", "mixed_signals", "same_event_but_new_angle", "same_core_fact_new_angle"}



def _record_menzo_second_pass_avoided(reason: str, ledger_context: dict[str, Any], *, result: str = "gate") -> None:
    record_gemini_event(agent="Menzo", phase="duplicate_arbitration_second_pass", model=MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL, status="avoided", reason=reason, result=result, saved_gemini_call=True, **ledger_context)


def _record_score(record: dict[str, Any]) -> int:
    try:
        return int(record.get("score") or record.get("menzo_score") or 0)
    except Exception:
        return 0


def menzo_second_pass_gate(item: dict[str, Any], records: list[dict[str, Any]], ai_data: dict[str, Any] | None) -> tuple[bool, str]:
    if not MENZO_ENABLE_35_FOR_HIGH_AMBIGUITY:
        return False, "purpose_gate_not_met"
    if not needs_second_pass(ai_data):
        return False, "high_ambiguity_gate_not_met"
    if len(records) < 2:
        return False, "high_ambiguity_gate_not_met"
    if MENZO_35_REQUIRE_DUPLICATE_OR_SAME_STORY:
        cluster_type = str((ai_data or {}).get("cluster_type") or "").lower()
        if cluster_type not in {"same_story", "same_core_fact_new_angle", "uncertain", "mixed_signals", "same_event_but_new_angle"}:
            return False, "purpose_gate_not_met"
    candidates = [r for r in records if str(r.get("publisher_history_origin") or "candidate") != "published_or_memory"]
    if len(candidates) < 2 and not any(str(r.get("publisher_history_origin") or "") == "suspicious" for r in records):
        return False, "high_ambiguity_gate_not_met"
    cluster_score = max([_record_score(item)] + [_record_score(r) for r in records])
    if cluster_score < MENZO_35_MIN_SCORE:
        return False, "high_ambiguity_gate_not_met"
    return True, "high_ambiguity_duplicate_novelty_arbitration"

def relevant_history_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = set()
    for rec in records:
        tokens |= {w for w in re.findall(r"[a-z0-9àèéìòù']+", normalize_text(json.dumps(rec, ensure_ascii=False)).lower()) if len(w) >= 4}
    footprints = []
    for old in load_story_fingerprints()[:60]:
        blob = normalize_text(json.dumps(old, ensure_ascii=False)).lower()
        if sum(1 for t in tokens if t in blob) >= 2:
            footprints.append(old)
        if len(footprints) >= 8:
            break
    return {"story_footprints": footprints}


def _parse_gemini_json_text(text: str) -> dict[str, Any] | None:
    raw = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.I).strip()
    data = json.loads(raw)
    return data if isinstance(data, dict) else None


def _cooldown_key(model: str, ledger_context: dict[str, Any] | None) -> tuple[str, str]:
    ctx = ledger_context or {}
    title_or_cluster = str(ctx.get("cluster_id") or ctx.get("title") or ctx.get("url") or "unknown")[:240]
    return model, title_or_cluster


def _is_cooldown_error(text: str) -> bool:
    low = text.lower()
    return "503" in low or "high demand" in low or "resource_exhausted" in low or "unavailable" in low


def call_gemini_json_model(prompt: str, model: str, *, ledger_context: dict[str, Any] | None = None, phase: str = "duplicate_arbitration") -> tuple[dict[str, Any] | None, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if _cooldown_key(model, ledger_context) in MENZO_MODEL_COOLDOWN_FAILURES:
        record_gemini_event(agent="Menzo", phase=phase, model=model, status="avoided", reason="model_cooldown_after_failure", result="cooldown", saved_gemini_call=True, **(ledger_context or {}))
        return None, f"model_cooldown_after_failure:{model}"
    if not api_key:
        return None, "missing_api_key"
    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        data = _parse_gemini_json_text(getattr(response, "text", "") or "")
        event_reason = "ai_novelty_allow" if phase == "cross_run_novelty_gate" and data and str(data.get("decision") or "").lower() == "allow" else ("ai_no_novelty_skip" if phase == "cross_run_novelty_gate" and data and str(data.get("decision") or "").lower() == "skip" else ("ai_uncertain_pending" if phase == "cross_run_novelty_gate" else "ai_duplicate_arbitration"))
        record_gemini_event(agent="Menzo", phase=phase, model=model, status="called", reason=event_reason, result="valid_json" if data else "invalid_json", **(ledger_context or {}))
        return (data, model) if data else (None, f"invalid_json:{model}")
    except Exception as exc:
        err = str(exc)[:500]
        if _is_cooldown_error(err):
            MENZO_MODEL_COOLDOWN_FAILURES.add(_cooldown_key(model, ledger_context))
        record_gemini_event(agent="Menzo", phase=phase, model=model, status="failed", reason="ai_uncertain_pending" if phase == "cross_run_novelty_gate" else "ai_duplicate_arbitration", result=err, **(ledger_context or {}))
        return None, f"gemini_unavailable:{model}:{exc}"


def call_gemini_json(prompt: str) -> tuple[dict[str, Any] | None, str]:
    for model in [m.strip() for m in os.getenv("GEMINI_MODEL_CHAIN", "gemini-3.1-flash-lite,gemini-2.5-flash-lite").split(",") if m.strip()]:
        data, status = call_gemini_json_model(prompt, model)
        if data:
            return data, status
    return None, "empty_or_invalid_response"


def cross_run_text(item: dict[str, Any]) -> str:
    return normalize_text(" ".join(str(item.get(k) or "") for k in ["title", "source_title", "title_it", "summary", "excerpt", "reason", "category_hint", "event_key"])).lower()


def cross_run_tokens(item: dict[str, Any]) -> set[str]:
    stop = {"wwe", "aew", "tna", "roh", "nxt", "the", "and", "con", "per", "del", "della", "news", "rumor", "rumors", "report", "reports", "update", "aggiornamento", "possibile", "possible", "verso", "alla"}
    return {w for w in re.findall(r"[a-z0-9àèéìòù']+", cross_run_text(item)) if len(w) >= 3 and w not in stop}


def cross_run_entities(item: dict[str, Any]) -> set[str]:
    text = " ".join(str(item.get(k) or "") for k in ["title", "source_title", "title_it", "summary", "reason"])
    filler = {
        "a", "ad", "al", "alla", "allo", "anche", "and", "as", "back", "con", "contro", "del", "della",
        "dello", "di", "dopo", "for", "from", "in", "il", "la", "le", "lo", "new", "news", "on", "per",
        "possibile", "possible", "potrebbe", "report", "reports", "return", "ritorno", "rumor", "rumors",
        "the", "to", "update", "verso", "with",
    }
    known = {
        "big bill", "enzo amore", "cm punk", "roman reigns", "cody rhodes", "seth rollins", "mjf", "jon moxley",
        "wwe", "aew", "tna", "nxt", "roh", "njpw", "raw", "smackdown", "dynamite", "collision",
        "wrestlemania", "summerslam", "royal rumble", "all out", "full gear", "forbidden door",
    }
    low = normalize_text(text).lower()
    entities: set[str] = {e for e in known if re.search(rf"\b{re.escape(e)}\b", low)}
    for m in re.finditer(r"\b[A-Z][A-Za-zÀ-ÿ']+(?:\s+[A-Z][A-Za-zÀ-ÿ']+){0,2}\b", text):
        raw = m.group(0).strip()
        value = raw.lower()
        parts = value.split()
        if len(parts) > 1:
            kept = " ".join(p for p in parts if p not in filler)
            if len(kept.split()) >= 2 or kept in known:
                entities.add(kept)
            continue
        if value in filler:
            continue
        if m.start() == 0 and value not in known:
            continue
        entities.add(value)
    entities |= {m.group(0).lower() for m in re.finditer(r"\b(?:WWE|AEW|TNA|NXT|ROH|NJPW)\b", text)}
    return {e for e in entities if e and e not in filler}


def cross_run_actions(item: dict[str, Any]) -> set[str]:
    text = cross_run_text(item)
    groups = {
        "rumor": {"rumor", "rumors", "possible", "possibile", "potrebbe", "talk", "si parla", "verso"},
        "confirmed": {"confirmed", "confermato", "official", "ufficiale", "announced", "annunciato"},
        "contract_status_changed": {"leaves", "left", "lascia", "free agent", "scadenza", "contract", "contratto", "released", "rilasciato"},
        "signed": {"signed", "signs", "firma", "accordo"},
        "medical": {"injured", "injury", "infortunio", "cleared", "medico"},
        "creative": {"creative", "piani", "plans", "storyline", "match", "title", "stipulation", "stipulazione", "booked", "aggiunto", "removed"},
        "denial": {"denied", "smentita", "smentisce", "false"},
    }
    return {code for code, terms in groups.items() if any(term in text for term in terms)}


def cross_run_dates(item: dict[str, Any]) -> set[str]:
    text = cross_run_text(item)
    found = set(re.findall(r"\b(?:20\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)\b", text))
    found |= set(re.findall(r"\b(?:raw|smackdown|dynamite|collision|wrestlemania|summerslam|royal rumble|all out|full gear|forbidden door)\b", text))
    return found


def _history_dt(item: dict[str, Any]) -> datetime | None:
    return parse_dt(item.get("published_at") or item.get("updated_at") or item.get("created_at") or item.get("added_at") or item.get("timestamp") or item.get("published"))


def load_cross_run_story_history(lookback_hours: int | None = None) -> list[dict[str, Any]]:
    lookback_hours = lookback_hours or MENZO_CROSS_RUN_NOVELTY_LOOKBACK_HOURS
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    out: list[dict[str, Any]] = []
    raw = load_json(publisher_history_file(), {})
    records = raw.values() if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    for item in records:
        if isinstance(item, dict) and (_history_dt(item) or datetime.now(timezone.utc)) >= cutoff:
            out.append({**item, "cross_run_origin": "publisher_history"})
    for old in load_story_footprints():
        if isinstance(old, dict) and (_history_dt(old) or datetime.now(timezone.utc)) >= cutoff:
            out.append({**old, "cross_run_origin": "story_footprints"})
    if MASTER_LOG_FILE.exists():
        try:
            for line in MASTER_LOG_FILE.read_text(encoding="utf-8").splitlines()[-400:]:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict) and (_history_dt(item) or datetime.now(timezone.utc)) >= cutoff:
                    out.append({**item, "cross_run_origin": "master_log"})
        except Exception:
            pass
    return out


def cross_run_similarity(item: dict[str, Any], old: dict[str, Any]) -> float:
    if source_key(item.get("url") or item.get("source_url") or "") == source_key(old.get("url") or old.get("source_url") or ""):
        return 0.0
    a, b = cross_run_tokens(item), cross_run_tokens(old)
    token_score = len(a & b) / max(1, min(len(a), len(b)))
    ea, eb = cross_run_entities(item), cross_run_entities(old)
    entity_score = len(ea & eb) / max(1, min(len(ea), len(eb))) if ea and eb else 0.0
    action_score = 0.15 if cross_run_actions(item) & cross_run_actions(old) else 0.0
    brand_score = 0.12 if ({w for w in ["wwe", "aew", "tna", "nxt", "roh"] if w in cross_run_text(item)} & {w for w in ["wwe", "aew", "tna", "nxt", "roh"] if w in cross_run_text(old)}) else 0.0
    return round(min(1.0, max(token_score, entity_score) + action_score + brand_score), 3)


def find_cross_run_match(item: dict[str, Any], history: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any] | None, float]:
    best, best_score = None, 0.0
    for old in history if history is not None else load_cross_run_story_history():
        if not isinstance(old, dict):
            continue
        score = cross_run_similarity(item, old)
        if score > best_score:
            best, best_score = old, score
    return (best, best_score) if best and best_score >= MENZO_CROSS_RUN_NOVELTY_MIN_SCORE else (None, best_score)


def deterministic_cross_run_novelty(item: dict[str, Any], old: dict[str, Any]) -> tuple[str, list[str], str]:
    codes: list[str] = []
    new_entities = cross_run_entities(item) - cross_run_entities(old)
    if new_entities:
        codes.append("new_entity")
    new_actions = cross_run_actions(item) - cross_run_actions(old)
    codes.extend(sorted(a for a in new_actions if a != "rumor"))
    new_dates = cross_run_dates(item) - cross_run_dates(old)
    if new_dates:
        codes.append("new_event_or_date")
    ia, oa = cross_run_actions(item), cross_run_actions(old)
    if "confirmed" in ia and "rumor" in oa:
        codes.append("rumor_to_confirmation")
    if "contract_status_changed" in ia and any(term in cross_run_text(item) for term in ["lascia", "leaves", "left", "released", "rilasciato"]):
        codes.append("contract_status_changed")
    text = cross_run_text(item)
    if any(x in text for x in ["update", "aggiornamento", "new detail", "dettaglio", "esclusiva", "exclusive"]):
        codes.append("explicit_update")
    if codes:
        return "allow", sorted(set(codes)), "cross_run_story_novelty_detected"
    return "unclear", [], "deterministic_no_material_novelty"


def build_cross_run_novelty_prompt(item: dict[str, Any], old: dict[str, Any]) -> str:
    return """Compare the new wrestling-news candidate against a recently published/worked story.
Return ONLY strict JSON:
{"same_story": true, "has_material_novelty": false, "novelty_codes": [], "decision": "allow|skip|pending", "reason": ""}
Rules: allow only if same_story=false or has_material_novelty=true; skip if same_story=true and novelty is absent; pending if uncertain or insufficient data.
Material novelty includes official/primary confirmation, rumor-to-fact, contract status change, new involved name, new date, denial, concrete creative consequence, roster/medical/legal update, or changed match/title/stipulation/event.
New candidate:
""" + json.dumps(lightweight_ai_record(item, "new"), ensure_ascii=False) + "\nPrevious story:\n" + json.dumps(lightweight_ai_record(old, "previous"), ensure_ascii=False)


def apply_cross_run_novelty_gate(result: dict[str, Any]) -> None:
    pp = result.setdefault("postprocess", {})
    pp.update({"cross_run_story_novelty_gate_v95_5": True, "cross_run_novelty_gate_enabled": MENZO_CROSS_RUN_NOVELTY_GATE_ENABLED})
    if not MENZO_CROSS_RUN_NOVELTY_GATE_ENABLED:
        return
    counters = {"matches": 0, "allowed": 0, "skipped": 0, "pending": 0, "ai_calls": 0, "ai_avoided": 0}
    history = load_cross_run_story_history()
    new_selected: list[dict[str, Any]] = []
    new_pending = [x for x in result.get("pending", []) if isinstance(x, dict)]
    new_skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    for item in [dict(x) for x in result.get("selected", []) if isinstance(x, dict)]:
        match, score = find_cross_run_match(item, history)
        item["cross_run_novelty_gate_v95_5"] = True
        item["cross_run_match"] = bool(match)
        item["cross_run_match_score"] = score
        if not match:
            item["cross_run_novelty_decision"] = "none"
            item["cross_run_novelty_reason"] = "no_cross_run_match"
            new_selected.append(item)
            continue
        counters["matches"] += 1
        item["cross_run_match_title"] = match.get("title") or match.get("source_title") or ""
        item["cross_run_match_url"] = match.get("url") or match.get("source_url") or ""
        decision, codes, reason = deterministic_cross_run_novelty(item, match)
        if decision == "allow":
            item["cross_run_novelty_decision"] = "allow"; item["cross_run_novelty_reason"] = reason; item["cross_run_novelty_codes"] = codes
            item["reason"] = "cross_run_story_novelty_detected; " + str(item.get("reason") or "")
            new_selected.append(item); counters["allowed"] += 1; counters["ai_avoided"] += 1
            record_gemini_event(agent="Menzo", phase="cross_run_novelty_gate", model=MENZO_CROSS_RUN_NOVELTY_AI_MODEL, status="avoided", reason="deterministic_novelty_allow", saved_gemini_call=True, url=item.get("url") or item.get("source_url"), title=item.get("title") or item.get("source_title"))
            continue
        if not MENZO_CROSS_RUN_NOVELTY_AI_ENABLED:
            item["decision"] = "pending"; item["priority"] = "soft"; item["cross_run_novelty_decision"] = "pending"; item["cross_run_novelty_reason"] = "ai_disabled"; item["cross_run_novelty_codes"] = []
            new_pending.append(item); counters["pending"] += 1
            record_gemini_event(agent="Menzo", phase="cross_run_novelty_gate", model=MENZO_CROSS_RUN_NOVELTY_AI_MODEL, status="avoided", reason="ai_disabled", saved_gemini_call=True, url=item.get("url") or item.get("source_url"), title=item.get("title") or item.get("source_title"))
            continue
        ai_data, model_status = call_gemini_json_model(build_cross_run_novelty_prompt(item, match), MENZO_CROSS_RUN_NOVELTY_AI_MODEL, ledger_context={"url": item.get("url") or item.get("source_url"), "title": item.get("title") or item.get("source_title")}, phase="cross_run_novelty_gate")
        counters["ai_calls"] += 1
        ai_decision = str((ai_data or {}).get("decision") or "pending").lower()
        if ai_data and (ai_decision == "allow" and (ai_data.get("same_story") is False or ai_data.get("has_material_novelty") is True)):
            item["cross_run_novelty_decision"] = "allow"; item["cross_run_novelty_reason"] = ai_data.get("reason") or "ai_novelty_allow"; item["cross_run_novelty_codes"] = ai_data.get("novelty_codes") or []
            new_selected.append(item); counters["allowed"] += 1
        elif ai_data and ai_decision == "skip":
            item["decision"] = "skip"; item["priority"] = "skip"; item["article_type"] = item.get("article_type") or "duplicate"; item["cross_run_novelty_decision"] = "skip"; item["cross_run_novelty_reason"] = ai_data.get("reason") or "ai_no_novelty_skip"; item["cross_run_novelty_codes"] = ai_data.get("novelty_codes") or []
            new_skipped.append(item); counters["skipped"] += 1
        else:
            item["decision"] = "pending"; item["priority"] = "soft"; item["article_type"] = item.get("article_type") or "pending_followup"; item["cross_run_novelty_decision"] = "pending"; item["cross_run_novelty_reason"] = (ai_data or {}).get("reason") or model_status; item["cross_run_novelty_codes"] = (ai_data or {}).get("novelty_codes") or []
            new_pending.append(item); counters["pending"] += 1
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = new_skipped
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in result["selected"] if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(result["selected"]), "pending": len(result["pending"]), "skipped": len(result["skipped"])}
    pp["cross_run_novelty_matches"] = counters["matches"]
    pp["cross_run_novelty_allowed"] = counters["allowed"]
    pp["cross_run_novelty_skipped"] = counters["skipped"]
    pp["cross_run_novelty_pending"] = counters["pending"]
    pp["cross_run_novelty_ai_calls"] = counters["ai_calls"]
    pp["cross_run_novelty_ai_avoided"] = counters["ai_avoided"]


def build_suspicious_ai_clusters(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    used: set[int] = set()
    for i, item in enumerate(items):
        if i in used:
            continue
        key = deterministic_story_key(item)
        words = ai_dedupe_words(item)
        cluster = [item]
        for j, other in enumerate(items[i + 1:], start=i + 1):
            if j in used:
                continue
            other_key = deterministic_story_key(other)
            if key and key == other_key:
                cluster.append(other); used.add(j); continue
            show_a, show_b = rating_show_key(item), rating_show_key(other)
            if show_a and show_b and show_a != show_b:
                continue
            other_words = ai_dedupe_words(other)
            overlap = len(words & other_words) / max(1, min(len(words), len(other_words)))
            if overlap >= AI_DEDUPE_MIN_OVERLAP and len(words & other_words) >= 4:
                cluster.append(other); used.add(j)
        if len(cluster) > 1:
            clusters.append(cluster[:AI_DEDUPE_MAX_CANDIDATES])
            used.add(i)
        if len(clusters) >= AI_DEDUPE_MAX_CLUSTERS:
            break
    return clusters


def published_fingerprint_records() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for old in load_story_fingerprints():
        if not isinstance(old, dict):
            continue
        fp = old.get("fingerprint") if isinstance(old.get("fingerprint"), dict) else old
        out.append({
            "title": fp.get("title") or old.get("title") or "",
            "source": fp.get("source") or old.get("source") or "",
            "url": fp.get("url") or old.get("url") or "",
            "summary": fp.get("canonical_summary") or "",
            "category_hint": "published_memory",
            "published_at": old.get("added_at") or "",
            "has_image": False,
            "embed_count": 0,
        })
    return out[:20]


def suspicious_published_records(item: dict[str, Any], published: list[dict[str, Any]]) -> list[dict[str, Any]]:
    item_key = deterministic_story_key(item)
    item_words = ai_dedupe_words(item)
    matches: list[tuple[float, dict[str, Any]]] = []
    for old in published:
        old_key = deterministic_story_key(old)
        if item_key and old_key and item_key == old_key:
            matches.append((1.0, old))
            continue
        show_a, show_b = rating_show_key(item), rating_show_key(old)
        if show_a and show_b and show_a != show_b:
            continue
        old_words = ai_dedupe_words(old)
        overlap = len(item_words & old_words) / max(1, min(len(item_words), len(old_words)))
        if overlap >= AI_DEDUPE_MIN_OVERLAP and len(item_words & old_words) >= 4:
            matches.append((overlap, old))
    return [record for _, record in sorted(matches, key=lambda x: x[0], reverse=True)[: AI_DEDUPE_MAX_CANDIDATES - 1]]


def massy_cluster_records(board: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for cluster in board.get("suspicious_story_clusters", []) if isinstance(board.get("suspicious_story_clusters"), list) else []:
        if not isinstance(cluster, dict):
            continue
        records = [r for r in cluster.get("records", []) if isinstance(r, dict)]
        for rec in records:
            key = source_key(rec.get("source_url") or rec.get("url") or "")
            if key and rec.get("origin") == "candidate":
                out.setdefault(key, records)
    return out


def arbitration_records_for_item(item: dict[str, Any], cluster_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate = lightweight_ai_record(item, "new_1")
    review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
    candidate.update({
        "source_url": candidate.get("url") or item.get("source_url") or "",
        "event_key": review.get("event_key") or "",
        "excerpt": item.get("excerpt") or "",
        "canonical_summary": review.get("canonical_summary") or item.get("summary") or "",
        "story_footprint": item.get("story_footprint") or review.get("story_footprint") or "",
    })
    records = [candidate]
    seen = {source_key(candidate.get("source_url") or candidate.get("url") or "")}
    for rec in cluster_records:
        key = source_key(rec.get("source_url") or rec.get("url") or "")
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "id": rec.get("id") or f"suspect_{len(records)}",
            "title": rec.get("title") or "",
            "summary": rec.get("summary") or "",
            "source": rec.get("source") or "",
            "source_url": rec.get("source_url") or rec.get("url") or "",
            "event_key": rec.get("event_key") or "",
            "excerpt": rec.get("excerpt") or "",
            "canonical_summary": rec.get("canonical_summary") or rec.get("summary") or "",
            "publisher_history_origin": rec.get("origin") or "suspicious",
            "score": rec.get("score") or rec.get("menzo_score") or 0,
        })
    return records[:AI_DEDUPE_MAX_CANDIDATES]


def duplicate_cluster_article_type(item: dict[str, Any]) -> str:
    """Return an editorial type for a duplicate-cluster survivor."""
    current = str(item.get("article_type") or "").strip().lower()
    if current and current != "duplicate":
        return current
    text = normalize_text(" ".join(str(item.get(k) or "") for k in ["title", "summary", "excerpt", "reason", "category_hint"])).lower()
    if any(term in text for term in ["turns heel", "turn heel", "heel turn", "turns face", "turn face", "face turn", "title change", "new champion", "debut", "returns", "returning", "injury", "injured"]):
        return "post_show_major_angle"
    return "hard_news"


def duplicate_cluster_source_rank(item: dict[str, Any]) -> int:
    source = " ".join(str(item.get(k) or "") for k in ["source", "url", "source_url"]).lower()
    if "wrestlinginc" in source or "wrestling inc" in source:
        return 30
    if "fightful" in source:
        return 30
    if "ringsidenews" in source or "ringside news" in source:
        return 10
    return 20


def duplicate_cluster_richness(item: dict[str, Any]) -> int:
    text = " ".join(str(item.get(k) or "") for k in ["summary", "excerpt", "body", "content", "reason"])
    embeds = item.get("embed_count") or item.get("embeds_count") or 0
    try:
        embed_score = int(embeds) * 120
    except Exception:
        embed_score = 0
    return len(text) + embed_score + (120 if item.get("image") or item.get("image_url") or item.get("has_image") else 0)


def duplicate_cluster_winner_key(items: list[dict[str, Any]]) -> str:
    label_rank = {"high": 3, "medium": 2, "low": 1, "skip": 0}

    def rank(item: dict[str, Any]) -> tuple[int, int, int, int, int]:
        try:
            score = int(item.get("score", 0) or 0)
        except Exception:
            score = 0
        label = label_rank.get(str(item.get("ai_priority_label") or item.get("priority_label") or "").lower(), 0)
        non_duplicate = 1 if str(item.get("article_type") or "").lower() != "duplicate" else 0
        return score, label, non_duplicate, duplicate_cluster_source_rank(item), duplicate_cluster_richness(item)

    winner = max(items, key=rank)
    return source_key(winner.get("url") or winner.get("source_url") or "")


def apply_candidate_duplicate_cluster_survivors(
    result: dict[str, Any],
    records_by_url: dict[str, list[dict[str, Any]]],
    logs: list[dict[str, Any]],
) -> set[str]:
    """Resolve candidate-only duplicate clusters so at least one new story survives."""
    items_by_key: dict[str, dict[str, Any]] = {}
    section_by_key: dict[str, str] = {}
    for section in ["selected", "pending"]:
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if isinstance(item, dict):
                key = source_key(item.get("url") or item.get("source_url") or "")
                if key:
                    items_by_key[key] = item
                    section_by_key[key] = section

    processed: set[tuple[str, ...]] = set()
    handled: set[str] = set()
    threshold = int(result.get("daily_policy", {}).get("dynamic_soft_threshold") or MIN_SELECTED_SCORE)
    for cluster_records in records_by_url.values():
        candidate_keys = []
        existing_published = False
        for rec in cluster_records:
            key = source_key(rec.get("source_url") or rec.get("url") or "")
            if rec.get("origin") == "published_or_memory":
                existing_published = True
            elif key in items_by_key:
                candidate_keys.append(key)
        cluster_id = tuple(sorted(set(candidate_keys)))
        if len(cluster_id) < 2 or cluster_id in processed:
            continue
        processed.add(cluster_id)
        cluster_items = [items_by_key[k] for k in cluster_id]
        already_selected = [k for k in cluster_id if section_by_key.get(k) == "selected" and str(items_by_key[k].get("decision") or "") == "selected"]
        survivor_key = "" if existing_published else (already_selected[0] if already_selected else duplicate_cluster_winner_key(cluster_items))
        for key in cluster_id:
            item = items_by_key[key]
            if existing_published or key != survivor_key:
                item["decision"] = "skip"
                item["priority"] = "skip"
                item["article_type"] = "duplicate"
                item["reason"] = "skip:ai_cross_source_duplicate_arbitration_loser"
                handled.add(key)
            else:
                item["article_type"] = duplicate_cluster_article_type(item)
                try:
                    score = int(item.get("score", 0) or 0)
                except Exception:
                    score = 0
                if score >= threshold or is_major_hard_news(item):
                    item["decision"] = "selected"
                else:
                    item["decision"] = "pending"
                handled.add(key)
        logs.append({
            "ai_cross_source_duplicate_arbitration_used": True,
            "decision": "cluster_survivor_selected" if survivor_key else "cluster_existing_published_skip",
            "cluster_type": "same_story",
            "duplicate_cluster_survivor_selected": bool(survivor_key),
            "duplicate_cluster_survivor_url": items_by_key[survivor_key].get("url") or items_by_key[survivor_key].get("source_url") if survivor_key else "",
            "duplicate_cluster_loser_count": len(cluster_id) if existing_published else max(0, len(cluster_id) - 1),
            "duplicate_cluster_existing_published": existing_published,
            "reason": "candidate duplicate cluster resolved with mandatory survivor",
        })
    return handled


def apply_arbitration_decision(item: dict[str, Any], ai_data: dict[str, Any], model_used: str, second_pass: bool) -> dict[str, Any]:
    item = dict(item)
    decision = str(ai_data.get("decision") or "pending_review").lower()
    cluster_type = str(ai_data.get("cluster_type") or "uncertain").lower()
    try:
        confidence = int(ai_data.get("confidence", 0) or 0)
    except Exception:
        confidence = 0
    arbitration = {
        "ai_cross_source_duplicate_arbitration_used": True,
        "model_used": model_used,
        "second_pass_used": second_pass,
        "decision": decision,
        "cluster_type": cluster_type,
        "confidence": confidence,
        "canonical_event_label": ai_data.get("canonical_event_label") or "",
        "reason": ai_data.get("reason") or "",
        "suggested_followup_title_it": ai_data.get("suggested_followup_title_it") or "",
        "angle_summary_it": ai_data.get("angle_summary_it") or "",
    }
    item.setdefault("menzo_policy", {})["ai_cross_source_duplicate_arbitration"] = arbitration
    item["ai_cross_source_duplicate_arbitration"] = arbitration
    if decision == "skip_duplicate" or cluster_type == "same_story":
        item["decision"] = "skip"; item["priority"] = "skip"; item["article_type"] = "duplicate"
        item["reason"] = "skip:ai_cross_source_duplicate_arbitration; " + str(ai_data.get("reason") or "same core fact, no meaningful new angle")
    elif decision == "pending_followup" or cluster_type == "same_core_fact_new_angle":
        item["decision"] = "pending"; item["priority"] = "soft"; item["article_type"] = "pending_followup"
        item["reason"] = "pending_followup:ai_cross_source_duplicate_arbitration; " + str(ai_data.get("reason") or "same core fact with possible new angle")
        if ai_data.get("suggested_followup_title_it"):
            item["suggested_followup_title_it"] = ai_data.get("suggested_followup_title_it")
        if ai_data.get("angle_summary_it"):
            item["angle_summary_it"] = ai_data.get("angle_summary_it")
    elif decision == "selected" and cluster_type == "different_story":
        item["decision"] = "selected"
    else:
        item["decision"] = "pending"; item["priority"] = "soft"; item["article_type"] = "pending_review"
        item["reason"] = "pending_review:ai_cross_source_duplicate_arbitration; " + str(ai_data.get("reason") or "uncertain duplicate/follow-up arbitration")
    return item


def apply_ai_duplicate_arbitration(result: dict[str, Any], massy_board: dict[str, Any] | None = None) -> None:
    selected = [dict(x) for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [dict(x) for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    board = massy_board if isinstance(massy_board, dict) else {}
    records_by_url = massy_cluster_records(board)
    candidates = selected + pending
    original_selected = {source_key(x.get("url") or x.get("source_url") or "") for x in selected}
    resolved: dict[str, dict[str, Any]] = {}
    logs: list[dict[str, Any]] = []
    handled_cluster_keys = apply_candidate_duplicate_cluster_survivors({"selected": selected, "pending": pending, "daily_policy": result.get("daily_policy", {})}, records_by_url, logs)

    for item in candidates:
        key = source_key(item.get("url") or item.get("source_url") or "")
        if key in handled_cluster_keys:
            resolved[key] = item
            continue
        cluster_records = records_by_url.get(key, [])
        if not cluster_records:
            suspicious_published = suspicious_published_records(item, published_fingerprint_records())
            if suspicious_published:
                cluster_records = [dict(r, origin="published_or_memory", source_url=r.get("url") or r.get("source_url") or "") for r in suspicious_published]
        if not cluster_records:
            resolved[key] = item
            continue
        records = arbitration_records_for_item(item, cluster_records)
        ledger_context = {"url": item.get("url") or item.get("source_url"), "title": item.get("title") or item.get("source_title"), "candidate_id": item.get("candidate_id") or item.get("id") or item.get("semantic_id"), "source_id": item.get("source_id") or item.get("source"), "cluster_id": "|".join(source_key(r.get("source_url") or r.get("url") or "") for r in records)}
        ai_data, model = call_gemini_json_model(build_ai_dedupe_prompt(records), MENZO_DUPLICATE_ARBITRATION_FIRST_MODEL, ledger_context=ledger_context)
        second_pass = False
        allowed_second_pass, second_pass_reason = menzo_second_pass_gate(item, records, ai_data)
        if needs_second_pass(ai_data) and not allowed_second_pass:
            _record_menzo_second_pass_avoided(second_pass_reason, ledger_context)
        if allowed_second_pass:
            second_pass = True
            ai_data2, model2 = call_gemini_json_model(build_ai_dedupe_second_pass_prompt(records, relevant_history_payload(records)), MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL, ledger_context=ledger_context, phase="duplicate_arbitration_second_pass")
            if ai_data2:
                ai_data, model = ai_data2, model2
        if not ai_data:
            ai_data = {"cluster_type": "uncertain", "decision": "pending_review", "confidence": 0, "reason": model}
        resolved_item = apply_arbitration_decision(item, ai_data, model, second_pass)
        resolved[key] = resolved_item
        logs.append(resolved_item["ai_cross_source_duplicate_arbitration"])

    new_selected: list[dict[str, Any]] = []
    new_pending: list[dict[str, Any]] = []
    new_skipped: list[dict[str, Any]] = list(skipped)
    for item in resolved.values():
        key = source_key(item.get("url") or item.get("source_url") or "")
        if item.get("decision") == "skip":
            new_skipped.append(item)
        elif item.get("decision") == "pending":
            new_pending.append(item)
        elif key in original_selected or str(item.get("ai_priority_label") or "").lower() == "high":
            item["decision"] = "selected"; new_selected.append(item)
        else:
            item["decision"] = "pending"; new_pending.append(item)
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = new_skipped
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in result["selected"] if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(result["selected"]), "pending": len(result["pending"]), "skipped": len(result["skipped"])}
    pp = result.setdefault("postprocess", {})
    pp["ai_cross_source_duplicate_arbitration_used"] = len(logs)
    pp["ai_duplicate_arbitration_clusters"] = len(records_by_url)
    pp["ai_duplicate_arbitration_calls"] = len(logs)
    pp["gemini_calls_used_for_duplicate_arbitration"] = len(logs)
    pp["ai_duplicate_arbitration_skipped"] = sum(1 for l in logs if l.get("decision") == "skip_duplicate")
    pp["ai_duplicate_arbitration_pending_followup"] = sum(1 for l in logs if l.get("decision") in {"pending_followup", "pending_review"})
    pp["ai_cross_source_duplicate_arbitration_logs"] = logs[:AI_DEDUPE_MAX_CLUSTERS * AI_DEDUPE_MAX_CANDIDATES]
    pp["gemini_model_routing_v95_4"] = True

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
        elif is_softpool_eligible(item):
            item["decision"] = "pending"
            item["priority"] = "soft"
            pending.append(item)
        else:
            item["decision"] = "skip"
            item["priority"] = "skip"
            item["reason"] = f"softpool_ineligible:{item.get('reason', '')}"
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
                if is_softpool_eligible(item):
                    item["decision"] = "pending"
                    item["priority"] = "soft"
                    item["reason"] = f"data_report_cap:{MAX_DATA_REPORTS}; {item.get('reason', '')}"
                    moved.append(item)
                else:
                    item["decision"] = "skip"
                    item["priority"] = "skip"
                    skipped.append(item)
                continue
        kept.append(item)
    result["selected"] = kept
    result["pending"] = sorted(pending + moved, key=sort_item, reverse=True)
    result["skipped"] = skipped
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in kept if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(kept), "pending": len(result["pending"]), "skipped": len(skipped)}


def enforce_capacity_buffer(result: dict[str, Any]) -> None:
    selected = sorted([x for x in result.get("selected", []) if isinstance(x, dict)], key=sort_item, reverse=True)
    overflow = selected[MAX_SELECTED_THIS_RUN:]
    selected = selected[:MAX_SELECTED_THIS_RUN]
    pending = [x for x in result.get("pending", []) if isinstance(x, dict)] + overflow
    for item in overflow:
        item["decision"] = "pending"
        item.setdefault("menzo_policy", {})["selected_capacity_buffer_overflow_to_pending"] = True
    result["selected"] = selected
    result["pending"] = sorted(pending, key=sort_item, reverse=True)
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in selected if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(selected), "pending": len(result["pending"]), "skipped": len(result.get("skipped", []))}
    result.setdefault("postprocess", {})["menzo_selected_capacity_buffer"] = MAX_SELECTED_THIS_RUN
    result.setdefault("postprocess", {})["menzo_selected_overflow_to_pending"] = len(overflow)


def save_softpool(result: dict[str, Any]) -> None:
    now = utc_now()
    previous = load_softpool()
    by_url: dict[str, dict[str, Any]] = {source_key(x.get("url") or x.get("source_url") or ""): x for x in previous if isinstance(x, dict)}
    for item in result.get("pending", []) if isinstance(result.get("pending"), list) else []:
        if not is_softpool_eligible(item):
            continue
        key = source_key(item.get("url") or item.get("source_url") or "")
        if not key:
            continue
        previous_item = by_url.get(key, {}) if isinstance(by_url.get(key), dict) else {}
        clone = {**previous_item, **dict(item)}
        clone.setdefault("softpool_added_at", previous_item.get("softpool_added_at") or now)
        clone["last_seen_at"] = now
        clone["softpool_reason"] = "medium_candidate_above_quality_threshold"
        clone["softpool_ttl_hours"] = item_ttl_hours(clone)
        if clone.get("from_softpool") or previous_item:
            clone["softpool_deferrals"] = softpool_deferrals(previous_item) + 1
        else:
            clone.setdefault("softpool_deferrals", 0)
        by_url[key] = clone
    for section in ["selected", "skipped"]:
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            key = source_key(item.get("url") or item.get("source_url") or "")
            if key in by_url:
                by_url.pop(key, None)
    active = []
    now_dt = datetime.now(timezone.utc)
    for item in by_url.values():
        if not is_softpool_eligible(item):
            continue
        added = parse_dt(item.get("softpool_added_at")) or now_dt
        ttl = int(item.get("softpool_ttl_hours") or item_ttl_hours(item))
        if now_dt - added <= timedelta(hours=ttl):
            active.append(item)
    write_json(SOFTPOOL_FILE, {"version": MENZO_VERSION, "updated_at": now, "ttl_hours": SOFTPOOL_TTL_HOURS, "softnews_ttl_hours": SOFTNEWS_TTL_HOURS, "min_score": MIN_SOFTPOOL_SCORE, "items": sorted(active, key=sort_item, reverse=True)})


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


def _wp_ready_for_costly_work() -> tuple[bool, str]:
    try:
        from agents.wp_preflight_v93_25 import run_wp_preflight
        data = run_wp_preflight()
        return bool(data.get("ready")), str(data.get("reason") or "unknown")
    except Exception as exc:
        return True, f"preflight_error_non_blocking:{exc}"


def _empty_menzo_when_wp_unready(reason: str) -> dict[str, Any]:
    data = {
        "agent": "Menzo",
        "version": "v93_25_wp_ready_guard",
        "generated_at": utc_now(),
        "status": "skipped",
        "reason": reason,
        "selected": [],
        "pending": [],
        "skipped": [],
        "allowed_urls_for_v92": [],
        "handoff": {"to_bob_or_v92": 0, "pending": 0, "skipped": 0},
        "policy": {"wp_must_be_ready_before_ai": True, "gemini_avoided": True},
    }
    write_json(ARTIFACT_DECISIONS_FILE, data)
    write_json(MENZO_DECISIONS_FILE, data)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": data["version"], "allowed_urls": []})
    print(f"[JARVIS v93.25] expensive_pipeline_skipped - WordPress not ready, Gemini avoided: {reason}", flush=True)
    return data


def run_menzo(massy_board: dict[str, Any] | None = None) -> dict[str, Any]:
    ok, why = _wp_ready_for_costly_work()
    if not ok:
        return _empty_menzo_when_wp_unready(why)
    board = augment_board_with_softpool(massy_board if isinstance(massy_board, dict) else base.load_json(base.MASSY_BOARD_FILE, {}))
    previous_ai_enabled = base.AI_ENABLED
    base.AI_ENABLED = False
    try:
        result = base.run_menzo(board)
    finally:
        base.AI_ENABLED = previous_ai_enabled
    normalize_ai_fields(result)
    rebuild_decisions(result)
    apply_source_opinion_policy(result)
    apply_medical_brand_policy(result)
    apply_story_footprint_policy(result)
    enforce_ai_skip_binding(result)
    apply_generalized_fingerprint_policy(result)
    apply_softpool_decay(result)
    apply_dynamic_editorial_budget(result)
    apply_ai_duplicate_arbitration(result, board)
    apply_dynamic_editorial_budget(result)
    apply_cross_run_novelty_gate(result)
    enforce_selected_cap(result)
    enforce_capacity_buffer(result)
    result["version"] = MENZO_VERSION
    result["mode"] = "selective_softpool_footprint_policy"
    policy = result.setdefault("policy", {})
    policy["priority_schema"] = "priority_label_high_medium_low_skip"
    policy["selected_requires_high_label_or_min_score"] = MIN_SELECTED_SCORE
    policy["softpool_enabled"] = True
    policy["softpool_min_score"] = MIN_SOFTPOOL_SCORE
    policy["softpool_excludes"] = sorted(EXCLUDED_SOFTPOOL_TYPES)
    policy["soft_news_ttl_hours"] = SOFTNEWS_TTL_HOURS
    policy["menzo_hard_skips_exported_to_massy"] = True
    policy["source_opinion_skip"] = True
    policy["story_footprint_dedupe_before_bob"] = True
    policy["story_footprints_ttl_days"] = 7
    policy["story_dedupe_before_bob"] = True
    policy["medical_return_major_brands_only"] = True
    policy["brand_rank_tiebreaker"] = "WWE/NXT/AEW > TNA/ROH > OVW/indie"
    policy["news_capacity_buffer_for_bob"] = MAX_SELECTED_THIS_RUN
    policy["daily_editorial_target"] = DAILY_NEWS_TARGET
    policy["dynamic_soft_threshold"] = result.get("daily_policy", {}).get("dynamic_soft_threshold")
    policy["softpool_max_age_hours"] = SOFTNEWS_TTL_HOURS
    policy["softpool_max_deferrals"] = SOFTPOOL_MAX_DEFERRALS
    policy["softpool_outranked_deferrals"] = SOFTPOOL_OUTRANKED_DEFERRALS
    policy["gemini_editorial_review_for_generic_soft_news"] = False
    policy["gemini_only_for_duplicate_novelty_arbitration"] = True
    policy["ai_duplicate_arbitration"] = True
    policy["ai_cross_source_duplicate_arbitration"] = True
    policy["ai_duplicate_arbitration_first_pass_model"] = MENZO_DUPLICATE_ARBITRATION_FIRST_MODEL
    policy["ai_duplicate_arbitration_second_pass_model"] = MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL
    policy["gemini_model_routing_v95_4"] = True
    policy["cross_run_story_novelty_gate_v95_5"] = True
    policy["cross_run_novelty_gate_enabled"] = MENZO_CROSS_RUN_NOVELTY_GATE_ENABLED
    policy["cross_run_novelty_ai_model"] = MENZO_CROSS_RUN_NOVELTY_AI_MODEL
    policy["menzo_35_gate"] = {"enabled": MENZO_ENABLE_35_FOR_HIGH_AMBIGUITY, "min_score": MENZO_35_MIN_SCORE, "require_duplicate_or_same_story": MENZO_35_REQUIRE_DUPLICATE_OR_SAME_STORY}
    policy["ai_duplicate_arbitration_limits"] = {"max_clusters_per_run": AI_DEDUPE_MAX_CLUSTERS, "max_candidates_per_cluster": AI_DEDUPE_MAX_CANDIDATES}
    save_softpool(result)
    save_hard_skips(result)
    remember_stories(result.get("selected", []), reason="menzo_selected")
    remember_footprints(result.get("selected", []), reason="menzo_selected")
    remember_fingerprints(result.get("selected", []), reason="menzo_selected")
    write_json(ARTIFACT_DECISIONS_FILE, result)
    write_json(MENZO_DECISIONS_FILE, result)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": MENZO_VERSION, "allowed_urls": result.get("allowed_urls_for_v92", [])})
    print(
        f"[MENZO v94.13.4.1] Decisione selettiva | "
        f"selected={len(result.get('selected', []))} "
        f"pending={len(result.get('pending', []))} "
        f"skipped={len(result.get('skipped', []))} "
        f"source_opinion={result.get('postprocess', {}).get('source_opinion_skipped', 0)} "
        f"footprint_dupes={result.get('postprocess', {}).get('story_footprint_duplicates_skipped', 0)} "
        f"fingerprint_dupes={result.get('postprocess', {}).get('story_fingerprint_duplicates_skipped', 0)} "
        f"ai_dupes={result.get('postprocess', {}).get('ai_duplicate_arbitration_skipped', 0)} ai_cross_source_duplicate_arbitration_used={result.get('postprocess', {}).get('ai_cross_source_duplicate_arbitration_used', 0)} "
        f"ai_skip_bound={result.get('postprocess', {}).get('ai_skip_binding_moved', 0)} "
        f"medical_non_major={result.get('postprocess', {}).get('medical_return_non_major_brand_skipped', 0)} "
        f"daily_news_target={result.get('daily_policy', {}).get('daily_news_target')} "
        f"published_today_count={result.get('daily_policy', {}).get('published_today_count')} "
        f"published_today_percent={result.get('daily_policy', {}).get('published_today_percent')} "
        f"dynamic_soft_threshold={result.get('daily_policy', {}).get('dynamic_soft_threshold')} "
        f"skipped_by_dynamic_threshold={result.get('postprocess', {}).get('skipped_by_dynamic_threshold', 0)} "
        f"softpool_expired_not_fresh={result.get('postprocess', {}).get('softpool_expired_not_fresh', 0)} "
        f"softpool_repeatedly_outranked={result.get('postprocess', {}).get('softpool_repeatedly_outranked', 0)} "
        f"gemini_calls_avoided_by_threshold={result.get('postprocess', {}).get('gemini_calls_avoided_by_threshold', 0)} "
        f"gemini_calls_used_for_duplicate_arbitration={result.get('postprocess', {}).get('gemini_calls_used_for_duplicate_arbitration', 0)} "
        f"softpool={len(load_softpool())} "
        f"capacity_buffer={MAX_SELECTED_THIS_RUN}",
        flush=True,
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_menzo().get("handoff", {}), ensure_ascii=False, indent=2))
