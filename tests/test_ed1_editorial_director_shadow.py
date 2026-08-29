import copy
import threading
import time
from pathlib import Path

from agents import gemini_diagnostics
from agents import menzo_editorial_director_shadow as ed
from agents.duplicate_pair_identity import article_id


def snapshot(count=1, history=None):
    board={'news_candidates_for_menzo':[{'source':'x','title':f'Story {i}','url':f'https://example.com/{i}','summary':'fact'} for i in range(count)]}
    return ed.capture_opportunity(board,run_id='run',observation_timestamp='2026-01-01T00:00:00+00:00',publisher_count_24h=3,history=history or [])


def valid(s):
    return {'schema_version':ed.SCHEMA_VERSION,'policy_version':ed.POLICY_VERSION,
      'candidates':[{'candidate_id':x['candidate_id'],'editorial_class':'SHOULD_PUBLISH','recommended_action':'SELECT','relative_rank':i+1,'category':'WWE','story_core':'A factual event','confidence':'HIGH','reason_codes':['HARD_NEWS']} for i,x in enumerate(s['candidates'])], 'relations':[]}


def test_flag_defaults_false_and_capture_is_deep_copy(monkeypatch):
    monkeypatch.delenv('OWTV_EDITORIAL_DIRECTOR_SHADOW_ENABLED',raising=False); assert not ed.enabled()
    board={'news_candidates_for_menzo':[{'title':'A','url':'https://x.test/a','summary':'old'}]}; s=ed.capture_opportunity(board,run_id='r',observation_timestamp='t',publisher_count_24h=0,history=[])
    board['news_candidates_for_menzo'][0]['summary']='new'; assert s['candidates'][0]['summary']=='old'


def test_shadow_reuses_live_softpool_augmentation_without_board_mutation(monkeypatch):
    from agents import menzo_policy_v93_15 as menzo
    board={'news_candidates_for_menzo':[{'title':'Fresh','url':'https://x.test/fresh'}], 'softpool':{'existing':True}}
    original=copy.deepcopy(board)
    eligible={'title':'Eligible soft','url':'https://x.test/soft','from_softpool':True}
    monkeypatch.setattr(menzo,'load_softpool',lambda:[copy.deepcopy(eligible)])
    shadow_board=ed.softpool_augmented_board(board)
    legacy_start=menzo.augment_board_with_softpool(copy.deepcopy(board))
    assert {article_id(x) for x in shadow_board['news_candidates_for_menzo']} == {article_id(x) for x in legacy_start['news_candidates_for_menzo']}
    assert board == original


def test_prompt_is_frozen_policy_and_input_excludes_legacy_editorial_fields():
    board={'news_candidates_for_menzo':[{'title':'A','url':'https://x.test/a','summary':'fact','score':99,'category_hint':'Business','reason':'legacy'}]}
    s=ed.capture_opportunity(board,run_id='r',observation_timestamp='t',publisher_count_24h=0,history=[])
    prompt=ed.build_prompt(s); input_text=prompt.split('INPUT=',1)[1]
    assert ed.POLICY_VERSION in prompt and 'keyword present ≠ central fact' in prompt and 'same person != duplicate' in prompt
    assert all(token not in input_text for token in ('"score"','category_hint','"reason"'))


def test_valid_primary_and_invalid_called_then_valid_repair(monkeypatch):
    ledger=[]; monkeypatch.setattr(ed,'record_gemini_attempt',lambda **kw: ledger.append(kw))
    s=snapshot(); before=copy.deepcopy(s); calls=[]
    def provider(*args): calls.append(1); return valid(s) if len(calls)==2 else '{}'
    result=ed.evaluate(s,{},provider=provider)
    assert result['status']=='VALIDATED' and result['attempts']==2 and [x['status'] for x in ledger]==['called','called']
    assert ledger[1]['repair'] is True and s==before


def test_validation_coverage_and_material_update():
    s=snapshot(); value=valid(s); value['candidates']=[]
    assert any('coverage' in x for x in ed.validate_output(value,s))
    s['authorized_relations']=[{'pair_id':'p','scope':'same_run','left_id':'a','right_id':'b'}]
    value=valid(s); value['relations']=[{'pair_id':'p','scope':'same_run','left_id':'a','right_id':'b','decision':'MATERIAL_UPDATE','new_fact':'x','temporal_basis':'today','confidence':'HIGH','reason_codes':[]}]
    assert any('MATERIAL_UPDATE' in x for x in ed.validate_output(value,s))


def test_oversize_zero_attempts(monkeypatch):
    s=snapshot(); s['limit_status']='exceeded'; called=[]
    result=ed.evaluate(s,{},provider=lambda *x: called.append(1)); assert result['status']=='OVERSIZE_NOT_EVALUATED' and not called


def test_blocking_provider_timeout_returns_without_join(monkeypatch):
    release=threading.Event(); s=snapshot(); ledger=[]
    monkeypatch.setattr(ed,'PROVIDER_TIMEOUT_SECONDS',.05); monkeypatch.setattr(ed,'record_gemini_attempt',lambda **kw:ledger.append(kw))
    started=time.monotonic()
    result=ed.evaluate(s,{},provider=lambda *_: release.wait(2))
    elapsed=time.monotonic()-started; release.set()
    assert result['error']=='TimeoutError' and elapsed < .5 and [x['status'] for x in ledger]==['failed']


def test_provider_exception_is_failed_and_no_repair(monkeypatch):
    ledger=[]; monkeypatch.setattr(ed,'record_gemini_attempt',lambda **kw:ledger.append(kw)); s=snapshot(); before=copy.deepcopy(s)
    result=ed.evaluate(s,{},provider=lambda *x: (_ for _ in ()).throw(ConnectionError()))
    assert result['attempts']==1 and [x['status'] for x in ledger]==['failed'] and s==before


def test_precall_missing_key_has_zero_real_attempts(monkeypatch):
    ledger=[]; monkeypatch.delenv('GEMINI_API_KEY',raising=False); monkeypatch.setattr(ed,'record_gemini_attempt',lambda **kw:ledger.append(kw))
    result=ed.evaluate(snapshot(),{})
    assert result['status']=='PROVIDER_UNAVAILABLE' and result['attempts']==0 and ledger==[]


def test_cost_availability_null_vs_zero():
    unavailable=gemini_diagnostics.build_gemini_diagnostics([],economic_available=False)['editorial_director_shadow']
    complete=gemini_diagnostics.build_gemini_diagnostics([],economic_available=True)['editorial_director_shadow']
    assert unavailable['provider_attempts'] is unavailable['known_cost'] is None
    assert complete['provider_attempts']==0 and complete['known_cost']=='0' and complete['complete_window_cost']=='0'
    assert complete['bound_status'] is None and 'partial' in complete['bound_status_availability']


def test_retained_history_body_survives_capture():
    history={'source_url':'https://old.test/a','title':'Old','published_at':'2026-01-01T00:00:00+00:00','canonical_source_body':{'text':'retained factual body'}}
    s=snapshot(history=[history]); assert s['publisher_history_12h'][0]['retained_body']=='retained factual body'
    assert s['publisher_history_12h'][0]['input_coverage']=='RETAINED_BODY_AVAILABLE'


def test_artifact_uses_category_hint_and_event_links_exact_package(tmp_path):
    import json
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    from agents.canonical_event_ledger import CanonicalEventLedger, clear_active_ledger, install_active_ledger
    s=snapshot(); out=valid(s); candidate=s['candidates'][0]
    ledger_path=tmp_path/'events.jsonl'; ledger=CanonicalEventLedger('run',path=ledger_path,enabled=True)
    install_active_ledger(ledger)
    index=CanonicalArtifactIndex('run',index_path=tmp_path/'index.jsonl',material_root=tmp_path/'material',repository_root=tmp_path,enabled=True)
    try:
        index.observe_editorial_director_shadow(s,out,{'selected':[{'url':candidate['url'],'priority':'hard','category_hint':'AEW'}]},
                                                {'logical_request_id':'lrq_test','status':'VALIDATED'})
    finally: clear_active_ledger()
    package_path=next((tmp_path/'material').rglob('editorial-director-shadow-*.json'))
    package=json.loads(package_path.read_text()); assert package['legacy_menzo']['category']=='AEW'
    events=[json.loads(x) for x in ledger_path.read_text().splitlines()]
    event=next(x for x in events if x.get('result')=='editorial_director_shadow_evaluated')
    assert event['artifact_refs'][0]['path']==package_path.relative_to(tmp_path).as_posix()


def test_relation_event_has_pair_id_and_joinable_artifact(tmp_path):
    import json
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    from agents.canonical_event_ledger import CanonicalEventLedger, clear_active_ledger, install_active_ledger
    s=snapshot(2); left,right=[x['candidate_id'] for x in s['candidates']]
    relation={'pair_id':'pair_sr_test','scope':'same_run','left_id':left,'right_id':right,'decision':'NO_MATCH','new_fact':None,'temporal_basis':None,'confidence':'HIGH','reason_codes':['DISTINCT_FACT']}
    out=valid(s); out['relations']=[relation]
    ledger_path=tmp_path/'events.jsonl'; install_active_ledger(CanonicalEventLedger('run',path=ledger_path,enabled=True))
    index=CanonicalArtifactIndex('run',index_path=tmp_path/'index.jsonl',material_root=tmp_path/'material',repository_root=tmp_path,enabled=True)
    try: index.observe_editorial_director_shadow(s,out,{}, {'logical_request_id':'lrq_test','status':'VALIDATED'})
    finally: clear_active_ledger()
    events=[json.loads(x) for x in ledger_path.read_text().splitlines()]
    event=next(x for x in events if x.get('pair_id')=='pair_sr_test')
    assert event['artifact_refs'] and (tmp_path/event['artifact_refs'][0]['path']).exists()


def test_wp_not_ready_uses_menzo_authority_and_preserves_empty_path(monkeypatch):
    from agents import menzo_policy_v93_15 as menzo
    board={'news_candidates_for_menzo':[{'title':'Fresh','url':'https://x.test/fresh'}]}; original=copy.deepcopy(board)
    checks=[]
    monkeypatch.setattr(menzo,'_wp_ready_for_costly_work',lambda:(checks.append(1) or (False,'wp_not_ready')))
    preflight=ed.costly_work_eligibility()
    monkeypatch.setattr(menzo,'_wp_ready_for_costly_work',lambda:(_ for _ in ()).throw(AssertionError('second check')))
    monkeypatch.setattr(menzo,'augment_board_with_softpool',lambda _board:(_ for _ in ()).throw(AssertionError('capture/work')))
    expected={'status':'skipped','reason':'wp_not_ready','selected':[]}
    monkeypatch.setattr(menzo,'_empty_menzo_when_wp_unready',lambda reason:{**expected,'reason':reason})
    assert menzo.run_menzo(board,costly_work_preflight=preflight)==expected
    assert checks==[1] and board==original


def test_wp_ready_preflight_is_reused_and_original_board_is_unchanged(monkeypatch):
    import pytest
    from agents import menzo_policy_v93_15 as menzo
    board={'news_candidates_for_menzo':[{'title':'Fresh','url':'https://x.test/fresh'}]}; original=copy.deepcopy(board)
    monkeypatch.setattr(menzo,'_wp_ready_for_costly_work',lambda:(True,'ready'))
    preflight=ed.costly_work_eligibility()
    shadow=ed.softpool_augmented_board(board)
    assert shadow is not board
    monkeypatch.setattr(menzo,'_wp_ready_for_costly_work',lambda:(_ for _ in ()).throw(AssertionError('second check')))
    monkeypatch.setattr(menzo.base,'run_menzo',lambda received,**_kwargs:(_ for _ in ()).throw(RuntimeError('reached_scoring')) if received is not board else (_ for _ in ()).throw(AssertionError('original board passed')))
    with pytest.raises(RuntimeError,match='reached_scoring'):
        menzo.run_menzo(board,costly_work_preflight=preflight)
    assert board==original


def test_runner_wp_ineligible_skips_capture_and_provider_opportunity(monkeypatch):
    import newsroom_runner
    from agents import menzo_editorial_director_shadow as shadow
    board={'news_candidates_for_menzo':[{'title':'Fresh','url':'https://x.test/fresh'}]}; original=copy.deepcopy(board)
    monkeypatch.setattr(shadow,'costly_work_eligibility',lambda:(False,'wp_not_ready'))
    monkeypatch.setattr(shadow,'softpool_augmented_board',lambda _board:(_ for _ in ()).throw(AssertionError('augmented')))
    monkeypatch.setattr(shadow,'capture_opportunity',lambda *_a,**_k:(_ for _ in ()).throw(AssertionError('captured')))
    captured,result,preflight=newsroom_runner.capture_editorial_director_opportunity(board,run_id='run',observation_timestamp='now')
    assert captured is None and result=={'status':'NOT_ELIGIBLE_WP_NOT_READY','reason':'wp_not_ready','attempts':0}
    assert preflight==(False,'wp_not_ready') and board==original


def test_runner_wp_ready_captures_using_existing_softpool_helper(monkeypatch):
    import newsroom_runner
    from agents import menzo_editorial_director_shadow as shadow
    from agents import menzo_policy_v93_15 as menzo
    board={'news_candidates_for_menzo':[{'title':'Fresh','url':'https://x.test/fresh'}]}; original=copy.deepcopy(board)
    monkeypatch.setattr(shadow,'costly_work_eligibility',lambda:(True,'ready'))
    monkeypatch.setattr(menzo,'load_authoritative_publisher_history',lambda hours:[])
    captured,result,preflight=newsroom_runner.capture_editorial_director_opportunity(board,run_id='run',observation_timestamp='now')
    assert captured is not None and result is None and preflight==(True,'ready')
    assert {x['candidate_id'] for x in captured['candidates']}=={article_id(board['news_candidates_for_menzo'][0])}
    assert board==original
