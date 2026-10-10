"""Keep permanent editorial memory isolated in every offline test."""
import pytest


@pytest.fixture(autouse=True)
def isolated_terminal_memory(tmp_path, monkeypatch):
    from agents import menzo_policy_v93_15 as menzo
    from agents import massy_policy_v93_24 as massy
    path = tmp_path / 'terminal-skips.json'
    monkeypatch.setattr(menzo, 'HARD_SKIP_FILE', path)
    monkeypatch.setattr(massy, 'MENZO_HARD_SKIP_FILE', path)
