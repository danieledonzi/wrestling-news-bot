from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
PUBLISHER_HISTORY_FILE = NEWSROOM_STATE_DIR / "publisher_history.json"
STORY_MEMORY_FILE = NEWSROOM_STATE_DIR / "story_dedupe_memory.json"
STORY_FOOTPRINT_FILE = NEWSROOM_STATE_DIR / "story_footprints.json"

STORY_TTL_HOURS = 96
FOOTPRINT_TTL_HOURS = 168
FOOTPRINT_DUPLICATE_THRESHOLD = 0.62

SOURCE_PRIORITY = {
    "wrestlinginc": 90,
    "wrestling inc": 90,
    "wrestling inc.": 90,
    "fightful": 86,
    "ringsidenews": 78,
    "ringside news": 78,
}

STOPWORDS = {
    "wwe", "aew", "tna", "nxt", "roh", "the", "and", "with", "from", "after", "before", "during",
    "says", "said", "report", "reports", "news", "rumor", "rumors", "update", "details", "reveals",
    "star", "former", "current", "wrestling", "wrestler", "match", "title", "show", "episode", "dynamite",
    "raw", "smackdown", "collision", "impact", "new", "returns", "return", "set", "announced", "exclusive",
    "opinion", "views", "take", "what", "about", "this", "that", "will", "could", "would", "should",
}

ENTITY_HINTS = {
    "mjf", "liv", "morgan", "dominik", "mysterio", "jim", "ross", "vince", "mcmahon", "seth", "rollins",
    "roman", "reigns", "punk", "cody", "rhodes", "oba", "femi", "sol", "ruca", "butcher", "blade",
    "becky", "lynch", "mercedes", "mone", "moné", "gable", "corbin", "amore", "knight", "stratus",
    "dreamwave", "laynie", "luck", "veronica", "haven", "sloane", "jacobs", "anya", "rune",
}

ACTION_HINTS = {
    "injury", "injured", "infortunio", "infortun", "pulled", "removed", "rimosso", "ritirato", "rinunciare",
    "contract", "contratto", "obligation", "obbligo", "lawsuit", "causa", "azionisti", "shareholder",
    "released", "rilasciato", "departs", "gone", "leaves", "lascia", "free", "agent", "booking", "creative",
    "frustration", "frustrazione", "direction", "direzione", "return", "ritorno", "debut", "title", "titolo",
}

OPINION_PATTERNS = [
    re.compile(r"\bopinion\s*:\b", re.I),
    re.compile(r"\bopinione\s*:\b", re.I),
    re.compile(r"\bmy\s+opinion\b", re.I),
    re.compile(r"\bin\s+my\s+view\b", re.I),
    re.compile(r"\bwhat\s+i\s+think\b", re.I),
    re.compile(r"\bthis\s+is\s+one\s+of\s+those\s+reports\s+that\s+makes\s+me\b", re.I),
    re.compile(r"\bmi\s+fanno\s+chiedere\s+cosa\b", re.I),
    re.compile(r"\bnon\s+sono\s+un\s+genio\b", re.I),
    re.compile(r"\bse\s+la\s+wwe\s+è\s+cos[iì]\s+frustrata\b", re.I),
]


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


def clean(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def blob(item: dict[str, Any]) -> str:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
    parts = [
        item.get("title"), item.get("title_it"), item.get("source_title"), item.get("summary"),
        item.get("description"), item.get("excerpt"), item.get("excerpt_it"), item.get("url"), item.get("source_url"),
        item.get("body_html"), meta.get("title"), meta.get("source_title"), meta.get("description"),
        review.get("story_footprint"), review.get("editorial_comment"), review.get("reason"),
    ]
    return clean(" ".join(str(x or "") for x in parts))


def source_score(item: dict[str, Any]) -> int:
    src = clean(item.get("source") or item.get("source_name") or item.get("feed") or item.get("url") or item.get("source_url") or "")
    for key, score in SOURCE_PRIORITY.items():
        if key in src:
            return score
    return 50


def item_score(item: dict[str, Any]) -> int:
    try:
        return int(item.get("score", item.get("ai_priority", item.get("deterministic_score", 0))) or 0)
    except Exception:
        return 0


def story_sort_key(item: dict[str, Any]) -> tuple[int, int, float]:
    age = 999999.0
    try:
        age = float(item.get("age_hours", 999999) or 999999)
    except Exception:
        pass
    return item_score(item), source_score(item), -age


def token_set(item_or_text: Any) -> set[str]:
    text = blob(item_or_text) if isinstance(item_or_text, dict) else clean(item_or_text)
    words = [w for w in text.split() if len(w) >= 4 and w not in STOPWORDS]
    return set(words)


def story_signature(item: dict[str, Any]) -> str:
    b = blob(item)
    if not b:
        return ""
    if "mjf" in b and any(x in b for x in ["injury", "infortun", "pulled", "rimosso", "rinunciare", "booking", "removed"]) and any(x in b for x in ["indie", "independent", "evento indipendente", "beyond wrestling"]):
        return "story:aew:mjf:indie_injury"
    if "jim ross" in b and any(x in b for x in ["lawsuit", "causa", "azionisti", "shareholder"]) and "vince" in b:
        return "story:wwe:vince_shareholder_lawsuit_jim_ross"
    if "liv morgan" in b and "dominik" in b and any(x in b for x in ["frustration", "frustrazione", "booking", "storyline", "direction", "direzione"]):
        return "story:wwe:liv_morgan_dominik_booking_frustration"
    if "seth rollins" in b and any(x in b for x in ["youtube", "video", "interview", "intervista"]) and any(x in b for x in ["injury", "infortun", "triceps", "tricipite"]):
        return "story:wwe:seth_rollins_triceps_video"
    if "sol ruca" in b and any(x in b for x in ["structured", "strutturato", "match", "criticism", "criticata"]):
        return "story:nxt:sol_ruca_structured_match_criticism"
    words = list(token_set(item))
    name_tokens = sorted([w for w in words if w in ENTITY_HINTS])
    action_tokens = sorted([w for w in words if w in ACTION_HINTS])
    if name_tokens and action_tokens:
        return "story:auto:" + ":".join((name_tokens[:3] + action_tokens[:3]))
    return ""


def story_footprint(item: dict[str, Any]) -> dict[str, Any]:
    b = blob(item)
    words = token_set(item)
    entities = sorted([w for w in words if w in ENTITY_HINTS])
    actions = sorted([w for w in words if w in ACTION_HINTS])
    sig = story_signature(item)
    review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
    ai_fp = clean(review.get("story_footprint") or "") if isinstance(review, dict) else ""
    return {
        "story_signature": sig,
        "tokens": sorted(words)[:80],
        "entities": entities[:20],
        "actions": actions[:20],
        "source": item.get("source") or "",
        "url": item.get("url") or item.get("source_url") or "",
        "title": item.get("title") or item.get("title_it") or item.get("source_title") or "",
        "ai_story_footprint": ai_fp,
        "text_sample": b[:500],
    }


def footprint_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    if not a or not b:
        return 0.0
    if a.get("story_signature") and a.get("story_signature") == b.get("story_signature"):
        return 1.0
    ta = set(a.get("tokens") or [])
    tb = set(b.get("tokens") or [])
    if not ta or not tb:
        return 0.0
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    ea, eb = set(a.get("entities") or []), set(b.get("entities") or [])
    aa, ab = set(a.get("actions") or []), set(b.get("actions") or [])
    entity_overlap = len(ea & eb) / max(1, min(len(ea), len(eb))) if ea and eb else 0.0
    action_overlap = len(aa & ab) / max(1, min(len(aa), len(ab))) if aa and ab else 0.0
    ai_a = set(str(a.get("ai_story_footprint") or "").split())
    ai_b = set(str(b.get("ai_story_footprint") or "").split())
    ai_overlap = len(ai_a & ai_b) / max(1, len(ai_a | ai_b)) if ai_a and ai_b else 0.0
    return round((jaccard * 0.45) + (entity_overlap * 0.25) + (action_overlap * 0.2) + (ai_overlap * 0.1), 4)


def is_source_opinion(item: dict[str, Any]) -> bool:
    b = " ".join([str(item.get("title") or ""), str(item.get("summary") or ""), str(item.get("source_title") or ""), str(item.get("body_html") or "")])
    review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
    review_text = " ".join(str(review.get(k) or "") for k in ["reason", "editorial_comment", "article_type", "source_material_type"])
    combined = f"{b} {review_text}"
    if any(p.search(combined) for p in OPINION_PATTERNS):
        return True
    if str(review.get("source_material_type") or "").lower() in {"opinion", "editorial", "commentary", "source_opinion"}:
        return True
    if str(review.get("priority_label") or "").lower() == "skip" and re.search(r"\b(opinion|editorial|commentary|personal take)\b", review_text, re.I):
        return True
    return False


def load_published_story_memory() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    history = load_json(PUBLISHER_HISTORY_FILE, {})
    if isinstance(history, dict):
        for item in history.values():
            if not isinstance(item, dict):
                continue
            sig = str(item.get("story_signature") or "") or story_signature(item)
            if sig:
                out[sig] = item
    raw = load_json(STORY_MEMORY_FILE, {"items": []})
    now = datetime.now(timezone.utc)
    for item in raw.get("items", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        sig = str(item.get("story_signature") or "")
        if not sig:
            continue
        added = parse_dt(item.get("added_at")) or now
        ttl = int(item.get("ttl_hours") or STORY_TTL_HOURS)
        if now - added <= timedelta(hours=ttl):
            out.setdefault(sig, item)
    return out


def load_story_footprints() -> list[dict[str, Any]]:
    raw = load_json(STORY_FOOTPRINT_FILE, {"items": []})
    items = raw.get("items", []) if isinstance(raw, dict) else []
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        added = parse_dt(item.get("added_at")) or now
        ttl = int(item.get("ttl_hours") or FOOTPRINT_TTL_HOURS)
        if now - added <= timedelta(hours=ttl):
            out.append(item)
    return out


def remember_stories(items: list[dict[str, Any]], *, reason: str) -> None:
    raw = load_json(STORY_MEMORY_FILE, {"items": []})
    existing = raw.get("items", []) if isinstance(raw, dict) else []
    by_sig: dict[str, dict[str, Any]] = {}
    now_dt = datetime.now(timezone.utc)
    for item in existing:
        if not isinstance(item, dict):
            continue
        sig = str(item.get("story_signature") or "")
        if not sig:
            continue
        added = parse_dt(item.get("added_at")) or now_dt
        ttl = int(item.get("ttl_hours") or STORY_TTL_HOURS)
        if now_dt - added <= timedelta(hours=ttl):
            by_sig[sig] = item
    now = utc_now()
    for item in items:
        sig = str(item.get("story_signature") or story_signature(item) or "")
        if not sig:
            continue
        by_sig[sig] = {"story_signature": sig, "title": item.get("title") or item.get("title_it") or item.get("source_title") or "", "url": item.get("url") or item.get("source_url") or "", "source": item.get("source") or "", "reason": reason, "added_at": now, "ttl_hours": STORY_TTL_HOURS}
    write_json(STORY_MEMORY_FILE, {"version": "v93_34_story_memory", "updated_at": now, "ttl_hours": STORY_TTL_HOURS, "items": list(by_sig.values())})


def remember_footprints(items: list[dict[str, Any]], *, reason: str) -> None:
    now = utc_now()
    existing = load_story_footprints()
    by_key: dict[str, dict[str, Any]] = {}
    for fp in existing:
        key = str(fp.get("story_signature") or fp.get("url") or fp.get("title") or "")
        if key:
            by_key[key] = fp
    for item in items:
        fp = story_footprint(item)
        key = str(fp.get("story_signature") or fp.get("url") or fp.get("title") or "")
        if not key:
            continue
        fp.update({"added_at": now, "ttl_hours": FOOTPRINT_TTL_HOURS, "reason": reason})
        by_key[key] = fp
    write_json(STORY_FOOTPRINT_FILE, {"version": "v93_34_story_footprints", "updated_at": now, "ttl_hours": FOOTPRINT_TTL_HOURS, "duplicate_threshold": FOOTPRINT_DUPLICATE_THRESHOLD, "items": list(by_key.values())})


def find_duplicate_by_footprint(item: dict[str, Any], footprints: list[dict[str, Any]], threshold: float = FOOTPRINT_DUPLICATE_THRESHOLD) -> tuple[dict[str, Any] | None, float]:
    fp = story_footprint(item)
    best: dict[str, Any] | None = None
    best_score = 0.0
    item_url = str(item.get("url") or item.get("source_url") or "")
    for old in footprints:
        if item_url and item_url == old.get("url"):
            continue
        score = footprint_similarity(fp, old)
        if score > best_score:
            best, best_score = old, score
    if best and best_score >= threshold:
        return best, best_score
    return None, best_score


def dedupe_against_memory(candidates: list[dict[str, Any]], memory: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    footprints = load_story_footprints()
    for item in candidates:
        clone = dict(item)
        sig = story_signature(clone)
        if sig:
            clone["story_signature"] = sig
        if sig and sig in memory:
            clone["decision"] = "hard_skip"
            clone["reason"] = "story_already_published_or_remembered"
            clone["duplicate_story_signature"] = sig
            clone["duplicate_of"] = memory[sig].get("url") or memory[sig].get("source_url")
            skipped.append(clone)
            continue
        duplicate, score = find_duplicate_by_footprint(clone, footprints)
        if duplicate:
            clone["decision"] = "hard_skip"
            clone["reason"] = f"story_footprint_overlap:{score}"
            clone["duplicate_story_signature"] = duplicate.get("story_signature")
            clone["duplicate_of"] = duplicate.get("url")
            clone["story_overlap_score"] = score
            skipped.append(clone)
        else:
            kept.append(clone)
    return kept, skipped


def dedupe_within_batch(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in candidates:
        duplicate, score = find_duplicate_by_footprint(item, [story_footprint(x) for x in kept], threshold=FOOTPRINT_DUPLICATE_THRESHOLD)
        if duplicate:
            loser = dict(item)
            loser["decision"] = "hard_skip"
            loser["reason"] = f"same_story_footprint_in_batch:{score}"
            loser["duplicate_story_signature"] = duplicate.get("story_signature")
            loser["duplicate_of"] = duplicate.get("url")
            loser["story_overlap_score"] = score
            skipped.append(loser)
        else:
            clone = dict(item)
            sig = story_signature(clone)
            if sig:
                clone["story_signature"] = sig
            kept.append(clone)
    return kept, skipped
