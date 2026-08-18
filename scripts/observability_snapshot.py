#!/usr/bin/env python3
"""Reusable 24-hour observability snapshot for repository-side reports.

Measurement-only helpers: read local master-log artifacts, normalize article
identity, and render a JSON-serializable snapshot without mutating newsroom
runtime state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCHEMA_VERSION = "v95.26_p1_4_authoritative_snapshot.v4"
METRIC_CONTRACT_VERSION = "v95.19.0"
POLICY_VERSION = "v95.26_p1_4"
ACTIVE_DUPLICATE_COUNTERS = (
    "menzo_same_run_batch_calls",
    "menzo_same_run_batch_repairs",
    "menzo_same_run_micro_fallback_calls",
    "menzo_same_run_duplicate_groups",
    "menzo_same_run_duplicates_blocked",
    "menzo_recent_history_batch_calls",
    "menzo_recent_history_batch_repairs",
    "menzo_recent_history_micro_fallback_calls",
    "menzo_recent_history_duplicates_blocked",
    "menzo_recent_history_material_updates",
    "menzo_duplicate_arbitration_fail_closed",
    "gemini_calls_used_for_duplicate_arbitration",
)
LEGACY_DUPLICATE_KEYS = ("footprint", "fingerprint", "story_footprint", "story_fingerprint", "duplicate_candidates", "same_story_clusters")
EXPECTED_RUNTIME_PATHS = (".bot_exit_code", "logs/master_log.log", "reports/")


def section_metadata(*, available: bool, source: str, coverage: Any = None,
                     warnings: list[str] | None = None, reason: str | None = None) -> dict[str, Any]:
    coverage_name = coverage if isinstance(coverage, str) else ((coverage or {}).get("status") if isinstance(coverage, dict) else None)
    coverage_value = ({**coverage, "status": coverage_name or ("full" if available else "unavailable")}
                      if isinstance(coverage, dict) else coverage_name or ("full" if available else "unavailable"))
    return {"available": available, "coverage": coverage_value,
            "complete_window": coverage_name == "full" if coverage_name else available, "source": source,
            "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
            "diagnostic_mismatches": warnings or [], "diagnostic_warnings": warnings or [],
            "coverage_detail": coverage if isinstance(coverage, dict) else {},
            "unavailability_reason": reason if not available else None}


def parse_utc_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(text)
        except Exception:
            return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def canonical_source_url(url: Any) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    p = urlsplit(raw)
    keep_q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((p.scheme.lower() or "https", p.netloc.lower().removeprefix("www."), p.path.rstrip("/"), urlencode(keep_q), ""))


def normalized_title(title: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()


def stable_article_identity(record: dict[str, Any]) -> str:
    for key in ("source_url", "url", "original_url", "link"):
        u = canonical_source_url(record.get(key))
        if u:
            return "source:" + u
    for key in ("wp_link", "wordpress_url", "published_url", "final_url"):
        u = canonical_source_url(record.get(key))
        if u:
            return "wp:" + u
    title = normalized_title(record.get("title") or record.get("title_it") or record.get("headline") or record.get("source_title"))
    return "title:" + title if title else "unknown:" + hashlib.sha1(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()[:12]


def identity_aliases(record: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for key in ("source_url", "url", "original_url", "link"):
        u = canonical_source_url(record.get(key))
        if u:
            aliases.add("source:" + u)
    for key in ("wp_link", "wordpress_url", "published_url", "final_url"):
        u = canonical_source_url(record.get(key))
        if u:
            aliases.add("wp:" + u)
    title = normalized_title(record.get("title") or record.get("title_it") or record.get("headline") or record.get("source_title"))
    if title:
        aliases.add("title:" + title)
    if not aliases:
        aliases.add(stable_article_identity(record))
    return aliases


def linkage_aliases(record: dict[str, Any]) -> set[str]:
    """Return only externally meaningful aliases; never hashed fallback identities."""
    aliases = identity_aliases(record)
    return {alias for alias in aliases if not alias.startswith("unknown:")}


def linkage_aliases_by_namespace(record: dict[str, Any]) -> dict[str, set[str]]:
    grouped = {namespace: set() for namespace in ("source", "wp", "title")}
    for alias in linkage_aliases(record):
        namespace, _separator, _value = alias.partition(":")
        if namespace in grouped:
            grouped[namespace].add(alias)
    return grouped


def load_json_defensively(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace")), None
    except Exception as exc:
        return None, f"read_failed:{path}:{exc}"


def load_jsonl_defensively(path: Path) -> tuple[list[dict[str, Any]], list[str], bool, int]:
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    malformed = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return [], [f"read_failed:{path}:{exc}"], False, 0
    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            malformed += 1
            warnings.append(f"malformed_jsonl:{path}:{idx}")
    return rows, warnings, True, malformed

def flatten_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from flatten_dicts(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from flatten_dicts(x)


def _nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        cur = cur.get(key) if isinstance(cur, dict) else None
    return cur


def record_time(record: dict[str, Any]) -> datetime | None:
    for k in ("published_at", "recorded_at", "created_at", "timestamp", "ts", "ended_at", "started_at"):
        dt = parse_utc_datetime(record.get(k))
        if dt:
            return dt
    for path in (("run", "ended_at"), ("run", "started_at"), ("event", "timestamp")):
        dt = parse_utc_datetime(_nested(record, *path))
        if dt:
            return dt
    return None


def master_run_timestamp(run_record: dict[str, Any]) -> datetime | None:
    return parse_utc_datetime(run_record.get("recorded_at")) or parse_utc_datetime(_nested(run_record, "run", "ended_at")) or parse_utc_datetime(_nested(run_record, "run", "started_at"))


def child_event_timestamp(child: dict[str, Any], parent_run: dict[str, Any]) -> datetime | None:
    return record_time(child) or master_run_timestamp(parent_run)


def master_run_identity(run_record: dict[str, Any]) -> str:
    run = run_record.get("run") if isinstance(run_record.get("run"), dict) else {}
    for key in ("github_run_id", "run_id"):
        value = run.get(key) or run_record.get(key)
        if value:
            return f"{key}:{value}"
    started = str(run.get("started_at") or "")
    ended = str(run.get("ended_at") or "")
    if started or ended:
        return "run_window:" + started + "|" + ended
    recorded = str(run_record.get("recorded_at") or "")
    return "recorded_at:" + recorded if recorded else "object:" + hashlib.sha1(json.dumps(run_record, sort_keys=True, default=str).encode()).hexdigest()[:12]


def in_window_dt(dt: datetime | None, since: datetime, until: datetime) -> bool:
    return bool(dt and since <= dt <= until)


def in_window(record: dict[str, Any], since: datetime, until: datetime) -> bool:
    return in_window_dt(record_time(record), since, until)


def dedupe_events(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for r in records:
        key = stable_article_identity(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _items(d: Any, key: str) -> list[dict[str, Any]]:
    v = d.get(key) if isinstance(d, dict) else None
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _is_production_shaped(row: dict[str, Any]) -> bool:
    return isinstance(row.get("run"), dict) or str(row.get("schema_version") or "").startswith("v93_19")


def load_master_runs(root: Path = ROOT, *, allow_tail_fallback: bool = True) -> tuple[list[dict[str, Any]], list[str], list[str], bool, dict[str, Any]]:
    sources: list[str] = []
    warnings: list[str] = []
    primary = root / "state/newsroom/master_log.jsonl"
    tail = root / "artifacts/newsroom/master_log_tail.jsonl"
    rows: list[dict[str, Any]] = []
    source_name = "missing"
    malformed = 0
    readable = False
    tail_fallback_used = False

    if primary.exists():
        primary_rows, ws, readable, malformed = load_jsonl_defensively(primary)
        warnings.extend(ws)
        sources.append(str(primary.relative_to(root)))
        production_rows = [r for r in primary_rows if _is_production_shaped(r)]
        if readable and (production_rows or (not primary_rows and malformed == 0)):
            rows = production_rows
            source_name = "primary"
        elif allow_tail_fallback and tail.exists():
            tail_rows, tail_ws, tail_readable, tail_malformed = load_jsonl_defensively(tail)
            warnings.extend(tail_ws)
            sources.append(str(tail.relative_to(root)))
            rows = [r for r in tail_rows if _is_production_shaped(r)]
            source_name = "tail_fallback"
            readable = tail_readable
            malformed += tail_malformed
            tail_fallback_used = True
        else:
            rows = []
            source_name = "primary_unusable"
    elif allow_tail_fallback and tail.exists():
        tail_rows, ws, readable, malformed = load_jsonl_defensively(tail)
        warnings.extend(ws)
        sources.append(str(tail.relative_to(root)))
        rows = [r for r in tail_rows if _is_production_shaped(r)]
        source_name = "tail"
        tail_fallback_used = True

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict):
            deduped[master_run_identity(row)] = row
    out = list(deduped.values())
    authority_available = bool(readable and (out or source_name == "primary" and primary.exists()))
    health = {
        "master_log_source": source_name,
        "master_log_partial": malformed > 0 and bool(out),
        "master_log_valid_rows": len(out),
        "master_log_malformed_lines": malformed,
        "tail_fallback_used": tail_fallback_used,
    }
    return out, sources, warnings, authority_available, health

def load_runtime_records(root: Path = ROOT) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    # Kept for compatibility with tests/importers that only need defensive JSON access.
    runs, sources, warnings, _available, _health = load_master_runs(root)
    return runs, sources, warnings


def iter_master_runs_in_window(runs: Iterable[dict[str, Any]], since: datetime, until: datetime) -> Iterable[dict[str, Any]]:
    for run in runs:
        if in_window_dt(master_run_timestamp(run), since, until):
            yield run


def _with_parent_timestamp(child: dict[str, Any], parent: dict[str, Any]) -> dict[str, Any]:
    clone = dict(child)
    dt = child_event_timestamp(child, parent)
    if dt and not any(clone.get(k) for k in ("published_at", "timestamp", "recorded_at", "created_at")):
        clone["_observed_at"] = dt.isoformat()
    return clone


def _child_in_window(child: dict[str, Any], parent: dict[str, Any], since: datetime, until: datetime) -> bool:
    return in_window_dt(child_event_timestamp(child, parent), since, until)


def _publication_record(c: dict[str, Any], kind: str, parent: dict[str, Any]) -> dict[str, Any]:
    dt = child_event_timestamp(c, parent)
    return {
        "source_url": c.get("source_url") or c.get("url") or c.get("original_url") or "",
        "wp_link": c.get("wp_link") or c.get("wordpress_url") or c.get("published_url") or c.get("link") or "",
        "title": c.get("title") or c.get("title_it") or c.get("headline") or "",
        "source": c.get("source") or "",
        "published_at": dt.isoformat() if dt else "",
        "content_kind": kind,
    }


def build_authoritative_publication_set(runs: list[dict[str, Any]], since: datetime, until: datetime) -> dict[str, Any]:
    news: dict[str, dict[str, Any]] = {}
    reports: dict[str, dict[str, Any]] = {}
    for run in iter_master_runs_in_window(runs, since, until):
        publisher = run.get("publisher") if isinstance(run.get("publisher"), dict) else {}
        for item in _items(publisher, "published"):
            if _child_in_window(item, run, since, until):
                news[stable_article_identity(item)] = _publication_record(item, "news", run)
        for item in _items(publisher, "results"):
            if str(item.get("status") or "").lower() == "published" and _child_in_window(item, run, since, until):
                news[stable_article_identity(item)] = _publication_record(item, "news", run)
        simone = run.get("simone") if isinstance(run.get("simone"), dict) else {}
        for item in _items(simone, "published_reports"):
            if str(item.get("status") or "").lower() == "published" and _child_in_window(item, run, since, until):
                reports[stable_article_identity(item)] = _publication_record(item, "report", run)
    records = list(news.values()) + list(reports.values())
    return {"news_unique": len(news), "reports_unique": len(reports), "total_unique": len(news) + len(reports), "records": records}


def _add_items(bucket: list[dict[str, Any]], parent: dict[str, Any], items: list[dict[str, Any]], since: datetime, until: datetime) -> int:
    count = 0
    for item in items:
        if _child_in_window(item, parent, since, until):
            bucket.append(_with_parent_timestamp(item, parent))
            count += 1
    return count


def _run_exit_bucket(run: dict[str, Any]) -> str:
    value = _nested(run, "run", "runtime_exit_code")
    if value is None or value == "":
        return "unknown"
    try:
        return "completed" if int(value) == 0 else "failed"
    except Exception:
        return "unknown"


def build_editorial_funnel(runs: list[dict[str, Any]], publication: dict[str, Any], since: datetime, until: datetime) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    event_counts: Counter[str] = Counter()
    runs_seen = runs_completed = runs_failed = runs_unknown = 0
    actionable_identity_keys: set[str] = set()
    actionable_ambiguous = False
    for run in iter_master_runs_in_window(runs, since, until):
        runs_seen += 1
        bucket = _run_exit_bucket(run)
        if bucket == "completed":
            runs_completed += 1
        elif bucket == "failed":
            runs_failed += 1
        else:
            runs_unknown += 1
        menzo = run.get("menzo") if isinstance(run.get("menzo"), dict) else {}
        persisted_keys = menzo.get("actionable_identity_keys")
        if isinstance(persisted_keys, list):
            actionable_identity_keys.update(str(key) for key in persisted_keys if str(key).strip())
        else:
            selected_details = _items(menzo, "selected")
            pending_details = _items(menzo, "pending")
            pending_total = menzo.get("pending_total")
            explicitly_exact = isinstance(pending_total, int) and pending_total == len(pending_details)
            truncated = menzo.get("pending_sample_truncated") is True
            if truncated or (len(pending_details) == 20 and not explicitly_exact):
                actionable_ambiguous = True
            else:
                actionable_identity_keys.update(stable_article_identity(item) for item in selected_details + pending_details)
        bob = run.get("bob") if isinstance(run.get("bob"), dict) else {}
        alfred = run.get("alfred") if isinstance(run.get("alfred"), dict) else {}
        publisher = run.get("publisher") if isinstance(run.get("publisher"), dict) else {}
        simone = run.get("simone") if isinstance(run.get("simone"), dict) else {}
        mapping = {
            "menzo_selected_downstream": _items(menzo, "selected"),
            "menzo_pending": _items(menzo, "pending"),
            "menzo_skipped_sample": _items(menzo, "skipped_sample"),
            "bob_packages_produced": _items(bob, "articles"),
            "alfred_reviews": _items(alfred, "reviews"),
            "publisher_published": (_items(publisher, "published") if "published" in publisher else [x for x in _items(publisher, "results") if str(x.get("status") or "").lower() == "published"]),
            "simone_reports_published": [x for x in _items(simone, "published_reports") if str(x.get("status") or "").lower() == "published"],
        }
        for name, items in mapping.items():
            event_counts[name] += _add_items(buckets[name], run, items, since, until)
    unique: dict[str, Any] = {
        "massy_unique_candidates_seen": None,
        "menzo_unique_actionable_candidates": None if actionable_ambiguous else len(actionable_identity_keys),
        "menzo_unique_selected_for_downstream_handoff": len({stable_article_identity(x) for x in buckets["menzo_selected_downstream"]}),
        "menzo_selected_downstream": len({stable_article_identity(x) for x in buckets["menzo_selected_downstream"]}),
        "menzo_unique_skipped_sample": len({stable_article_identity(x) for x in buckets["menzo_skipped_sample"]}),
        "andrea_unique_checked": None,
        "andrea_unique_blocked": None,
        "bob_unique_packages_produced": len({stable_article_identity(x) for x in buckets["bob_packages_produced"]}),
        "bob_unique_errors": None,
        "alfred_unique_reviews": len({stable_article_identity(x) for x in buckets["alfred_reviews"]}),
        "publisher_unique_published": publication["news_unique"],
        "publisher_published": publication["news_unique"],
        "simone_unique_reports_published": publication["reports_unique"],
        "simone_reports_published": publication["reports_unique"],
    }
    schema_warnings = [
        "massy_item_level_candidates_not_reconstructable_from_master_log_v93_19",
        "andrea_item_level_outcomes_not_reconstructable_from_master_log_v93_19",
        "bob_item_level_errors_not_reconstructable_from_master_log_v93_19",
    ]
    actionable_unavailability_reason = None
    if actionable_ambiguous:
        actionable_unavailability_reason = "menzo_actionable_identities_unavailable_legacy_pending_sample_at_cap"
        schema_warnings.append(actionable_unavailability_reason)
    handoffs = dedupe_events(buckets["menzo_selected_downstream"])
    publications = dedupe_events([x for x in publication.get("records", []) if x.get("content_kind") == "news"])
    handoff_aliases = [linkage_aliases_by_namespace(item) for item in handoffs]
    publication_aliases = [linkage_aliases_by_namespace(item) for item in publications]
    handoff_namespaces = {namespace for aliases in handoff_aliases for namespace, values in aliases.items() if values}
    publication_namespaces = {namespace for aliases in publication_aliases for namespace, values in aliases.items() if values}
    shared_namespaces = handoff_namespaces & publication_namespaces
    comparable = lambda aliases: any(aliases[namespace] for namespace in shared_namespaces)
    linked_handoff_ids = {stable_article_identity(h) for h in handoffs
                          if any(any(linkage_aliases_by_namespace(h)[namespace] & linkage_aliases_by_namespace(p)[namespace]
                                     for namespace in shared_namespaces) for p in publications)}
    linkage_supported = bool(handoffs and publications and shared_namespaces and
                             all(comparable(aliases) for aliases in handoff_aliases + publication_aliases))
    linkage_unavailability_reason = None
    if linkage_supported:
        overlap = len(linked_handoff_ids)
        selected_publication_ratio = overlap / len(handoffs)
    else:
        overlap = None
        selected_publication_ratio = None
        linkage_unavailability_reason = ("selected_publication_linkage_no_shared_namespace"
                                          if handoffs and publications and not shared_namespaces
                                          else "selected_publication_linkage_incomplete_shared_namespace_coverage")
        schema_warnings.append(linkage_unavailability_reason)
        schema_warnings.append("selected_publication_linkage_not_supported_by_available_identities")
    return {
        "runs_seen": runs_seen,
        "runs_completed": runs_completed,
        "runs_failed": runs_failed,
        "runs_unknown_exit": runs_unknown,
        "unique": unique,
        "event_counts": dict(event_counts),
        "selected_publication_overlap": overlap,
        "selected_publication_ratio": selected_publication_ratio,
        "selected_publication_linkage_unavailability_reason": linkage_unavailability_reason,
        "canonical": {
            "unique_actionable_candidates": unique["menzo_unique_actionable_candidates"],
            "unique_downstream_handoffs": len(handoffs),
            "unique_final_publications": len(publications),
            "linked_handoff_publication_overlap": overlap,
            "handoff_to_publication_ratio": selected_publication_ratio,
        },
        "canonical_unavailability_reasons": {
            "unique_actionable_candidates": actionable_unavailability_reason,
        },
        "schema_warnings": schema_warnings,
    }


def aggregate_andrea(runs: list[dict[str, Any]], since: datetime, until: datetime) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    exception_reasons: Counter[str] = Counter()
    covered_runs = 0
    total_runs = 0
    field_map = {
        "checked": "andrea_checked",
        "passed": "andrea_passed",
        "blocked": "andrea_blocked",
        "passed_with_exception": "andrea_passed_with_exception",
        "saved_gemini_calls": "andrea_saved_gemini_calls",
        "fetch_performed": "andrea_fetch_performed",
        "bob_may_reextract": "andrea_bob_may_reextract",
    }
    for run in iter_master_runs_in_window(runs, since, until):
        total_runs += 1
        andrea = run.get("andrea") if isinstance(run.get("andrea"), dict) else {}
        handoff = andrea.get("handoff") if isinstance(andrea.get("handoff"), dict) else {}
        if not any(key in handoff for key in field_map.values()):
            continue
        covered_runs += 1
        for output_key, source_key in field_map.items():
            value = handoff.get(source_key)
            if isinstance(value, int) and value >= 0:
                counters[output_key] += value
        reasons = handoff.get("andrea_exception_reasons")
        if isinstance(reasons, dict):
            for reason, count in reasons.items():
                if isinstance(count, int) and count > 0:
                    exception_reasons[str(reason)] += count
    available = covered_runs > 0
    warnings: list[str] = []
    if total_runs and not available:
        warnings.append("andrea_event_stream_not_available")
    elif covered_runs < total_runs:
        warnings.append("andrea_event_stream_partial_coverage")
    return {
        "available": available,
        "covered_runs": covered_runs,
        "total_runs": total_runs,
        "events": ({key: int(counters[key]) for key in field_map} if available else {}),
        "exception_reasons": (dict(sorted(exception_reasons.items())) if available else {}),
        "schema_warnings": warnings,
    }


def aggregate_duplicate_arbitration(runs: list[dict[str, Any]], since: datetime, until: datetime) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    counters: Counter[str] = Counter()
    legacy: Counter[str] = Counter()
    covered_runs = 0
    total_runs = 0
    for run in iter_master_runs_in_window(runs, since, until):
        total_runs += 1
        menzo = run.get("menzo") if isinstance(run.get("menzo"), dict) else {}
        payload = menzo.get("duplicate_arbitration") if isinstance(menzo.get("duplicate_arbitration"), dict) else None
        if payload:
            covered_runs += 1
            for key in ACTIVE_DUPLICATE_COUNTERS:
                if isinstance(payload.get(key), int):
                    counters[key] += payload[key]
        for d in flatten_dicts(menzo):
            for key, value in d.items():
                if any(token in str(key).lower() for token in LEGACY_DUPLICATE_KEYS) and isinstance(value, int):
                    legacy[str(key)] += value
    available = covered_runs > 0
    warnings = [] if available else ["menzo_duplicate_arbitration_counter_stream_not_available"]
    return {"available": available, "covered_runs": covered_runs, "total_runs": total_runs, "counters": ({key: int(counters[key]) for key in ACTIVE_DUPLICATE_COUNTERS} if available else {})}, dict(legacy), warnings


def _warning_entries(review: dict[str, Any]) -> list[Any]:
    return review.get("warnings", []) if isinstance(review.get("warnings"), list) else []


def _blocker_entries(review: dict[str, Any]) -> list[Any]:
    return review.get("blockers", []) if isinstance(review.get("blockers"), list) else []


def _review_status(review: dict[str, Any]) -> str:
    return str(review.get("status") or review.get("decision") or "").strip().lower()


def _event_is_unresolved(review: dict[str, Any]) -> bool:
    return _review_status(review) == "needs_revision" or bool(_blocker_entries(review))


def aggregate_alfred(runs: list[dict[str, Any]], publication: dict[str, Any], since: datetime, until: datetime) -> dict[str, Any]:
    reviews: list[tuple[datetime, dict[str, Any]]] = []
    for run in iter_master_runs_in_window(runs, since, until):
        alfred = run.get("alfred") if isinstance(run.get("alfred"), dict) else {}
        for review in _items(alfred, "reviews"):
            dt = child_event_timestamp(review, run)
            if in_window_dt(dt, since, until):
                reviews.append((dt or since, _with_parent_timestamp(review, run)))
    warning_reviews = [(dt, r) for dt, r in reviews
                       if _warning_entries(r) or isinstance(r.get("warning_occurrences_total"), int) and r["warning_occurrences_total"] > 0]
    warning_occurrences_lower_bound = sum(len(_warning_entries(r)) for _dt, r in reviews)
    warning_occurrences_ambiguous = any(
        not isinstance(r.get("warning_occurrences_total"), int) and len(_warning_entries(r)) == 10
        for _dt, r in reviews
    )
    warning_occurrences = None if warning_occurrences_ambiguous else sum(
        r["warning_occurrences_total"] if isinstance(r.get("warning_occurrences_total"), int) else len(_warning_entries(r))
        for _dt, r in reviews
    )
    events = {
        "warning_count": sum(len(_warning_entries(r)) for _dt, r in reviews),
        "warning_events": len(warning_reviews),
        "warning_occurrences": warning_occurrences,
        "warning_occurrences_diagnostic_lower_bound": warning_occurrences_lower_bound,
        "needs_revision_count": sum(1 for _dt, r in reviews if _review_status(r) == "needs_revision"),
        "blocker_count": sum(len(_blocker_entries(r)) for _dt, r in reviews),
    }
    by_identity: dict[str, list[tuple[datetime, str, dict[str, Any]]]] = defaultdict(list)
    for dt, review in reviews:
        by_identity[stable_article_identity(review)].append((dt, "review", review))
    for record in publication.get("records", []):
        dt = parse_utc_datetime(record.get("published_at"))
        if in_window_dt(dt, since, until):
            by_identity[stable_article_identity(record)].append((dt or since, "publication", record))
    unique = Counter()
    for _identity, rows in by_identity.items():
        rows.sort(key=lambda x: (x[0], 0 if x[1] == "review" else 1))
        latest_review = next((payload for _dt, kind, payload in reversed(rows) if kind == "review"), None)
        latest_review_dt = next((dt for dt, kind, _payload in reversed(rows) if kind == "review"), None)
        latest_publication_dt = next((dt for dt, kind, _payload in reversed(rows) if kind == "publication"), None)
        unresolved_times = [dt for dt, kind, payload in rows if kind == "review" and _event_is_unresolved(payload)]
        approved_times = [dt for dt, kind, payload in rows if kind == "review" and _review_status(payload) == "approved"]
        if latest_review is not None and _review_status(latest_review) == "approved":
            unique["approved"] += 1
        if unresolved_times and approved_times and max(approved_times) > min(unresolved_times):
            unique["revised_then_approved"] += 1
        if unresolved_times and latest_publication_dt is not None and any(t < latest_publication_dt for t in unresolved_times):
            unique["revised_then_published"] += 1
        later_resolution = False
        if latest_review_dt is not None:
            later_resolution = any(t > latest_review_dt for t in approved_times) or (latest_publication_dt is not None and latest_publication_dt > latest_review_dt)
        if latest_review is not None and _event_is_unresolved(latest_review) and not later_resolution:
            unique["final_blocked"] += 1
    occurrence_reason = "alfred_warning_occurrences_unavailable_legacy_warning_sample_at_cap" if warning_occurrences_ambiguous else None
    return {"events": events, "unique": {"articles_reviewed": len({stable_article_identity(r) for _dt, r in reviews}), "articles_with_warnings": len({stable_article_identity(r) for _dt, r in warning_reviews}), "approved": unique["approved"], "final_blockers": unique["final_blocked"], "final_blocked": unique["final_blocked"], "revised_then_approved": unique["revised_then_approved"], "revised_then_published": unique["revised_then_published"]}, "canonical_unavailability_reasons": {"warning_occurrences": occurrence_reason}, "schema_warnings": [occurrence_reason] if occurrence_reason else []}


def aggregate_simone(runs: list[dict[str, Any]], since: datetime, until: datetime) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    legacy_errors = 0
    for run in iter_master_runs_in_window(runs, since, until):
        simone = run.get("simone") if isinstance(run.get("simone"), dict) else {}
        for item in _items(simone, "published_reports"):
            if _child_in_window(item, run, since, until):
                statuses[str(item.get("status") or "unknown").lower()] += 1
        handoff = simone.get("publish_handoff") if isinstance(simone.get("publish_handoff"), dict) else {}
        try:
            legacy_errors += int(handoff.get("errors") or 0)
        except (TypeError, ValueError):
            pass
        try:
            statuses["already_present_events"] += int(handoff.get("already_published") or 0)
        except (TypeError, ValueError):
            pass
    return {"reports_published": statuses["published"], "already_present_events": statuses["already_present_events"],
            "reports_already_present": statuses["already_present_events"],  # deprecated compatibility alias
            "lifecycle_status_events": dict(statuses), "terminal_errors": None,
            "terminal_errors_available": False,
            "terminal_errors_unavailability_reason": "simone_error_taxonomy_not_implemented",
            "legacy_errors_diagnostic": legacy_errors}

def repository_diagnostics(root: Path = ROOT) -> dict[str, Any]:
    expected: list[str] = []
    actual: list[str] = []
    try:
        out = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, text=True)
        for line in out.splitlines():
            path = line[3:] if len(line) > 3 else line
            if any(path == p.rstrip("/") or path.startswith(p) for p in EXPECTED_RUNTIME_PATHS):
                expected.append(path)
            else:
                actual.append(line)
    except Exception as exc:
        actual.append(f"git_status_unavailable:{exc}")
    return {"expected_runtime_untracked_paths": expected, "actual_source_modifications": actual, "scheduler": {"systemd_timer": "separate_authority_if_configured", "cron_absence_is_anomaly": False}}


P1_3_BOUNDARY_COMMIT = "ca0fdf1ca9a3d27e94f13570c754047c7203251f"
P1_3_EVENT_TYPES = {"logical_ai_request_created", "model_attempt_started", "model_attempt_completed",
                    "model_attempt_failed", "model_attempt_avoided", "fallback_started", "repair_started",
                    "warning_recorded", "blocker_recorded"}


def _coverage_from_cutover(rows: list[dict[str, Any]], readable: bool, since: datetime, until: datetime,
                           *, family: str = "p1_1") -> tuple[str, str | None]:
    evidence = rows
    if family == "p1_3_core":
        evidence = [row for row in rows if row.get("event_type") in P1_3_EVENT_TYPES or
                    row.get("code_commit") == P1_3_BOUNDARY_COMMIT]
    elif family == "full_active_ai":
        evidence = [row for row in rows if row.get("event_type") == "logical_ai_request_created" and
                    row.get("model_role") == "report_translation"]
    dated = [parse_utc_datetime(row.get("timestamp_utc")) for row in evidence]
    dated = [value for value in dated if value]
    if not readable or not dated:
        reason = "full_active_ai_cutover_not_observable" if family == "full_active_ai" else (
            "p1_3_cutover_not_observable" if family == "p1_3_core" else "canonical_event_ledger_has_no_dated_coverage")
        return "unavailable", reason
    cutover = min(dated)
    if cutover > until:
        return "unavailable", f"{family}_cutover_after_window"
    if cutover > since:
        return "partial", "canonical_event_ledger_cutover_inside_window"
    return "full", None


def _canonical_event_sections(rows: list[dict[str, Any]], since: datetime, until: datetime,
                              coverage: dict[str, str]) -> dict[str, Any]:
    bounded = [row for row in rows if in_window_dt(parse_utc_datetime(row.get("timestamp_utc")), since, until)]
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in bounded:
        by_type[str(row.get("event_type") or "")].append(row)

    def metric(*types: str, agent: str | None = None, result: str | None = None) -> dict[str, Any]:
        selected = [row for kind in types for row in by_type.get(kind, [])
                    if (not agent or row.get("agent") == agent) and (result is None or row.get("result") == result)]
        identities = {row["content_id"] for row in selected if row.get("content_id")}
        return {"event_count": len(selected), "unique_content_count": len(identities),
                "content_ids": sorted(identities)}

    def value(item: dict[str, Any], key: str = "unique_content_count", family: str = "p1_1") -> int | None:
        return item[key] if coverage[family] == "full" else None

    publications = metric("publication_completed", agent="Publisher")
    report_publications = metric("report_published", agent="Simone")
    warning_occurrences = metric("warning_recorded", agent="Alfred")
    warning_articles = warning_occurrences["unique_content_count"]
    warning_review_events = len({(row.get("run_id"), row.get("content_id"))
                                 for row in by_type.get("warning_recorded", [])
                                 if row.get("agent") == "Alfred" and row.get("content_id")})
    reviews = metric("quality_review_completed", agent="Alfred")
    blocker_occurrences = metric("blocker_recorded", agent="Alfred")
    pub_attempts = metric("publication_attempted", agent="Publisher")
    pub_failures = [r for r in bounded if r.get("agent") == "Publisher" and r.get("error_terminal") is True]
    simone_failures = [r for r in bounded if r.get("agent") == "Simone" and r.get("error_terminal") is True]
    reason_codes: dict[str, dict[str, int]] = {}
    for kind, items in by_type.items():
        counts = Counter(str(x.get("reason_code")) for x in items if x.get("reason_code"))
        if counts:
            reason_codes[kind] = dict(sorted(counts.items()))

    funnel_metrics = {
        "massy_unique_universe_seen": metric("candidate_seen", agent="Massy"),
        "massy_unique_skipped": metric("candidate_skipped", agent="Massy"),
        "menzo_unique_selected": metric("candidate_selected", agent="Menzo"),
        "menzo_unique_pending": metric("candidate_pending", agent="Menzo"),
        "menzo_unique_skipped": metric("candidate_skipped", agent="Menzo"),
        "menzo_unique_duplicate_arbitration_inputs": metric("duplicate_check_requested", agent="Menzo"),
        "unique_downstream_handoffs": metric("article_generation_requested", agent="Bob"),
        "andrea_unique_checked": metric("content_sufficiency_checked", agent="Andrea"),
        "andrea_unique_blocked": metric("content_sufficiency_checked", agent="Andrea", result="blocked"),
        "bob_unique_packages_generated": metric("article_generated", agent="Bob"),
        "alfred_unique_reviewed": reviews,
        "alfred_unique_approved": metric("quality_review_completed", agent="Alfred", result="approved"),
        "alfred_unique_needs_revision": metric("quality_review_completed", agent="Alfred", result="needs_revision"),
        "publisher_unique_publications": publications,
        "simone_report_candidates": metric("report_candidate_seen", agent="Simone"),
        "simone_report_selected": metric("report_selected", agent="Simone"),
        "simone_report_publications": report_publications,
    }
    menzo_decision_ids = set().union(*(set(funnel_metrics[key]["content_ids"]) for key in
        ("menzo_unique_selected", "menzo_unique_pending")))
    unavailable = {
        "unique_news_candidates_toward_menzo": "a2_candidate_seen_does_not_encode_massy_universe_component",
        "unique_already_worked": "a2_candidate_seen_does_not_encode_massy_universe_component",
        "unique_hard_skipped": "frozen_a2_does_not_distinguish_hard_skipped_from_already_worked",
        "unique_report_candidates_from_massy": "a2_candidate_seen_does_not_encode_massy_universe_component",
        "same_run_duplicates_blocked": "a2_pair_resolution_does_not_encode_duplicate_horizon",
        "recent_history_duplicates_blocked": "a2_pair_resolution_does_not_encode_duplicate_horizon",
        "material_updates": "a2_has_no_material_update_event",
        "bob_unique_errors": "a2_has_no_item_level_bob_generation_failure_event",
    }
    lifecycle: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in bounded:
        if row.get("content_id"):
            lifecycle[row["content_id"]][row["event_type"]].append({
                "timestamp_utc": row.get("timestamp_utc"), "run_id": row.get("run_id"),
                "result": row.get("result"), "reason_code": row.get("reason_code")})
    final_blocked_ids: set[str] = set()
    for cid, events in lifecycle.items():
        last_blocker = max((str(x.get("timestamp_utc") or "") for x in events.get("blocker_recorded", [])), default="")
        resolved = any(str(x.get("timestamp_utc") or "") > last_blocker and x.get("result") == "approved"
                       for x in events.get("quality_review_completed", []))
        resolved = resolved or any(str(x.get("timestamp_utc") or "") > last_blocker
                                   for x in events.get("publication_completed", []))
        if last_blocker and not resolved:
            final_blocked_ids.add(cid)
    funnel_metrics["alfred_final_unique_blockers"] = {
        "event_count": blocker_occurrences["event_count"], "unique_content_count": len(final_blocked_ids),
        "content_ids": sorted(final_blocked_ids)}
    from scripts.validate_canonical_operational_semantics import analyze
    owned_ids = {row.get("logical_request_id") for row in bounded
                 if row.get("event_type") == "logical_ai_request_created" and row.get("logical_request_id")}
    owned_lifecycle = [row for row in rows if row.get("logical_request_id") in owned_ids]
    starts = [row for row in owned_lifecycle if row.get("event_type") == "model_attempt_started"]
    terminals = {row.get("attempt_id") for row in owned_lifecycle
                 if row.get("event_type") in {"model_attempt_completed", "model_attempt_failed"}}
    lifecycle_complete = all(row.get("attempt_id") in terminals for row in starts)
    operational = analyze(owned_lifecycle)
    terminal_request_ids = {row.get("logical_request_id") for row in owned_lifecycle
                            if row.get("error_terminal") is True and row.get("event_type") in
                            {"model_attempt_failed", "stage_failed"}}
    ai = {key: operational.get(source) for key, source in {
        "logical_requests": "logical_requests", "real_attempts": "model_attempts_started",
        "successful_attempts": "model_attempts_completed", "failed_attempts": "model_attempts_failed",
        "fallbacks_started": "fallbacks_started", "recovered_failures": "logical_requests_recovered",
        "terminal_failures": "logical_requests_terminal_failed"}.items()}
    ai["terminal_failures"] = len({request_id for request_id in terminal_request_ids if request_id})
    if coverage["ai"] != "full" or not lifecycle_complete:
        ai = {key: None for key in ai}
        lifecycle_complete_value = None
    else:
        lifecycle_complete_value = True
    ai["lifecycle_complete"] = lifecycle_complete_value
    result = {
        "bounded_event_count": len(bounded), "runs": {"event_count": len(by_type.get("run_completed", [])),
            "unique_run_count": len({r.get("run_id") for r in by_type.get("run_completed", []) if r.get("run_id")}),
            "value": value(metric("run_completed"), "event_count")},
        "publication": {"news": publications, "reports": report_publications,
            "unique_news_publications": value(publications), "unique_report_publications": value(report_publications)},
        "funnel": {"metrics": funnel_metrics,
            "unique_actionable_candidates": len(menzo_decision_ids) if coverage["p1_1"] == "full" else None,
            "unique_downstream_handoffs": value(funnel_metrics["unique_downstream_handoffs"]),
            "unique_final_publications": value(publications),
            "handoff_to_publication_ratio": ((value(publications) / value(funnel_metrics["unique_downstream_handoffs"]))
                if coverage["p1_1"] == "full" and value(funnel_metrics["unique_downstream_handoffs"]) else None),
            "unavailable_metrics": unavailable,
            "reason_code_distributions": reason_codes, "content_lifecycle": lifecycle},
        "alfred": {"articles_reviewed": value(reviews),
            "articles_with_warnings": warning_articles if coverage["warnings"] == "full" else None,
            "warning_events": warning_review_events if coverage["warnings"] == "full" else None,
            "warning_occurrences": value(warning_occurrences, "event_count", "warnings"),
            "blocker_occurrences": value(blocker_occurrences, "event_count", "warnings"),
            "final_blockers": len(final_blocked_ids) if coverage["failures"] == "full" else None},
        "publisher": {"attempts": value(pub_attempts, "event_count"),
            "publications": value(publications), "terminal_failures": len(pub_failures) if coverage["failures"] == "full" else None},
        "simone": {"report_outcomes": value(report_publications),
            "terminal_failures": len(simone_failures) if coverage["failures"] == "full" else None,
            "legacy_errors_are_terminal": False},
        "ai_operations": ai,
    }
    if coverage["p1_1"] != "full":
        unavailable_metric = {"event_count": None, "unique_content_count": None, "content_ids": None}
        result["bounded_event_count"] = None
        result["runs"] = {"event_count": None, "unique_run_count": None, "value": None}
        result["publication"]["news"] = dict(unavailable_metric)
        result["publication"]["reports"] = dict(unavailable_metric)
        result["publication"]["unique_news_publications"] = None
        result["publication"]["unique_report_publications"] = None
        result["funnel"]["metrics"] = {key: dict(unavailable_metric) for key in result["funnel"]["metrics"]}
        for key in ("unique_actionable_candidates", "unique_downstream_handoffs",
                    "unique_final_publications", "handoff_to_publication_ratio"):
            result["funnel"][key] = None
        result["funnel"]["reason_code_distributions"] = None
        result["funnel"]["content_lifecycle"] = None
    return result


def _without_authoritative_numbers(value: Any) -> Any:
    """Preserve diagnostic structure while suppressing totals from corrupt canonical input."""
    if isinstance(value, dict):
        return {key: _without_authoritative_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_authoritative_numbers(item) for item in value]
    return None if isinstance(value, (int, float)) and not isinstance(value, bool) else value


def _artifact_snapshot(root: Path, since: datetime, until: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    from agents.canonical_artifact_reader import read_artifact_index, verify_artifact_row
    roles = ("source_material", "translated_candidate", "quality_review", "final_published_material")
    index = read_artifact_index(root)
    if not index.get("available"):
        return {"role_coverage": {role: {"artifact_count": None, "unique_content_count": None}
                                  for role in roles}, "unavailability_reason": index.get("reason")}, section_metadata(
            available=False, source=index.get("source", "canonical_artifact_index"), coverage="unavailable",
            warnings=index.get("diagnostic_mismatches"), reason=index.get("reason"))
    rows = [row for values in index["rows_by_content_id"].values() for row in values]
    dated = [parse_utc_datetime(row.get("manifested_at_utc")) for row in rows]
    dated = [dt for dt in dated if dt]
    coverage = "full" if dated and min(dated) <= since else ("partial" if dated else "unavailable")
    bounded = [row for row in rows if in_window_dt(parse_utc_datetime(row.get("manifested_at_utc")), since, until)]
    role_coverage = {}
    integrity_mismatches = list(index.get("diagnostic_mismatches") or [])
    for role in roles:
        selected = [row for row in bounded if role in row.get("semantic_roles", [])]
        verified = []
        for row in selected:
            valid, failure = verify_artifact_row(root, row)
            if valid:
                verified.append(row)
            else:
                integrity_mismatches.append(f"{row.get('artifact_id')}:{role}:{failure}")
        role_coverage[role] = {"artifact_count": len(verified) if coverage == "full" else None,
            "unique_content_count": len({row["content_id"] for row in verified}) if coverage == "full" else None}
    reason = None if coverage == "full" else "canonical_artifact_index_cutover_inside_window"
    return {"role_coverage": role_coverage, "report_material": {"available": False,
        "reason": "p1_2_report_material_retention_out_of_scope"}}, section_metadata(
            available=coverage != "unavailable", source=index["source"], coverage=coverage,
            warnings=integrity_mismatches, reason=reason)


def build_snapshot(since: datetime, until: datetime, root: Path = ROOT, *, allow_tail_fallback: bool = True) -> dict[str, Any]:
    from agents.gemini_diagnostics import build_gemini_diagnostics, load_ledger
    runs, sources, warnings, authority_available, source_health = load_master_runs(
        root, allow_tail_fallback=allow_tail_fallback
    )
    in_window_runs = list(iter_master_runs_in_window(runs, since, until))
    pub = build_authoritative_publication_set(runs, since, until)
    funnel = build_editorial_funnel(runs, pub, since, until)
    dup, legacy, dup_warnings = aggregate_duplicate_arbitration(runs, since, until)
    andrea = aggregate_andrea(runs, since, until)
    alfred = aggregate_alfred(runs, pub, since, until)
    simone = aggregate_simone(runs, since, until)
    simone["reports_published"] = pub["reports_unique"]
    ledger_path = root / "state/newsroom/gemini_call_ledger.jsonl"
    gemini_records, gemini_warnings, gemini_health = load_ledger(
        ledger_path, since=since, until=until, strict_bounded=True, return_metadata=True
    )
    gemini = build_gemini_diagnostics(gemini_records, cache_path=root / "state/newsroom/menzo_duplicate_arbitration_cache.json", menzo_decisions_paths=())
    gemini_available = bool(gemini_health["readable"] and
                            (gemini_health["valid_rows"] > 0 or
                             gemini_health["malformed_rows"] == 0 and gemini_health["undated_rows"] == 0))
    if not gemini_available:
        for key in ("real_attempts", "completed_calls", "completed_successful_calls", "failures", "avoided_calls", "fallbacks",
                    "gemini_3_5_attempts", "gemini_3_5_completed_calls", "gemini_3_5_completed_successful_calls", "gemini_3_5_failures", "gemini_3_5_avoided_calls"):
            gemini[key] = None
    gemini["undated_rows_diagnostic"] = gemini_health["undated_rows"]
    if not authority_available:
        funnel["canonical"] = {key: None for key in funnel["canonical"]}
        for key in ("articles_reviewed", "articles_with_warnings", "final_blockers", "revised_then_approved", "revised_then_published"):
            alfred["unique"][key] = None
        for key in ("warning_events", "warning_occurrences"):
            alfred["events"][key] = None
        for key in ("reports_published", "already_present_events", "reports_already_present", "legacy_errors_diagnostic"):
            simone[key] = None
    warnings += gemini_warnings
    warnings += funnel.get("schema_warnings", []) + andrea.get("schema_warnings", []) + alfred.get("schema_warnings", []) + dup_warnings
    event_path = root / "state/newsroom/canonical_event_ledger.jsonl"
    canonical_rows, canonical_warnings, canonical_readable, canonical_malformed = load_jsonl_defensively(event_path)
    p1_4_event_metadata_present = event_path.exists() and bool(canonical_rows or canonical_malformed)
    from agents.canonical_event_ledger import validate_event
    canonical_validation_errors = [(index, validate_event(row)) for index, row in enumerate(canonical_rows, 1)]
    canonical_validation_errors = [(index, errors) for index, errors in canonical_validation_errors if errors]
    p1_1_coverage, p1_1_reason = _coverage_from_cutover(canonical_rows, canonical_readable, since, until)
    p1_3_coverage, p1_3_reason = _coverage_from_cutover(canonical_rows, canonical_readable, since, until,
                                                       family="p1_3_core")
    active_ai_coverage, active_ai_reason = _coverage_from_cutover(canonical_rows, canonical_readable, since, until,
                                                                 family="full_active_ai")
    coverages = {"p1_1": p1_1_coverage, "ai": active_ai_coverage,
                 "warnings": p1_3_coverage, "failures": p1_3_coverage}
    integrity_reason = None
    if canonical_malformed or canonical_validation_errors:
        integrity_reason = ("canonical_event_ledger_malformed_json" if canonical_malformed
                            else "canonical_event_ledger_schema_invalid")
        coverages = {family: "unavailable" for family in coverages}
        p1_1_coverage = p1_3_coverage = active_ai_coverage = "unavailable"
        p1_1_reason = p1_3_reason = active_ai_reason = integrity_reason
    canonical = _canonical_event_sections(canonical_rows, since, until, coverages)
    if integrity_reason:
        canonical = _without_authoritative_numbers(canonical)
        if canonical_malformed:
            canonical_warnings.append(f"canonical_event_ledger_malformed_json:{canonical_malformed}")
        for index, errors in canonical_validation_errors:
            canonical_warnings.append(f"canonical_event_ledger_schema_invalid:{index}:{'|'.join(errors)}")
    artifacts, artifact_metadata = _artifact_snapshot(root, since, until)
    def family_metadata(family: str, reason: str | None) -> dict[str, Any]:
        state = coverages[family]
        return section_metadata(available=state != "unavailable", source="state/newsroom/canonical_event_ledger.jsonl",
                                coverage=state, warnings=canonical_warnings, reason=reason)
    p1_1_metadata = family_metadata("p1_1", p1_1_reason)
    ai_metadata = family_metadata("ai", active_ai_reason)
    p1_3_core_metadata = section_metadata(available=p1_3_coverage != "unavailable",
        source="state/newsroom/canonical_event_ledger.jsonl", coverage=p1_3_coverage,
        warnings=canonical_warnings, reason=p1_3_reason)
    warning_metadata = family_metadata("warnings", p1_3_reason)
    failure_metadata = family_metadata("failures", p1_3_reason)
    for section_name in ("runs", "publication", "funnel"):
        canonical[section_name]["metadata"] = dict(p1_1_metadata)
    canonical["alfred"]["metadata"] = {"review_lifecycle": p1_1_metadata,
                                       "warning_occurrences": warning_metadata,
                                       "final_failures": failure_metadata}
    canonical["publisher"]["metadata"] = {"lifecycle": p1_1_metadata, "terminal_failures": failure_metadata}
    canonical["simone"]["metadata"] = {"lifecycle": p1_1_metadata, "terminal_failures": failure_metadata}
    canonical["ai_operations"]["metadata"] = ai_metadata
    artifacts["metadata"] = dict(artifact_metadata)
    return {
        "schema_version": SCHEMA_VERSION,
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": since.isoformat(),
        "window_end": until.isoformat(),
        "artifact_sources": sorted(set(sources)),
        "authority_available": authority_available,
        "schema_warnings": list(dict.fromkeys(warnings)),
        "publication": pub,
        "funnel": funnel,
        "duplicate_arbitration": dup,
        "andrea": andrea,
        "alfred": alfred,
        "gemini": gemini,
        "simone": simone,
        "authoritative": {**canonical, "artifacts": artifacts},
        "section_metadata": {
            "menzo": section_metadata(available=authority_available, source="master_log", coverage={"runs": len(in_window_runs)}, warnings=funnel.get("schema_warnings"), reason="master_log_authority_unavailable"),
            "andrea": section_metadata(available=authority_available and andrea.get("available") is True, source="master_log.andrea.handoff", coverage={"covered_runs": andrea.get("covered_runs", 0), "total_runs": andrea.get("total_runs", 0)}, warnings=andrea.get("schema_warnings"), reason="andrea_event_stream_unavailable"),
            "alfred": section_metadata(available=authority_available, source="master_log", coverage={"runs": len(in_window_runs)}, warnings=alfred.get("schema_warnings"), reason="master_log_authority_unavailable"),
            "gemini": section_metadata(available=gemini_available, source="state/newsroom/gemini_call_ledger.jsonl", coverage={**gemini_health, "bounded_records": len(gemini_records)}, warnings=gemini_warnings, reason="gemini_ledger_unavailable_for_bounded_metrics"),
            "simone": section_metadata(available=authority_available, source="master_log.simone", coverage={"runs": len(in_window_runs)}, reason="master_log_authority_unavailable"),
            **({"canonical_events": p1_1_metadata,
                "p1_1_lifecycle": p1_1_metadata,
                "p1_3_ai_operations": ai_metadata,
                "p1_3_core_ai_operations": p1_3_core_metadata,
                "p1_3_warning_occurrences": warning_metadata,
                "p1_3_failure_semantics": failure_metadata}
               if p1_4_event_metadata_present else {}),
            "artifacts": artifact_metadata,
        },
        "gemini_summary_if_available": {"duplicate_arbitration_calls": (dup.get("counters") or {}).get("gemini_calls_used_for_duplicate_arbitration") if dup.get("available") else None},
        "diagnostics": {"legacy_duplicate_signals": legacy, "master_runs_in_window": len(in_window_runs), **source_health, **repository_diagnostics(root)},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--output-dir", default="reports")
    ap.add_argument("--latest", action="store_true")
    args = ap.parse_args()
    until = parse_utc_datetime(args.until) or datetime.now(timezone.utc)
    since = until - timedelta(hours=args.hours)
    snap = build_snapshot(since, until, ROOT)
    outdir = ROOT / args.output_dir
    outdir.mkdir(parents=True, exist_ok=True)
    ts = until.strftime("%Y%m%d_%H%M%S")
    path = outdir / f"owtv_observability_snapshot_{args.hours}h_{ts}.json"
    text = json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    if args.latest:
        (outdir / "owtv_observability_snapshot_latest.json").write_text(text, encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
