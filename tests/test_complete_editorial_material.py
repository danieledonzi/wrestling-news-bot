"""Complete input, URL finality, scoped source holds and observable final decisions."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_primary_classification_store as primary
from agents import menzo_source_material as material
from agents import menzo_active_duplicate_pair_cache as cache
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_soft_board as soft
from agents import source_body
from agents.canonical_event_ledger import CanonicalEventLedger, install_active_ledger, clear_active_ledger, validate_event
from scripts.editorial_material_metrics import build_metrics

NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ('SOFTPOOL_FILE', 'MENZO_DECISIONS_FILE', 'ARTIFACT_DECISIONS_FILE', 'V92_ALLOWED_URLS_FILE'):
        monkeypatch.setattr(menzo, name, tmp_path / (name + '.json'))
    monkeypatch.setattr(cache, 'CACHE_FILE', tmp_path / 'pairs.json')
    monkeypatch.setattr(active, 'record_gemini_attempt', lambda **_: None)
    monkeypatch.setattr(menzo, 'load_authoritative_publisher_history', lambda *_: [])
    monkeypatch.setattr('agents.bob.dynamic_article_capacity', lambda *_: (5, 'test'))
    yield
    clear_active_ledger()


def article(name):
    return {'url': f'https://full.test/{name}', 'title': name, 'summary': 'A short RSS lead.'}


def snapshot(rows, history=()):
    return shadow.capture_opportunity({'news_candidates_for_menzo': rows}, run_id='full-input-test',
        observation_timestamp=NOW.isoformat(), history=list(history), defer_relation_build=True)


def contract(text, url="https://full.test/article"):
    return source_body.contract_from_elements(url, [{'type': 'text', 'text': text}],
        {'extraction_finished': True, 'body_complete': True, 'clean_element_count': 1})


def classify(count, cls='SHOULD_PUBLISH'):
    return {'candidates': [{'ref': f'c{i}', 'editorial_class': cls,
        'recommended_action': {'SKIP': 'SKIP', 'PUBLISHABLE_SOFT': 'DEFER'}.get(cls, 'SELECT'),
        'category': 'WWE', 'story_core': 'Autonomous factual development'} for i in range(count)]}


def test_complete_tail_reaches_classification_admission_and_gate_once_per_url(monkeypatch):
    body = 'Substantive source text. ' * 1500 + 'OTHER_PERFORMER_RETURN_AT_THE_END'
    calls = []
    def fetch(row):
        calls.append(row['url'])
        row['canonical_source_body'] = contract(body, row["url"])
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    value = snapshot([article('combined'), article('earlier')])
    phases = []
    def provider(prompt, schema, *_):
        data = json.loads(prompt.split('INPUT=', 1)[1])
        phases.append(list(schema['properties']))
        rows = [data['anchor']] + data['targets'] if 'anchor' in data else data['candidates']
        assert all(r['retained_body'] == body for r in rows)
        assert 'OTHER_PERFORMER_RETURN_AT_THE_END' in prompt
        if 'suspected_duplicates' in schema['properties']:
            assert not any('editorial_class' in r for r in rows)
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Potential shared event'}]}
        if 'relations' in schema['properties']:
            assert not any('editorial_class' in r for r in rows)
            return {'relations': [{'ref': 'r0', 'decision': 'NO_MATCH'}]}
        return classify(2)
    result = active.evaluate(value, provider=provider)
    assert result['status'] == 'VALIDATED'
    assert len(calls) == 2 and len(phases) == 3
    assert len(result['output']['candidates']) == 2
    stored = primary.load()
    assert all(r['first_input_coverage'] == 'FULL_BODY' for r in stored.values())
    assert all(r['first_input_contract'] == material.CONTRACT_VERSION for r in stored.values())


def test_missing_body_holds_only_its_url_without_freezing_class_or_skip(monkeypatch):
    good, unavailable = article('good'), article('unavailable')
    def fetch(row):
        if row['url'] == unavailable['url']:
            return False, 'incomplete_extraction'
        row['canonical_source_body'] = contract('Complete professional source details. ' * 20, row['url'])
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    value = snapshot([good, unavailable])
    result = active.evaluate(value, provider=lambda *_: classify(1))
    assert result['status'] == 'VALIDATED'
    assert result['output']['candidates'][0]['candidate_id'] == shadow.article_id(good)
    assert material.key(unavailable) not in primary.load()
    assert material.key(unavailable) not in menzo.terminal_skip_memory()
    projected = active.project(value, result)
    assert [r['url'] for r in projected['selected']] == [good['url']]
    assert [r['url'] for r in projected['pending']] == [unavailable['url']]
    assert 'editorial_director' not in projected['pending'][0]


def test_known_class_reused_with_complete_body_and_closed_url_never_fetched(monkeypatch):
    known, closed = article('known'), article('closed')
    value = snapshot([known])
    active.evaluate(value, provider=lambda *_: classify(1))
    menzo.save_hard_skips({'skipped': [{**closed, 'decision': 'skip', 'decision_authority': 'editorial_director',
        'editorial_director': {'editorial_class': 'SKIP'}, 'reason': 'editorial_class_skip'}]})
    original = copy.deepcopy(primary.load())
    monkeypatch.setattr(material, '_fetch_body', lambda *_: pytest.fail('cached source or terminal URL must not be fetched'))
    later = snapshot([known, closed])
    result = active.evaluate(later, provider=lambda *_: pytest.fail('fixed classification cannot be rerun'))
    assert result['status'] == 'VALIDATED' and result['attempts'] == 0
    assert primary.load() == original


def test_history_body_unavailable_blocks_only_admitted_component(monkeypatch):
    earlier = {**article('history'), 'status': 'published'}
    def fetch(row):
        if row['url'] == earlier['url']:
            return False, 'offline'
        row['canonical_source_body'] = contract('Concrete professional source details. ' * 20, row['url'])
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    value = snapshot([article('potential_duplicate'), article('independent')], [earlier])
    def provider(prompt, schema, *_):
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'h0', 'basis': 'Potential same development'}]
                if json.loads(prompt.split('INPUT=', 1)[1])['anchor']['ref'] == 'a0' else []}
        assert 'relations' not in schema['properties']
        return classify(2)
    result = active.evaluate(value, provider=provider)
    assert result['status'] == 'VALIDATED'
    assert [r['candidate_id'] for r in result['output']['candidates']] == [shadow.article_id(article('independent'))]
    assert len(result['source_material_holds']) == 1
    assert not menzo.terminal_skip_memory()


def test_new_events_validate_and_cached_verdict_is_not_a_second_unique_pair(tmp_path):
    ledger_path = tmp_path / 'state/newsroom/canonical_event_ledger.jsonl'
    ledger = CanonicalEventLedger('telemetry-test', path=ledger_path, enabled=True)
    install_active_ledger(ledger)
    left, right = article('left'), article('right')
    def provider(prompt, schema, *_):
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Potential same development'}]}
        if 'relations' in schema['properties']:
            # Sparse valid Gemini decisions remain final even without explanation fields.
            return {'relations': [{'ref': 'r0', 'decision': 'NO_MATCH'}]}
        return classify(2)
    first = active.evaluate(snapshot([left, right]), provider=provider)
    second = active.evaluate(snapshot([left, right]), provider=lambda *_: pytest.fail('unchanged material must reuse clearance'))
    assert first['status'] == second['status'] == 'VALIDATED'
    events = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    assert all(not validate_event(row) for row in events)
    assert ledger.stats['validation_errors'] == 0
    cutover = datetime.fromisoformat(events[0]['timestamp_utc'])
    result = build_metrics(tmp_path, cutover, datetime.now(timezone.utc) + timedelta(seconds=1))
    final = result['duplicates']['window_metrics']
    assert result['coverage'] == 'full'
    assert final['verdict_observations'] == 2
    assert final['unique_pair_material_decisions'] == 1
    assert final['decisions'] == {'NO_MATCH': 1}
    assert len(result['input_profiles']) == 3


def test_coverage_before_cutover_and_missing_ledger_never_means_zero(tmp_path):
    until = datetime.now(timezone.utc)
    missing = build_metrics(tmp_path, until - timedelta(hours=24), until)
    assert missing['coverage'] == 'unavailable' and missing['duplicates']['window_metrics'] is None
    ledger = CanonicalEventLedger('cutover', path=tmp_path / 'state/newsroom/canonical_event_ledger.jsonl')
    install_active_ledger(ledger)
    material.Session({}).finish()
    partial = build_metrics(tmp_path, until - timedelta(hours=24), datetime.now(timezone.utc))
    assert partial['coverage'] == 'partial' and partial['sources']['window_metrics'] is None
    assert partial['duplicates']['observed']['verdict_observations'] == 0


def test_soft_payload_contains_full_body_without_reclassifying():
    body = 'Professional explanation. ' * 1500 + 'FULL_SOFT_TAIL'
    row = {**article('soft'), 'retained_body': body, 'input_coverage': 'FULL_BODY',
           'editorial_director': {'editorial_class': 'PUBLISHABLE_SOFT', 'story_core': 'Professional explanation'}}
    payload, _ = soft._provider_payload([row], {}, {'soft_capacity_this_run': 1}, NOW)
    assert payload['candidates'][0]['retained_body'] == body
    assert payload['candidates'][0]['url'] == row['url']


def test_source_backoff_does_not_move_deadline_and_history_hold_never_becomes_candidate(monkeypatch):
    monkeypatch.setattr(material, '_fetch_body', lambda *_: (False, 'offline'))
    row = {**article('unavailable'), 'candidate_id': shadow.article_id(article('unavailable'))}
    start = datetime.now(timezone.utc)
    first = material.Session({'observation_timestamp': start.isoformat()})
    assert not first.hydrate(row, 'primary_classification')
    history = {**article('history'), 'article_id': shadow.article_id(article('history'))}
    assert not first.hydrate(history, 'duplicate_admission_history')
    first.finish()
    deadline = material._read()['holds'][material.key(row)]['retry_after']
    later = material.Session({'observation_timestamp': (start + timedelta(minutes=5)).isoformat()})
    assert not later.hydrate(row, 'primary_classification')
    later.finish()
    assert material._read()['holds'][material.key(row)]['retry_after'] == deadline
    state = material._read()
    state['holds'][material.key(history)]['retry_after'] = (start - timedelta(minutes=1)).isoformat()
    material._write(state)
    assert material.augment_board({'news_candidates_for_menzo': []})['news_candidates_for_menzo'] == []


def test_new_observer_write_failure_is_fail_open(monkeypatch):
    monkeypatch.setattr(material, 'active_event', lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('observer disk')))
    assert material.emit('editorial_input_profile', 'model', 'success', {'coverage': 'full'}) is False
    value = snapshot([article('good')])
    result = active.evaluate(value, provider=lambda *_: classify(1))
    assert result['status'] == 'VALIDATED'
    assert primary.load()[material.key(article('good'))]['editorial_class'] == 'SHOULD_PUBLISH'


def test_same_run_richer_winner_reuses_the_already_extracted_canonical_body(monkeypatch):
    def reuse(row):
        assert source_body.valid_contract(row.get('canonical_source_body'))
        return True, 'canonical_cache'
    monkeypatch.setattr(source_body, 'hydrate', reuse)
    def provider(prompt, schema, *_):
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Same factual outcome'}]}
        if 'relations' in schema['properties']:
            return {'relations': [{'ref': 'r0', 'decision': 'DUPLICATE'}]}
        return classify(2)
    result = active.evaluate(snapshot([article('left'), article('right')]), provider=provider)
    assert result['status'] == 'VALIDATED'
    assert len(result['output']['candidates']) == 1


def test_all_primary_skips_do_not_fetch_unneeded_published_history(monkeypatch):
    def fetch(row):
        assert row['url'] != 'https://full.test/history'
        row['canonical_source_body'] = contract('Complete factual source material. ' * 20, row['url'])
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    value = snapshot([article('weak')], [{**article('history'), 'status': 'published'}])
    result = active.evaluate(value, provider=lambda *_: classify(1, 'SKIP'))
    assert result['status'] == 'VALIDATED' and result['attempts'] == 1
    assert len(result['source_material']['observations']) == 1
