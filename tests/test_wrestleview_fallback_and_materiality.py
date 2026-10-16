"""Owner contract: timed fallback, final source identity, substantive updates."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agents import massy, simone
from agents import menzo_editorial_director_active as active
from agents import menzo_active_duplicate_pair_cache as pair_cache
from modules import simone_report_integrity as integrity
from modules.report_content import extract_report_blocks
from test_totem_r01_report_contract import _isolated_simone, _with_structured_match, candidate

ROME = ZoneInfo('Europe/Rome')
WV = 'https://www.wrestleview.com/impact-results/395084-tna-impact-on-amc-results-10-15-26'
RS = 'https://www.ringsidenews.com/tna-impact-results-october-15-2026'


def item(source='wrestleview', *, title='TNA IMPACT on AMC Results – 10/15/26', published='2026-10-16T04:18:24Z'):
    return {'source': source, 'url': WV if source == 'wrestleview' else RS,
            'title': title, 'published': published, 'summary': ''}


def isolate_weekly(tmp_path, monkeypatch, now):
    paths, _ = _isolated_simone(tmp_path, monkeypatch, now)
    monkeypatch.setattr(simone, 'load_effective_registry', lambda: ({'events': []}, {}))
    report = next(r for r in json.loads(simone.REPORTS_CONFIG.read_text())['reports'] if r['id'] == 'tna_impact')
    config = tmp_path / 'reports.json'
    config.write_text(json.dumps({'reports': [report]}))
    monkeypatch.setattr(simone, 'REPORTS_CONFIG', config)
    return paths


@pytest.mark.parametrize('day', ['2026-10-16', '2026-01-16'])
def test_deadline_is_rome_0830_in_summer_and_winter(day):
    before = datetime.fromisoformat(day + 'T08:29:59').replace(tzinfo=ROME)
    at = before.replace(hour=8, minute=30, second=0)
    event_day = (before.date() - integrity.timedelta(days=1)).isoformat()
    row = item()
    assert integrity.choose_report_source([row], event_day, before) is None
    assert integrity.choose_report_source([row], event_day, at.astimezone(ZoneInfo('UTC'))) is row


def test_first_scan_after_deadline_uses_publication_time_not_feed_order():
    now = datetime(2026, 10, 16, 8, 43, tzinfo=ROME)
    fallback = item()
    timely = item('ringsidenews', published='Fri, 16 Oct 2026 06:29:59 +0000')
    late = item('ringsidenews', published='2026-10-16T06:30:01Z')
    assert integrity.choose_report_source([fallback, timely], '2026-10-15', now) is timely
    assert integrity.choose_report_source([late, fallback], '2026-10-15', now) is fallback
    assert integrity.choose_report_source([late], '2026-10-15', now) is None
    assert integrity.choose_report_source([item('ringsidenews', published='')], '2026-10-15', now) is None


def test_weekly_fallback_waits_then_locks_and_ignores_later_ringside_even_after_publication(tmp_path, monkeypatch):
    before = datetime(2026, 10, 16, 8, 29, 59, tzinfo=ROME)
    paths = isolate_weekly(tmp_path, monkeypatch, before)
    fallback = item()
    result = simone.run_simone({'report_candidates': [fallback]})
    assert not result['ready_reports']
    assert not json.loads(paths['PENDING_REPORTS'].read_text())['reports']
    monkeypatch.setattr(simone, 'local_now', lambda: before.replace(minute=30, second=0))
    result = simone.run_simone({'report_candidates': [fallback]})
    chosen = result['ready_reports'][0]
    assert chosen['source_url'] == WV and chosen['source'] == 'wrestleview'
    pending = json.loads(paths['PENDING_REPORTS'].read_text())
    row = pending['reports'][0]
    assert row['canonical_source_locked'] and row['canonical_identity'] == 'wrestleview_results'
    # Even a late-discovered Ringside page with an earlier publication timestamp
    # cannot reopen an elected fallback or replace it in the ready queue.
    monkeypatch.setattr(simone, 'local_now', lambda: before.replace(hour=9))
    result = simone.run_simone({'report_candidates': [item('ringsidenews')]})
    assert [r['source_url'] for r in result['ready_reports']] == [WV]
    pending = json.loads(paths['PENDING_REPORTS'].read_text())
    pending['reports'][0]['status'] = 'published'
    paths['PENDING_REPORTS'].write_text(json.dumps(pending))
    paths['REPORT_STATUS_FILE'].write_text(json.dumps({chosen['report_key']: {'status': 'published', 'source_url': WV, 'wp_post_id': 42}}))
    result = simone.run_simone({'report_candidates': [item('ringsidenews')]})
    assert not result['ready_reports'] and result['skipped_reports'][0]['reason'] == 'already_published'
    assert len(json.loads(paths['PENDING_REPORTS'].read_text())['reports']) == 1


def test_timely_ringside_lock_remains_canonical_after_deadline(tmp_path, monkeypatch):
    before = datetime(2026, 10, 16, 6, 29, tzinfo=ROME)
    paths = isolate_weekly(tmp_path, monkeypatch, before)
    simone.run_simone({'report_candidates': [item(), item('ringsidenews')]})
    monkeypatch.setattr(simone, 'local_now', lambda: before.replace(hour=9))
    assert simone.run_simone({'report_candidates': [item()]})['ready_reports'][0]['source_url'] == RS


def test_special_event_fallback_does_not_reserve_early_and_locks_across_runs(tmp_path, monkeypatch):
    before = datetime(2026, 8, 31, 8, 29, 59, tzinfo=ROME)
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, before)
    config = tmp_path / 'reports.json'; config.write_text('{"reports": []}')
    monkeypatch.setattr(simone, 'REPORTS_CONFIG', config)
    source = {**candidate('AEW All In 2026 Results 8/30/26', 'https://www.wrestleview.com/aew-all-in/12-aew-all-in-results-8-30-26'), 'source': 'wrestleview'}
    source = _with_structured_match(source, cfg)
    assert source['special_event_match']['canonical_identity'] == 'wrestleview_results'
    result = simone.run_simone({'report_candidates': [source]})
    assert not result['ready_reports'] and not json.loads(paths['PENDING_REPORTS'].read_text())['reports']
    monkeypatch.setattr(simone, 'local_now', lambda: before.replace(minute=30, second=0))
    result = simone.run_simone({'report_candidates': [source]})
    assert [r['source_url'] for r in result['ready_reports']] == [source['url']]
    monkeypatch.setattr(simone, 'local_now', lambda: before.replace(hour=9))
    late = _with_structured_match(candidate('AEW All In 2026 Results 8/30/26'), cfg)
    assert simone.run_simone({'report_candidates': [late]})['ready_reports'][0]['source_url'] == source['url']


@pytest.mark.parametrize('title', ['TNA IMPACT Quick Results 10/15/26', 'TNA IMPACT Spoiler Results 10/15/26', 'TNA IMPACT Results Preview 10/15/26'])
def test_ineligible_fallback_is_not_a_canonical_source(title):
    assert not integrity.is_canonical_report_source(item(title=title))


def test_wrong_date_and_spoofed_hosts_cannot_be_fallback():
    report = {'show_name': 'TNA Impact', 'match_keywords': ['impact results']}
    assert not simone.candidate_matches_report(item(title='TNA IMPACT on AMC Results 10/14/26'), report, '2026-10-15')
    assert not integrity.is_canonical_report_source({**item(), 'url': WV.replace('wrestleview.com', 'wrestleview.com.evil.test')})


def test_feed_is_report_only_and_routes_full_results_to_simone():
    feeds = json.loads((Path(massy.FEEDS_CONFIG)).read_text())['feeds']
    feed = next(f for f in feeds if f['id'] == 'wrestleview')
    assert feed['reports_only'] is True
    ordinary = {**item(title='New WWE signing announced'), 'url': 'https://www.wrestleview.com/news/signing/', 'reports_only': True}
    report = {**item(), 'reports_only': True}
    board = massy.classify_entries([ordinary, report], set(), set(), {'events': []})
    assert not board['news_candidates_for_menzo']
    assert [r['url'] for r in board['report_candidates']] == [WV]


def test_wrestleview_cleanup_preserves_match_text_and_media_order():
    source = '''<div class="entry-content"><p>Results for this week’s TNA IMPACT are courtesy of TNAWrestling.com:</p>
    <p>TNA Impact Results October 15, 2026. Results by: Mike Tedesco of Wrestleview.com</p>
    <p>The Hardys discuss their 35-year career and welcome the champion.</p>
    <iframe src="https://www.youtube.com/embed/aBcD123"></iframe>
    <p>Trey Miguel wins the ladder match. The champion shakes his hand.</p>
    <p>Email – mike@wrestleview.com</p><p>X – @MikeTedescoWV</p>
    <p>Check out our retro recaps of WWF Raw every Thursday on Wrestleview!</p></div>'''
    blocks = extract_report_blocks(source, WV)
    assert [b['type'] for b in blocks] == ['paragraph', 'paragraph', 'embed', 'paragraph']
    assert '35-year career' in blocks[1]['text'] and blocks[2]['url'].endswith('aBcD123')
    text = ' '.join(b.get('text', '') for b in blocks)
    assert all(x not in text for x in ['courtesy', 'Results by:', 'mike@', 'retro recaps'])


def test_materiality_policy_changes_pair_contract_without_touching_first_classes():
    assert active.RELATION_POLICY_PATH.name.endswith('_V4.md')
    kwargs = dict(policy_version=active.POLICY_VERSION, model=active.MODEL,
                  gate_schema_path=active.RELATION_SCHEMA_PATH, event_registry_path=active.EVENT_REGISTRY_PATH)
    assert pair_cache.contract_fingerprint(policy_path=active.RELATION_POLICY_PATH, **kwargs) != pair_cache.contract_fingerprint(policy_path=active.RELATION_POLICY_PATH.with_name('OWTV_DUPLICATE_JUDGMENT_POLICY_V3.md'), **kwargs)


def test_special_source_order_cannot_lock_fallback_before_timely_ringside(tmp_path, monkeypatch):
    now = datetime(2026, 8, 31, 6, 30, tzinfo=ROME)
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, now)
    fallback = _with_structured_match({**candidate('AEW All In 2026 Results 8/30/26', 'https://www.wrestleview.com/aew-all-in-results-8-30-26'), 'source': 'wrestleview'}, cfg)
    primary = _with_structured_match(candidate('AEW All In 2026 Results 8/30/26'), cfg)
    result = simone.run_simone({'report_candidates': [fallback, primary]})
    key = primary['special_event_match']['report_key']
    assert [r['source_url'] for r in result['ready_reports'] if r['report_key'] == key] == [primary['url']]
    rows = json.loads(paths['PENDING_REPORTS'].read_text())['reports']
    assert not any(r.get('source') == 'wrestleview' for r in rows)


def test_stale_pending_fallback_cannot_override_deadline_or_timely_primary(tmp_path, monkeypatch):
    now = datetime(2026, 10, 16, 8, 20, tzinfo=ROME)
    paths = isolate_weekly(tmp_path, monkeypatch, now)
    invalid = {**item(), 'source_url': WV, 'source_title': item()['title'],
               'report_key': 'tna_impact_2026_10_15', 'report_id': 'tna_impact',
               'date_local': '2026-10-15', 'publish_date_local': '2026-10-16',
               'canonical_source_locked': True, 'canonical_identity': 'wrestleview_results',
               'status': 'waiting_publish_after', 'discovered_at': now.isoformat(),
               'source_selection_policy': integrity.REPORT_SOURCE_POLICY}
    paths['PENDING_REPORTS'].write_text(json.dumps({'reports': [invalid]}))
    result = simone.run_simone({'report_candidates': [item('ringsidenews')]})
    assert [r['source_url'] for r in result['ready_reports']] == [RS]
