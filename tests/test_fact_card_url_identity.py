"""A cosmetic source-URL change cannot purchase the same factual card twice."""
import copy

import pytest

from agents import menzo_fact_cards as facts
from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from test_isolated_fact_cards import article, Model, offline_runtime, run, state


CANONICAL = 'https://ringsidenews.com/bayley-announcement'
ALIASES = [CANONICAL, CANONICAL + '/', CANONICAL.replace('://', '://www.'),
           CANONICAL.replace('://', '://www.') + '/']


def obtain(row, model, *, cache=None, requested_model=None):
    return facts.obtain(row, cache or facts.Cache(), active._run_once, model,
                        requested_model or shadow.MODEL, max_input_bytes=2_000_000)


@pytest.mark.parametrize('first_url', ALIASES)
@pytest.mark.parametrize('later_url', ALIASES)
def test_aliases_reuse_both_persisted_stages_and_owned_fact_ids(first_url, later_url):
    row = article('Bayley announcement', url=first_url)
    before = copy.deepcopy(row)
    model = Model(); first, info = obtain(row, model)
    assert info['status'] == 'VALIDATED' and info['attempts'] == 2
    assert [phase for phase, _, _ in model.calls] == ['extraction', 'enrichment']
    assert row == before and first['source_url'] == CANONICAL
    cache_before = facts.CACHE_FILE.read_bytes()
    later, reused = obtain({**row, 'url': later_url},
                          lambda *_: pytest.fail('alias must reuse the persisted card'))
    assert reused['attempts'] == 0
    assert reused['extraction_cache_hit'] and reused['enrichment_cache_hit']
    assert later == first  # Includes source ownership, fact refs, provenance and hash.
    assert facts.CACHE_FILE.read_bytes() == cache_before


def test_source_url_only_and_both_url_fields_use_existing_canonical_identity():
    row = article('Bayley announcement', url=ALIASES[-1]); row.pop('url')
    row['source_url'] = ALIASES[-1]
    first, _ = obtain(row, Model())
    later, result = obtain({**row, 'url': ALIASES[-1], 'source_url': CANONICAL},
                           lambda *_: pytest.fail('history projection must reuse'))
    assert result['attempts'] == 0 and later == first


@pytest.mark.parametrize('change', ['body', 'title', 'model', 'path', 'domain', 'scheme',
                                   'extraction_policy', 'extraction_schema'])
def test_real_source_or_contract_changes_still_require_new_isolated_stages(change, monkeypatch, tmp_path):
    row = article('Bayley announcement', url=CANONICAL)
    first, _ = obtain(row, Model()); later = copy.deepcopy(row)
    model_name = None
    if change == 'body': later['retained_body'] += ' A new important development is confirmed.'
    elif change == 'title': later['title'] = 'Bayley confirms a different development'
    elif change == 'model':
        model_name = 'a-different-model'
        monkeypatch.setattr(active, 'MODEL', model_name)
    elif change == 'path': later['url'] += '-another-news-item'
    elif change == 'domain': later['url'] = later['url'].replace('ringsidenews.com', 'another-source.test')
    elif change == 'scheme': later['url'] = later['url'].replace('https:', 'http:')
    elif change == 'extraction_policy':
        path = tmp_path / 'extraction.md'; path.write_text(facts.EXTRACTION_POLICY.read_text() + '\nNew contract.')
        monkeypatch.setattr(facts, 'EXTRACTION_POLICY', path)
    else:
        previous = facts.extraction_schema
        monkeypatch.setattr(facts, 'extraction_schema', lambda p: {**previous(p), 'description': 'New contract'})
    model = Model(); card, result = obtain(later, model, requested_model=model_name)
    assert result['status'] == 'VALIDATED' and result['attempts'] == 2
    assert [phase for phase, _, _ in model.calls] == ['extraction', 'enrichment']
    assert card['card_sha256'] != first['card_sha256']


@pytest.mark.parametrize('change', ['policy', 'schema'])
def test_enrichment_contract_change_reuses_extraction_only(change, monkeypatch, tmp_path):
    row = article('Bayley announcement', url=ALIASES[-1]); obtain(row, Model())
    if change == 'policy':
        path = tmp_path / 'enrichment.md'; path.write_text(facts.ENRICHMENT_POLICY.read_text() + '\nNew contract.')
        monkeypatch.setattr(facts, 'ENRICHMENT_POLICY', path)
    else:
        previous = facts.enrichment_schema
        monkeypatch.setattr(facts, 'enrichment_schema', lambda p: {**previous(p), 'description': 'New contract'})
    model = Model(); _, result = obtain({**row, 'url': CANONICAL}, model)
    assert result['attempts'] == 1 and result['extraction_cache_hit']
    assert [phase for phase, _, _ in model.calls] == ['enrichment']


@pytest.mark.parametrize('failed_stage', ['extraction', 'enrichment'])
def test_url_alias_cannot_bypass_unchanged_technical_backoff(failed_stage):
    row = article('Bayley announcement', url=ALIASES[-1])
    bad = Model(mutate=lambda phase, data, raw:
                {**raw, 'coverage_complete': False} if phase == failed_stage else raw)
    first, result = obtain(row, bad)
    assert first is None and result['status'] != 'VALIDATED'
    later, repeated = obtain({**row, 'url': CANONICAL},
                             lambda *_: pytest.fail('unchanged failure must remain on backoff'))
    assert later is None and repeated['attempts'] == 0
    assert repeated['retry_after'] == result['retry_after']


def test_pair_assessment_cache_survives_url_alias_without_new_admission():
    value = state(2)
    value['_semantic_admission']['candidates'][0]['url'] = ALIASES[-1]
    first = run(value, Model())
    later = copy.deepcopy(value)
    later['_semantic_admission']['candidates'][0]['url'] = CANONICAL
    result = run(later, lambda *_: pytest.fail('source and pair caches must both reuse'))
    assert first['attempts'] == 5 and result['attempts'] == 0
    assert all(row['cache_hit'] for row in result['pair_dispositions'])


def test_no_card_cache_flush_or_global_final_judgment_contract_change():
    before = active.pair_cache.contract_fingerprint(policy_version=active.POLICY_VERSION,
        model=active.MODEL, policy_path=active.RELATION_POLICY_PATH,
        gate_schema_path=active.RELATION_SCHEMA_PATH, event_registry_path=active.EVENT_REGISTRY_PATH)
    obtain(article('Bayley announcement', url=ALIASES[-1]), Model())
    after = active.pair_cache.contract_fingerprint(policy_version=active.POLICY_VERSION,
        model=active.MODEL, policy_path=active.RELATION_POLICY_PATH,
        gate_schema_path=active.RELATION_SCHEMA_PATH, event_registry_path=active.EVENT_REGISTRY_PATH)
    assert after == before
