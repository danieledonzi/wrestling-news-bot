"""First-class permanence, independent factual contracts and single-attempt recovery."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_primary_classification_store as primary
from agents import menzo_editorial_recovery as recovery
from agents import menzo_active_duplicate_pair_cache as cache
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_priority_queue as queue
from agents import menzo_soft_board as soft
from test_ed2_editorial_director_active import snapshot, response, suspicious_relation
from test_dr1_duplicate_body_revalidation import canonical_body

CLEAR = {'admission_complete': True, 'suspected_duplicates': []}


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    for name in ('SOFTPOOL_FILE', 'MENZO_DECISIONS_FILE', 'ARTIFACT_DECISIONS_FILE', 'V92_ALLOWED_URLS_FILE'):
        monkeypatch.setattr(menzo, name, tmp_path / (name + '.json'))
    monkeypatch.setattr(cache, 'CACHE_FILE', tmp_path / 'pairs.json')
    monkeypatch.setattr(active.source_body, 'hydrate', lambda _: (False, 'offline'))
    monkeypatch.setattr(menzo, 'load_authoritative_publisher_history', lambda *_: [])
    monkeypatch.setattr(active, 'record_gemini_attempt', lambda **_: None)


def payload(prompt):
    return json.loads(prompt.rsplit('INPUT=', 1)[1])


def soft_item(url, title='An informative wrestling production story'):
    return {'url': url, 'title': title, 'summary': 'Substantive first-hand production details',
            'soft_board_first_seen_at': '2026-10-10T10:00:00Z', 'soft_board_day': '2026-10-10',
            'soft_board_review_count': 0, 'editorial_director': {
                'policy_version': 'older-policy', 'editorial_class': 'PUBLISHABLE_SOFT',
                'recommended_action': 'DEFER', 'category': 'WWE', 'story_core': 'Production insight'}}


def test_valid_primary_row_is_saved_before_invalid_sibling_and_never_reclassified():
    first = snapshot(2)
    bad = response(first, ('DEFER', 'SELECT'))
    bad['candidates'][1].pop('story_core')
    calls = []
    result = active.evaluate(first, provider=lambda prompt, *_: calls.append(prompt) or bad)
    assert result['status'] != 'VALIDATED' and len(calls) == 1
    assert primary.load()[menzo.source_key('https://ed2.test/0')]['editorial_class'] == 'PUBLISHABLE_SOFT'
    later = snapshot(2)
    later['candidates'][0]['title'] = 'A title changed an hour later'
    def provider(prompt, schema, *_):
        calls.append(prompt)
        if 'suspected_duplicates' in schema['properties']:
            return CLEAR
        assert [r['url'] for r in payload(prompt)['candidates']] == ['https://ed2.test/1']
        return {'candidates': [{'ref': 'c0', 'editorial_class': 'SHOULD_PUBLISH',
            'recommended_action': 'SELECT', 'category': 'WWE', 'story_core': 'A valid fact'}]}
    result = active.evaluate(later, provider=provider)
    assert result['status'] == 'VALIDATED'
    assert {r['editorial_class'] for r in result['output']['candidates']} == {'PUBLISHABLE_SOFT', 'SHOULD_PUBLISH'}
    assert result['editorial_prefilter']['newly_classified'] == 1
    assert result['editorial_prefilter']['reused_primary_classes'] == 1


@pytest.mark.parametrize('action,cls', [('SELECT', 'MUST_PUBLISH'), ('DEFER', 'PUBLISHABLE_SOFT'), ('SKIP', 'SKIP')])
def test_first_class_survives_new_title_timestamp_policy_and_time(action, cls, monkeypatch):
    first = snapshot(1)
    assert active.evaluate(first, provider=lambda *_: response(first, (action,)))['status'] == 'VALIDATED'
    frozen = copy.deepcopy(primary.load())
    monkeypatch.setattr(active, 'POLICY_VERSION', 'future-policy')
    later = snapshot(1)
    later['observation_timestamp'] = '2027-01-01T00:00:00Z'
    later['candidates'][0].update(title='Completely changed title', published_at='2027-01-01T00:00:00Z')
    result = active.evaluate(later, provider=lambda *_: pytest.fail('already classified URL cannot call primary'))
    assert result['status'] == 'VALIDATED' and result['attempts'] == 0
    assert primary.load() == frozen
    if cls == 'SKIP':
        assert not later['candidates'] and later['terminal_policy_skips']
    else:
        assert result['output']['candidates'][0]['editorial_class'] == cls


def test_class_skip_removed_before_factual_election_and_judgment():
    value = snapshot(3)
    calls = []
    def provider(prompt, schema, *_):
        calls.append(prompt)
        if 'suspected_duplicates' in schema['properties']:
            data = payload(prompt)
            assert len(data['candidates']) == 2
            assert 'https://ed2.test/2' not in prompt
            assert not any(field in json.dumps(data) for field in ('editorial_class', 'fixed_class', 'story_core', 'relative_rank'))
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Same confirmed release'}]}
        if 'relations' in schema['properties']:
            data = payload(prompt)
            assert len(data['candidates']) == 2 and len(data['authorized_relations']) == 1
            assert not any(field in json.dumps(data) for field in ('editorial_class', 'story_core', 'admission_basis', 'relative_rank'))
            return {'relations': [{'ref': 'r0', 'decision': 'NO_MATCH'}]}
        return response(value, ('SELECT', 'DEFER', 'SKIP'))
    result = active.evaluate(value, provider=provider)
    assert result['status'] == 'VALIDATED' and len(calls) == 3
    assert not any('REPAIR' in prompt for prompt in calls)


def test_minimal_duplicate_is_terminal_before_projection_even_with_invalid_sibling():
    value = snapshot(3)
    value['authorized_relations'] = [suspicious_relation(value), suspicious_relation(value, right=2, pair_id='ac')]
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if 'DUPLICATE GATE' in prompt:
            return {'relations': [{'ref': 'r0', 'decision': 'DUPLICATE'}, {'ref': 'r1', 'decision': 'UNCERTAIN'}]}
        return response(value, ('SELECT', 'SELECT', 'SELECT'))
    result = active.evaluate(value, provider=provider)
    assert result['status'] != 'VALIDATED' and len(calls) == 3
    assert cache.load()['entries']['pair-ab']['final_relation']['decision'] == 'DUPLICATE'
    assert len(menzo.terminal_skip_memory()) == len(value['semantic_duplicate_skips']) == 1
    assert len(primary.load()) == 3


def test_bad_admission_is_one_attempt_backoff_and_exact_success_clearance_is_reused():
    value = snapshot(2)
    calls = []
    def bad_provider(prompt, schema, *_):
        calls.append(prompt)
        return {'admission_complete': False, 'suspected_duplicates': []} if 'suspected_duplicates' in schema['properties'] else response(value, ('SELECT', 'DEFER'))
    first = active.evaluate(value, provider=bad_provider)
    assert first['failure_stage'] == 'duplicate_admission' and first['attempts'] == 2
    assert first['validation_errors'][0]['family'] == 'semantic_admission_coverage' and first['retry_after']
    second = active.evaluate(snapshot(2), provider=lambda *_: pytest.fail('backoff must prevent repeated paid work'))
    assert second['status'] == 'TECHNICAL_HOLD' and second['attempts'] == 0
    assert not menzo.terminal_skip_memory()
    entries = json.loads(recovery.CACHE_FILE.read_text())
    for row in entries['entries'].values():
        row['retry_after'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    recovery.CACHE_FILE.write_text(json.dumps(entries))
    third = active.evaluate(snapshot(2), provider=lambda *_: CLEAR)
    assert third['status'] == 'VALIDATED' and third['attempts'] == 1
    fourth = active.evaluate(snapshot(2), provider=lambda *_: pytest.fail('unchanged valid election is cached'))
    assert fourth['status'] == 'VALIDATED' and fourth['attempts'] == 0
    assert len(primary.load()) == 2


def test_changed_admission_material_recovers_without_waiting_or_reclassification():
    value = snapshot(2)
    active.evaluate(value, provider=lambda prompt, schema, *_: {'admission_complete': False} if 'suspected_duplicates' in schema['properties'] else response(value, ('SELECT', 'SELECT')))
    changed = snapshot(2)
    changed['candidates'][0]['summary'] = 'New factual material in the same source URL'
    calls = []
    result = active.evaluate(changed, provider=lambda prompt, *_: calls.append(prompt) or CLEAR)
    assert result['status'] == 'VALIDATED' and len(calls) == 1
    assert result['editorial_prefilter']['newly_classified'] == 0


def test_corrupt_primary_store_holds_without_model_or_loss():
    primary.STORE_FILE.write_text('{corrupt')
    result = active.evaluate(snapshot(1), provider=lambda *_: pytest.fail('corrupt permanent class cannot be replaced'))
    assert result['status'] == 'TECHNICAL_HOLD' and result['attempts'] == 0
    assert primary.STORE_FILE.read_text() == '{corrupt'


def test_bootstrap_uses_earliest_retained_valid_class_over_later_queue_promotion():
    url = 'https://bootstrap.test/story'
    first = soft_item(url)
    promoted = copy.deepcopy(first)
    promoted['editorial_director'].update(editorial_class='SHOULD_PUBLISH', recommended_action='SELECT')
    records = []
    for when, item in [('2026-10-10T11:00:00Z', promoted), ('2026-10-10T10:00:00Z', first)]:
        records.append({'run': {'started_at': when}, 'editorial_pipeline': {'status': 'VALIDATED',
            'prefilter': {'policy_version': 'historical', 'candidates': [{**item['editorial_director'], 'url': url}]}}})
    primary.MASTER_LOG.write_text('\n'.join(json.dumps(row) for row in records))
    menzo.write_json(queue.queue_path(), {'items': [promoted]})
    assert primary.load()[menzo.source_key(url)]['editorial_class'] == 'PUBLISHABLE_SOFT'
    assert queue.augment_board({'news_candidates_for_menzo': []})['news_candidates_for_menzo'] == []
    assert primary.load()[menzo.source_key(url)]['classified_at'] == '2026-10-10T10:00:00Z'
    assert menzo.load_json(menzo.SOFTPOOL_FILE, {})['items'][0]['editorial_director']['editorial_class'] == 'PUBLISHABLE_SOFT'


def test_soft_admission_uses_own_schema_and_never_classifies_old_pool():
    rows = [soft_item('https://pool.test/a', 'WWE confirms a wrestler release'),
            soft_item('https://pool.test/b', 'AEW announces a new venue for Dynamite')]
    calls = []
    def provider(prompt, schema, *_):
        calls.append(prompt)
        assert set(schema['properties']) == {'admission_complete', 'suspected_duplicates'}
        assert all('editorial_class' not in row for row in payload(prompt)['candidates'])
        # Additional old classification-shaped rows cannot enter its dedicated validator.
        return {**CLEAR, 'candidates': [{'ref': 'c0', 'editorial_class': 'SHOULD_PUBLISH'}]}
    survivors, skipped, meta = soft._revalidate_pool_duplicates(rows, provider=provider)
    assert survivors and not skipped and meta['semantic_admission_status'] == 'VALIDATED'
    assert len(calls) == 1
    assert all(row['editorial_director']['editorial_class'] == 'PUBLISHABLE_SOFT' for row in survivors)


def test_partial_soft_skip_is_terminal_and_keeps_first_class_when_sibling_invalid(monkeypatch):
    rows = [soft_item('https://soft.test/a'), soft_item('https://soft.test/b')]
    menzo.write_json(menzo.SOFTPOOL_FILE, {'items': rows})
    primary.load()
    monkeypatch.setattr(soft, '_revalidate_pool_duplicates', lambda rows: (rows, [], {}))
    result = soft.apply({'selected': [], 'pending': [], 'skipped': []},
        {'observation_timestamp': '2026-10-10T12:00:00Z', 'remaining_slots': 20},
        provider=lambda *_: {'candidates': [{'ref': 's0', 'disposition': 'SOFT_SKIP', 'reason': 'Weak opportunity'},
                                          {'ref': 's1', 'disposition': 'INVALID', 'reason': 'Malformed'}]})
    assert len(result['skipped']) == 1 and len(result['pending']) == 1
    assert menzo.source_key(rows[0]['url']) in menzo.terminal_skip_memory()
    assert primary.load()[menzo.source_key(rows[0]['url'])]['editorial_class'] == 'PUBLISHABLE_SOFT'
    assert [row['url'] for row in menzo.load_json(menzo.SOFTPOOL_FILE, {})['items']] == [rows[1]['url']]


def test_soft_review_clock_change_does_not_bypass_technical_backoff():
    rows = [soft_item('https://review.test/a')]
    capacity = {'soft_capacity_this_run': 1}
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    result, first = soft._review(rows, {}, capacity, now, lambda *_: {'wrong': []})
    assert result is None and first['attempts'] == 1
    result, later = soft._review(rows, {}, capacity, now + timedelta(minutes=30),
        lambda *_: pytest.fail('wall clock/age cannot bypass identical technical failure backoff'))
    assert result is None and later['attempts'] == 0 and later['retry_after']


def test_recovery_cache_write_failure_cannot_revoke_a_valid_primary(monkeypatch):
    monkeypatch.setattr(recovery, 'record', lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('disk')))
    value = snapshot(1)
    result = active.evaluate(value, provider=lambda *_: response(value, ('SELECT',)))
    assert result['status'] == 'VALIDATED'
    assert primary.load()[menzo.source_key('https://ed2.test/0')]['editorial_class'] == 'MUST_PUBLISH'


def test_equal_richness_keeps_earliest_arrival_and_richer_later_article_wins():
    early = {'url': 'https://winner.test/a', 'title': 'A wrestler confirms a new contract', 'first_seen_at': '2026-10-10T10:00:00Z'}
    late = {**early, 'url': 'https://winner.test/z', 'first_seen_at': '2026-10-10T11:00:00Z'}
    winner, _ = menzo.canonical_richer_winner([late, early], earliest_arrival=True)
    assert winner['url'] == early['url']
    late['canonical_source_body'] = canonical_body('A wrestler confirms a new contract with extensive professional detail. ' * 20)
    winner, _ = menzo.canonical_richer_winner([early, late], earliest_arrival=True)
    assert winner['url'] == late['url']


def test_large_soft_duplicate_batches_preserve_valid_decisions_on_later_failure(monkeypatch):
    monkeypatch.setattr(shadow, 'MAX_RELATIONS', 1)
    rows = [soft_item('https://large.test/a', 'John Cena confirms a new contract'),
            soft_item('https://large.test/b', 'A new deal for John Cena is announced'),
            soft_item('https://large.test/c', 'Cena gives details about his new deal')]
    calls = []
    def provider(prompt, schema, *_):
        calls.append(prompt)
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Same contract announcement'},
                {'left_ref': 'a1', 'right_ref': 'a2', 'basis': 'The contract announcement'}]}
        if len(calls) == 2:
            return {'relations': [{'ref': 'r0', 'decision': 'DUPLICATE'}]}
        return {'relations': [{'ref': 'r0', 'decision': 'INVALID'}]}
    survivors, skipped, meta = soft._revalidate_pool_duplicates(rows, provider=provider)
    assert meta['semantic_admission_status'] == 'TECHNICAL_BLOCK'
    assert len(calls) == meta['gemini_duplicate_calls_executed'] == 3
    assert len(skipped) == len(menzo.terminal_skip_memory()) == 1
    assert {row['url'] for row in survivors}.isdisjoint({row['url'] for row in skipped})


def test_closed_url_projection_preserves_original_primary_class(monkeypatch):
    value = snapshot(1)
    active.evaluate(value, provider=lambda *_: response(value, ('DEFER',)))
    menzo.save_hard_skips({'skipped': [{'url': 'https://ed2.test/0', 'reason': 'soft_board_competition_skip', 'decision_authority': 'soft_board'}]})
    later = snapshot(1)
    result = active.evaluate(later, provider=lambda *_: pytest.fail('closed URL cannot call Gemini'))
    monkeypatch.setattr(soft, 'apply', lambda result, *_args, **_kwargs: {**result, 'allowed_urls_for_v92': []})
    projected = active.project(later, result)
    assert projected['skipped'][0]['editorial_director']['editorial_class'] == 'PUBLISHABLE_SOFT'
    assert projected['skipped'][0]['decision'] == 'skip'
