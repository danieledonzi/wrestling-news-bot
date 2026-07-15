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
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "v95.12a_observability_snapshot.v2"
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
EXPECTED_RUNTIME_UNTRACKED_PATHS = ("reports/",)


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


def load_master_runs(root: Path = ROOT) -> tuple[list[dict[str, Any]], list[str], list[str], bool, dict[str, Any]]:
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
        elif tail.exists():
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
    elif tail.exists():
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
        "menzo_unique_actionable_candidates": len({stable_article_identity(x) for x in buckets["menzo_selected_downstream"] + buckets["menzo_pending"]}),
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
    selected_ids = {stable_article_identity(x) for x in buckets["menzo_selected_downstream"]}
    published_ids = {stable_article_identity(x) for x in publication.get("records", []) if x.get("content_kind") == "news"}
    if selected_ids and published_ids:
        overlap = len(selected_ids & published_ids)
        selected_publication_ratio = overlap / len(selected_ids)
    else:
        overlap = None
        selected_publication_ratio = None
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
        "schema_warnings": schema_warnings,
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
    events = {
        "warning_count": sum(len(_warning_entries(r)) for _dt, r in reviews),
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
    return {"events": events, "unique": {"approved": unique["approved"], "final_blocked": unique["final_blocked"], "revised_then_approved": unique["revised_then_approved"], "revised_then_published": unique["revised_then_published"]}, "schema_warnings": []}

def repository_diagnostics(root: Path = ROOT) -> dict[str, Any]:
    expected: list[str] = []
    actual: list[str] = []
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
        for line in out.splitlines():
            path = line[3:] if len(line) > 3 else line
            if line.startswith("??") and any(path == p.rstrip("/") or path.startswith(p) for p in EXPECTED_RUNTIME_UNTRACKED_PATHS):
                expected.append(path)
            else:
                actual.append(line)
    except Exception as exc:
        actual.append(f"git_status_unavailable:{exc}")
    return {"expected_runtime_untracked_paths": expected, "actual_source_modifications": actual, "scheduler": {"systemd_timer": "separate_authority_if_configured", "cron_absence_is_anomaly": False}}


def build_snapshot(since: datetime, until: datetime, root: Path = ROOT) -> dict[str, Any]:
    runs, sources, warnings, authority_available, source_health = load_master_runs(root)
    in_window_runs = list(iter_master_runs_in_window(runs, since, until))
    pub = build_authoritative_publication_set(runs, since, until)
    funnel = build_editorial_funnel(runs, pub, since, until)
    dup, legacy, dup_warnings = aggregate_duplicate_arbitration(runs, since, until)
    alfred = aggregate_alfred(runs, pub, since, until)
    warnings += funnel.get("schema_warnings", []) + alfred.get("schema_warnings", []) + dup_warnings
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": since.isoformat(),
        "window_end": until.isoformat(),
        "artifact_sources": sorted(set(sources)),
        "authority_available": authority_available,
        "schema_warnings": list(dict.fromkeys(warnings)),
        "publication": pub,
        "funnel": funnel,
        "duplicate_arbitration": dup,
        "alfred": alfred,
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
