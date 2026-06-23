from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents.menzo_policy_v93_15 as menzo


def lyra_item(url: str, source: str, score: int, label: str, *, decision: str = "pending", article_type: str = "duplicate") -> dict:
    return {
        "url": url,
        "source": source,
        "title": "WWE Raw Lyra Valkyria turns heel on Bayley after Women's Tag Team Title match",
        "summary": "Lyra Valkyria turned heel on Bayley after the Women's Tag Team Title loss on WWE Raw.",
        "score": score,
        "ai_priority_label": label,
        "article_type": article_type,
        "priority": "hard" if label == "high" else "soft",
        "decision": decision,
    }


def board_for(*items: dict, published: bool = False) -> dict:
    records = [
        {"origin": "candidate", "url": item["url"], "source_url": item["url"], "title": item["title"], "summary": item["summary"], "source": item["source"]}
        for item in items
    ]
    if published:
        records.append({
            "origin": "published_or_memory",
            "url": "https://example.test/published-lyra",
            "source_url": "https://example.test/published-lyra",
            "title": "Lyra Valkyria turns heel after WWE Raw title loss",
            "summary": "Already published coverage of Lyra Valkyria turning heel on Bayley.",
            "source": "Published",
        })
    return {"suspicious_story_clusters": [{"records": records}]}


def test_lyra_cluster_selects_wrestlinginc_and_skips_ringside(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda prompt, model: (_ for _ in ()).throw(AssertionError("Gemini should not be needed")))
    ringside = lyra_item(
        "https://www.ringsidenews.com/lyra-valkyria-turns-heel-bayley-womens-tag-title-loss-wwe-raw/",
        "RingsideNews",
        62,
        "medium",
    )
    wrestlinginc = lyra_item(
        "https://www.wrestlinginc.com/2199229/wwe-raw-lyra-valkyria-turns-heel-bayley-womens-tag-title-match/",
        "WrestlingInc",
        76,
        "high",
    )

    result = {"selected": [], "pending": [ringside, wrestlinginc], "skipped": [], "postprocess": {}, "daily_policy": {"dynamic_soft_threshold": 65}}
    menzo.apply_ai_duplicate_arbitration(result, board_for(ringside, wrestlinginc))

    assert [x["url"] for x in result["selected"]] == [wrestlinginc["url"]]
    assert result["selected"][0]["article_type"] == "post_show_major_angle"
    assert result["skipped"][0]["url"] == ringside["url"]
    assert result["skipped"][0]["reason"] == "skip:ai_cross_source_duplicate_arbitration_loser"
    log = result["postprocess"]["ai_cross_source_duplicate_arbitration_logs"][0]
    assert log["duplicate_cluster_survivor_selected"] is True
    assert log["duplicate_cluster_survivor_url"] == wrestlinginc["url"]
    assert log["duplicate_cluster_loser_count"] == 1
    assert log["duplicate_cluster_existing_published"] is False


def test_duplicate_cluster_with_existing_published_skips_all_candidates(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda prompt, model: (_ for _ in ()).throw(AssertionError("Gemini should not be needed")))
    a = lyra_item("https://example.test/a", "RingsideNews", 80, "high")
    b = lyra_item("https://example.test/b", "WrestlingInc", 82, "high")
    result = {"selected": [], "pending": [a, b], "skipped": [], "postprocess": {}, "daily_policy": {"dynamic_soft_threshold": 65}}

    menzo.apply_ai_duplicate_arbitration(result, board_for(a, b, published=True))

    assert result["selected"] == []
    assert result["pending"] == []
    assert {x["url"] for x in result["skipped"]} == {a["url"], b["url"]}
    assert all(x["reason"] == "skip:ai_cross_source_duplicate_arbitration_loser" for x in result["skipped"])
    log = result["postprocess"]["ai_cross_source_duplicate_arbitration_logs"][0]
    assert log["duplicate_cluster_survivor_selected"] is False
    assert log["duplicate_cluster_existing_published"] is True


def test_duplicate_cluster_with_selected_survivor_does_not_duplicate(monkeypatch):
    monkeypatch.setattr(menzo, "call_gemini_json_model", lambda prompt, model: (_ for _ in ()).throw(AssertionError("Gemini should not be needed")))
    selected = lyra_item("https://example.test/selected", "Fightful", 70, "medium", decision="selected", article_type="hard_news")
    pending = lyra_item("https://example.test/pending", "RingsideNews", 90, "high", decision="pending")
    result = {"selected": [selected], "pending": [pending], "skipped": [], "postprocess": {}, "daily_policy": {"dynamic_soft_threshold": 65}}

    menzo.apply_ai_duplicate_arbitration(result, board_for(selected, pending))

    assert [x["url"] for x in result["selected"]] == [selected["url"]]
    assert result["pending"] == []
    assert [x["url"] for x in result["skipped"]] == [pending["url"]]
