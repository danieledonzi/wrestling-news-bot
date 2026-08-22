import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import newsroom_runner
from agents import gemini_ledger


def patch_ledger_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", tmp_path / "state" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", tmp_path / "artifacts" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", tmp_path / "state" / "newsroom" / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", tmp_path / "artifacts" / "newsroom" / "gemini_call_ledger_latest.json")
    monkeypatch.setenv("NEWSROOM_RUN_ID", "run-test")


def test_gemini_ledger_records_called_and_andrea_avoided(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)

    gemini_ledger.record_gemini_event(agent="Menzo", phase="duplicate_arbitration", model="gemini-test", status="called", reason="ai_duplicate_arbitration")
    gemini_ledger.record_andrea_avoided({"title": "Blocked", "url": "https://example.test/a", "source": "Feed"})

    lines = gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["status"] == "called"
    assert records[1]["status"] == "avoided"
    assert records[1]["agent"] == "Andrea"
    assert records[1]["would_have_agent"] == "Bob"
    assert records[1]["saved_gemini_call"] is True

    latest = json.loads(gemini_ledger.LATEST_FILE.read_text(encoding="utf-8"))
    assert latest["summary"]["gemini_calls_total"] == 1
    assert latest["summary"]["gemini_calls_by_agent"] == {"Menzo": 1}
    assert latest["summary"]["gemini_calls_avoided_total"] == 1
    assert latest["summary"]["gemini_calls_avoided_by_andrea"] == 1


def test_andrea_blocked_items_drive_avoided_ledger(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)
    andrea_result = {
        "handoff": {"andrea_checked": 3, "andrea_passed": 1, "andrea_blocked": 2, "saved_gemini_calls": 2},
        "blocked_items": [
            {"title": "Too thin 1", "url": "https://example.test/1", "reason": "insufficient_content"},
            {"title": "Too thin 2", "url": "https://example.test/2", "reason": "insufficient_content"},
        ],
        "selected": [{"title": "Passed", "url": "https://example.test/3"}],
    }

    newsroom_runner.record_andrea_avoids_from_result(andrea_result)
    summary = gemini_ledger.write_latest_snapshot()["summary"]

    assert newsroom_runner.andrea_blocked_count(andrea_result) == 2
    assert summary["gemini_calls_avoided_by_andrea"] == andrea_result["handoff"]["andrea_blocked"]
    assert summary["gemini_calls_avoided_total"] == andrea_result["handoff"]["andrea_blocked"]


def test_andrea_count_only_creates_synthetic_avoided_records(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)
    andrea_result = {"handoff": {"andrea_blocked": 3, "saved_gemini_calls": 3}}

    newsroom_runner.record_andrea_avoids_from_result(andrea_result)
    records = gemini_ledger.latest_for_run()["records"]

    assert len(records) == 3
    assert all(record["agent"] == "Andrea" for record in records)
    assert all(record["status"] == "avoided" for record in records)
    assert gemini_ledger.summarize(records)["gemini_calls_avoided_by_andrea"] == 3

class UsageObj:
    def __init__(self, **kwargs):
        self.usage_metadata = type("Meta", (), kwargs)()
        self.text = "ok"


def test_v95_13a_extracts_object_and_dict_usage():
    obj = UsageObj(prompt_token_count=10, candidates_token_count=5, total_token_count=15, cached_content_token_count=2, thoughts_token_count=1)
    usage = gemini_ledger.extract_usage_metadata(obj)
    assert usage["usage_available"] is True
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 5
    assert usage["total_tokens"] == 15
    assert usage["cached_input_tokens"] == 2
    assert usage["thinking_tokens"] == 1

    usage2 = gemini_ledger.extract_usage_metadata({"usage_metadata": {"input_token_count": 0, "output_token_count": 7, "cached_input_token_count": 0, "thinking_token_count": 3}})
    assert usage2["usage_available"] is True
    assert usage2["input_tokens"] == 0
    assert usage2["cached_input_tokens"] == 0
    assert usage2["total_tokens"] == 7
    assert "total_tokens_derived" in usage2["usage_warning"]


def test_v95_13a_missing_and_malformed_usage_are_fail_soft():
    missing = gemini_ledger.extract_usage_metadata(object())
    assert missing["usage_available"] is False
    assert missing["input_tokens"] is None
    bad = gemini_ledger.extract_usage_metadata({"usage_metadata": {"prompt_token_count": "abc"}})
    assert bad["usage_available"] is False
    assert bad["input_tokens"] is None
    assert "malformed_prompt_token_count" in bad["usage_warning"]


def test_v95_13a_pricing_fixture_alias_and_unknown(tmp_path, monkeypatch):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({
        "schema_version": "v95.13_pricing.v1", "price_table_version": "test-v1", "currency": "USD", "aliases": {"alias-model": "priced-model"},
        "models": {"priced-model": {"input_price_per_million": "1.25", "output_price_per_million": "2.50", "cached_input_price_per_million": "0.25"}}
    }), encoding="utf-8")
    monkeypatch.setenv("GEMINI_PRICING_FILE", str(pricing))
    usage = {"usage_available": True, "input_tokens": 1000, "output_tokens": 2000, "cached_input_tokens": 4000}
    cost = gemini_ledger.calculate_estimated_cost(usage, "alias-model")
    assert cost["pricing_model_key"] == "priced-model"
    assert cost["estimated_input_cost"] == "0.00125"
    assert cost["estimated_output_cost"] == "0.005"
    assert cost["estimated_cached_input_cost"] == "0.001"
    assert cost["estimated_cost"] == "0.00725"
    unknown = gemini_ledger.calculate_estimated_cost(usage, "unknown-model")
    assert unknown["estimated_cost"] is None
    assert unknown["pricing_warning"] == "price_not_configured:unknown-model"


def test_v95_13a_records_attempts_avoided_fallback_retry_repair_and_v1(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"price_table_version": "test", "currency": "USD", "aliases": {}, "models": {"m1": {"input_price_per_million": "1", "output_price_per_million": "1", "cached_input_price_per_million": "1"}, "m2": {"input_price_per_million": "2", "output_price_per_million": "2"}}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_PRICING_FILE", str(pricing))
    op = "Bob:candidate:translation:test"
    gemini_ledger.record_gemini_attempt(response=UsageObj(prompt_token_count=1, candidates_token_count=1, total_token_count=2), agent="Bob", phase="translate_article", model_requested="m1", status="failed", result="err", operation_id=op, attempt_index=0)
    gemini_ledger.record_gemini_attempt(response=UsageObj(prompt_token_count=2, candidates_token_count=3, total_token_count=5), agent="Bob", phase="translate_article", model_requested="m2", status="called", result="text", operation_id=op, attempt_index=1, fallback=True)
    gemini_ledger.record_gemini_attempt(response=None, agent="Bob", phase="translate_article", model_requested="m2", status="failed", result="err", operation_id=op, attempt_index=2, retry=True)
    gemini_ledger.record_gemini_attempt(response=UsageObj(prompt_token_count=1, candidates_token_count=2, total_token_count=3), agent="Menzo", phase="duplicate_repair", model_requested="m1", status="called", result="valid_json", operation_id="repair-op", attempt_index=0, repair=True)
    gemini_ledger.record_gemini_event(ledger_schema_version="v2", agent="Andrea", phase="guard", model="m1", status="avoided", reason="blocked", saved_gemini_call=True)
    gemini_ledger.LEDGER_FILE.write_text(json.dumps({"timestamp":"2026-01-01T00:00:00+00:00","agent":"Legacy","status":"called","model":"old"}) + "\n" + gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    records = gemini_ledger.iter_records()
    assert len(records) == 6
    legacy = records[0]
    assert legacy["ledger_schema_version"] == "v1"
    assert legacy["usage_available"] is False
    assert legacy["estimated_cost"] is None
    rows = records[1:]
    assert rows[0]["operation_id"] == rows[1]["operation_id"] == rows[2]["operation_id"] == op
    assert [rows[i]["attempt_index"] for i in range(3)] == [0, 1, 2]
    assert rows[1]["fallback"] is True
    assert rows[2]["retry"] is True and rows[2]["usage_available"] is False
    assert rows[3]["repair"] is True and rows[3]["operation_id"] == "repair-op"
    assert rows[4]["status"] == "avoided" and rows[4]["estimated_cost"] == "0" and rows[4]["usage_source"] == "avoided_no_api_call"
    summary = gemini_ledger.summarize(records)
    assert summary["gemini_calls_total"] == 3  # v1 called plus two successful v2 calls; failed and avoided excluded
    assert summary["v2_real_attempts"] == 4
    assert summary["real_attempts_with_usage"] == 3
    assert summary["real_attempts_with_cost"] == 0  # v3 monetary authority is computed_* only

class ActualResponse:
    def __init__(self, text="ok", actual=None, usage=None):
        self.text = text
        if actual is not None:
            self.model_version = actual
        self.usage_metadata = usage if usage is not None else type("Meta", (), {"prompt_token_count": 1, "candidates_token_count": 2, "total_token_count": 3})()


def test_v95_13a_actual_model_and_default_v2_no_rewrite(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)
    old = {"timestamp": "2026-01-01T00:00:00+00:00", "agent": "Legacy", "status": "called", "model": "old"}
    gemini_ledger.LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    gemini_ledger.LEDGER_FILE.write_text(json.dumps(old) + "\n", encoding="utf-8")
    before = gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8")
    gemini_ledger.record_gemini_event(agent="Andrea", phase="guard", status="avoided", reason="blocked")
    gemini_ledger.record_gemini_attempt(response=ActualResponse(actual="actual-model"), agent="Bob", phase="p", model_requested="requested-model", status="called")
    gemini_ledger.record_gemini_attempt(response=ActualResponse(actual=None), agent="Bob", phase="p", model_requested="requested-only", status="called")
    after_lines = gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()
    assert after_lines[0] == before.strip()
    rows = [json.loads(line) for line in after_lines]
    assert rows[1]["ledger_schema_version"] == "v2" and rows[1]["usage_source"] == "avoided_no_api_call"
    assert rows[2]["model_requested"] == "requested-model" and rows[2]["actual_model"] == "actual-model" and rows[2]["model"] == "actual-model"
    assert rows[3]["model_requested"] == "requested-only" and rows[3]["actual_model"] is None and rows[3]["model"] == "requested-only"
    assert gemini_ledger.iter_records()[0]["ledger_schema_version"] == "v1"


def test_v95_13a_camelcase_empty_and_all_malformed_usage():
    usage = gemini_ledger.extract_usage_metadata({"usageMetadata": {"promptTokenCount": 0, "candidatesTokenCount": 5, "totalTokenCount": 5, "cachedInputTokenCount": 0, "thinkingTokenCount": 0}})
    assert usage["usage_available"] is True
    assert usage["usage_source"] == "usageMetadata"
    assert usage["input_tokens"] == 0 and usage["thinking_tokens"] == 0
    empty = gemini_ledger.extract_usage_metadata({"usage_metadata": {}})
    assert empty["usage_available"] is False
    assert "no_recognized" in empty["usage_warning"]
    bad = gemini_ledger.extract_usage_metadata({"usage_metadata": {"prompt_token_count": "bad", "total_token_count": "also-bad"}})
    assert bad["usage_available"] is False
    assert "all_token_fields_malformed" in bad["usage_warning"]


def test_v95_13a_incomplete_cost_semantics_and_no_usage_no_warning(tmp_path, monkeypatch):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"price_table_version": "test", "currency": "USD", "aliases": {}, "models": {"m": {"input_price_per_million": "1"}, "m2": {"input_price_per_million": "1", "output_price_per_million": "1"}}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_PRICING_FILE", str(pricing))
    missing_output = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 10, "output_tokens": 20}, "m")
    assert missing_output["estimated_input_cost"] == "0.00001"
    assert missing_output["estimated_cost"] is None
    assert "incomplete_price_configuration" in missing_output["pricing_warning"]
    missing_cached = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 10, "output_tokens": 20, "cached_input_tokens": 5}, "m2")
    assert missing_cached["estimated_cost"] is None and "cached_input" in missing_cached["pricing_warning"]
    zero_cached = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 10, "output_tokens": 20, "cached_input_tokens": 0}, "m2")
    assert zero_cached["estimated_cost"] == "0.00003"
    assert zero_cached["estimated_cached_input_cost"] == "0"
    no_usage = gemini_ledger.calculate_estimated_cost({"usage_available": False}, "unknown")
    assert no_usage["estimated_cost"] is None and no_usage["pricing_warning"] is None

def test_v95_13a_integer_operation_id_key_and_billable_component_semantics(tmp_path, monkeypatch):
    op = gemini_ledger.make_operation_id("Bob", "translate", 12345)
    assert ":12345:" in op
    patch_ledger_paths(tmp_path, monkeypatch)
    gemini_ledger.record_gemini_attempt(response=ActualResponse(), agent="Bob", phase="translate", model_requested="m", status="called", operation_id=op, candidate_id=12345)
    rows = [json.loads(line) for line in gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == 12345


def test_v95_13a_no_billable_tokens_do_not_emit_false_zero_cost(tmp_path, monkeypatch):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"price_table_version": "test", "currency": "USD", "aliases": {}, "models": {"m": {"input_price_per_million": "1", "output_price_per_million": "2"}}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_PRICING_FILE", str(pricing))
    only_total = gemini_ledger.calculate_estimated_cost({"usage_available": True, "total_tokens": 7}, "m")
    assert only_total["estimated_cost"] is None
    assert only_total["pricing_warning"] == "no_billable_token_components"
    no_billable = gemini_ledger.calculate_estimated_cost({"usage_available": True, "total_tokens": 7}, "m")
    assert no_billable["estimated_cost"] is None
    assert no_billable["pricing_warning"] == "no_billable_token_components"
    zero_io = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 0, "output_tokens": 0}, "m")
    assert zero_io["estimated_cost"] == "0"
    normal = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 1000, "output_tokens": 1000}, "m")
    assert normal["estimated_cost"] == "0.003"

def test_v95_13a_thinking_tokens_use_output_rate_and_are_not_double_counted(tmp_path, monkeypatch):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"price_table_version": "thinking-test", "currency": "USD", "aliases": {}, "models": {"m": {"input_price_per_million": "1", "output_price_per_million": "2", "cached_input_price_per_million": "0.5"}}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_PRICING_FILE", str(pricing))
    cost = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 10, "output_tokens": 100, "thinking_tokens": 50, "cached_input_tokens": 20, "total_tokens": 999999}, "m")
    assert cost["estimated_input_cost"] == "0.00001"
    assert cost["estimated_output_cost"] == "0.0002"
    assert cost["estimated_thinking_cost"] == "0.0001"
    assert cost["estimated_cached_input_cost"] == "0.00001"
    assert cost["estimated_cost"] == "0.00032"


def test_v95_13a_thinking_without_output_uses_output_rate(tmp_path, monkeypatch):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"price_table_version": "thinking-test", "currency": "USD", "aliases": {}, "models": {"m": {"output_price_per_million": "2"}}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_PRICING_FILE", str(pricing))
    cost = gemini_ledger.calculate_estimated_cost({"usage_available": True, "thinking_tokens": 50}, "m")
    assert cost["estimated_output_cost"] is None
    assert cost["estimated_thinking_cost"] == "0.0001"
    assert cost["estimated_cost"] == "0.0001"


def test_v95_13a_nonzero_thinking_requires_output_price(tmp_path, monkeypatch):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"price_table_version": "thinking-test", "currency": "USD", "aliases": {}, "models": {"m": {"input_price_per_million": "1"}}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_PRICING_FILE", str(pricing))
    cost = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 10, "thinking_tokens": 50}, "m")
    assert cost["estimated_input_cost"] == "0.00001"
    assert cost["estimated_thinking_cost"] is None
    assert cost["estimated_cost"] is None
    assert "incomplete_price_configuration:thinking" in cost["pricing_warning"]


def test_v95_13a_zero_and_absent_thinking_semantics(tmp_path, monkeypatch):
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"price_table_version": "thinking-test", "currency": "USD", "aliases": {}, "models": {"m": {"input_price_per_million": "1"}, "m2": {"input_price_per_million": "1", "output_price_per_million": "2"}}}), encoding="utf-8")
    monkeypatch.setenv("GEMINI_PRICING_FILE", str(pricing))
    zero = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 10, "thinking_tokens": 0}, "m")
    assert zero["estimated_thinking_cost"] == "0"
    assert zero["estimated_cost"] == "0.00001"
    assert zero["pricing_warning"] is None
    absent = gemini_ledger.calculate_estimated_cost({"usage_available": True, "input_tokens": 10}, "m2")
    assert absent["estimated_thinking_cost"] is None
    assert absent["estimated_cost"] == "0.00001"
