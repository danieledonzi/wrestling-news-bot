"""Real October 17 false report and validated source/date paths."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agents import simone
from modules import simone_report_integrity as integrity
from test_wrestleview_fallback_and_materiality import isolate_weekly, item

ROME = ZoneInfo('Europe/Rome')
BAD_URL = ('https://www.wrestleview.com/impact-wrestling-results/395098-'
           'viewership-and-key-demo-up-for-tna-impact-on-amc-bound-for-glory-go-home-show')
BAD_TITLE = 'Viewership and key demo up for TNA IMPACT on AMC Bound For Glory go-home show'


def bad_item():
    return {'source': 'wrestleview', 'title': BAD_TITLE, 'url': BAD_URL,
            'published': 'Fri, 16 Oct 2026 16:50:37 +0000'}


def weekly():
    return next(r for r in json.loads(simone.REPORTS_CONFIG.read_text())['reports']
                if r['id'] == 'tna_impact')


@pytest.mark.parametrize('date', ['2026-10-15', '2026-10-16'])
def test_category_folder_is_not_results_identity(date):
    assert not simone.candidate_matches_report(bad_item(), weekly(), date)


def test_generated_pending_title_cannot_supply_source_identity():
    row = {**bad_item(), 'title': 'TNA Impact del 16 ottobre 2026 - risultati e momenti salienti',
           'source_title': BAD_TITLE, 'source_url': BAD_URL}
    assert not simone.candidate_matches_report(row, weekly(), '2026-10-16')


def test_wrong_report_is_never_reserved_or_published_off_schedule(tmp_path, monkeypatch):
    now = datetime(2026, 10, 17, 8, 58, tzinfo=ROME)
    paths = isolate_weekly(tmp_path, monkeypatch, now)
    result = simone.run_simone({'report_candidates': [bad_item()]})
    assert not result['ready_reports']
    assert not json.loads(paths['PENDING_REPORTS'].read_text())['reports']


def test_invalid_unpublished_pending_report_is_closed_before_replay(tmp_path, monkeypatch):
    now = datetime(2026, 10, 17, 8, 58, tzinfo=ROME)
    paths = isolate_weekly(tmp_path, monkeypatch, now)
    pending = {**bad_item(), 'source_url': BAD_URL, 'source_title': BAD_TITLE,
               'normalized_url': BAD_URL, 'report_key': 'tna_impact_2026_10_16',
               'report_id': 'tna_impact', 'date_local': '2026-10-16',
               'publish_date_local': '2026-10-17', 'canonical_source_locked': True,
               'canonical_identity': 'wrestleview_results', 'status': 'waiting_publish_after',
               'discovered_at': now.isoformat(), 'source_selection_policy': integrity.REPORT_SOURCE_POLICY}
    paths['PENDING_REPORTS'].write_text(json.dumps({'reports': [pending]}))
    result = simone.run_simone({'report_candidates': []})
    assert not result['ready_reports']
    row = json.loads(paths['PENDING_REPORTS'].read_text())['reports'][0]
    assert row['status'] == 'invalid_canonical_identity' and not row['canonical_source_locked']


def test_fallback_needs_show_date_not_only_article_publication_timestamp():
    row = item(title='TNA Impact Results', published='2026-10-16T04:18:24Z')
    row['url'] = 'https://www.wrestleview.com/impact-results/123-tna-impact-results'
    assert not simone.candidate_matches_report(row, weekly(), '2026-10-15')


def test_legitimate_dated_results_slug_survives_generic_title():
    row = item(title='Full coverage', published='2026-10-16T04:18:24Z')
    assert simone.candidate_matches_report(row, weekly(), '2026-10-15')


def test_real_rescheduled_show_can_replay_without_a_global_weekday_veto(tmp_path, monkeypatch):
    now = datetime(2026, 10, 17, 8, 58, tzinfo=ROME)
    paths = isolate_weekly(tmp_path, monkeypatch, now)
    url = 'https://www.wrestleview.com/impact-results/123-tna-impact-results-10-16-26'
    row = {**item(title='TNA Impact Results 10/16/26'), 'url': url, 'source_url': url,
           'source_title': 'TNA Impact Results 10/16/26', 'normalized_url': url,
           'report_key': 'tna_impact_2026_10_16', 'report_id': 'tna_impact',
           'date_local': '2026-10-16', 'publish_date_local': '2026-10-17',
           'canonical_source_locked': True, 'canonical_identity': 'wrestleview_results',
           'discovered_at': now.isoformat(), 'source_selection_policy': integrity.REPORT_SOURCE_POLICY,
           'status': 'waiting_publish_after'}
    paths['PENDING_REPORTS'].write_text(json.dumps({'reports': [row]}))
    result = simone.run_simone({'report_candidates': []})
    assert [r['source_url'] for r in result['ready_reports']] == [url]
