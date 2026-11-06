"""Offline regressions: source-aware retries, model routes, dated pricing, env migration."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from modules.report_postshow import plan_postshow
from modules.report_retry_guard import (
    ReportRetryDeferred, digest_blocks, mark_terminal_contract, preflight,
    source_completion_issue,
)
from modules import report_workshop_v92 as workshop
from agents.gemini_ledger import calculate_v96_2_cost
from scripts.migrate_gemini38_env import migrate, install


def fixture(*, completed: int = 0, updates: bool = True):
    blocks = [
        {"type": "paragraph", "text": "Tonight five matches will take place."},
        {"type": "heading", "text": "Matches & Key Moments Scheduled", "level": "h2"},
    ]
    for i in range(5):
        blocks.append({"type": "paragraph", "text": f"A{i} vs. B{i}", "list_type": "ul"})
    blocks.append({"type": "heading", "text": "WWE NXT Results (11/4/26)", "level": "h2"})
    blocks.append({"type": "paragraph", "text": "Commentary welcomes viewers to NXT."})
    for i in range(completed):
        blocks += [{"type": "heading", "text": f"A{i} vs. B{i}", "level": "h2"},
                   {"type": "paragraph", "text": f"Winner: A{i} by pinfall after a hard-fought match."}]
    if updates:
        blocks.append({"type": "paragraph", "text": "Update coming shortly."})
    blocks.append({"type": "embed", "url": "https://twitter.com/WWE/status/123"})
    return blocks


def job(report_key="wwe_nxt_2026_11_04", source="https://www.ringsidenews.com/nxt-results/"):
    return {"report_key": report_key, "report_id": "wwe_nxt", "date": "2026-11-04", "source_url": source}


def test_nxt_unfinished_zero_provider_calls_and_source_change_unlocks(tmp_path):
    source = fixture(completed=1)
    plan = plan_postshow(source)
    assert plan is not None
    assert source_completion_issue(source, plan) == "source_results_still_updating"
    calls = []
    for _ in range(2):
        with pytest.raises(ReportRetryDeferred) as raised:
            preflight(job(), source, plan, state_dir=tmp_path)
        assert raised.value.reason == "source_results_still_updating"
        assert calls == []
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        assert json.loads(files[0].read_text())["source_digest"] == digest_blocks(source)
    finished = fixture(completed=5, updates=False)
    assert source_completion_issue(finished, plan_postshow(finished)) is None
    assert preflight(job(), finished, plan_postshow(finished), state_dir=tmp_path) == digest_blocks(finished)


def test_unconfirmed_or_changed_matches_not_fabricated(tmp_path):
    source = fixture(completed=2, updates=False)
    # Absence of a result for every preview item alone is not proof of an unfinished source.
    assert source_completion_issue(source, plan_postshow(source)) is None
    assert preflight(job(), source, plan_postshow(source), state_dir=tmp_path)
    source.append({"type": "paragraph", "text": "The remaining match was cancelled."})
    assert preflight(job(), source, plan_postshow(source), state_dir=tmp_path)
    assert source_completion_issue(source, None) is None


def test_no_safely_bounded_preview_preserves_old_behavior(tmp_path):
    source = [{"type": "heading", "text": "Results", "level": "h2"},
              {"type": "paragraph", "text": "Updates coming soon."}]
    assert plan_postshow(source) is None
    assert preflight(job(), source, None, state_dir=tmp_path)


def test_terminal_model_contract_is_scoped_and_fingerprint_sensitive(tmp_path):
    source = fixture(completed=5, updates=False)
    p = plan_postshow(source)
    key = job()
    token = preflight(key, source, p, state_dir=tmp_path)
    mark_terminal_contract(key, token, error=ValueError("invalid result_index"), state_dir=tmp_path)
    with pytest.raises(ReportRetryDeferred, match="unchanged_source_terminal_contract"):
        preflight(key, source, p, state_dir=tmp_path)
    assert preflight(key, source, p, contract_version="new_prompt_v2", state_dir=tmp_path) == token
    assert preflight(job(report_key="wwe_raw_2026_11_04"), source, p, state_dir=tmp_path) == token
    assert preflight(job(source="https://www.wrestleview.com/nxt-results/"), source, p, state_dir=tmp_path) == token
    changed = source + [{"type": "paragraph", "text": "A new decisive segment occurred."}]
    assert preflight(key, changed, plan_postshow(changed), state_dir=tmp_path) != token


class RequestStub:
    def __init__(self, *args, **kwargs):
        self.attempt_number = 0

    def start(self, *args, **kwargs):
        self.attempt_number += 1
        return object()

    def failed(self, *args, **kwargs):
        return None

    def completed(self, *args, **kwargs):
        return None


def mock_generate(monkeypatch, responses):
    models = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    calls = []
    class Provider:
        def generate_content(self, *, model, contents, config=None):
            assert config == {"response_mime_type": "application/json"}
            calls.append(model)
            outcome = responses[len(calls) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return type("Response", (), {"text": outcome})()
    monkeypatch.setattr(workshop, "GEMINI_API_KEY", "test-only")
    monkeypatch.setattr(workshop, "REPORT_MODEL_CHAIN", models)
    monkeypatch.setattr(workshop, "OperationalAIRequest", RequestStub)
    monkeypatch.setattr(workshop, "record_gemini_attempt", lambda **kw: None)
    monkeypatch.setattr(workshop, "record_gemini_event", lambda **kw: None)
    monkeypatch.setattr(workshop.genai, "Client", lambda **kw: type("Client", (), {"models": Provider()})())
    return calls


def validate(data):
    if data.get("result_index") != 7:
        raise ValueError("Report postshow: held match requires actual result evidence")


def test_complete_source_invalid_result_index_bounded_fallback(monkeypatch):
    calls = mock_generate(monkeypatch, ['{"result_index":999}', '{"result_index":7}'])
    data, model = workshop.generate_json("offline", chain_name="report_blocks_test", response_validator=validate)
    assert data["result_index"] == 7
    assert model == "gemini-3.5-flash-lite"
    assert len(calls) == 2


def test_complete_source_repeated_invalid_index_does_not_escalate_to_premium(monkeypatch):
    calls = mock_generate(monkeypatch, ['{"result_index":999}', '{"result_index":998}'])
    with pytest.raises(workshop.ReportModelValidationError, match="actual result evidence"):
        workshop.generate_json("offline", chain_name="report_blocks_test", response_validator=validate)
    assert calls == ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]


def test_transient_503_still_falls_back_and_sets_cooldown(monkeypatch):
    calls = mock_generate(monkeypatch, [RuntimeError("503 temporarily unavailable"), '{"result_index":7}'])
    cooldown = set()
    data, _ = workshop.generate_json("offline", chain_name="report_blocks_test",
                                     response_validator=validate, cooldown_models=cooldown)
    assert data["result_index"] == 7
    assert "gemini-3.1-flash-lite" in cooldown
    assert len(calls) == 2


def usage():
    return {"usage_available": True, "input_tokens": 1000, "cached_input_tokens": 200,
            "output_tokens": 400, "thinking_tokens": 50, "total_tokens": 1450,
            "total_tokens_provider_reported": True}


def test_38_dated_pricing_and_missing_date():
    from decimal import Decimal
    dec = calculate_v96_2_cost(usage(), "gemini-3.8-flash", timestamp="2026-12-31T23:59:59+00:00")
    jan = calculate_v96_2_cost(usage(), "gemini-3.8-flash", timestamp="2027-01-01T00:00:00+00:00")
    no_date = calculate_v96_2_cost(usage(), "gemini-3.8-flash")
    assert dec["cost_resolution_status"] == "resolved"
    assert jan["cost_resolution_status"] == "resolved"
    expected = (Decimal(800)*Decimal("0.75") + Decimal(200)*Decimal("0.075") +
                Decimal(450)*Decimal("3.75")) / Decimal(1000000)
    assert Decimal(dec["computed_list_price_cost"]) == expected
    assert Decimal(jan["computed_list_price_cost"]) == expected * 2
    assert no_date["cost_resolution_status"] == "unresolved"
    assert no_date["cost_resolution_reason"] == "pricing_date_unresolved"
    assert calculate_v96_2_cost(usage(), "gemini-2.5-pro")["cost_resolution_status"] == "resolved"


def test_env_migration_preview_apply_idempotent_and_preserves_metadata(tmp_path):
    original = (
        "WP_PASSWORD=keep-this-secret\r\n"
        "REPORT_GEMINI_MODEL_CHAIN='gemini-3.1-flash-lite,gemini-2.5-pro,gemini-3.8-flash'\r\n"
        "GEMINI_REPORT_MODEL_CHAIN=gemini-3.1-flash-lite,gemini-2.5-pro # keep this comment\r\n"
        "BOB_PREMIUM_MODEL_CHAIN=gemini-3.1-flash-lite,gemini-3.5-flash\r\n"
    )
    path = tmp_path / ".env"
    path.write_bytes(original.encode())
    os.chmod(path, 0o600)
    preview, keys = migrate(original)
    assert len(keys) == 2
    assert "WP_PASSWORD=keep-this-secret\r\n" in preview
    assert "gemini-2.5-pro" not in preview
    assert preview.count("gemini-3.8-flash") == 2
    assert preview.count("\r\n") == 4
    changed, backup = install(path, apply=True)
    assert changed == keys
    assert backup is not None and backup.read_bytes() == original.encode()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert install(path, apply=True)[0] == []
    assert path.read_bytes() == preview.encode()
