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
