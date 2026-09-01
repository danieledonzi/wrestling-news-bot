from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from modules.simone_report_integrity import PENDING_REPORTS, candidate_date_evidence, dynamic_special_event_match, load_effective_registry, normalize_url, reserve_report

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
SPECIAL_EVENTS_CONFIG = CONFIG_DIR / "special_events.json"
MANUAL_RUNS_FILE = STATE_DIR / "manual_runs.json"
REPORT_REGISTRY_FILE = NEWSROOM_STATE_DIR / "report_publication_registry.json"
SIMONE_EXPECTED_EVENTS_FILE = NEWSROOM_STATE_DIR / "simone_expected_events_latest.json"
ARTIFACT_EXPECTED_EVENTS_FILE = ARTIFACT_DIR / "simone_expected_events_latest.json"

SIMONE_VERSION = "v95.19.1_simone_report_identity_guard"

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


ROME = ZoneInfo("Europe/Rome")


def rome_time(value: datetime) -> datetime:
    """Return an aware Europe/Rome time; naive scheduler inputs are local Rome."""
    return value.replace(tzinfo=ROME) if value.tzinfo is None else value.astimezone(ROME)


def local_now() -> datetime:
    return datetime.now(ROME)


def rome_now() -> datetime:
    return datetime.now(ROME)


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
    now = rome_time(now)
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
    now = rome_time(now)
    show_date = now.date() - timedelta(days=int(report.get("show_date_offset_days", 1)))
    date_iso = show_date.isoformat()
    return f"{report.get('id')}_{date_iso.replace('-', '_')}", date_iso


def discovery_report_identity(report: dict[str, Any], now: datetime) -> tuple[str, str, str]:
    """Key an evening discovery using the Europe/Rome calendar."""
    now = rome_time(now)
    expected = DAY_NAMES.get(str(report.get("expected_day_after") or "").lower())
    if expected is not None and now.weekday() == (expected - 1) % 7:
        show_date = now.date(); publish_date = show_date + timedelta(days=1)
    else:
        show_date = now.date() - timedelta(days=int(report.get("show_date_offset_days", 1)))
        publish_date = now.date()
    date_iso = show_date.isoformat()
    return f"{report.get('id')}_{date_iso.replace('-', '_')}", date_iso, publish_date.isoformat()


def pending_due(row: dict[str, Any], now: datetime) -> bool:
    try:
        hour, minute = [int(x) for x in str(row.get("publish_after") or "06:30").split(":", 1)]
        publish_date = str(row.get("publish_date_local") or row.get("date_local"))
        y, m, d = [int(x) for x in publish_date.split("-")]
        due_at = datetime(y, m, d, hour, minute, tzinfo=ROME)
        return rome_time(now) >= due_at
    except Exception:
        return False



def load_special_events_config() -> dict[str, Any]:
    data, _diagnostics = load_effective_registry()
    return data if isinstance(data, dict) else {}


def parse_local_event_time(date_iso: str, hhmm: str) -> datetime | None:
    try:
        hour, minute = [int(x) for x in str(hhmm or "06:30").split(":", 1)]
        y, m, d = [int(x) for x in str(date_iso).split("-")]
        return datetime(y, m, d, hour, minute, tzinfo=ZoneInfo("Europe/Rome"))
    except Exception:
        return None


def next_calendar_date(date_iso: str) -> str | None:
    """Return the following local calendar date without raising on registry data."""
    try:
        return (datetime.strptime(str(date_iso or ""), "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    except (TypeError, ValueError):
        return None


def special_report_key(night_key: str, date_iso: str) -> str:
    return f"special_event_{night_key}_{date_iso.replace('-', '_')}"


def special_display_name(event: dict[str, Any]) -> str:
    promotion = str(event.get("promotion") or "").strip()
    name = str(event.get("event_name") or event.get("key") or "Special Event").strip()
    aliases = [str(x).strip() for x in event.get("aliases", []) if str(x).strip()] if isinstance(event.get("aliases"), list) else []
    if any("AEW x NJPW" in a or "AEW×NJPW" in a for a in aliases):
        return "AEW x NJPW Forbidden Door"
    if promotion and promotion.upper() == "WWE" and str(event.get("brand") or "").upper() == "NXT" and not name.upper().startswith("NXT"):
        return f"NXT {name.removeprefix('The ').strip()}"
    if promotion and promotion.upper() not in name.upper():
        return f"{promotion} {name}"
    return name


def build_expected_special_reports(cfg: dict[str, Any], now: datetime | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = rome_time(now or rome_now())
    lookback = int(cfg.get("default_lookback_hours") or 18) if isinstance(cfg, dict) else 18
    # Prudential rescue window keeps just-confirmed weekend PLE/PPV diagnosable across a missed daily run.
    window_hours = max(lookback, int(cfg.get("simone_special_report_window_hours") or 72) if isinstance(cfg, dict) else 72)
    expected: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    events = cfg.get("events", []) if isinstance(cfg, dict) else []
    if not isinstance(events, list):
        return expected, blocked
    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("status") or "").lower() not in {"confirmed", "active"}:
            continue
        nights = event.get("nights", []) if isinstance(event.get("nights"), list) else []
        for night in nights:
            if not isinstance(night, dict) or not night.get("enabled", True):
                continue
            date_iso = str(night.get("date_local") or "")
            publish_date_local = next_calendar_date(date_iso)
            due_at = parse_local_event_time(publish_date_local or "", str(night.get("report_publish_after_local") or cfg.get("default_report_publish_after_local") or "06:30"))
            night_key = str(night.get("night_key") or "")
            if not due_at or not night_key:
                blocked.append({"event_key": event.get("key"), "night_key": night_key, "reason": "invalid_special_event_schedule"})
                continue
            if now < due_at:
                blocked.append({"event_key": event.get("key"), "night_key": night_key, "reason": "not_due_yet", "due_at_local": due_at.isoformat()})
                continue
            age_hours = (now - due_at).total_seconds() / 3600
            if age_hours > window_hours:
                blocked.append({"event_key": event.get("key"), "night_key": night_key, "reason": "outside_special_event_lookback_window", "age_hours": round(age_hours, 2), "window_hours": window_hours})
                continue
            aliases = []
            for source in (event.get("aliases"), night.get("aliases")):
                if isinstance(source, list):
                    aliases.extend(str(x) for x in source if x)
            aliases.append(str(event.get("event_name") or ""))
            show_name = special_display_name(event)
            expected.append({
                "event_key": str(event.get("key") or ""),
                "night_key": night_key,
                "report_key": special_report_key(night_key, date_iso),
                "promotion": event.get("promotion"),
                "category_hint": event.get("category_hint") or event.get("promotion"),
                "event_name": event.get("event_name"),
                "aliases": sorted(set(a for a in aliases if a)),
                "title": f"{show_name} del {date_it(date_iso)} - risultati e momenti salienti",
                "date": date_iso,
                "publish_date_local": publish_date_local,
                "due_at_local": due_at.isoformat(),
                "report_type": "special_event",
            })
    return expected, blocked


REPORT_SIGNAL_RE = re.compile(r"\b(results|risultati)\b", re.I)
def _is_wrestlinginc(candidate: dict[str, Any]) -> bool:
    source = f"{candidate.get('source', '')} {candidate.get('url', '')} {candidate.get('source_url', '')}".lower()
    return "wrestlinginc" in source.replace(" ", "")


def _candidate_date_matches(candidate: dict[str, Any], date_iso: str) -> bool:
    return bool(candidate_date_evidence(candidate, date_iso)["matches"])


def candidate_matches_special_report(candidate: dict[str, Any], report: dict[str, Any]) -> tuple[bool, str]:
    explicit_raw = " ".join(str(candidate.get(k) or "") for k in ["title", "url", "source_url"])
    explicit_blob = normalize(explicit_raw)
    aliases = [normalize(x) for x in report.get("aliases", []) if x]
    if not _is_wrestlinginc(candidate):
        return False, "rejected_non_results_event_article"
    if not REPORT_SIGNAL_RE.search(explicit_raw):
        return False, "rejected_non_results_event_article"
    reports_cfg = load_json(REPORTS_CONFIG, {"reports": []})
    for weekly in reports_cfg.get("reports", []) if isinstance(reports_cfg, dict) else []:
        show = normalize(str(weekly.get("show_name") or "")) if isinstance(weekly, dict) else ""
        if show and re.search(rf"\b{re.escape(show)}\s+results?\b", explicit_blob) and not any(show in alias for alias in aliases):
            return False, "rejected_conflicting_weekly_identity"
    if not any(alias and alias in explicit_blob for alias in aliases):
        return False, "event_alias_not_found"
    date_iso = str(report.get("date") or report.get("date_local") or "")
    if not _candidate_date_matches(candidate, date_iso):
        return False, "rejected_non_results_event_article"
    return True, "canonical_results_match"

def choose_special_report_candidate(candidates: list[dict[str, Any]], report: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    matches = []
    rejections: list[str] = []
    for c in candidates:
        ok, reason = candidate_matches_special_report(c, report)
        if ok:
            matches.append(c)
        elif reason != "event_alias_not_found":
            rejections.append(reason)
    if not matches:
        for reason in ["rejected_conflicting_weekly_identity", "rejected_non_results_event_article"]:
            if reason in rejections:
                return None, reason
        return None, "waiting_for_canonical_results_source"
    return matches[0], "canonical_results_match"


PUBLISHED_STATUS_VALUES = {"", "published", "already_published", "completed", "dry_run"}


def published_record_compatible(record: dict[str, Any], *, require_evidence: bool = False) -> bool:
    status = str(record.get("status") or "").strip().lower()
    if status and status not in PUBLISHED_STATUS_VALUES:
        return False
    if require_evidence:
        return bool(record.get("wp_post_id") or record.get("link") or record.get("wp_link"))
    return True


def report_identity_values(report: dict[str, Any]) -> set[str]:
    values = {str(report.get(k) or "").strip() for k in ["report_key", "event_key", "night_key", "source_url", "wp_post_id"]}
    event_key = str(report.get("event_key") or "").strip()
    night_key = str(report.get("night_key") or "").strip()
    if event_key:
        values.add(f"manual:{event_key}")
    if night_key:
        values.add(f"manual:{night_key}")
    return {v for v in values if v}


def record_identity_values(record: dict[str, Any], *, keyed_report_key: str = "") -> set[str]:
    values = {keyed_report_key.strip()} if keyed_report_key else set()
    for key in ["report_key", "event_key", "night_key", "source_url", "url", "link", "wp_link", "wp_post_id"]:
        value = str(record.get(key) or "").strip()
        if value:
            values.add(value)
    job = record.get("job") if isinstance(record.get("job"), dict) else {}
    for key in ["report_key", "event_key", "night_key", "source_url", "url", "link", "wp_link", "wp_post_id"]:
        value = str(job.get(key) or "").strip()
        if value:
            values.add(value)
    for key in [
        str(record.get("event_key") or "").strip(),
        str(record.get("night_key") or "").strip(),
        str(job.get("event_key") or "").strip(),
        str(job.get("night_key") or "").strip(),
    ]:
        if key:
            values.add(f"manual:{key}")
    return {v for v in values if v}


def title_fallback_matches(report: dict[str, Any], record: dict[str, Any]) -> bool:
    report_title = normalize(str(report.get("title") or ""))
    if not report_title:
        return False
    titles = [str(record.get("title") or ""), str(record.get("source_title") or "")]
    job = record.get("job") if isinstance(record.get("job"), dict) else {}
    titles.extend([str(job.get("title") or ""), str(job.get("source_title") or "")])
    return any(report_title and normalize(title) == report_title for title in titles if title)


def _record_source_url(record: dict[str, Any]) -> str:
    job = record.get("job") if isinstance(record.get("job"), dict) else {}
    return str(record.get("source_url") or record.get("url") or job.get("source_url") or job.get("url") or "")


def report_already_published(report: dict[str, Any], status: dict[str, Any], registry: dict[str, Any], manual_runs: list[Any]) -> bool:
    """Publication evidence is valid only for the same canonical source URL."""
    expected_raw_url = str(report.get("source_url") or "")
    expected_url = normalize_url(expected_raw_url) if expected_raw_url else ""
    records: list[tuple[dict[str, Any], bool]] = []
    if isinstance(status, dict):
        records.extend((value, False) for value in status.values() if isinstance(value, dict))
    items = registry.get("items", []) if isinstance(registry, dict) else []
    records.extend((item, True) for item in items if isinstance(item, dict))
    records.extend((run, True) for run in manual_runs if isinstance(run, dict))
    for record, require_evidence in records:
        if not published_record_compatible(record, require_evidence=require_evidence):
            continue
        recorded_raw_url = _record_source_url(record)
        recorded_url = normalize_url(recorded_raw_url) if recorded_raw_url else ""
        if expected_url and recorded_url:
            if recorded_url == expected_url:
                return True
            continue
        # With no canonical URL available, explicit event/night identity plus
        # publication evidence remains valid; a report_key alone is insufficient.
        shared = report_identity_values(report) & record_identity_values(record)
        non_key = {str(report.get("event_key") or ""), str(report.get("night_key") or ""), f"manual:{report.get('event_key') or ''}", f"manual:{report.get('night_key') or ''}"}
        if shared & {value for value in non_key if value and value != "manual:"}:
            return True
    return False

def source_rank(source: str, report: dict[str, Any]) -> int:
    if source.lower() == str(report.get("preferred_source") or "").lower():
        return 0
    if source.lower() == str(report.get("fallback_source") or "").lower():
        return 1
    return 9


def _canonical_structured_special_match(candidate: dict[str, Any]) -> bool:
    match = candidate.get("special_event_match")
    if not isinstance(match, dict) or match.get("canonical_identity") != "wrestlinginc_results":
        return False
    report = {
        "report_key": match.get("report_key"),
        "aliases": match.get("aliases") or (match.get("match_evidence") or {}).get("alias_hits") or [],
        "date": match.get("date_local"),
    }
    return candidate_matches_special_report(candidate, report)[0]


def candidate_report_identity(candidate: dict[str, Any], report: dict[str, Any], date_iso: str) -> tuple[bool, str]:
    explicit = f"{candidate.get('title', '')} {candidate.get('url', '')} {candidate.get('source_url', '')}"
    blob = normalize(explicit)
    if not _is_wrestlinginc(candidate) or not re.search(r"\b(results|risultati)\b", explicit, re.I):
        return False, "waiting_for_canonical_results_source"
    if _canonical_structured_special_match(candidate):
        return False, "rejected_special_event_as_weekly"
    special_cfg = load_json(SPECIAL_EVENTS_CONFIG, {"events": []})
    special, _reason = dynamic_special_event_match(candidate, special_cfg)
    if special:
        return False, "rejected_special_event_as_weekly"
    show = normalize(str(report.get("show_name") or ""))
    if not show or not re.search(rf"\b{re.escape(show)}\s+results\b", blob):
        return False, "rejected_conflicting_weekly_identity"
    if not _candidate_date_matches(candidate, date_iso):
        return False, "rejected_conflicting_weekly_identity"
    return True, "canonical_results_match"


def candidate_matches_report(candidate: dict[str, Any], report: dict[str, Any], date_iso: str) -> bool:
    return candidate_report_identity(candidate, report, date_iso)[0]

def candidate_published_score(candidate: dict[str, Any]) -> str:
    raw = str(candidate.get("published") or candidate.get("published_at") or "")
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return raw


def choose_report_candidate(candidates: list[dict[str, Any]], report: dict[str, Any], date_iso: str) -> tuple[dict[str, Any] | None, str]:
    evaluated = [(c, *candidate_report_identity(c, report, date_iso)) for c in candidates]
    matches = [c for c, matched, _reason in evaluated if matched]
    if not matches:
        reasons = [reason for _c, _matched, reason in evaluated]
        for reason in ["rejected_special_event_as_weekly", "rejected_conflicting_weekly_identity"]:
            if reason in reasons:
                return None, reason
        return None, "waiting_for_canonical_results_source"
    preferred = [c for c in matches if str(c.get("source") or "").lower() == str(report.get("preferred_source") or "").lower()]
    return (preferred[0], "canonical_results_match") if preferred else (None, "waiting_for_canonical_results_source")


def _pending_lock(report_key: str) -> dict[str, Any] | None:
    state = load_json(PENDING_REPORTS, {"reports": []})
    rows = state.get("reports", []) if isinstance(state, dict) else []
    return next((row for row in rows if isinstance(row, dict) and row.get("report_key") == report_key and row.get("canonical_source_locked") is True), None)


def _pending_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "url": row.get("source_url"), "title": row.get("source_title")}


def run_simone(massy_board: dict[str, Any] | None = None) -> dict[str, Any]:
    board = massy_board if isinstance(massy_board, dict) else load_json(MASSY_BOARD_FILE, {})
    report_candidates = board.get("report_candidates", []) if isinstance(board, dict) else []
    if not isinstance(report_candidates, list):
        report_candidates = []

    reports_cfg = load_json(REPORTS_CONFIG, {"reports": []})
    special_cfg, registry_diagnostics = load_effective_registry()
    status = load_json(REPORT_STATUS_FILE, {})
    publication_registry = load_json(REPORT_REGISTRY_FILE, {"items": []})
    manual_runs = load_json(MANUAL_RUNS_FILE, [])
    reports = reports_cfg.get("reports", []) if isinstance(reports_cfg, dict) else []
    now = local_now()
    expected_special, special_blocked = build_expected_special_reports(special_cfg)

    # Validate legacy pending rows and establish a lock only from canonical identity.
    pending_seed = load_json(PENDING_REPORTS, {"reports": []})
    pending_seed_rows = pending_seed.get("reports", []) if isinstance(pending_seed, dict) else []
    locked_keys = {str(row.get("report_key")) for row in pending_seed_rows if isinstance(row, dict) and row.get("canonical_source_locked") is True}
    for row in pending_seed_rows:
        if not isinstance(row, dict) or row.get("status") in {"published", "already_published"}:
            continue
        key = str(row.get("report_key") or "")
        weekly_cfg = next((x for x in reports if isinstance(x, dict) and str(x.get("id")) == str(row.get("report_id"))), None)
        special_report = next((x for x in expected_special if str(x.get("report_key")) == key), None)
        candidate = _pending_candidate(row)
        valid = candidate_matches_report(candidate, weekly_cfg, str(row.get("date_local") or "")) if weekly_cfg else bool(special_report and candidate_matches_special_report(candidate, special_report)[0])
        if not valid and (weekly_cfg or special_report):
            row["status"] = "invalid_canonical_identity"
            row["identity_reason"] = "invalid_canonical_identity"
        elif valid and key not in locked_keys:
            row["canonical_source_locked"] = True
            row["identity_reason"] = "canonical_source_locked"
            locked_keys.add(key)
        elif valid and row.get("canonical_source_locked") is not True:
            row["status"] = "later_canonical_candidate_ignored"
            row["identity_reason"] = "later_canonical_candidate_ignored"
    if isinstance(pending_seed, dict):
        pending_seed["reports"] = pending_seed_rows; pending_seed["updated_at"] = utc_now(); write_json(PENDING_REPORTS, pending_seed)

    # Reserve special-event candidates immediately from Massy's authoritative
    # structured match, including discoveries before the event becomes due.
    for candidate in report_candidates:
        match = candidate.get("special_event_match") if isinstance(candidate, dict) else None
        if not isinstance(match, dict) or not match.get("report_key"):
            continue
        validation_report = {
            "report_key": match.get("report_key"),
            "aliases": match.get("aliases") or (match.get("match_evidence") or {}).get("alias_hits") or [],
            "date": match.get("date_local"),
        }
        valid_special, _validation_reason = candidate_matches_special_report(candidate, validation_report)
        if not valid_special:
            continue
        try:
            publish_date = (datetime.strptime(str(match.get("date_local")), "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
        except Exception:
            publish_date = str(match.get("date_local") or "")
        reserve_report(candidate, {**match, "report_id": match.get("night_key"), "event_identity": match.get("event_name"), "event_name": match.get("event_name"), "aliases": match.get("aliases") or [], "publish_date_local": publish_date, "category": match.get("category_hint"), "title": candidate.get("title"), "categories": [x for x in ["Editoriali", match.get("category_hint")] if x], "counts_as_news": False}, now=now, pending_path=PENDING_REPORTS)

    ready: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    special_ready: list[dict[str, Any]] = []
    special_missing: list[dict[str, Any]] = []
    special_already: list[dict[str, Any]] = []

    print(f"[SIMONE v95.1.1] Avvio controllo report | candidates={len(report_candidates)} reports={len(reports)}", flush=True)

    for report in reports:
        if not isinstance(report, dict):
            continue
        report_id = str(report.get("id") or "")
        report_key, date_iso, publish_date_iso = discovery_report_identity(report, now)
        title = build_report_title(report, date_iso)
        locked = _pending_lock(report_key)
        if locked:
            locked_candidate = _pending_candidate(locked)
            if candidate_matches_report(locked_candidate, report, date_iso):
                chosen, reason = locked_candidate, "canonical_source_locked"
            else:
                chosen, reason = None, "invalid_canonical_identity"
        else:
            chosen, reason = choose_report_candidate(report_candidates, report, date_iso)
        if chosen:
            reservation = reserve_report(chosen, {
                "report_key": report_key, "report_id": report_id, "event_identity": report.get("show_name"), "canonical_identity": "wrestlinginc_results",
                "date_local": date_iso, "publish_after": report.get("publish_after") or "06:30",
                "publish_date_local": publish_date_iso, "category": report.get("category"), "title": title,
                "categories": [x for x in [report.get("editorial_category", "Editoriali"), report.get("category")] if x], "counts_as_news": False,
            }, now=now, pending_path=PENDING_REPORTS)
        else:
            reservation = None
        if not report_due_today(report, now):
            skipped.append({
                "report_id": report_id,
                "report_key": report_key,
                "title": title,
                "decision": "skip",
                "reason": "waiting_publish_after" if reservation else f"not_due_today:{report.get('expected_day_after')}",
                **({"source_url": reservation.get("source_url"), "status": "waiting_publish_after"} if reservation else {}),
            })
            continue
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


    for report in expected_special:
        locked = _pending_lock(str(report.get("report_key") or ""))
        if locked:
            locked_candidate = _pending_candidate(locked)
            if candidate_matches_special_report(locked_candidate, report)[0]:
                chosen, reason = locked_candidate, "canonical_source_locked"
            else:
                chosen, reason = None, "invalid_canonical_identity"
        else:
            chosen, reason = choose_special_report_candidate(report_candidates, report)
        if not chosen:
            item = {**report, "decision": "missing", "reason": reason}
            special_missing.append(item)
            waiting.append(item)
            continue
        item = {
            **report,
            "report_id": report.get("night_key"),
            "decision": "ready_for_bob_or_v92",
            "reason": reason,
            "source": chosen.get("source"),
            "source_url": chosen.get("url") or chosen.get("source_url"),
            "source_title": chosen.get("title"),
            "categories": [x for x in ["Editoriali", report.get("category_hint")] if x],
            "counts_as_news": False,
        }
        if report_already_published(item, status if isinstance(status, dict) else {}, publication_registry if isinstance(publication_registry, dict) else {}, manual_runs if isinstance(manual_runs, list) else []):
            item.update({"decision": "skip", "reason": "already_published"})
            special_already.append(item); skipped.append(item)
            continue
        reserve_report(chosen, {"report_key": report.get("report_key"), "report_id": report.get("night_key"), "night_key": report.get("night_key"), "event_identity": report.get("event_name"), "event_name": report.get("event_name"), "canonical_identity": "wrestlinginc_results", "aliases": report.get("aliases") or [], "date_local": report.get("date"), "publish_after": "06:30", "category": report.get("category_hint")}, now=now, pending_path=PENDING_REPORTS)
        special_ready.append(item)
        ready.append(item)

    # Pending state is authoritative: replay a reservation even when this run's
    # feed no longer contains its URL.
    pending_state = load_json(PENDING_REPORTS, {"reports": []})
    pending_rows = pending_state.get("reports", []) if isinstance(pending_state, dict) else []
    for pending_row in pending_rows:
        if not isinstance(pending_row, dict) or pending_row.get("status") in {"published", "already_published"}:
            continue
        key = str(pending_row.get("report_key") or "")
        weekly_cfg = next((x for x in reports if isinstance(x, dict) and str(x.get("id")) == str(pending_row.get("report_id"))), None)
        special_expected_row = next((x for x in expected_special if str(x.get("report_key")) == key), None)
        candidate = _pending_candidate(pending_row)
        valid = candidate_matches_report(candidate, weekly_cfg, str(pending_row.get("date_local") or "")) if weekly_cfg else bool(special_expected_row and candidate_matches_special_report(candidate, special_expected_row)[0])
        if not valid and (weekly_cfg or special_expected_row):
            pending_row["status"] = "invalid_canonical_identity"
            pending_row["identity_reason"] = "invalid_canonical_identity"
        elif valid and pending_row.get("canonical_source_locked") is not True:
            pending_row["status"] = "later_canonical_candidate_ignored"
            pending_row["identity_reason"] = "later_canonical_candidate_ignored"
    for row in pending_rows:
        if not isinstance(row, dict) or row.get("status") in {"published", "already_published", "invalid_canonical_identity", "later_canonical_candidate_ignored"}:
            continue
        report = {**row, "source_url": row.get("source_url"), "url": row.get("source_url"), "source_title": row.get("source_title"), "report_id": row.get("report_id") or row.get("night_key"), "categories": row.get("categories") or [x for x in ["Editoriali", row.get("category")] if x], "counts_as_news": False, "decision": "ready_for_bob_or_v92", "reason": "pending_queue_replay"}
        weekly_cfg = next((x for x in reports if isinstance(x, dict) and str(x.get("id")) == str(row.get("report_id"))), None)
        special_expected = next((x for x in expected_special if str(x.get("report_key")) == str(row.get("report_key"))), None)
        if weekly_cfg:
            report["title"] = build_report_title(weekly_cfg, str(row.get("date_local") or ""))
        elif special_expected:
            report["title"] = special_expected["title"]
        if not pending_due(row, now):
            row["status"] = "waiting_publish_after"; waiting.append({**report, "decision": "waiting", "reason": "waiting_publish_after"})
            continue
        valid_pending = candidate_matches_report(report, weekly_cfg, str(row.get("date_local") or "")) if weekly_cfg else bool(special_expected and candidate_matches_special_report(report, special_expected)[0])
        if not valid_pending:
            row["status"] = "invalid_canonical_identity"
            skipped.append({**report, "decision": "skip", "reason": "invalid_canonical_identity"})
            continue
        if report_already_published(report, status if isinstance(status, dict) else {}, publication_registry if isinstance(publication_registry, dict) else {}, manual_runs if isinstance(manual_runs, list) else []):
            row["status"] = "already_published"; skipped.append({**report, "reason": "already_published"}); continue
        if pending_due(row, now):
            ready.append(report)
        else:
            row["status"] = "waiting_publish_after"; waiting.append({**report, "decision": "waiting", "reason": "waiting_publish_after"})
    if isinstance(pending_state, dict):
        pending_state["reports"] = pending_rows; pending_state["updated_at"] = utc_now(); write_json(PENDING_REPORTS, pending_state)

    # One identity appears once even if both current feed and queue supplied it.
    ready_by_key: dict[str, dict[str, Any]] = {}
    pending_by_key = {str(x.get("report_key")): x for x in pending_rows if isinstance(x, dict) and x.get("report_key")}
    for item in ready:
        row = pending_by_key.get(str(item.get("report_key") or ""))
        if row is not None and not pending_due(row, now):
            continue
        if item.get("report_key"):
            ready_by_key.setdefault(str(item.get("report_key")), item)
    ready = list(ready_by_key.values())
    ready_keys = set(ready_by_key)
    special_ready = [item for item in special_ready if str(item.get("report_key") or "") in ready_keys]
    waiting = list({f"{x.get('report_key')}:{x.get('reason')}": x for x in waiting}.values())

    result = {
        "agent": "Simone",
        "version": SIMONE_VERSION,
        "generated_at": utc_now(),
        "mode": "report_director",
        "input": {
            "massy_version": board.get("version") if isinstance(board, dict) else None,
            "report_candidates": len(report_candidates),
            "configured_reports": len(reports),
            "expected_special_events": len(expected_special),
        },
        "ready_reports": ready,
        "waiting_reports": waiting,
        "skipped_reports": skipped,
        "expected_special_events": expected_special,
        "special_ready": special_ready,
        "special_missing": special_missing,
        "special_already_published": special_already,
        "special_blocked": special_blocked,
        "effective_registry": registry_diagnostics,
        "handoff": {
            "ready": len(ready),
            "waiting": len(waiting),
            "skipped": len(skipped),
            "expected_special_events": len(expected_special),
            "special_ready": len(special_ready),
            "special_missing": len(special_missing),
            "special_already_published": len(special_already),
            "special_blocked": len(special_blocked),
            "report_urls_reserved": sum(1 for x in report_candidates if x.get("url") or x.get("source_url")),
            "reports_waiting_publish_after": sum(1 for x in skipped if x.get("reason") == "waiting_publish_after"),
            "multiple_reports_processed": len(ready) if len(ready) > 1 else 0,
        },
    }
    expected_artifact = {"generated_at": result["generated_at"], "expected_special_events": expected_special, "special_ready": special_ready, "special_missing": special_missing, "special_already_published": special_already, "special_blocked": special_blocked}
    write_json(SIMONE_EXPECTED_EVENTS_FILE, expected_artifact)
    write_json(ARTIFACT_EXPECTED_EVENTS_FILE, expected_artifact)
    write_json(ARTIFACT_SIMONE_FILE, result)
    write_json(SIMONE_DECISIONS_FILE, result)
    print(
        "[SIMONE v95.1.1] Decisione report pronta | "
        f"ready={len(ready)} waiting={len(waiting)} skipped={len(skipped)}",
        flush=True,
    )
    return result


if __name__ == "__main__":
    out = run_simone()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
