from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from agents.massy import run_massy as base_run_massy, write_json

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
MENZO_HARD_SKIP_FILE = NEWSROOM_STATE_DIR / "menzo_hard_skips.json"
MASSY_BOARD_FILE = NEWSROOM_STATE_DIR / "massy_board_latest.json"
ARTIFACT_MASSY_FILE = ARTIFACT_DIR / "massy_board.json"
REPORT_STATUS_FILE = STATE_DIR / "report_status.json"
REPORTS_CONFIG = CONFIG_DIR / "reports_v92.json"

VERSION = "v93_21_massy_manual_report_coverage"
MAX_NEWS_AGE_DAYS = int(os.getenv("V93_MASSY_MAX_NEWS_AGE_DAYS", "7"))
DAY_NAMES = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
SHOW_PATTERNS = {
    "wwe_raw": re.compile(r"\b(wwe\s+raw|raw)\b", re.I),
    "wwe_smackdown": re.compile(r"\b(wwe\s+smackdown|smackdown|smack\s*down)\b", re.I),
    "wwe_nxt": re.compile(r"\b(wwe\s+nxt|nxt)\b", re.I),
    "aew_dynamite": re.compile(r"\b(aew\s+dynamite|dynamite)\b", re.I),
    "aew_collision": re.compile(r"\b(aew\s+collision|collision)\b", re.I),
    "tna_impact": re.compile(r"\b(tna\s+impact|impact\s+wrestling|impact)\b", re.I),
}
EPISODE_RE = re.compile(r"\b(results?|highlights?|episode|segment|match|title\s+defen[cs]e|stands\s+tall|announced|return|debut|wins?|loses?|defeats?|attacks?|brawl|spoiler|recap|moment|appearance|during)\b", re.I)


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


def local_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=2)


def report_due_today(report: dict[str, Any], now: datetime) -> bool:
    if not report.get("enabled", True):
        return False
    expected = DAY_NAMES.get(str(report.get("expected_day_after") or "").strip().lower())
    if expected is not None and now.weekday() != expected:
        return False
    publish_after = str(report.get("publish_after") or "00:00")
    try:
        hour, minute = [int(x) for x in publish_after.split(":", 1)]
    except Exception:
        hour, minute = 0, 0
    return now.time() >= now.replace(hour=hour, minute=minute, second=0, microsecond=0).time()


def report_key_and_date(report: dict[str, Any], now: datetime) -> tuple[str, str]:
    show_date = now.date() - timedelta(days=int(report.get("show_date_offset_days", 1)))
    date_iso = show_date.isoformat()
    return f"{report.get('id')}_{date_iso.replace('-', '_')}", date_iso


def configured_reports() -> list[dict[str, Any]]:
    cfg = load_json(REPORTS_CONFIG, {"reports": []})
    return [x for x in (cfg.get("reports", []) if isinstance(cfg, dict) else []) if isinstance(x, dict)]


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
    if dt and datetime.now(timezone.utc) - dt > timedelta(days=MAX_NEWS_AGE_DAYS):
        return f"older_than_{MAX_NEWS_AGE_DAYS}_days"
    return None


def hard_skip_entry(candidate: dict[str, Any], reason: str, **extra: Any) -> dict[str, Any]:
    data = dict(candidate)
    data["decision"] = "hard_skip"
    data["reason"] = reason
    data.pop("assigned_to", None)
    data.update(extra)
    return data


def candidate_matches_report(candidate: dict[str, Any], report: dict[str, Any]) -> bool:
    blob = f"{candidate.get('title', '')} {candidate.get('url', '')} {candidate.get('show_hint', '')}"
    report_id = str(report.get("id") or "")
    pattern = SHOW_PATTERNS.get(report_id)
    if pattern and pattern.search(blob):
        return True
    for keyword in report.get("match_keywords", []) or []:
        if str(keyword).lower() in blob.lower():
            return True
    return False


def event_news_matches_report(candidate: dict[str, Any], report: dict[str, Any]) -> bool:
    blob = f"{candidate.get('title', '')} {candidate.get('url', '')} {candidate.get('summary', '')}"
    pattern = SHOW_PATTERNS.get(str(report.get("id") or ""))
    return bool(pattern and pattern.search(blob) and EPISODE_RE.search(blob))


def report_coverage(report_candidates: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    now = local_now()
    status = load_json(REPORT_STATUS_FILE, {})
    published: dict[str, dict[str, Any]] = {}
    active: set[str] = set()
    for report in configured_reports():
        if not report_due_today(report, now):
            continue
        report_id = str(report.get("id") or "")
        key, date_iso = report_key_and_date(report, now)
        current = status.get(key, {}) if isinstance(status, dict) else {}
        if current.get("status") == "published":
            published[report_id] = {
                "report_id": report_id,
                "report_key": key,
                "date": date_iso,
                "source": current.get("source", ""),
                "wp_post_id": current.get("wp_post_id"),
                "link": current.get("link") or current.get("wp_link"),
            }
            active.add(report_id)
        elif any(candidate_matches_report(c, report) for c in report_candidates):
            active.add(report_id)
    return published, active


def run_massy() -> dict[str, Any]:
    board = base_run_massy()
    candidates = [x for x in board.get("news_candidates_for_menzo", []) if isinstance(x, dict)]
    report_candidates = [x for x in board.get("report_candidates", []) if isinstance(x, dict)]
    published_reports, active_report_ids = report_coverage(report_candidates)
    memory = menzo_skip_memory()
    kept: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    filtered_reports: list[dict[str, Any]] = []
    report_skips: list[dict[str, Any]] = []
    menzo_memory_count = old_count = report_skip_count = episode_skip_count = 0

    for rc in report_candidates:
        matched = None
        for report in configured_reports():
            report_id = str(report.get("id") or "")
            if report_id in published_reports and candidate_matches_report(rc, report):
                matched = published_reports[report_id]
                break
        if matched:
            report_skips.append(hard_skip_entry(rc, "report_already_published_manual_or_history", **matched))
            report_skip_count += 1
        else:
            filtered_reports.append(rc)

    active_reports = [r for r in configured_reports() if str(r.get("id") or "") in active_report_ids]
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
        covering = next((r for r in active_reports if event_news_matches_report(item, r)), None)
        if covering:
            moved.append(hard_skip_entry(item, "covered_by_published_or_present_report", report_id=covering.get("id"), show_name=covering.get("show_name"), report_coverage_guard="report_has_priority_over_episode_news"))
            episode_skip_count += 1
            continue
        kept.append(item)

    board["news_candidates_for_menzo"] = kept
    board["report_candidates"] = filtered_reports
    board.setdefault("hard_skipped", []).extend(moved + report_skips)
    board["version"] = VERSION
    board.setdefault("binding", {})["manual_or_existing_reports_block_simone"] = True
    board.setdefault("binding", {})["present_or_published_reports_block_episode_news"] = True
    board.setdefault("binding", {})["menzo_hard_skip_memory_is_binding"] = True
    board.setdefault("binding", {})["news_older_than_7_days_are_hard_skips"] = True
    board["handoff"]["to_simone"] = len(filtered_reports)
    board["handoff"]["to_menzo"] = len(kept)
    board["handoff"]["hard_skipped"] = len(board.get("hard_skipped", []))
    board["handoff"]["menzo_memory_hard_skipped"] = menzo_memory_count
    board["handoff"]["old_news_hard_skipped"] = old_count
    board["handoff"]["report_candidates_blocked_by_manual_or_history"] = report_skip_count
    board["handoff"]["episode_news_blocked_by_report"] = episode_skip_count
    board["known_menzo_hard_skip_urls"] = len(memory)
    board["active_report_ids_for_news_suppression"] = sorted(active_report_ids)
    board["published_due_reports"] = published_reports
    write_json(ARTIFACT_MASSY_FILE, board)
    write_json(MASSY_BOARD_FILE, board)
    print(f"[MASSY v93.21] Policy applicata | to_simone={board['handoff']['to_simone']} to_menzo={board['handoff']['to_menzo']} menzo_skip={menzo_memory_count} old_skip={old_count} report_skip={report_skip_count} episode_skip={episode_skip_count}", flush=True)
    return board
