from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from agents.gemini_ledger import make_operation_id, record_gemini_attempt

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

MASSY_BOARD_FILE = NEWSROOM_STATE_DIR / "massy_board_latest.json"
MENZO_DECISIONS_FILE = NEWSROOM_STATE_DIR / "menzo_decisions_latest.json"
V92_ALLOWED_URLS_FILE = NEWSROOM_STATE_DIR / "v92_allowed_news_urls.json"
ARTIFACT_DECISIONS_FILE = ARTIFACT_DIR / "menzo_decisions.json"

MENZO_VERSION = "v93_13_ai_editorial_review"
AI_ENABLED = str(os.getenv("V93_MENZO_AI_ENABLED", "1")).strip().lower() not in {"0", "false", "no", "off"}
AI_TOP_N = int(os.getenv("V93_MENZO_AI_TOP_N", "12"))
MODEL_CHAIN = [m.strip() for m in os.getenv(
    "GEMINI_MODEL_CHAIN",
    "gemini-3.1-flash-lite,gemini-3.5-flash,gemini-2.5-flash-lite,gemini-2.5-flash",
).split(",") if m.strip()]

HARD_SIGNALS = {
    "death": 100,
    "passes away": 100,
    "arrested": 92,
    "lawsuit": 88,
    "legal": 82,
    "injury": 86,
    "injured": 86,
    "surgery": 82,
    "fired": 84,
    "departs": 76,
    "signs": 80,
    "contract": 78,
    "returning": 78,
    "returns": 76,
    "return": 72,
    "debut": 78,
    "title change": 82,
    "new champion": 82,
    "championship": 68,
    "acquisition": 88,
    "media rights": 86,
    "tv deal": 84,
    "netflix": 76,
    "tko": 74,
    "moves to smackdown": 80,
    "moves to raw": 80,
    "moves to nxt": 78,
    "lineup": 62,
    "bracket": 66,
}

STRATEGIC_SIGNALS = {
    "creative": 66,
    "booking": 62,
    "plans": 64,
    "reportedly": 62,
    "backstage": 60,
    "future": 58,
    "main roster": 60,
    "queen of the ring": 58,
    "king of the ring": 58,
    "clash in italy": 58,
    "raw": 54,
    "smackdown": 54,
}

ENTITY_SIGNALS = {
    "roman reigns": 10,
    "cody rhodes": 10,
    "cm punk": 10,
    "john cena": 10,
    "the rock": 10,
    "brock lesnar": 10,
    "paul heyman": 8,
    "rhea ripley": 8,
    "becky lynch": 8,
    "seth rollins": 8,
    "liv morgan": 8,
    "gunther": 8,
    "mercedes mone": 8,
    "chad gable": 8,
    "finn balor": 8,
    "finn bálor": 8,
    "iyo sky": 8,
    "iyo skye": 8,
    "oba femi": 8,
    "mick foley": 5,
    "kevin nash": 5,
}

SOFT_OR_SKIP_SIGNALS = {
    "addresses": -8,
    "explains why": -6,
    "recalls": -10,
    "reflects": -10,
    "identifies": -6,
    "reacts": -10,
    "reaction": -12,
    "social media": -14,
    "photo": -16,
    "photos": -16,
    "jokes": -14,
    "breaks silence": -4,
    "open to": -10,
    "comments from": -8,
    "documentary": -12,
    "docuseries": -12,
}

HARD_SKIP_PATTERNS = [
    (re.compile(r"\b\d+\s+things\s+(we\s+)?(hated|loved|learned)\b", re.I), "listicle_low_value"),
    (re.compile(r"\b(draws\s*(?:and|&)\s*duds|duds\s*(?:and|&)\s*draws)\b", re.I), "draws_and_duds_low_value"),
    (re.compile(r"\bpreview\b.*\b(start\s*time|how\s+to\s+watch|confirmed\s+matches)\b", re.I), "generic_preview"),
]

RATINGS_PATTERNS = [re.compile(r"\b(ratings?|viewership|demo|p18\s*49|viewers|ascolti)\b", re.I)]
RELEASED_DATA_PATTERNS = [
    re.compile(r"\b(data|numbers|ratings?|viewership|figures)\s+(has|have|was|were)?\s*(been\s*)?released\b", re.I),
    re.compile(r"\breleased\s+(ratings?|viewership|figures|data|numbers)\b", re.I),
]
ROSTER_TRADE_PATTERN = re.compile(
    r"\b(trade|traded|moves?\s+to|moved\s+to)\b.*\b(raw|smackdown|nxt|wwe|brand|roster|draft|judgment\s+day|judgement\s+day)\b|"
    r"\b(raw|smackdown|nxt|wwe|brand|roster|draft|judgment\s+day|judgement\s+day)\b.*\b(trade|traded|moves?\s+to|moved\s+to)\b",
    re.I,
)
EXTERNAL_SPORTS_PATTERN = re.compile(
    r"\b(nfl|nba|mlb|nhl|browns|cleveland|myles\s+garrett|garrett|sacks?|playoffs?|draft\s+picks?|quarterback|touchdown|football|basketball|baseball|hockey)\b",
    re.I,
)
CELEBRITY_REACTION_PATTERN = re.compile(r"\b(reacts?|reaction|begs|jokes|responds?|comments?)\b", re.I)
CURRENT_PRIORITY_PATTERNS = [
    (re.compile(r"\bmajor changes?\b.*\b(king|queen)\s+of\s+the\s+ring\b|\b(king|queen)\s+of\s+the\s+ring\b.*\bmajor changes?\b", re.I), 20, "current:tournament_changes"),
    (ROSTER_TRADE_PATTERN, 18, "current:roster_move"),
    (re.compile(r"\bnetflix\b.*\b(aaa|wwe|replay|unmasking)\b", re.I), 16, "current:netflix_aaa"),
    (re.compile(r"\b(call(?:s)?\s+out|confronts?)\b.*\b(brock lesnar|roman reigns|cody rhodes|cm punk)\b", re.I), 12, "current:major_storyline"),
    (re.compile(r"\b(plaintiffs?|lawsuit|evidence|espn)\b", re.I), 10, "current:business_legal"),
]
EVERGREEN_TERMS = {"lawsuit", "legal", "media rights", "tv deal", "tko", "contract", "acquisition"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


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


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9àèéìòùáíóúäëïöüñç]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_published(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value)
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def age_hours(item: dict[str, Any]) -> float | None:
    dt = parse_published(item.get("published"))
    if not dt:
        return None
    return max(0.0, (now_dt() - dt).total_seconds() / 3600.0)


def category_hint(item: dict[str, Any]) -> str:
    blob = normalize(f"{item.get('title', '')} {item.get('summary', '')} {item.get('url', '')}")
    if "nxt" in blob:
        return "NXT"
    if "aew" in blob or "dynamite" in blob or "collision" in blob:
        return "AEW"
    if "tna" in blob or "impact" in blob:
        return "TNA"
    if "roh" in blob:
        return "ROH"
    if "tko" in blob or "media rights" in blob or "tv deal" in blob or "espn" in blob or "lawsuit" in blob:
        return "Business"
    if "wwe" in blob or "raw" in blob or "smackdown" in blob or "roman reigns" in blob or "cody rhodes" in blob:
        return "WWE"
    return "World"


def is_ratings_report(raw_blob: str) -> bool:
    return any(pattern.search(raw_blob) for pattern in RATINGS_PATTERNS)


def is_released_data_context(raw_blob: str) -> bool:
    return any(pattern.search(raw_blob) for pattern in RELEASED_DATA_PATTERNS)


def has_evergreen_signal(blob: str) -> bool:
    return any(term in blob for term in EVERGREEN_TERMS)


def is_external_sports_reaction(raw_blob: str) -> bool:
    return bool(EXTERNAL_SPORTS_PATTERN.search(raw_blob) and CELEBRITY_REACTION_PATTERN.search(raw_blob))


def is_external_sports_trade(raw_blob: str) -> bool:
    return bool(EXTERNAL_SPORTS_PATTERN.search(raw_blob) and re.search(r"\b(trade|traded|deal|signs?|contract)\b", raw_blob, re.I) and not ROSTER_TRADE_PATTERN.search(raw_blob))


def apply_recency(score: int, reasons: list[str], item: dict[str, Any], blob: str) -> int:
    hours = age_hours(item)
    if hours is None:
        reasons.append("recency:unknown")
        return score - 4
    if hours <= 12:
        reasons.append("recency:fresh_12h")
        return score + 8
    if hours <= 36:
        reasons.append("recency:fresh_36h")
        return score + 4
    if hours <= 72:
        reasons.append("recency:recent_72h")
        return score
    if has_evergreen_signal(blob):
        reasons.append("recency:old_but_evergreen")
        return score - 8
    reasons.append("recency:old_penalty")
    return score - 35


def classify_item(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    url = str(item.get("url") or "")
    blob = normalize(f"{title} {summary} {url}")
    raw_blob = f"{title} {summary} {url}"
    for pattern, reason in HARD_SKIP_PATTERNS:
        if pattern.search(raw_blob):
            return {"decision": "skip", "article_type": "low_value", "priority": "skip", "score": 0, "reason": reason}
    if is_external_sports_reaction(raw_blob) or is_external_sports_trade(raw_blob):
        return {"decision": "skip", "article_type": "external_sports_reaction", "priority": "skip", "score": 18, "reason": "skip:external_sports_context_not_core_wrestling"}
    score = 30
    reasons: list[str] = []
    article_type = "standard_useful"
    ratings_report = is_ratings_report(raw_blob)
    released_data_context = is_released_data_context(raw_blob)
    for term, value in HARD_SIGNALS.items():
        if term in blob:
            if term == "released" and released_data_context:
                reasons.append("disambiguated:released_data_not_hard_news")
                continue
            score = max(score, value)
            reasons.append(f"hard:{term}")
            article_type = "hard_news"
    if re.search(r"\btrade\b|\btraded\b", raw_blob, re.I):
        if ROSTER_TRADE_PATTERN.search(raw_blob):
            score = max(score, 80)
            reasons.append("hard:trade_roster_context")
            article_type = "hard_news"
        else:
            score -= 18
            reasons.append("disambiguated:trade_not_roster_context")
    for term, value in STRATEGIC_SIGNALS.items():
        if term in blob:
            score = max(score, value)
            reasons.append(f"strategic:{term}")
            if article_type != "hard_news":
                article_type = "strategic_discussion"
    entity_bonus = 0
    for term, value in ENTITY_SIGNALS.items():
        if term in blob:
            entity_bonus += value
            reasons.append(f"entity:{term}")
    score += min(entity_bonus, 16)
    for pattern, value, reason in CURRENT_PRIORITY_PATTERNS:
        if pattern.search(raw_blob):
            score += value
            reasons.append(reason)
            if article_type == "standard_useful":
                article_type = "strategic_discussion"
    for term, value in SOFT_OR_SKIP_SIGNALS.items():
        if term in blob:
            score += value
            reasons.append(f"soft_penalty:{term}")
    if ratings_report:
        if re.search(r"\b(record|highest|lowest|massive|huge|surge|best|worst)\b", raw_blob, re.I):
            score += 4
            reasons.append("ratings:exceptional_signal")
        else:
            score -= 18
            reasons.append("ratings:generic_penalty")
            if article_type == "hard_news":
                article_type = "data_report"
    score = apply_recency(score, reasons, item, blob)
    score = max(0, min(int(score), 100))
    if score >= 75:
        decision = "selected"
        priority = "hard"
        if article_type not in {"data_report", "strategic_discussion"}:
            article_type = "hard_news"
    elif score >= 62:
        decision = "selected"
        priority = "soft"
    elif score >= 50:
        decision = "pending"
        priority = "soft"
        if article_type == "standard_useful":
            article_type = "soft_news"
    else:
        decision = "skip"
        priority = "skip"
        article_type = "low_value"
    return {"decision": decision, "article_type": article_type, "priority": priority, "score": score, "deterministic_score": score, "reason": ",".join(reasons[:16]) or "menzo_baseline"}


def sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    hours = age_hours(item)
    freshness = 999999.0 if hours is None else hours
    return int(item.get("score") or 0), -freshness, str(item.get("published") or "")


def compact_for_ai(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        ai_id = f"c{idx}"
        item["ai_id"] = ai_id
        compact.append({
            "id": ai_id,
            "title": str(item.get("title") or "")[:220],
            "summary": str(item.get("summary") or "")[:500],
            "source": item.get("source"),
            "url": item.get("url"),
            "published": item.get("published"),
            "deterministic_score": item.get("score"),
            "deterministic_reason": item.get("reason"),
            "category_hint": item.get("category_hint"),
            "age_hours": item.get("age_hours"),
        })
    return compact


def build_ai_prompt(items: list[dict[str, Any]]) -> str:
    return f"""Sei Menzo, responsabile editoriale di OpenWrestlingTV.

Valuta questi candidati wrestling usando solo titolo, summary, fonte, URL e data. Devi aiutare la redazione a scegliere cosa pubblicare e dare a Bob istruzioni operative.

Obiettivi:
- pubblicare notizie realmente utili per il pubblico italiano di wrestling;
- evitare duplicati dello stesso evento/notizia tra fonti diverse;
- evitare curiosita' deboli, social reaction, sport esterno, rating generici, listicle, vecchie notizie superate;
- correggere categoria: WWE, AEW, NXT, TNA, ROH, World, Business;
- segnalare a Bob se deve aspettarsi embed, video, tweet, citazioni, tabelle, bio autore, social bar o CTA.

Rispondi SOLO in JSON valido:
{{
  "reviews": [
    {{
      "id": "c1",
      "decision": "selected|pending|skip",
      "priority": 0,
      "category_hint": "WWE|AEW|NXT|TNA|ROH|World|Business",
      "article_type": "hard_news|storyline_development|business_legal|data_report|soft_news|low_value|duplicate",
      "event_key": "chiave breve uguale per notizie duplicate sullo stesso fatto",
      "duplicate_of": "c2 oppure stringa vuota",
      "editorial_reason": "motivo breve in italiano",
      "bob_brief": {{
        "expected_embeds": ["x_tweet", "youtube", "instagram", "video"],
        "expected_quotes": true,
        "expected_tables": false,
        "possible_noise": ["source_social_bar", "author_bio", "cta", "share_links"],
        "must_preserve": ["embed video/tweet se presente", "citazioni dirette"],
        "source_specific_notes": "nota breve per Bob"
      }}
    }}
  ]
}}

Regole importanti:
- Se due articoli parlano dello stesso fatto, seleziona uno solo e marca gli altri skip con article_type duplicate e duplicate_of.
- Se una fonte sembra avere video/tweet embed dal titolo o summary, aggiungilo in expected_embeds.
- Se e' una reaction social/sport esterno o curiosita' non centrale, abbassa molto priority.
- Se e' una notizia WWE/AEW/TNA/ROH/NXT fresca con conseguenza narrativa, aumenta priority.

CANDIDATI:
{json.dumps(items, ensure_ascii=False, indent=2)}
"""


def call_gemini(prompt: str) -> tuple[str, str, list[str]]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    attempts: list[str] = []
    if not api_key:
        return "", "missing_api_key", attempts
    last_error = ""
    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=api_key)
        operation_id = make_operation_id("Menzo", "ai_editorial_review", "batch")
        for attempt_index, model in enumerate(MODEL_CHAIN):
            attempts.append(model)
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                text = getattr(response, "text", "") or ""
                record_gemini_attempt(response=response, agent="Menzo", phase="ai_editorial_review", model_requested=model, status="called", reason="ai_editorial_review", result="text" if text.strip() else "empty_response", operation_id=operation_id, attempt_index=attempt_index, fallback=attempt_index > 0)
                if text.strip():
                    return text.strip(), model, attempts
            except Exception as exc:
                last_error = f"{model}: {exc}"
                record_gemini_attempt(response=None, agent="Menzo", phase="ai_editorial_review", model_requested=model, status="failed", reason="ai_editorial_review", result=str(exc)[:500], operation_id=operation_id, attempt_index=attempt_index, fallback=attempt_index > 0)
    except Exception as exc:
        last_error = f"genai_import_or_client_error: {exc}"
    return "", last_error or "empty_response", attempts


def parse_ai_json(raw: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.I).strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {"reviews": []}
    except Exception:
        return {"reviews": [], "parse_error": True, "raw_preview": raw[:2000]}


def apply_ai_review(items: list[dict[str, Any]]) -> dict[str, Any]:
    ai_result: dict[str, Any] = {"enabled": AI_ENABLED, "used": False, "model": None, "attempts": [], "reviews": [], "error": ""}
    if not AI_ENABLED or not items:
        return ai_result
    candidates = sorted(items, key=sort_key, reverse=True)[:AI_TOP_N]
    prompt_items = compact_for_ai(candidates)
    raw, model_or_error, attempts = call_gemini(build_ai_prompt(prompt_items))
    ai_result.update({"model": model_or_error, "attempts": attempts, "used": bool(raw), "prompt_count": len(prompt_items)})
    if not raw:
        ai_result["error"] = model_or_error
        return ai_result
    parsed = parse_ai_json(raw)
    reviews = parsed.get("reviews") if isinstance(parsed.get("reviews"), list) else []
    ai_result["reviews"] = reviews
    ai_result["raw_preview"] = raw[:4000]
    review_by_id = {str(r.get("id")): r for r in reviews if isinstance(r, dict) and r.get("id")}
    for item in candidates:
        review = review_by_id.get(str(item.get("ai_id")))
        if not review:
            continue
        item["menzo_ai_review"] = review
        try:
            ai_priority = max(0, min(100, int(review.get("priority", item.get("score", 0)))))
        except Exception:
            ai_priority = int(item.get("score", 0) or 0)
        det = int(item.get("score", 0) or 0)
        item["ai_priority"] = ai_priority
        item["score"] = int(round(det * 0.55 + ai_priority * 0.45))
        if str(review.get("category_hint") or "") in {"WWE", "AEW", "NXT", "TNA", "ROH", "World", "Business"}:
            item["category_hint"] = review.get("category_hint")
        if review.get("article_type"):
            item["article_type"] = str(review.get("article_type"))
        if review.get("editorial_reason"):
            item["ai_editorial_reason"] = str(review.get("editorial_reason"))
        if isinstance(review.get("bob_brief"), dict):
            item["bob_brief"] = review.get("bob_brief")
        decision = str(review.get("decision") or "").lower()
        if decision in {"selected", "pending", "skip"}:
            item["decision"] = decision
            item["priority"] = "hard" if item["score"] >= 75 else ("soft" if item["score"] >= 50 else "skip")
        duplicate_of = str(review.get("duplicate_of") or "").strip()
        if duplicate_of:
            item["decision"] = "skip"
            item["priority"] = "skip"
            item["article_type"] = "duplicate"
            item["duplicate_of"] = duplicate_of
            item["reason"] = f"ai_duplicate_of:{duplicate_of}; {item.get('reason', '')}"
        else:
            item["reason"] = f"ai:{item.get('ai_editorial_reason', '')}; deterministic:{item.get('reason', '')}".strip()
    # Defensive duplicate pass by event_key in case Gemini forgets duplicate_of.
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
        key = normalize(str(review.get("event_key") or ""))
        if key:
            groups.setdefault(key, []).append(item)
    for key, group in groups.items():
        if len(group) <= 1:
            continue
        winner = sorted(group, key=sort_key, reverse=True)[0]
        for item in group:
            if item is winner:
                continue
            item["decision"] = "skip"
            item["priority"] = "skip"
            item["article_type"] = "duplicate"
            item["duplicate_of"] = winner.get("ai_id")
            item["reason"] = f"ai_duplicate_event:{key}; {item.get('reason', '')}"
    return ai_result


def run_menzo(massy_board: dict[str, Any] | None = None, *, apply_capacity_limits: bool = True, persist_outputs: bool = True) -> dict[str, Any]:
    board = massy_board if isinstance(massy_board, dict) else load_json(MASSY_BOARD_FILE, {})
    candidates = board.get("news_candidates_for_menzo", []) if isinstance(board, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    max_selected = int(os.getenv("V93_MENZO_MAX_SELECTED_PER_RUN", "6"))
    max_pending = int(os.getenv("V93_MENZO_MAX_PENDING_PER_RUN", "12"))
    evaluated: list[dict[str, Any]] = []
    print(f"[MENZO v93.13] Avvio decisione editoriale AI | candidates={len(candidates)}", flush=True)
    for candidate in candidates:
        item = dict(candidate)
        classification = classify_item(item)
        item.update(classification)
        item["agent"] = "Menzo"
        item["category_hint"] = category_hint(item)
        item["age_hours"] = age_hours(item)
        item["evaluated_at"] = utc_now()
        evaluated.append(item)
    ai_result = apply_ai_review(evaluated)
    selected: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for item in evaluated:
        if item["decision"] == "selected":
            selected.append(item)
        elif item["decision"] == "pending":
            pending.append(item)
        else:
            skipped.append(item)
    selected = sorted(selected, key=sort_key, reverse=True)
    pending = sorted(pending, key=sort_key, reverse=True)
    overflow: list[dict[str, Any]] = []
    if apply_capacity_limits:
        overflow = selected[max_selected:]
        selected = selected[:max_selected]
        for item in overflow:
            item = dict(item)
            item["decision"] = "pending"
            item["reason"] = f"selected_overflow:{item.get('reason', '')}"
            pending.append(item)
        pending = sorted(pending, key=sort_key, reverse=True)[:max_pending]
    else:
        pending = sorted(pending, key=sort_key, reverse=True)
    allowed_urls = [str(item.get("url") or item.get("source_url") or "") for item in selected if item.get("url") or item.get("source_url")]
    result = {
        "agent": "Menzo",
        "version": MENZO_VERSION,
        "generated_at": utc_now(),
        "mode": "ai_editorial_review_with_bob_briefs",
        "daily_policy": {"target_min": 20, "target_max": 30, "reports_excluded": True, "max_selected_this_run": max_selected, "max_pending_this_run": max_pending, "base_capacity_limits_applied": apply_capacity_limits, "base_outputs_persisted": persist_outputs},
        "policy": {
            "recency_penalty_after_72h": True,
            "released_data_disambiguation": True,
            "ratings_reports_penalized_unless_exceptional": True,
            "current_storyline_and_roster_boosts": True,
            "trade_requires_wrestling_roster_context": True,
            "external_sports_reactions_are_skipped": True,
            "gemini_editorial_review": AI_ENABLED,
            "bob_briefs_enabled": True,
            "ai_duplicate_detection": True,
        },
        "input": {"massy_version": board.get("version") if isinstance(board, dict) else None, "candidate_count": len(candidates), "base_capacity_limits_applied": apply_capacity_limits, "base_outputs_persisted": persist_outputs},
        "menzo_ai": ai_result,
        "selected": selected,
        "pending": pending,
        "skipped": skipped,
        "allowed_urls_for_v92": allowed_urls,
        "handoff": {"to_bob_or_v92": len(selected), "pending": len(pending), "skipped": len(skipped)},
    }
    if persist_outputs:
        write_json(ARTIFACT_DECISIONS_FILE, result)
        write_json(MENZO_DECISIONS_FILE, result)
        write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": MENZO_VERSION, "allowed_urls": allowed_urls})
    print(f"[MENZO v93.13] Decisione pronta | selected={len(selected)} pending={len(pending)} skipped={len(skipped)} ai_used={ai_result.get('used')} allowed_for_v92={len(allowed_urls)}", flush=True)
    return result


if __name__ == "__main__":
    result = run_menzo()
    print(json.dumps(result.get("handoff", {}), ensure_ascii=False, indent=2))
