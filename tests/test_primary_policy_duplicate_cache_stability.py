from agents import menzo_editorial_director_active as active
from agents import menzo_active_duplicate_pair_cache as cache
import pytest


def legacy_v10_contract():
    return cache.contract_fingerprint(policy_version='owtv_editorial_director_policy_v10_active',
        model=active.MODEL,policy_path=active.RELATION_POLICY_PATH,
        gate_schema_path=active.RELATION_SCHEMA_PATH,event_registry_path=active.EVENT_REGISTRY_PATH)


@pytest.mark.parametrize('scope',['same_run','recent_history'])
@pytest.mark.parametrize('verdict',['DUPLICATE','NO_MATCH','MATERIAL_UPDATE'])
def test_existing_v10_verdict_survives_primary_bump_but_not_duplicate_policy_change(monkeypatch,tmp_path,scope,verdict):
    relation={'pair_id':'pair-existing','scope':scope,'left_id':'left','right_id':'right',
              'decision':verdict,'semantic_authority':'gemini_final'}
    endpoints={'left':{'url':'https://source.test/a','retained_body':'fact A'},
               'right':{'url':'https://source.test/b','retained_body':'fact B'}}
    old=cache.pair_material(relation,endpoints,legacy_v10_contract())
    existing=cache.empty();cache.store(existing,[(old,relation)],path=tmp_path/'cache.json')
    monkeypatch.setattr(active,'POLICY_VERSION','future_primary_policy')
    current=cache.pair_material(relation,endpoints,active.duplicate_contract_fingerprint())
    assert cache.lookup(existing,current)['decision']==verdict
    changed=tmp_path/'new-duplicate-policy.md';changed.write_text(active.RELATION_POLICY_PATH.read_text()+'\nChanged duplicate rule.\n')
    monkeypatch.setattr(active,'RELATION_POLICY_PATH',changed)
    assert cache.lookup(existing,cache.pair_material(relation,endpoints,active.duplicate_contract_fingerprint())) is None


def test_cached_duplicate_admission_cannot_disappear_after_primary_bump(monkeypatch):
    identity={'pair_id':'pair-existing','scope':'recent_history','left_id':'left','right_id':'right'}
    entry={'identity':identity,'contract_fingerprint':cache.scope_contract_fingerprint(legacy_v10_contract(),'recent_history'),
           'final_relation':{**identity,'decision':'DUPLICATE','semantic_authority':'gemini_final'}}
    monkeypatch.setattr(cache,'load',lambda:{'entries':{'pair-existing':entry}})
    monkeypatch.setattr(active,'POLICY_VERSION','future_primary_policy')
    snapshot={'candidates':[{'candidate_id':'left'}],'publisher_history_12h':[{'article_id':'right'}]}
    elected=[]
    active._preserve_cached_duplicate_admissions(snapshot,elected)
    assert [r['pair_id'] for r in elected]==['pair-existing']
