"""A successful report fulfils one event/night/date, independently of source."""
import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents import simone
from agents import simone_publisher_v93_18 as publisher
from test_totem_r01_report_contract import _isolated_simone, _with_structured_match, candidate, event_report
from test_wrestleview_fallback_and_materiality import isolate_weekly, item, RS, WV

ROME = ZoneInfo('Europe/Rome')
RS_REAL = 'https://www.ringsidenews.com/aew-wrestledream-results-highlights-key-moments-october-17-2026'
WV_REAL = 'https://www.wrestleview.com/top-story/395196-aew-wrestledream-results-10-17-26-clockwork-carnage-four-way-title-match-more'
KEY = 'special_event_aew_wrestledream_2026_main_2026_10_17'


def obligation():
    return {'report_key': KEY, 'event_key': 'aew_wrestledream_2026',
            'night_key': 'aew_wrestledream_2026_main', 'report_id': 'aew_wrestledream_2026_main',
            'date': '2026-10-17', 'aliases': ['AEW WrestleDream', 'WrestleDream'],
            'event_name': 'WrestleDream', 'source_url': WV_REAL,
            'source_title': 'AEW WrestleDream Results 10/17/26', 'title': 'AEW WrestleDream'}


def published(url=RS_REAL, **updates):
    return {'report_key': KEY, 'source_url': url, 'wp_post_id': 13724,
            'wp_link': 'https://news.test/report/', 'status': 'published', **updates}


@pytest.mark.parametrize('url', [RS_REAL, WV_REAL, 'https://future-source.test/aew-wrestledream-results-october-17-2026'])
def test_completed_report_does_not_depend_on_current_source_policy(url):
    assert simone.report_already_published(obligation(), {KEY: published(url)}, {'items': []}, [])


def test_completion_receipt_survives_future_url_and_headline_formats():
    record = published('https://future-source.test/live/123', source_title='Future-format coverage',
        report_completion={'version': 'totem-r01-completion-v1', 'report_key': KEY, 'date': '2026-10-17',
                           'night_key': 'aew_wrestledream_2026_main'})
    assert simone.report_already_published(obligation(), {KEY: record}, {'items': []}, [])


@pytest.mark.parametrize('updates', [
    {'source_url': RS_REAL.replace('october-17', 'october-16')},
    {'source_url': 'https://www.ringsidenews.com/wwe-raw-results-october-17-2026'},
    {'source_url': 'https://www.ringsidenews.com/aew-wrestledream-preview-october-17-2026'},
    {'source_url': 'https://www.ringsidenews.com/pyro-wrestledream-october-17-2026'},
    {'status': 'dry_run'}, {'status': 'publish_error'},
    {'wp_post_id': None, 'wp_link': ''},
    {'report_key': 'special_event_aew_wrestledream_2026_night_2_2026_10_17'},
])
def test_bad_legacy_associations_and_unsuccessful_work_do_not_close_an_obligation(updates):
    assert not simone.report_already_published(obligation(), {KEY: published(**updates)}, {'items': []}, [])


def test_generated_italian_title_does_not_turn_a_news_article_into_a_report():
    record = published('https://www.wrestleview.com/impact-wrestling-results/395098-viewership-and-key-demo-up-for-tna-impact-on-amc-bound-for-glory-go-home-show',
                       title='TNA Impact del 16 ottobre 2026 - risultati e momenti salienti')
    target = {'report_key': 'tna_impact_2026_10_16', 'report_id': 'tna_impact', 'date': '2026-10-16', 'source_url': WV}
    record['report_key'] = target['report_key']
    assert not simone.report_already_published(target, {target['report_key']: record}, {'items': []}, [])


def test_different_night_or_date_remains_due():
    target = {**obligation(), 'report_key': KEY.replace('_main_', '_night_2_'), 'night_key': 'aew_wrestledream_2026_night_2'}
    assert not simone.report_already_published(target, {KEY: published()}, {'items': []}, [])


def test_weekly_completion_stops_election_and_reservation_after_source_leaves_feed(tmp_path, monkeypatch):
    paths = isolate_weekly(tmp_path, monkeypatch, datetime(2026, 10, 16, 9, tzinfo=ROME))
    key = 'tna_impact_2026_10_15'
    paths['SIMONE_REPORT_HISTORY_FILE'].write_text(json.dumps({key: {
        'report_key': key, 'source_url': RS, 'wp_post_id': 42}}))
    monkeypatch.setattr(simone, 'choose_report_candidate', lambda *a, **k: pytest.fail('completed report must not elect sources'))
    monkeypatch.setattr(simone, 'reserve_report', lambda *a, **k: pytest.fail('completed report must not reserve sources'))
    result = simone.run_simone({'report_candidates': [item()]})
    assert not result['ready_reports'] and result['skipped_reports'][0]['reason'] == 'already_published'
    assert not json.loads(paths['PENDING_REPORTS'].read_text())['reports']


@pytest.mark.parametrize('hour,minute', [(6, 10), (9, 0)])
def test_completed_pending_row_is_closed_even_before_its_deadline(tmp_path, monkeypatch, hour, minute):
    paths = isolate_weekly(tmp_path, monkeypatch, datetime(2026, 10, 16, hour, minute, tzinfo=ROME))
    key = 'tna_impact_2026_10_15'
    paths['SIMONE_REPORT_HISTORY_FILE'].write_text(json.dumps({key: {
        'report_key': key, 'source_url': RS, 'wp_post_id': 42}}))
    row = {'report_key': key, 'report_id': 'tna_impact', 'date_local': '2026-10-15',
           'publish_date_local': '2026-10-16', 'publish_after': '06:30', 'source': 'ringsidenews',
           'source_url': RS, 'normalized_url': RS, 'source_title': 'TNA Impact Results October 15, 2026',
           'canonical_source_locked': True, 'canonical_identity': 'ringsidenews_results',
           'status': 'waiting_publish_after'}
    paths['PENDING_REPORTS'].write_text(json.dumps({'reports': [row]}))
    result = simone.run_simone({'report_candidates': []})
    assert not result['ready_reports'] and not result['waiting_reports']
    assert len(result['skipped_reports']) == 1 and result['skipped_reports'][0]['reason'] == 'already_published'
    assert json.loads(paths['PENDING_REPORTS'].read_text())['reports'][0]['status'] == 'already_published'


def test_special_completion_stops_structured_discovery_election_and_pending_replay(tmp_path, monkeypatch):
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, datetime(2026, 8, 31, 9, tzinfo=ROME))
    cfg['events'] = [event for event in cfg['events'] if event['key'] == 'aew_all_in_2026']
    config = tmp_path / 'reports.json'; config.write_text('{"reports": []}')
    monkeypatch.setattr(simone, 'REPORTS_CONFIG', config)
    report = event_report('aew_all_in_2026')
    rs = 'https://www.ringsidenews.com/aew-all-in-results-august-30-2026'
    source = {**candidate('AEW All In 2026 Results 8/30/26', 'https://www.wrestleview.com/12-aew-all-in-results-8-30-26'), 'source': 'wrestleview'}
    source = _with_structured_match(source, cfg)
    paths['SIMONE_REPORT_HISTORY_FILE'].write_text(json.dumps({report['report_key']: {
        'report_key': report['report_key'], 'source_url': rs, 'wp_post_id': 42}}))
    paths['PENDING_REPORTS'].write_text(json.dumps({'reports': [{**report,
        'source': 'wrestleview', 'source_url': source['url'], 'normalized_url': source['url'],
        'source_title': source['title'], 'date_local': report['date'], 'status': 'waiting_publish_after',
        'canonical_source_locked': True, 'canonical_identity': 'wrestleview_results',
        'source_selection_policy': 'ringside_until_0830_wrestleview_v1',
        'discovered_at': '2026-08-31T08:42:00+02:00'}]}))
    monkeypatch.setattr(simone, 'choose_special_report_candidate', lambda *a, **k: pytest.fail('no source election after successful publication'))
    monkeypatch.setattr(simone, 'reserve_report', lambda *a, **k: pytest.fail('no reservation after successful publication'))
    result = simone.run_simone({'report_candidates': [source]})
    assert not result['ready_reports'] and result['special_already_published']
    assert len(json.loads(paths['PENDING_REPORTS'].read_text())['reports']) == 1


def isolate_publisher(tmp_path, monkeypatch):
    for name in ('SIMONE_REPORT_HISTORY_FILE', 'PENDING_REPORTS', 'ARTIFACT_SIMONE_PUBLISH_FILE', 'SIMONE_REPORT_STATUS_FILE'):
        monkeypatch.setattr(publisher, name, tmp_path / (name + '.json'))
    monkeypatch.setattr(publisher, 'DRY_RUN', False)
    monkeypatch.setattr(publisher, 'jarvis_wp_preflight', lambda: (True, 'isolated', {}))
    monkeypatch.setattr(publisher, 'wp_ready', lambda: (True, 'isolated', {}))


def test_publisher_preserves_first_success_without_scraping_or_wp_checks(tmp_path, monkeypatch):
    isolate_publisher(tmp_path, monkeypatch)
    publisher.SIMONE_REPORT_HISTORY_FILE.write_text(json.dumps({KEY: published()}))
    before = publisher.SIMONE_REPORT_HISTORY_FILE.read_bytes()
    for name in ('scrape_article', 'run_report_workshop', 'jarvis_wp_preflight', 'wp_ready'):
        monkeypatch.setattr(publisher, name, lambda *a, **k: pytest.fail('completed report must not do downstream work'))
    result = publisher.run_simone_report_publisher({'ready_reports': [obligation()]})
    assert result['handoff']['already_published'] == 1
    assert publisher.SIMONE_REPORT_HISTORY_FILE.read_bytes() == before


def test_two_same_run_sources_publish_once_and_store_source_agnostic_completion(tmp_path, monkeypatch):
    isolate_publisher(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(publisher, 'scrape_article', lambda url: ([{'text': 'A defeated B.'}], '', None))
    def workshop(job, *_):
        calls.append(job['source_url']); return 77, {'link': 'https://news.test/77'}
    monkeypatch.setattr(publisher, 'run_report_workshop', workshop)
    first = {**obligation(), 'source_url': RS_REAL}
    second = copy.deepcopy(obligation())
    result = publisher.run_simone_report_publisher({'ready_reports': [first, second]})
    assert result['handoff']['published'] == 1 and calls == [RS_REAL]
    stored = json.loads(publisher.SIMONE_REPORT_HISTORY_FILE.read_text())[KEY]
    assert stored['report_completion']['date'] == '2026-10-17'
    stored['source_url'] = 'https://future-source.test/opaque/123'
    assert simone.report_already_published(second, {KEY: stored}, {'items': []}, [])
