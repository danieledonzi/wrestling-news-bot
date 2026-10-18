"""Keep permanent editorial memory isolated in every offline test."""
import pytest


@pytest.fixture(autouse=True)
def isolated_terminal_memory(tmp_path, monkeypatch):
    from agents import menzo_policy_v93_15 as menzo
    from agents import massy_policy_v93_24 as massy
    from agents import menzo_primary_classification_store as primary
    from agents import menzo_editorial_recovery as recovery
    path = tmp_path / 'terminal-skips.json'
    monkeypatch.setattr(menzo, 'HARD_SKIP_FILE', path)
    monkeypatch.setattr(massy, 'MENZO_HARD_SKIP_FILE', path)
    monkeypatch.setattr(primary, 'STORE_FILE', tmp_path / 'first-primary.json')
    monkeypatch.setattr(primary, 'MASTER_LOG', tmp_path / 'master-log.jsonl')
    monkeypatch.setattr(recovery, 'CACHE_FILE', tmp_path / 'technical-recovery.json')
    from agents import menzo_source_material as material, source_body
    from agents import menzo_fact_cards as factual
    monkeypatch.setattr(factual, 'CACHE_FILE', tmp_path / 'fact-cards.json')
    monkeypatch.setattr(material, 'CACHE_FILE', tmp_path / 'source-material.json')
    def complete_fixture(item):
        text = str(item.get('retained_body') or item.get('summary') or item.get('title') or 'Offline factual fixture')
        if len(text) < 200:
            text = (text + ' ') * (201 // max(1, len(text)) + 1)
        contract = source_body.contract_from_elements(item.get('source_url') or item.get('source_url') or item.get('url', ''), [{'type': 'text', 'text': text}],
            {'extraction_finished': True, 'body_complete': True, 'clean_element_count': 1})
        item['canonical_source_body'] = contract
        return True, 'offline_fixture'
    monkeypatch.setattr(material, '_fetch_body', complete_fixture)


@pytest.fixture(autouse=True)
def historical_provider_contracts(request, monkeypatch):
    """Keep historical final-verdict fixtures; real card contracts have separate tests."""
    modules = {'test_ed8_terminal_skip_semantic_admission', 'test_alfred_newsletter_and_factual_admission',
               'test_admission_binding_covered_updates', 'test_complete_editorial_material',
               'test_complete_editorial_material_review', 'test_duplicate_technical_isolation',
               'test_ed5_editorial_prefilter', 'test_ed3_editorial_totems_soft_board',
               'test_ed9_independent_duplicate_contracts', 'test_pair_context_boundaries',
               'test_ed2_editorial_director_active', 'test_ed6_editorial_category_policy',
               'test_dr1_duplicate_body_revalidation', 'test_totem_feed_and_gemini_authority'}
    if request.module.__name__.split('.')[-1] not in modules:
        return
    from agents import menzo_editorial_director_active as active
    from factual_provider_fixtures import adapt
    original = active._run_once
    source_order, sources = [], {}
    def run(snapshot, call, prompt, schema, phase, *args, **kwargs):
        if call is None and phase in {'editorial_fact_extraction', 'editorial_fact_enrichment'}:
            call = lambda *_: {}  # Old fixtures isolate final decisions; no live model for cards.
        if call is None and phase in {'editorial_duplicate_admission', 'editorial_soft_duplicate_admission'}:
            try:
                call = active.shadow._default_provider_factory()
            except Exception as exc:
                # Reuse the observed initialization failure; do not probe the fake factory twice.
                def failed_initialization():
                    raise exc
                with monkeypatch.context() as context:
                    context.setattr(active.shadow, '_default_provider_factory', failed_initialization)
                    return original(snapshot, None, prompt, schema, phase, *args, **kwargs)
        if call is not None:
            raw_call = call
            call = lambda p, s, t: adapt(raw_call, p, s, t, source_order, sources)
        return original(snapshot, call, prompt, schema, phase, *args, **kwargs)
    monkeypatch.setattr(active, '_run_once', run)
