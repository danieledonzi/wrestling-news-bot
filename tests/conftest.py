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
    monkeypatch.setattr(material, 'CACHE_FILE', tmp_path / 'source-material.json')
    def complete_fixture(item):
        text = str(item.get('retained_body') or item.get('summary') or item.get('title') or 'Offline factual fixture')
        if len(text) < 200:
            text = (text + ' ') * (201 // max(1, len(text)) + 1)
        contract = source_body.contract_from_elements(item.get('url', ''), [{'type': 'text', 'text': text}],
            {'extraction_finished': True, 'body_complete': True, 'clean_element_count': 1})
        item['canonical_source_body'] = contract
        return True, 'offline_fixture'
    monkeypatch.setattr(material, '_fetch_body', complete_fixture)
