"""Read-only complete-input and final-pair metrics, with explicit cutover coverage."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents.canonical_event_ledger import validate_event
from agents.menzo_source_material import CONTRACT_VERSION
from scripts.observability_snapshot import load_jsonl_defensively


def _stamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError):
        return None


def _payload(row):
    try:
        result = json.loads(row.get('result') or '')
        return result if isinstance(result, dict) and result.get('input_contract') == CONTRACT_VERSION else None
    except (ValueError, TypeError):
        return None


def _graph(records):
    """Only recorded DUPLICATE edges form components; show/name similarity never does."""
    parent = {}
    def find(value):
        parent.setdefault(value, value)
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value
    for row in records:
        if row['decision'] != 'DUPLICATE':
            continue
        left, right = row.get('left', {}).get('url'), row.get('right', {}).get('url')
        if left and right:
            parent[find(left)] = find(right)
    groups = defaultdict(list)
    for node in parent:
        groups[find(node)].append(node)
    return [sorted(nodes) for nodes in groups.values() if len(nodes) > 1]


def build_metrics(root: Path, since, until, cache_metrics=None):
    path = root / 'state/newsroom/canonical_event_ledger.jsonl'
    rows, warnings, readable, malformed = load_jsonl_defensively(path)
    invalid = sum(bool(validate_event(row)) for row in rows)
    cycles = [row for row in rows if row.get('event_type') == 'editorial_full_material_cycle'
              and row.get('agent') == 'Menzo' and _payload(row) and _stamp(row.get('timestamp_utc'))
              and _stamp(row['timestamp_utc']) <= until]
    cutover = min((_stamp(row['timestamp_utc']) for row in cycles), default=None)
    coverage = ('unavailable' if not readable or malformed or invalid or cutover is None else
                'full' if cutover <= since else 'partial')
    profiles, sources, verdicts = [], [], []
    payload_errors = []
    expected = {'editorial_input_profile', 'editorial_source_material', 'editorial_duplicate_verdict'}
    for row in rows:
        at = _stamp(row.get('timestamp_utc'))
        if not at or not since <= at <= until or row.get('agent') != 'Menzo' or row.get('event_type') not in expected:
            continue
        data = _payload(row)
        if data is None:
            payload_errors.append('invalid_editorial_event_payload')
            continue
        data = {**data, 'at': at.isoformat(), 'run_id': row.get('run_id'),
                'logical_request_id': row.get('logical_request_id'), 'phase': row.get('model_role')}
        kind = row['event_type']
        if kind == 'editorial_input_profile':
            if (not isinstance(data.get('phase'), str) or data.get('coverage') != 'full' or not isinstance(data.get('endpoints'), list) or
                    any(not isinstance(r, dict) for r in data['endpoints'])):
                payload_errors.append('invalid_input_profile')
            else:
                profiles.append(data)
        elif kind == 'editorial_source_material':
            if data.get('status') not in {'COMPLETE', 'TECHNICAL_HOLD'} or not data.get('url'):
                payload_errors.append('invalid_source_observation')
            else:
                sources.append(data)
        else:
            if (data.get('decision') not in {'DUPLICATE', 'NO_MATCH', 'MATERIAL_UPDATE'} or
                    data.get('semantic_authority') != 'gemini_final' or
                    not all(data.get(k) for k in ('pair_id', 'left_id', 'right_id', 'material_digest', 'contract_fingerprint')) or
                    not isinstance(data.get('left'), dict) or not isinstance(data.get('right'), dict)):
                payload_errors.append('invalid_final_verdict')
            else:
                verdicts.append(data)
    if payload_errors:
        coverage = 'unavailable'
    complete = coverage == 'full'
    inputs = {}
    for phase in sorted({r['phase'] for r in profiles}):
        selected = [r for r in profiles if r['phase'] == phase]
        endpoints = [e for r in selected for e in r['endpoints']]
        counts = Counter(e.get('input_coverage') or 'UNKNOWN' for e in endpoints)
        observed = {'provider_requests': len(selected), 'endpoint_occurrences': len(endpoints),
                    'unique_endpoint_urls': len({e['url'] for e in endpoints if e.get('url')}),
                    'coverage_counts': dict(counts), 'prompt_bytes': sum(r.get('prompt_bytes', 0) for r in selected),
                    'full_body_ratio': counts['FULL_BODY'] / len(endpoints) if endpoints else None}
        inputs[phase] = {'observed': observed, 'window_metrics': observed if complete else None}
    final = {}
    conflicts = []
    for row in sorted(verdicts, key=lambda r: r['at']):
        identity = (row['pair_id'], row['material_digest'], row['contract_fingerprint'])
        if identity in final and final[identity]['decision'] != row['decision']:
            conflicts.append({'pair_id': row['pair_id'], 'at': row['at']})
        final[identity] = row
    records = list(final.values())
    observed_verdicts = {'verdict_observations': len(verdicts), 'unique_pair_material_decisions': len(records),
        'unique_pair_ids': len({r['pair_id'] for r in records}),
        'decisions': dict(Counter(r['decision'] for r in records)),
        'by_path': {p: dict(Counter(r['decision'] for r in records if r.get('path') == p))
                    for p in sorted({r.get('path', 'unknown') for r in records})},
        'conflicting_same_material_decisions': len(conflicts)}
    source_counts = {'observations': len(sources),
        'source_fetches': sum(r['origin'] == 'source_fetch' for r in sources),
        'canonical_reuses': sum(r['origin'] == 'canonical_reuse' and r['status'] == 'COMPLETE' for r in sources),
        'held_observations': sum(r['status'] == 'TECHNICAL_HOLD' for r in sources),
        'unique_held_urls': len({r['url'] for r in sources if r['status'] == 'TECHNICAL_HOLD'})}
    current_cache = {'available': False, 'entries': None, 'meaning': 'snapshot attuale, non hit rate storico'}
    cache_path = root / 'state/newsroom/menzo_active_duplicate_pair_cache_v1.json'
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        if cache.get('schema_version') == 'owtv_active_duplicate_pair_cache_v1' and isinstance(cache.get('entries'), dict):
            current_cache.update(available=True, entries=len(cache['entries']))
    except (OSError, ValueError, AttributeError):
        pass
    current_sources = {'available': False, 'body_entries': None, 'candidate_holds': None,
                       'history_holds': None, 'effective_candidate_holds': None,
                       'meaning': 'snapshot della memoria sorgenti; record grezzi ed effettivi distinti; non conteggio di finestra'}
    try:
        state = json.loads((root / 'state/newsroom/menzo_source_material_v1.json').read_text(encoding='utf-8'))
        if (state.get('version') == CONTRACT_VERSION and isinstance(state.get('bodies'), dict) and
                isinstance(state.get('holds'), dict) and all(isinstance(r, dict) and isinstance(r.get('item'), dict)
                                                            for r in state['holds'].values())):
            candidates = [r for r in state['holds'].values() if r['item'].get('candidate_id')]
            current_sources.update(available=True, body_entries=len(state['bodies']),
                candidate_holds=len(candidates), history_holds=len(state['holds']) - len(candidates),
                holds=[{'url': r['item'].get('url') or r['item'].get('source_url'),
                        **{k: r.get(k) for k in ('reason', 'first_seen_at', 'retry_after', 'updated_at')}}
                       for r in state['holds'].values()])
            from agents.menzo_policy_v93_15 import terminal_skip_memory, source_key
            from agents.news_scheduling import is_successful_news_publication
            publisher_path = root / 'state/newsroom/publisher_history.json'
            skip_path = root / 'state/newsroom/menzo_hard_skips.json'
            if publisher_path.exists() and skip_path.exists():
                published = json.loads(publisher_path.read_text(encoding='utf-8'))
                if not isinstance(published, (dict, list)):
                    raise ValueError('publisher_snapshot_unavailable')
                pub_rows = published.values() if isinstance(published, dict) else published
                pub_rows = list(pub_rows)
                if any(not isinstance(r, dict) for r in pub_rows):
                    raise ValueError('publisher_snapshot_invalid_row')
                published_keys = {source_key(r.get('source_url') or r.get('url') or '') for r in pub_rows
                                  if is_successful_news_publication(r)}
                closed = terminal_skip_memory(path=skip_path)
                now = datetime.now(timezone.utc)
                current_sources['effective_candidate_holds'] = sum(
                    source_key(r['item'].get('url') or r['item'].get('source_url') or '') not in published_keys and
                    source_key(r['item'].get('url') or r['item'].get('source_url') or '') not in closed and
                    _stamp(r.get('first_seen_at')) is not None and
                    now - _stamp(r['first_seen_at']) < timedelta(hours=24) for r in candidates)
    except (OSError, ValueError, AttributeError):
        pass
    return {'contract_version': CONTRACT_VERSION, 'coverage': coverage,
        'cutover_at': cutover.isoformat() if cutover else None,
        'source': str(path.relative_to(root)), 'warnings': warnings + payload_errors,
        'invalid_event_rows': invalid, 'malformed_rows': malformed,
        'inputs': inputs, 'input_profiles': profiles,
        'sources': {'observed': source_counts, 'window_metrics': source_counts if complete else None,
                    'records': sources},
        'duplicates': {'observed': observed_verdicts, 'window_metrics': observed_verdicts if complete else None,
            'records': records, 'conflicts': conflicts,
            'duplicate_components': _graph(records),
            'material_update_links': [r for r in records if r['decision'] == 'MATERIAL_UPDATE'],
            'semantic_correctness': 'not_automatically_certified'},
        'pair_cache': cache_metrics or {'coverage': 'unavailable'}, 'pair_cache_current': current_cache,
        'source_cache_current': current_sources,
        'interpretation': [
            'FULL_BODY certifica il materiale fornito, non la correttezza editoriale del verdetto.',
            'Endpoint e verdetti osservati possono ripetersi; coppie/materiali unici e URL chiusi sono grani diversi.',
            'Hit per coppia non equivale a chiamata evitata: un batch con miss richiede ancora Gemini.',
            'MATERIAL_UPDATE collega aggiornamenti; non unisce notizie in un cluster duplicate.',
            'I componenti DUPLICATE riportano decisioni registrate, non errori semantici confermati.',
            'Prima del cutover o con dati incompleti, i totali di finestra sono n.d.; observed resta un campione.',
        ]}
