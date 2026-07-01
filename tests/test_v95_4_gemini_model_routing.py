import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import alfred_policy_v93_20 as alfred
from agents import bob
from agents import gemini_ledger
from agents import menzo_policy_v93_15 as menzo


def patch_ledger_paths(tmp_path, monkeypatch):
    state = tmp_path / "state" / "newsroom"
    artifacts = tmp_path / "artifacts" / "newsroom"
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", state)
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", artifacts)
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", state / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", artifacts / "gemini_call_ledger_latest.json")
    monkeypatch.setattr(menzo, "record_gemini_event", gemini_ledger.record_gemini_event)


def test_bob_uses_standard_chain_for_low_score_or_missing_metadata(monkeypatch):
    monkeypatch.setattr(bob, "LEGACY_BOB_MODEL_CHAIN_OVERRIDE", False)
    low = bob.bob_model_routing({"score": 30, "priority_label": "low", "article_type": "hard_news", "category_hint": "WWE"})
    missing = bob.bob_model_routing({})
    assert low["kind"] == "standard"
    assert missing["kind"] == "standard"
    assert "gemini-3.5-flash" not in low["chain"]
    assert "gemini-3.5-flash" not in missing["chain"]


def test_bob_uses_premium_chain_for_high_score_or_high_important_type(monkeypatch):
    monkeypatch.setattr(bob, "LEGACY_BOB_MODEL_CHAIN_OVERRIDE", False)
    by_score = bob.bob_model_routing({"score": 85, "priority_label": "medium", "article_type": "soft_news"})
    by_type = bob.bob_model_routing({"score": 50, "priority_label": "high", "article_type": "major_return"})
    assert by_score["kind"] == "premium"
    assert by_type["kind"] == "premium"
    assert by_score["chain"][0] == "gemini-3.5-flash"



def test_bob_legacy_override_uses_bob_specific_chain(monkeypatch):
    monkeypatch.setattr(bob, "BOB_GEMINI_MODEL_CHAIN_SET", True)
    monkeypatch.setattr(bob, "GEMINI_MODEL_CHAIN_SET", False)
    monkeypatch.setattr(bob, "LEGACY_BOB_MODEL_CHAIN_OVERRIDE", True)
    monkeypatch.setattr(bob, "MODEL_CHAIN", ["bob-a", "bob-b"])
    routing = bob.bob_model_routing({"score": 10})
    assert routing["kind"] == "legacy_override"
    assert routing["chain"] == ["bob-a", "bob-b"]
    assert routing["reason"] == "BOB_GEMINI_MODEL_CHAIN explicitly set"


def test_bob_legacy_override_uses_generic_gemini_model_chain(monkeypatch):
    monkeypatch.setattr(bob, "BOB_GEMINI_MODEL_CHAIN_SET", False)
    monkeypatch.setattr(bob, "GEMINI_MODEL_CHAIN_SET", True)
    monkeypatch.setattr(bob, "LEGACY_BOB_MODEL_CHAIN_OVERRIDE", True)
    monkeypatch.setattr(bob, "MODEL_CHAIN", ["custom-a", "custom-b"])
    routing = bob.bob_model_routing({"score": 10})
    assert routing["kind"] == "legacy_override"
    assert routing["chain"] == ["custom-a", "custom-b"]
    assert routing["reason"] == "GEMINI_MODEL_CHAIN explicitly set"

def test_menzo_does_not_call_35_when_high_ambiguity_gate_not_satisfied(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)
    item = {"title": "Minor story", "score": 50}
    records = [{"title": "A", "score": 50}, {"title": "B", "score": 50, "publisher_history_origin": "suspicious"}]
    ai_data = {"cluster_type": "uncertain", "decision": "pending_review", "confidence": 20}
    allowed, reason = menzo.menzo_second_pass_gate(item, records, ai_data)
    assert allowed is False
    assert reason == "high_ambiguity_gate_not_met"
    menzo._record_menzo_second_pass_avoided(reason, {"title": item["title"]})
    rec = json.loads(gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["status"] == "avoided"
    assert rec["saved_gemini_call"] is True


def test_menzo_can_use_35_for_high_ambiguity_duplicate_arbitration(monkeypatch):
    monkeypatch.setattr(menzo, "MENZO_ENABLE_35_FOR_HIGH_AMBIGUITY", True)
    item = {"title": "Major story", "score": 90}
    records = [{"title": "A", "score": 90}, {"title": "B", "score": 88, "publisher_history_origin": "suspicious"}]
    ai_data = {"cluster_type": "same_core_fact_new_angle", "decision": "pending_followup", "confidence": 50}
    allowed, reason = menzo.menzo_second_pass_gate(item, records, ai_data)
    assert allowed is True
    assert reason == "high_ambiguity_duplicate_novelty_arbitration"


def test_menzo_cooldown_avoids_second_35_attempt_same_title_after_503(tmp_path, monkeypatch):
    patch_ledger_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    menzo.MENZO_MODEL_COOLDOWN_FAILURES.clear()

    class Models:
        def generate_content(self, model, contents):
            raise RuntimeError("503 UNAVAILABLE high demand")

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", Client)
    ctx = {"title": "Same title"}
    menzo.call_gemini_json_model("{}", "gemini-3.5-flash", ledger_context=ctx, phase="duplicate_arbitration_second_pass")
    menzo.call_gemini_json_model("{}", "gemini-3.5-flash", ledger_context=ctx, phase="duplicate_arbitration_second_pass")
    records = [json.loads(line) for line in gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()]
    assert records[-1]["status"] == "avoided"
    assert records[-1]["reason"] == "model_cooldown_after_failure"
    assert records[-1]["saved_gemini_call"] is True


def test_alfred_quote_resolver_default_has_no_gemini_35():
    assert "gemini-3.5-flash" not in alfred.ALFRED_QUOTE_RESOLVER_MODEL_CHAIN
