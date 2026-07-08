import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import gemini_ledger
from agents import menzo_policy_v93_15 as menzo


def patch_paths(tmp_path, monkeypatch):
    ns = tmp_path / "state" / "newsroom"
    art = tmp_path / "artifacts" / "newsroom"
    monkeypatch.setattr(menzo, "NEWSROOM_STATE_DIR", ns)
    monkeypatch.setattr(menzo, "MENZO_DUPLICATE_ARBITRATION_CACHE_FILE", ns / "menzo_duplicate_arbitration_cache.json")
    monkeypatch.setattr(gemini_ledger, "STATE_DIR", ns)
    monkeypatch.setattr(gemini_ledger, "ARTIFACT_DIR", art)
    monkeypatch.setattr(gemini_ledger, "LEDGER_FILE", ns / "gemini_call_ledger.jsonl")
    monkeypatch.setattr(gemini_ledger, "LATEST_FILE", art / "gemini_call_ledger_latest.json")
    monkeypatch.setattr(menzo, "record_gemini_event", gemini_ledger.record_gemini_event)
    monkeypatch.setenv("NEWSROOM_RUN_ID", "cache-test")


def item(url="https://example.test/sami", title="Sami Zayn Has Profanity-Laden Reaction To Undisputed WWE Title Loss To CM Punk On Raw", score=80, article_type="hard_news"):
    return {"title": title, "url": url, "source": "Example", "score": score, "priority": "hard", "article_type": article_type, "decision": "pending", "summary": "Sami Zayn reacted after losing to CM Punk on Raw."}


def board(*urls):
    records = [{"origin": "candidate", "title": "Sami Zayn reaction", "source_url": "https://example.test/sami", "summary": "Sami Zayn reacted after CM Punk loss.", "score": 80}]
    for n, url in enumerate(urls):
        records.append({"origin": "published_or_memory", "title": f"CM Punk defeats Sami Zayn {n}", "source_url": url, "summary": "CM Punk defeated Sami Zayn on Raw.", "score": 78})
    return {"suspicious_story_clusters": [{"records": records}]}


def run_once(candidate):
    result = {"selected": [], "pending": [candidate], "skipped": [], "daily_policy": {"dynamic_soft_threshold": 70}}
    menzo.apply_ai_duplicate_arbitration(result, board("https://example.test/punk"))
    return result


def ai_pending(*args, **kwargs):
    return ({"cluster_type": "same_core_fact_new_angle", "decision": "pending_followup", "confidence": 90, "reason": "same pending follow-up"}, "gemini-3.5-flash")


def test_same_candidate_cluster_within_ttl_calls_gemini_once(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (calls.append(k.get("phase", "duplicate_arbitration")) or ai_pending(*a, **k)))
    run_once(item())
    second = run_once(item())
    assert len(calls) == 1
    assert second["postprocess"]["duplicate_arbitration_cache_hit"] == 1
    assert second["postprocess"]["gemini_calls_avoided_by_duplicate_arbitration_cache"] == 1
    assert second["postprocess"]["gemini_calls_used_for_duplicate_arbitration"] == 0
    assert second["postprocess"]["ai_duplicate_arbitration_calls"] == 0


def test_sami_zayn_pending_followup_uses_cache_on_second_run(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (calls.append(1) or ai_pending(*a, **k)))
    run_once(item())
    result = run_once(item())
    assert len(calls) == 1
    assert result["pending"][0]["article_type"] == "pending_followup"
    assert result["pending"][0]["ai_cross_source_duplicate_arbitration"]["cache_hit"] is True


def test_reversed_compared_url_order_hits_same_cache_key(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (calls.append(1) or ai_pending(*a, **k)))
    r1 = {"selected": [], "pending": [item()], "skipped": [], "daily_policy": {"dynamic_soft_threshold": 70}}
    r2 = {"selected": [], "pending": [item()], "skipped": [], "daily_policy": {"dynamic_soft_threshold": 70}}
    menzo.apply_ai_duplicate_arbitration(r1, board("https://example.test/a", "https://example.test/b"))
    menzo.apply_ai_duplicate_arbitration(r2, board("https://example.test/b", "https://example.test/a"))
    assert len(calls) == 1
    assert r2["postprocess"]["duplicate_arbitration_cache_hit"] == 1


def test_expired_cache_triggers_new_gemini_arbitration(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (calls.append(1) or ai_pending(*a, **k)))
    run_once(item())
    cache = json.loads(menzo.MENZO_DUPLICATE_ARBITRATION_CACHE_FILE.read_text())
    for entry in cache.values():
        entry["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    menzo.MENZO_DUPLICATE_ARBITRATION_CACHE_FILE.write_text(json.dumps(cache))
    result = run_once(item())
    assert len(calls) == 2
    assert result["postprocess"]["duplicate_arbitration_cache_expired"] == 1


def test_new_url_or_material_title_or_score_crossing_invalidates_cache(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (calls.append(1) or ai_pending(*a, **k)))
    run_once(item(score=60, article_type="soft_news"))
    r_new_url = {"selected": [], "pending": [item(score=60, article_type="soft_news")], "skipped": [], "daily_policy": {"dynamic_soft_threshold": 70}}
    menzo.apply_ai_duplicate_arbitration(r_new_url, board("https://example.test/punk", "https://example.test/new"))
    run_once(item(title="Sami Zayn Responds To Different Raw Situation", score=60, article_type="soft_news"))
    run_once(item(score=80, article_type="soft_news"))
    # Crossing the threshold in either direction is material enough to re-arbitrate.
    run_once(item(score=60, article_type="soft_news"))
    assert len(calls) == 5


def test_cache_read_write_failure_non_fatal(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(menzo, "load_duplicate_arbitration_cache", lambda: (_ for _ in ()).throw(OSError("boom")))
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (calls.append(1) or ai_pending(*a, **k)))
    result = run_once(item())
    assert calls == [1]
    assert result["pending"]


def test_ledger_records_cache_hit_as_avoided_not_called_and_summary_metric(tmp_path, monkeypatch):
    patch_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(menzo, "call_gemini_json_model", ai_pending)
    run_once(item())
    run_once(item())
    records = [json.loads(line) for line in gemini_ledger.LEDGER_FILE.read_text().splitlines()]
    cache_hits = [r for r in records if r.get("reason") == "duplicate_arbitration_cache_hit"]
    assert cache_hits and cache_hits[0]["status"] == "avoided"
    assert cache_hits[0]["saved_gemini_call"] is True
    assert gemini_ledger.summarize(records)["gemini_calls_avoided_by_duplicate_arbitration_cache"] == 1
