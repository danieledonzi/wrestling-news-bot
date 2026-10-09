"""Read-only ED-5 observation over one explicit, homogeneous UTC window."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path


def stamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except (TypeError, ValueError):
        return None


def rows(path):
    if not path.exists():
        return
    with path.open(encoding='utf-8') as source:
        for line in source:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                yield row


def summarize(root: Path, since: datetime, until: datetime):
    classes, latest_candidates, admissions, publications = Counter(), {}, {}, {}
    relations, relation_details = Counter(), {}
    retries = Counter()
    run_count = covered = failures = 0
    relation_evaluations = queue_deferrals = cache_hits = cache_misses = 0
    for row in rows(root / 'state/newsroom/master_log.jsonl'):
        when = stamp((row.get('run') or {}).get('started_at') or row.get('recorded_at'))
        if not when or not since <= when < until:
            continue
        run_count += 1
        pipeline = row.get('editorial_pipeline') or {}
        prefilter = pipeline.get('prefilter') or {}
        if not prefilter:
            continue
        covered += 1
        failures += pipeline.get('status') != 'VALIDATED'
        classes.update(prefilter.get('classes') or {})
        relation_evaluations += int(prefilter.get('duplicate_relations', 0))
        cache_hits += int(pipeline.get('duplicate_cache_hits', 0))
        cache_misses += int(pipeline.get('duplicate_cache_misses', 0))
        for candidate in prefilter.get('candidates', []):
            key = candidate.get('url') or candidate.get('candidate_id')
            latest_candidates[key] = candidate
            retries[key] += 1
        for relation in prefilter.get('relations', []):
            key = relation['pair_id']
            relations[key] += 1
            relation_details[key] = relation
        scheduling = pipeline.get('scheduling') or {}
        queue_deferrals += int(scheduling.get('should_deferred_capacity', 0))
        for candidate in scheduling.get('soft_board_admitted_items', []):
            admissions[candidate.get('url')] = candidate
        for published in (row.get('publisher') or {}).get('published', []):
            key = published.get('source_url')
            publications[key] = {**published, 'run_started_at': when.isoformat()}
    phases = defaultdict(lambda: {'calls': 0, 'repairs': 0, 'unpriced_calls': 0, 'known_cost_usd': Decimal(0)})
    for row in rows(root / 'state/newsroom/gemini_call_ledger.jsonl'):
        when = stamp(row.get('timestamp'))
        if not when or not since <= when < until or row.get('status') == 'avoided':
            continue
        phase = str(row.get('phase') or row.get('workload') or 'unknown')
        item = phases[phase]
        item['calls'] += 1
        item['repairs'] += bool(row.get('repair'))
        cost = row.get('computed_list_price_cost')
        if cost is None:
            item['unpriced_calls'] += 1
        else:
            item['known_cost_usd'] += Decimal(str(cost))
    history_path = root / 'state/newsroom/publisher_history.json'
    # Resolve the same configured Publisher history path as the application when present.
    if not history_path.exists():
        history_path = root / 'state/publisher_history.json'
    history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else {}
    for row in history.values() if isinstance(history, dict) else history:
        key = row.get('source_url') or row.get('url')
        if key not in publications:
            continue
        first = stamp((row.get('editorial_director') or {}).get('first_seen_at'))
        published_at = stamp(row.get('published_at'))
        publications[key]['published_at'] = row.get('published_at')
        publications[key]['first_seen_to_publish_minutes'] = (
            round((published_at - first).total_seconds() / 60, 2) if first and published_at else None)
    unique_classes = Counter(row.get('editorial_class', 'UNKNOWN') for row in latest_candidates.values())
    published_classes = Counter((row.get('editorial_director') or {}).get('editorial_class', 'UNKNOWN')
                                for row in publications.values())
    for item in phases.values():
        item['known_cost_usd'] = str(item['known_cost_usd'])
    return {
        'since': since.isoformat(), 'until': until.isoformat(), 'runs': run_count,
        'ed5_covered_runs': covered, 'ed5_failed_runs': failures,
        'class_observations_including_retries': dict(classes), 'unique_candidates_by_latest_class': dict(unique_classes),
        'duplicate_relation_evaluations': relation_evaluations, 'unique_duplicate_pairs': len(relations),
        'duplicate_cache_hits': cache_hits, 'duplicate_cache_misses': cache_misses,
        'should_capacity_deferrals_including_retries': queue_deferrals,
        'soft_pool_unique_admissions': len(admissions), 'published_by_class': dict(published_classes),
        'cost_by_phase': dict(phases), 'candidate_decisions': list(latest_candidates.values()),
        'soft_pool_admissions': list(admissions.values()), 'publications': list(publications.values()),
        'repeated_candidate_evaluations': {key: count for key, count in retries.items() if count > 1},
        'duplicate_pairs': [{**relation_details[key], 'evaluations': count} for key, count in relations.items()],
        'limitations': ['Known costs exclude unpriced calls; inspect unpriced_calls.',
                        'First-seen delay starts at pipeline observation, not at the live event.',
                        'Class totals include retries; unique counts use each candidate latest observed class.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--since', required=True, help='Inclusive ISO timestamp, normally verified deploy time')
    parser.add_argument('--hours', type=float, default=24)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    since = stamp(args.since)
    if since is None:
        parser.error('Invalid --since timestamp')
    result = summarize(args.root, since, min(since + timedelta(hours=args.hours), datetime.now(timezone.utc)))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
