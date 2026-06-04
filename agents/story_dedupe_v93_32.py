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

STORY_TTL_HOURS = 96

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
    "raw", "smackdown", "collision", "impact", "new", "returns", "return", "set", "announced",
}


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
    parts = [
        item.get("title"), item.get("title_it"), item.get("source_title"), item.get("summary"),
        item.get("description"), item.get("excerpt"), item.get("excerpt_it"), item.get("url"), item.get("source_url"),
        meta.get("title"), meta.get("source_title"), meta.get("description"),
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


def story_signature(item: dict[str, Any]) -> str:
    b = blob(item)
    if not b:
        return ""

    # High-confidence explicit story signatures. These are intentionally conservative:
    # they catch recurring duplicate stories without blocking broad follow-ups.
    if "mjf" in b and any(x in b for x in ["injury", "infortun", "pulled", "rimosso", "rinunciare", "booking"]) and any(x in b for x in ["indie", "independent", "evento indipendente", "beyond wrestling"]):
        return "story:aew:mjf:indie_injury"
    if "jim ross" in b and any(x in b for x in ["lawsuit", "causa", "azionisti", "shareholder"]) and "vince" in b:
        return "story:wwe:vince_shareholder_lawsuit_jim_ross"
    if "liv morgan" in b and "dominik" in b and any(x in b for x in ["frustration", "frustrazione", "booking", "storyline"]):
        return "story:wwe:liv_morgan_dominik_booking_frustration"
    if "seth rollins" in b and any(x in b for x in ["youtube", "video", "interview", "intervista"]) and any(x in b for x in ["injury", "infortun", "triceps", "tricipite"]):
        return "story:wwe:seth_rollins_triceps_video"
    if "sol ruca" in b and any(x in b for x in ["structured", "strutturato", "match", "criticism", "criticata"]):
        return "story:nxt:sol_ruca_structured_match_criticism"

    # Generic fallback for very similar hard-news titles: named entity + two strongest action tokens.
    # Keep this conservative: only for short factual items with at least one distinctive name.
    words = [w for w in b.split() if len(w) >= 4 and w not in STOPWORDS]
    distinctive = []
    for w in words:
        if w not in distinctive:
            distinctive.append(w)
    if len(distinctive) >= 5:
        name_tokens = [w for w in distinctive if w in {"rollins", "strowman", "corbin", "amore", "knight", "femi", "gable", "stratus", "cena", "orton", "omega", "mone", "moné", "mjf"}]
        action_tokens = [w for w in distinctive if w in {"injury", "infortunio", "lawsuit", "causa", "stalking", "arrest", "released", "rilasciato", "contract", "contratto", "return", "ritorno", "debut", "infortun", "title", "titolo"}]
        if name_tokens and action_tokens:
            return "story:auto:" + ":".join((name_tokens[:2] + action_tokens[:2]))
    return ""


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
        by_sig[sig] = {
            "story_signature": sig,
            "title": item.get("title") or item.get("title_it") or item.get("source_title") or "",
            "url": item.get("url") or item.get("source_url") or "",
            "source": item.get("source") or "",
            "reason": reason,
            "added_at": now,
            "ttl_hours": STORY_TTL_HOURS,
        }
    write_json(STORY_MEMORY_FILE, {"version": "v93_32_story_memory", "updated_at": now, "ttl_hours": STORY_TTL_HOURS, "items": list(by_sig.values())})


def dedupe_against_memory(candidates: list[dict[str, Any]], memory: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
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
        else:
            kept.append(clone)
    return kept, skipped


def dedupe_within_batch(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for item in candidates:
        clone = dict(item)
        sig = story_signature(clone)
        if sig:
            clone["story_signature"] = sig
            groups.setdefault(sig, []).append(clone)
        else:
            passthrough.append(clone)
    kept: list[dict[str, Any]] = list(passthrough)
    skipped: list[dict[str, Any]] = []
    for sig, items in groups.items():
        ordered = sorted(items, key=story_sort_key, reverse=True)
        winner = ordered[0]
        winner["story_signature"] = sig
        kept.append(winner)
        for loser in ordered[1:]:
            loser["decision"] = "hard_skip"
            loser["reason"] = "same_story_duplicate_in_batch"
            loser["duplicate_story_signature"] = sig
            loser["duplicate_of"] = winner.get("url") or winner.get("source_url")
            skipped.append(loser)
    return kept, skipped
