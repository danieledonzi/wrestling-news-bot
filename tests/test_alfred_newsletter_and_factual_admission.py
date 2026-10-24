"""Owner-approved newsletter citations and factual admission evidence."""
import copy
import json

import pytest

from agents import alfred, menzo_semantic_admission as admission
from agents import menzo_editorial_director_active as active
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_primary_classification_store as primary
from agents import menzo_priority_queue as queue
from agents import menzo_active_duplicate_pair_cache as pair_cache
from test_admission_binding_covered_updates import election


ITALIAN = ('La società ha chiarito la propria posizione sulla vicenda e ha fornito ulteriori '
           'informazioni sulle decisioni prese dai dirigenti. Il comunicato descrive i fatti '
           'confermati e le conseguenze per il professionista coinvolto. ')


def article(extra):
    return {'source_url': 'https://source.test/news', 'title_it': 'La società chiarisce la propria posizione',
            'status': 'ready_for_alfred', 'body_html': f'<p>{ITALIAN * 3}</p><p>{extra}</p>',
            'element_counts': {'text': 2, 'quote': 0, 'table': 0}}


def codes(value):
    return {x['code'] for x in alfred.review_article(value)['issues']}


@pytest.mark.parametrize('citation', [
    'Secondo Dave Meltzer nel Wrestling Observer Newsletter, la WWE ha smentito il proprio coinvolgimento.',
    'Meltzer ha scritto nella newsletter che le fonti interne alla WWE hanno negato ogni pressione.',
    'La newsletter riporta una smentita dei dirigenti, attribuita a fonti interne alla società.',
    'La fonte citata è la nostra newsletter, secondo la dichiarazione del giornalista.',
    'Secondo la fonte, alcuni dirigenti subscribe to the Wrestling Observer Newsletter per seguire le notizie.',
])
def test_editorial_newsletter_citations_are_not_ctas(citation):
    assert codes(article(citation)) == set()


@pytest.mark.parametrize('cta', [
    'Iscriviti alla nostra newsletter.', 'Abbonati alla newsletter per ricevere tutti gli aggiornamenti.',
    'Ricevi la newsletter ogni giorno.', 'La nostra newsletter ti offre gli aggiornamenti.',
    'Subscribe to the newsletter.', 'Sign up for the newsletter.', 'Join our newsletter.',
    'Get our free newsletter.', 'Seguici su Instagram.', 'Fateci sapere cosa ne pensate.',
    'Don’t miss updates—our newsletter delivers the latest news.',
    'Non perderti gli aggiornamenti della newsletter.',
])
def test_actual_promotional_calls_still_block(cta):
    assert 'cta_residue' in codes(article(cta))


@pytest.mark.parametrize('cta', [
    'Please subscribe to our newsletter.',
    'You can sign up for our newsletter.',
    'To receive updates, sign up for our newsletter.',
    'Per ricevere gli aggiornamenti, abbonati alla newsletter.',
    'Subscribe to our <strong>newsletter</strong>.',
    'For more wrestling news, subscribe to our newsletter.',
    'Stay up to date with our newsletter.',
    'Per altre notizie, abbonati alla newsletter.',
])
def test_prefixed_and_unpunctuated_paragraph_ctas_still_block(cta):
    value = article('')
    value['body_html'] = f'<p>{ITALIAN * 3}</p><p>Ulteriori dettagli sulla vicenda</p><p>{cta}</p>'
    assert 'cta_residue' in codes(value)


def test_paragraph_boundaries_do_not_turn_reported_subscription_into_a_cta():
    value = article('')
    value['body_html'] = (f'<p>{ITALIAN * 3}</p><p>Ulteriori dettagli sulla vicenda</p>'
                          '<p>Secondo la fonte, alcuni dirigenti subscribe to the Wrestling Observer '
                          'Newsletter per seguire le notizie.</p>')
    assert codes(value) == set()


def test_a_newsletter_citation_does_not_whitelist_a_later_cta():
    value = article('Secondo il Wrestling Observer Newsletter, la società ha smentito le voci. '
                    'Abbonati alla newsletter per ricevere gli aggiornamenti.')
    assert 'cta_residue' in codes(value)


def test_newsletter_change_does_not_weaken_html_or_language_guards():
    value = article('Secondo il Wrestling Observer Newsletter, la società ha smentito le voci.')
    value['body_html'] += '<script>danger()</script>'
    assert 'unsafe_html' in codes(value)
    value['body_html'] = '<p>' + ('The company has announced that this will be the next event and the officials '
                                  'would work with the team while the situation could change. ' * 15) + '</p>'
    assert codes(value) & {'untranslated_body', 'residual_english_body'}


def suspicion(**updates):
    value = {'left_ref': 'a0', 'right_ref': 'h0',
             'anchor_fact': 'The performer announced a new contract with the promotion.',
             'target_fact': 'The promotion confirmed that same performer signed a contract.',
             'basis': 'The two articles may report the same contract announcement.'}
    return {**value, **updates}


@pytest.mark.parametrize('bad', [None, '', '   ', 1, 'x' * 501])
@pytest.mark.parametrize('field', ['anchor_fact', 'target_fact'])
def test_malformed_endpoint_explanations_are_technical_failures(field, bad):
    value, errors = admission.validate({'admission_complete': True,
        'suspected_duplicates': [suspicion(**{field: bad})]}, election(1, 1), [], 300)
    assert value is None and errors == [{'family': 'semantic_admission_facts',
                                        'detail': 'bounded_endpoint_facts_required'}]


def test_schema_requires_facts_but_empty_election_needs_no_fabricated_evidence():
    state = election(1, 1)
    template = json.loads(active.ADMISSION_SCHEMA_PATH.read_text())
    schema = admission.bound_schema(template, state, payload=admission.anchored_payloads(state)[0])
    assert {'anchor_fact', 'target_fact', 'basis'} <= set(schema['properties']['suspected_duplicates']['items']['required'])
    assert admission.validate({'admission_complete': True, 'suspected_duplicates': []}, state, [], 300) == ([], [])


def test_local_validation_does_not_veto_geminis_semantic_interpretation():
    # Deliberately unrelated wording: local code has no authority to overrule
    # a structurally valid Gemini suspicion using name/word/entity heuristics.
    raw = {'admission_complete': True, 'suspected_duplicates': [suspicion(
        anchor_fact='A new arrival was announced.', target_fact='A different description appears here.')]}
    relations, errors = admission.validate(raw, election(1, 1), [], 300)
    assert not errors and len(relations) == 1
    assert relations[0]['admission_evidence']['anchor_id'] == 'id0'
    assert relations[0]['admission_evidence']['target_id'] == 'hist0'


def test_evidence_keeps_provider_endpoint_binding_when_pair_ids_are_sorted():
    state = election(2, 0)
    state['_admission_candidate_ids'] = ['z-anchor', 'a-target']
    state['_admission_fixed_classes'] = {'z-anchor': 'SHOULD_PUBLISH', 'a-target': 'SHOULD_PUBLISH'}
    relations, errors = admission.validate({'admission_complete': True, 'suspected_duplicates': [
        suspicion(right_ref='a1')]}, state, [], 300)
    assert not errors and relations[0]['left_id'] == 'a-target'
    assert relations[0]['admission_evidence']['anchor_id'] == 'z-anchor'
    assert relations[0]['admission_evidence']['target_id'] == 'a-target'


def test_old_admission_cache_cannot_reinsert_pairs_but_current_decisions_remain_binding(monkeypatch):
    def fingerprint():
        return active.duplicate_contract_fingerprint()
    current_contract = fingerprint()
    with monkeypatch.context() as old:
        old.setattr(admission, 'FINAL_JUDGMENT_BINDING_VERSION', 'totem-d01-anchored-material-admission-v5')
        old_contract = fingerprint()
    assert old_contract != current_contract
    state = {'candidates': [{'candidate_id': 'anchor'}],
             'publisher_history_12h': [{'article_id': 'history'}]}
    identity = {'pair_id': 'pair', 'scope': 'recent_history', 'left_id': 'anchor', 'right_id': 'history'}
    final = {**identity, 'decision': 'DUPLICATE', 'semantic_authority': 'gemini_final'}
    for contract, expected in [(old_contract, 0), (current_contract, 1)]:
        entry = {'identity': identity, 'contract_fingerprint':
                 pair_cache.scope_contract_fingerprint(contract, identity['scope']), 'final_relation': final}
        monkeypatch.setattr(pair_cache, 'load', lambda: {'entries': {'pair': entry}})
        relations = []
        active._preserve_cached_duplicate_admissions(state, relations)
        assert len(relations) == expected


def test_cached_duplicate_restores_original_endpoint_facts_without_affecting_cache_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(pair_cache, 'CACHE_FILE', tmp_path / 'pairs.json')
    contract = active.duplicate_contract_fingerprint()
    relations, errors = admission.validate({'admission_complete': True,
        'suspected_duplicates': [suspicion()]}, election(1, 1), [], 300)
    assert not errors
    elected = relations[0]
    endpoints = {'left': {'title': 'Signing announcement'}, 'right': {'title': 'Same signing'}}
    material = pair_cache.pair_material(elected, endpoints, contract)
    identity = {k: elected[k] for k in ('pair_id', 'scope', 'left_id', 'right_id')}
    final = {**identity, 'decision': 'DUPLICATE', 'semantic_authority': 'gemini_final'}
    pair_cache.store(pair_cache.empty(), [(material, final)])
    restored = []
    active._preserve_cached_duplicate_admissions({'candidates': [{'candidate_id': 'id0'}],
        'publisher_history_12h': [{'article_id': 'hist0'}]}, restored)
    assert restored[0]['admission_evidence'] == elected['admission_evidence']
    assert restored[0]['admission_basis'] == elected['admission_basis']
    new_material = pair_cache.pair_material(restored[0], endpoints, contract)
    assert pair_cache.lookup(pair_cache.load(), new_material)['decision'] == 'DUPLICATE'
    restored[0]['admission_evidence']['anchor_fact'] = 'Mutated observation'
    assert pair_cache.load()['entries'][elected['pair_id']]['admission_evidence'] == elected['admission_evidence']


def test_sparse_factual_contract_uses_one_existing_request_and_no_classes():
    state = election(1, 1); calls = []
    def provider(prompt, schema, *_):
        calls.append(prompt)
        payload = json.loads(prompt.rsplit('INPUT=', 1)[1])
        assert payload['contract_version'] == admission.VERSION
        assert not any(x in prompt for x in ('editorial_class', 'relative_rank', 'story_core'))
        return {'admission_complete': True, 'suspected_duplicates': [suspicion()]}
    first = active._admit(copy.deepcopy(state), provider)
    second = active._admit(copy.deepcopy(state), provider)
    assert first['status'] == second['status'] == 'VALIDATED'
    assert len(calls) == 1 and first['attempts'] == 5 and second['attempts'] == 0
    assert first['admitted_relations'][0]['admission_evidence'] == second['admitted_relations'][0]['admission_evidence']


def test_owner_url_closure_preserves_primary_class_and_prevents_queue_reentry(tmp_path, monkeypatch):
    monkeypatch.setattr(menzo, 'SOFTPOOL_FILE', tmp_path / 'soft.json')
    monkeypatch.setattr(queue, '_published_keys', lambda: set())
    row = {'url': 'https://source.test/obsolete', 'title': 'Old factual reporting',
           'editorial_director': {'editorial_class': 'SHOULD_PUBLISH', 'recommended_action': 'SELECT'}}
    key = menzo.source_key(row['url'])
    stored = {**row, **row['editorial_director'], 'category': 'Business', 'story_core': 'The initial professional development.'}
    primary._write({key: stored}); queue._write([row])
    menzo.write_json(menzo.HARD_SKIP_FILE, {'items': [{**row, 'reason': 'owner_skip:obsolete_superseded',
        'decision_authority': 'owner_editorial_skip', 'terminal': True, 'expires_after_hours': None}]})
    assert queue.augment_board({'news_candidates_for_menzo': [row]})['news_candidates_for_menzo'] == []
    assert primary.load()[key]['editorial_class'] == 'SHOULD_PUBLISH'
    assert key in menzo.terminal_skip_memory()
