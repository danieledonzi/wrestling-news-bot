from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

REPORTS_CONFIG = CONFIG_DIR / "reports_v92.json"
REPORT_STATUS_FILE = STATE_DIR / "report_status.json"
MASSY_BOARD_FILE = NEWSROOM_STATE_DIR / "massy_board_latest.json"
SIMONE_DECISIONS_FILE = NEWSROOM_STATE_DIR / "simone_reports_latest.json"
ARTIFACT_SIMONE_FILE = ARTIFACT_DIR / "simone_reports.json"

SIMONE_VERSION = "v93_3_simone_report_director"

DAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

MONTHS_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def local_now() -> datetime:
    # GitHub runner is UTC; for the report scheduler we only need date/day stability.
    return datetime.utcnow() + timedelta(hours=2)


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


def date_it(date_iso: str) -> str:
    y, m, d = [int(x) for x in date_iso.split("-")]
    return f"{d} {MONTHS_IT[m - 1]} {y}"


def build_report_title(report: dict[str, Any], date_iso: str) -> str:
    template = report.get("title_template") or "{show_name} del {date_it} - risultati e momenti salienti"
    return template.format(
        show_name=report.get("show_name", report.get("id", "Report")),
        date_iso=date_iso,
        date_it=date_it(date_iso),
        year=date_iso[:4],
    )


def report_due_today(report: dict[str, Any], now: datetime) -> bool:
    if not report.get("enabled", True):
        return False
    expected_day = str(report.get("expected_day_after") or "").strip().lower()
    expected = DAY_NAMES.get(expected_day)
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


def source_rank(source: str, report: dict[str, Any]) -> int:
    if source == report.get("preferred_source"):
        return 0
    if source == report.get("fallback_source"):
        return 1
    return 9


def candidate_matches_report(candidate: dict[str, Any], report: dict[str, Any], date_iso: str) -> bool:
    blob = normalize(f"{candidate.get('title', '')} {candidate.get('url', '')} {candidate.get('show_hint', '')}")
    if "results" not in blob and "risultati" not in blob and "highlights" not in blob:
        return False
    keywords = [normalize(x) for x in report.get("match_keywords", []) if x]
    if keywords and not any(keyword in blob for keyword in keywords):
        return False
    # Date matching is intentionally permissive in Simone v93.3 because Massy
    # already isolated report-like URLs and some feeds use slugs without dates.
    date_tokens = date_iso.split("-")
    year, month, day = date_tokens[0], int(date_tokens[1]), int(date_tokens[2])
    raw = f"{candidate.get('title', '')} {candidate.get('url', '')}".lower()
    if str(year) in raw or f"{month}/{day}" in raw or f"{month:02d}/{day:02d}" in raw or f"{month}-{day}" in raw:
        return True
    return True


def candidate_published_score(candidate: dict[str, Any]) -> str:
    return str(candidate.get("published") or "")


def choose_report_candidate(candidates: list[dict[str, Any]], report: dict[str, Any], date_iso: str) -> tuple[dict[str, Any] | None, str]:
    matches = [c for c in candidates if candidate_matches_report(c, report, date_iso)]
    if not matches:
        return None, "no_candidate"
    matches.sort(key=lambda c: (source_rank(str(c.get("source") or ""), report), candidate_published_score(c)))
    preferred = [c for c in matches if c.get("source") == report.get("preferred_source")]
    if preferred:
        return preferred[0], "preferred_source"
    fallback = [c for c in matches if c.get("source") == report.get("fallback_source")]
    if fallback:
        return fallback[0], "fallback_source"
    return matches[0], "other_source"


def run_simone(massy_board: dict[str, Any] | None = None) -> dict[str, Any]:
    board = massy_board if isinstance(massy_board, dict) else load_json(MASSY_BOARD_FILE, {})
    report_candidates = board.get("report_candidates", []) if isinstance(board, dict) else []
    if not isinstance(report_candidates, list):
        report_candidates = []

    reports_cfg = load_json(REPORTS_CONFIG, {"reports": []})
    status = load_json(REPORT_STATUS_FILE, {})
    reports = reports_cfg.get("reports", []) if isinstance(reports_cfg, dict) else []
    now = local_now()

    ready: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    print(f"[SIMONE v93.3] Avvio controllo report | candidates={len(report_candidates)} reports={len(reports)}", flush=True)

    for report in reports:
        if not isinstance(report, dict):
            continue
        report_id = str(report.get("id") or "")
        report_key, date_iso = report_key_and_date(report, now)
        title = build_report_title(report, date_iso)
        current = status.get(report_key, {}) if isinstance(status, dict) else {}
        if current.get("status") == "published":
            skipped.append({
                "report_id": report_id,
                "report_key": report_key,
                "title": title,
                "decision": "skip",
                "reason": "already_published",
            })
            continue
        if not report_due_today(report, now):
            skipped.append({
                "report_id": report_id,
                "report_key": report_key,
                "title": title,
                "decision": "skip",
                "reason": f"not_due_today:{report.get('expected_day_after')}",
            })
            continue
        chosen, reason = choose_report_candidate(report_candidates, report, date_iso)
        if not chosen:
            waiting.append({
                "report_id": report_id,
                "report_key": report_key,
                "title": title,
                "decision": "waiting",
                "reason": reason,
                "date": date_iso,
            })
            continue
        ready.append({
            "report_id": report_id,
            "report_key": report_key,
            "title": title,
            "decision": "ready_for_bob_or_v92",
            "reason": reason,
            "date": date_iso,
            "source": chosen.get("source"),
            "source_url": chosen.get("url") or chosen.get("source_url"),
            "source_title": chosen.get("title"),
            "categories": [x for x in [report.get("editorial_category", "Editoriali"), report.get("category")] if x],
            "counts_as_news": False,
        })

    result = {
        "agent": "Simone",
        "version": SIMONE_VERSION,
        "generated_at": utc_now(),
        "mode": "report_director",
        "input": {
            "massy_version": board.get("version") if isinstance(board, dict) else None,
            "report_candidates": len(report_candidates),
            "configured_reports": len(reports),
        },
        "ready_reports": ready,
        "waiting_reports": waiting,
        "skipped_reports": skipped,
        "handoff": {
            "ready": len(ready),
            "waiting": len(waiting),
            "skipped": len(skipped),
        },
    }
    write_json(ARTIFACT_SIMONE_FILE, result)
    write_json(SIMONE_DECISIONS_FILE, result)
    print(
        "[SIMONE v93.3] Decisione report pronta | "
        f"ready={len(ready)} waiting={len(waiting)} skipped={len(skipped)}",
        flush=True,
    )
    return result


if __name__ == "__main__":
    out = run_simone()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
