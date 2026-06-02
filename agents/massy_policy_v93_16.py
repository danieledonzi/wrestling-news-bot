from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from agents.massy import run_massy as base_run_massy, write_json

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
MENZO_HARD_SKIP_FILE = NEWSROOM_STATE_DIR / "menzo_hard_skips.json"
MASSY_BOARD_FILE = NEWSROOM_STATE_DIR / "massy_board_latest.json"
ARTIFACT_MASSY_FILE = ARTIFACT_DIR / "massy_board.json"

VERSION = "v93_16_massy_old_news_and_menzo_skip_memory"
MAX_NEWS_AGE_DAYS = int(os.getenv("V93_MASSY_MAX_NEWS_AGE_DAYS", "7"))


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


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


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def menzo_skip_memory() -> dict[str, dict[str, Any]]:
    data = load_json(MENZO_HARD_SKIP_FILE, {"items": []})
    items = data.get("items", []) if isinstance(data, dict) else []
    out: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict):
            continue
        key = source_key(item.get("url") or item.get("source_url") or item.get("normalized_url") or "")
        if not key:
            continue
        added = parse_published(item.get("added_at")) or now
        ttl = int(item.get("expires_after_hours") or data.get("ttl_hours") or 168)
        if now - added <= timedelta(hours=ttl):
            out[key] = item
    return out


def old_news_reason(candidate: dict[str, Any]) -> str | None:
    dt = parse_published(candidate.get("published"))
    if not dt:
        return None
    if datetime.now(timezone.utc) - dt > timedelta(days=MAX_NEWS_AGE_DAYS):
        return f"older_than_{MAX_NEWS_AGE_DAYS}_days"
    return None


def hard_skip_entry(candidate: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    data = dict(candidate)
    data["decision"] = "hard_skip"
    data["reason"] = reason
    data.pop("assigned_to", None)
    data.update(extra)
    return data


def run_massy() -> dict[str, Any]:
    board = base_run_massy()
    candidates = [x for x in board.get("news_candidates_for_menzo", []) if isinstance(x, dict)]
    memory = menzo_skip_memory()
    kept: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    menzo_memory_count = 0
    old_count = 0
    for item in candidates:
        key = source_key(item.get("url") or item.get("normalized_url") or "")
        if key in memory:
            mem = memory[key]
            moved.append(hard_skip_entry(item, "menzo_hard_skip_memory", menzo_reason=mem.get("reason", ""), menzo_article_type=mem.get("article_type", "")))
            menzo_memory_count += 1
            continue
        reason = old_news_reason(item)
        if reason:
            moved.append(hard_skip_entry(item, reason, age_guard="massy_7_day_window"))
            old_count += 1
            continue
        kept.append(item)
    if moved:
        board["news_candidates_for_menzo"] = kept
        board.setdefault("hard_skipped", []).extend(moved)
        board["version"] = VERSION
        board.setdefault("binding", {})["menzo_hard_skip_memory_is_binding"] = True
        board.setdefault("binding", {})["news_older_than_7_days_are_hard_skips"] = True
        board["handoff"]["to_menzo"] = len(kept)
        board["handoff"]["hard_skipped"] = len(board.get("hard_skipped", []))
        board["handoff"]["menzo_memory_hard_skipped"] = menzo_memory_count
        board["handoff"]["old_news_hard_skipped"] = old_count
        board["known_menzo_hard_skip_urls"] = len(memory)
        write_json(ARTIFACT_MASSY_FILE, board)
        write_json(MASSY_BOARD_FILE, board)
    print(
        f"[MASSY v93.16] Policy applicata | to_menzo={board['handoff']['to_menzo']} "
        f"menzo_skip={menzo_memory_count} old_skip={old_count}",
        flush=True,
    )
    return board
