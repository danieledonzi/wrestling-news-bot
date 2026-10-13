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
