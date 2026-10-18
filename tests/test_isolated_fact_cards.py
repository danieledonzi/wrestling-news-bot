"""Actual new contracts, separate from migrated historical provider fixtures."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from agents import menzo_fact_cards as facts, menzo_card_admission as election
from agents import menzo_semantic_admission as admission
from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_editorial_recovery as recovery
from agents import menzo_primary_classification_store as primary
from agents import menzo_policy_v93_15 as menzo
from factual_provider_fixtures import extraction, enrichment


@pytest.fixture(autouse=True)
def offline_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(active, 'record_gemini_attempt', lambda **_: None)
    monkeypatch.setattr(active.pair_cache, 'CACHE_FILE', tmp_path / 'final-pairs.json')
    monkeypatch.setattr('agents.bob.dynamic_article_capacity', lambda *_: (5, 'fixture'))
    monkeypatch.setattr(menzo, 'load_authoritative_publisher_history', lambda *_: [])


def article(name, **extra):
    return {'url': 'https://cards.test/' + name, 'title': name,
            'retained_body': (name + ' announces a concrete professional development. ') * 8,
            'input_coverage': 'FULL_BODY', **extra}


def state(count=2, history=0):
    result = {}
    current = [dict(article('current' + str(i)), candidate_id='c' + str(i)) for i in range(count)]
    old = [dict(article('history' + str(i)), article_id='h' + str(i)) for i in range(history)]
    admission.attach(result, current, old, [{'candidate_id': r['candidate_id'], 'editorial_class': 'SHOULD_PUBLISH'} for r in current])
    return result


class Model:
    def __init__(self, *, choose=False, mutate=None, subjects=None):
        self.calls = []
        self.choose = choose
        self.mutate = mutate
        self.subjects = subjects or {}

    def __call__(self, prompt, schema, *_):
        data = json.loads(prompt.split('INPUT=', 1)[1]);properties = schema['properties']
        phase = ('enrichment' if 'identities' in properties else 'extraction' if 'article_kind' in properties else
                 'admission' if 'pair_assessments' in properties else 'duplicate' if set(properties) == {'relations'} else 'classification')
        self.calls.append((phase, copy.deepcopy(data), schema))
        if phase == 'extraction':
            output = extraction(data)
            output['facts'][0]['central_subjects'][0]['name'] = self.subjects.get(data['title'], 'Fixture Performer')
        elif phase == 'enrichment':
            output = enrichment(data)
        elif phase == 'admission':
            cs = {c['article_id']: c for c in data['cards']}
            output = {'admission_complete': True, 'pair_assessments': []}
            for p in data['permitted_pairs']:
                chosen = self.choose(p, cs) if callable(self.choose) else self.choose
                output['pair_assessments'].append({'pair_id': p['pair_id'], 'decision': 'ADMIT' if chosen else 'NO_SUSPICION',
                    'left_fact_refs': [cs[p['left_article']]['facts'][0]['fact_id']] if chosen else [],
                    'right_fact_refs': [cs[p['right_article']]['facts'][0]['fact_id']] if chosen else [],
                    'basis': 'Same concrete development.' if chosen else 'Independent factual developments.'})
        elif phase == 'duplicate':
            output = {'relations': [{'ref': 'r0', 'decision': 'NO_MATCH'}]}
        else:
            output = {'candidates': [{'ref': 'c'+str(i), 'editorial_class': 'SHOULD_PUBLISH',
                'recommended_action': 'SELECT', 'category': 'WWE', 'story_core': 'Autonomous professional news'}
                for i in range(len(data['candidates']))], 'relations': []}
        return self.mutate(phase, data, output) if self.mutate else output


def run(value, model):
    return active._admit(value, model)


def test_each_source_has_two_isolated_operations_and_cards_never_receive_other_bodies():
    value = state();value['_semantic_admission']['candidates'][0]['retained_body'] += ' FIRST_PRIVATE_TAIL'
    value['_semantic_admission']['candidates'][1]['retained_body'] += ' SECOND_PRIVATE_TAIL'
    model = Model(choose=True);result = run(value, model)
    assert result['status'] == 'VALIDATED' and not result['held_candidate_ids']
    assert [p for p, _, _ in model.calls].count('extraction') == 2
    assert [p for p, _, _ in model.calls].count('enrichment') == 2
    for phase, data, _ in model.calls:
        serialized = json.dumps(data)
        assert 'editorial_class' not in serialized
        if phase in {'extraction', 'enrichment'}:
            assert ('FIRST_PRIVATE_TAIL' in serialized) != ('SECOND_PRIVATE_TAIL' in serialized)
            assert data['source_url'] in {'https://cards.test/current0', 'https://cards.test/current1'}
        else:
            assert 'source_units' not in data
            assert all('retained_body' not in c for c in data['cards'])
            for card in data['cards']:
                content = json.dumps(card['facts'])
                assert ('FIRST_PRIVATE_TAIL' in content) != ('SECOND_PRIVATE_TAIL' in content)
                assert all(f['article_id'] == card['article_id'] for f in card['facts'])
            assert len(data['permitted_pairs']) == 1
    assert len(result['admitted_relations']) == 1
    assert result['attempts'] == 5


def test_cards_and_pair_assessments_reuse_exact_material_across_primary_and_soft():
    value = state(2, 1);model = Model()
    first = run(value, model)
    assert first['attempts'] == 7
    second = run({**value, '_semantic_admission_only': True}, lambda *_: pytest.fail('cached stages cannot call provider'))
    assert second['attempts'] == 0 and not second['held_candidate_ids']
    assert all(r.get('cache_hit') for r in second['pair_dispositions'])


def test_new_endpoint_does_not_rejudge_old_pairs():
    model = Model();first = run(state(2), model)
    assert first['attempts'] == 5
    model.calls.clear();later = run(state(3), model)
    assert [p for p, _, _ in model.calls] == ['extraction', 'enrichment', 'admission']
    offered = next(d['permitted_pairs'] for p, d, _ in model.calls if p == 'admission')
    assert len(offered) == 2
    assert sum(r.get('cache_hit', False) for r in later['pair_dispositions']) == 1


def test_body_or_title_change_invalidates_only_its_source_stages():
    run(state(), Model());value = state();value['_semantic_admission']['candidates'][0]['retained_body'] += ' Important new fact.'
    model = Model();result = run(value, model)
    assert [p for p, _, _ in model.calls] == ['extraction', 'enrichment', 'admission']
    assert result['attempts'] == 3


def test_enrichment_failure_preserves_valid_extraction_and_obeys_backoff(monkeypatch):
    model = Model(mutate=lambda p,d,r: {**r, 'coverage_complete': False} if p == 'enrichment' else r)
    first = run(state(1), model)
    assert first['held_candidate_ids'] == ['c0'] and first['attempts'] == 2
    second = run(state(1), Model())
    assert second['held_candidate_ids'] == ['c0'] and second['attempts'] == 0
    monkeypatch.setattr(recovery, 'lookup', lambda *_a, **_k: None)
    model = Model();third = run(state(1), model)
    assert not third['held_candidate_ids'] and [p for p,_,_ in model.calls] == ['enrichment']


def test_pair_failure_backoff_survives_json_disk_roundtrip_and_rss_changes():
    def damage(phase,data,raw):
        if phase=='admission': raw['pair_assessments']=[]
        return raw
    first=run(state(),Model(mutate=damage))
    assert first['status']=='TECHNICAL_HOLD' and first['attempts']==5
    later=state();later['_semantic_admission']['candidates'][0]['summary']='A refreshed RSS excerpt.'
    second=run(later,lambda *_: pytest.fail('unchanged full material must remain on backoff'))
    assert second['attempts']==0 and second['status']=='TECHNICAL_HOLD'
    assert second['retry_after']==first['retry_after']


def test_foreign_source_unit_rejected_without_repair():
    def mutate(phase, data, output):
        if phase == 'extraction': output['facts'][0]['source_unit_ids'] = ['other-article.u1']
        return output
    model = Model(mutate=mutate);result = run(state(1), model)
    assert result['held_candidate_ids'] == ['c0'] and result['attempts'] == 1
    assert [p for p, _, _ in model.calls] == ['extraction']


def test_history_gate_excludes_complete_distinct_subjects_with_auditable_reason():
    model = Model(subjects={'current0': 'Michael Cole', 'history0': 'Ilja Dragunov'})
    result = run(state(1, 1), model)
    assert result['admission_summary']['history_excluded'] == 1
    assert all(phase != 'admission' for phase,_,_ in model.calls)
    row = result['pair_dispositions'][0]
    assert row['decision'] == 'EXCLUDED_HISTORY' and row['left_card_sha256'] and row['right_card_sha256']


@pytest.mark.parametrize('shared_evidence', ['episode', 'event', 'facet', 'context', 'none'])
def test_business_organization_cross_family_requires_specific_episode_evidence(shared_evidence):
    def mutate(phase, data, raw):
        if phase == 'extraction':
            raw['facts'][0]['central_subjects'] = [{'kind': 'organization', 'name': 'WWE'}]
            raw['facts'][0]['episode_family'] = ('business_media_ownership' if data['title']=='current0'
                                                   else 'industry_economics')
            raw['facts'][0]['specific_event_tags'] = (['wwe_netflix_agreement_2026']
                                                       if shared_evidence=='event' else [])
            raw['context_tags'] = ['WWE', 'business'] if shared_evidence=='context' else []
        elif phase == 'enrichment':
            raw['facts'][0]['episode_facets'] = ['industry_economics'] if shared_evidence=='facet' else []
            raw['facts'][0]['episode_tags'] = (['wwe_netflix_agreement_2026']
                                               if shared_evidence=='episode' else [])
        return raw
    result = run(state(1, 1), Model(mutate=mutate))
    admitted = shared_evidence in {'episode', 'event'}
    assert result['admission_summary']['pairs_offered'] == int(admitted)
    assert result['pair_dispositions'][0]['decision'] == ('NO_SUSPICION' if admitted else 'EXCLUDED_HISTORY')


def test_ambiguous_identity_is_not_silently_excluded_from_history():
    def mutate(phase, data, raw):
        if phase == 'enrichment' and data['title'] == 'current0': raw['identities'][0]['confidence'] = 'uncertain'
        return raw
    model = Model(subjects={'current0': 'Unknown Performer', 'history0': 'Known Performer'}, mutate=mutate)
    result = run(state(1, 1), model)
    assert result['admission_summary']['pairs_offered'] == 1 and result['pair_dispositions'][0]['decision'] == 'NO_SUSPICION'


def test_alias_resolution_and_cross_family_facets_recover_history():
    def mutate(phase, data, raw):
        if phase == 'enrichment':
            raw['identities'][0].update(canonical_name='Shotzi', aliases=['Shotzi', 'Shotzi Blackheart'])
            raw['facts'][0]['episode_facets'] = ['personal_family_bereavement']
        elif phase == 'extraction':
            raw['facts'][0]['episode_family'] = 'career_departure_retirement' if data['title']=='current0' else 'other'
        return raw
    model = Model(subjects={'current0': 'Shotzi Blackheart', 'history0': 'Shotzi'}, mutate=mutate)
    result = run(state(1, 1), model)
    assert result['admission_summary']['pairs_offered'] == 1
    assert result['pair_dispositions'][0]['retrieval_reason'] == 'shared_factual_retrieval_evidence'


@pytest.mark.parametrize('damage', ['omit', 'repeat', 'foreign_fact'])
def test_missing_invalid_pair_decisions_hold_only_their_endpoints(damage):
    def mutate(phase, data, raw):
        if phase != 'admission': return raw
        if damage=='omit': raw['pair_assessments'].pop(0)
        elif damage=='repeat': raw['pair_assessments'].append(copy.deepcopy(raw['pair_assessments'][0]))
        else: raw['pair_assessments'][0]['left_fact_refs'] = ['foreign.f1']
        return raw
    model = Model(mutate=mutate);result = run(state(3), model)
    assert len(result['held_candidate_ids']) == 2
    assert result['admission_summary']['pair_holds'] == 1
    assert result['admission_summary']['pair_decisions'] == 2
    assert result['attempts'] == 7  # Six isolated stages and one admission; no repair.
    assert result['validation_errors']


def test_twenty_current_articles_cover_190_pairs_in_bounded_batches():
    model = Model();result = run(state(20), model)
    batches = [d for phase,d,_ in model.calls if phase=='admission']
    assert len(batches) == 16 and sum(len(b['permitted_pairs']) for b in batches) == 190
    assert all(len(b['permitted_pairs']) <= 12 and len(b['current_article_ids']) == len(set(b['current_article_ids'])) for b in batches)
    assert result['admission_summary']['pair_decisions'] == 190 and not result['held_candidate_ids']
    assert len({r['pair_id'] for r in result['pair_dispositions']}) == 190


def test_input_limit_holds_without_truncating_or_inventing_no_suspicion(monkeypatch):
    monkeypatch.setattr(election, 'MAX_BATCH_BYTES', 100)
    result = run(state(), Model())
    assert result['held_candidate_ids'] == ['c0','c1']
    assert result['pair_dispositions'][0]['decision'] == 'TECHNICAL_HOLD'
    assert result['pair_dispositions'][0]['reason'] == 'single_card_pair_input_limit'


def test_corrupt_card_cache_is_not_overwritten_and_cannot_clear_news():
    facts.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True);facts.CACHE_FILE.write_text('{broken')
    result = run(state(), lambda *_: pytest.fail('unreadable cache cannot call a provider'))
    assert result['held_candidate_ids'] == ['c0','c1'] and facts.CACHE_FILE.read_text()=='{broken'


def test_admission_version_change_preserves_final_body_judgment_cache(monkeypatch):
    def fingerprint():
        return active.pair_cache.contract_fingerprint(policy_version=active.POLICY_VERSION, model=active.MODEL,
            policy_path=active.RELATION_POLICY_PATH, gate_schema_path=active.RELATION_SCHEMA_PATH,
            event_registry_path=active.EVENT_REGISTRY_PATH)
    before=fingerprint();monkeypatch.setattr(admission,'VERSION','future-admission-transport')
    assert fingerprint()==before


def test_primary_skip_never_enters_card_work():
    def mutate(phase, data, raw):
        if phase=='classification':
            for row in raw['candidates']: row.update(editorial_class='SKIP',recommended_action='SKIP')
        return raw
    value=shadow.capture_opportunity({'news_candidates_for_menzo':[article('closed')]},run_id='cards',
        observation_timestamp='2026-10-18T12:00:00Z',history=[],defer_relation_build=True)
    model=Model(mutate=mutate);result=active.evaluate(value,provider=model)
    assert [p for p,_,_ in model.calls]==['classification']
    assert result['output']['candidates'][0]['editorial_class']=='SKIP'
    assert menzo.terminal_skip_memory()


def test_new_input_profiles_distinguish_cards_from_bodies():
    model=Model();run(state(),model)
    for phase,data,_ in model.calls:
        profile=active.source_material.input_profile('INPUT='+json.dumps(data))
        if phase in {'extraction','enrichment'}:
            assert profile['full_body_endpoints']==1
        else:
            assert profile['input_kind']=='isolated_factual_cards' and profile['full_body_endpoints']==0
            assert profile['card_endpoints']==2 and profile['body_unavailable_endpoints']==0


def test_valid_classes_survive_missing_pair_and_unaffected_article_continues():
    def mutate(phase, data, raw):
        if phase=='admission': raw['pair_assessments'].pop(0)
        return raw
    value=shadow.capture_opportunity({'news_candidates_for_menzo':[article('a'),article('b'),article('c')]},
        run_id='partial',observation_timestamp='2026-10-18T12:00:00Z',history=[],defer_relation_build=True)
    result=active.evaluate(value,provider=Model(mutate=mutate))
    assert result['status']=='VALIDATED' and len(result['output']['candidates'])==1
    assert len(result['source_material_holds'])==2 and len(primary.load())==3
    assert all(r['editorial_class']=='SHOULD_PUBLISH' for r in primary.load().values())
    assert not menzo.terminal_skip_memory()


def test_current_card_failure_is_scoped_and_does_not_reclassify_siblings():
    def mutate(phase,data,raw):
        if phase=='extraction' and data['title']=='a': raw['coverage_complete']=False
        return raw
    value=shadow.capture_opportunity({'news_candidates_for_menzo':[article('a'),article('b'),article('c')]},
        run_id='card-failure',observation_timestamp='2026-10-18T12:00:00Z',history=[],defer_relation_build=True)
    result=active.evaluate(value,provider=Model(mutate=mutate))
    assert result['status']=='VALIDATED' and len(result['output']['candidates'])==2
    assert len(result['source_material_holds'])==1 and len(primary.load())==3
    assert not menzo.terminal_skip_memory()


def test_fact_and_pair_events_reconcile_and_incomplete_cycle_is_not_zero(tmp_path):
    from agents.canonical_event_ledger import CanonicalEventLedger,install_active_ledger,clear_active_ledger,validate_event
    from scripts.factual_admission_metrics import build
    ledger=CanonicalEventLedger('card-metrics',path=tmp_path/'events.jsonl',enabled=True)
    install_active_ledger(ledger)
    try:
        run(state(2,1),Model())
    finally:
        clear_active_ledger()
    events=[json.loads(line) for line in (tmp_path/'events.jsonl').read_text().splitlines()]
    assert all(not validate_event(r) for r in events)
    since=datetime.fromisoformat(events[0]['timestamp_utc']);until=datetime.now(timezone.utc)+timedelta(seconds=1)
    metrics=build(events,since,until)
    assert metrics['coverage']=='full' and metrics['window_metrics']['pair_disposition_observations']==3
    assert metrics['observed']['pair_decisions']=={'NO_SUSPICION':3}
    broken=[r for r in events if r['event_type']!='editorial_pair_disposition']
    missing=build(broken,since,until)
    assert missing['coverage']=='unavailable' and missing['window_metrics'] is None
    partial=build(events,since-timedelta(hours=24),until)
    assert partial['coverage']=='partial' and partial['window_metrics'] is None
