import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import menzo_policy_v93_15 as menzo


def lyra_item(url: str, source: str, score: int, label: str, *, decision: str = "pending", article_type: str = "duplicate") -> dict:
    return {
        "url": url,
        "source_url": url,
        "source": source,
        "title": "Lyra Valkyria turns on Bayley after WWE Raw tag title match",
        "summary": "Lyra Valkyria turned heel on Bayley after the WWE Raw tag title match.",
        "score": score,
        "ai_priority_label": label,
        "priority": "hard" if score >= 75 else "soft",
        "decision": decision,
        "article_type": article_type,
    }


def board_for(*records, published: bool = False) -> dict:
    rows = [{"origin": "candidate", "source_url": r["url"], "title": r["title"], "summary": r["summary"], "source": r["source"], "score": r["score"]} for r in records]
    if published:
        rows.append({"origin": "published_or_memory", "source_url": "https://old.test/lyra", "title": "Published Lyra story", "summary": "Lyra turned on Bayley."})
    return {"suspicious_story_clusters": [{"records": rows}]}


def test_legacy_duplicate_cluster_survivor_path_no_longer_selects_or_skips(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy path should not call Gemini")))
    ringside = lyra_item("https://www.ringsidenews.com/lyra", "RingsideNews", 62, "medium")
    wrestlinginc = lyra_item("https://www.wrestlinginc.com/lyra", "WrestlingInc", 76, "high")
    result = {"selected": [], "pending": [ringside, wrestlinginc], "skipped": [], "postprocess": {}, "daily_policy": {"dynamic_soft_threshold": 65}}
    menzo.apply_ai_duplicate_arbitration(result, board_for(ringside, wrestlinginc))
    assert result["selected"] == []
    assert result["pending"] == [ringside, wrestlinginc]
    assert result["skipped"] == []
    assert result["postprocess"]["legacy_ai_duplicate_arbitration_disabled"] is True


def test_legacy_duplicate_cluster_with_published_memory_does_not_skip_before_batch(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy path should not call Gemini")))
    a = lyra_item("https://example.test/a", "RingsideNews", 80, "high")
    b = lyra_item("https://example.test/b", "WrestlingInc", 82, "high")
    result = {"selected": [], "pending": [a, b], "skipped": [], "postprocess": {}, "daily_policy": {"dynamic_soft_threshold": 65}}
    menzo.apply_ai_duplicate_arbitration(result, board_for(a, b, published=True))
    assert result["pending"] == [a, b]
    assert result["skipped"] == []


def test_legacy_duplicate_cluster_with_selected_survivor_keeps_pending_for_gemini(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda *a, **k: (_ for _ in ()).throw(AssertionError("legacy path should not call Gemini")))
    selected = lyra_item("https://example.test/selected", "Fightful", 70, "medium", decision="selected", article_type="hard_news")
    pending = lyra_item("https://example.test/pending", "RingsideNews", 90, "high", decision="pending")
    result = {"selected": [selected], "pending": [pending], "skipped": [], "postprocess": {}, "daily_policy": {"dynamic_soft_threshold": 65}}
    menzo.apply_ai_duplicate_arbitration(result, board_for(selected, pending))
    assert result["selected"] == [selected]
    assert result["pending"] == [pending]
    assert result["skipped"] == []
