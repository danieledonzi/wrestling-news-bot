"""Request-bound refs and owner-approved A+B selection without lost facts."""
import copy
import json

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_semantic_admission as admission
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_primary_classification_store as primary
from agents import menzo_soft_board as soft
from test_ed8_terminal_skip_semantic_admission import isolated_runtime, article, snapshot, classes, pool_article


def input_data(prompt):
    return json.loads(prompt.rsplit('INPUT=', 1)[1])


def election(count=2, old=2):
    value = {}
    admission.attach(value, [{'candidate_id': f'id{i}', **article(i), 'retained_body': 'Complete source body. ' * 20, 'input_coverage': 'FULL_BODY'} for i in range(count)],
        [{'article_id': f'hist{i}', **article(f'old{i}'), 'retained_body': 'Complete history body. ' * 20, 'input_coverage': 'FULL_BODY'} for i in range(old)],
        [{'candidate_id': f'id{i}', 'editorial_class': 'SHOULD_PUBLISH'} for i in range(count)])
    return value


def test_request_schema_enumerates_only_exact_current_and_history_refs():
    template = json.loads(active.ADMISSION_SCHEMA_PATH.read_text())
    before = copy.deepcopy(template)
    bound = admission.bound_schema(template, election(1, 12))
    refs = bound['properties']['suspected_duplicates']['items']['properties']
    assert refs['left_ref'] == {'type': 'string', 'enum': ['a0']}
    assert refs['right_ref']['enum'] == ['a0'] + [f'h{i}' for i in range(12)]
    assert 'c0' not in refs['right_ref']['enum'] and 'a1' not in refs['right_ref']['enum']
    assert template == before


@pytest.mark.parametrize('left,right', [('a9', 'h0'), ('c0', 'h0'), ('h0', 'a0'), ('a0', 'h9')])
def test_wrong_refs_remain_hold_and_retain_bounded_diagnostic(left, right):
    value = election(1, 2)
    raw = {'admission_complete': True, 'suspected_duplicates': [
        {'left_ref': left, 'right_ref': right, 'anchor_fact': 'The anchor reports the concrete development under test.', 'target_fact': 'The target reports the corresponding development under test.', 'basis': 'Suspicious factual overlap'}]}
    result, errors = admission.validate(raw, value, [], 300)
    assert result is None
    assert errors[0]['left_ref'] == left and errors[0]['right_ref'] == right
    assert errors[0]['candidate_count'] == 1 and errors[0]['history_count'] == 2
    assert active._technical_failures(errors) == errors


def test_primary_and_soft_use_bound_schema_without_a_second_attempt():
    for soft_phase in (False, True):
        value = election(2, 1)
        value['_semantic_admission_only'] = soft_phase
        calls = []
        def provider(prompt, schema, *_):
            calls.append(prompt)
            properties = schema['properties']['suspected_duplicates']['items']['properties']
            data = input_data(prompt)
            assert properties['left_ref']['enum'] == [data['anchor']['ref']]
            assert properties['right_ref']['enum'] == [r['ref'] for r in data['targets']]
            assert not any(k in prompt for k in ('editorial_class', 'story_core', 'relative_rank'))
            return {'admission_complete': True, 'suspected_duplicates': []}
        result = active._admit(value, provider)
        assert result['status'] == 'VALIDATED'
        # Source cards and pair decisions are reusable across primary and soft phases.
        assert len(calls) == (0 if soft_phase else 2)
        assert result['attempts'] == (0 if soft_phase else 7)


def update_provider(value, covering_index, calls, *, kinds=None, history_duplicate=False):
    def provider(prompt, schema, *_):
        calls.append(prompt)
        data = input_data(prompt)
        if 'suspected_duplicates' in schema['properties']:
            pairs = [{'left_ref': 'a0', 'right_ref': 'a1', 'anchor_fact': 'The anchor reports the concrete development under test.', 'target_fact': 'The target reports the corresponding development under test.', 'basis': 'Initial fact plus update'}]
            if history_duplicate:
                pairs.append({'left_ref': f'a{covering_index}', 'right_ref': 'h0', 'anchor_fact': 'The anchor reports the concrete development under test.', 'target_fact': 'The target reports the corresponding development under test.', 'basis': 'Published fact'})
            anchor = data['anchor']['ref']
            allowed = {r['ref'] for r in data['targets']}
            pairs = [r for r in pairs if r['left_ref'] == anchor and r['right_ref'] in allowed]
            return {'admission_complete': True, 'suspected_duplicates': pairs}
        if 'DUPLICATE GATE' in prompt:
            rel = data['authorized_relations'][0]
            if history_duplicate and rel['scope'] == 'recent_history':
                return {'relations': [{'ref': 'r0', 'decision': 'DUPLICATE'}]}
            side = ('left' if rel['left_ref'] == f'c{covering_index}' else 'right') if covering_index is not None else 'neither'
            rows = [{'ref': 'r0', 'decision': 'MATERIAL_UPDATE', 'covering_side': side,
                     'shared_fact': 'The original initial fact', 'new_fact': 'The later confirmed update'}]
            return {'relations': rows}
        return classes(kinds or ['SHOULD_PUBLISH'] * len(value['candidates']))
    return provider


@pytest.mark.parametrize('covering_index', [0, 1])
def test_complete_covering_article_is_only_survivor_in_either_direction(covering_index):
    rows = [article('a', 'Initial AEW announcement'), article('b', 'Updated AEW announcement')]
    rows[covering_index]['retained_body'] = 'Initial fact A is confirmed. Additional development B is confirmed. ' * 5
    rows[1-covering_index]['retained_body'] = 'Initial fact A is confirmed. ' * 10
    for row in rows:
        row['canonical_source_body'] = active.source_body.contract_from_elements(row['url'],
            [{'type': 'text', 'text': row['retained_body']}],
            {'extraction_finished': True, 'body_complete': True, 'clean_element_count': 1})
    value = snapshot(rows)
    active.source_material.attach_contracts(value, rows)
    ids = [r['candidate_id'] for r in value['candidates']]
    calls = []
    result = active.evaluate(value, provider=update_provider(value, covering_index, calls))
    assert result['status'] == 'VALIDATED' and len(calls) == 3
    assert [r['candidate_id'] for r in result['output']['candidates']] == [ids[covering_index]]
    survivor = value['candidates'][0]
    assert 'Initial fact A' in survivor['retained_body'] and 'Additional development B' in survivor['retained_body']
    assert len(menzo.terminal_skip_memory()) == 1
    assert all(r['editorial_class'] == 'SHOULD_PUBLISH' for r in primary.load().values())
    projected = active.project(value, result)
    assert len(projected['selected']) == len(projected['skipped']) == 1
    assert projected['skipped'][0]['reason'] == 'semantic_same_run_duplicate_covered_by_update'


def test_neither_body_contains_both_facts_keeps_both_without_stitching():
    value = snapshot([article('a'), article('b')])
    result = active.evaluate(value, provider=update_provider(value, None, []))
    assert result['status'] == 'VALIDATED' and len(result['output']['candidates']) == 2
    assert result['output']['relations'][0]['decision'] == 'NO_MATCH'
    assert not menzo.terminal_skip_memory()


def test_covering_soft_source_cannot_silently_demote_must_initial_fact():
    value = snapshot([article('a'), article('b')])
    result = active.evaluate(value, provider=update_provider(value, 1, [],
        kinds=['MUST_PUBLISH', 'PUBLISHABLE_SOFT']))
    assert result['status'] == 'VALIDATED' and len(result['output']['candidates']) == 2
    assert not menzo.terminal_skip_memory()
    assert {r['editorial_class'] for r in primary.load().values()} == {'MUST_PUBLISH', 'PUBLISHABLE_SOFT'}


def test_published_duplicate_of_covering_source_does_not_delete_initial_article():
    value = snapshot([article('a'), article('b')], history=[{**article('history'),
        'source_url': article('history')['url'], 'status': 'published'}])
    original_id = value['candidates'][0]['candidate_id']
    result = active.evaluate(value, provider=update_provider(value, 1, [], history_duplicate=True))
    assert result['status'] == 'VALIDATED'
    assert [r['candidate_id'] for r in result['output']['candidates']] == [original_id]
    assert len(menzo.terminal_skip_memory()) == 1


def test_recent_history_material_update_remains_publishable_without_consolidation():
    value = snapshot([article('new')], history=[{**article('old'), 'source_url': article('old')['url']}])
    def provider(prompt, schema, *_):
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'h0', 'anchor_fact': 'The anchor reports the concrete development under test.', 'target_fact': 'The target reports the corresponding development under test.', 'basis': 'Same developing fact'}]}
        if 'DUPLICATE GATE' in prompt:
            return {'relations': [{'ref': 'r0', 'decision': 'MATERIAL_UPDATE', 'covering_side': 'left'}]}
        return classes(['SHOULD_PUBLISH'])
    result = active.evaluate(value, provider=provider)
    assert result['status'] == 'VALIDATED' and len(result['output']['candidates']) == 1
    assert result['output']['relations'][0]['decision'] == 'MATERIAL_UPDATE'
    assert 'material_update_covering_id' not in result['output']['relations'][0]
    assert not menzo.terminal_skip_memory()


def test_softpool_uses_same_covering_body_rule_and_keeps_first_classes():
    rows = [pool_article('a'), pool_article('b')]
    calls = []
    def provider(prompt, schema, *_):
        calls.append(prompt)
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'anchor_fact': 'The anchor reports the concrete development under test.', 'target_fact': 'The target reports the corresponding development under test.', 'basis': 'Initial plus update'}]}
        rel = input_data(prompt)['authorized_relations'][0]
        side = 'left' if rel['left_ref'] == 'c1' else 'right'
        return {'relations': [{'ref': 'r0', 'decision': 'MATERIAL_UPDATE', 'covering_side': side}]}
    survivors, skipped, meta = soft._revalidate_pool_duplicates(rows, provider=provider)
    assert [r['url'] for r in survivors] == [rows[1]['url']]
    assert len(skipped) == 1 and len(calls) == 2
    assert survivors[0]['editorial_director']['editorial_class'] == 'PUBLISHABLE_SOFT'


def test_update_chains_keep_final_covering_source_but_cycles_keep_all():
    rows = [{'candidate_id': key, 'retained_body': 'Complete factual body', 'input_coverage': 'FULL_BODY'}
            for key in ('a', 'b', 'c')]
    decisions = [{'candidate_id': key, 'editorial_class': 'SHOULD_PUBLISH'} for key in ('a', 'b', 'c')]
    def relation(a, b):
        return {'decision': 'MATERIAL_UPDATE', 'scope': 'same_run', 'left_id': a, 'right_id': b,
                'material_update_covered_id': a, 'material_update_covering_id': b, 'pair_id': a+b}
    eliminated = active._covered_same_run_updates(rows, [relation('a','b'), relation('b','c')], decisions)
    assert {r['candidate_id'] for r in eliminated} == {'a', 'b'}
    assert {r['semantic_duplicate_of'] for r in eliminated} == {'c'}
    assert active._covered_same_run_updates(rows, [relation('a','b'), relation('b','a')], decisions) == []


def test_invalid_covering_direction_cannot_close_either_url_or_trigger_repair():
    value = snapshot([article('a'), article('b')])
    calls = []
    def provider(prompt, schema, *_):
        calls.append(prompt)
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'anchor_fact': 'The anchor reports the concrete development under test.', 'target_fact': 'The target reports the corresponding development under test.', 'basis': 'Initial plus update'}]}
        if 'DUPLICATE GATE' in prompt:
            return {'relations': [{'ref': 'r0', 'decision': 'MATERIAL_UPDATE', 'covering_side': 'both'}]}
        return classes(['SHOULD_PUBLISH', 'SHOULD_PUBLISH'])
    result = active.evaluate(value, provider=provider)
    assert result['status'] != 'VALIDATED' and len(calls) == 3
    assert any(e['family'] == 'material_update_covering_side' for e in result['validation_errors'])
    assert not menzo.terminal_skip_memory() and len(primary.load()) == 2


def test_dense_circular_update_graph_keeps_all_sources_with_bounded_traversal():
    keys = [f'node{i}' for i in range(16)]
    rows = [{'candidate_id': key, 'retained_body': 'Complete factual body', 'input_coverage': 'FULL_BODY'}
            for key in keys]
    decisions = [{'candidate_id': key, 'editorial_class': 'SHOULD_PUBLISH'} for key in keys]
    relations = [{'decision': 'MATERIAL_UPDATE', 'scope': 'same_run', 'left_id': a, 'right_id': b,
                  'material_update_covered_id': a, 'material_update_covering_id': b, 'pair_id': a+b}
                 for a in keys for b in keys if a != b]
    assert active._covered_same_run_updates(rows, relations, decisions) == []
