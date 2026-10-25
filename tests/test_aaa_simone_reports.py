"""AAA results are Simone reports; specials occupy the corresponding weekly slot."""
import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from agents import massy, simone
from modules import simone_report_integrity as integrity
from test_totem_r01_report_contract import _isolated_simone

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'config/special_events.json').read_text())
WEEKLY = next(r for r in json.loads((ROOT / 'config/reports_v92.json').read_text())['reports'] if r['id'] == 'aaa_on_fox')
ROME = ZoneInfo('Europe/Rome')
URL = 'https://www.ringsidenews.com/aaa-heroes-inmortales-results-stream-highlights-key-moments-october-24-2026/'

def item(title='AAA Heroes Inmortales Results (10/24/26)', url=URL):
    return {'title': title, 'url': url, 'source': 'ringsidenews', 'published': '2026-10-25T01:30:00Z'}

@pytest.mark.parametrize('title', ['Lucha Libre AAA Results October 31, 2026', 'AAA on Fox Results October 31, 2026', 'AAA Results October 31, 2026', 'AAA Heroes Inmortales Week 2 Results October 31, 2026'])
def test_weekly_results_route_and_match(title):
    candidate = item(title, 'https://www.ringsidenews.com/'+title.lower().replace(' ', '-'))
    routed = massy.classify_entries([candidate], set(), set(), CFG)
    assert len(routed['report_candidates']) == 1
    assert not routed['news_candidates_for_menzo']
    assert simone.candidate_matches_report(candidate, WEEKLY, '2026-10-31')
    assert not simone.candidate_matches_report(candidate, WEEKLY, '2026-10-17')

@pytest.mark.parametrize('title', ['El Grande Americano Defeats Dominik Mysterio at AAA Heroes Inmortales', 'AAA announces Guerra de Titanes', 'AAA Heroes Inmortales Match Card October 24, 2026', 'Mini Vikingo Injury Update after AAA'])
def test_dedicated_news_and_previews_do_not_become_reports(title):
    result = massy.classify_entries([item(title, 'https://www.ringsidenews.com/'+title.lower().replace(' ', '-'))], set(), set(), CFG)
    assert not result['report_candidates']
    assert len(result['news_candidates_for_menzo']) == 1


def isolate(tmp_path, monkeypatch, now):
    paths, cfg = _isolated_simone(tmp_path, monkeypatch, now)
    cfg.clear(); cfg.update(copy.deepcopy(CFG))
    config = tmp_path/'weekly.json';config.write_text(json.dumps({'reports': [WEEKLY]}))
    monkeypatch.setattr(simone, 'REPORTS_CONFIG', config)
    special = tmp_path/'special.json';special.write_text(json.dumps(cfg))
    monkeypatch.setattr(simone, 'SPECIAL_EVENTS_CONFIG', special)
    return paths, cfg

@pytest.mark.parametrize('hour,minute,expected', [(6,29,0),(6,30,1),(8,45,1)])
def test_special_owns_weekly_slot_and_deadline(tmp_path, monkeypatch, hour, minute, expected):
    paths,cfg=isolate(tmp_path, monkeypatch, datetime(2026,10,25,hour,minute,tzinfo=ROME))
    candidate=item();match,reason=integrity.dynamic_special_event_match(candidate,cfg)
    assert match and reason == 'canonical_results_match'
    candidate['special_event_match']=match
    result=simone.run_simone({'report_candidates':[candidate, item('AAA on Fox Results October 24, 2026','https://www.ringsidenews.com/aaa-on-fox-results-october-24-2026')]})
    assert len(result['ready_reports']) == expected
    assert all(r['report_type']=='special_event' and r['counts_as_news'] is False for r in result['ready_reports'])
    assert any(r['reason']=='replaced_by_scheduled_special' for r in result['skipped_reports'])
    assert not any(r.get('report_id')=='aaa_on_fox' for r in json.loads(paths['PENDING_REPORTS'].read_text())['reports'])


def test_published_special_prevents_later_weekly_or_alternate_source(tmp_path,monkeypatch):
    paths,cfg=isolate(tmp_path,monkeypatch,datetime(2026,10,25,9,tzinfo=ROME))
    key='special_event_aaa_heroes_inmortales_2026_main_2026_10_24'
    paths['SIMONE_REPORT_HISTORY_FILE'].write_text(json.dumps({key:{'report_key':key,'wp_post_id':14121,'source_url':URL,'date':'2026-10-24','report_completion':{'version':'totem-r01-completion-v1','report_key':key,'date':'2026-10-24'}}}))
    result=simone.run_simone({'report_candidates':[item()]})
    assert not result['ready_reports']
    assert any(r['reason']=='already_published' and r.get('report_key')==key for r in result['skipped_reports'])


def test_regular_weekly_and_undated_specials(tmp_path,monkeypatch):
    paths,cfg=isolate(tmp_path,monkeypatch,datetime(2026,11,1,6,30,tzinfo=ROME))
    result=simone.run_simone({'report_candidates':[item('AAA Heroes Inmortales Week 2 Results October 31, 2026','https://www.ringsidenews.com/aaa-heroes-inmortales-week-2-results-october-31-2026')]})
    assert len(result['ready_reports'])==1
    assert result['ready_reports'][0]['report_key']=='aaa_on_fox_2026_10_31'
    assert result['ready_reports'][0]['categories']==['Editoriali','World']
    assert not result['expected_special_events']


def test_aaa_runtime_schedule_is_supported():
    result,diagnostics=integrity.build_effective_registry({'events':[]},[{'promotion':'AAA','event_name':'Guerra de Titanes','dates':['2026-12-19']}])
    event=result['events'][0]
    assert event['category_hint']=='World'
    assert event['replaces_weekly_report_ids']==['aaa_on_fox']
    assert integrity.weekly_special_override(WEEKLY,'2026-12-19',result)==event
    assert not integrity.weekly_special_override(WEEKLY,'2026-12-12',result)


def test_confirmed_dates_do_not_invent_later_parts():
    heroes=next(e for e in CFG['events'] if e['key']=='aaa_heroes_inmortales_2026')
    assert [n['date_local'] for n in heroes['nights']]==['2026-10-24']
    guerra=next(e for e in CFG['events'] if e['key']=='aaa_guerra_de_titanes_2026')
    assert guerra['status']=='confirmed' and guerra['nights'][0]['date_local']=='2026-12-19'


def test_runtime_special_invalidates_pending_weekly_lock(tmp_path,monkeypatch):
    paths,cfg=isolate(tmp_path,monkeypatch,datetime(2026,11,1,7,tzinfo=ROME))
    # This special exists only in the effective registry, not the seed file.
    event=copy.deepcopy(next(e for e in cfg['events'] if e['key']=='aaa_heroes_inmortales_2026'))
    event.update(key='aaa_runtime_special_2026',event_name='Runtime Special',aliases=['AAA Runtime Special'])
    event['nights']=[{'night_key':'aaa_runtime_special_2026_main','date_local':'2026-10-31','enabled':True}]
    cfg['events'].append(event)
    key='aaa_on_fox_2026_10_31'
    paths['PENDING_REPORTS'].write_text(json.dumps({'reports':[{'report_key':key,'report_id':'aaa_on_fox','date_local':'2026-10-31','publish_date_local':'2026-11-01','publish_after':'06:30','source':'ringsidenews','source_title':'AAA on Fox Results October 31, 2026','source_url':'https://www.ringsidenews.com/aaa-on-fox-results-october-31-2026','canonical_source_locked':True,'canonical_identity':'ringsidenews_results','status':'waiting_publish_after'}]}))
    result=simone.run_simone({'report_candidates':[]})
    assert not result['ready_reports']
    row=json.loads(paths['PENDING_REPORTS'].read_text())['reports'][0]
    assert row['status']=='invalid_canonical_identity' and row['canonical_source_locked'] is False
    assert any(r['event_key']=='aaa_runtime_special_2026' for r in result['special_missing'])
