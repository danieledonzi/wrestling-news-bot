from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from modules.simone_report_integrity import PENDING_REPORTS, load_effective_registry, reserve_report

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


def local_now() -> datetime:
    # GitHub runner is UTC; for the report scheduler we only need date/day stability.
    return datetime.utcnow() + timedelta(hours=2)


def rome_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Rome"))


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


def discovery_report_identity(report: dict[str, Any], now: datetime) -> tuple[str, str, str]:
    """Key an evening discovery to that show and its next-morning report day."""
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
        return now >= datetime(y, m, d, hour, minute)
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
    now = now or rome_now()
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


REPORT_SIGNAL_RE = re.compile(r"\b(results?|risultati|recap|report|full\s+results?|live\s+results?|highlights?)\b", re.I)
NON_REPORT_RE = re.compile(r"\b(preview|card|betting|odds|rumou?rs?|spoilers?|spoiler\s+lineup|lineup|reaction|post[-\s]?show|media scrum|press conference|appears|returns|wins|retains|defeats|title change)\b", re.I)
REPORT_HINT_VALUES = {"report", "results", "results_report", "full_results", "live_results", "recap"}


def candidate_report_hint(candidate: dict[str, Any], report: dict[str, Any], raw: str) -> bool:
    for key in ["kind_hint", "kind", "article_type", "content_type", "candidate_type", "classification", "bucket"]:
        value = normalize(str(candidate.get(key) or ""))
        if value in REPORT_HINT_VALUES or "results report" in value or "report candidate" in value:
            return True
    for key in ["report_candidate", "is_report_candidate", "assigned_to_simone"]:
        if candidate.get(key) is True:
            return True
    if str(candidate.get("assigned_to") or "").lower() == "simone":
        return True
    show_hint = normalize(str(candidate.get("show_hint") or ""))
    source_blob = normalize(f"{candidate.get('source', '')} {candidate.get('url', '')} {candidate.get('source_url', '')}")
    aliases = [normalize(x) for x in report.get("aliases", []) if x]
    if "wrestlinginc" in source_blob and show_hint and any(alias and alias in show_hint for alias in aliases):
        return True
    blob = normalize(raw)
    return any(token in blob for token in ["results report", "full results", "live results", "complete results"])


def candidate_matches_special_report(candidate: dict[str, Any], report: dict[str, Any]) -> tuple[bool, str]:
    explicit_raw = " ".join(str(candidate.get(k) or "") for k in ["title", "url", "source_url"])
    supporting_raw = " ".join(str(candidate.get(k) or "") for k in ["show_hint", "summary", "description", "reason"])
    raw = f"{explicit_raw} {supporting_raw}"
    blob = normalize(raw)
    aliases = [normalize(x) for x in report.get("aliases", []) if x]
    explicit_blob = normalize(explicit_raw)
    special_identity_explicit = any(alias and alias in explicit_blob for alias in aliases)
    reports_cfg = load_json(REPORTS_CONFIG, {"reports": []})
    weekly_reports = reports_cfg.get("reports", []) if isinstance(reports_cfg, dict) else []
    for weekly in weekly_reports if isinstance(weekly_reports, list) else []:
        if not isinstance(weekly, dict):
            continue
        show_identity = normalize(str(weekly.get("show_name") or ""))
        result_identities = [
            term for value in (weekly.get("match_keywords") or [])
            if (term := normalize(str(value or ""))) and REPORT_SIGNAL_RE.search(str(value or ""))
        ]
        results_keyword_identity = any(term in explicit_blob for term in result_identities)
        generic_show_report_identity = bool(
            show_identity
            and show_identity in explicit_blob
            and REPORT_SIGNAL_RE.search(explicit_raw)
            and not special_identity_explicit
        )
        strong_weekly_identity = results_keyword_identity or generic_show_report_identity
        if strong_weekly_identity:
            return False, "conflicting_explicit_show_identity"
    structured = candidate.get("special_event_match")
    structured_key = str(structured.get("report_key") or "") if isinstance(structured, dict) else ""
    if structured_key and structured_key == str(report.get("report_key") or ""):
        return True, "structured_special_event_match"
    event_hit = any(alias and alias in blob for alias in aliases)
    if not event_hit:
        return False, "event_alias_not_found"
    if NON_REPORT_RE.search(raw):
        return False, "only_non_report_event_news_found"
    if REPORT_SIGNAL_RE.search(raw) or candidate_report_hint(candidate, report, raw):
        return True, "special_report_match"
    return False, "missing_report_results_signal"


def choose_special_report_candidate(candidates: list[dict[str, Any]], report: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    rejected_reasons: list[str] = []
    event_related_rejections: list[str] = []
    matches = []
    for c in candidates:
        ok, reason = candidate_matches_special_report(c, report)
        if ok:
            matches.append(c)
        else:
            rejected_reasons.append(reason)
            if reason != "event_alias_not_found":
                event_related_rejections.append(reason)
    if not matches:
        if event_related_rejections and all(r in {"missing_report_results_signal", "only_non_report_event_news_found"} for r in event_related_rejections):
            return None, "only_non_report_event_news_found"
        return None, "missing_report_source_not_found"
    def rank(c: dict[str, Any]) -> tuple[int, str]:
        source = str(c.get("source") or "").lower()
        return (0 if "wrestlinginc" in source or "wrestlinginc" in str(c.get("url") or "").lower() else 1, candidate_published_score(c))
    matches.sort(key=rank)
    return matches[0], "preferred_wrestlinginc" if rank(matches[0])[0] == 0 else "fallback_source"


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


def report_already_published(report: dict[str, Any], status: dict[str, Any], registry: dict[str, Any], manual_runs: list[Any]) -> bool:
    expected_ids = report_identity_values(report)
    if not expected_ids:
        return False
    if isinstance(status, dict):
        for key, value in status.items():
            if not isinstance(value, dict) or not published_record_compatible(value):
                continue
            if expected_ids & record_identity_values(value, keyed_report_key=str(key)) or title_fallback_matches(report, value):
                return True
    items = registry.get("items", []) if isinstance(registry, dict) else []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not published_record_compatible(item, require_evidence=True):
            continue
        if expected_ids & record_identity_values(item) or title_fallback_matches(report, item):
            return True
    for run in manual_runs if isinstance(manual_runs, list) else []:
        if not isinstance(run, dict):
            continue
        job = run.get("job") if isinstance(run.get("job"), dict) else {}
        merged = {**job, **{k: v for k, v in run.items() if k != "job"}}
        if not published_record_compatible(merged, require_evidence=True):
            continue
        if expected_ids & record_identity_values(merged) or title_fallback_matches(report, merged):
            return True
    return False

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
    raw = str(candidate.get("published") or candidate.get("published_at") or "")
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).isoformat()
    except Exception:
        return raw


def choose_report_candidate(candidates: list[dict[str, Any]], report: dict[str, Any], date_iso: str) -> tuple[dict[str, Any] | None, str]:
    matches = [c for c in candidates if candidate_matches_report(c, report, date_iso)]
    if not matches:
        return None, "no_candidate"
    matches.sort(key=lambda c: (source_rank(str(c.get("source") or ""), report), candidate_published_score(c)))
    preferred = [c for c in matches if c.get("source") == report.get("preferred_source")]
    if preferred:
        preferred_urls = {str(c.get("normalized_url") or c.get("url") or c.get("source_url") or "").rstrip("/") for c in preferred}
        if len(preferred_urls) != 1:
            return None, "ambiguous_preferred_candidates"
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
    special_cfg, registry_diagnostics = load_effective_registry()
    status = load_json(REPORT_STATUS_FILE, {})
    publication_registry = load_json(REPORT_REGISTRY_FILE, {"items": []})
    manual_runs = load_json(MANUAL_RUNS_FILE, [])
    reports = reports_cfg.get("reports", []) if isinstance(reports_cfg, dict) else []
    now = local_now()

    # Reserve special-event candidates immediately from Massy's authoritative
    # structured match, including discoveries before the event becomes due.
    for candidate in report_candidates:
        match = candidate.get("special_event_match") if isinstance(candidate, dict) else None
        if not isinstance(match, dict) or not match.get("report_key"):
            continue
        try:
            publish_date = (datetime.strptime(str(match.get("date_local")), "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
        except Exception:
            publish_date = str(match.get("date_local") or "")
        reserve_report(candidate, {**match, "report_id": match.get("night_key"), "event_identity": match.get("event_name"), "event_name": match.get("event_name"), "aliases": match.get("aliases") or [], "publish_date_local": publish_date, "category": match.get("category_hint"), "title": candidate.get("title"), "categories": [x for x in ["Editoriali", match.get("category_hint")] if x], "counts_as_news": False}, now=now, pending_path=PENDING_REPORTS)

    ready: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    expected_special, special_blocked = build_expected_special_reports(special_cfg)
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
        chosen, reason = choose_report_candidate(report_candidates, report, date_iso)
        if chosen:
            reservation = reserve_report(chosen, {
                "report_key": report_key, "report_id": report_id, "event_identity": report.get("show_name"),
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


    special_publish_slots = 1
    for report in expected_special:
        if report_already_published(report, status if isinstance(status, dict) else {}, publication_registry if isinstance(publication_registry, dict) else {}, manual_runs if isinstance(manual_runs, list) else []):
            item = {**report, "decision": "skip", "reason": "already_published"}
            special_already.append(item)
            skipped.append(item)
            continue
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
        reserve_report(chosen, {"report_key": report.get("report_key"), "report_id": report.get("night_key"), "night_key": report.get("night_key"), "event_identity": report.get("event_name"), "event_name": report.get("event_name"), "aliases": report.get("aliases") or [], "date_local": report.get("date"), "publish_after": "06:30", "category": report.get("category_hint")}, now=now, pending_path=PENDING_REPORTS)
        special_ready.append(item)
        ready.append(item)

    # Pending state is authoritative: replay a reservation even when this run's
    # feed no longer contains its URL.
    pending_state = load_json(PENDING_REPORTS, {"reports": []})
    pending_rows = pending_state.get("reports", []) if isinstance(pending_state, dict) else []
    for row in pending_rows:
        if not isinstance(row, dict) or row.get("status") in {"published", "already_published"}:
            continue
        report = {**row, "source_url": row.get("source_url"), "source_title": row.get("source_title"), "report_id": row.get("report_id") or row.get("night_key"), "title": row.get("title") or row.get("source_title"), "categories": row.get("categories") or [x for x in ["Editoriali", row.get("category")] if x], "counts_as_news": False, "decision": "ready_for_bob_or_v92", "reason": "pending_queue_replay"}
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
