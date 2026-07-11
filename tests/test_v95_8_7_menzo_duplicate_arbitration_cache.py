import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import menzo_policy_v93_15 as menzo


def item(url="https://example.test/sami"):
    return {"title": "Sami Zayn update", "url": url, "source_url": url, "source": "Example", "score": 80, "priority": "hard", "article_type": "hard_news", "decision": "pending", "summary": "Sami Zayn update."}


def board(*urls):
    records = [{"origin": "candidate", "source_url": "https://example.test/sami", "title": "Sami Zayn update"}]
    records += [{"origin": "published_or_memory", "source_url": url, "title": "Old story"} for url in urls]
    return {"suspicious_story_clusters": [{"records": records}]}


def test_legacy_duplicate_arbitration_cache_path_is_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: calls.append(1) or ({"decision": "MATERIAL_UPDATE"}, "gemini-3.5-flash"))
    candidate = item()
    result = {"selected": [], "pending": [candidate], "skipped": [], "postprocess": {}, "daily_policy": {"dynamic_soft_threshold": 70}}
    menzo.apply_ai_duplicate_arbitration(result, board("https://example.test/old"))
    assert calls == []
    assert result["pending"] == [candidate]
    assert result["skipped"] == []
    assert result["postprocess"]["legacy_ai_duplicate_arbitration_disabled"] is True
    assert result["postprocess"]["gemini_calls_used_for_duplicate_arbitration"] == 0
    assert result["postprocess"]["duplicate_arbitration_cache_hit"] == 0


def test_legacy_duplicate_arbitration_does_not_depend_on_cluster_order(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy path should not call Gemini")))
    r1 = {"selected": [], "pending": [item("https://example.test/a")], "skipped": [], "postprocess": {}}
    r2 = {"selected": [], "pending": [item("https://example.test/a")], "skipped": [], "postprocess": {}}
    menzo.apply_ai_duplicate_arbitration(r1, board("https://example.test/a", "https://example.test/b"))
    menzo.apply_ai_duplicate_arbitration(r2, board("https://example.test/b", "https://example.test/a"))
    assert r1["pending"][0]["url"] == r2["pending"][0]["url"]
    assert r1["postprocess"]["gemini_calls_used_for_duplicate_arbitration"] == 0
    assert r2["postprocess"]["gemini_calls_used_for_duplicate_arbitration"] == 0
