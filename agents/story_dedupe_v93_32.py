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
STORY_FINGERPRINT_FILE = NEWSROOM_STATE_DIR / "story_fingerprints.json"

STORY_TTL_HOURS = 96
FOOTPRINT_TTL_HOURS = 168
FOOTPRINT_DUPLICATE_THRESHOLD = 0.62
FINGERPRINT_DUPLICATE_THRESHOLD = 0.78
FINGERPRINT_REVIEW_THRESHOLD = 0.65

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


# v93_36_generalized_story_fingerprint
CONNECTOR_WORDS = {
    "after", "before", "during", "amid", "despite", "following", "because", "over", "under", "against",
    "dopo", "prima", "durante", "nonostante", "contro", "verso", "tramite", "sulla", "sullo", "nella",
}
MEDIA_ID_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtube\.com/embed/|youtu\.be/|instagram\.com/(?:p|reel)/|twitter\.com/(?:i/status/|[^/]+/status/)|x\.com/[^/]+/status/)([A-Za-z0-9_-]{6,})", re.I)
QUOTE_RE = re.compile(r"[\"“”'‘’]([^\"“”'‘’]{8,220})[\"“”'‘’]")

ACTION_ALIASES = {
    "injury": {"injury", "injured", "infortunio", "infortun", "triceps", "tricipite", "medically", "cleared"},
    "return": {"return", "returns", "returned", "ritorno", "torna", "rientro", "back"},
    "debut": {"debut", "debutto", "esordio", "first"},
    "signing": {"sign", "signs", "firma", "accordo", "deal", "partnership", "distribution", "distribuzione"},
    "match_announcement": {"match", "announced", "annuncia", "confirmed", "confermato", "card", "title", "titolo"},
    "social_reply": {"fan", "reply", "responds", "risponde", "tells", "dice", "youtube", "instagram"},
    "legal": {"lawsuit", "trial", "court", "legal", "causa", "processo", "tribunale", "accused", "accusato"},
    "creative_plans": {"creative", "plans", "piani", "storyline", "booking", "feud", "angle"},
    "departure": {"leaves", "gone", "depart", "release", "released", "lascia", "rilasciato", "free", "agent"},
}

BRAND_TERMS = {"wwe", "nxt", "aew", "tna", "roh", "njpw", "cmll", "stardom", "ovw", "indie", "myAew".lower(), "myaew", "produce"}


def normalized_words(value: Any) -> list[str]:
    return [w for w in clean(value).split() if len(w) >= 3 and w not in STOPWORDS and w not in CONNECTOR_WORDS]


def extract_media_ids_from_blob(raw: str) -> list[str]:
    out: list[str] = []
    for m in MEDIA_ID_RE.finditer(str(raw or "")):
        token = m.group(1).strip().lower()
        if token and token not in out:
            out.append(token)
    return out[:10]


def extract_quote_claims(raw: str) -> list[str]:
    claims: list[str] = []
    for m in QUOTE_RE.finditer(str(raw or "")):
        q = clean(m.group(1))
        if len(q) >= 8 and q not in claims:
            claims.append(q[:180])
    return claims[:8]


def infer_action(words: set[str]) -> str:
    best = ""
    best_count = 0
    for action, aliases in ACTION_ALIASES.items():
        count = len(words & aliases)
        if count > best_count:
            best = action
            best_count = count
    return best or "general_update"


def build_generalized_fingerprint(item: dict[str, Any]) -> dict[str, Any]:
    meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
    review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
    raw_parts = [
        item.get("title"), item.get("source_title"), item.get("title_it"), item.get("summary"), item.get("description"),
        item.get("excerpt"), item.get("excerpt_it"), item.get("url"), item.get("source_url"), item.get("body_html"),
        meta.get("title"), meta.get("source_title"), meta.get("description"),
        review.get("event_key"), review.get("editorial_reason"), review.get("canonical_summary"), review.get("story_footprint"),
    ]
    raw = " ".join(str(x or "") for x in raw_parts)
    words = normalized_words(raw)
    word_set = set(words)
    media_ids = extract_media_ids_from_blob(raw)
    quoted_claims = extract_quote_claims(raw)
    entities = sorted([w for w in word_set if w in ENTITY_HINTS or w in BRAND_TERMS])[:18]
    action = str(review.get("news_action") or review.get("event_key") or "").strip().lower()
    if not action:
        action = infer_action(word_set)
    action = re.sub(r"[^a-z0-9_:-]+", "_", action).strip("_") or "general_update"
    action_terms: list[str] = []
    if action in ACTION_ALIASES:
        action_terms = sorted(word_set & ACTION_ALIASES[action])
    else:
        for aliases in ACTION_ALIASES.values():
            action_terms.extend(sorted(word_set & aliases))
    # Story object: distinctive non-entity tokens, preserving the factual object while avoiding full-title duplication.
    object_terms = [w for w in words if w not in entities and w not in action_terms and w not in BRAND_TERMS]
    distinctive: list[str] = []
    for w in object_terms:
        if w not in distinctive:
            distinctive.append(w)
    return {
        "version": "v93_36_generalized_story_fingerprint",
        "main_subjects": entities[:8],
        "news_action": action,
        "news_object_terms": distinctive[:18],
        "event_context": sorted([w for w in word_set if w in BRAND_TERMS])[:8],
        "media_ids": media_ids,
        "quoted_claims": quoted_claims,
        "canonical_summary": clean(" ".join(str(x or "") for x in [item.get("title") or item.get("source_title"), item.get("summary") or meta.get("description")]))[:500],
        "source": item.get("source") or "",
        "url": item.get("url") or item.get("source_url") or "",
        "title": item.get("title") or item.get("title_it") or item.get("source_title") or "",
    }


def set_overlap(a: list[str], b: list[str], *, relative_to_min: bool = True) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    denom = min(len(sa), len(sb)) if relative_to_min else len(sa | sb)
    return len(sa & sb) / max(1, denom)


def fingerprint_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    if not a or not b:
        return 0.0
    media_overlap = set_overlap(a.get("media_ids", []), b.get("media_ids", []), relative_to_min=True)
    if media_overlap >= 1.0 and set_overlap(a.get("main_subjects", []), b.get("main_subjects", []), relative_to_min=True) > 0:
        return 0.98
    quote_overlap = set_overlap(a.get("quoted_claims", []), b.get("quoted_claims", []), relative_to_min=True)
    subject_overlap = set_overlap(a.get("main_subjects", []), b.get("main_subjects", []), relative_to_min=True)
    object_overlap = set_overlap(a.get("news_object_terms", []), b.get("news_object_terms", []), relative_to_min=False)
    context_overlap = set_overlap(a.get("event_context", []), b.get("event_context", []), relative_to_min=True)
    action_match = 1.0 if str(a.get("news_action") or "") == str(b.get("news_action") or "") else 0.0
    if subject_overlap < 0.34 and media_overlap == 0 and quote_overlap == 0:
        return round((object_overlap * 0.25) + (context_overlap * 0.15) + (action_match * 0.1), 4)
    score = (subject_overlap * 0.26) + (action_match * 0.24) + (object_overlap * 0.24) + (context_overlap * 0.08) + (media_overlap * 0.12) + (quote_overlap * 0.06)
    return round(score, 4)


def load_story_fingerprints() -> list[dict[str, Any]]:
    raw = load_json(STORY_FINGERPRINT_FILE, {"items": []})
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


def remember_fingerprints(items: list[dict[str, Any]], *, reason: str) -> None:
    now = utc_now()
    existing = load_story_fingerprints()
    by_key: dict[str, dict[str, Any]] = {}
    for old in existing:
        key = str(old.get("url") or old.get("title") or json.dumps(old.get("fingerprint", {}), sort_keys=True))
        if key:
            by_key[key] = old
    for item in items:
        fp = build_generalized_fingerprint(item)
        key = str(fp.get("url") or fp.get("title") or json.dumps(fp, sort_keys=True))
        if not key:
            continue
        by_key[key] = {"fingerprint": fp, "url": fp.get("url"), "title": fp.get("title"), "source": fp.get("source"), "added_at": now, "ttl_hours": FOOTPRINT_TTL_HOURS, "reason": reason}
    write_json(STORY_FINGERPRINT_FILE, {"version": "v93_36_generalized_story_fingerprints", "updated_at": now, "ttl_hours": FOOTPRINT_TTL_HOURS, "duplicate_threshold": FINGERPRINT_DUPLICATE_THRESHOLD, "review_threshold": FINGERPRINT_REVIEW_THRESHOLD, "items": list(by_key.values())})


def find_duplicate_by_fingerprint(item: dict[str, Any], fingerprints: list[dict[str, Any]], threshold: float = FINGERPRINT_DUPLICATE_THRESHOLD) -> tuple[dict[str, Any] | None, float]:
    fp = build_generalized_fingerprint(item)
    item_url = str(item.get("url") or item.get("source_url") or "")
    best: dict[str, Any] | None = None
    best_score = 0.0
    for old in fingerprints:
        old_fp = old.get("fingerprint") if isinstance(old.get("fingerprint"), dict) else old
        if item_url and item_url == old.get("url"):
            continue
        score = fingerprint_similarity(fp, old_fp)
        if score > best_score:
            best = old
            best_score = score
    if best and best_score >= threshold:
        return best, best_score
    return None, best_score


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
    fp = build_generalized_fingerprint(item)
    subjects = ":".join(fp.get("main_subjects", [])[:4])
    action = str(fp.get("news_action") or "general_update")
    obj = ":".join(fp.get("news_object_terms", [])[:6])
    media = ":".join(fp.get("media_ids", [])[:2])
    if not subjects and not obj and not media:
        return ""
    return "story:fp:" + ":".join(x for x in [subjects, action, obj, media] if x)

def story_footprint(item: dict[str, Any]) -> dict[str, Any]:
    b = blob(item)
    words = token_set(item)
    entities = sorted([w for w in words if w in ENTITY_HINTS])
    actions = sorted([w for w in words if w in ACTION_HINTS])
    sig = story_signature(item)
    review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
    ai_fp = clean(review.get("story_footprint") or "") if isinstance(review, dict) else ""
    fp = build_generalized_fingerprint(item)
    return {
        "story_signature": sig,
        "tokens": sorted(words)[:80],
        "entities": entities[:20],
        "actions": actions[:20],
        "fingerprint": fp,
        "main_subjects": fp.get("main_subjects", []),
        "news_action": fp.get("news_action", ""),
        "news_object_terms": fp.get("news_object_terms", []),
        "event_context": fp.get("event_context", []),
        "media_ids": fp.get("media_ids", []),
        "quoted_claims": fp.get("quoted_claims", []),
        "source": item.get("source") or "",
        "url": item.get("url") or item.get("source_url") or "",
        "title": item.get("title") or item.get("title_it") or item.get("source_title") or "",
        "ai_story_footprint": ai_fp,
        "text_sample": b[:500],
    }


def footprint_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    if not a or not b:
        return 0.0
    afp = a.get("fingerprint") if isinstance(a.get("fingerprint"), dict) else a
    bfp = b.get("fingerprint") if isinstance(b.get("fingerprint"), dict) else b
    gen_score = fingerprint_similarity(afp, bfp)
    if gen_score >= FINGERPRINT_DUPLICATE_THRESHOLD:
        return gen_score
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
    write_json(STORY_FOOTPRINT_FILE, {"version": "v93_36_story_footprints", "updated_at": now, "ttl_hours": FOOTPRINT_TTL_HOURS, "duplicate_threshold": FOOTPRINT_DUPLICATE_THRESHOLD, "items": list(by_key.values())})


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
    fingerprints = load_story_fingerprints()
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
        duplicate_fp, fp_score = find_duplicate_by_fingerprint(clone, fingerprints)
        if duplicate_fp:
            clone["decision"] = "hard_skip"
            clone["reason"] = f"story_fingerprint_overlap:{fp_score}"
            clone["duplicate_of"] = duplicate_fp.get("url")
            clone["story_overlap_score"] = fp_score
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
