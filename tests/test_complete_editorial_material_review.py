"""Pre-PR regressions for source identity, failure isolation and metric authority."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from agents import menzo_source_material as material
from agents import menzo_editorial_director_active as active
from agents import menzo_soft_board as soft
from agents import menzo_policy_v93_15 as menzo
from agents import source_body
from agents.canonical_event_ledger import CanonicalEventLedger, install_active_ledger, clear_active_ledger
from scripts.editorial_material_metrics import build_metrics
from scripts import current_editorial_report as report
from test_complete_editorial_material import article, snapshot, classify


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ('SOFTPOOL_FILE', 'MENZO_DECISIONS_FILE', 'ARTIFACT_DECISIONS_FILE', 'V92_ALLOWED_URLS_FILE'):
        monkeypatch.setattr(menzo, name, tmp_path / (name + '.json'))
    monkeypatch.setattr(active.pair_cache, 'CACHE_FILE', tmp_path / 'pairs.json')
    monkeypatch.setattr(active, 'record_gemini_attempt', lambda **_: None)
    monkeypatch.setattr(menzo, 'load_authoritative_publisher_history', lambda *_: [])
    yield
    clear_active_ledger()


def body(url):
    return source_body.contract_from_elements(url, [{'type': 'text', 'text': 'Verified professional facts. ' * 20}],
        {'extraction_finished': True, 'body_complete': True, 'clean_element_count': 1})


def test_other_url_body_is_never_used_as_complete_input(monkeypatch):
    row = {**article('current'), 'candidate_id': 'current', 'canonical_source_body': body('https://full.test/other')}
    monkeypatch.setattr(material, '_fetch_body', lambda *_: (False, 'offline'))
    session = material.Session({'observation_timestamp': datetime.now(timezone.utc).isoformat()})
    assert session.hydrate(row, 'primary_classification') is False
    assert row['input_coverage'] == 'BODY_UNAVAILABLE'


def test_soft_source_failure_does_not_block_independent_complete_url(monkeypatch):
    rows = [article('good'), article('offline')]
    for row in rows:
        row['editorial_director'] = {'editorial_class': 'PUBLISHABLE_SOFT', 'recommended_action': 'DEFER',
            'category': 'WWE', 'story_core': 'Professional source facts'}
    def fetch(row):
        if row['url'].endswith('/offline'):
            return False, 'offline'
        row['canonical_source_body'] = body(row['url'])
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    survivors, skipped, meta = soft._revalidate_pool_duplicates(rows,
        provider=lambda *_: pytest.fail('one eligible endpoint has no comparison'))
    assert [row['url'] for row in survivors] == [rows[0]['url']]
    assert meta['semantic_admission_status'] != 'TECHNICAL_BLOCK'
    assert [row['url'] for row in meta['source_material_held_items']] == [rows[1]['url']]
    assert not skipped and not menzo.terminal_skip_memory()


def observed_cycle(tmp_path):
    ledger = CanonicalEventLedger('review', path=tmp_path / 'state/newsroom/canonical_event_ledger.jsonl')
    install_active_ledger(ledger)
    active.evaluate(snapshot([article('complete')]), provider=lambda *_: classify(1))
    rows = [json.loads(line) for line in ledger.path.read_text().splitlines()]
    return ledger.path, rows, datetime.fromisoformat(rows[0]['timestamp_utc'])


@pytest.mark.parametrize('missing_type', ['editorial_input_profile', 'editorial_source_material'])
def test_missing_observer_events_cannot_certify_window_totals(tmp_path, missing_type):
    path, rows, start = observed_cycle(tmp_path)
    path.write_text('\n'.join(json.dumps(row) for row in rows if row['event_type'] != missing_type))
    metrics = build_metrics(tmp_path, start, datetime.now(timezone.utc) + timedelta(seconds=1))
    assert metrics['coverage'] == 'unavailable'
    assert metrics['sources']['window_metrics'] is None


def test_repeated_input_observation_is_one_logical_request_and_one_attempt(tmp_path):
    path, rows, start = observed_cycle(tmp_path)
    profile = next(row for row in rows if row['event_type'] == 'editorial_input_profile')
    rows.append(copy.deepcopy(profile))
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    metrics = build_metrics(tmp_path, start, datetime.now(timezone.utc) + timedelta(seconds=1))
    counts = metrics['inputs']['editorial_director_active']['observed']
    assert counts['input_profile_observations'] == 2
    assert counts['logical_requests'] == counts['provider_attempts'] == 1
    assert counts['prompt_bytes'] == json.loads(profile['result'])['prompt_bytes']


def test_malformed_source_payload_is_unavailable_instead_of_crashing_report(tmp_path):
    path, rows, start = observed_cycle(tmp_path)
    row = next(row for row in rows if row['event_type'] == 'editorial_source_material')
    payload = json.loads(row['result'])
    payload.pop('origin')
    row['result'] = json.dumps(payload)
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    metrics = build_metrics(tmp_path, start, datetime.now(timezone.utc) + timedelta(seconds=1))
    assert metrics['coverage'] == 'unavailable'


def test_missing_economic_ledger_has_no_known_zero_token_sum(tmp_path):
    now = datetime.now(timezone.utc)
    economic = report.economic_sections(tmp_path, now - timedelta(hours=24), now)
    assert economic['usage']['overall']['input_tokens']['known_sum'] is None
    assert economic['usage']['overall']['input_tokens']['window_total'] is None


def test_unknown_workload_is_not_attributed_to_news(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / 'state/newsroom/gemini_call_ledger.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'timestamp': now.isoformat(), 'status': 'called',
        'ledger_schema_version': 'v3', 'provider_attempt_id': 'unknown-workload'}))
    economic = report.economic_sections(tmp_path, now - timedelta(hours=24), now)
    assert economic['partitions']['news_and_editorial']['real_attempts'] == 0
    assert economic['partitions']['unattributed']['real_attempts'] == 1


def test_wrong_archived_contract_is_discarded_before_fresh_source_extraction(monkeypatch):
    row = {**article('current'), 'candidate_id': 'current', 'canonical_source_body': body('https://full.test/other')}
    def fetch(item):
        assert 'canonical_source_body' not in item
        item['canonical_source_body'] = body(item['url'])
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    session = material.Session({})
    assert session.hydrate(row, 'primary_classification')
    assert material.valid_for(session.data['bodies'][material.key(row)]['contract'], row)


def test_corrupt_source_cache_is_preserved_and_does_not_invent_skip(monkeypatch):
    material.CACHE_FILE.write_text('{corrupt')
    original = material.CACHE_FILE.read_bytes()
    monkeypatch.setattr(material, '_fetch_body', lambda *_: (False, 'offline'))
    session = material.Session({})
    assert not session.hydrate({**article('held'), 'candidate_id': 'held'}, 'primary_classification')
    assert session.finish()['cache_error'] == 'source_material_cache_unavailable'
    assert material.CACHE_FILE.read_bytes() == original and not menzo.terminal_skip_memory()


def test_soft_missing_history_holds_only_its_connected_component(monkeypatch):
    rows = [article(name) for name in ('affected', 'connected', 'independent')]
    for row in rows:
        row['editorial_director'] = {'editorial_class': 'PUBLISHABLE_SOFT', 'recommended_action': 'DEFER',
            'category': 'WWE', 'story_core': 'Professional facts'}
    history = {**article('history'), 'status': 'published'}
    monkeypatch.setattr(menzo, 'load_authoritative_publisher_history', lambda *_: [history])
    def fetch(row):
        if row['url'] == history['url']:
            return False, 'offline'
        row['canonical_source_body'] = body(row['url'])
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    calls = []
    def admission_only(prompt, schema, *_):
        calls.append(prompt)
        assert 'suspected_duplicates' in schema['properties']
        return {'admission_complete': True, 'suspected_duplicates': [
            {'left_ref': 'a0', 'right_ref': 'h0', 'basis': 'Potential same development'},
            {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Potential connected development'}]}
    survivors, skipped, meta = soft._revalidate_pool_duplicates(rows, provider=admission_only)
    assert [row['url'] for row in survivors] == [rows[2]['url']]
    assert {row['url'] for row in meta['source_material_held_items']} == {row['url'] for row in rows[:2]}
    assert len(calls) == 1 and not skipped and not menzo.terminal_skip_memory()


def test_soft_source_hold_is_persisted_without_consuming_meaningful_review(monkeypatch):
    now = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    rows = [article('good'), article('offline')]
    for row in rows:
        row.update(soft_board_day='2026-10-13', soft_board_review_count=1,
            soft_board_first_seen_at=now.isoformat(), editorial_director={
                'editorial_class': 'PUBLISHABLE_SOFT', 'recommended_action': 'DEFER',
                'category': 'WWE', 'story_core': 'Professional facts'})
    soft._write_pool(rows)
    def fetch(row):
        if row['url'].endswith('/offline'):
            return False, 'offline'
        row['canonical_source_body'] = body(row['url'])
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    monkeypatch.setattr(soft, '_capacity', lambda *_: {'soft_capacity_this_run': 1})
    monkeypatch.setattr(soft, '_published_day_context', lambda *_: {})
    def review(prompt, schema, *_):
        data = json.loads(prompt.split('INPUT=', 1)[1])
        assert [r['url'] for r in data['candidates']] == [rows[0]['url']]
        return {'candidates': [{'ref': 's0', 'disposition': 'SOFT_MUST', 'reason': 'Substantial professional facts'}]}
    projected = soft.apply({'selected': [], 'pending': [], 'skipped': []},
        {'observation_timestamp': now.isoformat()}, provider=review)
    assert [row['url'] for row in projected['selected']] == [rows[0]['url']]
    assert [row['url'] for row in projected['pending']] == [rows[1]['url']]
    remaining = soft._load_pool_rows()
    assert len(remaining) == 1 and remaining[0]['soft_board_review_count'] == 1
    assert remaining[0]['editorial_director']['editorial_class'] == 'PUBLISHABLE_SOFT'


def test_missing_final_verdict_event_makes_window_unavailable(tmp_path):
    ledger = CanonicalEventLedger('review-verdict', path=tmp_path / 'state/newsroom/canonical_event_ledger.jsonl')
    install_active_ledger(ledger)
    def provider(prompt, schema, *_):
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Possible shared fact'}]}
        if 'relations' in schema['properties']:
            return {'relations': [{'ref': 'r0', 'decision': 'NO_MATCH'}]}
        return classify(2)
    active.evaluate(snapshot([article('left'), article('right')]), provider=provider)
    rows = [json.loads(line) for line in ledger.path.read_text().splitlines()]
    start = datetime.fromisoformat(rows[0]['timestamp_utc'])
    ledger.path.write_text('\n'.join(json.dumps(row) for row in rows if row['event_type'] != 'editorial_duplicate_verdict'))
    metrics = build_metrics(tmp_path, start, datetime.now(timezone.utc) + timedelta(seconds=1))
    assert metrics['coverage'] == 'unavailable' and metrics['duplicates']['window_metrics'] is None


def test_installed_report_producer_without_workload_is_still_report_cost(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / 'state/newsroom/gemini_call_ledger.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'timestamp': now.isoformat(), 'status': 'called', 'agent': 'Bob',
        'ledger_schema_version': 'v3', 'provider_attempt_id': 'report-attempt',
        'pipeline': 'report', 'phase': 'report_blocks_legacy_prompt', 'reason': 'report_translation'}))
    economic = report.economic_sections(tmp_path, now - timedelta(hours=24), now)
    assert economic['partitions']['reports']['real_attempts'] == 1
    assert economic['partitions']['news_and_editorial']['real_attempts'] == 0
    assert economic['attribution_complete'] is True


@pytest.mark.parametrize('field,value', [('observation_id', ['invalid']), ('origin', ['invalid']), ('status', {})])
def test_non_scalar_payload_identities_do_not_crash_reporting(tmp_path, field, value):
    path, rows, start = observed_cycle(tmp_path)
    row = next(row for row in rows if row['event_type'] == 'editorial_source_material')
    payload = json.loads(row['result'])
    payload[field] = value
    row['result'] = json.dumps(payload)
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    metrics = build_metrics(tmp_path, start, datetime.now(timezone.utc) + timedelta(seconds=1))
    assert metrics['coverage'] == 'unavailable' and metrics['sources']['window_metrics'] is None


def test_oversized_full_body_is_retryable_without_classification_or_truncation(monkeypatch):
    from agents import menzo_editorial_director_shadow as shadow
    import newsroom_runner as runner
    complete = ('Complete autonomous source facts. ' * (shadow.MAX_INPUT_BYTES // 20)).strip()
    def fetch(row):
        row['canonical_source_body'] = source_body.contract_from_elements(row['url'],
            [{'type': 'text', 'text': complete}],
            {'extraction_finished': True, 'body_complete': True, 'clean_element_count': 1})
        return True, 'complete'
    monkeypatch.setattr(material, '_fetch_body', fetch)
    value = snapshot([article('oversized')])
    result = active.evaluate(value, provider=lambda *_: pytest.fail('oversize cannot call provider'))
    assert result['status'] == 'OVERSIZE_NOT_EVALUATED' and result['attempts'] == 0
    assert not active.primary_store.load()
    held = material._read()['holds']
    row = held[material.key(article('oversized'))]
    assert row['reason'] == 'primary_input_limit' and row['item']['retained_body'] == complete
    decision = runner.persist_active_fail_closed(value, result['fallback_reason'], technical_hold=True)
    assert decision['selected'] == decision['skipped'] == decision['allowed_urls_for_v92'] == []
    assert [r['url'] for r in decision['pending']] == [article('oversized')['url']]
    assert not menzo.terminal_skip_memory() and not menzo.SOFTPOOL_FILE.exists()
    assert menzo.load_json(menzo.V92_ALLOWED_URLS_FILE, {})['allowed_urls'] == []
    monkeypatch.setattr('agents.menzo_priority_queue._published_keys', lambda: set())
    recovered = material.augment_board({'news_candidates_for_menzo': []})
    assert recovered['news_candidates_for_menzo'][0]['url'] == article('oversized')['url']


@pytest.mark.parametrize('phase', ['admission', 'duplicate_gate'])
def test_input_bounds_after_classification_preserve_classes_and_true_skips(monkeypatch, phase):
    import newsroom_runner as runner
    value = snapshot([article('terminal'), article('left'), article('right')])
    finalize = active._finalize_active_input
    def bound(row):
        finalize(row)
        if ((phase == 'admission' and row.get('_semantic_admission')) or
                (phase == 'duplicate_gate' and row.get('authorized_relations'))):
            row['limit_status'] = 'exceeded'
    monkeypatch.setattr(active, '_finalize_active_input', bound)
    calls = []
    def provider(_prompt, schema, *_):
        calls.append(list(schema['properties']))
        if 'suspected_duplicates' in schema['properties']:
            return {'admission_complete': True, 'suspected_duplicates': [
                {'left_ref': 'a0', 'right_ref': 'a1', 'basis': 'Possible shared facts'}]}
        assert 'relations' not in schema['properties'] or 'candidates' in schema['properties']
        rows = classify(3)['candidates']
        rows[0].update(editorial_class='SKIP', recommended_action='SKIP')
        return {'candidates': rows}
    result = active.evaluate(value, provider=provider)
    assert result['status'] == 'OVERSIZE_NOT_EVALUATED'
    assert len(calls) == (1 if phase == 'admission' else 2)
    frozen = copy.deepcopy(active.primary_store.load())
    decision = runner.persist_active_fail_closed(value, result['fallback_reason'], technical_hold=True)
    assert len(decision['pending']) == 2 and len(decision['skipped']) == 1
    assert {r['editorial_director']['editorial_class'] for r in decision['pending']} == {'SHOULD_PUBLISH'}
    assert active.primary_store.load() == frozen
    assert set(menzo.terminal_skip_memory()) == {material.key(article('terminal'))}
    assert set(material._read()['holds']) == {material.key(article('left')), material.key(article('right'))}
    assert not menzo.SOFTPOOL_FILE.exists()
    monkeypatch.setattr(active, '_finalize_active_input', finalize)
    def retry_provider(_prompt, schema, *_):
        assert 'candidates' not in schema['properties'], 'First classes cannot be reevaluated'
        if 'relations' in schema['properties']:
            return {'relations': [{'ref': 'r0', 'decision': 'NO_MATCH'}]}
        return {'admission_complete': True, 'suspected_duplicates': []}
    retried = active.evaluate(snapshot([article('left'), article('right')]), provider=retry_provider)
    assert retried['status'] == 'VALIDATED'
    assert retried['editorial_prefilter']['reused_primary_classes'] == 2
    assert active.primary_store.load() == frozen and material._read()['holds'] == {}


def test_primary_input_bound_keeps_reused_skip_terminal(monkeypatch):
    import newsroom_runner as runner
    rows = [article('prior_skip'), article('oversized_sibling')]
    value = snapshot(rows)
    frozen = {**classify(1, 'SKIP')['candidates'][0], 'candidate_id': value['candidates'][0]['candidate_id']}
    active.primary_store.remember(value['candidates'][:1], [frozen], when=value['observation_timestamp'],
                                  policy=active.POLICY_VERSION)
    finalize = active._finalize_active_input
    def bound(row):
        finalize(row)
        row['limit_status'] = 'exceeded'
    monkeypatch.setattr(active, '_finalize_active_input', bound)
    result = active.evaluate(value, provider=lambda *_: pytest.fail('transport hold has no provider call'))
    decision = runner.persist_active_fail_closed(value, result['fallback_reason'], technical_hold=True)
    assert [r['url'] for r in decision['skipped']] == [rows[0]['url']]
    assert [r['url'] for r in decision['pending']] == [rows[1]['url']]
    assert set(material._read()['holds']) == {material.key(rows[1])}
    assert set(menzo.terminal_skip_memory()) == {material.key(rows[0])}
