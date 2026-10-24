"""Read-only editorial observation: frozen classes, URL lifecycles and owner review.

Only report artifacts and the daily observation journal are written. No newsroom
producer, provider, queue mutator or publication operation is invoked here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "owtv_editorial_observation_v2"
CLASSES = ("MUST_PUBLISH", "SHOULD_PUBLISH", "PUBLISHABLE_SOFT", "SKIP")
ROME = ZoneInfo("Europe/Rome")
BLOCKS = {"WAIT_DUPLICATE_CLEARANCE", "TECHNICAL_BLOCK", "REVIEW_UNAVAILABLE", "WAIT_PRIMARY_DECISION"}
NO_ACTION = "Nessuna azione proposta"


def stamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (ValueError, TypeError):
        return None


def url_key(row: dict) -> str:
    from agents.menzo_policy_v93_15 import source_key
    return source_key(str(row.get("url") or row.get("source_url") or ""))


def primary_class(row: dict) -> str | None:
    director = row.get("editorial_director")
    return (director.get("editorial_class") if isinstance(director, dict) else None) or row.get("editorial_class")


def run_time(row: dict) -> datetime | None:
    from scripts.observability_snapshot import master_run_timestamp
    return master_run_timestamp(row)


def state_rows(data: dict | None, field: str, errors: list[str], name: str) -> Any:
    """An absent or malformed collection is unavailable, not an empty pool."""
    value = (data or {}).get(field)
    valid = isinstance(value, dict if field == "entries" else list)
    rows = value.values() if valid and field == "entries" else value if valid else []
    if not valid or any(not isinstance(r, dict) or not url_key(r) for r in rows):
        errors.append(f"{name}:invalid_{field}")
        return None
    if field == "entries" and any(r.get("editorial_class") not in CLASSES or not stamp(r.get("classified_at")) for r in rows):
        errors.append(f"{name}:invalid_primary_decision")
        return None
    return value


def read_json(path: Path, expected: type, errors: list[str]) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, expected):
            raise ValueError("invalid_root_type")
        return value
    except (OSError, ValueError) as exc:
        errors.append(f"{path.name}:{type(exc).__name__}")
        return None


def release_metadata(root: Path) -> dict:
    """The merge commit is the locally installed PR, not a guessed release date."""
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        rows = subprocess.check_output(
            ["git", "log", "--first-parent", "-100", "--format=%H\t%cI\t%s"], cwd=root, text=True)
        for line in rows.splitlines():
            sha, date, subject = line.split("\t", 2)
            match = re.search(r"(?:Merge pull request #|\(#)(\d+)", subject)
            if match:
                number = int(match.group(1))
                return {"head": head, "last_pr": number, "merged_at": date, "merge_commit": sha,
                        "url": f"https://github.com/danieledonzi/wrestling-news-bot/pull/{number}",
                        "source": "git.first_parent_merge_history"}
        return {"head": head, "last_pr": None, "merged_at": None, "source": "git_no_pr_merge_found"}
    except (OSError, subprocess.SubprocessError):
        return {"head": None, "last_pr": None, "merged_at": None, "source": "unavailable"}


def compact(row: dict) -> dict:
    return {"url": row.get("url") or row.get("source_url"), "title": row.get("title") or row.get("title_it"),
            "class": primary_class(row), "reason": row.get("reason"), "duplicate_of": row.get("duplicate_of"),
            "wp_link": row.get("wp_link")}


def economic_sections(root: Path, since: datetime, until: datetime) -> dict:
    from agents.gemini_diagnostics import load_ledger, build_gemini_economic_truth
    rows, warnings, health = load_ledger(root / "state/newsroom/gemini_call_ledger.jsonl",
        since=since, until=until, strict_bounded=True, return_metadata=True)
    valid = health["readable"] and not health["malformed_rows"] and not health["undated_rows"]
    overall = build_gemini_economic_truth(rows, available=valid)
    valid = overall["available"]
    workloads = {}
    names = {
        "primary_classification": {"editorial_director_active"},
        "isolated_fact_cards": {"editorial_fact_extraction", "editorial_fact_enrichment"},
        "pair_admission": {"editorial_duplicate_admission", "editorial_soft_duplicate_admission"},
        "duplicate_verdict": {"editorial_director_duplicate_gate", "editorial_director_duplicate_confirmation"},
        "soft_competition": {"editorial_soft_board"},
    }
    for name, accepted in names.items():
        selected = [r for r in rows if r.get("workload") in accepted]
        workloads[name] = build_gemini_economic_truth(selected, available=valid)
    news_workloads = set().union(*names.values()) | {'translation_generation', 'quote_resolution',
                     'duplicate_arbitration', 'selection'}
    def partition(row):
        if row.get("test_run") is True or row.get("workload") == "editorial_quality_reform_test":
            return "isolated_tests"
        # Installed report producers also use pipeline/phase evidence, without
        # a workload field. Unknown work never silently becomes news cost.
        if (row.get('workload') == 'report_translation' or row.get('model_role') == 'report_translation' or
                row.get('pipeline') == 'report' or str(row.get('reason') or '').startswith('report_translation') or
                str(row.get('phase') or '').startswith('report_blocks')):
            return 'reports'
        if (row.get('workload') in news_workloads or row.get('model_role') in news_workloads or
                row.get('phase') in {'translate_article', 'quote_resolver', 'ai_editorial_review',
                    'same_run_duplicate_arbitration', 'recent_history_duplicate_arbitration'} or
                str(row.get('purpose') or '').startswith('news_translate')):
            return 'news_and_editorial'
        return 'unattributed'
    partitions = {name: build_gemini_economic_truth([r for r in rows if partition(r) == name], available=valid)
                  for name in ('news_and_editorial', 'reports', 'isolated_tests', 'unattributed')}
    real = [r for r in rows if str(r.get('status') or '').strip().casefold() in {'called', 'failed'}]
    token_fields = ('input_tokens', 'output_tokens', 'total_tokens', 'non_cached_input_tokens',
                    'effective_cached_input_tokens', 'effective_thinking_tokens')
    def token_summary(selected):
        totals = {}
        for field in token_fields:
            values = [r.get(field) if r.get('usage_resolution_status') == 'resolved' else None for r in selected]
            known = [v for v in values if isinstance(v, int) and not isinstance(v, bool) and v >= 0]
            totals[field] = {'known_sum': sum(known) if known or (valid and not selected) else None,
                'resolved_attempts': len(known), 'attempts': len(selected),
                'window_total': sum(known) if valid and len(known) == len(selected) else None}
        return totals
    usage = {'overall': token_summary(real), 'by_workload': {
        phase: token_summary([r for r in real if (r.get('workload') or 'UNKNOWN') == phase])
        for phase in sorted({r.get('workload') or 'UNKNOWN' for r in real})}}
    cost_records = [{**{k: r.get(k) for k in ('timestamp', 'provider_attempt_id', 'logical_request_id', 'workload',
        'status', 'actual_model', 'model_requested', 'input_tokens', 'output_tokens', 'total_tokens',
        'effective_cached_input_tokens', 'effective_thinking_tokens', 'computed_list_price_cost',
        'pricing_currency', 'price_table_version', 'usage_resolution_status', 'cost_resolution_status',
        'retry', 'repair', 'fallback', 'error_class', 'validation_families', 'phase', 'pipeline', 'reason')},
        'attributed_partition': partition(r)} for r in real]
    logical_ids = {r['logical_request_id'] for r in rows if r.get('logical_request_id')}
    uncorrelated = sum(not r.get('logical_request_id') for r in real)
    return {"overall": overall, "workloads": workloads, "warnings": warnings,
            'partitions': partitions,
            'attribution_complete': bool(valid and not any(partition(r) == 'unattributed' for r in real)),
            'request_identity': {'observed_logical_requests': len(logical_ids),
                'uncorrelated_provider_attempts': uncorrelated,
                'complete_logical_requests': len(logical_ids) if valid and not uncorrelated else None},
            'usage': usage, 'provider_attempt_records': cost_records,
            'validation_failed_attempts': sum(bool(r.get('validation_families')) for r in real) if valid else None,
            "repairs": sum(r.get("repair") is True for r in rows if r.get("status") in {"called", "failed"}) if valid else None,
            "failed_attempts": sum(r.get("status") == "failed" for r in rows) if valid else None}


def analyze_runs(runs: list[dict], frozen: dict, closed: dict, since: datetime, until: datetime,
                 *, complete: bool) -> dict:
    """Counts are URL sets or explicitly labelled run observations, never their sum."""
    bounded = sorted((r for r in runs if run_time(r) and since <= run_time(r) <= until), key=run_time)
    before = [r for r in runs if run_time(r) and run_time(r) < since]
    articles: dict[str, dict] = {}
    observations = Counter()
    mismatches = []
    resurrected = []
    skipped_endpoints = []
    versions = Counter()
    soft_runs = []
    soft_admitted = set()
    soft_selected = set()
    soft_published = set()
    soft_skipped = set()
    soft_statuses = Counter()
    relations = {}
    concentration = Counter()
    sample_incomplete = False
    primary_observations = 0
    skip_chronology_unavailable = 0
    for r in bounded:
        # Windowing and ordering share the master contract. Skip chronology
        # additionally needs the phase start: a tombstone written inside this
        # run must not look like a reintroduction when only its end is known.
        phase_start = stamp((r.get("run") or {}).get("started_at"))
        skip_chronology_unavailable += phase_start is None
        at = (phase_start or run_time(r)).isoformat()
        ep = r.get("editorial_pipeline") or {}
        pf = ep.get("prefilter") or {}
        sc = ep.get("scheduling") or {}
        version = pf.get("policy_version") or ep.get("policy_version") or "unknown"
        versions[version] += 1
        m = r.get("menzo") or {}
        sample_incomplete |= bool(m.get("pending_sample_truncated") or m.get("skipped_sample_truncated"))
        candidates = pf.get("candidates", [])
        by_id = {c.get("candidate_id"): c for c in candidates}
        for stage, rows in [("primary", candidates), ("selected", m.get("selected", [])),
                            ("pending", m.get("pending", [])), ("skipped", m.get("skipped_sample", [])),
                            ("published", (r.get("publisher") or {}).get("published", []))]:
            for row in rows:
                key = url_key(row)
                if not key:
                    continue
                first = frozen.get(key)
                cl = primary_class(row)
                article = articles.setdefault(key, {**compact(row), "first_class": (first or {}).get("editorial_class"),
                    'first_input_coverage': (first or {}).get('first_input_coverage'),
                    'first_body_sha256': (first or {}).get('first_body_sha256'),
                    "classified_at": (first or {}).get("classified_at"), "story_core": (first or {}).get("story_core"),
                    "events": [], "published": False})
                event = {"at": at, "stage": stage, "class": cl, "reason": row.get("reason"),
                         "duplicate_of": row.get("duplicate_of"), "policy_version": version}
                article["events"].append(event)
                if stage == "primary":
                    observations[key] += 1
                    primary_observations += 1
                if first and cl and cl != first.get("editorial_class"):
                    mismatches.append({"url": key, "at": at, "first_class": first["editorial_class"],
                                       "observed_class": cl, "stage": stage, "policy_version": version})
                tomb = closed.get(key)
                closed_at = stamp((tomb or {}).get("added_at"))
                if stage in {"primary", "selected", "pending"} and closed_at and phase_start and closed_at < phase_start:
                    resurrected.append({"url": key, "at": at, "stage": stage, "closed_at": closed_at.isoformat(),
                                        "policy_version": version})
                if stage == "published":
                    article.update(published=True, wp_link=row.get("wp_link"))
                    if (first or {}).get("editorial_class") == "PUBLISHABLE_SOFT":
                        soft_published.add(key)
                if (first or {}).get("editorial_class") == "PUBLISHABLE_SOFT":
                    if stage == "selected": soft_selected.add(key)
                    if stage == "skipped": soft_skipped.add(key)
        for rel in pf.get("relations", []):
            pair = rel.get("pair_id")
            if not pair:
                continue
            relations[pair] = rel
            for side in ("left", "right"):
                # Production stores both URLs, including history endpoints;
                # older fixtures can retain endpoint IDs instead.
                row = {"url": rel[f"{side}_url"]} if rel.get(f"{side}_url") else by_id.get(rel.get(f"{side}_id"), {})
                key = url_key(row)
                if key:
                    concentration[key] += 1
                    closed_at = stamp((closed.get(key) or {}).get("added_at"))
                    if closed_at and phase_start and closed_at < phase_start:
                        skipped_endpoints.append({"url": key, "at": at, "pair_id": pair, "policy_version": version})
        if "soft_board_status" in sc:
            status = sc["soft_board_status"]
            soft_statuses[status] += 1
            admitted = sc.get("soft_board_admitted_items") or []
            soft_admitted.update(url_key(a) for a in admitted if url_key(a))
            soft_runs.append({"at": at, "policy_version": version, "status": status,
                "pool_before_review": sc.get("soft_board_pool_size"),
                "admitted": [compact(a) for a in admitted],
                "meaningful_review": sc.get("soft_board_meaningful_review"),
                "selected": sc.get("soft_board_selected"), "skipped": sc.get("soft_board_skipped"),
                "expired_after_reviews": sc.get("soft_board_repeatedly_outranked"),
                "midnight_or_policy_tombstones": sc.get("soft_board_midnight_tombstones"),
                "duplicate_removed": sc.get("soft_board_duplicates_removed"),
                "capacity_context": sc.get("soft_board_review_day_context"),
                "review": (sc.get("soft_board_review") or {}).get("output"),
                "technical_details": sc.get("soft_board_duplicate_revalidation") or sc.get("soft_board_review") if status in BLOCKS else None})
    cohorts = {}
    for cl in CLASSES:
        members = {k: v for k, v in frozen.items() if v.get("editorial_class") == cl and
                   stamp(v.get("classified_at")) and since <= stamp(v["classified_at"]) <= until}
        states = Counter()
        for key, first in members.items():
            a = articles.setdefault(key, {**compact(first), "first_class": cl,
                'first_input_coverage': first.get('first_input_coverage'),
                'first_body_sha256': first.get('first_body_sha256'),
                "classified_at": first.get("classified_at"), "story_core": first.get("story_core"),
                "events": [], "published": False})
            closed_at = stamp((closed.get(key) or {}).get("added_at"))
            if a["published"]: state = "published"
            elif closed_at and closed_at <= until: state = "terminal_skip"
            elif a["events"] and a["events"][-1]["stage"] == "pending": state = "pending_last_observation"
            else: state = "outcome_not_observed"
            a["cohort_outcome"] = state
            a["terminal_skip"] = compact(closed[key]) if key in closed and closed_at and closed_at <= until else None
            states[state] += 1
        cohorts[cl] = {"new_unique_urls": len(members) if complete else None,
                       "outcomes": dict(states) if complete else None,
                       "observed_new_unique_urls": len(members)}
    def pool_rows(run):
        return [compact(a) for a in (run or {}).get("menzo", {}).get("pending", [])
                if primary_class(a) == "PUBLISHABLE_SOFT"]
    return {"available": complete, "runs_observed": len(bounded), "policy_versions": dict(versions),
        "sample_incomplete": sample_incomplete, "cohorts": cohorts, "articles": list(articles.values()),
        "immutability": {"primary_observations": primary_observations, "unique_urls_observed": len(observations),
            "urls_observed_multiple_runs": sum(n > 1 for n in observations.values()), "violations": mismatches,
            "verdict": "violations_observed" if mismatches else ("no_violation_observed" if complete else "unavailable")},
        "terminal_skip": {"resurrections": resurrected, "skipped_pair_endpoints": skipped_endpoints,
            "endpoint_coverage": "primary_path_url_endpoints; softpool pairs not retained in master projection",
            "run_chronology_unavailable": skip_chronology_unavailable,
            "undated_tombstones": sum(not stamp(r.get('added_at')) for r in closed.values())},
        "duplicates": {"unique_admitted_pairs_observed": len(relations),
            "admission_records": list(relations.values()),
            "decisions_observed": dict(Counter(x['decision'] for x in relations.values() if x.get('decision'))) if all(x.get('decision') for x in relations.values()) else None,
            "decision_coverage": "full_observed" if all(x.get('decision') for x in relations.values()) else "verdicts_not_retained_in_master_projection",
            "scope": "primary_path_only; softpool has separate removal telemetry",
            "terminal_duplicate_urls": [{**compact(v), 'closed_at': v.get('added_at')} for v in closed.values()
                if stamp(v.get('added_at')) and since <= stamp(v['added_at']) <= until and
                (v.get('decision_authority') in {'semantic_duplicate_gate', 'soft_board_duplicate_revalidation', 'deterministic_exact_duplicate'} or 'duplicate' in str(v.get('reason', '')))],
            "concentration_observations": [{"url": u, "endpoint_observations": n} for u, n in concentration.most_common(5)]},
        "softpool": {"opening_last_observed": pool_rows(max(before, key=run_time) if before else None),
            "opening_available": bool(before), "closing_last_observed": pool_rows(bounded[-1] if bounded else None),
            "closing_available": bool(bounded) and not bool((bounded[-1].get("menzo") or {}).get("pending_sample_truncated")),
            "admitted_unique": len(soft_admitted), "selected_unique": len(soft_selected),
            "published_unique_observed": len(soft_published), "skipped_unique_observed_sample": len(soft_skipped),
            "status_run_observations": dict(soft_statuses), "runs": soft_runs}}


def observed_patterns(analysis: dict, weekly: dict, current_version: str | None) -> list[dict]:
    """Only measured invariant failures create proposals. Semantic hints stay observed."""
    patterns = []
    for code, rows in [("primary_class_changed", analysis["immutability"]["violations"]),
                       ("terminal_skip_reintroduced", analysis["terminal_skip"]["resurrections"]),
                       ("terminal_skip_compared", analysis["terminal_skip"]["skipped_pair_endpoints"])]:
        unique = {(r["url"], r["at"]): r for r in rows}
        active = [r for r in unique.values() if current_version and r.get("policy_version") == current_version]
        if unique:
            patterns.append({"id": code, "status": "proposal_requires_owner_approval" if active and analysis["available"] else "historical_or_unavailable",
                "affected_unique_urls": len({r["url"] for r in unique.values()}), "evidence": list(unique.values()),
                "harm": "Violazione osservata del totem; nessuna modifica automatica agli URL o alle classi.",
                "proposed_rule": ({"primary_class_changed": "Il percorso indicato deve riutilizzare la prima classe persistita senza modificarla.",
                    "terminal_skip_reintroduced": "Il percorso indicato deve escludere gli URL con skip definitivo prima di ammetterli al pool.",
                    "terminal_skip_compared": "Il percorso indicato deve escludere gli URL con skip definitivo prima di ammettere coppie duplicate."}[code]) if active else None})
    blocks = [r for r in weekly["softpool"]["runs"] if r["status"] in BLOCKS and
              current_version and r["policy_version"] == current_version and (r["pool_before_review"] or 0) > 0]
    if blocks:
        patterns.append({"id": "softpool_technical_wait", "status": "observe", "run_observations": len(blocks),
            "evidence": blocks[-5:], "harm": "Attese tecniche del pool da distinguere dalle scelte editoriali.", "proposed_rule": None})
    return patterns


def publication_pressure_observation(runs, since, until):
    """Decision-time observations, never sums of rolling snapshot counters."""
    observations, rejected, publisher_rejected = [], {}, {}
    for run in runs:
        at = run_time(run)
        if not at or not since <= at <= until:
            continue
        pressure = ((run.get('editorial_pipeline') or {}).get('scheduling') or {}).get('publication_pressure')
        if isinstance(pressure, dict):
            observations.append({'at': at.isoformat(), **pressure})
            for row in pressure.get('terminal_skipped', []):
                if isinstance(row, dict) and url_key(row):
                    rejected[url_key(row)] = row
        for row in (run.get('menzo') or {}).get('skipped_sample', []):
            if str(row.get('reason') or '').startswith('publication_pressure:') and url_key(row):
                rejected.setdefault(url_key(row), compact(row))
        for section in ('results', 'skipped_approved_articles', 'skipped'):
            for row in (run.get('publisher') or {}).get(section, []):
                if isinstance(row, dict) and str(row.get('reason') or '').startswith('publication_pressure:') and url_key(row):
                    publisher_rejected[url_key(row)] = compact(row)
    return {'available': bool(observations), 'runs_observed': len(observations),
        'observations': observations, 'terminal_skipped_unique_observed': len(set(rejected) | set(publisher_rejected)),
        'terminal_skipped': list(rejected.values()), 'publisher_guard_skipped': list(publisher_rejected.values()),
        'maximum_published_news_24h_at_decision': max((r['published_news_24h'] for r in observations), default=None),
        'meaning': 'Contatori mobili al momento della selezione, non sommabili e non massimo continuo delle pubblicazioni. Esclusioni terminali per pressione, non duplicate, riclassificazioni o blocchi tecnici. Il campione pre-riforma non certifica assenza di scarti.',
        'semantic_quality': 'requires_full_source_review; priority flag is not a quality certification'}


def build_report(root: Path = ROOT, *, until: datetime | None = None, hours: int = 24,
                 snapshot: dict | None = None, release: dict | None = None,
                 quality_report: dict | None = None) -> dict:
    from scripts.observability_snapshot import build_snapshot, load_master_runs
    from agents.canonical_event_ledger import content_id
    until = until or datetime.now(timezone.utc)
    if hours <= 0:
        raise ValueError("hours must be positive")
    since = until - timedelta(hours=hours)
    errors: list[str] = []
    runs, sources, warnings, available, health = load_master_runs(root, allow_tail_fallback=False)
    frozen_raw = read_json(root / "state/newsroom/menzo_primary_classifications_v1.json", dict, errors)
    skip_raw = read_json(root / "state/newsroom/menzo_hard_skips.json", dict, errors)
    frozen_entries = state_rows(frozen_raw, "entries", errors, "primary_store")
    skip_items = state_rows(skip_raw, "items", errors, "terminal_skips")
    frozen = {url_key(r): r for r in (frozen_entries or {}).values()}
    closed = {url_key(r): r for r in skip_items or [] if r.get("terminal") is True}
    dated = [run_time(r) for r in runs]
    dated = [d for d in dated if d and d <= until]
    complete = bool(available and not health.get("master_log_malformed_lines") and dated and min(dated) <= since
                    and frozen_entries is not None and skip_items is not None)
    if not complete: errors.append("primary_lifecycle_window_incomplete")
    snapshot = snapshot if snapshot is not None else build_snapshot(since, until, root, allow_tail_fallback=False)
    analysis = analyze_runs(runs, frozen, closed, since, until, complete=complete)
    weekly = analyze_runs(runs, frozen, closed, until - timedelta(hours=168), until,
        complete=bool(complete and min(dated) <= until - timedelta(hours=168)))
    pub = snapshot.get("authoritative", {}).get("publication", {})
    publication_complete = pub.get("metadata", {}).get("complete_window") is True
    published_ids = set((pub.get("news") or {}).get("content_ids", [])) if publication_complete else set()
    published_rows = {}
    for a in analysis["articles"]:
        if content_id({"url": a["url"]}) in published_ids and a["published"]:
            published_rows[url_key(a)] = a
    classes = Counter(a.get("first_class") or "UNKNOWN" for a in published_rows.values())
    enriched_complete = publication_complete and len(published_rows) == pub.get("unique_news_publications") and not classes.get("UNKNOWN")
    # Current snapshots are effective queues, not claims about the preceding day.
    # Published entries may still exist in the persisted priority queue until its
    # next consumer run; don't turn them into fictitious waiting publications.
    all_published_keys = {url_key(row) for run in runs for row in (run.get("publisher") or {}).get("published", [])
                          if run_time(run) and run_time(run) <= until}
    current_state = {}
    for name in ("menzo_softpool", "menzo_priority_queue"):
        data = read_json(root / f"state/newsroom/{name}.json", dict, errors)
        items = state_rows(data, "items", errors, name)
        effective = [r for r in items or [] if url_key(r) not in all_published_keys and url_key(r) not in closed]
        current_state[name] = {"available": items is not None, "updated_at": (data or {}).get("updated_at"),
            "raw_items_count": len(items) if items is not None else None,
            "effective_pending_observed": len(effective) if items is not None else None,
            "excluded_already_published_observed": sum(url_key(r) in all_published_keys for r in items or []),
            "excluded_terminal_skip_observed": sum(url_key(r) in closed and url_key(r) not in all_published_keys for r in items or []),
            "publication_filter_coverage": "retained_master_history_only",
            "snapshot_only": True, "items": [{**compact(r), "review_count": r.get("soft_board_review_count"),
                "soft_board": r.get("soft_board"), "first_seen_at": r.get("soft_board_first_seen_at") or r.get("priority_queue_first_seen_at")}
                for r in effective]}
    ordered_runs = sorted((r for r in runs if run_time(r) and run_time(r) <= until), key=run_time)
    latest = ordered_runs[-1] if ordered_runs else {}
    current_version = ((latest.get("editorial_pipeline") or {}).get("prefilter") or {}).get("policy_version")
    analysis['immutability']['current_policy_version'] = current_version
    analysis['immutability']['current_violations'] = [v for v in analysis['immutability']['violations'] if current_version and v['policy_version'] == current_version]
    analysis['immutability']['historical_violation_observations'] = len(analysis['immutability']['violations']) - len(analysis['immutability']['current_violations'])
    patterns = observed_patterns(analysis, weekly, current_version)
    proposals = [p for p in patterns if p["status"] == "proposal_requires_owner_approval"]
    econ = economic_sections(root, since, until)
    from scripts.editorial_material_metrics import build_metrics
    material_metrics = build_metrics(root, since, until,
        snapshot.get('authoritative', {}).get('pr131_duplicate_pair_cache'))
    def per_news(value):
        denominator = pub.get('unique_news_publications') if publication_complete else None
        return str((Decimal(str(value)) / denominator).quantize(Decimal('0.00000001'))) if value is not None and denominator else None
    news_econ = econ['partitions']['news_and_editorial']
    econ['per_news'] = {
        'news_and_editorial_cost': per_news(news_econ.get('complete_window_computed_list_price_cost')) if econ['attribution_complete'] else None,
        'news_and_editorial_attempts': per_news(news_econ.get('real_attempts')) if econ['attribution_complete'] else None,
        'meaning': 'Rapporto dei consumi osservati alle news pubblicate nella finestra; include selezione/scarti/attese, non costo marginale della singola news. Report esclusi.',
    }
    quality_errors: list[str] = []
    quality = quality_report if quality_report is not None else read_json(root / "state/reports/owtv_translation_warning_analysis_latest.json", dict, quality_errors)
    quality_at = stamp((quality or {}).get("generated_at"))
    quality_fresh = bool(quality_at and abs((quality_at - until).total_seconds()) <= 600)
    translation = {"available": quality_fresh and not (quality or {}).get("errors"),
        "status_counts": (quality or {}).get("status_counts") if quality_fresh else None,
        "semantic_errors_confirmed": None, "meaning": "reproduced = controllo riprodotto, non errore semantico confermato",
        "examples": [{k: r.get(k) for k in ("title", "source_url", "warning_code", "investigation_status", "evidence", "semantic_verdict")}
                     for r in (quality or {}).get("investigations", [])[:5]] if quality_fresh else []}
    coverage = {"primary_lifecycle": "full" if complete else "partial_or_unavailable",
        "primary_observations": analysis["immutability"]["primary_observations"],
        "weekly_lifecycle": "full" if weekly["available"] else "partial_or_unavailable",
        "publication": "full" if publication_complete else "unavailable",
        "publication_class_enrichment": "full" if enriched_complete else "partial_or_unavailable",
        "first_class_known_urls": sum(bool(a.get("first_class")) for a in analysis["articles"]),
        "first_class_unknown_urls": sum(not a.get("first_class") for a in analysis["articles"]),
        "semantic_classification_quality": "requires_source_review; no automatic reclassification",
        "sources": sources, "warnings": warnings, "master_health": health}
    return {"schema_version": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": since.isoformat(), "window_end": until.isoformat(), "timezone": "Europe/Rome",
        "release": release if release is not None else release_metadata(root), "coverage": coverage,
        "publications": {"news_unique": pub.get("unique_news_publications") if publication_complete else None,
            "reports_unique_separate": pub.get("unique_report_publications") if publication_complete else None,
            "news_by_first_class": dict(classes) if enriched_complete else None,
            "news_records": [{k: a.get(k) for k in ("url", "title", "first_class", "wp_link")} for a in published_rows.values()]},
        "publication_pressure": publication_pressure_observation(runs, since, until),
        "lifecycle": analysis, "weekly": {"available": weekly["available"], "runs_observed": weekly["runs_observed"],
            "policy_versions": weekly["policy_versions"], "cohorts": weekly["cohorts"],
            "soft_status_run_observations": weekly["softpool"]["status_run_observations"]},
        "current_snapshots": current_state, "patterns": patterns, "economics": econ,
        'complete_material_observation': material_metrics,
        "operational": {"runs": snapshot.get("authoritative", {}).get("runs"),
            "publisher": snapshot.get("authoritative", {}).get("publisher"),
            "andrea": snapshot.get("authoritative", {}).get("andrea"),
            "alfred": snapshot.get("authoritative", {}).get("alfred"),
            "source_modifications": snapshot.get("diagnostics", {}).get("actual_source_modifications")},
        "translation_signals": translation, "diagnostic_errors": errors,
        "daily_note": {"local_day": until.astimezone(ROME).date().isoformat(),
            "status": "proposal_requires_owner_approval" if proposals else "no_action_proposed",
            "text": "Proposta da sottoporre a Daniele; nessuna implementazione autorizzata dalla nota." if proposals else NO_ACTION,
            "proposals": proposals, "approval_required": True,
            "limits": "Pochi articoli, slot inutilizzati o zero pubblicazioni soft non costituiscono da soli un pattern dannoso."}}


def note_history(root: Path, report: dict, *, persist: bool) -> list[dict]:
    """Immutable dated observations; identical reruns don't duplicate the journal."""
    path = root / "state/reports/editorial_observation_notes.jsonl"
    history = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)  # corruption must not silently erase history
                if not isinstance(value, dict): raise ValueError("invalid_observation_note")
                history.append(value)
    note = {**report["daily_note"], "window_end": report["window_end"], "release": report["release"],
            "coverage": report["coverage"], "patterns": report["patterns"]}
    digest = hashlib.sha256(json.dumps(note, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    note["note_id"] = digest
    if persist and not any(n.get("note_id") == digest for n in history):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(note, ensure_ascii=False, sort_keys=True) + "\n")
        history.append(note)
    return history


def num(value: Any) -> str:
    return "n.d." if value is None else str(value)


def render_summary(r: dict) -> str:
    life = r["lifecycle"]
    soft = life["softpool"]
    pub = r["publications"]
    release = r["release"]
    lines = ["OSSERVAZIONE REDAZIONALE", f"Finestra: {r['window_start']} → {r['window_end']} (UTC)",
        f"Copertura percorso URL: {r['coverage']['primary_lifecycle']}; classi delle pubblicazioni: {r['coverage']['publication_class_enrichment']}",
        f"News uniche pubblicate: {num(pub['news_unique'])}; report separati: {num(pub['reports_unique_separate'])}"]
    for cl in CLASSES:
        c = life["cohorts"][cl]
        lines.append(f"{cl}: nuovi URL {num(c['new_unique_urls'])}; esiti {c['outcomes'] if c['outcomes'] is not None else 'n.d.'}")
    lines += [f"News pubblicate per classe primaria: {pub['news_by_first_class'] if pub['news_by_first_class'] is not None else 'n.d.'}",
        f"Softpool: ingressi unici osservati {soft['admitted_unique']}; selezionati {soft['selected_unique']}; pubblicati osservati {soft['published_unique_observed']}",
        f"Softpool stati per run: {soft['status_run_observations']}",
        f"Variazioni di classe osservate nella policy attuale: {len(life['immutability']['current_violations']) if life['available'] else 'n.d.'}; osservazioni di variazioni storiche: {life['immutability']['historical_violation_observations']}; URL osservati più volte {life['immutability']['urls_observed_multiple_runs']}",
        f"Violazioni osservate skip tombale: rientri {len(life['terminal_skip']['resurrections'])}; endpoint confrontati nel percorso primario {len(life['terminal_skip']['skipped_pair_endpoints'])}",
        f"Controllo cronologia skip non disponibile per {life['terminal_skip']['run_chronology_unavailable']} run senza ora d'inizio.",
        "Qualità semantica delle classificazioni: richiede verifica delle fonti; non certificata automaticamente.",
        f"Versioni policy nella finestra: {life['policy_versions']}",
        f"Copertura percorso URL settimanale: {r['coverage']['weekly_lifecycle']}; i conteggi incompleti non certificano assenza di problemi."]
    current_patterns = [p for p in r['patterns'] if p['status'] == 'proposal_requires_owner_approval']
    lines += [f"Violazioni candidate nella versione attuale: {len(current_patterns)} pattern (vedi evidenze e limiti negli allegati).",
        f"Duplicate nel percorso primario: coppie ammesse uniche osservate {life['duplicates']['unique_admitted_pairs_observed']}; URL chiusi per duplicate {len(life['duplicates']['terminal_duplicate_urls'])}",
        f"Controlli di traduzione: {r['translation_signals']['status_counts'] if r['translation_signals']['available'] else 'n.d.'}; riprodotto non significa errore semantico."]
    pressure = r.get('publication_pressure') or {}
    lines.append(f"Progressività 24h mobili: run osservate {pressure.get('runs_observed', 0)}; scarti terminali unici osservati {pressure.get('terminal_skipped_unique_observed', 0) if pressure.get('available') else 'n.d.'}; massimo contatore osservato alla selezione {num(pressure.get('maximum_published_news_24h_at_decision'))}. Report esclusi; sotto 25 selezione ordinaria rigorosa, 25–29 MUST/SHOULD prioritari, da 30 MUST. Il contatore non si azzera a mezzanotte.")
    lines.append("Qualità della riforma: verificare su fonti complete il valore autonomo degli SHOULD, la priorità congelata, i follow-up con almeno metà informazione nuova e la naturalezza/fedeltà delle traduzioni. Le metriche automatiche non certificano questi giudizi semantici.")
    overall = r["economics"]["overall"]
    lines.append(f"Costo Gemini calcolato a listino: {num(overall.get('complete_window_computed_list_price_cost'))} {overall.get('currency') or 'n.d.'}; copertura {overall['coverage']}")
    for name, partition in r['economics']['partitions'].items():
        lines.append(f"{name}: chiamate {num(partition['real_attempts'])}; costo {num(partition['complete_window_computed_list_price_cost'])} {partition.get('currency') or 'n.d.'}")
    lines.append(f"Costo news/decisioni per news pubblicata: {num(r['economics']['per_news']['news_and_editorial_cost'])}; tentativi per news {num(r['economics']['per_news']['news_and_editorial_attempts'])}. Report esclusi; rapporti di finestra, non costi marginali.")
    material = r['complete_material_observation']
    lines.append(f"Input completo e verdetti: copertura {material['coverage']}; cutover {num(material['cutover_at'])}; fonti {material['sources']['window_metrics'] if material['sources']['window_metrics'] is not None else 'n.d.'}")
    for phase, metrics in material['inputs'].items():
        lines.append(f"Input {phase}: {metrics['window_metrics'] if metrics['window_metrics'] is not None else 'n.d. (campione negli allegati)'}")
    lines.append(f"Richieste editoriali canoniche, tentativi e chiamate evitate: {material['ai_requests']['window_metrics'] if material['ai_requests']['window_metrics'] is not None else 'n.d. (campione negli allegati)'}. Profili ripetuti non sono nuove richieste.")
    factual = material.get('factual_admission', {})
    lines.append(f"Schede e coppie: copertura {factual.get('coverage', 'unavailable')}; metriche di finestra {factual.get('window_metrics') if factual.get('window_metrics') is not None else 'n.d. (campione negli allegati)'}. Esclusioni history, ammissioni negative e verdetti finali sono distinti.")
    if factual.get('window_metrics') is None:
        lines.append(f"Schede/coppie, sole osservazioni disponibili (finestra non certificata): {factual.get('observed', {})}")
    finals = material['duplicates']
    lines.append(f"Verdetti finali canonici (primario + softpool): {finals['window_metrics'] if finals['window_metrics'] is not None else 'n.d. (campione negli allegati)'}. La correttezza semantica richiede review delle fonti.")
    cache = material['pair_cache']
    hit_rate = f"{cache['pair_hit_rate']:.1%}" if isinstance(cache.get('pair_hit_rate'), (int, float)) else 'n.d.'
    lines.append(f"Cache coppie PR131: copertura {cache.get('coverage', 'unavailable')}; lookup/hit/miss {num(cache.get('pair_lookups'))}/{num(cache.get('pair_hits'))}/{num(cache.get('pair_misses'))}; hit rate {hit_rate}; richieste gate evitate {num(cache.get('gate_logical_requests_avoided'))}.")
    lines.append('Un hit per coppia non equivale a una chiamata evitata; un batch con miss richiede ancora Gemini. Cache e token cached del provider sono distinti.')
    source_cache = material['source_cache_current']
    lines.append(f"Memoria sorgenti, snapshot corrente: corpi {num(source_cache.get('body_entries'))}; record candidate in attesa {num(source_cache.get('candidate_holds'))}, effettivi {num(source_cache.get('effective_candidate_holds'))}; record corpi storici {num(source_cache.get('history_holds'))}. Non sono ingressi nel softpool.")
    for name, econ in r["economics"]["workloads"].items():
        lines.append(f"{name}: chiamate {num(econ['real_attempts'])}; costo {num(econ['complete_window_computed_list_price_cost'])} {econ.get('currency') or 'n.d.'}")
    lines.append(f"Tentativi provider falliti Gemini: {num(r['economics']['failed_attempts'])}; tentativi con output non validato {num(r['economics']['validation_failed_attempts'])}; repair osservati: {num(r['economics']['repairs'])}")
    diagnostics = overall.get('diagnostics') or {}
    lines.append(f"Retry/fallback Gemini, conteggi di finestra: {num(diagnostics.get('retry_attempts') if overall['available'] else None)}/{num(diagnostics.get('fallback_attempts') if overall['available'] else None)}; modelli effettivi: {json.dumps((overall.get('breakdowns') or {}).get('by_model', {}), ensure_ascii=False)}")
    lines.append(f"Attribuzione costi news/report completa: {r['economics']['attribution_complete']}; lavoro non attribuito resta separato. Richieste logiche nel ledger economico: {num(r['economics']['request_identity']['complete_logical_requests'])}.")
    lines.append('Totali token input/output/cached/thinking, versioni di prezzo e associazioni alle richieste sono negli allegati; valori non risolti restano n.d.')
    operational = r['operational']
    lines.append(f"Run completate (fonte canonica): {num((operational.get('runs') or {}).get('completed_unique_run_count'))}")
    andrea = operational.get('andrea') or {}
    lines.append("Andrea, eventi checked/passed/eccezioni/blocked (fonte canonica): " + '/'.join(num((andrea.get(k) or {}).get('event_count')) for k in ('checked', 'passed', 'passed_with_exception', 'blocked')))
    publisher = operational.get('publisher') or {}
    lines.append("Publisher, tentativi/pubblicazioni/già presenti/fallimenti recuperabili/fallimenti terminali: " + '/'.join(
        num(publisher.get(k)) for k in ('attempts', 'publications', 'already_present', 'recoverable_failures', 'terminal_failures')))
    alfred = operational.get('alfred') or {}
    lines.append("Alfred, articoli verificati/warning/blocker finali: " + '/'.join(num(alfred.get(k)) for k in ('articles_reviewed', 'warning_occurrences', 'final_blockers')))
    for name in ('menzo_softpool', 'menzo_priority_queue'):
        state = r['current_snapshots'][name]
        lines.append(f"{name}, snapshot attuale: pending effettivi osservati {num(state['effective_pending_observed'])}; già pubblicati esclusi {state['excluded_already_published_observed']}")
    lines.append(f"Avvisi sui dati: {r['diagnostic_errors'] or 'nessuno'}")
    lines += [f"Ultima PR installata: #{num(release['last_pr'])}; merge {num(release['merged_at'])}; HEAD {num(release['head'])}",
        f"NOTA PER LA PROSSIMA REVIEW: {r['daily_note']['text']}",
        "Ogni proposta richiede approvazione di Daniele prima dell'implementazione."]
    return "\n".join(lines)


def render_markdown(r: dict) -> str:
    lines = ["# OWTV — Osservazione redazionale delle 12", "", render_summary(r), "",
        "## Percorsi degli URL", "", "| Notizia | Prima classe | Esito osservato |", "|---|---|---|"]
    for a in r["lifecycle"]["articles"]:
        title = str(a.get("title") or a["url"]).replace("|", "\\|").replace("\n", " ")
        outcome = "published" if a["published"] else a.get("cohort_outcome") or "vedi eventi JSON"
        lines.append(f"| [{title}]({a['url']}) | {a.get('first_class') or 'n.d.'} | {outcome} |")
    soft = r["lifecycle"]["softpool"]
    lines += ["", "## Softpool: percorso nella finestra", "",
        "Gli stati sono osservazioni di run; non sono conteggi di articoli unici.",
        f"Apertura (ultima osservazione precedente): {soft['opening_last_observed'] if soft['opening_available'] else 'n.d.'}",
        f"Chiusura (ultima run nella finestra): {soft['closing_last_observed'] if soft['closing_available'] else 'n.d.'}",
        "", "| Run UTC | Policy | Stato | Pool prima della review | Selezioni | Scarti | Scadenze per revisioni |", "|---|---|---|---:|---:|---:|---:|"]
    for s in soft["runs"]:
        lines.append(f"| {s['at']} | {s['policy_version']} | {s['status']} | {num(s['pool_before_review'])} | {num(s['selected'])} | {num(s['skipped'])} | {num(s['expired_after_reviews'])} |")
    lines += ["", "### Motivazioni e capacità delle review", ""]
    for s in soft["runs"]:
        if s.get("review"):
            output = s["review"]
            decisions = output.get("decisions", []) if isinstance(output, dict) else output
            lines.append(f"- {s['at']}: {json.dumps(decisions, ensure_ascii=False)}; capacità: {s['capacity_context']}")
        if s.get("technical_details"):
            lines.append(f"- {s['at']}: attesa tecnica — {json.dumps(s['technical_details'], ensure_ascii=False)}")
    material = r['complete_material_observation']
    lines += ['', '## Input completo, cache e verdetti semantici', '',
        f"Copertura: {material['coverage']}; cutover: {num(material['cutover_at'])}.",
        *material['interpretation'], '', '### Profili di input per richiesta', '',
        '| Ora UTC | Fase | Endpoint | Corpo completo | Non completo | Byte del prompt |',
        '|---|---|---:|---:|---:|---:|']
    for p in material['input_profiles']:
        lines.append(f"| {p['at']} | {p['phase']} | {len(p['endpoints'])} | {num(p.get('full_body_endpoints'))} | {num(p.get('body_unavailable_endpoints'))} | {num(p.get('prompt_bytes'))} |")
    lines += ['', '### Coppie e decisioni finali registrate', '',
        '| Ora UTC | Percorso | Articolo corrente | Confronto | Verdetto | Fatto nuovo | Cache |',
        '|---|---|---|---|---|---|---|']
    def cell(value):
        return str(value or '').replace('|', '\\|').replace('\n', ' ')
    for p in material['duplicates']['records']:
        lines.append('| ' + ' | '.join(cell(v) for v in (p['at'], p.get('path'), p['left'].get('title'),
            p['right'].get('title'), p['decision'], p.get('new_fact'), p.get('cache_hit'))) + ' |')
    factual = material.get('factual_admission', {})
    lines += ['', '### Schede isolate e percorso di tutte le coppie eleggibili', '',
              f"Copertura: {factual.get('coverage', 'unavailable')}; cutover: {num(factual.get('cutover_at'))}.",
              *factual.get('interpretation', []), '',
              '| Ora UTC | Coppia | Ambito | Esito | Motivo | Cache decisione |',
              '|---|---|---|---|---|---|']
    for p in factual.get('pair_dispositions', []):
        lines.append('| ' + ' | '.join(cell(v) for v in (p['at'], p['pair_id'], p['scope'], p['decision'], p['reason'], p.get('cache_hit'))) + ' |')
    lines += ['', f"Cicli incompleti: {factual.get('incomplete_cycles', [])}; payload non validi: {factual.get('invalid_payloads', 'n.d.')}.",
              'Schede per URL, inventario, provenienza e cache sono negli allegati JSON. Le fonti integrali non sono replicate nella mail.']
    lines += ['', '### Relazioni semanticamente dichiarate (non cluster lessicali)', '',
        f"Componenti DUPLICATE osservati: {json.dumps(material['duplicates']['duplicate_components'], ensure_ascii=False)}",
        f"Aggiornamenti MATERIAL_UPDATE osservati: {len(material['duplicates']['material_update_links'])}",
        f"Cache PR131, metriche di finestra: {json.dumps(material['pair_cache'], ensure_ascii=False)}",
        f"Cache PR131, snapshot corrente separato: {json.dumps(material['pair_cache_current'], ensure_ascii=False)}",
        f"Memoria sorgenti, snapshot corrente separato: {json.dumps(material['source_cache_current'], ensure_ascii=False)}",
        f"Avvisi input/verdetti: {material['warnings']}"]
    lines += ['', '## Consumi per fase e copertura economica', '',
        r['economics']['per_news']['meaning'], '',
        '| Workload | Input | Output | Input cached effettivo | Thinking effettivo |',
        '|---|---:|---:|---:|---:|']
    for phase, fields in r['economics']['usage']['by_workload'].items():
        lines.append('| ' + phase + ' | ' + ' | '.join(num(fields[k]['window_total']) for k in
            ('input_tokens', 'output_tokens', 'effective_cached_input_tokens', 'effective_thinking_tokens')) + ' |')
    lines += ['', 'I token cached sono quelli normalizzati dal contratto usage del provider. Non sono hit della cache PR131.',
        'Ogni tentativo reale, con modello e costo risolto o indisponibile, è esposto nel JSON; le chiamate diagnostiche isolate non vengono attribuite alla produzione.']
    lines += ["", "## Pattern e limiti", "",
        "Contratto osservato: classificazione primaria immutabile prima di duplicate/pool; skip definitivo escluso da nuovi confronti; quote bookmaker escluse; MUST/SHOULD durante la copertura live pubblicabili autonomamente; il report non sostituisce le news e non alimenta il feed.",
        "Una somiglianza fra titoli, una regola lessicale riprodotta o zero soft pubblicate non dimostrano un errore editoriale.",
        "Le osservazioni di versioni precedenti restano storiche; non giustificano modifiche alla versione attuale.",
        f"Copertura settimanale: {r['coverage']['weekly_lifecycle']}; versioni {r['weekly']['policy_versions']}"]
    for p in r["patterns"]:
        lines += ["", f"- {p['id']}: {p['status']}; {p['harm']}", f"  Evidenze: {json.dumps(p['evidence'], ensure_ascii=False)}"]
    lines += ["", "## Segnali di traduzione", "", r["translation_signals"]["meaning"],
        f"Stati dei controlli: {r['translation_signals']['status_counts'] if r['translation_signals']['available'] else 'n.d.'}",
        "", "## Stato attuale (snapshot, separato dalla finestra)", ""]
    for name, state in r["current_snapshots"].items():
        lines += [f"- {name}: disponibile {state['available']}; aggiornato {state['updated_at']}; pending effettivi osservati {num(state['effective_pending_observed'])}; esclusi già pubblicati {state['excluded_already_published_observed']}; {json.dumps(state['items'], ensure_ascii=False)}"]
    lines += ["", "## Copertura e verifiche operative", "", json.dumps(r["coverage"], ensure_ascii=False), "",
        json.dumps(r["operational"], ensure_ascii=False), "", f"Avvisi diagnostici: {r['diagnostic_errors']}",
        "", "## Storico delle note per la review", "", "| Giorno | Ultima PR | Data merge | Nota |", "|---|---|---|---|"]
    for n in r.get("note_history", [])[-14:]:
        rel = n.get("release", {})
        lines.append(f"| {n['local_day']} | #{num(rel.get('last_pr'))} | {num(rel.get('merged_at'))} | {n['text']} |")
    lines += ["", "## Nota per il giorno dopo", "", r["daily_note"]["text"], "",
        "Proposte in attesa della tua approvazione; nessuna modifica automatica a classi, skip, duplicate o pubblicazioni.", ""]
    for p in r["daily_note"]["proposals"]:
        lines += [f"- {p['id']}: {p['proposed_rule']}", f"  Evidenze: {json.dumps(p['evidence'], ensure_ascii=False)}", ""]
    return "\n".join(lines)


def generate_outputs(root: Path = ROOT, *, until: datetime | None = None, hours: int = 24,
                     output_dir: Path | None = None, state_dir: Path | None = None, persist_note: bool = True,
                     quality_report: dict | None = None) -> dict[str, Path]:
    report = build_report(root, until=until, hours=hours, quality_report=quality_report)
    history = note_history(root, report, persist=persist_note)
    report["note_history"] = history[-30:]
    report["note_history_total"] = len(history)
    report["note_history_source"] = "state/reports/editorial_observation_notes.jsonl"
    output = output_dir or root / "reports"
    state = state_dir or root / "state/reports"
    output.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    token = stamp(report["window_end"]).strftime("%Y%m%d_%H%M%S")
    md = output / f"owtv_daily_editorial_judgment_24h_{token}.md"
    data = output / f"owtv_daily_editorial_judgment_24h_{token}.json"
    latest = state / "owtv_daily_editorial_judgment_latest.json"
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    md.write_text(render_markdown(report), encoding="utf-8")
    data.write_text(text, encoding="utf-8")
    temporary = latest.with_suffix(".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(latest)
    return {"markdown": md, "json": data, "latest_json": latest}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--until")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-note", action="store_true")
    args = parser.parse_args()
    if args.until and stamp(args.until) is None:
        parser.error("--until must be an ISO timestamp")
    print(generate_outputs(until=stamp(args.until), hours=args.hours, output_dir=args.output_dir,
                           persist_note=not args.no_note)["markdown"])
    return 0


if __name__ == "__main__":
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
