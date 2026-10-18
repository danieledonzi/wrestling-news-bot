"""Complete pair accounting over isolated cards, with conservative history election."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from agents import menzo_fact_cards as cards
from agents import menzo_source_material as material

POLICY_PATH = Path(__file__).resolve().parents[1] / 'docs/editorial-rules/OWTV_CARD_PAIR_ADMISSION_V1.md'
VERSION = 'isolated-card-complete-pair-admission-v1'
MAX_BATCH_PAIRS = 12
MAX_BATCH_BYTES = 80_000
BUSINESS = {'business_media_ownership', 'business_touring', 'industry_economics'}


def resolve_identities(values):
    """Share identity labels only. Factual statements are never combined or rewritten."""
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    for card in values:
        for fact in card['facts']:
            for s in fact['central_subjects']:
                labels = [s['kind'] + ':' + n for n in s['identity_labels']]
                for name in labels:
                    a, b = find(labels[0]), find(name)
                    if a != b:
                        parent[max(a, b)] = min(a, b)
    result = copy.deepcopy(values)
    for card in result:
        for fact in card['facts']:
            for s in fact['central_subjects']:
                s['canonical_entity_id'] = find(s['kind'] + ':' + s['identity_labels'][0])
    return result


def uncertain(card):
    return any(not f['central_subjects'] or
               any(s['identity_confidence'] != 'certain' for s in f['central_subjects']) or
               (f['episode_family'] == 'other' and not f['episode_facets'] and not f['retrieval_episode_tags'])
               for f in card['facts'])


def history_evidence(left, right):
    """A retrieval gate, never semantic authority. Insufficient tags stay reviewable."""
    if uncertain(left) or uncertain(right):
        return {'reason': 'uncertain_identity_or_episode', 'fact_pairs': []}
    evidence = []
    for a in left['facts']:
        for b in right['facts']:
            sa = {(s['kind'], s['canonical_entity_id']) for s in a['central_subjects']}
            sb = {(s['kind'], s['canonical_entity_id']) for s in b['central_subjects']}
            shared = sa & sb
            family = a['episode_family'] == b['episode_family'] and a['episode_family'] != 'other'
            facets = set(a['episode_facets']) & set(b['episode_facets'])
            episodes = set(a['retrieval_episode_tags']) & set(b['retrieval_episode_tags'])
            events = set(a['specific_event_tags']) & set(b['specific_event_tags'])
            business_episode = (a['episode_family'] in BUSINESS and b['episode_family'] in BUSINESS
                                and (family or episodes or events))
            subjects = [s for s in shared if s[0] in {'person', 'team'} or
                        (s[0] == 'organization' and business_episode)]
            if subjects and (family or facets or episodes or events):
                evidence.append({'left_fact': a['fact_id'], 'right_fact': b['fact_id'],
                                 'subjects': sorted(s[1] for s in subjects), 'facets': sorted(facets),
                                 'episode_family': a['episode_family'] if family else None,
                                 'episode_tags': sorted(episodes), 'event_tags': sorted(events)})
    return {'reason': 'shared_factual_retrieval_evidence', 'fact_pairs': evidence} if evidence else None


def projection(card):
    return {k: copy.deepcopy(card[k]) for k in ('article_id', 'title', 'source_url', 'article_kind',
             'context_tags', 'quoted_speakers', 'source_body_sha256', 'source_body_chars', 'card_sha256', 'facts')}


def payload_for(pairs, by_id):
    ids = list(dict.fromkeys(x for p in pairs for x in (p['left_article'], p['right_article'])))
    current = list(dict.fromkeys([p['left_article'] for p in pairs] +
                                [p['right_article'] for p in pairs if p['scope'] == 'same_run']))
    history = [x for x in ids if x not in current]
    return {'card_contract': cards.VERSION, 'current_article_ids': current, 'history_article_ids': history,
            'cards': [projection(by_id[i]) for i in ids],
            'permitted_history_by_current': {c: [p['right_article'] for p in pairs
                if p['left_article'] == c and p['scope'] == 'recent_history'] for c in current},
            'permitted_pairs': [{k: p[k] for k in ('pair_id', 'left_article', 'right_article', 'scope')} for p in pairs]}


def schema_for(pairs):
    return cards.obj({'admission_complete': {'type': 'boolean'}, 'pair_assessments': cards.array(cards.obj({
        'pair_id': {'type': 'string', 'enum': [p['pair_id'] for p in pairs]},
        'decision': {'type': 'string', 'enum': ['ADMIT', 'NO_SUSPICION']},
        'left_fact_refs': cards.array({'type': 'string'}), 'right_fact_refs': cards.array({'type': 'string'}),
        'basis': {'type': 'string', 'minLength': 1, 'maxLength': 1000}}))})


def validate(raw, pairs, by_id):
    """Return all independently valid rows; never turn a missing row into NO_SUSPICION."""
    expected = {p['pair_id']: p for p in pairs}
    failures, accepted = [], []
    if not isinstance(raw, dict) or set(raw) != {'admission_complete', 'pair_assessments'} or raw.get('admission_complete') is not True:
        return {'assessments': [], 'unresolved': list(expected)}, [
            {'family': 'card_pair_coverage', 'detail': 'explicit_complete_required'}], []
    rows = raw.get('pair_assessments')
    if not isinstance(rows, list) or len(rows) > 2 * len(pairs):
        return {'assessments': [], 'unresolved': list(expected)}, [
            {'family': 'card_pair_coverage', 'detail': 'bounded_assessment_array_required'}], []
    counts = {}
    for r in rows:
        if isinstance(r, dict) and isinstance(r.get('pair_id'), str):
            counts[r['pair_id']] = counts.get(r['pair_id'], 0) + 1
    unknown = any(not isinstance(r, dict) or not isinstance(r.get('pair_id'), str) or
                  r['pair_id'] not in expected for r in rows)
    if unknown:
        failures.append({'family': 'card_pair_binding', 'detail': 'unauthorized_pair'})
    for r in rows:
        if not isinstance(r, dict):
            continue
        pid = r.get('pair_id')
        if not isinstance(pid, str) or pid not in expected or counts[pid] != 1:
            continue
        p = expected[pid]
        error = None
        if set(r) != {'pair_id', 'decision', 'left_fact_refs', 'right_fact_refs', 'basis'} or r.get('decision') not in ('ADMIT', 'NO_SUSPICION'):
            error = 'invalid_assessment'
        elif not cards.text(r.get('basis'), 1000):
            error = 'bounded_basis_required'
        else:
            for side in ('left', 'right'):
                refs = r.get(side + '_fact_refs')
                owned = {f['fact_id'] for f in by_id[p[side + '_article']]['facts']}
                if (not isinstance(refs, list) or len(refs) > len(owned) or
                        any(not isinstance(x, str) or x not in owned for x in refs) or
                        (r['decision'] == 'ADMIT' and not refs)):
                    error = 'fact_ref_must_belong_to_exact_endpoint'
        if error:
            failures.append({'family': 'card_pair_binding', 'detail': error, 'ref': pid})
        else:
            accepted.append(copy.deepcopy(r))
    valid_ids = {r['pair_id'] for r in accepted}
    unresolved = [p for p in expected if p not in valid_ids]
    if unresolved:
        failures.append({'family': 'card_pair_coverage', 'detail': 'missing_or_invalid_pair', 'missing_refs': unresolved})
    return {'assessments': accepted, 'unresolved': unresolved}, failures, []


def execute(snapshot, call, run_once, *, model, max_input_bytes):
    from agents import menzo_semantic_admission as admission
    source = snapshot['_semantic_admission']
    current_ids = snapshot['_admission_candidate_ids']
    history_ids = snapshot['_admission_history_ids']
    fixed = snapshot.get('_admission_fixed_classes', {})
    if not any(fixed.get(ident) != 'SKIP' for ident in current_ids):
        # Closed current URLs never cause historical card/model work.
        source = {'candidates': [], 'history': []}
        current_ids, history_ids = [], []
    observations = uuid.uuid4().hex
    cache = cards.Cache()
    result = {'status': 'VALIDATED', 'attempts': 0, 'validation_attempts': [], 'validation_errors': [],
              'logical_request_ids': [], 'admitted_relations': [], 'held_candidate_ids': [],
              'admission_contract': VERSION, 'card_observations': [], 'pair_dispositions': []}
    def emit(kind, status, data):
        material.emit(kind, 'selection', status, {'admission_contract': VERSION,
                      'audit_observation_id': observations, **data}, model_role='card_pair_admission')
    emit('editorial_admission_cycle', 'started', {'current_count': len(current_ids), 'history_count': len(history_ids)})
    held = set()
    retry_times = []
    card_attempts, pair_attempts = 0, 0
    endpoints, obtained, id_to_card = {}, [], {}
    for ids, rows, is_current in ((current_ids, source['candidates'], True), (history_ids, source['history'], False)):
        for ident, row in zip(ids, rows):
            if is_current and fixed.get(ident) == 'SKIP':
                continue
            endpoint = {**copy.deepcopy(row), ('candidate_id' if is_current else 'article_id'): ident}
            endpoints[ident] = endpoint
            card, operation = cards.obtain(endpoint, cache, run_once, call, model, max_input_bytes=max_input_bytes)
            result['attempts'] += operation.get('attempts', 0)
            card_attempts += operation.get('attempts', 0)
            result['validation_attempts'] += operation.get('validation_attempts', [])
            result['logical_request_ids'] += operation.get('logical_request_ids', [])
            if operation.get('retry_after'):
                retry_times.append(operation['retry_after'])
            profile = {'endpoint_id': ident, 'url': row.get('url') or row.get('source_url'), 'scope': 'current' if is_current else 'history',
                       'status': 'READY' if card else 'TECHNICAL_HOLD',
                       'source_body_sha256': cards.digest(row['retained_body']) if row.get('retained_body') else None,
                       'card_id': card['article_id'] if card else None, 'card_sha256': card['card_sha256'] if card else None,
                       'fact_count': len(card['facts']) if card else None,
                       'article_kind': card['article_kind'] if card else None,
                       'extraction_cache_hit': operation.get('extraction_cache_hit', False),
                       'enrichment_cache_hit': operation.get('enrichment_cache_hit', False),
                       'reason': operation.get('fallback_reason')}
            result['card_observations'].append(profile)
            emit('editorial_card_observation', 'success' if card else 'pending', profile)
            if card:
                obtained.append(card); id_to_card[ident] = card['article_id']
            elif is_current:
                held.add(ident)
    resolved = resolve_identities(obtained)
    by_id = {c['article_id']: c for c in resolved}
    pair_rows = []
    eligible = [i for i in current_ids if fixed.get(i) != 'SKIP']
    for index, left in enumerate(eligible):
        for right in eligible[index + 1:]:
            a, b = sorted((left, right))
            pair_rows.append(admission.make_relation('same_run', a, b, 'Card pair admission'))
        for right in history_ids:
            pair_rows.append(admission.make_relation('recent_history', left, right, 'Card pair admission'))
    permitted = []
    def disposition(pair, decision, reason, **extra):
        record = {k: pair[k] for k in ('pair_id', 'scope', 'left_id', 'right_id')}
        record.update(decision=decision, reason=reason,
                      left_url=endpoints[pair['left_id']].get('url') or endpoints[pair['left_id']].get('source_url'),
                      right_url=endpoints[pair['right_id']].get('url') or endpoints[pair['right_id']].get('source_url'), **extra)
        for side in ('left', 'right'):
            card_id = id_to_card.get(pair[side + '_id'])
            record.setdefault(side + '_card_sha256', by_id[card_id]['card_sha256'] if card_id else None)
        result['pair_dispositions'].append(record)
        emit('editorial_pair_disposition', 'pending' if decision == 'TECHNICAL_HOLD' else 'success', record)
    for p in pair_rows:
        if p['left_id'] not in id_to_card or p['right_id'] not in id_to_card:
            if p['scope'] == 'recent_history' and p['right_id'] not in id_to_card:
                held.add(p['left_id'])  # Unknown published material is not evidence of distinction.
            disposition(p, 'TECHNICAL_HOLD', 'endpoint_card_unavailable')
            continue
        p['left_article'], p['right_article'] = id_to_card[p['left_id']], id_to_card[p['right_id']]
        evidence = history_evidence(by_id[p['left_article']], by_id[p['right_article']]) if p['scope'] == 'recent_history' else {'reason': 'same_run_pair', 'fact_pairs': []}
        if evidence is None:
            disposition(p, 'EXCLUDED_HISTORY', 'no_shared_central_identity_and_episode',
                        left_card_sha256=by_id[p['left_article']]['card_sha256'],
                        right_card_sha256=by_id[p['right_article']]['card_sha256'])
        else:
            p['retrieval_evidence'] = evidence
            permitted.append(p)
    policy = POLICY_PATH.read_text()
    def cache_key(pair):
        return cards.digest({'stage': VERSION, 'policy': cards.digest(policy), 'model': model,
                             'schema': schema_for([pair]), 'pair': {k: pair[k] for k in ('pair_id', 'scope', 'left_id', 'right_id')},
                             'left_card_sha256': by_id[pair['left_article']]['card_sha256'],
                             'right_card_sha256': by_id[pair['right_article']]['card_sha256']})
    pending, decisions = [], []
    for p in permitted:
        cached = cache.get(cache_key(p))
        if cached is not None:
            parsed, errors, _ = validate({'admission_complete': True, 'pair_assessments': [cached]}, [p], by_id)
            if errors:
                held.add(p['left_id'])
                if p['scope'] == 'same_run': held.add(p['right_id'])
                disposition(p, 'TECHNICAL_HOLD', 'invalid_cached_pair_assessment')
                continue
            decisions.append((p, parsed['assessments'][0], True))
        else:
            pending.append(p)
    batches, batch = [], []
    def prompt_for(pairs):
        return policy + '\nReturn only JSON. INPUT=' + json.dumps(payload_for(pairs, by_id), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    limit = min(MAX_BATCH_BYTES, max_input_bytes)
    for p in pending:
        if batch and (len(batch) >= MAX_BATCH_PAIRS or len(prompt_for(batch + [p]).encode()) > limit):
            batches.append(batch); batch = []
        if len(prompt_for([p]).encode()) > limit:
            held.add(p['left_id'])
            if p['scope'] == 'same_run': held.add(p['right_id'])
            disposition(p, 'TECHNICAL_HOLD', 'single_card_pair_input_limit')
        else:
            batch.append(p)
    if batch: batches.append(batch)
    phase = 'editorial_soft_duplicate_admission' if snapshot.get('_semantic_admission_only') else 'editorial_duplicate_admission'
    for batch in batches:
        current = list(dict.fromkeys([p['left_id'] for p in batch] +
                                    [p['right_id'] for p in batch if p['scope'] == 'same_run']))
        history = list(dict.fromkeys(p['right_id'] for p in batch if p['scope'] == 'recent_history'))
        part = {'_admission_candidate_ids': current, '_admission_history_ids': history,
                '_provider_candidate_count': len(current), '_provider_relation_count': len(batch)}
        operation = run_once(part, call, prompt_for(batch), schema_for(batch), phase, POLICY_PATH,
                             lambda raw: validate(raw, batch, by_id), cache_success=True, policy_version=VERSION)
        result['attempts'] += operation.get('attempts', 0)
        pair_attempts += operation.get('attempts', 0)
        result['validation_attempts'] += operation.get('validation_attempts', [])
        result['validation_errors'] += operation.get('validation_errors', [])
        result['logical_request_ids'] += operation.get('logical_request_ids', [operation.get('logical_request_id')])
        if operation.get('retry_after'):
            retry_times.append(operation['retry_after'])
        parsed = operation.get('output') or {'assessments': [], 'unresolved': [p['pair_id'] for p in batch]}
        accepted = {r['pair_id']: r for r in parsed['assessments']}
        for p in batch:
            if p['pair_id'] in accepted:
                row = accepted[p['pair_id']]
                try:
                    cache.put(cache_key(p), row)
                except (OSError, ValueError):
                    row = None
                if row is not None:
                    decisions.append((p, row, False)); continue
            held.add(p['left_id'])
            if p['scope'] == 'same_run': held.add(p['right_id'])
            disposition(p, 'TECHNICAL_HOLD', 'pair_assessment_missing_or_invalid')
    for p, row, cached in decisions:
        disposition(p, row['decision'], row['basis'], cache_hit=cached,
                    left_fact_refs=row['left_fact_refs'], right_fact_refs=row['right_fact_refs'],
                    retrieval_reason=p['retrieval_evidence']['reason'])
        if row['decision'] == 'ADMIT':
            relation = admission.make_relation(p['scope'], p['left_id'], p['right_id'], row['basis'])
            relation['admission_version'] = VERSION
            relation['admission_evidence'] = {'anchor_id': p['left_id'], 'target_id': p['right_id'],
                'left_fact_refs': row['left_fact_refs'], 'right_fact_refs': row['right_fact_refs'],
                'anchor_fact': ' '.join(f['statement'] for f in by_id[p['left_article']]['facts'] if f['fact_id'] in row['left_fact_refs']),
                'target_fact': ' '.join(f['statement'] for f in by_id[p['right_article']]['facts'] if f['fact_id'] in row['right_fact_refs'])}
            result['admitted_relations'].append(relation)
    # Only suspected same-run connections propagate a technical hold, as in the final gate.
    changed = True
    while changed:
        previous = len(held)
        for r in result['admitted_relations']:
            if r['scope'] == 'same_run' and held.intersection({r['left_id'], r['right_id']}):
                held.update((r['left_id'], r['right_id']))
        changed = len(held) != previous
    if held and not any(i not in held for i in eligible):
        result['status'] = 'TECHNICAL_HOLD'
        result['fallback_reason'] = 'factual_admission_incomplete'
    result['held_candidate_ids'] = sorted(held)
    if retry_times:
        result['retry_after'] = min(retry_times)
    result['admitted_relations'] = [r for r in result['admitted_relations'] if r['left_id'] not in held and
                                    not (r['scope'] == 'same_run' and r['right_id'] in held)]
    result['output'] = copy.deepcopy(result['admitted_relations'])
    result['admission_summary'] = {'current_count': len(eligible), 'history_count': len(history_ids),
        'card_observations': len(result['card_observations']), 'pair_universe': len(pair_rows),
        'history_excluded': sum(r['decision'] == 'EXCLUDED_HISTORY' for r in result['pair_dispositions']),
        'pairs_offered': len(permitted), 'pair_decisions': sum(r['decision'] in {'ADMIT', 'NO_SUSPICION'} for r in result['pair_dispositions']),
        'pair_holds': sum(r['decision'] == 'TECHNICAL_HOLD' for r in result['pair_dispositions']),
        'held_candidates': len(held), 'batches': len(batches), 'provider_attempts': result['attempts'],
        'card_provider_attempts': card_attempts, 'pair_provider_attempts': pair_attempts}
    emit('editorial_admission_cycle', 'pending' if held else 'success', result['admission_summary'])
    return result
