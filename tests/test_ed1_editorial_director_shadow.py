import copy
import json
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


def test_provider_schema_uses_supported_exact_version_enums():
    schema=json.loads(Path('config/editorial_director_output_schema_v1.json').read_text())
    for field, expected in (
        ('schema_version', 'owtv_editorial_director_output_v1'),
        ('policy_version', 'owtv_editorial_director_policy_v1'),
    ):
        version_schema=schema['properties'][field]
        assert version_schema == {'type': 'string', 'enum': [expected]}
        assert 'const' not in version_schema


def test_local_validation_still_rejects_inexact_versions():
    s=snapshot()
    for field in ('schema_version', 'policy_version'):
        output=valid(s)
        output[field]=f'wrong_{field}'
        assert 'invalid schema or policy version' in ed.validate_output(output, s)


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


def test_native_provider_timeout_failure_is_one_attempt_without_repair(monkeypatch):
    s=snapshot(); ledger=[]
    monkeypatch.setattr(ed,'record_gemini_attempt',lambda **kw:ledger.append(kw))
    result=ed.evaluate(s,{},provider=lambda *_: (_ for _ in ()).throw(TimeoutError('native transport timeout')))
    assert result['error']=='TimeoutError' and result['attempts']==1
    assert [x['status'] for x in ledger]==['failed'] and ledger[0]['repair'] is False


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


def test_candidate_oversize_performs_zero_pair_scoring(monkeypatch):
    board={'news_candidates_for_menzo':[{'title':f'Story {i}','url':f'https://oversize.test/{i}'} for i in range(ed.MAX_CANDIDATES+1)]}
    scored=[]; monkeypatch.setattr(ed.menzo_duplicate_scorer,'score_pair',lambda *_a,**_k:scored.append(1))
    result=ed.capture_opportunity(board,run_id='run',observation_timestamp='now',publisher_count_24h=0,history=[])
    assert result['limit_status']=='exceeded' and result['observed']['candidate_count']==ed.MAX_CANDIDATES+1
    assert scored==[]


def test_relation_scan_stops_at_first_proven_oversize(monkeypatch):
    monkeypatch.setattr(ed,'MAX_RELATIONS',3); scored=[]
    monkeypatch.setattr(ed.menzo_duplicate_scorer,'score_pair',lambda *_a,**_k:(scored.append(1) or {'exact_duplicate':False,'above_threshold':True,'scorer_version':'test','score':.9,'threshold':.55,'components':{}}))
    result=snapshot(4)
    assert result['limit_status']=='exceeded' and len(result['authorized_relations'])==4
    assert len(scored)==ed.MAX_RELATIONS+1
    called=[]; evaluated=ed.evaluate(result,{},provider=lambda *_:called.append(1))
    assert evaluated['status']=='OVERSIZE_NOT_EVALUATED' and called==[]


def test_lazy_pair_builders_preserve_list_identity_and_order():
    from agents.duplicate_pair_matrix import (build_recent_history_pair_specs, build_same_run_pair_specs,
                                              iter_recent_history_pair_specs, iter_same_run_pair_specs)
    candidates=[{'url':'https://pairs.test/b'},{'url':'https://pairs.test/a'},{'url':'https://pairs.test/c'}]
    history=[{'url':'https://history.test/2'},{'url':'https://history.test/1'}]
    assert build_same_run_pair_specs(candidates)==list(iter_same_run_pair_specs(candidates))
    assert build_recent_history_pair_specs(candidates,history)==list(iter_recent_history_pair_specs(candidates,history))


def test_closed_relation_scalar_and_reason_code_types():
    s=snapshot(); supplied={'pair_id':'p','scope':'recent_history','left_id':'a','right_id':'b'}
    s['authorized_relations']=[supplied]
    base={'pair_id':'p','scope':'recent_history','left_id':'a','right_id':'b','decision':'NO_MATCH',
          'new_fact':None,'temporal_basis':None,'confidence':'HIGH','reason_codes':['DISTINCT']}
    invalid=[('new_fact',{}),('new_fact',[]),('temporal_basis',{}),('reason_codes',[123]),
             ('reason_codes',['']),('reason_codes',['x'*65])]
    for field,value in invalid:
        output=valid(s); output['relations']=[{**base,field:value}]
        assert ed.validate_output(output,s), (field,value)


def test_shadow_economics_reject_invalid_v3_integrity_despite_available_flag():
    row={'ledger_schema_version':'v3','status':'called','provider_attempt_id':'duplicate','workload':'editorial_director_shadow',
         'logical_request_id':'lrq','attempt_index':0,'repair':False,'fallback':False,'candidate_count':1}
    diag=gemini_diagnostics.build_gemini_diagnostics([row,dict(row)],economic_available=True)
    assert diag['economic']['available'] is False
    shadow=diag['editorial_director_shadow']; assert shadow['source_available'] is False
    for field in ('logical_requests','provider_attempts','primary_attempts','repairs','fallbacks','input_tokens','output_tokens','known_cost','complete_window_cost','cost_per_logical_request','cost_per_evaluated_candidate_occurrence','by_phase'):
        assert shadow[field] is None


def test_final_decorated_snapshot_crossing_bound_is_oversize_and_zero_call(monkeypatch):
    board={'news_candidates_for_menzo':[{'title':'A','url':'https://size.test/a','summary':'x'*2000}]}
    baseline=ed.capture_opportunity(board,run_id='run',observation_timestamp='now',publisher_count_24h=0,history=[])
    pre={k:v for k,v in baseline.items() if k not in {'observed','limits','limit_status','input_digest'}}
    preliminary_size=len(json.dumps(pre,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    monkeypatch.setattr(ed,'MAX_INPUT_BYTES',preliminary_size+10)
    result=ed.capture_opportunity(board,run_id='run',observation_timestamp='now',publisher_count_24h=0,history=[])
    final_size=len(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    assert preliminary_size < ed.MAX_INPUT_BYTES < final_size
    assert result['limit_status']=='exceeded' and result['observed']['serialized_input_bytes']==final_size
    calls=[]; assert ed.evaluate(result,{},provider=lambda *_:calls.append(1))['status']=='OVERSIZE_NOT_EVALUATED'
    assert calls==[]


def test_final_snapshot_immediately_below_bound_remains_evaluable(monkeypatch):
    board={'news_candidates_for_menzo':[{'title':'A','url':'https://size.test/b','summary':'x'*500}]}
    baseline=ed.capture_opportunity(board,run_id='run',observation_timestamp='now',publisher_count_24h=0,history=[])
    baseline_size=len(json.dumps(baseline,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    monkeypatch.setattr(ed,'MAX_INPUT_BYTES',baseline_size+32)
    result=ed.capture_opportunity(board,run_id='run',observation_timestamp='now',publisher_count_24h=0,history=[])
    final_size=len(json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
    assert final_size <= ed.MAX_INPUT_BYTES and result['limit_status']!='exceeded'
    assert result['observed']['serialized_input_bytes']==final_size


def test_missing_key_has_canonical_request_but_gemini_only_logical_metric_is_null(monkeypatch):
    from agents.canonical_event_ledger import clear_active_ledger, install_active_ledger
    events=[]
    class Ledger:
        def safely(self, method, *args, **kwargs):
            events.append((method,args,kwargs)); return True
    install_active_ledger(Ledger()); monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    ledger=[]; monkeypatch.setattr(ed,'record_gemini_attempt',lambda **kw:ledger.append(kw))
    try: result=ed.evaluate(snapshot(),{})
    finally: clear_active_ledger()
    assert result['status']=='PROVIDER_UNAVAILABLE' and ledger==[]
    assert any(args and args[0]=='logical_ai_request_created' for _method,args,_kwargs in events)
    shadow=gemini_diagnostics.build_gemini_diagnostics([],economic_available=True)['editorial_director_shadow']
    assert shadow['logical_requests'] is None and shadow['cost_per_logical_request'] is None
    assert shadow['logical_requests_availability']=='requires_canonical_event_ledger_join'
    assert shadow['provider_attempts']==0 and shadow['known_cost']=='0'


def _resolved_shadow_row(attempt_id, currency):
    from agents.gemini_ledger import calculate_v96_2_cost
    usage={'usage_available':True,'input_tokens':100,'cached_input_tokens':0,'output_tokens':10,
           'thinking_tokens':0,'total_tokens':110,'total_tokens_provider_reported':True}
    cost=calculate_v96_2_cost(usage,'gemini-3.1-flash-lite')
    return {'status':'called','ledger_schema_version':'v3','provider_attempt_id':attempt_id,
            'actual_model':'gemini-3.1-flash-lite','model_requested':'gemini-3.1-flash-lite',
            'agent':'Menzo','workload':'editorial_director_shadow','phase':'editorial_director_shadow_primary',
            'logical_request_id':attempt_id,'attempt_index':0,'repair':False,'fallback':False,'candidate_count':1,
            **cost,'pricing_currency':currency}


def test_mixed_shadow_currencies_never_form_scalar_cost():
    rows=[_resolved_shadow_row('usd','USD'),_resolved_shadow_row('eur','EUR')]
    shadow=gemini_diagnostics.build_gemini_diagnostics(rows,economic_available=True)['editorial_director_shadow']
    assert shadow['source_available'] is True and shadow['pricing_currency']=='mixed'
    assert shadow['known_cost'] is shadow['complete_window_cost'] is None
    assert shadow['cost_per_logical_request'] is shadow['cost_per_evaluated_candidate_occurrence'] is None


def test_same_currency_shadow_rows_retain_complete_cost():
    rows=[_resolved_shadow_row('usd-1','USD'),_resolved_shadow_row('usd-2','USD')]
    shadow=gemini_diagnostics.build_gemini_diagnostics(rows,economic_available=True)['editorial_director_shadow']
    assert shadow['source_available'] is True and shadow['pricing_currency']=='USD'
    assert shadow['known_cost'] is not None and shadow['complete_window_cost']==shadow['known_cost']
    assert shadow['cost_per_evaluated_candidate_occurrence'] is not None
    assert shadow['cost_per_logical_request'] is None
