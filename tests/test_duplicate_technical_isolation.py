"""Technical duplicate failures retain only unresolved suspicious components."""
import copy

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_primary_classification_store as primary
from test_ed2_editorial_director_active import snapshot, response, suspicious_relation
from test_ed9_independent_duplicate_contracts import offline


def provider_for(value, verdicts, calls):
    def provider(prompt, schema, *_):
        calls.append(prompt)
        if 'DUPLICATE GATE PHASE ONLY' in prompt:
            if isinstance(verdicts, Exception):
                raise verdicts
            return {'relations': copy.deepcopy(verdicts)}
        return response(value, ('SELECT',) * len(value['candidates']), prompt=prompt)
    return provider


def test_same_run_material_update_is_final_nonduplicate_and_reused():
    value = snapshot(2)
    value['authorized_relations'] = [suspicious_relation(value)]
    calls = []
    verdicts = [{'ref': 'r0', 'decision': 'MATERIAL_UPDATE', 'new_fact': 'A substantive additional fact'}]
    result = active.evaluate(value, provider=provider_for(value, verdicts, calls))
    assert result['status'] == 'VALIDATED' and len(result['output']['candidates']) == 2
    assert result['output']['relations'][0]['decision'] == 'NO_MATCH'
    assert result['output']['relations'][0]['provider_decision'] == 'MATERIAL_UPDATE'
    assert len(calls) == 3 and not menzo.terminal_skip_memory()
    later = snapshot(2)
    later['authorized_relations'] = [suspicious_relation(later)]
    result = active.evaluate(later, provider=lambda *_: pytest.fail('final material must be reused'))
    assert result['status'] == 'VALIDATED' and result['attempts'] == 0


@pytest.mark.parametrize('verdicts', [[], [{'ref': 'r0', 'decision': 'INVALID'}], TimeoutError('offline')])
def test_unrelated_hard_news_proceeds_while_suspicious_pair_is_held(verdicts):
    value = snapshot(3)
    value['authorized_relations'] = [suspicious_relation(value)]
    ids = [row['candidate_id'] for row in value['candidates']]
    calls = []
    result = active.evaluate(value, provider=provider_for(value, verdicts, calls))
    assert result['status'] == 'VALIDATED' and result['duplicate_partial_clearance']
    assert [row['candidate_id'] for row in result['output']['candidates']] == ids[2:]
    assert {row['candidate_id'] for row in value['source_material_holds']} == set(ids[:2])
    assert result['editorial_prefilter']['duplicate_technical_hold_count'] == 2
    assert len(calls) == 4 and not menzo.terminal_skip_memory()
    frozen = copy.deepcopy(primary.load())
    projected = active.project(value, result)
    assert len(projected['selected']) == 1 and len(projected['pending']) == 2
    assert not projected['skipped']
    assert {row['decision_authority'] for row in projected['pending']} == {'duplicate_technical_hold'}
    assert all(row['editorial_director']['editorial_class'] == 'MUST_PUBLISH'
               for row in projected['selected'] + projected['pending'])
    assert primary.load() == frozen


def test_all_suspicious_candidates_stay_failed_and_nonterminal():
    value = snapshot(2)
    value['authorized_relations'] = [suspicious_relation(value)]
    result = active.evaluate(value, provider=provider_for(value, [], []))
    assert result['status'] != 'VALIDATED'
    assert len(value['source_material_holds']) == 2
    assert not menzo.terminal_skip_memory()


def test_incomplete_admission_cannot_clear_any_candidate():
    value = snapshot(3)
    calls = []
    def provider(prompt, schema, *_):
        calls.append(prompt)
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a99', 'right_ref': 'a0', 'anchor_fact': 'The anchor reports the concrete development under test.', 'target_fact': 'The target reports the corresponding development under test.', 'basis': 'Invalid reference'}]}
        return response(value, ('SELECT', 'SELECT', 'SELECT'), prompt=prompt)
    result = active.evaluate(value, provider=provider)
    assert result['status'] != 'VALIDATED' and result['failure_stage'] == 'duplicate_admission'
    assert len(calls) == 2 and not menzo.terminal_skip_memory()


def test_unchanged_failed_pair_waits_without_reclassification_or_paid_retry():
    first = snapshot(3)
    first['authorized_relations'] = [suspicious_relation(first)]
    assert active.evaluate(first, provider=provider_for(first, [], []))['duplicate_partial_clearance']
    frozen = copy.deepcopy(primary.load())
    later = snapshot(3)
    later['authorized_relations'] = [suspicious_relation(later)]
    result = active.evaluate(later, provider=lambda *_: pytest.fail('unchanged failed operation must wait'))
    assert result['status'] == 'VALIDATED' and result['attempts'] == 0
    assert result['duplicate_technical_failure']['status'] == 'TECHNICAL_HOLD'
    assert len(result['output']['candidates']) == 1
    assert len(later['source_material_holds']) == 2
    assert primary.load() == frozen and not menzo.terminal_skip_memory()


def test_unresolved_relation_holds_its_connected_component_only():
    value = snapshot(3)
    fourth = copy.deepcopy(value['candidates'][2])
    fourth.update(candidate_id='independent-fourth', url='https://ed2.test/3', title='Independent announcement')
    value['candidates'].append(fourth)
    value['authorized_relations'] = [suspicious_relation(value),
        suspicious_relation(value, left=1, right=2, pair_id='bc')]
    result = active.evaluate(value, provider=provider_for(value, [{'ref': 'r1', 'decision': 'NO_MATCH'}], []))
    assert result['status'] == 'VALIDATED'
    assert [row['candidate_id'] for row in result['output']['candidates']] == ['independent-fourth']
    assert len(value['source_material_holds']) == 3
    assert not menzo.terminal_skip_memory()


def test_valid_duplicate_remains_terminal_when_independent_article_proceeds():
    value = snapshot(3)
    fourth = copy.deepcopy(value['candidates'][2])
    fourth.update(candidate_id='independent-fourth', url='https://ed2.test/3', title='Independent announcement')
    value['candidates'].append(fourth)
    value['authorized_relations'] = [suspicious_relation(value),
        suspicious_relation(value, left=1, right=2, pair_id='bc')]
    gates = iter(['DUPLICATE', 'INVALID'])
    def provider(prompt, schema, *_):
        if 'DUPLICATE GATE PHASE ONLY' in prompt:
            return {'relations': [{'ref': 'r0', 'decision': next(gates)}]}
        return response(value, ('SELECT',) * 4, prompt=prompt)
    result = active.evaluate(value, provider=provider)
    assert result['status'] == 'VALIDATED'
    assert [row['candidate_id'] for row in result['output']['candidates']] == ['independent-fourth']
    assert len(value['semantic_duplicate_skips']) == len(menzo.terminal_skip_memory()) == 1
    assert len(value['source_material_holds']) == 2
    assert all(row['editorial_class'] == 'MUST_PUBLISH' for row in primary.load().values())
