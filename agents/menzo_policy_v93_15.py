from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agents import menzo as base
from agents.story_dedupe_v93_32 import dedupe_within_batch, is_source_opinion, remember_footprints, remember_stories, story_footprint, story_signature
from agents.story_dedupe_v93_32 import build_generalized_fingerprint, dedupe_within_batch, find_duplicate_by_fingerprint, is_source_opinion, load_story_fingerprints, remember_fingerprints, remember_footprints, remember_stories, story_footprint, story_signature

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

MENZO_DECISIONS_FILE = NEWSROOM_STATE_DIR / "menzo_decisions_latest.json"
V92_ALLOWED_URLS_FILE = NEWSROOM_STATE_DIR / "v92_allowed_news_urls.json"
ARTIFACT_DECISIONS_FILE = ARTIFACT_DIR / "menzo_decisions.json"
SOFTPOOL_FILE = NEWSROOM_STATE_DIR / "menzo_softpool.json"
HARD_SKIP_FILE = NEWSROOM_STATE_DIR / "menzo_hard_skips.json"

MENZO_VERSION = "v93_39_capacity_buffer"
VALID_LABELS = {"high", "medium", "low", "skip"}
LABEL_SCORE = {"high": 92, "medium": 72, "low": 48, "skip": 0}
SOFTPOOL_TTL_HOURS = int(os.getenv("V93_MENZO_SOFTPOOL_TTL_HOURS", "36"))
SOFTNEWS_TTL_HOURS = int(os.getenv("V93_MENZO_SOFTNEWS_TTL_HOURS", "24"))
HARD_SKIP_TTL_HOURS = int(os.getenv("V93_MENZO_HARD_SKIP_TTL_HOURS", "168"))
MIN_SELECTED_SCORE = int(os.getenv("V93_MENZO_MIN_SELECTED_SCORE", "65"))
MIN_SOFTPOOL_SCORE = int(os.getenv("V93_MENZO_MIN_SOFTPOOL_SCORE", "55"))
MAX_DATA_REPORTS = int(os.getenv("V93_MENZO_MAX_DATA_REPORTS_PER_RUN", "1"))
MAX_SELECTED_THIS_RUN = int(os.getenv("V93_MENZO_MAX_SELECTED_THIS_RUN", "7"))

EXCLUDED_SOFTPOOL_TYPES = {"low_value", "duplicate", "external_sports_reaction"}


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
        clone = dict(item)
        clone.setdefault("softpool_added_at", now)
        clone["last_seen_at"] = now
        clone["softpool_reason"] = "medium_candidate_above_quality_threshold"
        clone["softpool_ttl_hours"] = item_ttl_hours(clone)
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
    result = base.run_menzo(board)
    normalize_ai_fields(result)
    rebuild_decisions(result)
    apply_source_opinion_policy(result)
    apply_medical_brand_policy(result)
    apply_story_footprint_policy(result)
    enforce_ai_skip_binding(result)
    apply_generalized_fingerprint_policy(result)
    enforce_selected_cap(result)
    enforce_capacity_buffer(result)
    result["version"] = MENZO_VERSION
    result["mode"] = "selective_softpool_footprint_policy"
    result.setdefault("policy", {})["priority_schema"] = "priority_label_high_medium_low_skip"
    result.setdefault("policy", {})["selected_requires_high_label_or_min_score"] = MIN_SELECTED_SCORE
    result.setdefault("policy", {})["softpool_enabled"] = True
    result.setdefault("policy", {})["softpool_min_score"] = MIN_SOFTPOOL_SCORE
    result.setdefault("policy", {})["softpool_excludes"] = sorted(EXCLUDED_SOFTPOOL_TYPES)
    result.setdefault("policy", {})["soft_news_ttl_hours"] = SOFTNEWS_TTL_HOURS
    result.setdefault("policy", {})["menzo_hard_skips_exported_to_massy"] = True
    result.setdefault("policy", {})["source_opinion_skip"] = True
    result.setdefault("policy", {})["story_footprint_dedupe_before_bob"] = True
    result.setdefault("policy", {})["story_footprints_ttl_days"] = 7
    result.setdefault("policy", {})["medical_return_major_brands_only"] = True
    result.setdefault("policy", {})["brand_rank_tiebreaker"] = "WWE/NXT/AEW > TNA/ROH > OVW/indie"
    result.setdefault("policy", {})["medical_return_major_brands_only"] = True
    result.setdefault("policy", {})["brand_rank_tiebreaker"] = "WWE/NXT/AEW > TNA/ROH > OVW/indie"
    result.setdefault("policy", {})["story_dedupe_before_bob"] = True
    result.setdefault("policy", {})["news_capacity_buffer_for_bob"] = MAX_SELECTED_THIS_RUN
    result.setdefault("policy", {})["source_opinion_skip"] = True
    result.setdefault("policy", {})["story_footprint_dedupe_before_bob"] = True
    result.setdefault("policy", {})["story_footprints_ttl_days"] = 7
    result.setdefault("policy", {})["medical_return_major_brands_only"] = True
    result.setdefault("policy", {})["brand_rank_tiebreaker"] = "WWE/NXT/AEW > TNA/ROH > OVW/indie"
    result.setdefault("policy", {})["medical_return_major_brands_only"] = True
    result.setdefault("policy", {})["brand_rank_tiebreaker"] = "WWE/NXT/AEW > TNA/ROH > OVW/indie"
    result.setdefault("policy", {})["medical_return_major_brands_only"] = True
    result.setdefault("policy", {})["brand_rank_tiebreaker"] = "WWE/NXT/AEW > TNA/ROH > OVW/indie"
    result.setdefault("policy", {})["story_dedupe_before_bob"] = True
    save_softpool(result)
    save_hard_skips(result)
    remember_stories(result.get("selected", []), reason="menzo_selected")
    remember_stories(result.get("selected", []), reason="menzo_selected")
    remember_footprints(result.get("selected", []), reason="menzo_selected")
    remember_fingerprints(result.get("selected", []), reason="menzo_selected")
    remember_stories(result.get("selected", []), reason="menzo_selected")
    write_json(ARTIFACT_DECISIONS_FILE, result)
    write_json(MENZO_DECISIONS_FILE, result)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": MENZO_VERSION, "allowed_urls": result.get("allowed_urls_for_v92", [])})
    print(f"[MENZO v93.34] Decisione selettiva | selected={len(result.get('selected', []))} pending={len(result.get('pending', []))} skipped={len(result.get('skipped', []))} source_opinion={result.get('postprocess', {}).get('source_opinion_skipped', 0)} footprint_dupes={result.get('postprocess', {}).get('story_footprint_duplicates_skipped', 0)} fingerprint_dupes={result.get('postprocess', {}).get('story_fingerprint_duplicates_skipped', 0)} ai_skip_bound={result.get('postprocess', {}).get('ai_skip_binding_moved', 0)} fingerprint_dupes={result.get('postprocess', {}).get('story_fingerprint_duplicates_skipped', 0)} ai_skip_bound={result.get('postprocess', {}).get('ai_skip_binding_moved', 0)} medical_non_major={result.get('postprocess', {}).get('medical_return_non_major_brand_skipped', 0)} softpool={len(load_softpool())} capacity_buffer={MAX_SELECTED_THIS_RUN} capacity_buffer={MAX_SELECTED_THIS_RUN}", flush=True)
    return result


if __name__ == "__main__":
    print(json.dumps(run_menzo().get("handoff", {}), ensure_ascii=False, indent=2))
