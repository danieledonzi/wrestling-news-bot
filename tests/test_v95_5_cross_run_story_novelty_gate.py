import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import gemini_ledger
from agents import menzo_policy_v93_15 as menzo


def patch_paths(tmp_path, monkeypatch):
    state = tmp_path / "state" / "newsroom"
    artifacts = tmp_path / "artifacts" / "newsroom"
    monkeypatch.setattr(menzo, "NEWSROOM_STATE_DIR", state)
    monkeypatch.setattr(menzo, "MASTER_LOG_FILE", state / "master_log.jsonl")
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", state)
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", artifacts)
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", state / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", artifacts / "gemini_call_ledger_latest.json")
    monkeypatch.setattr(menzo, "record_gemini_event", gemini_ledger.record_gemini_event)
    state.mkdir(parents=True, exist_ok=True)


def base_result(item):
    return {"selected": [item], "pending": [], "skipped": [], "postprocess": {}, "daily_policy": {}}


def test_no_cross_run_match_keeps_selected_and_avoids_ai(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [{"title": "CM Punk firma un nuovo contratto", "url": "https://old.test/punk"}])
    result = base_result({"title": "Mercedes Moné aggiunta a Dynamite", "url": "https://new.test/mercedes", "score": 90})

    menzo.apply_cross_run_novelty_gate(result)

    assert len(result["selected"]) == 1
    assert result["selected"][0]["cross_run_novelty_decision"] == "none"
    assert result["selected"][0]["cross_run_novelty_reason"] == "no_cross_run_match"
    assert result["postprocess"]["cross_run_novelty_ai_calls"] == 0
    assert result["postprocess"]["cross_run_novelty_ai_avoided"] == 0
    assert not gemini_ledger.LEDGER_FILE.exists()


def test_same_story_without_novelty_not_selected_when_ai_disabled(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(menzo, "MENZO_CROSS_RUN_NOVELTY_AI_ENABLED", False)
    old = {"title": "Big Bill verso il ritorno in WWE alla scadenza del contratto AEW", "url": "https://old.test/big-bill"}
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [old])
    result = base_result({"title": "Big Bill possibile ritorno in WWE", "url": "https://new.test/big-bill", "score": 92})

    menzo.apply_cross_run_novelty_gate(result)

    assert result["selected"] == []
    assert len(result["pending"]) == 1
    assert result["pending"][0]["cross_run_novelty_decision"] == "pending"
    assert result["postprocess"]["cross_run_novelty_pending"] == 1


def test_same_story_with_contract_and_new_entity_novelty_is_allowed(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    old = {"title": "Big Bill verso il ritorno in WWE alla scadenza del contratto AEW", "url": "https://old.test/big-bill"}
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [old])
    result = base_result({"title": "Big Bill lascia la AEW, possibile ritorno in WWE con Enzo Amore", "url": "https://new.test/big-bill-enzo", "score": 94})

    menzo.apply_cross_run_novelty_gate(result)

    assert len(result["selected"]) == 1
    selected = result["selected"][0]
    assert selected["cross_run_novelty_decision"] == "allow"
    assert "new_entity" in selected["cross_run_novelty_codes"]
    assert "contract_status_changed" in selected["cross_run_novelty_codes"]
    assert result["postprocess"]["cross_run_novelty_ai_avoided"] == 1
    record = json.loads(gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()[-1])
    assert record["reason"] == "deterministic_novelty_allow"
    assert record["saved_gemini_call"] is True


def test_ai_fallback_allow_and_skip_and_malformed_pending(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    old = {"title": "John Doe verso il ritorno in WWE", "url": "https://old.test/john"}
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda lookback_hours=None: [old])

    def run_with(ai_data):
        monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *args, **kwargs: (ai_data, "gemini-3.1-flash-lite") if ai_data != "MALFORMED" else (None, "invalid_json:gemini-3.1-flash-lite"))
        result = base_result({"title": "John Doe possibile ritorno in WWE", "url": f"https://new.test/{ai_data}", "score": 90})
        menzo.apply_cross_run_novelty_gate(result)
        return result

    allowed = run_with({"same_story": True, "has_material_novelty": True, "novelty_codes": ["new_source"], "decision": "allow", "reason": "new source"})
    skipped = run_with({"same_story": True, "has_material_novelty": False, "novelty_codes": [], "decision": "skip", "reason": "same rumor"})
    pending = run_with("MALFORMED")

    assert len(allowed["selected"]) == 1
    assert skipped["selected"] == [] and len(skipped["skipped"]) == 1
    assert pending["selected"] == [] and len(pending["pending"]) == 1


def test_default_cross_run_novelty_model_is_low_cost_not_35():
    assert menzo.MENZO_CROSS_RUN_NOVELTY_AI_MODEL == "gemini-3.1-flash-lite"
    assert "gemini-3.5-flash" not in menzo.MENZO_CROSS_RUN_NOVELTY_AI_MODEL
