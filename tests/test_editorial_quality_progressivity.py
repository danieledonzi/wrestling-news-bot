"""Rolling boundaries, immutable priority and terminal pressure exclusions."""
from datetime import datetime, timedelta, timezone
import copy
import json

import pytest

from agents import editorial_publication_policy as pressure
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_primary_classification_store as primary
from agents import menzo_priority_queue as queue
from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow

NOW = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)


def article(name, cls='SHOULD_PUBLISH', priority=False):
    return {'url': 'https://quality.test/' + name, 'title': name,
            'editorial_director': {'editorial_class': cls, 'coverage_priority': priority,
                'recommended_action': {'SKIP': 'SKIP', 'PUBLISHABLE_SOFT': 'DEFER'}.get(cls, 'SELECT'),
                'category': 'WWE', 'story_core': 'A supported current professional development'}}


def history(n):
    return {f'https://history.test/{i}': {'source_url': f'https://history.test/{i}',
        'published_at': (NOW - timedelta(hours=3)).isoformat(), 'status': 'publish'} for i in range(n)}


def isolate(monkeypatch, tmp_path, n):
    monkeypatch.setattr(menzo, 'SOFTPOOL_FILE', tmp_path / 'soft.json')
    monkeypatch.setattr(menzo, 'publisher_history_file', lambda: tmp_path / 'history.json')
    (tmp_path / 'history.json').write_text(json.dumps(history(n)))
    from agents import bob
    monkeypatch.setattr(bob, 'dynamic_article_capacity', lambda *_: (10, 'fixture'))


@pytest.mark.parametrize('count,cls,priority,allowed', [
    (0, 'SHOULD_PUBLISH', False, True), (24, 'SHOULD_PUBLISH', False, True),
    (25, 'SHOULD_PUBLISH', False, False), (25, 'SHOULD_PUBLISH', True, True),
    (29, 'SHOULD_PUBLISH', True, True), (30, 'SHOULD_PUBLISH', True, False),
    (24, 'PUBLISHABLE_SOFT', False, True), (25, 'PUBLISHABLE_SOFT', False, False),
    (43, 'MUST_PUBLISH', False, True)])
def test_pressure_boundary(count, cls, priority, allowed):
    assert (pressure.rejection_reason(article('a', cls, priority), count) is None) == allowed


def test_counter_survives_midnight_excludes_reports_failures_and_exact_lower_boundary():
    rows = list(history(25).values())
    rows += [dict(rows[0]),  # repeated canonical URL is not a second news
             {'source_url': 'https://history.test/old', 'status': 'publish', 'published_at': (NOW-timedelta(hours=24)).isoformat()},
             {'source_url': 'https://history.test/report', 'status': 'publish', 'article_type': 'report', 'published_at': NOW.isoformat()},
             {'source_url': 'https://history.test/dry', 'status': 'publish', 'dry_run': True, 'published_at': NOW.isoformat()},
             {'source_url': 'https://history.test/error', 'status': 'publish_error', 'published_at': NOW.isoformat()}]
    assert pressure.published_count(rows, now=NOW) == 25


def test_batch_cannot_cross_25_and_rejected_url_never_returns(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path, 24)
    a, b = article('a'), article('b')
    primary.remember([dict(a, candidate_id='a'), dict(b, candidate_id='b')],
        [dict(a['editorial_director'], candidate_id='a'), dict(b['editorial_director'], candidate_id='b')],
        when=NOW.isoformat(), policy=active.POLICY_VERSION)
    projected = {'selected': [a,b], 'pending': [], 'skipped': []}
    queue.schedule(projected, {'observation_timestamp': NOW.isoformat()})
    assert [r['url'] for r in projected['selected']] == [a['url']]
    assert projected['skipped'][0]['url'] == b['url']
    assert projected['skipped'][0]['editorial_director']['editorial_class'] == 'SHOULD_PUBLISH'
    assert menzo.source_key(b['url']) in menzo.terminal_skip_memory()
    assert primary.load()[menzo.source_key(b['url'])]['editorial_class'] == 'SHOULD_PUBLISH'
    assert [r['url'] for r in queue._read()] == [a['url']]
    refreshed = queue.augment_board({'news_candidates_for_menzo': [b]})
    assert b['url'] not in [r['url'] for r in refreshed['news_candidates_for_menzo']]


def test_must_reserved_first_priority_should_sorted_before_ordinary(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path, 28)
    ordinary, high, high2, must = article('ordinary'), article('high', priority=True), article('high2', priority=True), article('must','MUST_PUBLISH')
    projected={'selected':[ordinary,high,high2,must], 'pending':[], 'skipped':[]}
    queue.schedule(projected, {'observation_timestamp': NOW.isoformat()})
    assert [r['url'] for r in projected['selected']] == [must['url'],high['url']]
    assert len(projected['skipped']) == 2
    assert not projected['pending']


def test_soft_headroom_reserves_strong_and_does_not_reset_at_midnight(monkeypatch,tmp_path):
    isolate(monkeypatch,tmp_path,24)
    assert pressure.soft_remaining([article('a')], now=NOW) == 0
    assert pressure.soft_remaining([], now=NOW) == 1


def test_primary_priority_round_trip_is_frozen(monkeypatch,tmp_path):
    a=article('priority', priority=True)
    primary.remember([dict(a,candidate_id='a')], [dict(a['editorial_director'],candidate_id='a')],when=NOW.isoformat(),policy=active.POLICY_VERSION)
    primary.remember([dict(a,candidate_id='a')], [dict(a['editorial_director'],candidate_id='a',coverage_priority=False)],when=NOW.isoformat(),policy='new')
    restored=primary.decision(primary.load()[menzo.source_key(a['url'])], 'new-local-ref')
    assert restored['coverage_priority'] is True
    assert restored['editorial_class'] == 'SHOULD_PUBLISH'


def test_active_validates_priority_without_changing_shadow_contract():
    s=shadow.capture_opportunity({'news_candidates_for_menzo':[{'url':'https://quality.test/a','title':'A'}]},run_id='test',observation_timestamp=NOW.isoformat(),publisher_count_24h=0,history=[])
    row={'ref':'c0',**article('a')['editorial_director']}
    out,errors,_=active._validate_active({'candidates':[row],'relations':[]},s)
    assert not errors and out['candidates'][0]['coverage_priority'] is False
    for value,cls in [('true','SHOULD_PUBLISH'),(True,'PUBLISHABLE_SOFT')]:
        bad={**row,'coverage_priority':value,'editorial_class':cls,'recommended_action':'DEFER' if cls=='PUBLISHABLE_SOFT' else 'SELECT'}
        assert active._validate_active({'candidates':[bad],'relations':[]},s)[1]


def test_pressure_report_never_sums_snapshot_counts():
    from scripts.current_editorial_report import publication_pressure_observation
    runs=[{'recorded_at':(NOW+timedelta(minutes=i)).isoformat(), 'run':{'started_at':(NOW+timedelta(minutes=i)).isoformat()},
        'editorial_pipeline':{'scheduling':{'publication_pressure':{'published_news_24h':25,
            'terminal_skipped':[{'url':'https://quality.test/a','reason':'publication_pressure:25_priority_should_only'}]}}}} for i in (0,1)]
    data=publication_pressure_observation(runs,NOW-timedelta(hours=1),NOW+timedelta(hours=1))
    assert data['terminal_skipped_unique_observed']==1
    assert data['maximum_published_news_24h_at_decision']==25
    assert data['runs_observed']==2


def test_publisher_retry_guard_obeys_30_and_does_not_revive_terminal_skip(monkeypatch,tmp_path):
    from agents import publisher
    isolate(monkeypatch,tmp_path,29)
    rows=history(29)
    # Publisher uses wall time; keep this test independent of today's date.
    for row in rows.values():
        row['published_at']=datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(publisher,'load_json',lambda *_: rows)
    monkeypatch.setattr(publisher,'build_trace_metadata_index',lambda *_: {})
    monkeypatch.setattr(publisher,'publisher_duplicate_safety_filter',lambda a,h:(a,[]))
    monkeypatch.setattr(publisher,'wp_ready',lambda:(True,'fixture'))
    monkeypatch.setattr(publisher,'DRY_RUN',True)
    monkeypatch.setattr(publisher,'MAX_POSTS_PER_RUN',10)
    monkeypatch.setattr(publisher,'write_json',lambda *_:None)
    attempted=[]
    def publish(a,*_):
        attempted.append(a['source_url'])
        return {'source_url':a['source_url'],'status':'dry_run'}
    monkeypatch.setattr(publisher,'publish_article',publish)
    candidates=[article('priority-1',priority=True),article('priority-2',priority=True),article('ordinary')]
    for a in candidates:a.update(source_url=a['url'],from_publish_retry_queue=True)
    result=publisher.run_publisher({'approved_articles':candidates})
    assert attempted==[candidates[0]['url']]
    assert result['input']['published_news_24h']==29
    assert result['input']['publication_pressure_skipped']==2
    assert menzo.source_key(candidates[1]['url']) in menzo.terminal_skip_memory()
    # Once pressure has fallen, the same rejected URL still cannot publish.
    rows.clear();attempted.clear()
    result=publisher.run_publisher({'approved_articles':[candidates[1]]})
    assert attempted==[]
    assert result['skipped_approved_articles'][0]['editorial_director']['editorial_class']=='SHOULD_PUBLISH'


def test_pressure_never_overrides_duplicate_clearance(monkeypatch,tmp_path):
    from agents import publisher
    isolate(monkeypatch,tmp_path,0)
    monkeypatch.setattr(publisher,'load_json',lambda *_: {})
    monkeypatch.setattr(publisher,'build_trace_metadata_index',lambda *_: {})
    monkeypatch.setattr(publisher,'wp_ready',lambda:(True,'fixture'))
    monkeypatch.setattr(publisher,'DRY_RUN',True)
    monkeypatch.setattr(publisher,'write_json',lambda *_:None)
    attempted=[]
    monkeypatch.setattr(publisher,'publish_article',lambda *a:attempted.append(a))
    row=article('must-duplicate','MUST_PUBLISH')
    row.update(source_url=row['url'], menzo_duplicate_checked=True,menzo_authorized=False,menzo_duplicate_decision='DUPLICATE')
    result=publisher.run_publisher({'approved_articles':[row]})
    assert not attempted
    assert result['skipped_approved_articles']
