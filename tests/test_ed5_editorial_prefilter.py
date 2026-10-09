import copy
import json

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_priority_queue as queue
from agents import menzo_soft_board as soft
from agents import menzo_active_duplicate_pair_cache as cache


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for attr in ('SOFTPOOL_FILE', 'HARD_SKIP_FILE', 'MENZO_DECISIONS_FILE',
                 'ARTIFACT_DECISIONS_FILE', 'V92_ALLOWED_URLS_FILE'):
        monkeypatch.setattr(menzo, attr, tmp_path / (attr + '.json'))
    history = tmp_path / 'history.json'
    history.write_text('{}')
    monkeypatch.setattr(menzo, 'publisher_history_file', lambda: history)
    monkeypatch.setattr(cache, 'CACHE_FILE', tmp_path / 'cache.json')
    monkeypatch.setattr(active, 'record_gemini_attempt', lambda **_: None)
    monkeypatch.setattr(active.source_body, 'hydrate', lambda _: (False, 'offline'))
    monkeypatch.setattr('agents.bob.dynamic_article_capacity', lambda *_: (1, 'test'))
    return history


def state():
    rows = [{'url': 'https://ed5.test/a', 'title': 'John Cena discusses a new project', 'summary': 'Interview facts'},
            {'url': 'https://ed5.test/b', 'title': 'John Cena shares new comments', 'summary': 'More interview facts'}]
    return shadow.capture_opportunity({'news_candidates_for_menzo': rows}, run_id='r',
        observation_timestamp='2026-10-09T06:00:00+00:00', history=[], defer_relation_build=True)


def classify(classes):
    return {'candidates': [{'ref': f'c{i}', 'editorial_class': cls,
        'recommended_action': {'SKIP': 'SKIP', 'PUBLISHABLE_SOFT': 'DEFER'}.get(cls, 'SELECT'),
        'category': 'WWE', 'story_core': f'Fact and reason {i}'} for i, cls in enumerate(classes)], 'relations': []}


def test_all_skips_never_construct_or_send_semantic_relations(monkeypatch):
    s = state()
    def build(candidates, history, **_):
        assert candidates == []
        return [], True
    monkeypatch.setattr(shadow, 'build_authorized_relations', build)
    calls = []
    result = active.evaluate(s, provider=lambda prompt, *_: calls.append(prompt) or classify(['SKIP', 'SKIP']))
    assert result['status'] == 'VALIDATED' and len(calls) == 1
    assert result['editorial_prefilter']['skipped_before_duplicate'] == 2
    assert result['editorial_prefilter']['duplicate_relations'] == 0
    projected = active.project(s, result)
    assert len(projected['skipped']) == 2
    assert len(menzo.load_json(menzo.HARD_SKIP_FILE, {})['items']) == 2
    assert projected['selected'] == projected['pending'] == []


def test_only_eligible_endpoints_reach_relation_builder(monkeypatch):
    s = state()
    candidates = []
    def build(rows, history, **_):
        candidates.extend(rows)
        return [], True
    monkeypatch.setattr(shadow, 'build_authorized_relations', build)
    result = active.evaluate(s, provider=lambda *_: classify(['SKIP', 'PUBLISHABLE_SOFT']))
    assert [row['url'] for row in candidates] == ['https://ed5.test/b']
    projected = active.project(s, result)
    assert projected['pending'][0]['url'] == 'https://ed5.test/b'
    assert projected['pending'][0]['soft_board']['disposition'] == 'MORNING_HOLD'


def test_primary_failure_cannot_reach_gate_or_pool(monkeypatch):
    s = state()
    monkeypatch.setattr(active, '_evaluate_duplicate_stage', lambda *_args, **_kw: pytest.fail('gate called'))
    result = active.evaluate(s, provider=lambda *_: {'candidates': [], 'relations': []})
    assert result['status'] != 'VALIDATED'
    assert result['failure_stage'] == 'editorial_prefilter'
    assert not menzo.SOFTPOOL_FILE.exists()


def test_show_identity_reaches_primary_without_pacing_or_history():
    s = state()
    active.preserve_bob_capacity_metadata(s, [{'url': 'https://ed5.test/a', 'show_report_id': 'raw',
                                             'show_name': 'Raw', 'event_report_key': 'raw:2026-10-09'}])
    def provider(prompt, *_):
        data = json.loads(prompt.split('INPUT=', 1)[1])
        assert data['candidates'][0]['show_report_id'] == 'raw'
        assert data['history'] == data['authorized_relations'] == []
        assert 'publication_context' not in data
        assert 'at least\nSHOULD_PUBLISH' in prompt
        return classify(['SHOULD_PUBLISH', 'SKIP'])
    result = active.evaluate(s, provider=provider)
    projected = active.project(s, result)
    assert projected['selected'][0]['show_report_id'] == 'raw'


def strong(url, cls='SHOULD_PUBLISH', **extra):
    return {'url': url, 'title': url, 'decision_authority': 'editorial_director',
            'editorial_director': {'editorial_class': cls, 'recommended_action': 'SELECT',
                                   'policy_version': active.POLICY_VERSION}, **extra}


def test_should_overflow_returns_without_feed_and_only_publication_drains(isolated):
    rows = [strong('https://ed5.test/1'), strong('https://ed5.test/2')]
    projected = {'selected': rows, 'pending': [], 'skipped': []}
    queue.schedule(projected, {'observation_timestamp': '2026-10-09T06:00:00+00:00'})
    assert len(projected['selected']) == len(projected['pending']) == 1
    assert projected['pending'][0]['editorial_director']['editorial_class'] == 'SHOULD_PUBLISH'
    # Both remain recoverable until Publisher acknowledges success, including downstream failures.
    board = queue.augment_board({'news_candidates_for_menzo': []})
    assert len(board['news_candidates_for_menzo']) == 2
    isolated.write_text(json.dumps({'a': {'source_url': rows[0]['url'], 'status': 'publish'}}))
    board = queue.augment_board({'news_candidates_for_menzo': []})
    assert [row['url'] for row in board['news_candidates_for_menzo']] == [rows[1]['url']]
    assert board['news_candidates_for_menzo'][0]['priority_queue_first_seen_at'] == '2026-10-09T06:00:00+00:00'


def test_dry_run_is_not_publication_and_midnight_does_not_drop_strong(isolated):
    row = strong('https://ed5.test/1')
    queue.schedule({'selected': [row], 'pending': [], 'skipped': []}, {'observation_timestamp': '2026-10-08T21:59:00+00:00'})
    isolated.write_text(json.dumps({'a': {'source_url': row['url'], 'status': 'dry_run'}}))
    assert len(queue.augment_board({'news_candidates_for_menzo': []})['news_candidates_for_menzo']) == 1


def test_live_should_precedes_ordinary_should_and_must_keeps_priority():
    ordinary = strong('https://ed5.test/1')
    live = strong('https://ed5.test/2', show_report_id='raw', corresponding_report_published=False)
    must = strong('https://ed5.test/3', 'MUST_PUBLISH')
    projected = {'selected': [ordinary, live, must], 'pending': [], 'skipped': []}
    queue.schedule(projected, {})
    assert projected['selected'] == [must, live]
    assert projected['pending'][0]['url'] == ordinary['url']
    assert projected['postprocess']['should_deferred_capacity'] == 1


def test_validated_duplicate_removes_queued_should():
    row = strong('https://ed5.test/1')
    queue.schedule({'selected': [row], 'pending': [], 'skipped': []}, {})
    skip = {**row, 'decision_authority': 'semantic_duplicate_gate'}
    queue.schedule({'selected': [], 'pending': [], 'skipped': [skip]}, {})
    assert queue.augment_board({'news_candidates_for_menzo': []})['news_candidates_for_menzo'] == []


def test_old_policy_soft_can_receive_new_live_classification():
    row = strong('https://ed5.test/1', 'PUBLISHABLE_SOFT')
    row['editorial_director']['policy_version'] = 'owtv_editorial_director_policy_v4_active'
    menzo.write_json(menzo.SOFTPOOL_FILE, {'items': [row]})
    board = soft.mark_rediscovered_pool_candidates({'news_candidates_for_menzo': [row]})
    assert not board['news_candidates_for_menzo'][0].get('_soft_board_existing')


def test_queue_is_rolled_back_when_projection_write_fails(monkeypatch):
    s = state()
    result = active.evaluate(s, provider=lambda *_: classify(['MUST_PUBLISH', 'SKIP']))
    original = menzo.write_json
    def fail(path, data):
        if path == menzo.ARTIFACT_DECISIONS_FILE:
            raise OSError('disk failure')
        return original(path, data)
    monkeypatch.setattr(menzo, 'write_json', fail)
    with pytest.raises(OSError):
        active.project(s, result)
    assert not queue.queue_path().exists()


def test_unchanged_queued_should_reuses_class_but_still_passes_duplicate_stage(monkeypatch):
    row = strong('https://ed5.test/queued')
    row['editorial_director'].update(category='WWE', story_core='Confirmed match result')
    queue.schedule({'selected': [row], 'pending': [], 'skipped': []}, {})
    board = queue.augment_board({'news_candidates_for_menzo': []})
    s = shadow.capture_opportunity(board, run_id='r2', observation_timestamp='2026-10-09T06:30:00Z',
                                   history=[], defer_relation_build=True)
    active.preserve_bob_capacity_metadata(s, board['news_candidates_for_menzo'])
    called = []
    original = active._evaluate_duplicate_stage
    def gate(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(active, '_evaluate_duplicate_stage', gate)
    monkeypatch.setattr(shadow, '_default_provider_factory',
                        lambda: pytest.fail('no model operation requires a provider'))
    result = active.evaluate(s)
    assert result['status'] == 'VALIDATED' and called == [True]
    assert result['editorial_prefilter']['reused_strong_classes'] == 1
    assert result['output']['candidates'][0]['editorial_class'] == 'SHOULD_PUBLISH'


def test_gate_failure_keeps_primary_skip_terminal(monkeypatch):
    import newsroom_runner as runner
    s = state()
    monkeypatch.setattr(active, '_evaluate_duplicate_stage', lambda *_args, **_kw:
                        {'status': 'PROVIDER_FAILED', 'attempts': 1})
    result = active.evaluate(s, provider=lambda *_: classify(['SKIP', 'SHOULD_PUBLISH']))
    assert result['status'] == 'PROVIDER_FAILED'
    handoff = runner.persist_active_fail_closed(s, 'gate_unavailable')
    assert handoff['selected'] == []
    assert menzo.load_json(menzo.HARD_SKIP_FILE, {})['items'][0]['url'] == 'https://ed5.test/a'
    assert len(menzo.load_json(menzo.HARD_SKIP_FILE, {})['items']) == 1


def test_observation_counts_unique_pairs_separately_from_repeated_evaluations(tmp_path):
    from scripts.editorial_prefilter_observation import summarize, stamp
    folder = tmp_path / 'state/newsroom'
    folder.mkdir(parents=True)
    row = {'run': {'started_at': '2026-10-09T06:00:00Z'}, 'editorial_pipeline': {
        'status': 'VALIDATED', 'prefilter': {'classes': {'PUBLISHABLE_SOFT': 1},
            'candidates': [{'url': 'https://ed5.test/a', 'editorial_class': 'PUBLISHABLE_SOFT'}],
            'duplicate_relations': 1, 'relations': [{'pair_id': 'p', 'scope': 'same_run'}]}}}
    (folder / 'master_log.jsonl').write_text(json.dumps(row) + '\n' + json.dumps(row) + '\n')
    (folder / 'gemini_call_ledger.jsonl').write_text(json.dumps({'timestamp': '2026-10-09T06:10:00Z',
        'phase': 'duplicate', 'computed_list_price_cost': '0.012', 'repair': True}) + '\n' + json.dumps({
        'timestamp': '2026-10-09T06:20:00Z', 'phase': 'duplicate'}) + '\n')
    result = summarize(tmp_path, stamp('2026-10-09T06:00:00Z'), stamp('2026-10-09T07:00:00Z'))
    assert result['duplicate_relation_evaluations'] == 2
    assert result['unique_duplicate_pairs'] == 1
    assert result['unique_candidates_by_latest_class'] == {'PUBLISHABLE_SOFT': 1}
    assert result['cost_by_phase']['duplicate'] == {'calls': 2, 'repairs': 1, 'unpriced_calls': 1, 'known_cost_usd': '0.012'}


def test_large_backlog_cannot_deadlock_active_candidate_guard(monkeypatch):
    monkeypatch.setattr(shadow, 'MAX_CANDIDATES', 3)
    queued = [strong(f'https://ed5.test/{i}') for i in range(5)]
    queue.schedule({'selected': queued, 'pending': [], 'skipped': []}, {})
    board = queue.augment_board({'news_candidates_for_menzo': [
        {'url': 'https://ed5.test/fresh', 'title': 'A fresh development'}]})
    assert len(board['news_candidates_for_menzo']) == 3
    assert any(row['url'].endswith('/fresh') for row in board['news_candidates_for_menzo'])
    assert board['priority_queue_waiting_capture_capacity'] == 3
    assert len(json.loads(queue.queue_path().read_text())['items']) == 5


@pytest.mark.parametrize('cached', [True, False])
def test_reused_strong_queue_only_needs_provider_for_uncached_relations(monkeypatch, cached):
    rows = [strong('https://ed5.test/a'), strong('https://ed5.test/b')]
    for row in rows:
        row.update(title='John Cena discusses his confirmed match ' + row['url'][-1], summary='Match news')
        row['editorial_director'].update(category='WWE', story_core='Confirmed match news')
    queue.schedule({'selected': rows, 'pending': [], 'skipped': []}, {})
    board = queue.augment_board({'news_candidates_for_menzo': []})
    snapshot = shadow.capture_opportunity(board, run_id='cached',
        observation_timestamp='2026-10-09T06:30:00Z', history=[], defer_relation_build=True)
    active.preserve_bob_capacity_metadata(snapshot, board['news_candidates_for_menzo'])
    relations, _ = shadow.build_authorized_relations(snapshot['candidates'], [], enforce_limit=False)
    assert len(relations) == 1
    monkeypatch.setattr(cache, 'lookup', lambda *_:
                        {**relations[0], 'decision': 'NO_MATCH'} if cached else None)
    initialized = []
    def unavailable():
        initialized.append(True)
        raise RuntimeError('provider unavailable')
    monkeypatch.setattr(shadow, '_default_provider_factory', unavailable)
    result = active.evaluate(snapshot)
    assert result['status'] == ('VALIDATED' if cached else 'PROVIDER_UNAVAILABLE')
    assert initialized == ([] if cached else [True])
    if cached:
        assert len(result['output']['candidates']) == 2
