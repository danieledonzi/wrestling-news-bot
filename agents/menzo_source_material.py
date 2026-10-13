"""Complete factual input for Active only; source failures never become editorial SKIP."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from agents import source_body
from agents.canonical_event_ledger import active_event

CONTRACT_VERSION = 'owtv_complete_editorial_material_v1'
CACHE_FILE = Path(__file__).resolve().parents[1] / 'state/newsroom/menzo_source_material_v1.json'
MAX_ENTRIES = 2048
HOLD_HOURS = 24


def key(row):
    from agents.menzo_policy_v93_15 import source_key
    return source_key(str(row.get('url') or row.get('source_url') or ''))


def _stamp(value):
    try:
        value = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    except (TypeError, ValueError):
        return None


def _read():
    if not CACHE_FILE.exists():
        return {'version': CONTRACT_VERSION, 'bodies': {}, 'holds': {}}
    value = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or value.get('version') != CONTRACT_VERSION or
            not isinstance(value.get('bodies'), dict) or not isinstance(value.get('holds'), dict) or
            any(not isinstance(v, dict) for v in value['bodies'].values()) or
            any(not isinstance(v, dict) or not isinstance(v.get('item'), dict) for v in value['holds'].values())):
        raise ValueError('invalid_source_material_cache')
    return value


def _write(value):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = CACHE_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    temporary.replace(CACHE_FILE)


def _fetch_body(row):
    return source_body.hydrate(row)


def profile(row):
    body = str(row.get('retained_body') or '')
    return {'url': row.get('url') or row.get('source_url'),
            'input_coverage': row.get('input_coverage') or 'RSS_SUMMARY_ONLY',
            'body_chars': len(body), 'body_sha256': hashlib.sha256(body.encode()).hexdigest() if body else None}


def emit(event_type, stage, status, payload, **identity):
    """Versioned JSON facts inside the existing closed event envelope."""
    try:
        return active_event(event_type, 'Menzo', stage, status,
                            result=json.dumps({'input_contract': CONTRACT_VERSION, **payload},
                                              ensure_ascii=False, sort_keys=True), **identity)
    except Exception:
        return False


class Session:
    """One cache read/write per operation; no source fetch per comparison pair."""
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.now = _stamp(snapshot.get('observation_timestamp')) or datetime.now(timezone.utc)
        self.rows = []
        self.changed = False
        self.cache_error = None
        try:
            self.data = _read()
        except (OSError, ValueError):
            # Do not overwrite a corrupt cache or disguise it as valid empty history.
            self.data = {'version': CONTRACT_VERSION, 'bodies': {}, 'holds': {}}
            self.cache_error = 'source_material_cache_unavailable'

    def hold(self, row, reason, *, retry_after=None):
        url_key = key(row)
        if not url_key:
            return
        prior = self.data['holds'].get(url_key, {})
        self.data['holds'][url_key] = {'item': copy.deepcopy(dict(row)), 'reason': reason,
            'first_seen_at': prior.get('first_seen_at') or self.now.isoformat(),
            'updated_at': self.now.isoformat(),
            'retry_after': retry_after or (self.now + timedelta(minutes=30)).isoformat()}
        self.changed = True

    def hydrate(self, row, stage):
        url_key = key(row)
        endpoint_id = row.get('candidate_id') or row.get('article_id')
        trusted = self.snapshot.get('_active_source_contracts', {}).get(endpoint_id)
        cached = self.data['bodies'].get(url_key, {})
        contract = next((c for c in (row.get('canonical_source_body'), trusted, cached.get('contract'))
                         if source_body.valid_contract(c)), None)
        origin = 'canonical_reuse'
        reason = None
        if contract is None:
            prior = self.data['holds'].get(url_key, {})
            retry = _stamp(prior.get('retry_after'))
            if retry and retry > self.now:
                reason = 'source_fetch_backoff'
            else:
                item = copy.deepcopy(dict(row))
                try:
                    ok, reason = _fetch_body(item)
                except Exception as exc:
                    ok, reason = False, 'source_extraction_error:' + type(exc).__name__
                contract = item.get('canonical_source_body') if ok else None
                origin = 'source_fetch'
                if not source_body.valid_contract(contract):
                    contract = None
        if contract is None:
            row.pop('retained_body', None)
            row['input_coverage'] = 'BODY_UNAVAILABLE'
            retry_after = (prior.get('retry_after') if reason == 'source_fetch_backoff' else None)
            self.hold(row, reason or 'complete_body_unavailable', retry_after=retry_after)
            result = {**profile(row), 'stage': stage, 'origin': origin, 'status': 'TECHNICAL_HOLD',
                      'reason': reason or 'complete_body_unavailable'}
        else:
            body = source_body.contract_text({'canonical_source_body': contract})
            row.update(retained_body=body, input_coverage='FULL_BODY')
            self.snapshot.setdefault('_active_source_contracts', {})[endpoint_id] = copy.deepcopy(contract)
            self.snapshot.setdefault('_duplicate_revalidation_bodies', {})[endpoint_id] = {
                'text': body, 'coverage': 'FULL_BODY', 'sha256': contract['sha256']}
            if cached.get('contract') != contract:
                self.data['bodies'][url_key] = {'contract': copy.deepcopy(contract), 'stored_at': self.now.isoformat()}
                self.changed = True
            result = {**profile(row), 'stage': stage, 'origin': origin, 'status': 'COMPLETE'}
        self.rows.append(result)
        emit('editorial_source_material', 'selection', 'success' if contract else 'pending',
             result, item=row, model_role=stage)
        return contract is not None

    def finish(self):
        if self.changed and not self.cache_error:
            bodies = self.data['bodies']
            self.data['bodies'] = dict(sorted(bodies.items(), key=lambda kv: kv[1].get('stored_at', ''))[-MAX_ENTRIES:])
            self.data['holds'] = {k: v for k, v in self.data['holds'].items()
                if _stamp(v.get('first_seen_at')) and self.now - _stamp(v['first_seen_at']) < timedelta(hours=HOLD_HOURS)}
            try:
                _write(self.data)
            except OSError:
                self.cache_error = 'source_material_cache_write_failed'
        result = {'contract_version': CONTRACT_VERSION, 'observations': self.rows,
                  'cache_error': self.cache_error}
        self.snapshot['source_material'] = result
        return result


def attach_contracts(snapshot, rows):
    from agents.duplicate_pair_identity import article_id
    contracts = snapshot.setdefault('_active_source_contracts', {})
    for row in rows:
        contract = row.get('canonical_source_body')
        if source_body.valid_contract(contract):
            contracts[article_id(row)] = copy.deepcopy(contract)


def augment_board(board):
    """Retry feed-origin opportunities held before a final decision, within capture capacity."""
    from agents import menzo_policy_v93_15 as menzo
    from agents.menzo_priority_queue import _published_keys
    from agents.menzo_editorial_director_shadow import MAX_CANDIDATES
    result = copy.deepcopy(dict(board))
    try:
        holds = _read()['holds']
    except (OSError, ValueError):
        return result
    closed, published = menzo.terminal_skip_memory(), _published_keys()
    current = {key(r): r for r in result.get('news_candidates_for_menzo', []) if isinstance(r, dict)}
    now = datetime.now(timezone.utc)
    for url_key, hold in holds.items():
        if not hold['item'].get('candidate_id'):
            continue  # Published-history extraction failures are never feed opportunities.
        first = _stamp(hold.get('first_seen_at'))
        retry = _stamp(hold.get('retry_after'))
        if (url_key in current or url_key in closed or url_key in published or not first or
                now - first >= timedelta(hours=HOLD_HOURS) or (retry and retry > now)):
            continue
        if len(current) >= MAX_CANDIDATES:
            break
        current[url_key] = copy.deepcopy(hold['item'])
    result['news_candidates_for_menzo'] = list(current.values())
    return result


def input_profile(prompt):
    """Describe the exact supplied input, excluding article text and editorial guesses."""
    try:
        payload = json.loads(prompt.split('INPUT=', 1)[1])
    except (IndexError, ValueError):
        return {'coverage': 'unavailable', 'endpoints': [], 'prompt_bytes': len(prompt.encode())}
    endpoints = [profile(row) for table in ('candidates', 'history') for row in payload.get(table, [])]
    return {'coverage': 'full', 'endpoints': endpoints, 'prompt_bytes': len(prompt.encode()),
            'full_body_endpoints': sum(r['input_coverage'] == 'FULL_BODY' for r in endpoints),
            'body_unavailable_endpoints': sum(r['input_coverage'] != 'FULL_BODY' for r in endpoints)}
