import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import alfred, alfred_policy_v93_20, bob, publisher
from agents import andrea_policy_v94_15 as andrea
from agents import menzo as base_menzo
from agents import menzo_policy_v93_15 as menzo
from agents import source_body



@pytest.fixture(autouse=True)
def canonical_fixture_bodies(monkeypatch):
    def hydrate(record):
        if source_body.contract_text(record): return True,"canonical_cache"
        text=str(record.get("summary") or record.get("title") or record.get("title_it") or "fixture article")
        text += " Complete fixture source body with all factual paragraphs, participants, chronology, context, outcome, and relevant editorial detail." * 2
        record["canonical_source_body"]=source_body.contract_from_elements(str(record.get("source_url") or record.get("url") or ""),[{"type":"text","text":text}],{"stage":"extraction_finished","extraction_finished":True,"body_complete":True,"body_complete_reason":"verified_test_fixture","clean_element_count":1,"root_text_chars":len(text),"extracted_text_chars":len(text),"root_coverage_ratio":1.0,"structured_article_body_chars":0,"structured_coverage_ratio":None,"truncation_access_markers":[]})
        return True,"fixture_bob_extraction"
    monkeypatch.setattr(menzo.source_body,"hydrate",hydrate)


def item(url, title, summary=None, section="selected", score=90):
    summary = summary or title
    return {"url": url, "source_url": url, "title": title, "source_title": title, "source": "Test", "summary": summary, "description": summary, "body_html": "<p>" + summary + "</p>", "score": score, "decision": section, "priority": "hard" if section == "selected" else "soft", "ai_priority_label": "high"}


def result(items):
    return {"selected": [x for x in items if x["decision"] == "selected"], "pending": [x for x in items if x["decision"] == "pending"], "skipped": [], "postprocess": {}}



def base_candidate(url, title):
    return {"url": url, "source_url": url, "title": title, "summary": title, "source": "Test"}


def isolate_wrapper_state(monkeypatch, tmp_path):
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE", tmp_path / "duplicate_cache.json")
    publisher_history = tmp_path / "publisher_history.json"
    publisher_history.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(menzo, "publisher_history_file", lambda: publisher_history)
    monkeypatch.setattr(menzo, "SOFTPOOL_FILE", tmp_path / "softpool.json")
    monkeypatch.setattr(menzo, "HARD_SKIP_FILE", tmp_path / "hard_skips.json")



def test_base_menzo_default_persistence_compatibility(monkeypatch, tmp_path):
    monkeypatch.setattr(base_menzo, "AI_ENABLED", False)
    art = tmp_path / "artifacts" / "menzo.json"
    dec = tmp_path / "state" / "menzo.json"
    urls = tmp_path / "state" / "urls.json"
    monkeypatch.setattr(base_menzo, "ARTIFACT_DECISIONS_FILE", art)
    monkeypatch.setattr(base_menzo, "MENZO_DECISIONS_FILE", dec)
    monkeypatch.setattr(base_menzo, "V92_ALLOWED_URLS_FILE", urls)
    out = base_menzo.run_menzo({"news_candidates_for_menzo": [base_candidate("https://persist/one", "CM Punk signs WWE contract")]})
    assert art.exists() and dec.exists() and urls.exists()
    assert out["daily_policy"]["base_capacity_limits_applied"] is True
    assert out["daily_policy"]["base_outputs_persisted"] is True
    assert out["input"]["base_outputs_persisted"] is True


def test_base_internal_mode_preserves_existing_output_files(monkeypatch, tmp_path):
    monkeypatch.setattr(base_menzo, "AI_ENABLED", False)
    art = tmp_path / "artifacts" / "menzo.json"
    dec = tmp_path / "state" / "menzo.json"
    urls = tmp_path / "state" / "urls.json"
    for path in [art, dec, urls]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"sentinel": true}', encoding="utf-8")
    monkeypatch.setattr(base_menzo, "ARTIFACT_DECISIONS_FILE", art)
    monkeypatch.setattr(base_menzo, "MENZO_DECISIONS_FILE", dec)
    monkeypatch.setattr(base_menzo, "V92_ALLOWED_URLS_FILE", urls)
    board = {"news_candidates_for_menzo": [base_candidate(f"https://internal/{i}", f"CM Punk signs WWE contract {i}") for i in range(8)]}
    out = base_menzo.run_menzo(board, apply_capacity_limits=False, persist_outputs=False)
    assert len(out["selected"]) == 8
    assert out["daily_policy"]["base_capacity_limits_applied"] is False
    assert out["daily_policy"]["base_outputs_persisted"] is False
    assert out["input"]["base_outputs_persisted"] is False
    assert art.read_text(encoding="utf-8") == '{"sentinel": true}'
    assert dec.read_text(encoding="utf-8") == '{"sentinel": true}'
    assert urls.read_text(encoding="utf-8") == '{"sentinel": true}'


def test_no_provisional_allowed_url_write_and_final_wrapper_write(monkeypatch, tmp_path):
    isolate_wrapper_state(monkeypatch, tmp_path)
    monkeypatch.setattr(menzo, "_wp_ready_for_costly_work", lambda: (True, "ok"))
    for obj in [base_menzo, menzo.base]:
        monkeypatch.setattr(obj, "AI_ENABLED", False)
        monkeypatch.setattr(obj, "ARTIFACT_DECISIONS_FILE", tmp_path / "base_artifacts" / "menzo.json")
        monkeypatch.setattr(obj, "MENZO_DECISIONS_FILE", tmp_path / "base_state" / "menzo.json")
        monkeypatch.setattr(obj, "V92_ALLOWED_URLS_FILE", tmp_path / "base_state" / "urls.json")
    final_art = tmp_path / "wrapper_artifacts" / "menzo.json"
    final_dec = tmp_path / "wrapper_state" / "menzo.json"
    final_urls = tmp_path / "wrapper_state" / "urls.json"
    monkeypatch.setattr(menzo, "ARTIFACT_DECISIONS_FILE", final_art)
    monkeypatch.setattr(menzo, "MENZO_DECISIONS_FILE", final_dec)
    monkeypatch.setattr(menzo, "V92_ALLOWED_URLS_FILE", final_urls)
    monkeypatch.setattr(menzo, "load_cross_run_story_history", lambda *a, **k: [])
    monkeypatch.setattr(menzo, "save_softpool", lambda r: None)
    monkeypatch.setattr(menzo, "save_hard_skips", lambda r: None)
    monkeypatch.setattr(menzo, "remember_stories", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_footprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_fingerprints", lambda *a, **k: None)
    writes = []
    real_write = menzo.write_json
    def spy(path, data):
        writes.append((Path(path), data))
        real_write(path, data)
    monkeypatch.setattr(menzo, "write_json", spy)
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: ({"duplicate_groups": [{"keep_id": "c0", "discard_ids": ["c1"], "reason": "same"}]}, "gemini-3.1-flash-lite"))
    board = {"news_candidates_for_menzo": [base_candidate("https://safe/winner", "CM Punk signs WWE contract"), base_candidate("https://safe/loser", "CM Punk signs WWE contract")]}
    out = menzo.run_menzo(board)
    allowed_writes = [data for path, data in writes if path == final_urls]
    assert len(allowed_writes) == 1
    assert allowed_writes[0]["allowed_urls"] == ["https://safe/winner"]
    assert "https://safe/loser" not in final_urls.read_text(encoding="utf-8")
    assert not (tmp_path / "base_state" / "urls.json").exists()
    assert out["allowed_urls_for_v92"] == ["https://safe/winner"]


def test_wrapper_exception_after_base_leaves_existing_allowed_urls_intact(monkeypatch, tmp_path):
    isolate_wrapper_state(monkeypatch, tmp_path)
    sentinel = tmp_path / "wrapper_state" / "urls.json"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text('{"allowed_urls": ["https://safe/sentinel"]}', encoding="utf-8")
    monkeypatch.setattr(menzo, "_wp_ready_for_costly_work", lambda: (True, "ok"))
    monkeypatch.setattr(menzo, "V92_ALLOWED_URLS_FILE", sentinel)
    for obj in [base_menzo, menzo.base]:
        monkeypatch.setattr(obj, "AI_ENABLED", False)
        monkeypatch.setattr(obj, "ARTIFACT_DECISIONS_FILE", tmp_path / "base_artifacts" / "menzo.json")
        monkeypatch.setattr(obj, "MENZO_DECISIONS_FILE", tmp_path / "base_state" / "menzo.json")
        monkeypatch.setattr(obj, "V92_ALLOWED_URLS_FILE", tmp_path / "base_state" / "urls.json")
    def boom(result):
        raise RuntimeError("post-base failure")
    monkeypatch.setattr(menzo, "normalize_ai_fields", boom)
    try:
        menzo.run_menzo({"news_candidates_for_menzo": [base_candidate("https://unsafe/provisional", "CM Punk signs WWE contract")]})
    except RuntimeError:
        pass
    assert sentinel.read_text(encoding="utf-8") == '{"allowed_urls": ["https://safe/sentinel"]}'
    assert not (tmp_path / "base_state" / "urls.json").exists()

def test_base_menzo_default_capacity_limits_remain(monkeypatch, tmp_path):
    monkeypatch.setattr(base_menzo, "AI_ENABLED", False)
    monkeypatch.setenv("V93_MENZO_MAX_SELECTED_PER_RUN", "2")
    monkeypatch.setenv("V93_MENZO_MAX_PENDING_PER_RUN", "3")
    monkeypatch.setattr(base_menzo, "ARTIFACT_DECISIONS_FILE", tmp_path / "artifacts" / "menzo.json")
    monkeypatch.setattr(base_menzo, "MENZO_DECISIONS_FILE", tmp_path / "state" / "menzo.json")
    monkeypatch.setattr(base_menzo, "V92_ALLOWED_URLS_FILE", tmp_path / "state" / "urls.json")
    board = {"news_candidates_for_menzo": [base_candidate(f"https://base/{i}", f"CM Punk signs WWE contract {i}") for i in range(6)]}
    out = base_menzo.run_menzo(board)
    assert len(out["selected"]) == 2
    assert len(out["pending"]) == 3
    assert out["daily_policy"]["base_capacity_limits_applied"] is True


def test_base_menzo_unlimited_handoff_preserves_all_actionable(monkeypatch, tmp_path):
    monkeypatch.setattr(base_menzo, "AI_ENABLED", False)
    monkeypatch.setenv("V93_MENZO_MAX_SELECTED_PER_RUN", "2")
    monkeypatch.setenv("V93_MENZO_MAX_PENDING_PER_RUN", "3")
    monkeypatch.setattr(base_menzo, "ARTIFACT_DECISIONS_FILE", tmp_path / "artifacts" / "menzo.json")
    monkeypatch.setattr(base_menzo, "MENZO_DECISIONS_FILE", tmp_path / "state" / "menzo.json")
    monkeypatch.setattr(base_menzo, "V92_ALLOWED_URLS_FILE", tmp_path / "state" / "urls.json")
    selected = [base_candidate(f"https://base/sel{i}", f"CM Punk signs WWE contract {i}") for i in range(7)]
    pending = [base_candidate(f"https://base/pen{i}", f"Backstage plans for Raw {i}") for i in range(14)]
    skipped = [base_candidate("https://base/skip", "10 things we hated on Raw")]
    out = base_menzo.run_menzo({"news_candidates_for_menzo": selected + pending + skipped}, apply_capacity_limits=False)
    assert len(out["selected"]) == 7
    assert len(out["pending"]) == 14
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["url"] == "https://base/skip"
    assert out["daily_policy"]["base_capacity_limits_applied"] is False


def test_wrapper_passes_apply_capacity_limits_false(monkeypatch, tmp_path):
    isolate_wrapper_state(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(menzo, "_wp_ready_for_costly_work", lambda: (True, "ok"))
    def fake_base(board, *, apply_capacity_limits=True, persist_outputs=True):
        seen.append((apply_capacity_limits, persist_outputs))
        return {"selected": [], "pending": [], "skipped": [], "postprocess": {}, "policy": {}, "daily_policy": {}}
    monkeypatch.setattr(menzo.base, "run_menzo", fake_base)
    monkeypatch.setattr(menzo, "normalize_ai_fields", lambda r: None)
    monkeypatch.setattr(menzo, "rebuild_decisions", lambda r: None)
    for name in ["apply_betting_odds_policy", "apply_source_opinion_policy", "apply_medical_brand_policy", "apply_story_footprint_policy", "enforce_ai_skip_binding", "apply_generalized_fingerprint_policy", "apply_softpool_decay", "apply_same_story_duplicate_guard", "apply_recent_published_duplicate_guard", "apply_dynamic_editorial_budget", "enforce_selected_cap", "enforce_capacity_buffer", "enforce_final_menzo_duplicate_authorization"]:
        monkeypatch.setattr(menzo, name, lambda *a, **k: None)
    monkeypatch.setattr(menzo, "save_softpool", lambda r: None)
    monkeypatch.setattr(menzo, "save_hard_skips", lambda r: None)
    monkeypatch.setattr(menzo, "remember_stories", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_footprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_fingerprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "write_json", lambda *a, **k: None)
    menzo.run_menzo({})
    assert seen == [(False, False)]


def test_real_base_unlimited_pipeline_payload_exceeds_old_caps(monkeypatch, tmp_path):
    isolate_wrapper_state(monkeypatch, tmp_path)
    monkeypatch.setenv("V93_MENZO_MAX_SELECTED_PER_RUN", "6")
    monkeypatch.setenv("V93_MENZO_MAX_PENDING_PER_RUN", "12")
    monkeypatch.setattr(base_menzo, "ARTIFACT_DECISIONS_FILE", tmp_path / "base_artifacts" / "menzo.json")
    monkeypatch.setattr(base_menzo, "MENZO_DECISIONS_FILE", tmp_path / "base_state" / "menzo.json")
    monkeypatch.setattr(base_menzo, "V92_ALLOWED_URLS_FILE", tmp_path / "base_state" / "urls.json")
    monkeypatch.setattr(menzo, "_wp_ready_for_costly_work", lambda: (True, "ok"))
    monkeypatch.setattr(menzo, "ARTIFACT_DECISIONS_FILE", tmp_path / "wrapper_artifacts" / "menzo.json")
    monkeypatch.setattr(menzo, "MENZO_DECISIONS_FILE", tmp_path / "wrapper_state" / "menzo.json")
    monkeypatch.setattr(menzo, "V92_ALLOWED_URLS_FILE", tmp_path / "wrapper_state" / "urls.json")
    monkeypatch.setattr(menzo.base, "ARTIFACT_DECISIONS_FILE", tmp_path / "base_artifacts" / "menzo.json")
    monkeypatch.setattr(menzo.base, "MENZO_DECISIONS_FILE", tmp_path / "base_state" / "menzo.json")
    monkeypatch.setattr(menzo.base, "V92_ALLOWED_URLS_FILE", tmp_path / "base_state" / "urls.json")
    monkeypatch.setattr(menzo.base, "AI_ENABLED", False)
    sent = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda prompt, model, **k: sent.append(prompt) or ({"duplicate_groups": []}, "gemini-3.1-flash-lite"))
    monkeypatch.setattr(menzo, "save_softpool", lambda r: None)
    monkeypatch.setattr(menzo, "save_hard_skips", lambda r: None)
    monkeypatch.setattr(menzo, "remember_stories", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_footprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_fingerprints", lambda *a, **k: None)
    selected = [
        base_candidate("https://pipe/sel0", "CM Punk suffers a WWE knee injury"),
        base_candidate("https://pipe/sel1", "CM Punk knee injury reported by WWE doctors"),
        base_candidate("https://pipe/sel2", "Rhea Ripley discusses a charity project"),
        base_candidate("https://pipe/sel3", "Seth Rollins launches a fitness program"),
        base_candidate("https://pipe/sel4", "Becky Lynch appears at a community event"),
        base_candidate("https://pipe/sel5", "Cody Rhodes signs a new AEW contract"),
        base_candidate("https://pipe/sel6", "Cody Rhodes contract signing reported by AEW"),
    ]
    pending = [base_candidate(f"https://pipe/pen{i}", f"Community feature number {i}") for i in range(13)]
    board = {"news_candidates_for_menzo": selected + pending, "suspicious_story_clusters": [{"records": [{"url": "https://pipe/sel0"}]}] * 12}
    out = menzo.run_menzo(board)
    assert len(sent) == 2
    punk_prompt = next(prompt for prompt in sent if "https://pipe/sel0" in prompt)
    cody_prompt = next(prompt for prompt in sent if "https://pipe/sel5" in prompt)
    assert "https://pipe/sel1" in punk_prompt and "https://pipe/sel5" not in punk_prompt
    assert "https://pipe/sel6" in cody_prompt and "https://pipe/sel0" not in cody_prompt
    for candidate in selected[2:5] + pending:
        assert all(candidate["url"] not in prompt for prompt in sent)
    assert out["postprocess"]["same_run_suspicious_components"] == 2
    assert out["postprocess"].get("massy_suspicious_duplicate_pairs", 0) == 0
    assert out["daily_policy"]["base_capacity_limits_applied"] is False
    assert len(out["selected"]) <= menzo.MAX_SELECTED_THIS_RUN


def test_duplicate_arbitration_before_post_caps_then_caps_apply(monkeypatch, tmp_path):
    isolate_wrapper_state(monkeypatch, tmp_path)
    monkeypatch.setenv("V93_MENZO_MAX_SELECTED_PER_RUN", "6")
    monkeypatch.setattr(menzo, "MAX_SELECTED_THIS_RUN", 3)
    monkeypatch.setattr(menzo, "_wp_ready_for_costly_work", lambda: (True, "ok"))
    for obj in [base_menzo, menzo.base]:
        monkeypatch.setattr(obj, "ARTIFACT_DECISIONS_FILE", tmp_path / "base_artifacts" / "menzo.json")
        monkeypatch.setattr(obj, "MENZO_DECISIONS_FILE", tmp_path / "base_state" / "menzo.json")
        monkeypatch.setattr(obj, "V92_ALLOWED_URLS_FILE", tmp_path / "base_state" / "urls.json")
        monkeypatch.setattr(obj, "AI_ENABLED", False)
    monkeypatch.setattr(menzo, "ARTIFACT_DECISIONS_FILE", tmp_path / "wrapper_artifacts" / "menzo.json")
    monkeypatch.setattr(menzo, "MENZO_DECISIONS_FILE", tmp_path / "wrapper_state" / "menzo.json")
    monkeypatch.setattr(menzo, "V92_ALLOWED_URLS_FILE", tmp_path / "wrapper_state" / "urls.json")
    monkeypatch.setattr(menzo, "save_softpool", lambda r: None)
    monkeypatch.setattr(menzo, "save_hard_skips", lambda r: None)
    monkeypatch.setattr(menzo, "remember_stories", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_footprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_fingerprints", lambda *a, **k: None)
    sent = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda prompt, model, **k: sent.append(prompt) or ({"duplicate_groups": [{"keep_id": "c0", "discard_ids": ["c1"], "reason": "same"}]}, "gemini-3.1-flash-lite"))
    board = {"news_candidates_for_menzo": [base_candidate(f"https://cap/{i}", f"CM Punk signs WWE contract {i}") for i in range(7)]}
    out = menzo.run_menzo(board)
    assert "https://cap/6" in sent[0]
    assert any(x["reason"] == "skip:duplicate_same_run" for x in out["skipped"])
    assert len(out["selected"]) <= 3
    assert all(x["url"] not in out["allowed_urls_for_v92"] for x in out["skipped"] if x.get("reason")=="skip:duplicate_same_run")

def test_runtime_order_has_one_budget_after_duplicate_guards(monkeypatch, tmp_path):
    isolate_wrapper_state(monkeypatch, tmp_path)
    order = []
    base = {"selected": [], "pending": [], "skipped": [], "postprocess": {}, "policy": {}}
    monkeypatch.setattr(menzo, "_wp_ready_for_costly_work", lambda: (True, "ok"))
    monkeypatch.setattr(menzo.base, "run_menzo", lambda board, **kwargs: dict(base))
    monkeypatch.setattr(menzo, "normalize_ai_fields", lambda r: None)
    monkeypatch.setattr(menzo, "rebuild_decisions", lambda r: None)
    for name in ["apply_betting_odds_policy", "apply_source_opinion_policy", "apply_medical_brand_policy", "apply_story_footprint_policy", "enforce_ai_skip_binding", "apply_generalized_fingerprint_policy"]:
        monkeypatch.setattr(menzo, name, lambda r, _name=name: order.append(_name))
    for name in ["apply_softpool_decay", "apply_same_story_duplicate_guard", "apply_recent_published_duplicate_guard", "apply_dynamic_editorial_budget", "enforce_selected_cap", "enforce_capacity_buffer", "enforce_final_menzo_duplicate_authorization"]:
        monkeypatch.setattr(menzo, name, lambda *a, _name=name, **k: order.append(_name))
    monkeypatch.setattr(menzo, "save_softpool", lambda r: None)
    monkeypatch.setattr(menzo, "save_hard_skips", lambda r: None)
    monkeypatch.setattr(menzo, "remember_stories", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_footprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "remember_fingerprints", lambda *a, **k: None)
    monkeypatch.setattr(menzo, "write_json", lambda *a, **k: None)
    menzo.run_menzo({})
    required = ["apply_softpool_decay", "apply_same_story_duplicate_guard", "apply_recent_published_duplicate_guard", "apply_dynamic_editorial_budget", "enforce_selected_cap", "enforce_capacity_buffer", "enforce_final_menzo_duplicate_authorization"]
    assert [x for x in order if x in required] == required
    assert order.count("apply_dynamic_editorial_budget") == 1


def test_same_run_ab_duplicate_c_distinct_one_batch_and_massy_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE", tmp_path / "cache.json")
    calls=[]
    def fake(prompt, model, **k):
        calls.append((prompt, k.get("phase"), model))
        return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same story"}]}, model
    monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
    r=result([item("https://t/A","CM Punk suffers a WWE knee injury"), item("https://t/B","CM Punk knee injury reported by WWE doctors"), item("https://t/C","Cody Rhodes signs a new AEW contract")])
    menzo.apply_same_story_duplicate_guard(r, {"suspicious_story_clusters":[{"records":[{}]}]*12})
    assert [x["url"] for x in r["selected"]] == ["https://t/B", "https://t/C"]
    assert r["skipped"][0]["url"] == "https://t/A"
    assert "menzo_duplicate_checked" not in r["selected"][1]
    assert len(calls) == 1 and calls[0][1] == "duplicate_arbitration_same_run_batch"
    assert "https://t/A" in calls[0][0] and "https://t/B" in calls[0][0] and "https://t/C" not in calls[0][0]
    assert r["postprocess"]["same_run_suspicious_components"] == 1
    assert r["postprocess"].get("massy_suspicious_duplicate_pairs", 0) == 0


def test_no_same_run_duplicates_and_two_independent_groups(monkeypatch, tmp_path):
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE", tmp_path / "scenario_a.json")
    scenario_a_prompts=[]
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda prompt,*a, **k: scenario_a_prompts.append(prompt) or ({"duplicate_groups": []}, "gemini-3.1-flash-lite"))
    r=result([item("https://t/A","CM Punk suffers a WWE knee injury"), item("https://t/B","CM Punk knee injury reported by WWE doctors")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert len(r["selected"]) == 2 and all("menzo_duplicate_checked" not in x for x in r["selected"])
    assert len(scenario_a_prompts)==1
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE", tmp_path / "scenario_b.json")
    prompts=[]
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda prompt,*a, **k: prompts.append(prompt) or ({"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"same"}]}, "gemini-3.1-flash-lite"))
    r=result([item("https://t/A","CM Punk suffers a WWE knee injury"), item("https://t/B","CM Punk knee injury reported by WWE doctors"), item("https://t/C","Cody Rhodes signs a new AEW contract"), item("https://t/D","Cody Rhodes contract signing reported by AEW")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert [x["url"] for x in r["selected"]] == ["https://t/B", "https://t/D"]
    assert {x["url"] for x in r["skipped"]} == {"https://t/A", "https://t/C"}
    assert len(prompts)==2 and all(not ("CM Punk" in prompt and "Cody Rhodes" in prompt) for prompt in prompts)
    assert r["postprocess"]["same_run_suspicious_components"]==2


def test_malformed_batch_repair_and_legacy_shape_never_applied(monkeypatch, tmp_path):
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE", tmp_path / "cache.json")
    calls=[]
    def fake(*a, **k):
        calls.append(k.get("phase"))
        if len(calls) == 1:
            return {"decision":"DUPLICATE"}, "gemini-3.1-flash-lite"
        return {"duplicate_groups":[{"keep_id":"c0","discard_ids":["c1"],"reason":"fixed"}]}, "gemini-3.1-flash-lite"
    monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
    r=result([item("https://t/A","CM Punk suffers a WWE knee injury"), item("https://t/B","CM Punk knee injury reported by WWE doctors"), item("https://t/C","Cody Rhodes signs a new AEW contract")])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert [x["url"] for x in r["selected"]] == ["https://t/B", "https://t/C"]
    assert calls == ["duplicate_arbitration_same_run_batch", "duplicate_arbitration_same_run_repair"]
    assert r["postprocess"]["menzo_same_run_batch_calls"]==1
    assert r["postprocess"]["menzo_same_run_batch_repairs"]==1
    assert r["postprocess"]["menzo_same_run_micro_fallback_calls"]==0
    assert r["postprocess"]["gemini_duplicate_calls_executed"]==2


def test_same_run_micro_survivor_wins_current_wins_invalids_and_failure(monkeypatch, tmp_path):
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE", cache_path)
    # both batch attempts invalid; survivor wins over B; C replaces A; D compares only against C; E invalid fail-closes
    responses = [({"bad": True}, "gemini-3.1-flash-lite"), ({"bad": True}, "gemini-3.1-flash-lite"),
                 ({"decision":"DUPLICATE_OF", "matched_id":"c0", "keep_id":"c0", "reason":"A better"}, "gemini-3.1-flash-lite"),
                 ({"decision":"DUPLICATE_OF", "matched_id":"c0", "keep_id":"c2", "reason":"C better"}, "gemini-3.1-flash-lite"),
                 ({"decision":"NO_DUPLICATE"}, "gemini-3.1-flash-lite"),
                 ({"decision":"DUPLICATE_OF", "matched_id":"c0", "keep_id":"c0", "reason":"discarded survivor invalid"}, "gemini-3.1-flash-lite")]
    prompts=[]
    def fake(prompt, model, **k):
        prompts.append((k.get("phase"), prompt))
        return responses.pop(0)
    monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
    titles = ["CM Punk suffers a WWE knee injury", "CM Punk knee injury reported by WWE doctors", "New details on CM Punk WWE knee injury", "CM Punk WWE knee injury medical report", "CM Punk WWE knee injury surgery report"]
    r=result([item(f"https://t/{letter}", title) for letter, title in zip("ABCDE", titles)])
    menzo.apply_same_story_duplicate_guard(r, {})
    assert [phase for phase, _ in prompts] == ["duplicate_arbitration_same_run_batch", "duplicate_arbitration_same_run_repair"] + ["duplicate_arbitration_same_run_micro"] * 4
    assert r["postprocess"]["gemini_duplicate_calls_executed"] == 6
    assert [x["url"] for x in r["selected"]] == ["https://t/B", "https://t/C", "https://t/D"]
    assert {x["url"] for x in r["skipped"]} == {"https://t/A", "https://t/E"}
    assert r["postprocess"]["menzo_duplicate_arbitration_fail_closed"] == 1
    d_prompt = [p for phase,p in prompts if phase == "duplicate_arbitration_same_run_micro"][2]
    assert '"id": "c0"' not in d_prompt and '"id": "c2"' in d_prompt
    assert next(x for x in r["skipped"] if x["url"] == "https://t/E")["menzo_duplicate_decision"] == "ARBITRATION_FAILED"
    cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache_data["entries"] == {} and len(cache_data["failures"]) == 1


def test_same_run_micro_invalid_matched_keep_missing_and_unresolved_only_current(monkeypatch, tmp_path):
    for index, bad_response in enumerate([
        {"decision":"DUPLICATE_OF", "matched_id":"future", "keep_id":"future", "reason":"bad"},
        {"decision":"DUPLICATE_OF", "matched_id":"c0", "keep_id":"c9", "reason":"bad"},
        {"decision":"DUPLICATE_OF", "keep_id":"c0", "reason":"bad"},
        None,
    ]):
        monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_V2_FILE", tmp_path / f"cache-{index}.json")
        responses=[({"bad": True}, "gemini-3.1-flash-lite"), ({"bad": True}, "gemini-3.1-flash-lite"), (bad_response, "gemini-3.1-flash-lite")]
        phases=[]
        def fake(*a, **kwargs):
            phases.append(kwargs.get("phase"))
            return responses.pop(0)
        monkeypatch.setattr(menzo, "call_gemini_json_model", fake)
        r=result([item("https://t/A","CM Punk suffers a WWE knee injury"), item("https://t/B","CM Punk knee injury reported by WWE doctors")])
        menzo.apply_same_story_duplicate_guard(r, {})
        assert [x["url"] for x in r["selected"]] == ["https://t/A"]
        assert r["skipped"][0]["url"] == "https://t/B"
        assert r["skipped"][0]["reason"] == "skip:duplicate_arbitration_unresolved"
        assert r["skipped"][0]["menzo_duplicate_decision"] == "ARBITRATION_FAILED"
        assert phases == ["duplicate_arbitration_same_run_batch", "duplicate_arbitration_same_run_repair", "duplicate_arbitration_same_run_micro"]
        assert r["postprocess"]["gemini_duplicate_calls_executed"] == 3
        cache_data=json.loads((tmp_path / f"cache-{index}.json").read_text(encoding="utf-8"))
        assert cache_data["entries"] == {} and len(cache_data["failures"]) == 1






def test_grounded_material_update_validation(monkeypatch):
    old = {"id":"p0", "title":"Old", "full_body":"CM Punk match was rumored."}
    current = {"id":"c0", "title":"Official", "full_body":"WWE officially announced CM Punk match."}
    assert not menzo.material_update_is_grounded("several additional details", current, old)
    assert not menzo.material_update_is_grounded("WWE officially changed the match opponent.", current, old)
    assert not menzo.material_update_is_grounded("CM Punk match was rumored.", current, old)
    assert menzo.material_update_is_grounded("WWE officially announced CM Punk match.", current, old)




def test_final_allowed_urls_only_valid_selected(monkeypatch):
    good = item("https://t/good", "Good")
    ordinary = item("https://t/ordinary", "Ordinary")
    bad = item("https://t/bad", "Bad")
    menzo.mark_menzo_duplicate(good, checked=True, scope="same_run", decision="DUPLICATE", authorized=True, winner=good)
    bad.update({"menzo_duplicate_checked": True, "menzo_duplicate_scope": "same_run", "menzo_duplicate_decision": "DUPLICATE", "menzo_authorized": True, "menzo_winner_url": "https://t/other"})
    r=result([good, ordinary, bad])
    menzo.enforce_final_menzo_duplicate_authorization(r)
    assert r["allowed_urls_for_v92"] == ["https://t/good", "https://t/ordinary"]
    assert r["skipped"][0]["url"] == "https://t/bad"


def test_metadata_propagation_actual_andrea_bob_alfred_publisher(monkeypatch, tmp_path):
    src = item("https://t/win", "Winner", "Questo articolo contiene informazioni editoriali complete e verificate sulla notizia principale. " * 8)
    menzo.mark_menzo_duplicate(src, checked=True, scope="same_run", decision="DUPLICATE", authorized=True, winner=src, reason="same")
    menzo_out = {"version":"test", "selected":[src], "pending":[], "skipped":[], "handoff":{}}
    andrea_out = andrea.run_andrea(menzo_out)
    assert andrea_out["selected"][0]["menzo_duplicate_scope"] == "same_run"
    monkeypatch.setattr(bob, "fetch_html", lambda url: "<html><head><title>Winner</title></head><body><article><p>" + ("Questo articolo contiene informazioni editoriali complete e verificate sulla notizia principale. " * 8) + "</p></article></body></html>")
    monkeypatch.setattr(bob, "call_gemini", lambda *a, **k: (json.dumps({"title_it":"Titolo italiano valido completo", "excerpt_it":"Estratto completo", "translations":{"b1":"Questo articolo contiene informazioni editoriali complete e verificate sulla notizia principale. " * 8}, "notes":[]}), "gemini-test", ["gemini-test"]))
    package = bob.article_package(andrea_out["selected"][0])
    assert package["menzo_duplicate_decision"] == "DUPLICATE"
    review = alfred.review_article(package)
    assert review["approved_article"]["menzo_duplicate_scope"] == "same_run"
    wrapped = alfred_policy_v93_20._approved_article_from_source({"title_it":"Titolo italiano valido completo"}, package)
    assert wrapped["menzo_winner_url"] == "https://t/win"
    calls=[]
    monkeypatch.setattr(publisher, "DRY_RUN", True)
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "test"))
    monkeypatch.setattr(publisher, "publish_article", lambda article, history, wp_ok: calls.append(article) or {"status":"dry_run", "source_url": article.get("source_url")})
    monkeypatch.setattr(publisher, "PUBLISHER_HISTORY_FILE", tmp_path / "publisher_history.json")
    monkeypatch.setattr(publisher, "ARTIFACT_PUBLISHER_FILE", tmp_path / "publisher_result.json")
    monkeypatch.setattr(publisher, "PUBLISHER_STATUS_FILE", tmp_path / "publisher_status.json")
    malformed = {"title_it":"Bad", "source_url":"https://t/bad", "menzo_duplicate_checked": True, "menzo_duplicate_scope":"same_run", "menzo_duplicate_decision":"DUPLICATE", "menzo_authorized": True, "menzo_winner_url":"https://t/other"}
    out = publisher.run_publisher({"approved_articles":[wrapped, malformed]})
    assert [x["source_url"] for x in calls] == ["https://t/win"]
    assert any(x.get("source_url") == "https://t/bad" and x.get("reason") == "skip:duplicate_arbitration_unresolved" for x in out["results"])




def test_generalized_fingerprint_enrichment_does_not_skip_memory_match_before_gemini(monkeypatch):
    current = item("https://new/fp", "WWE officially announced CM Punk match", "WWE officially announced CM Punk match.")
    r = result([current])
    monkeypatch.setattr(menzo, "load_story_fingerprints", lambda: [{"fingerprint": menzo.build_generalized_fingerprint(current), "url": "https://old/fp", "title": "Old"}])
    menzo.apply_generalized_fingerprint_policy(r)
    assert r["selected"] == [current]
    assert r["skipped"] == []
    assert r["postprocess"]["story_fingerprint_duplicates_skipped"] == 0
    assert "duplicate_of" not in current and current.get("reason") != "skip:story_fingerprint_overlap"







def test_menzo_model_chain_shared_operation_id_and_invalid_json_usage(monkeypatch, tmp_path):
    from agents import gemini_ledger
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL_CHAIN", "m1,m2")
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", tmp_path / "state" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", tmp_path / "artifacts" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", tmp_path / "state" / "newsroom" / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", tmp_path / "artifacts" / "newsroom" / "gemini_call_ledger_latest.json")

    class Resp:
        text = '{"duplicate_groups": []}'
        usage_metadata = type("Meta", (), {"prompt_token_count": 5, "candidates_token_count": 6, "total_token_count": 11})()

    class Models:
        def generate_content(self, *, model, contents):
            if model == "m1":
                raise RuntimeError("boom")
            return Resp()

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    import google.genai as real_genai
    monkeypatch.setattr(real_genai, "Client", Client)
    data, status = menzo.call_gemini_json("prompt")
    assert data == {"duplicate_groups": []}
    rows = [json.loads(line) for line in gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["operation_id"] == rows[1]["operation_id"]
    assert [r["attempt_index"] for r in rows] == [0, 1]
    assert [r["fallback"] for r in rows] == [False, True]
    assert rows[1]["usage_available"] is True


def test_menzo_invalid_json_preserves_usage_single_row(monkeypatch, tmp_path):
    from agents import gemini_ledger
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", tmp_path / "state" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", tmp_path / "artifacts" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", tmp_path / "state" / "newsroom" / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", tmp_path / "artifacts" / "newsroom" / "gemini_call_ledger_latest.json")

    class Resp:
        text = 'not json'
        usage_metadata = type("Meta", (), {"prompt_token_count": 1, "candidates_token_count": 1, "total_token_count": 2})()

    class Models:
        def generate_content(self, *, model, contents):
            return Resp()

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    import google.genai as real_genai
    monkeypatch.setattr(real_genai, "Client", Client)
    data, status = menzo.call_gemini_json_model("prompt", "m1", operation_id="op", attempt_index=0)
    assert data is None
    rows = [json.loads(line) for line in gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["status"] == "called" and rows[0]["result"] == "invalid_json"
    assert rows[0]["usage_available"] is True

def test_menzo_cooldown_skip_does_not_consume_attempt_index(monkeypatch, tmp_path):
    from agents import gemini_ledger
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL_CHAIN", "m1,m2")
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", tmp_path / "state" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", tmp_path / "artifacts" / "newsroom")
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", tmp_path / "state" / "newsroom" / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", tmp_path / "artifacts" / "newsroom" / "gemini_call_ledger_latest.json")
    menzo.MENZO_MODEL_COOLDOWN_FAILURES.clear()
    menzo.MENZO_MODEL_COOLDOWN_FAILURES.add(("m1", "unknown"))

    class Resp:
        text = '{"duplicate_groups": []}'
        usage_metadata = type("Meta", (), {"prompt_token_count": 2, "candidates_token_count": 3, "total_token_count": 5})()

    class Models:
        def generate_content(self, *, model, contents):
            return Resp()

    class Client:
        def __init__(self, api_key):
            self.models = Models()

    import google.genai as real_genai
    monkeypatch.setattr(real_genai, "Client", Client)
    data, status = menzo.call_gemini_json("prompt")
    assert data == {"duplicate_groups": []}
    rows = [json.loads(line) for line in gemini_ledger.LEDGER_FILE.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["status"] == "avoided"
    assert rows[1]["status"] == "called"
    assert rows[1]["attempt_index"] == 0
    assert rows[1]["fallback"] is False
