"""No target-to-target admission or unrelated article in an individual judgment."""
import json

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_semantic_admission as admission
from agents import menzo_source_material as material
from test_admission_binding_covered_updates import election
from test_ed2_editorial_director_active import snapshot, response, suspicious_relation
from test_ed9_independent_duplicate_contracts import offline


def data(prompt):
    return json.loads(prompt.rsplit('INPUT=', 1)[1])


def test_each_same_run_pair_is_offered_once_and_history_is_target_only():
    state = election(4, 3)
    payloads = admission.anchored_payloads(state)
    offered = [(p['anchor']['ref'], r['ref']) for p in payloads for r in p['targets']]
    expected = [(f'a{i}', f'a{j}') for i in range(4) for j in range(i + 1, 4)]
    expected += [(f'a{i}', f'h{j}') for i in range(4) for j in range(3)]
    assert set(offered) == set(expected) and len(offered) == len(expected)
    assert len(payloads) == 4  # Not one provider call per possible pair.
    assert not any(k in json.dumps(payloads) for k in ('editorial_class', 'story_core'))


def test_target_to_target_suspicion_is_rejected_even_with_valid_global_refs():
    state = election(2, 2)
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        # Both refs exist globally, but a1 is a target of this a0 request.
        return {'admission_complete': True, 'suspected_duplicates': [
            {'left_ref': 'a1', 'right_ref': 'h0', 'basis': 'Two targets share a development'}]}
    result = active._admit(state, provider)
    assert result['status'] != 'VALIDATED' and result['admitted_relations'] == []
    assert result['validation_errors'] == [
        {'family': 'semantic_admission_ref', 'detail': 'outside_anchor_request'}]
    assert len(calls) == 1 and 'REPAIR' not in calls[0]


def test_input_profile_counts_complete_anchor_and_targets_without_losing_tail():
    state = election(2, 1)
    for table in ('candidates', 'history'):
        for row in state['_semantic_admission'][table]:
            row.update(retained_body='Complete facts. ' * 2000 + 'FINAL_FACT', input_coverage='FULL_BODY')
    payload = admission.anchored_payloads(state)[0]
    profile = material.input_profile('INPUT=' + json.dumps(payload))
    assert profile['coverage'] == 'full'
    assert len(profile['endpoints']) == profile['full_body_endpoints'] == 3
    assert profile['body_unavailable_endpoints'] == 0
    assert all(r['retained_body'].endswith('FINAL_FACT') for r in [payload['anchor'], *payload['targets']])


def test_failed_first_pair_does_not_block_independent_final_judgment(offline):
    value = snapshot(3)
    value['publisher_history_12h'] = [
        {'article_id': f'history-{i}', 'source_url': f'https://history.test/{i}',
         'title': f'Old independent facts {i}'} for i in range(2)]
    value['authorized_relations'] = [
        suspicious_relation(value, left=0, right=0, scope='recent_history', pair_id='unavailable'),
        suspicious_relation(value, left=1, right=1, scope='recent_history', pair_id='decided')]
    independent_id = value['candidates'][2]['candidate_id']
    judged = []
    def provider(prompt, schema, *_):
        if 'DUPLICATE GATE PHASE ONLY' not in prompt:
            return response(value, ('SELECT',) * 3, prompt=prompt)
        payload = data(prompt)
        judged.append(payload)
        assert len(payload['candidates']) == len(payload['history']) == 1
        assert len(payload['authorized_relations']) == 1
        assert payload['authorized_relations'][0]['ref'] == 'r0'
        item = schema['properties']['relations']
        assert item['minItems'] == item['maxItems'] == 1
        assert item['items']['properties']['ref']['enum'] == ['r0']
        assert not any(k in prompt for k in ('editorial_class', 'story_core'))
        if (payload['history'][0].get('url') or payload['history'][0].get('source_url')).endswith('/0'):
            raise TimeoutError('only first pair unavailable')
        return {'relations': [{'ref': 'r0', 'decision': 'DUPLICATE'}]}
    result = active.evaluate(value, provider=provider)
    assert len(judged) == 2 and result['status'] == 'VALIDATED'
    assert result['duplicate_partial_clearance']
    assert [r['candidate_id'] for r in result['output']['candidates']] == [independent_id]
    assert len(value['semantic_duplicate_skips']) == len(value['source_material_holds']) == 1
    assert result['duplicate_pair_cache_entries_stored'] == 1
