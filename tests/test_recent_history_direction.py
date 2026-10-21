"""Direction is explicit only for history; old in-run authority remains reusable."""
import copy
import json

import pytest

from agents import menzo_active_duplicate_pair_cache as cache
from agents import menzo_duplicate_history_direction as direction
from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from test_ed2_editorial_director_active import snapshot, suspicious_relation
from test_ed9_independent_duplicate_contracts import offline


def state():
    value = snapshot(3)
    value['publisher_history_12h'] = [
        {'article_id': f'published-{i}', 'source_url': f'https://history.test/{i}',
         'title': f'Already published fact {i}', 'retained_body': f'Published full body {i}. ' * 30,
         'input_coverage': 'FULL_BODY', 'published_at': '2026-10-21T10:00:00+00:00'}
        for i in range(2)]
    for i, row in enumerate(value['candidates']):
        row.update(retained_body=f'Current full body {i}. ' * 30, input_coverage='FULL_BODY',
                   published='Wed, 21 Oct 2026 11:00:00 +0000')
    value['authorized_relations'] = [
        suspicious_relation(value, pair_id='in-run'),
        suspicious_relation(value, left=2, right=1, scope='recent_history', pair_id='history')]
    value['_defer_duplicate_application'] = True
    active._finalize_active_input(value)
    return value


def contract():
    return cache.contract_fingerprint(policy_version=active.POLICY_VERSION, model=active.MODEL,
        policy_path=active.RELATION_POLICY_PATH, gate_schema_path=active.RELATION_SCHEMA_PATH,
        event_registry_path=active.EVENT_REGISTRY_PATH)


def materials(value):
    _, endpoints = active._duplicate_gate_endpoint_maps(value)
    _, refs = shadow.short_ref_maps(value)
    return {refs[ref]['pair_id']: cache.pair_material(refs[ref], rows, contract())
            for ref, rows in endpoints.items()}


@pytest.mark.parametrize('scope', ['same_run', 'empty'])
def test_nonhistory_prompt_is_byte_identical_to_released_prompt(scope):
    value = state()
    value['authorized_relations'] = value['authorized_relations'][:1] if scope == 'same_run' else []
    payload = active._duplicate_provider_input(value)
    previous = (active.RELATION_POLICY_PATH.read_text() +
        '\nDUPLICATE GATE PHASE ONLY. Return only JSON with relations. INPUT=' +
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    assert active._duplicate_prompt(value) == previous


def test_history_roles_use_exact_projected_aliases_and_keep_two_complete_bodies():
    value = state(); value['authorized_relations'] = value['authorized_relations'][1:]
    before = copy.deepcopy(value)
    prompt = active._duplicate_prompt(value)
    payload = json.loads(prompt.rsplit('INPUT=', 1)[1])
    relation = payload['authorized_relations'][0]
    assert relation['left_ref'] == 'c2' and relation['right_ref'] == 'h1'
    assert direction.INSTRUCTION_TEMPLATE.format(current='c2', published='h1') in prompt
    assert payload['candidates'][0]['retained_body'] == value['candidates'][2]['retained_body']
    assert payload['history'][0]['retained_body'] == value['publisher_history_12h'][1]['retained_body']
    assert len(payload['candidates']) == len(payload['history']) == 1
    assert payload == active._duplicate_provider_input(value) and value == before
    assert not any(field in prompt for field in ('editorial_class', 'story_core', 'relative_rank'))


def test_prompt_change_invalidates_only_history_exact_material(monkeypatch):
    value = state(); before = materials(value)
    monkeypatch.setattr(direction, 'INSTRUCTION_TEMPLATE', direction.INSTRUCTION_TEMPLATE + '\nChanged contract.')
    after = materials(value)
    assert before['in-run'] == after['in-run']
    assert before['history']['contract_fingerprint'] != after['history']['contract_fingerprint']
    for field in ('identity', 'endpoint_material_hash', 'relation_contract_hash'):
        assert before['history'][field] == after['history'][field]


def test_old_history_misses_once_while_old_same_run_and_new_history_are_reused(offline):
    value = state(); initial = materials(value); rows = []
    for material in initial.values():
        old = copy.deepcopy(material); old['contract_fingerprint'] = contract()
        final = {**old['identity'], 'decision': 'NO_MATCH', 'semantic_authority': 'gemini_final'}
        rows.append((old, final))
    cache.store(cache.empty(), rows)
    calls = []
    def provider(prompt, schema, *_):
        calls.append(prompt)
        payload = json.loads(prompt.rsplit('INPUT=', 1)[1])
        assert payload['authorized_relations'][0]['scope'] == 'recent_history'
        assert len(payload['authorized_relations']) == 1
        return {'relations': [{'ref': 'r0', 'decision': 'MATERIAL_UPDATE',
            'shared_fact': 'Shared A', 'new_fact': 'Current important B',
            'temporal_basis': 'CURRENT=c2; ALREADY_PUBLISHED=h1; new_fact_source=c2'}]}
    result = active._evaluate_duplicate_stage(value, provider=provider)
    assert result['status'] == 'VALIDATED' and result['attempts'] == 1
    assert result['duplicate_pair_cache_hits'] == result['duplicate_pair_cache_misses'] == 1
    assert len(calls) == 1
    repeat = active._evaluate_duplicate_stage(state(), provider=lambda *_: pytest.fail('both pairs must reuse'))
    assert repeat['status'] == 'VALIDATED' and repeat['attempts'] == 0
    assert repeat['duplicate_pair_cache_hits'] == 2
    assert [r['decision'] for r in repeat['output']['relations']] == ['NO_MATCH', 'MATERIAL_UPDATE']


def test_old_history_cannot_be_reintroduced_through_cached_admission(offline):
    value = state(); old_rows = []
    for material in materials(value).values():
        old = copy.deepcopy(material); old['contract_fingerprint'] = contract()
        final = {**old['identity'], 'decision': 'DUPLICATE', 'semantic_authority': 'gemini_final'}
        old_rows.append((old, final))
    cache.store(cache.empty(), old_rows)
    restored = []; active._preserve_cached_duplicate_admissions(value, restored)
    assert [r['pair_id'] for r in restored] == ['in-run']
    current = materials(value)['history']
    cache.store(cache.load(), [(current, {**current['identity'], 'decision': 'DUPLICATE',
                                        'semantic_authority': 'gemini_final'})])
    restored = []; active._preserve_cached_duplicate_admissions(value, restored)
    assert {r['pair_id'] for r in restored} == {'history', 'in-run'}


@pytest.mark.parametrize('decision', ['NO_MATCH', 'MATERIAL_UPDATE', 'DUPLICATE'])
def test_directional_explanation_is_not_a_local_semantic_veto(decision):
    value = state(); value['authorized_relations'] = value['authorized_relations'][1:]
    # Source attribution is an instruction to Gemini, never a second local judge.
    rows, errors, _ = active._validate_duplicate_gate({'relations': [
        {'ref': 'r0', 'decision': decision, 'shared_fact': 'A', 'new_fact': 'B'}]}, value)
    assert not errors and rows[0]['decision'] == decision
    assert rows[0]['semantic_authority'] == 'gemini_final'
