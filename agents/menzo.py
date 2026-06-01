from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

MASSY_BOARD_FILE = NEWSROOM_STATE_DIR / "massy_board_latest.json"
MENZO_DECISIONS_FILE = NEWSROOM_STATE_DIR / "menzo_decisions_latest.json"
V92_ALLOWED_URLS_FILE = NEWSROOM_STATE_DIR / "v92_allowed_news_urls.json"
ARTIFACT_DECISIONS_FILE = ARTIFACT_DIR / "menzo_decisions.json"

MENZO_VERSION = "v93_2_menzo_editorial_director"

HARD_SIGNALS = {
    "death": 100,
    "passes away": 100,
    "arrested": 92,
    "lawsuit": 88,
    "injury": 86,
    "injured": 86,
    "surgery": 82,
    "released": 84,
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
}

ENTITY_SIGNALS = {
    "roman reigns": 10,
    "cody rhodes": 10,
    "cm punk": 10,
    "john cena": 10,
    "the rock": 10,
    "rhea ripley": 8,
    "becky lynch": 8,
    "seth rollins": 8,
    "liv morgan": 8,
    "gunther": 8,
    "mercedes mone": 8,
    "kevin nash": 5,
}

SOFT_OR_SKIP_SIGNALS = {
    "addresses": -8,
    "explains why": -6,
    "recalls": -10,
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
}

HARD_SKIP_PATTERNS = [
    (re.compile(r"\b\d+\s+things\s+(we\s+)?(hated|loved|learned)\b", re.I), "listicle_low_value"),
    (re.compile(r"\b(draws\s*(?:and|&)\s*duds|duds\s*(?:and|&)\s*draws)\b", re.I), "draws_and_duds_low_value"),
    (re.compile(r"\bpreview\b.*\b(start\s*time|how\s+to\s+watch|confirmed\s+matches)\b", re.I), "generic_preview"),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def category_hint(item: dict[str, Any]) -> str:
    blob = normalize(f"{item.get('title', '')} {item.get('summary', '')} {item.get('url', '')}")
    if "nxt" in blob:
        return "NXT"
    if "aew" in blob or "dynamite" in blob or "collision" in blob:
        return "AEW"
    if "tna" in blob or "impact" in blob:
        return "TNA"
    if "wwe" in blob or "raw" in blob or "smackdown" in blob or "roman reigns" in blob or "cody rhodes" in blob:
        return "WWE"
    if "tko" in blob or "media rights" in blob or "tv deal" in blob or "netflix" in blob:
        return "Business"
    return "World"


def classify_item(item: dict[str, Any]) -> dict[str, Any]:
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    blob = normalize(f"{title} {summary} {item.get('url', '')}")
    raw_blob = f"{title} {summary} {item.get('url', '')}"

    for pattern, reason in HARD_SKIP_PATTERNS:
        if pattern.search(raw_blob):
            return {
                "decision": "skip",
                "article_type": "low_value",
                "priority": "skip",
                "score": 0,
                "reason": reason,
            }

    score = 30
    reasons: list[str] = []
    article_type = "standard_useful"

    for term, value in HARD_SIGNALS.items():
        if term in blob:
            score = max(score, value)
            reasons.append(f"hard:{term}")
            article_type = "hard_news"

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

    for term, value in SOFT_OR_SKIP_SIGNALS.items():
        if term in blob:
            score += value
            reasons.append(f"soft_penalty:{term}")

    score = max(0, min(int(score), 100))

    if score >= 75:
        decision = "selected"
        priority = "hard"
        article_type = "hard_news"
    elif score >= 58:
        decision = "selected"
        priority = "soft"
        if article_type == "standard_useful":
            article_type = "standard_useful"
    elif score >= 48:
        decision = "pending"
        priority = "soft"
        if article_type == "standard_useful":
            article_type = "soft_news"
    else:
        decision = "skip"
        priority = "skip"
        article_type = "low_value"

    return {
        "decision": decision,
        "article_type": article_type,
        "priority": priority,
        "score": score,
        "reason": ",".join(reasons[:10]) or "menzo_baseline",
    }


def sort_key(item: dict[str, Any]) -> tuple[int, str]:
    return int(item.get("score") or 0), str(item.get("published") or "")


def run_menzo(massy_board: dict[str, Any] | None = None) -> dict[str, Any]:
    board = massy_board if isinstance(massy_board, dict) else load_json(MASSY_BOARD_FILE, {})
    candidates = board.get("news_candidates_for_menzo", []) if isinstance(board, dict) else []
    if not isinstance(candidates, list):
        candidates = []

    max_selected = int(os.getenv("V93_MENZO_MAX_SELECTED_PER_RUN", "6"))
    max_pending = int(os.getenv("V93_MENZO_MAX_PENDING_PER_RUN", "12"))

    selected: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    print(f"[MENZO v93.2] Avvio decisione editoriale | candidates={len(candidates)}", flush=True)

    for candidate in candidates:
        item = dict(candidate)
        classification = classify_item(item)
        item.update(classification)
        item["agent"] = "Menzo"
        item["category_hint"] = category_hint(item)
        item["evaluated_at"] = utc_now()
        if item["decision"] == "selected":
            selected.append(item)
        elif item["decision"] == "pending":
            pending.append(item)
        else:
            skipped.append(item)

    selected = sorted(selected, key=sort_key, reverse=True)
    pending = sorted(pending, key=sort_key, reverse=True)
    overflow = selected[max_selected:]
    selected = selected[:max_selected]
    for item in overflow:
        item = dict(item)
        item["decision"] = "pending"
        item["reason"] = f"selected_overflow:{item.get('reason', '')}"
        pending.append(item)
    pending = sorted(pending, key=sort_key, reverse=True)[:max_pending]

    allowed_urls = [str(item.get("url") or item.get("source_url") or "") for item in selected if item.get("url") or item.get("source_url")]

    result = {
        "agent": "Menzo",
        "version": MENZO_VERSION,
        "generated_at": utc_now(),
        "mode": "deterministic_editorial_gate",
        "daily_policy": {
            "target_min": 20,
            "target_max": 30,
            "reports_excluded": True,
            "max_selected_this_run": max_selected,
            "max_pending_this_run": max_pending,
        },
        "input": {
            "massy_version": board.get("version") if isinstance(board, dict) else None,
            "candidate_count": len(candidates),
        },
        "selected": selected,
        "pending": pending,
        "skipped": skipped,
        "allowed_urls_for_v92": allowed_urls,
        "handoff": {
            "to_bob_or_v92": len(selected),
            "pending": len(pending),
            "skipped": len(skipped),
        },
    }

    write_json(ARTIFACT_DECISIONS_FILE, result)
    write_json(MENZO_DECISIONS_FILE, result)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "allowed_urls": allowed_urls})

    print(
        "[MENZO v93.2] Decisione pronta | "
        f"selected={len(selected)} pending={len(pending)} skipped={len(skipped)} allowed_for_v92={len(allowed_urls)}",
        flush=True,
    )
    return result


if __name__ == "__main__":
    out = run_menzo()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
