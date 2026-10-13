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


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _identity(value):
    return isinstance(value, str) and bool(value)


def _endpoint(value):
    return (isinstance(value, dict) and isinstance(value.get('url'), str) and bool(value['url']) and
            isinstance(value.get('input_coverage'), str) and _whole(value.get('body_chars')) and
            (value.get('input_coverage') != 'FULL_BODY' or
             (value['body_chars'] >= 200 and isinstance(value.get('body_sha256'), str) and
              len(value['body_sha256']) == 64)))


EDITORIAL_PHASES = {'editorial_director_active', 'editorial_duplicate_admission',
                    'editorial_soft_duplicate_admission', 'editorial_director_duplicate_gate',
                    'editorial_soft_board'}


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
    invalid, valid_rows = 0, []
    for row in rows:
        if validate_event(row):
            invalid += 1
        else:
            valid_rows.append(row)
    rows = valid_rows
    cycles = [row for row in rows if row.get('event_type') == 'editorial_full_material_cycle'
              and row.get('agent') == 'Menzo' and _payload(row) and
              _identity(_payload(row).get('observation_id')) and _stamp(row.get('timestamp_utc'))
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
            if (data.get('phase') not in EDITORIAL_PHASES or not row.get('logical_request_id') or
                    data.get('coverage') != 'full' or not isinstance(data.get('endpoints'), list) or
                    not _whole(data.get('prompt_bytes')) or
                    any(not _endpoint(r) for r in data['endpoints'])):
                payload_errors.append('invalid_input_profile')
            else:
                profiles.append(data)
        elif kind == 'editorial_source_material':
            if (data.get('status') not in ('COMPLETE', 'TECHNICAL_HOLD') or not _endpoint(data) or
                    data.get('origin') not in ('canonical_reuse', 'source_fetch', 'backoff') or
                    not isinstance(data.get('stage'), str) or not _identity(data.get('observation_id'))):
                payload_errors.append('invalid_source_observation')
            else:
                sources.append(data)
        else:
            if (data.get('decision') not in ('DUPLICATE', 'NO_MATCH', 'MATERIAL_UPDATE') or
                    data.get('semantic_authority') != 'gemini_final' or
                    not all(_identity(data.get(k)) for k in ('pair_id', 'left_id', 'right_id', 'material_digest', 'contract_fingerprint')) or
                    not _endpoint(data.get('left')) or not _endpoint(data.get('right')) or
                    data.get('path') not in ('primary', 'softpool') or not _identity(data.get('verdict_observation_id'))):
                payload_errors.append('invalid_final_verdict')
            else:
                verdicts.append(data)
    # A cutover marker proves installation, not complete emission. Reconcile
    # source sessions and actual model attempts before certifying any totals.
    all_sources = defaultdict(list)
    session_starts, session_ends = {}, {}
    verdict_ends, all_verdicts = {}, defaultdict(list)
    attempts, requests, avoided = {}, {}, {}
    for row in rows:
        at = _stamp(row.get('timestamp_utc'))
        if not at or at > until:
            continue
        data = _payload(row)
        if data and row.get('event_type') == 'editorial_source_material' and _identity(data.get('observation_id')):
            all_sources[data.get('observation_id')].append(data)
        if data and row.get('event_type') == 'editorial_duplicate_verdict' and _identity(data.get('verdict_observation_id')):
            all_verdicts[data.get('verdict_observation_id')].append(data)
        if data and row.get('event_type') == 'editorial_full_material_cycle' and _identity(data.get('verdict_observation_id')):
            verdict_ends[data['verdict_observation_id']] = (at, data, row.get('logical_request_id'))
        if data and row.get('event_type') == 'editorial_full_material_cycle' and _identity(data.get('observation_id')):
            target = session_starts if row.get('status') == 'started' else session_ends
            target[data['observation_id']] = (at, data)
        if since <= at and row.get('model_role') in EDITORIAL_PHASES:
            if row.get('event_type') == 'model_attempt_started' and row.get('attempt_id'):
                attempts[row['attempt_id']] = row
            elif row.get('event_type') == 'logical_ai_request_created' and row.get('logical_request_id'):
                requests[row['logical_request_id']] = row
            elif row.get('event_type') == 'model_attempt_avoided' and row.get('logical_request_id'):
                avoided[row['logical_request_id']] = row
    for observation_id in set(session_starts) | set(session_ends):
        start = session_starts.get(observation_id)
        end = session_ends.get(observation_id)
        if not ((start and start[0] >= since) or (end and end[0] >= since)):
            continue
        if (not start or not end or not _whole(end[1].get('source_observations')) or
                end[1]['source_observations'] != len(all_sources[observation_id])):
            payload_errors.append('source_observation_coverage_incomplete')
    unique_profiles = {}
    for row in profiles:
        request_id = row['logical_request_id']
        previous = unique_profiles.get(request_id)
        if previous and any(previous[k] != row[k] for k in ('phase', 'endpoints', 'prompt_bytes')):
            payload_errors.append('conflicting_input_profiles')
        unique_profiles[request_id] = row
    attempt_requests = {r.get('logical_request_id') for r in attempts.values()}
    if attempt_requests != set(unique_profiles):
        payload_errors.append('provider_input_profile_coverage_incomplete')
    for observation_id in set(verdict_ends) | {r.get('verdict_observation_id') for r in verdicts}:
        end = verdict_ends.get(observation_id)
        if end and end[0] < since:
            continue
        if (not end or not _whole(end[1].get('verdict_observations')) or
                end[1]['verdict_observations'] != len(all_verdicts[observation_id])):
            payload_errors.append('final_verdict_coverage_incomplete')
    gate_requests = {r.get('logical_request_id') for r in attempts.values()
                     if r.get('model_role') == 'editorial_director_duplicate_gate'}
    if not gate_requests.issubset({end[2] for end in verdict_ends.values()}):
        payload_errors.append('final_verdict_operation_incomplete')
    inputs = {}
    for phase in sorted({r['phase'] for r in profiles}):
        selected = [r for r in unique_profiles.values() if r['phase'] == phase]
        endpoints = [e for r in selected for e in r['endpoints']]
        counts = Counter(e.get('input_coverage') or 'UNKNOWN' for e in endpoints)
        observed = {'input_profile_observations': sum(r['phase'] == phase for r in profiles),
                    'logical_requests': len(selected),
                    'provider_attempts': sum(r.get('model_role') == phase for r in attempts.values()),
                    'endpoint_occurrences': len(endpoints),
                    'unique_endpoint_urls': len({e['url'] for e in endpoints if e.get('url')}),
                    'coverage_counts': dict(counts), 'prompt_bytes': sum(r.get('prompt_bytes', 0) for r in selected),
                    'full_body_ratio': counts['FULL_BODY'] / len(endpoints) if endpoints else None}
        inputs[phase] = {'observed': observed}
    final = {}
    conflicts = []
    for row in sorted(verdicts, key=lambda r: r['at']):
        identity = (row['pair_id'], row['material_digest'], row['contract_fingerprint'])
        if identity in final and final[identity]['decision'] != row['decision']:
            conflicts.append({'pair_id': row['pair_id'], 'at': row['at']})
        final[identity] = row
    records = list(final.values())
    if conflicts:
        payload_errors.append('conflicting_final_verdicts')
    lookup_hits = [r for r in rows if r.get('event_type') == 'duplicate_pair_cache_hit' and
                   since <= (_stamp(r.get('timestamp_utc')) or datetime.min.replace(tzinfo=timezone.utc)) <= until]
    if any(not any(v['run_id'] == hit.get('run_id') and v['pair_id'] == hit.get('pair_id') and
                   v.get('cache_hit') for v in verdicts) for hit in lookup_hits):
        payload_errors.append('cached_verdict_coverage_incomplete')
    if payload_errors:
        coverage = 'unavailable'
    complete = coverage == 'full'
    for metrics in inputs.values():
        metrics['window_metrics'] = metrics['observed'] if complete else None
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
        'ai_requests': {'observed': {'logical_requests': len(requests), 'provider_attempts': len(attempts),
                                    'avoided_logical_requests': len(avoided)},
                        'window_metrics': {'logical_requests': len(requests), 'provider_attempts': len(attempts),
                                           'avoided_logical_requests': len(avoided)} if complete else None},
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
            'Profili ripetuti non sono nuove richieste; le richieste logiche e i tentativi provider hanno identità distinte.',
            'source_fetches conta operazioni di estrazione osservate, non richieste HTTP interne o risparmi monetari.',
            'Hit per coppia non equivale a chiamata evitata: un batch con miss richiede ancora Gemini.',
            'MATERIAL_UPDATE collega aggiornamenti; non unisce notizie in un cluster duplicate.',
            'I componenti DUPLICATE riportano decisioni registrate, non errori semantici confermati.',
            'Prima del cutover o con dati incompleti, i totali di finestra sono n.d.; observed resta un campione.',
        ]}
