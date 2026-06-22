from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents.menzo_policy_v93_15 as menzo


def item(score=65, article_type="soft_news", priority="soft", title="Soft useful wrestling update"):
    return {
        "url": f"https://example.test/{score}/{article_type}/{title.replace(' ', '-')}",
        "title": title,
        "summary": title,
        "score": score,
        "ai_priority_label": "medium" if score < 75 else "high",
        "article_type": article_type,
        "priority": priority,
        "decision": "selected",
    }


def run_budget(candidate, published_count):
    result = {"selected": [candidate], "pending": [], "skipped": [], "postprocess": {}}
    menzo.apply_dynamic_editorial_budget(result, published_count=published_count)
    return result


def test_target_30_published_zero_minimum_soft_score_passes(monkeypatch):
    monkeypatch.setattr(menzo, "DAILY_NEWS_TARGET", 30)
    result = run_budget(item(score=65), 0)
    assert len(result["selected"]) == 1
    assert result["daily_policy"]["dynamic_soft_threshold"] == 65
    assert result["daily_policy"]["published_today_percent"] == 0


def test_published_12_of_30_soft_threshold_tuned_to_1_1x(monkeypatch):
    monkeypatch.setattr(menzo, "DAILY_NEWS_TARGET", 30)
    result = run_budget(item(score=71, article_type="soft_news", priority="soft"), 12)
    assert len(result["selected"]) == 0
    blocked = (result["pending"] or result["skipped"])[0]
    assert blocked["reason"].startswith("skipped_by_dynamic_threshold")
    assert result["daily_policy"]["dynamic_soft_threshold"] == 72


def test_published_21_of_30_soft_threshold_tuned_to_1_2x(monkeypatch):
    monkeypatch.setattr(menzo, "DAILY_NEWS_TARGET", 30)
    result = run_budget(item(score=77, article_type="soft_news", priority="soft"), 21)
    assert len(result["selected"]) == 0
    blocked = (result["pending"] or result["skipped"])[0]
    assert blocked["reason"].startswith("skipped_by_dynamic_threshold")
    assert result["daily_policy"]["dynamic_soft_threshold"] == 78


def test_published_28_of_30_soft_threshold_tuned_to_1_25x(monkeypatch):
    monkeypatch.setattr(menzo, "DAILY_NEWS_TARGET", 30)
    result = run_budget(item(score=80, article_type="soft_news", priority="soft"), 28)
    assert len(result["selected"]) == 0
    blocked = (result["pending"] or result["skipped"])[0]
    assert blocked["reason"].startswith("skipped_by_dynamic_threshold")
    assert result["daily_policy"]["dynamic_soft_threshold"] == 81


def test_over_target_only_major_hard_high_score_passes(monkeypatch):
    monkeypatch.setattr(menzo, "DAILY_NEWS_TARGET", 30)
    soft_result = run_budget(item(score=99, article_type="soft_news", priority="soft"), 31)
    hard_result = run_budget(item(score=88, article_type="hard_news", priority="hard", title="Breaking major title change creates new champion"), 31)
    assert len(soft_result["selected"]) == 0
    assert len(hard_result["selected"]) == 1


def test_softpool_item_older_than_six_hours_hard_skip(monkeypatch):
    monkeypatch.setattr(menzo, "SOFTNEWS_TTL_HOURS", 6)
    old = item(score=70)
    old.update({"from_softpool": True, "softpool_added_at": (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()})
    result = {"selected": [old], "pending": [], "skipped": [], "postprocess": {}}
    menzo.apply_softpool_decay(result)
    assert len(result["selected"]) == 0
    assert result["skipped"][0]["reason"] == "softpool_expired_not_fresh"
    assert result["postprocess"]["softpool_expired_not_fresh"] == 1


def test_softpool_item_deferred_four_times_hard_skip(monkeypatch):
    monkeypatch.setattr(menzo, "SOFTPOOL_MAX_DEFERRALS", 4)
    deferred = item(score=70)
    deferred.update({"from_softpool": True, "softpool_added_at": datetime.now(timezone.utc).isoformat(), "softpool_deferrals": 4})
    result = {"selected": [], "pending": [deferred], "skipped": [], "postprocess": {}}
    menzo.apply_softpool_decay(result)
    assert len(result["pending"]) == 0
    assert result["skipped"][0]["reason"] == "softpool_repeatedly_outranked"
    assert result["postprocess"]["softpool_repeatedly_outranked"] == 1


def test_ambiguous_duplicate_cluster_still_uses_gemini_arbitration(monkeypatch):
    calls = []

    def fake_call(prompt, model):
        calls.append((prompt, model))
        return {"cluster_type": "different_story", "decision": "selected", "confidence": 90, "reason": "new angle"}, model

    monkeypatch.setattr(menzo, "call_gemini_json_model", fake_call)
    candidate = item(score=82, article_type="hard_news", priority="hard", title="WWE Raw same show report has new injury angle")
    board = {"suspicious_story_clusters": [{"records": [
        {"origin": "candidate", "url": candidate["url"], "title": candidate["title"], "summary": candidate["summary"], "source": "A"},
        {"origin": "published_or_memory", "url": "https://example.test/old", "title": "WWE Raw same show report", "summary": "same show window", "source": "B"},
    ]}]}
    result = {"selected": [candidate], "pending": [], "skipped": [], "postprocess": {}}
    menzo.apply_ai_duplicate_arbitration(result, board)
    assert calls
    assert result["postprocess"]["gemini_calls_used_for_duplicate_arbitration"] == 1
