from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agents import menzo as base
from agents.story_dedupe_v93_32 import (
    build_generalized_fingerprint,
    dedupe_within_batch,
    find_duplicate_by_fingerprint,
    is_source_opinion,
    load_story_fingerprints,
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

MENZO_VERSION = "v94.11_menzo_ai_duplicate_arbitration"
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
    }


def build_ai_dedupe_prompt(records: list[dict[str, Any]]) -> str:
    return """You are Menzo's duplicate-news arbiter. Use only the lightweight metadata below; do not assume full article bodies.
Return ONLY valid JSON with this shape:
{"cluster_type":"same_story|follow_up|different_story|mixed","keep_ids":[],"drop_ids":[],"reason":"","novelty_by_id":{"id":"none|minor|substantial"}}
Rules: same central wrestling fact with no substantial novelty is same_story. If multiple same-run candidates describe the same fact, keep the best by verifiable details, source reliability, useful image/embed, less clickbait, central clarity, and direct/original details. Different TV ratings stories for different shows are not same_story.

Candidates:
""" + json.dumps(records, ensure_ascii=False, indent=2)


def call_gemini_json(prompt: str) -> tuple[dict[str, Any] | None, str]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None, "missing_api_key"
    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=api_key)
        for model in [m.strip() for m in os.getenv("GEMINI_MODEL_CHAIN", "gemini-3.1-flash-lite,gemini-2.5-flash-lite").split(",") if m.strip()]:
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                raw = re.sub(r"^```(?:json)?|```$", "", (getattr(response, "text", "") or "").strip(), flags=re.I).strip()
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data, model
            except Exception:
                continue
    except Exception as exc:
        return None, f"gemini_unavailable:{exc}"
    return None, "empty_or_invalid_response"


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


def apply_ai_duplicate_arbitration(result: dict[str, Any]) -> None:
    selected = [dict(x) for x in result.get("selected", []) if isinstance(x, dict)]
    pending = [dict(x) for x in result.get("pending", []) if isinstance(x, dict)]
    skipped = [x for x in result.get("skipped", []) if isinstance(x, dict)]
    candidates = selected + pending
    original_selected = {source_key(x.get("url") or x.get("source_url") or "") for x in selected}
    clusters = build_suspicious_ai_clusters(candidates)
    ai_used = 0
    ai_statuses: list[str] = []
    dropped: dict[str, dict[str, Any]] = {}
    keep_keys: set[str] = set()

    for idx, cluster in enumerate(clusters, start=1):
        records = [lightweight_ai_record(item, f"c{idx}_{n}") for n, item in enumerate(cluster, start=1)]
        ai_data, status = call_gemini_json(build_ai_dedupe_prompt(records))
        ai_statuses.append(status)
        if ai_data:
            ai_used += 1
        det_keys = [deterministic_story_key(x) for x in cluster]
        deterministic_same_story = (
            len(det_keys) == len(cluster)
            and all(det_keys)
            and len(set(det_keys)) == 1
        )
        same_story = bool(ai_data and ai_data.get("cluster_type") == "same_story") or deterministic_same_story
        if not same_story:
            continue
        keep_ids = set(ai_data.get("keep_ids") or []) if ai_data else set()
        if keep_ids:
            keep_item = next((cluster[int(k.rsplit("_", 1)[-1]) - 1] for k in keep_ids if k.rsplit("_", 1)[-1].isdigit() and 0 < int(k.rsplit("_", 1)[-1]) <= len(cluster)), None)
        else:
            keep_item = sorted(cluster, key=candidate_quality_score, reverse=True)[0]
        keep_url = str(keep_item.get("url") or keep_item.get("source_url") or "")
        keep_keys.add(source_key(keep_url))
        for item in cluster:
            key = source_key(item.get("url") or item.get("source_url") or "")
            if key == source_key(keep_url):
                continue
            item["decision"] = "skip"
            item["priority"] = "skip"
            item["article_type"] = "duplicate"
            item["reason"] = "ai_cluster_duplicate_loser"
            item["duplicate_of"] = keep_url
            item.setdefault("menzo_policy", {})["ai_duplicate_arbitration"] = True
            dropped[key] = item

    # Published-memory check is AI-only and only runs for lightweight suspicious matches.
    # If Gemini is unavailable, leave candidates untouched/pending via the existing conservative flow.
    published_records = published_fingerprint_records()
    for item in list(candidates):
        key = source_key(item.get("url") or item.get("source_url") or "")
        if key in dropped:
            continue
        suspicious_published = suspicious_published_records(item, published_records)
        if not suspicious_published:
            continue
        probe = [lightweight_ai_record(item, "new_1")] + [dict(r, id=f"pub_{i}") for i, r in enumerate(suspicious_published, start=1)]
        if len(probe) <= 1 or len(ai_statuses) >= AI_DEDUPE_MAX_CLUSTERS:
            break
        ai_data, status = call_gemini_json(build_ai_dedupe_prompt(probe))
        ai_statuses.append(status)
        if not ai_data:
            continue
        ai_used += 1
        novelty = (ai_data.get("novelty_by_id") or {}).get("new_1")
        drop_ids = set(ai_data.get("drop_ids") or [])
        if ai_data.get("cluster_type") == "same_story" and ("new_1" in drop_ids or novelty in {"none", "minor"}):
            pub_id = next((x for x in ai_data.get("keep_ids", []) if str(x).startswith("pub_")), "")
            pub_url = next((r.get("url") for r in probe if r.get("id") == pub_id), "")
            item["decision"] = "skip"; item["priority"] = "skip"; item["article_type"] = "duplicate"
            item["reason"] = "ai_confirmed_duplicate_of_published"; item["duplicate_of"] = pub_url
            item.setdefault("menzo_policy", {})["ai_duplicate_arbitration"] = True
            dropped[key] = item

    kept = [x for x in candidates if source_key(x.get("url") or x.get("source_url") or "") not in dropped]
    new_selected, new_pending = [], []
    for item in kept:
        key = source_key(item.get("url") or item.get("source_url") or "")
        if key in original_selected or key in keep_keys or str(item.get("ai_priority_label") or "").lower() == "high":
            item["decision"] = "selected"; new_selected.append(item)
        else:
            item["decision"] = "pending"; new_pending.append(item)
    result["selected"] = sorted(new_selected, key=sort_item, reverse=True)
    result["pending"] = sorted(new_pending, key=sort_item, reverse=True)
    result["skipped"] = skipped + list(dropped.values())
    result["allowed_urls_for_v92"] = [str(x.get("url") or x.get("source_url") or "") for x in result["selected"] if x.get("url") or x.get("source_url")]
    result["handoff"] = {"to_bob_or_v92": len(result["selected"]), "pending": len(result["pending"]), "skipped": len(result["skipped"])}
    result.setdefault("postprocess", {})["ai_duplicate_arbitration_clusters"] = len(clusters)
    result.setdefault("postprocess", {})["ai_duplicate_arbitration_calls"] = ai_used
    result.setdefault("postprocess", {})["ai_duplicate_arbitration_skipped"] = len(dropped)
    result.setdefault("postprocess", {})["ai_duplicate_arbitration_statuses"] = ai_statuses[:AI_DEDUPE_MAX_CLUSTERS]


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
    apply_ai_duplicate_arbitration(result)
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
    policy["ai_duplicate_arbitration"] = True
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
        f"[MENZO v94.11] Decisione selettiva | "
        f"selected={len(result.get('selected', []))} "
        f"pending={len(result.get('pending', []))} "
        f"skipped={len(result.get('skipped', []))} "
        f"source_opinion={result.get('postprocess', {}).get('source_opinion_skipped', 0)} "
        f"footprint_dupes={result.get('postprocess', {}).get('story_footprint_duplicates_skipped', 0)} "
        f"fingerprint_dupes={result.get('postprocess', {}).get('story_fingerprint_duplicates_skipped', 0)} "
        f"ai_dupes={result.get('postprocess', {}).get('ai_duplicate_arbitration_skipped', 0)} "
        f"ai_skip_bound={result.get('postprocess', {}).get('ai_skip_binding_moved', 0)} "
        f"medical_non_major={result.get('postprocess', {}).get('medical_return_non_major_brand_skipped', 0)} "
        f"softpool={len(load_softpool())} "
        f"capacity_buffer={MAX_SELECTED_THIS_RUN}",
        flush=True,
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run_menzo().get("handoff", {}), ensure_ascii=False, indent=2))
