from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
REPORT_STATUS_FILE = STATE_DIR / "report_status.json"
MANUAL_RUNS_FILE = STATE_DIR / "manual_runs.json"
REPORT_REGISTRY_FILE = NEWSROOM_STATE_DIR / "report_publication_registry.json"
SPECIAL_EVENTS_CONFIG = CONFIG_DIR / "special_events.json"
EFFECTIVE_SPECIAL_EVENTS_FILE = NEWSROOM_STATE_DIR / "special_events_effective.json"

VERSION = "v95_13_2_manual_report_reconciliation"

SHOW_PATTERNS = [
    ("wwe_raw", re.compile(r"\b(wwe\s+raw|raw)\b", re.I), ["Editoriali", "WWE"]),
    ("wwe_smackdown", re.compile(r"\b(wwe\s+smackdown|smackdown|smack\s*down)\b", re.I), ["Editoriali", "WWE"]),
    ("wwe_nxt", re.compile(r"\b(wwe\s+nxt|nxt)\b", re.I), ["Editoriali", "NXT"]),
    ("aew_dynamite", re.compile(r"\b(aew\s+dynamite|dynamite)\b", re.I), ["Editoriali", "AEW"]),
    ("aew_collision", re.compile(r"\b(aew\s+collision|collision)\b", re.I), ["Editoriali", "AEW"]),
    ("tna_impact", re.compile(r"\b(tna\s+impact|impact\s+wrestling|impact)\b", re.I), ["Editoriali", "TNA"]),
]

DATE_PATTERNS = [
    re.compile(r"\b(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})\b"),
    re.compile(r"\b(\d{1,2})[-_/](\d{1,2})[-_/](20\d{2})\b"),
    re.compile(r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)[a-z]*[-\s]+(\d{1,2})[-,\s]+(20\d{2})\b", re.I),
    re.compile(r"\b(\d{1,2})[-\s]+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)[-\s]+(20\d{2})\b", re.I),
]
MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7,
    "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12, "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9,
    "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def utc_now() -> str:
    return datetime.utcnow().isoformat()


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


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def blob_from_job(job: dict[str, Any]) -> str:
    return " ".join(str(job.get(k) or "") for k in ["title", "source_title", "source_url", "report_key", "date"])


def infer_report_id(job: dict[str, Any]) -> tuple[str, list[str]]:
    blob = blob_from_job(job)
    for report_id, pattern, categories in SHOW_PATTERNS:
        if pattern.search(blob):
            return report_id, categories
    if str(job.get("kind") or "").strip().lower() == "report":
        categories = job.get("categories") if isinstance(job.get("categories"), list) else []
        return "special_event_manual", [str(x) for x in categories if str(x)]
    return "", []


def parse_date_candidate(value: str) -> datetime | None:
    text = value or ""
    match = DATE_PATTERNS[0].search(text)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except Exception:
            pass
    match = DATE_PATTERNS[1].search(text)
    if match:
        try:
            return datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        except Exception:
            pass
    for pattern in DATE_PATTERNS[2:]:
        match = pattern.search(text)
        if not match:
            continue
        whole = match.group(0).lower()
        month = next((number for name, number in MONTHS.items() if name in whole), None)
        if month:
            try:
                return datetime(int(match.group(2)), month, int(match.group(1)))
            except Exception:
                pass
    return None


def infer_show_date(job: dict[str, Any], created_at: str | None = None) -> str:
    for key in ["source_url", "source_title", "title", "report_key"]:
        parsed = parse_date_candidate(str(job.get(key) or ""))
        if parsed:
            return parsed.date().isoformat()
    parsed = parse_date_candidate(str(job.get("date") or ""))
    if parsed:
        return parsed.date().isoformat()
    raw_created = created_at or str(job.get("created_at") or "")
    try:
        return datetime.fromisoformat(raw_created.replace("Z", "+00:00")).date().isoformat()
    except Exception:
        return datetime.utcnow().date().isoformat()


def load_special_events() -> list[dict[str, Any]]:
    for path in (EFFECTIVE_SPECIAL_EVENTS_FILE, SPECIAL_EVENTS_CONFIG):
        data = load_json(path, {})
        events = data.get("events", []) if isinstance(data, dict) else []
        if isinstance(events, list) and events:
            return [item for item in events if isinstance(item, dict)]
    return []


def infer_special_event_identity(job: dict[str, Any], show_date: str) -> dict[str, str] | None:
    blob = normalize(blob_from_job(job))
    if not blob:
        return None
    matches: list[tuple[int, dict[str, str]]] = []
    for event in load_special_events():
        event_key = str(event.get("key") or "").strip()
        aliases = [str(event.get("event_name") or "")]
        if isinstance(event.get("aliases"), list):
            aliases.extend(str(x) for x in event["aliases"] if x)
        nights = event.get("nights", []) if isinstance(event.get("nights"), list) else []
        for night in nights:
            if not isinstance(night, dict) or str(night.get("date_local") or "") != show_date:
                continue
            night_key = str(night.get("night_key") or "").strip()
            if not event_key or not night_key:
                continue
            night_aliases = aliases[:]
            if isinstance(night.get("aliases"), list):
                night_aliases.extend(str(x) for x in night["aliases"] if x)
            normalized_aliases = [normalize(alias) for alias in night_aliases if normalize(alias)]
            hits = [alias for alias in normalized_aliases if alias in blob]
            if hits:
                matches.append((max(len(alias) for alias in hits), {
                    "event_key": event_key,
                    "night_key": night_key,
                    "report_id": night_key,
                    "report_key": f"special_event_{night_key}_{show_date.replace('-', '_')}",
                }))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def fallback_special_event_identity(job: dict[str, Any], show_date: str) -> dict[str, str]:
    raw = "|".join(str(job.get(key) or "") for key in ["source_url", "source_title", "title", "report_key"])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    report_id = f"special_event_manual_{digest}"
    return {
        "event_key": report_id,
        "night_key": report_id,
        "report_id": report_id,
        "report_key": f"{report_id}_{show_date.replace('-', '_')}",
    }


def build_registry_entry(job: dict[str, Any], *, wp_post_id: Any = None, link: str = "", created_at: str | None = None, source: str = "manual_runs") -> dict[str, Any] | None:
    report_id, default_categories = infer_report_id(job)
    if not report_id:
        return None
    show_date = infer_show_date(job, created_at)
    identity: dict[str, str] = {}
    if report_id == "special_event_manual":
        identity = infer_special_event_identity(job, show_date) or fallback_special_event_identity(job, show_date)
        report_id = identity["report_id"]
        report_key = identity["report_key"]
    else:
        report_key = f"{report_id}_{show_date.replace('-', '_')}"
    categories = job.get("categories") if isinstance(job.get("categories"), list) else []
    if default_categories:
        categories = default_categories
    entry = {
        "report_id": report_id,
        "report_key": report_key,
        "show_date": show_date,
        "status": "published",
        "source": source,
        "source_url": job.get("source_url", ""),
        "source_title": job.get("source_title", ""),
        "title": job.get("title", ""),
        "categories": categories or default_categories,
        "wp_post_id": wp_post_id,
        "link": link,
        "published_at": created_at or utc_now(),
        "updated_at": utc_now(),
        "detected_by": VERSION,
    }
    if identity:
        entry.update({"event_key": identity["event_key"], "night_key": identity["night_key"]})
    return entry


def upsert_report_status(entry: dict[str, Any]) -> None:
    status = load_json(REPORT_STATUS_FILE, {})
    if not isinstance(status, dict):
        status = {}
    status[entry["report_key"]] = {
        "categories": entry.get("categories", []),
        "event_key": entry.get("event_key", ""),
        "night_key": entry.get("night_key", ""),
        "link": entry.get("link", ""),
        "published_at": entry.get("published_at"),
        "source": entry.get("source", ""),
        "source_title": entry.get("source_title", ""),
        "source_url": entry.get("source_url", ""),
        "status": "published",
        "title": entry.get("title", ""),
        "updated_at": utc_now(),
        "wp_post_id": entry.get("wp_post_id"),
    }
    write_json(REPORT_STATUS_FILE, status)


def upsert_registry(entry: dict[str, Any]) -> None:
    registry = load_json(REPORT_REGISTRY_FILE, {"items": []})
    items = registry.get("items", []) if isinstance(registry, dict) else []
    by_key = {str(x.get("report_key")): x for x in items if isinstance(x, dict) and x.get("report_key")}
    by_key[entry["report_key"]] = entry
    write_json(REPORT_REGISTRY_FILE, {"version": VERSION, "updated_at": utc_now(), "items": sorted(by_key.values(), key=lambda x: str(x.get("published_at") or ""))})


def record_published_report(job: dict[str, Any], *, wp_post_id: Any = None, link: str = "", source: str = "manual_runs", created_at: str | None = None) -> dict[str, Any] | None:
    entry = build_registry_entry(job, wp_post_id=wp_post_id, link=link, source=source, created_at=created_at)
    if not entry:
        return None
    upsert_report_status(entry)
    upsert_registry(entry)
    return entry


def rebuild_from_manual_runs() -> dict[str, Any]:
    runs = load_json(MANUAL_RUNS_FILE, [])
    added = 0
    skipped = 0
    if not isinstance(runs, list):
        runs = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        job = run.get("job") if isinstance(run.get("job"), dict) else {}
        entry = build_registry_entry(job, wp_post_id=run.get("wp_post_id"), link=run.get("link", ""), source="manual_runs", created_at=run.get("created_at"))
        if entry:
            upsert_report_status(entry)
            upsert_registry(entry)
            added += 1
        else:
            skipped += 1
    return {"version": VERSION, "added": added, "skipped": skipped}


def published_reports_from_status_and_manual() -> dict[str, dict[str, Any]]:
    rebuild_from_manual_runs()
    status = load_json(REPORT_STATUS_FILE, {})
    out: dict[str, dict[str, Any]] = {}
    if isinstance(status, dict):
        for key, value in status.items():
            if isinstance(value, dict) and value.get("status") == "published":
                report_id = "_".join(str(key).split("_")[:-3]) if len(str(key).split("_")) > 3 else ""
                out[str(key)] = {"report_key": key, "report_id": report_id, **value}
    return out
