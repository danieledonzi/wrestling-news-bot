"""Persistent MUST/SHOULD handoff; only confirmed publication or terminal decisions drain it."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from agents import menzo_policy_v93_15 as menzo
from agents.news_scheduling import is_successful_news_publication


def queue_path() -> Path:
    return Path(menzo.SOFTPOOL_FILE).with_name('menzo_priority_queue.json')


def _key(row: Mapping[str, Any]) -> str:
    return menzo.source_key(str(row.get('url') or row.get('source_url') or ''))


def _class(row: Mapping[str, Any]) -> str:
    return str((row.get('editorial_director') or {}).get('editorial_class') or '')


def _read() -> list[dict[str, Any]]:
    path = queue_path()
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not isinstance(value.get('items'), list):
        raise ValueError('invalid_priority_queue')
    return value['items']


def _published_keys() -> set[str]:
    raw = menzo.load_json(menzo.publisher_history_file(), {})
    rows = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    return {_key(row) for row in rows if isinstance(row, dict)
            and is_successful_news_publication(row) and not row.get('dry_run')}


def _write(rows: list[dict[str, Any]]) -> None:
    path = queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'version': 1, 'updated_at': menzo.utc_now(), 'items': rows},
                                    ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def augment_board(board: Mapping[str, Any]) -> dict[str, Any]:
    """Retry strong candidates even when the feed no longer contains their URL."""
    result = copy.deepcopy(dict(board))
    published = _published_keys()
    queued = [row for row in _read() if _key(row) not in published]
    _write(queued)
    by_key = {_key(row): copy.deepcopy(row) for row in queued}
    for row in board.get('news_candidates_for_menzo', []):
        if not isinstance(row, dict) or _key(row) in published:
            continue
        key = _key(row)
        prior = by_key.get(key, {})
        by_key[key] = {**prior, **copy.deepcopy(row)}
        if prior.get('priority_queue_first_seen_at'):
            by_key[key]['priority_queue_first_seen_at'] = prior['priority_queue_first_seen_at']
    queued_by_key = {_key(row): row for row in queued}
    for key, row in by_key.items():
        prior = queued_by_key.get(key)
        if prior and all(row.get(field) == prior.get(field) for field in ('title', 'summary', 'canonical_source_body')):
            row['_priority_queue_editorial'] = copy.deepcopy(prior.get('editorial_director', {}))
        else:
            row.pop('_priority_queue_editorial', None)
    result['news_candidates_for_menzo'] = list(by_key.values())
    result['priority_queue_reintroduced'] = len(queued)
    return result


def schedule(projected: dict[str, Any], snapshot: Mapping[str, Any]) -> None:
    """Reserve capacity for strong news before the soft board and persist overflow."""
    from agents.bob import dynamic_article_capacity
    now = str(snapshot.get('observation_timestamp') or menzo.utc_now())
    published = _published_keys()
    by_key = {_key(row): copy.deepcopy(row) for row in _read() if _key(row) not in published}
    for section in ('skipped', 'pending'):
        for row in projected.get(section, []):
            # New validated primary decisions supersede an old queue entry.
            if row.get('decision_authority') in {'editorial_director', 'deterministic_exact_duplicate',
                                                'semantic_duplicate_gate'}:
                by_key.pop(_key(row), None)
    selected = projected.get('selected', [])
    strong = [row for row in selected if _class(row) in {'MUST_PUBLISH', 'SHOULD_PUBLISH'}]
    for row in strong:
        key = _key(row)
        prior = by_key.get(key, {})
        row['priority_queue_first_seen_at'] = str(prior.get('priority_queue_first_seen_at') or
                                                 row.get('priority_queue_first_seen_at') or now)
        row['editorial_director']['first_seen_at'] = row['priority_queue_first_seen_at']
        row.pop('_priority_queue_editorial', None)
        by_key[key] = copy.deepcopy(row)
    must = [row for row in strong if _class(row) == 'MUST_PUBLISH']
    should = [row for row in strong if _class(row) == 'SHOULD_PUBLISH']
    # Factual show identity is scheduling metadata; Gemini still owns the class.
    def order(row):
        live = bool((row.get('show_report_id') or row.get('event_report_key') or row.get('special_event_match'))
                    and not row.get('corresponding_report_published'))
        return (not live, row.get('priority_queue_first_seen_at', now))
    should.sort(key=order)
    capacity, reason = dynamic_article_capacity(projected, should)
    kept, deferred = should[:max(0, capacity)], should[max(0, capacity):]
    projected['selected'] = must + kept + [row for row in selected if row not in strong]
    for row in deferred:
        row['decision'] = 'defer'
        row['scheduling_override'] = {'reason': 'should_wait_capacity', 'final_action': 'DEFER',
                                      'original_recommended_action': 'SELECT'}
        projected.setdefault('pending', []).append(row)
    projected.setdefault('postprocess', {}).update(
        priority_queue_size=len(by_key), should_deferred_capacity=len(deferred),
        strong_ordinary_capacity=capacity, strong_capacity_reason=reason,
        should_deferred_urls=[row.get('url') or row.get('source_url') for row in deferred])
    _write(list(by_key.values()))
