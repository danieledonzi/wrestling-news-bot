"""Owner regressions: permanent URL finality and meaning-based sparse admission."""
import json

import pytest

from agents import massy_policy_v93_24 as massy
from agents import menzo_active_duplicate_pair_cache as cache
from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_priority_queue as queue
from agents import menzo_semantic_admission as admission
from agents import menzo_soft_board as soft


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    for name in ('SOFTPOOL_FILE', 'MENZO_DECISIONS_FILE', 'ARTIFACT_DECISIONS_FILE', 'V92_ALLOWED_URLS_FILE'):
        monkeypatch.setattr(menzo, name, tmp_path / (name + '.json'))
    monkeypatch.setattr(cache, 'CACHE_FILE', tmp_path / 'pairs.json')
    monkeypatch.setattr(active, 'record_gemini_attempt', lambda **_: None)
    monkeypatch.setattr(soft, 'record_gemini_attempt', lambda **_: None)
    monkeypatch.setattr(active.source_body, 'hydrate', lambda _: (False, 'offline_fixture'))
    monkeypatch.setattr(menzo, 'load_authoritative_publisher_history', lambda hours=12: [])
    monkeypatch.setattr(queue, '_published_keys', lambda: set())
    monkeypatch.setattr('agents.bob.dynamic_article_capacity', lambda *_: (5, 'test'))


def article(i, title=None):
    return {'url': f'https://ed8.test/{i}', 'title': title or f'Wrestling factual story {i}',
            'summary': f'Concrete factual detail {i}'}


def snapshot(rows, history=()):
    return shadow.capture_opportunity({'news_candidates_for_menzo': rows}, run_id='ed8',
        observation_timestamp='2026-10-10T08:00:00Z', history=list(history), defer_relation_build=True)


def classes(values, suspects=()):
    return {'candidates': [{'ref': f'c{i}', 'editorial_class': value,
            'recommended_action': {'SKIP': 'SKIP', 'PUBLISHABLE_SOFT': 'DEFER'}.get(value, 'SELECT'),
            'category': 'WWE', 'story_core': f'Concrete central development {i}'}
            for i, value in enumerate(values)], 'relations': [],
            'admission_complete': True, 'suspected_duplicates': list(suspects)}


def pool_article(i):
    return {**article(i), 'decision_authority': 'editorial_director',
        'soft_board_day': '2026-10-10', 'soft_board_first_seen_at': '2026-10-10T07:00:00Z',
        'editorial_director': {'policy_version': active.POLICY_VERSION,
            'editorial_class': 'PUBLISHABLE_SOFT', 'recommended_action': 'DEFER',
            'category': 'WWE', 'story_core': f'Substantial professional explanation {i}'}}


@pytest.mark.parametrize('title', [
    'WWE Money in the Bank Betting Odds Released',
    'Latest bookmaker odds for WWE Money in the Bank',
    'Quote dei bookmaker per Money in the Bank',
    'WWE Money in the Bank Odds Reveal Favorites',
])
def test_odds_close_before_any_provider_call(title):
    row = article('odds', title)
    value = snapshot([row])
    result = active.evaluate(value, provider=lambda *_: pytest.fail('odds must not call Gemini'))
    assert result['status'] == 'VALIDATED' and result['output']['candidates'] == []
    assert menzo.source_key(row['url']) in menzo.terminal_skip_memory()
    assert len(active.project(value, result)['skipped']) == 1


@pytest.mark.parametrize('title', [
    'WWE wrestler beats the odds to win the championship',
    'WWE announces partnership with a bookmaker',
    'Investigators probe leaked WWE betting odds',
    'Money in the Bank Final Card Confirmed',
])
def test_incidental_odds_and_distinct_facts_keep_gemini_classification(title):
    assert not menzo.is_bookmaker_odds_news(article('fact', title))


def test_legacy_skip_is_permanent_and_never_enters_either_endpoint_table():
    old = article('closed')
    menzo.write_json(menzo.HARD_SKIP_FILE, {'items': [{**old, 'reason': 'soft_board_competition_loss',
        'added_at': '2020-01-01T00:00:00Z', 'expires_after_hours': 168}]})
    assert menzo.source_key(old['url']) in massy.menzo_skip_memory()
    changed = {**old, 'title': 'Updated title after six years'}
    value = snapshot([changed, article('fresh')], [{**old, 'source_url': old['url'], 'status': 'published'}])
    prompts = []
    result = active.evaluate(value, provider=lambda prompt, *_: prompts.append(prompt) or classes(['SHOULD_PUBLISH']))
    assert result['status'] == 'VALIDATED' and len(prompts) == 1
    assert old['url'] not in prompts[0] and 'Updated title' not in prompts[0]
    assert value['publisher_history_12h'] == []
    menzo.save_hard_skips({'skipped': []})
    assert menzo.source_key(old['url']) in menzo.terminal_skip_memory()


def test_many_skips_cannot_generate_fresh_comparisons():
    old = [article(f'skip-{i}') for i in range(86)]
    menzo.save_hard_skips({'skipped': [{**row, 'reason': 'soft_board_competition_loss',
                         'decision_authority': 'soft_board'} for row in old]})
    value = snapshot([article('card', 'Money in the Bank Final Card Confirmed')], [
        {**row, 'source_url': row['url'], 'history_state': 'soft_tombstone'} for row in old])
    calls = []
    result = active.evaluate(value, provider=lambda prompt, *_: calls.append(prompt) or classes(['SHOULD_PUBLISH']))
    assert result['status'] == 'VALIDATED' and len(calls) == 1
    assert result['editorial_prefilter']['duplicate_relations'] == 0
    assert 'skip-85' not in calls[0]


def test_shared_wwe_final_match_words_do_not_admit_a_pair(monkeypatch):
    rows = [article('card', 'WWE Money in the Bank Final Match Card Confirmed'),
            article('west', 'Veronica West Says October 7 WWE EVOLVE Match Was Her Final Appearance')]
    monkeypatch.setattr(shadow, 'build_authorized_relations', lambda *_args, **_kwargs:
                        pytest.fail('lexical scorer cannot authorize semantic comparisons'))
    prompts = []
    result = active.evaluate(snapshot(rows), provider=lambda prompt, *_:
        prompts.append(prompt) or classes(['SHOULD_PUBLISH', 'SHOULD_PUBLISH']))
    assert result['status'] == 'VALIDATED' and len(prompts) == 2
    assert result['editorial_prefilter']['duplicate_relations'] == 0


def test_valid_skip_survives_admission_failure_and_is_absent_from_repair():
    rows = [article('skip'), article('keep-a'), article('keep-b')]
    responses = [classes(['SKIP', 'SHOULD_PUBLISH', 'SHOULD_PUBLISH']), {'candidates': [], 'relations': []}]
    responses[0]['admission_complete'] = False
    prompts = []
    result = active.evaluate(snapshot(rows), provider=lambda prompt, *_:
        prompts.append(prompt) or responses.pop(0))
    assert result['status'] != 'VALIDATED' and len(prompts) == 2
    assert rows[0]['url'] not in prompts[1] and rows[0]['title'] not in prompts[1]
    assert menzo.source_key(rows[0]['url']) in menzo.terminal_skip_memory()
    assert menzo.source_key(rows[1]['url']) not in menzo.terminal_skip_memory()


def test_new_skip_overrides_carried_current_soft_and_blocks_queue():
    row = pool_article('carried')
    menzo.write_json(menzo.SOFTPOOL_FILE, {'items': [row]})
    skipped = {**row, '_soft_board_existing': True, 'decision': 'skip',
        'editorial_director': {**row['editorial_director'], 'editorial_class': 'SKIP', 'recommended_action': 'SKIP'}}
    projected = soft.apply({'selected': [], 'pending': [], 'skipped': [skipped]},
        {'observation_timestamp': '2026-10-10T08:00:00Z', 'remaining_slots': 30})
    assert projected['pending'] == [] and menzo.load_json(menzo.SOFTPOOL_FILE, {})['items'] == []
    assert menzo.source_key(row['url']) in menzo.terminal_skip_memory()
    queue._write([{**row, 'editorial_director': {**row['editorial_director'], 'editorial_class': 'SHOULD_PUBLISH'}}])
    assert queue.augment_board({'news_candidates_for_menzo': [row]})['news_candidates_for_menzo'] == []


def test_soft_admission_failure_holds_pool_without_terminal_memory(monkeypatch):
    rows = [pool_article('a'), pool_article('b')]
    menzo.write_json(menzo.SOFTPOOL_FILE, {'items': rows})
    def unavailable(*_):
        raise TimeoutError('provider unavailable')
    monkeypatch.setattr(shadow, '_default_provider_factory', lambda: unavailable)
    result = soft.apply({'selected': [], 'pending': [], 'skipped': []},
        {'observation_timestamp': '2026-10-10T12:00:00Z', 'remaining_slots': 30},
        provider=lambda *_: pytest.fail('uncleared pool cannot compete'))
    assert len(result['pending']) == 2 and result['skipped'] == []
    assert result['postprocess']['soft_board_status'] == 'WAIT_DUPLICATE_CLEARANCE'
    assert menzo.terminal_skip_memory() == {}


def test_unchanged_pool_reuses_clearance_without_another_call():
    calls = []
    first, skipped, meta = soft._revalidate_pool_duplicates([pool_article('a'), pool_article('b')],
        provider=lambda prompt, *_: calls.append(prompt) or classes([]))
    assert len(first) == 2 and not skipped and len(calls) == 1
    second, skipped, meta = soft._revalidate_pool_duplicates(first,
        provider=lambda *_: pytest.fail('unchanged cleared pool must not call Gemini again'))
    assert len(second) == 2 and not skipped and meta['semantic_admission_status'] == 'UNCHANGED_CLEARANCE'


def test_soft_skip_survives_later_pool_write_failure(monkeypatch):
    row = pool_article('skip-before-write')
    menzo.write_json(menzo.SOFTPOOL_FILE, {'items': [row]})
    monkeypatch.setattr(soft, '_write_pool', lambda *_: (_ for _ in ()).throw(OSError('pool write failed')))
    with pytest.raises(OSError, match='pool write failed'):
        soft.apply({'selected': [], 'pending': [], 'skipped': []},
            {'observation_timestamp': '2026-10-10T12:00:00Z', 'remaining_slots': 30},
            provider=lambda *_: {'candidates': [{'ref': 's0', 'disposition': 'SOFT_SKIP',
                'reason': 'No longer worth publishing'}]})
    assert menzo.source_key(row['url']) in menzo.terminal_skip_memory()


def test_odds_already_in_soft_pool_close_during_morning_hold():
    row = pool_article('old-odds')
    row['title'] = 'WWE Money in the Bank Betting Odds Released'
    menzo.write_json(menzo.SOFTPOOL_FILE, {'items': [row]})
    result = soft.apply({'selected': [], 'pending': [], 'skipped': []},
        {'observation_timestamp': '2026-10-10T08:00:00Z', 'remaining_slots': 30},
        provider=lambda *_: pytest.fail('old odds cannot compete'))
    assert result['pending'] == result['selected'] == [] and len(result['skipped']) == 1
    assert menzo.source_key(row['url']) in menzo.terminal_skip_memory()


def test_corrupt_permanent_memory_cannot_silently_reopen_urls():
    menzo.HARD_SKIP_FILE.write_text('{broken', encoding='utf-8')
    with pytest.raises(ValueError):
        active.evaluate(snapshot([article('closed')]), provider=lambda *_:
            pytest.fail('corrupt memory must block costly work'))


def test_full_gate_sees_only_semantically_admitted_pair_and_cached_final_cannot_be_omitted():
    rows = [article('a', 'AJ Styles confirms WWE released him from his contract'),
            article('b', 'WWE confirms the release of AJ Styles'), article('c', 'NXT confirms its next venue')]
    suspect = {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Both report the confirmed release of AJ Styles.'}
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if 'DUPLICATE GATE PHASE ONLY' in prompt:
            return {'relations': [{'ref': 'r0', 'decision': 'DUPLICATE',
                'shared_fact': 'The confirmed release of AJ Styles',
                'left_evidence': 'AJ Styles confirms WWE released him from his contract',
                'right_evidence': 'WWE confirms the release of AJ Styles',
                'left_central_development': 'AJ Styles is released from WWE',
                'right_central_development': 'AJ Styles is released from WWE',
                'centrality_basis': 'Both independently report this same confirmed professional departure.'}]}
        return classes(['SHOULD_PUBLISH'] * 3, [suspect])
    first = snapshot(rows)
    result = active.evaluate(first, provider=provider)
    assert result['status'] == 'VALIDATED' and len(calls) == 3
    assert len(first['semantic_duplicate_skips']) == 1
    gate = json.loads(calls[2].rsplit('INPUT=', 1)[1])
    assert len(gate['authorized_relations']) == 1
    # The gate may retain the candidate table but only the suspected pair has
    # authorized full-material endpoints and decision refs.
    assert set(gate['authorized_relations'][0]) == {'ref', 'scope', 'left_ref', 'right_ref'}
    second = snapshot(rows)
    later_calls = []
    later = active.evaluate(second, provider=lambda prompt, *_:
        later_calls.append(prompt) or classes(['SHOULD_PUBLISH'] * 3))
    assert later['status'] == 'VALIDATED' and len(later_calls) == 1
    assert later['output']['relations'] == []
    assert len(second['terminal_policy_skips']) == 1


@pytest.mark.parametrize('bad', [
    {'left_ref': 'a0', 'right_ref': 'h99', 'basis': 'Unknown endpoint'},
    {'left_ref': 'a0', 'right_ref': 'a0', 'basis': 'Self comparison'},
    {'left_ref': 'a0', 'right_ref': 'a1', 'basis': ''},
])
def test_invalid_suspicion_cannot_authorize_a_comparison(bad):
    primary = snapshot([article('a'), article('b')])
    admission.attach(primary, primary['candidates'], [], [])
    decisions = [{'candidate_id': row['candidate_id'], 'editorial_class': 'SHOULD_PUBLISH'}
                 for row in primary['candidates']]
    relations, failures = admission.validate({'admission_complete': True, 'suspected_duplicates': [bad]},
                                            primary, decisions, 300)
    assert relations is None and failures
