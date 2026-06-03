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

VERSION = "v93_24_massy_show_news_before_report_closure"
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
RECAP_DUPLICATE_RE = re.compile(r"\b(results?|highlights?|key\s+moments?|recap|full\s+results?|live\s+coverage|complete\s+coverage|moments\s+salienti|risultati)\b", re.I)
FACTUAL_RE = re.compile(r"\b(new\s+champion|wins?\s+(?:the\s+)?title|title\s+change|retains?|defeats?|debut|returns?|comeback|injur(?:y|ed)|limping|botch|controversy|attack(?:s|ed)?|turns?|heel\s+turn|face\s+turn|announced|set\s+for|confirmed|qualif(?:y|ies|ied)|tournament|cash\s*in|suspended|fired|released|signs?|contract|medical|backstage)\b", re.I)
POST_SHOW_HARD_RE = re.compile(r"\b(injur(?:y|ed)|botch|backstage|controversy|fallout|reaction|responds?|comments?|explains?|breaks\s+silence|medical|hospital|heat|real\s+reason)\b", re.I)


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


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour, minute = [int(x) for x in str(value or "00:00").split(":", 1)]
        return hour, minute
    except Exception:
        return 0, 0


def report_due_today(report: dict[str, Any], now: datetime) -> bool:
    if not report.get("enabled", True):
        return False
    expected = DAY_NAMES.get(str(report.get("expected_day_after") or "").strip().lower())
    if expected is not None and now.weekday() != expected:
        return False
    hour, minute = parse_hhmm(str(report.get("publish_after") or "06:30"))
    return now.time() >= now.replace(hour=hour, minute=minute, second=0, microsecond=0).time()


def report_waiting_today(report: dict[str, Any], now: datetime) -> bool:
    if not report.get("enabled", True):
        return False
    expected = DAY_NAMES.get(str(report.get("expected_day_after") or "").strip().lower())
    return expected is not None and now.weekday() == expected and not report_due_today(report, now)


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


def show_related(candidate: dict[str, Any], report: dict[str, Any]) -> bool:
    blob = f"{candidate.get('title', '')} {candidate.get('url', '')} {candidate.get('summary', '')}"
    pattern = SHOW_PATTERNS.get(str(report.get("id") or ""))
    return bool(pattern and pattern.search(blob))


def classify_show_news(candidate: dict[str, Any], report: dict[str, Any]) -> str:
    blob = f"{candidate.get('title', '')} {candidate.get('url', '')} {candidate.get('summary', '')}"
    if RECAP_DUPLICATE_RE.search(blob) and not FACTUAL_RE.search(blob):
        return "event_recap_duplicate"
    if POST_SHOW_HARD_RE.search(blob):
        return "post_show_hard_news"
    if FACTUAL_RE.search(blob):
        return "event_factual_news"
    return "event_soft_reaction"


def report_coverage(report_candidates: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str], set[str]]:
    now = local_now()
    status = load_json(REPORT_STATUS_FILE, {})
    published: dict[str, dict[str, Any]] = {}
    active: set[str] = set()
    waiting: set[str] = set()
    for report in configured_reports():
        report_id = str(report.get("id") or "")
        if not report_id:
            continue
        key, date_iso = report_key_and_date(report, now)
        current = status.get(key, {}) if isinstance(status, dict) else {}
        if current.get("status") == "published":
            published[report_id] = {"report_id": report_id, "report_key": key, "date": date_iso, "source": current.get("source", ""), "wp_post_id": current.get("wp_post_id"), "link": current.get("link") or current.get("wp_link")}
            active.add(report_id)
            continue
        if report_due_today(report, now) and any(candidate_matches_report(c, report) for c in report_candidates):
            active.add(report_id)
        elif report_waiting_today(report, now):
            waiting.add(report_id)
    return published, active, waiting


def annotate_show_candidate(item: dict[str, Any], report: dict[str, Any], news_class: str) -> dict[str, Any]:
    item = dict(item)
    item["show_report_id"] = report.get("id")
    item["show_name"] = report.get("show_name")
    item["event_news_class"] = news_class
    item["show_day_policy"] = "news_before_report_then_report_closure"
    if news_class in {"event_factual_news", "post_show_hard_news"}:
        item["massive_editorial_boost"] = "show_factual_core"
    return item


def run_massy() -> dict[str, Any]:
    board = base_run_massy()
    candidates = [x for x in board.get("news_candidates_for_menzo", []) if isinstance(x, dict)]
    report_candidates = [x for x in board.get("report_candidates", []) if isinstance(x, dict)]
    published_reports, active_report_ids, waiting_report_ids = report_coverage(report_candidates)
    memory = menzo_skip_memory()
    kept: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    filtered_reports: list[dict[str, Any]] = []
    report_skips: list[dict[str, Any]] = []
    menzo_memory_count = old_count = report_skip_count = recap_skip_count = factual_count = post_show_count = soft_reaction_count = 0

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
    waiting_reports = [r for r in configured_reports() if str(r.get("id") or "") in waiting_report_ids]
    show_context_reports = active_reports + waiting_reports

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
        covering = next((r for r in show_context_reports if show_related(item, r)), None)
        if covering:
            news_class = classify_show_news(item, covering)
            if str(covering.get("id") or "") in active_report_ids and news_class == "event_recap_duplicate":
                moved.append(hard_skip_entry(item, "covered_by_report_recap_duplicate", report_id=covering.get("id"), show_name=covering.get("show_name"), event_news_class=news_class, report_coverage_guard="report_closes_only_recap_duplicates"))
                recap_skip_count += 1
                continue
            annotated = annotate_show_candidate(item, covering, news_class)
            if news_class == "event_factual_news":
                factual_count += 1
            elif news_class == "post_show_hard_news":
                post_show_count += 1
            else:
                soft_reaction_count += 1
            kept.append(annotated)
            continue
        kept.append(item)

    board["news_candidates_for_menzo"] = kept
    board["report_candidates"] = filtered_reports
    board.setdefault("hard_skipped", []).extend(moved + report_skips)
    board["version"] = VERSION
    board.setdefault("binding", {})["manual_or_existing_reports_block_simone"] = True
    board.setdefault("binding", {})["report_publish_after_respected"] = True
    board.setdefault("binding", {})["report_closes_only_recap_duplicates"] = True
    board.setdefault("binding", {})["show_factual_news_allowed_before_report"] = True
    board.setdefault("binding", {})["menzo_hard_skip_memory_is_binding"] = True
    board.setdefault("binding", {})["news_older_than_7_days_are_hard_skips"] = True
    board["handoff"]["to_simone"] = len(filtered_reports)
    board["handoff"]["to_menzo"] = len(kept)
    board["handoff"]["hard_skipped"] = len(board.get("hard_skipped", []))
    board["handoff"]["menzo_memory_hard_skipped"] = menzo_memory_count
    board["handoff"]["old_news_hard_skipped"] = old_count
    board["handoff"]["report_candidates_blocked_by_manual_or_history"] = report_skip_count
    board["handoff"]["event_recap_duplicates_blocked_by_report"] = recap_skip_count
    board["handoff"]["event_factual_news_to_menzo"] = factual_count
    board["handoff"]["post_show_hard_news_to_menzo"] = post_show_count
    board["handoff"]["event_soft_reactions_to_menzo"] = soft_reaction_count
    board["known_menzo_hard_skip_urls"] = len(memory)
    board["active_report_ids_for_recap_suppression"] = sorted(active_report_ids)
    board["waiting_report_ids_for_show_news_boost"] = sorted(waiting_report_ids)
    board["published_due_reports"] = published_reports
    write_json(ARTIFACT_MASSY_FILE, board)
    write_json(MASSY_BOARD_FILE, board)
    print(f"[MASSY v93.24] Policy applicata | to_simone={board['handoff']['to_simone']} to_menzo={board['handoff']['to_menzo']} menzo_skip={menzo_memory_count} old_skip={old_count} report_skip={report_skip_count} recap_skip={recap_skip_count} factual={factual_count} post_show={post_show_count} soft_show={soft_reaction_count}", flush=True)
    return board
