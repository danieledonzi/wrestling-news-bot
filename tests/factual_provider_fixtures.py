"""Migrate historical fake providers without changing their tested editorial verdicts.

Old regression tests isolate primary classes/final duplicate authority using a
fake anchored admission provider. This adapter supplies the new two isolated card
operations and translates that fake's suspicions to explicit pair assessments.
It is test-only. New card/admission tests use the actual new contracts directly.
"""
import copy
import json

from agents import menzo_semantic_admission as legacy


def extraction(payload):
    return {'coverage_complete': True, 'article_kind': 'focused_news', 'context_tags': [],
            'quoted_speakers': [], 'facts': [{'statement': ' '.join(u['text'] for u in payload['source_units'])[:1000],
                'source_unit_ids': [payload['source_units'][0]['unit_id']],
                'central_subjects': [{'kind': 'person', 'name': 'Fixture Performer'}],
                'episode_family': 'promotion_arrival', 'development_tags': ['announcement'], 'specific_event_tags': []}]}


def enrichment(payload):
    return {'coverage_complete': True, 'identities': [{'subject_ref': s['subject_ref'],
            'canonical_name': s['source_name'], 'aliases': [s['source_name']], 'confidence': 'certain',
            'identity_basis': 'Explicit offline fixture identity.', 'source_unit_ids': ['u1']}
            for s in payload['subjects']], 'facts': [{'fact_ref': f['fact_ref'], 'episode_facets': ['promotion_arrival'],
            'development_tags': ['announcement'], 'episode_tags': [], 'source_unit_ids': f['source_unit_ids']}
            for f in payload['fixed_facts']]}


def adapt(call, prompt, schema, timeout, source_order, sources):
    payload = json.loads(prompt.split('INPUT=', 1)[1])
    properties = schema.get('properties', {})
    if 'source_units' in payload:
        url = payload['source_url']
        if url not in source_order: source_order.append(url)
        sources[url] = {**payload, 'retained_body': ' '.join(u['text'] for u in payload['source_units'])}
        return enrichment(payload) if 'identities' in properties else extraction(payload)
    if 'pair_assessments' not in properties:
        return call(prompt, schema, timeout)
    cards = {c['article_id']: c for c in payload['cards']}
    currents = sorted(payload['current_article_ids'], key=lambda i: source_order.index(cards[i]['source_url']))
    histories = sorted(payload['history_article_ids'], key=lambda i: source_order.index(cards[i]['source_url']))
    refs = {ident: ('a' if ident in currents else 'h') + str((currents if ident in currents else histories).index(ident))
            for ident in currents + histories}
    inverse = {v: k for k, v in refs.items()}
    def row(i):
        c = cards[i]
        return {'ref': refs[i], 'title': c['title'], 'url': c['source_url'],
                'retained_body': sources[c['source_url']]['retained_body'], 'input_coverage': 'FULL_BODY'}
    suspected = {}
    for anchor in currents:
        targets = []
        for pair in payload['permitted_pairs']:
            left, right = pair['left_article'], pair['right_article']
            if pair['scope'] == 'same_run':
                left, right = sorted([left, right], key=currents.index)
            if left == anchor and right not in targets: targets.append(right)
        if not targets: continue
        data = {'contract_version': legacy.VERSION, 'anchor': row(anchor), 'targets': [row(i) for i in targets]}
        template = json.loads(__import__('pathlib').Path(legacy.__file__).resolve().parents[1].joinpath(
            'config/editorial_duplicate_admission_schema_v1.json').read_text())
        p = template['properties']['suspected_duplicates']['items']['properties']
        p['left_ref'] = {'type': 'string', 'enum': [refs[anchor]]}
        p['right_ref'] = {'type': 'string', 'enum': [refs[t] for t in targets]}
        response = call(prompt.split('INPUT=', 1)[0] + 'INPUT=' + json.dumps(data), template, timeout)
        if not isinstance(response, dict) or response.get('admission_complete') is not True or not isinstance(response.get('suspected_duplicates'), list):
            return response
        for r in response['suspected_duplicates']:
            if (r.get('left_ref') not in inverse or r.get('right_ref') not in inverse or
                    inverse[r['left_ref']] == inverse[r['right_ref']]):
                return {'admission_complete': True, 'pair_assessments': []}
            suspected[frozenset([inverse[r['left_ref']], inverse[r['right_ref']]])] = r
    output = []
    for pair in payload['permitted_pairs']:
        left, right = pair['left_article'], pair['right_article']
        suspicion = suspected.get(frozenset([left, right]))
        output.append({'pair_id': pair['pair_id'], 'decision': 'ADMIT' if suspicion else 'NO_SUSPICION',
            'left_fact_refs': [cards[left]['facts'][0]['fact_id']] if suspicion else [],
            'right_fact_refs': [cards[right]['facts'][0]['fact_id']] if suspicion else [],
            'basis': suspicion.get('basis', '') if suspicion else 'No shared factual development in the offline fixture.'})
    return {'admission_complete': True, 'pair_assessments': output}
