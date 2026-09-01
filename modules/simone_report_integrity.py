"""Deterministic v95.13.1 report reservation, registry and cleanup helpers."""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SEED_REGISTRY = ROOT / "config" / "special_events.json"
REPORTS_CONFIG = ROOT / "config" / "reports_v92.json"
EFFECTIVE_REGISTRY = ROOT / "state" / "newsroom" / "special_events_effective.json"
PENDING_REPORTS = ROOT / "state" / "newsroom" / "simone_pending_reports.json"
SCHEDULE_REPORT_DIR = ROOT / "reports"
SCHEDULE_RUNTIME_DIR = ROOT / "state" / "newsroom" / "special_events_schedule_runtime"
TRUSTED_PROMOTIONS = {"WWE", "AEW", "TNA", "ROH"}
REFRESH_INTERVAL = timedelta(hours=20)
REFRESH_TIMEOUT_SECONDS = 75
ARTIFACT_CLOCK_SKEW = timedelta(minutes=10)


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def normalize_url(url: str) -> str:
    p = urlsplit((url or "").strip())
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit(((p.scheme or "https").lower(), p.netloc.lower(), p.path.rstrip("/") or "/", urlencode(query), ""))


def _slug(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def _nights(key: str, dates: list[str], promotion: str, name: str) -> list[dict[str, Any]]:
    dates = sorted(set(dates))
    many = len(dates) > 1
    return [{"night_key": f"{key}_night_{i}" if many else f"{key}_main", "label": f"Night {i}" if many else "Main show", "date_local": date, "report_publish_after_local": "06:30", "enabled": True, "aliases": [f"{name} results", f"{promotion} {name} results"]} for i, date in enumerate(dates, 1)]


def _proposal_event(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    promotion = str(row.get("promotion") or "").upper()
    dates = sorted(set(str(x) for x in (row.get("dates") or []) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(x))))
    name = str(row.get("event_name") or "").strip()
    if promotion not in TRUSTED_PROMOTIONS:
        return None, "excluded_promotion" if promotion else "missing_promotion"
    if not dates:
        return None, "missing_concrete_date"
    if not name:
        return None, "missing_event_name"
    key = f"{promotion.lower()}_{_slug(name)}_{dates[0][:4]}"
    return {"key": key, "promotion": promotion, "brand": row.get("brand") or promotion, "event_name": name, "aliases": sorted(set([name, f"{promotion} {name}"] + list(row.get("aliases") or []))), "status": "confirmed", "coverage_policy": "multi_night_report_and_post_event_freeze" if len(dates) > 1 else "report_and_post_event_freeze", "category_hint": promotion, "nights": _nights(key, dates, promotion, name), "venue": row.get("venue"), "location": row.get("location"), "source": row.get("source") or "trusted_structured_schedule", "last_verified_at_utc": datetime.now(timezone.utc).isoformat()}, "trusted_dated_event"


def build_effective_registry(seed: dict[str, Any], proposals: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    effective = copy.deepcopy(seed)
    events = effective.setdefault("events", [])
    by_key = {str(e.get("key")): e for e in events if isinstance(e, dict)}
    diagnostics: dict[str, Any] = {"accepted": [], "skipped": [], "ambiguous": []}
    for row in proposals:
        event, reason = _proposal_event(row)
        if event is None:
            diagnostics["skipped"].append({"event_name": row.get("event_name"), "promotion": row.get("promotion"), "reason": reason})
            continue
        exact = by_key.get(event["key"])
        aliases = {_slug(str(event.get("event_name") or "")), *(_slug(str(a)) for a in event.get("aliases", []))}
        possible = [e for e in events if isinstance(e, dict) and str(e.get("promotion") or "").upper() == event["promotion"] and _slug(str(e.get("event_name") or "")) in aliases]
        if exact is None and len(possible) > 1:
            diagnostics["ambiguous"].append({"event_name": event["event_name"], "matches": [e.get("key") for e in possible]})
            continue
        target = exact or (possible[0] if possible else None)
        if target is None:
            events.append(event); by_key[event["key"]] = event
        else:
            # Never delete curated fields; runtime confirmation/date information may advance them.
            target.update({k: v for k, v in event.items() if v is not None and k in {"status", "nights", "venue", "location", "source", "last_verified_at_utc"}})
            target["aliases"] = sorted(set(list(target.get("aliases") or []) + list(event["aliases"])))
        diagnostics["accepted"].append({"key": (target or event).get("key"), "reason": reason})
    return effective, diagnostics


def _schedule_files() -> list[Path]:
    files = list(SCHEDULE_RUNTIME_DIR.glob("special_events_wikipedia_schedule_layer_*.json"))
    files.extend(SCHEDULE_REPORT_DIR.glob("special_events_wikipedia_schedule_layer_*.json"))
    return files


def _artifact_generated_at(path: Path) -> datetime | None:
    raw = _load(path, {})
    value = str(raw.get("generated_at_utc") or "") if isinstance(raw, dict) else ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _newest_valid_artifact(paths: Iterable[Path], now: datetime) -> tuple[Path | None, datetime | None]:
    valid = []
    for path in paths:
        generated_at = _artifact_generated_at(path)
        if generated_at is None or generated_at > now + ARTIFACT_CLOCK_SKEW:
            continue
        valid.append((generated_at, path))
    if not valid:
        return None, None
    generated_at, path = max(valid, key=lambda item: item[0])
    return path, generated_at


def _generate_schedule_artifact() -> Path:
    """Run only the trusted schedule collector, isolated from newsroom publishing."""
    SCHEDULE_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "special_events_wikipedia_schedule_layer.py"), "--repo-dir", str(ROOT), "--report-dir", str(SCHEDULE_RUNTIME_DIR)],
        check=True, timeout=REFRESH_TIMEOUT_SECONDS, capture_output=True, text=True,
    )
    files = list(SCHEDULE_RUNTIME_DIR.glob("special_events_wikipedia_schedule_layer_*.json"))
    path, _generated_at = _newest_valid_artifact(files, datetime.now(timezone.utc))
    if path is None:
        raise RuntimeError("schedule generator produced no JSON artifact")
    return path


def load_effective_registry(now: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    prior = _load(EFFECTIVE_REGISTRY, {})
    refreshed = str(prior.get("refreshed_at_utc") or "") if isinstance(prior, dict) else ""
    try:
        age = now - datetime.fromisoformat(refreshed.replace("Z", "+00:00"))
    except Exception:
        age = REFRESH_INTERVAL + timedelta(seconds=1)
    if isinstance(prior, dict) and prior.get("events") and age < REFRESH_INTERVAL:
        return prior, {"effective_registry_source": "prior_runtime_state", "refresh_status": "fresh_cache", "artifact_generated_at_utc": prior.get("artifact_generated_at_utc")}
    seed = _load(SEED_REGISTRY, {})
    files = _schedule_files()
    artifact: Path | None = None
    artifact_generated_at: datetime | None = None
    refresh_status = "refresh_used_existing_fresh_artifact"
    newest_artifact, newest_generated_at = _newest_valid_artifact(files, now)
    if newest_artifact is not None and newest_generated_at is not None and timedelta(0) <= now - newest_generated_at < REFRESH_INTERVAL:
        artifact, artifact_generated_at = newest_artifact, newest_generated_at
    else:
        try:
            artifact = _generate_schedule_artifact()
            artifact_generated_at = _artifact_generated_at(artifact)
            if artifact_generated_at is None or artifact_generated_at > now + ARTIFACT_CLOCK_SKEW or now - artifact_generated_at >= REFRESH_INTERVAL:
                raise RuntimeError("generated schedule artifact has invalid or stale generated_at_utc")
            refresh_status = "refresh_generated_new_artifact"
        except Exception as exc:
            if isinstance(prior, dict) and prior.get("events"):
                return prior, {"effective_registry_source": "prior_runtime_state", "refresh_status": "refresh_failed_using_prior_state", "refresh_error": str(exc)[:500], "artifact_generated_at_utc": newest_generated_at.isoformat() if newest_generated_at else None}
            return seed, {"effective_registry_source": "static_fallback", "refresh_status": "refresh_failed_using_static_fallback", "refresh_error": str(exc)[:500], "artifact_generated_at_utc": newest_generated_at.isoformat() if newest_generated_at else None}
    if artifact:
        raw = _load(artifact, {})
        proposals = raw.get("events") or raw.get("proposals") or raw.get("schedule") or []
        if isinstance(proposals, list):
            effective, diag = build_effective_registry(seed, [x for x in proposals if isinstance(x, dict)])
            effective["refreshed_at_utc"] = now.isoformat()
            effective["artifact_generated_at_utc"] = artifact_generated_at.isoformat() if artifact_generated_at else None
            effective["runtime_diagnostics"] = diag
            _write(EFFECTIVE_REGISTRY, effective)
            return effective, {"effective_registry_source": "refreshed_structured_schedule", "refresh_status": refresh_status, "schedule_artifact": str(artifact), "artifact_generated_at_utc": artifact_generated_at.isoformat() if artifact_generated_at else None, **diag}
    if isinstance(prior, dict) and prior.get("events"):
        return prior, {"effective_registry_source": "prior_runtime_state", "refresh_status": "refresh_failed_using_prior_state", "refresh_error": "invalid_schedule_artifact", "artifact_generated_at_utc": artifact_generated_at.isoformat() if artifact_generated_at else None}
    return seed, {"effective_registry_source": "static_fallback", "refresh_status": "refresh_failed_using_static_fallback", "refresh_error": "invalid_schedule_artifact", "artifact_generated_at_utc": artifact_generated_at.isoformat() if artifact_generated_at else None}


REPORT_WORDS = re.compile(r"\b(results?|risultati|live[\s-]+results?)\b", re.I)

MONTH_NUMBERS = {name.lower(): number for number, names in enumerate(((), ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"), ("december", "dec"))) for name in names}


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except Exception:
        try:
            return parsedate_to_datetime(value)
        except Exception:
            return None


def candidate_date_evidence(entry: dict[str, Any], expected_date: str) -> dict[str, Any]:
    """Apply the single canonical explicit-date-then-timestamp contract."""
    try:
        expected = datetime.strptime(expected_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {"matches": False, "explicit_content_dates": set(), "feed_timestamp_dates": set()}
    content = " ".join(str(entry.get(k) or "") for k in ("title", "url", "source_url"))
    explicit: set[str] = set()
    for year, month, day in re.findall(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", content):
        explicit.add(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
    for month, day, year in re.findall(r"(?<!\d)(\d{1,2})/(\d{1,2})/(20\d{2})(?!\d)", content):
        explicit.add(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
    for month, day in re.findall(r"(?<!\d[-/])(?<![\d/])(\d{1,2})[/-](\d{1,2})(?![/\d])", content):
        explicit.add(f"{expected.year:04d}-{int(month):02d}-{int(day):02d}")
    month_pattern = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
    for month, day, year in re.findall(rf"\b({month_pattern})\s+(\d{{1,2}})(?:,?\s+(20\d{{2}}))?\b", content, re.I):
        explicit.add(f"{int(year) if year else expected.year:04d}-{MONTH_NUMBERS[month.lower()]:02d}-{int(day):02d}")
    stamps = {_parse_timestamp(str(entry.get(k) or "")) for k in ("published", "published_at", "updated")}
    feed_dates = {stamp.date().isoformat() for stamp in stamps if stamp is not None}
    if explicit:
        matches = expected.isoformat() in explicit
    else:
        next_date = (expected + timedelta(days=1)).isoformat()
        matches = bool(feed_dates & {expected.isoformat(), next_date})
    return {"matches": matches, "explicit_content_dates": explicit, "feed_timestamp_dates": feed_dates}


def dynamic_special_event_match(entry: dict[str, Any], registry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    raw = " ".join(str(entry.get(k) or "") for k in ("title", "url", "source_url"))
    source_blob = f"{entry.get('source', '')} {entry.get('url', '')} {entry.get('source_url', '')}".lower().replace(" ", "")
    if "wrestlinginc" not in source_blob:
        return None, "waiting_for_canonical_results_source"
    explicit_report = bool(re.search(r"\bresults\b|\brisultati\b", raw, re.I))
    if not explicit_report:
        return None, "rejected_non_results_event_article"
    normalized_raw = _slug(raw).replace("_", " ")
    weekly_cfg = _load(REPORTS_CONFIG, {"reports": []})
    for weekly in weekly_cfg.get("reports", []) if isinstance(weekly_cfg, dict) else []:
        show = _slug(str(weekly.get("show_name") or "")).replace("_", " ") if isinstance(weekly, dict) else ""
        if show and re.search(rf"\b{re.escape(show)}\s+results\b", normalized_raw):
            return None, "rejected_conflicting_weekly_identity"
    blob = normalized_raw
    matches: list[tuple[int, dict[str, Any]]] = []
    for event in registry.get("events", []):
        if not isinstance(event, dict) or str(event.get("status") or "").lower() not in {"confirmed", "active"}:
            continue
        event_aliases = [event.get("event_name")] + list(event.get("aliases") or [])
        for night in event.get("nights", []):
            if not isinstance(night, dict) or not night.get("enabled", True):
                continue
            night_aliases = list(night.get("aliases") or [])
            aliases = event_aliases + night_aliases
            hits = sorted({str(a) for a in aliases if a and len(_slug(str(a))) >= 4 and _slug(str(a)).replace("_", " ") in blob}, key=len, reverse=True)
            if not hits:
                continue
            night_date = str(night.get("date_local") or "")
            date_evidence = candidate_date_evidence(entry, night_date)
            if not date_evidence["matches"]:
                continue
            explicit_dates = date_evidence["explicit_content_dates"]
            feed_dates = date_evidence["feed_timestamp_dates"]
            try:
                next_date = (datetime.strptime(night_date, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
            except ValueError:
                next_date = ""
            timestamp_compatible = bool(feed_dates & {night_date, next_date})
            night_alias_hit = next((hit for hit in hits if hit in night_aliases), None)
            score = len(_slug(hits[0])) + (200 if night_date in explicit_dates else 0) + (100 if timestamp_compatible and feed_dates else 0) + (50 if night_alias_hit else 0)
            metadata = {
                "event_key": event.get("key"), "night_key": night.get("night_key"),
                "report_key": f"special_event_{night.get('night_key')}_{night_date.replace('-', '_')}",
                "date_local": night_date,
                "publish_after": night.get("report_publish_after_local") or registry.get("default_report_publish_after_local") or "06:30",
                "category_hint": event.get("category_hint") or event.get("promotion"),
                "event_name": event.get("event_name"), "promotion": event.get("promotion"),
                "aliases": sorted({str(alias) for alias in aliases if alias}),
                "canonical_identity": "wrestlinginc_results",
                "match_evidence": {"strong_alias": hits[0], "night_alias": night_alias_hit, "alias_hits": hits, "explicit_content_dates": sorted(explicit_dates), "feed_timestamp_dates": sorted(feed_dates), "explicit_date_match": night_date in explicit_dates, "feed_timestamp_compatible": timestamp_compatible, "promotion_support": str(event.get("promotion") or "").lower() in blob},
            }
            matches.append((score, metadata))
    matches.sort(key=lambda item: item[0], reverse=True)
    if not matches or (len(matches) > 1 and matches[0][0] == matches[1][0]):
        return None, "ambiguous_event_match" if matches else "event_alias_not_found"
    return matches[0][1], "canonical_results_match"


def reserve_report(candidate: dict[str, Any], identity: dict[str, Any], *, now: datetime, pending_path: Path = PENDING_REPORTS) -> dict[str, Any]:
    """Reserve a validated source without allowing later URLs to reopen selection."""
    state = _load(pending_path, {"reports": []}); rows = state.get("reports", []) if isinstance(state, dict) else []
    url = normalize_url(str(candidate.get("url") or candidate.get("source_url") or "")); key = str(identity.get("report_key") or "")
    locked = next((r for r in rows if isinstance(r, dict) and r.get("report_key") == key and r.get("canonical_source_locked") is True), None)
    existing = next((r for r in rows if isinstance(r, dict) and r.get("report_key") == key and r.get("normalized_url") == url), None)
    if existing is None:
        existing = {**identity, "source_url": url, "normalized_url": url, "source": candidate.get("source"), "source_title": candidate.get("title"), "published": candidate.get("published"), "published_at": candidate.get("published_at"), "updated": candidate.get("updated"), "discovered_at": now.isoformat(), "status": "waiting_publish_after", "last_checked_at": None, "readiness": None, "retry_count": 0}
        rows.append(existing)
    else:
        for field, value in identity.items():
            if value is not None:
                existing[field] = value
    if locked is None:
        existing["canonical_source_locked"] = True
        existing["identity_reason"] = "canonical_source_locked"
    elif locked is not existing:
        existing["canonical_source_locked"] = False
        existing["status"] = "later_canonical_candidate_ignored"
        existing["identity_reason"] = "later_canonical_candidate_ignored"
        existing["locked_source_url"] = locked.get("source_url")
    state = {"updated_at": now.isoformat(), "reports": rows}; _write(pending_path, state)
    return locked or existing


OUTCOME_RE = re.compile(r"\b(defeated|defeats|winner|won|retained|retains|pinfall|submission|disqualification|via pin|via submission|new champion)\b", re.I)
RESULT_HEADING_RE = re.compile(r"\b(?:match\s+\d+\s*[:\-]|(?:official\s+)?result|winner)\s*[:\-]", re.I)
PREVIEW_RE = re.compile(r"\b(will face|scheduled|tonight['’]?s card|announced card|previously|last week|previous event|background|storyline|is set to|will challenge)\b", re.I)


def report_readiness(blocks: Iterable[Any]) -> dict[str, Any]:
    texts = [str(b.get("text") or "") if isinstance(b, dict) else BeautifulSoup(str(b), "html.parser").get_text(" ", strip=True) for b in blocks]
    current_units = historical = headings = 0
    for index, text in enumerate(texts):
        if PREVIEW_RE.search(text):
            historical += len(OUTCOME_RE.findall(text)); continue
        heading = bool(RESULT_HEADING_RE.search(text))
        outcome = bool(OUTCOME_RE.search(text))
        adjacent_heading = index > 0 and bool(RESULT_HEADING_RE.search(texts[index - 1])) and not PREVIEW_RE.search(texts[index - 1])
        if heading: headings += 1
        if (heading and outcome) or (outcome and adjacent_heading) or (outcome and re.search(r"\b(?:via|by)\s+(?:pinfall|submission|disqualification)|\bretained\s+(?:the|his|her)\s+title\b", text, re.I)):
            current_units += 1
    ready = current_units >= 2
    return {"ready": ready, "reason": "ready_complete_results" if ready else "waiting_source_completion", "evidence": {"current_result_units": current_units, "structured_result_headings": headings, "historical_outcome_markers_excluded": historical}}


INTRO_RE = re.compile(r"^(?:welcome to (?:wrestling inc\.?['’]?s|our) (?:live coverage|results)(?:\s+for)?|this is wrestling inc\.?['’]?s (?:live coverage|results)|wrestling inc\.? will provide live coverage|coverage begins at)\b", re.I)
BIO_SIGNALS = [re.compile(x, re.I) for x in [r"ringside news", r"(?:cover(?:ing|s)|writes?) wrestling news|(?:si occupa|scrive) di news di wrestling", r"(?:nearly |for )?\w+ years|da .+ anni", r"articles? (?:have been )?(?:picked up|featured)|articoli (?:sono stati )?(?:ripresi|pubblicati)", r"\b(?:TMZ|Forbes|The Sun)\b"]]


def is_author_bio(text: str, *, explicit_container: bool = False) -> bool:
    hits = sum(bool(p.search(text or "")) for p in BIO_SIGNALS)
    return hits >= (2 if explicit_container else 3)


def cleanup_blocks(blocks: list[dict[str, Any]], source: str = "") -> tuple[list[dict[str, Any]], dict[str, int]]:
    out = list(blocks); intro = bio = 0
    if "wrestlinginc" in _slug(source):
        while out[:1] and INTRO_RE.search(str(out[0].get("text") or "").strip()): out.pop(0); intro += 1
    # Only trailing prose is considered unless the scraper explicitly identified a bio container.
    for i in range(len(out) - 1, max(-1, len(out) - 7), -1):
        block = out[i]; explicit = "author" in str(block.get("class") or block.get("type") or "").lower()
        if is_author_bio(str(block.get("text") or ""), explicit_container=explicit): out.pop(i); bio += 1
    return out, {"wrestlinginc_intro_blocks_removed": intro, "author_bio_blocks_removed": bio}


def cleanup_rendered_html(content: str, source: str = "") -> tuple[str, dict[str, int]]:
    soup = BeautifulSoup(content or "", "html.parser"); removed = 0
    blocks = soup.find_all(["p", "div", "section", "aside"], recursive=False)
    for i, node in enumerate(list(blocks)):
        text = node.get_text(" ", strip=True); classes = " ".join(node.get("class", []))
        if (i < 3 and "wrestlinginc" in _slug(source) and INTRO_RE.search(text)) or is_author_bio(text, explicit_container="author" in classes.lower()): node.decompose(); removed += 1
    return str(soup), {"final_boilerplate_blocks_removed": removed}
