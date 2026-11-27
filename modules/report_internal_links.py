"""Read-only report identity resolution for news hyperlinks.

The alias index is derived from Massy's report observations, not source
election. It never alters Simone history, reservations or publication policy.
Only explicit report headlines and dates may establish cross-source identity.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from modules.editorial_internal_links import source_identity
from modules.simone_report_integrity import (
    candidate_date_evidence, matches_weekly_result_identity, weekly_special_override,
)

INDEX_NAME = "report_link_aliases_v1.json"
MAX_ALIASES = 20000
_VERSION = "report-link-aliases-v1"
_KEY = re.compile(r"[a-z0-9_]+_20\d{2}_\d{2}_\d{2}")
_NOISE = re.compile(r"\b(?:spoilers?|preview|predictions?|quick results|ratings?|viewership|recap|reaction|analysis|review|highlights only|match results only|upcoming|schedule|will air|to air)\b", re.I)
_RESULTS = re.compile(r"\bresults\b", re.I)
_SINGLE_MATCH = re.compile(r"\b(?:match|battle royal|tournament|championship|title defense|title match)\b", re.I)


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _date_from_key(key):
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        return ""
    day = key[-10:].replace("_", "-")
    try:
        datetime.strptime(day, "%Y-%m-%d")
        return day
    except ValueError:
        return ""


def _stamp(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        try:
            return parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            return None


def _title_date_matches(title, day, published):
    """Title-only dates: slug and publication time cannot establish the day."""
    dates = candidate_date_evidence({"source_title": title}, day)["explicit_content_dates"]
    if dates != {day}:
        return False
    # A dated feed observation disambiguates yearless headings and rules out
    # a report of a different edition cited in the current title.
    stamp = _stamp(published)
    expected = datetime.strptime(day, "%Y-%m-%d").date()
    if stamp is None or stamp.tzinfo is None:
        return False
    return abs((stamp.date() - expected).days) <= 2


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _observed_key(row, reports, registry):
    if not isinstance(row, dict):
        return ""
    url = row.get("url") or row.get("source_url")
    identity = source_identity(url, report=True)
    if identity is None or identity[1] not in {"ringsidenews.com", "wrestlinginc.com", "wrestleview.com", "fightful.com"}:
        return ""
    title = str(row.get("title") or row.get("source_title") or "")
    results = _RESULTS.search(title)
    if not results or _NOISE.search(title) or _NOISE.search(_norm(identity[3])) or _SINGLE_MATCH.search(title[:results.start()]):
        return ""
    published = row.get("published") or row.get("published_at")
    stamp = _stamp(published)
    if stamp is None or stamp.tzinfo is None:
        return ""
    reason = row.get("original_report_reason") or row.get("reason")
    # A Massy report route alone is insufficient: headlines must also be
    # result-oriented, start with the configured show and explicitly date it.
    if reason == "weekly_show_results":
        if isinstance(row.get("special_event_match"), dict):
            return ""
        hint = _norm(row.get("show_hint") or "")
        matches = []
        normalized = _norm(title)
        for report in reports:
            if not isinstance(report, dict) or not report.get("enabled", True):
                continue
            name = _norm(report.get("show_name") or "")
            if not name or hint != name or not normalized.startswith(name + " "):
                continue
            if not matches_weekly_result_identity(title, report):
                continue
            for offset in range(-2, 3):
                day = (stamp.date() + timedelta(days=offset)).isoformat()
                if _title_date_matches(title, day, published) and not weekly_special_override(report, day, registry):
                    key = str(report.get("id") or "") + "_" + day.replace("-", "_")
                    if _date_from_key(key):
                        matches.append(key)
        # For a yearless date close to New Year, evaluate every nearby day,
        # not just the year in the URL or an inferred weekday.
        return matches[0] if len(set(matches)) == 1 else ""
    # For special events only use a structured Massy match, never fuzzy
    # matching by an event name or by publication date alone.
    match = row.get("special_event_match")
    if not isinstance(match, dict):
        return ""
    key = match.get("report_key")
    day = _date_from_key(key)
    if not day or not key.startswith("special_event_") or match.get("date_local") != day:
        return ""
    if not _title_date_matches(title, day, published):
        return ""
    title_norm = _norm(title)
    # Validate against the configured night, not an arbitrary stored alias.
    for event in registry.get("events", []):
        if not isinstance(event, dict) or event.get("status") not in {"confirmed", "active"}:
            continue
        for night in event.get("nights", []):
            if not isinstance(night, dict) or not night.get("enabled", True) or night.get("date_local") != day:
                continue
            if key != f"special_event_{night.get('night_key')}_{day.replace('-', '_')}":
                continue
            aliases = [event.get("event_name"), *event.get("aliases", []), *night.get("aliases", [])]
            if any(len(_norm(a)) >= 4 and title_norm.startswith(_norm(a) + " ") for a in aliases if a):
                return key
    return ""


def _observation_rows(board):
    if not isinstance(board, dict):
        return
    for field in ("report_candidates", "hard_skipped", "already_worked"):
        rows = board.get(field)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and (row.get("reason") == "weekly_show_results"
                        or row.get("original_report_reason") == "weekly_show_results"
                        or isinstance(row.get("special_event_match"), dict)):
                    yield row


def _alias_rows(index):
    if not isinstance(index, dict) or index.get("version") != _VERSION or not isinstance(index.get("items"), dict):
        return {}
    items = {}
    for url, observations in list(index["items"].items())[:MAX_ALIASES]:
        if source_identity(url, report=True) is None or not isinstance(observations, dict) or not observations:
            continue
        if any(not _date_from_key(key) or not isinstance(evidence, dict)
               or not isinstance(evidence.get("title"), str) or not evidence["title"]
               or not isinstance(evidence.get("published"), str) or not _stamp(evidence["published"])
               for key, evidence in observations.items()):
            continue
        items[url] = observations
    return items


def _evidence(row):
    return {"title": str(row.get("title") or row.get("source_title") or "")[:1000],
            "published": str(row.get("published") or row.get("published_at") or "")[:100],
            "reason": str(row.get("original_report_reason") or row.get("reason") or "")[:100],
            "show_hint": str(row.get("show_hint") or "")[:100]}


def _config(state_dir, config_dir):
    cfg = _read(config_dir / "reports_v92.json", {})
    reports = cfg.get("reports", []) if isinstance(cfg, dict) else []
    if not isinstance(reports, list):
        reports = []
    seed = _read(config_dir / "special_events.json", {})
    effective = _read(state_dir / "special_events_effective.json", {})
    registry = effective if isinstance(effective, dict) and isinstance(effective.get("events"), list) else seed
    if not isinstance(registry, dict) or not isinstance(registry.get("events"), list):
        registry = {"events": []}
    return reports, registry


def refresh_report_aliases(state_dir: Path, config_dir: Path):
    """Update a bounded, rebuildable index from the already collected board."""
    path = state_dir / INDEX_NAME
    old = _read(path, {})
    items = _alias_rows(old)
    reports, registry = _config(state_dir, config_dir)
    board = _read(state_dir / "massy_board_latest.json", {})
    changed = False
    for row in _observation_rows(board):
        key = _observed_key(row, reports, registry)
        url = row.get("url") or row.get("source_url")
        if not key:
            continue
        if url not in items and len(items) >= MAX_ALIASES:
            continue
        observations = items.setdefault(url, {})
        if key not in observations:
            observations[key] = _evidence(row)
            changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": _VERSION, "items": items}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


def load_report_link_records(state_dir: Path, config_dir: Path) -> dict:
    """Map exact source identities and verified observations to history rows.

    No network or mutations. Historical report destinations still require the
    same anonymous WordPress verification as ordinary news.
    """
    history = _read(state_dir / "simone_report_history.json", {})
    registry = _read(state_dir / "report_publication_registry.json", {})
    candidates = []
    if isinstance(history, dict):
        candidates.extend((key, row) for key, row in history.items())
    if isinstance(registry, dict) and isinstance(registry.get("items"), list):
        candidates.extend((row.get("report_key"), row) for row in registry["items"] if isinstance(row, dict))
    by_key = {}
    direct = {}
    invalid_keys = set()
    for key, row in candidates:
        if not isinstance(row, dict) or not _date_from_key(key) or row.get("report_key", key) != key:
            continue
        identity = source_identity(row.get("source_url"), report=True)
        if identity is not None:
            direct.setdefault(identity, set()).add(key)
        day = _date_from_key(key)
        if (row.get("status", "") not in {"", "publish", "published", "already_published", "completed"}
                or any(row.get(field) and row[field] != day for field in ("date", "show_date", "date_local"))):
            invalid_keys.add(key)
            continue
        if not _stamp(row.get("published_at")) or not row.get("wp_post_id") or not (row.get("wp_link") or row.get("link")):
            continue
        completion = row.get("report_completion")
        if completion is not None and (not isinstance(completion, dict) or completion.get("version") != "totem-r01-completion-v1"
                or completion.get("report_key") != key or completion.get("date") != _date_from_key(key)):
            invalid_keys.add(key)
            continue
        normalized = {**row, "status": "publish", "wp_link": row.get("wp_link") or row.get("link")}
        by_key.setdefault(key, []).append(normalized)

    aliases = _alias_rows(_read(state_dir / INDEX_NAME, {}))
    # Also use the current board in read-only mode, even if index persistence
    # failed or this resolver is called independently of run_publisher.
    reports, effective = _config(state_dir, config_dir)
    for row in _observation_rows(_read(state_dir / "massy_board_latest.json", {})):
        key = _observed_key(row, reports, effective)
        if key:
            url = row.get("url") or row.get("source_url")
            aliases.setdefault(url, {}).setdefault(key, _evidence(row))
    identities = {identity: set(keys) for identity, keys in direct.items()}
    for url, keys in aliases.items():
        identity = source_identity(url, report=True)
        if identity is not None:
            identities.setdefault(identity, set()).update(keys)
    result = {}
    for identity, keys in identities.items():
        if len(keys) != 1:
            continue
        key = next(iter(keys))
        rows = by_key.get(key, [])
        if rows and key not in invalid_keys:
            result[identity] = rows
    return result
