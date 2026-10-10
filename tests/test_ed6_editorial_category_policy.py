"""Category migration and prefilter behavior; mocked outputs do not test model semantics."""
import copy
import json

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_priority_queue as queue
from agents import menzo_soft_board as soft


OLD_POLICY = "owtv_editorial_director_policy_v5_active"
NOW = "2026-10-10T12:00:00+00:00"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                 "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / (name + ".json"))
    history = tmp_path / "history.json"
    history.write_text("{}")
    monkeypatch.setattr(menzo, "publisher_history_file", lambda: history)
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    monkeypatch.setattr(soft, "record_gemini_attempt", lambda **_: None)
    monkeypatch.setattr(active.source_body, "hydrate", lambda _: (False, "offline"))
    monkeypatch.setattr("agents.bob.dynamic_article_capacity", lambda *_: (5, "test"))


def candidate(url, cls="PUBLISHABLE_SOFT", policy=None):
    return {"url": url, "title": "A detailed wrestling production explanation", "summary": "Professional facts",
            "soft_board_day": "2026-10-10", "soft_board_first_seen_at": "2026-10-10T08:00:00Z",
            "soft_board_review_count": 1,
            "decision_authority": "editorial_director", "editorial_director": {
                "policy_version": policy or active.POLICY_VERSION, "editorial_class": cls,
                "recommended_action": "DEFER" if cls == "PUBLISHABLE_SOFT" else "SELECT",
                "category": "WWE", "story_core": "A substantive first-hand explanation of wrestling production."}}


def empty():
    return {"selected": [], "pending": [], "skipped": [], "postprocess": {}}


def classification(classes):
    return {"candidates": [{"ref": f"c{i}", "editorial_class": cls,
             "recommended_action": {"SKIP": "SKIP", "PUBLISHABLE_SOFT": "DEFER"}.get(cls, "SELECT"),
             "category": "WWE", "story_core": "Central fact and its editorial value"}
            for i, cls in enumerate(classes)], "relations": [],
            "admission_complete": True, "suspected_duplicates": []}


def test_mixed_categories_remove_weak_soft_before_relation_work(monkeypatch):
    rows = [candidate(f"https://ed6.test/{i}") for i in range(4)]
    for row, title in zip(rows, (
        "WWE announces a major media-rights agreement",
        "NXT confirms the date and venue for its next special",
        "Veteran explains how HD changed match production",
        "Wrestler jokes about his dating difficulties",
    )):
        row["title"] = title
    snapshot = shadow.capture_opportunity({"news_candidates_for_menzo": rows}, run_id="ed6",
        observation_timestamp="2026-10-10T08:00:00Z", history=[], defer_relation_build=True)
    observed = []
    original_gate = active._evaluate_duplicate_stage
    def gate(snapshot, **kwargs):
        observed.extend(row['url'] for row in snapshot['candidates'])
        return original_gate(snapshot, **kwargs)
    monkeypatch.setattr(active, '_evaluate_duplicate_stage', gate)
    monkeypatch.setattr(shadow, 'build_authorized_relations', lambda *_args, **_kwargs:
                        pytest.fail('lexical overlap cannot admit Active pairs'))
    prompts = []
    def provider(prompt, *_):
        prompts.append(prompt)
        payload = json.loads(prompt.split("INPUT=", 1)[1])
        assert payload["history"] == payload["authorized_relations"] == []
        assert "publication_context" not in payload
        return classification(["MUST_PUBLISH", "SHOULD_PUBLISH", "PUBLISHABLE_SOFT", "SKIP"])
    result = active.evaluate(snapshot, provider=provider)
    assert result["status"] == "VALIDATED"
    assert observed == [row["url"] for row in rows[:3]]
    assert len(prompts) == 1
    assert result["editorial_prefilter"]["skipped_before_duplicate"] == 1
    assert result["output"]["policy_version"] == active.POLICY_VERSION != OLD_POLICY


def test_old_strong_queue_class_is_reclassified_then_current_decision_reused(monkeypatch):
    row = candidate("https://ed6.test/queued", "MUST_PUBLISH", OLD_POLICY)
    queue.schedule({"selected": [row], "pending": [], "skipped": []}, {"observation_timestamp": NOW})
    board = queue.augment_board({"news_candidates_for_menzo": []})
    snapshot = shadow.capture_opportunity(board, run_id="new-policy", observation_timestamp=NOW,
                                         history=[], defer_relation_build=True)
    active.preserve_bob_capacity_metadata(snapshot, board["news_candidates_for_menzo"])
    calls = []
    result = active.evaluate(snapshot, provider=lambda *_: calls.append(True) or classification(["SHOULD_PUBLISH"]))
    assert result["status"] == "VALIDATED" and calls == [True]
    assert result["editorial_prefilter"]["reused_strong_classes"] == 0
    active.project(snapshot, result)
    board = queue.augment_board({"news_candidates_for_menzo": []})
    later = shadow.capture_opportunity(board, run_id="same-policy", observation_timestamp=NOW,
                                      history=[], defer_relation_build=True)
    active.preserve_bob_capacity_metadata(later, board["news_candidates_for_menzo"])
    result = active.evaluate(later, provider=lambda *_: pytest.fail("unchanged current class must be reused"))
    assert result["status"] == "VALIDATED"
    assert result["editorial_prefilter"]["reused_strong_classes"] == 1


def test_old_pool_waits_without_model_work_or_review_loss():
    row = candidate("https://ed6.test/old", policy=OLD_POLICY)
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
    board = soft.mark_rediscovered_pool_candidates({"news_candidates_for_menzo": []})
    assert board["news_candidates_for_menzo"] == []
    result = soft.apply(empty(), {"observation_timestamp": NOW, "remaining_slots": 20},
                        provider=lambda *_: pytest.fail("old admission cannot enter soft review"))
    assert result["selected"] == result["skipped"] == []
    assert result["pending"][0]["soft_board"]["disposition"] == "WAIT_PRIMARY_POLICY"
    stored = menzo.load_json(menzo.SOFTPOOL_FILE, {})["items"][0]
    assert stored["soft_board_review_count"] == 1 and stored["soft_board_day"] == row["soft_board_day"]
    assert result["postprocess"]["soft_board_meaningful_review"] is False


@pytest.mark.parametrize("new_class", ["SKIP", "SHOULD_PUBLISH", "PUBLISHABLE_SOFT"])
def test_feed_rediscovery_applies_current_policy_instead_of_restoring_old_soft(monkeypatch, new_class):
    old = candidate("https://ed6.test/old", policy=OLD_POLICY)
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [old]})
    feed = copy.deepcopy(old)
    feed["_soft_board_existing"] = True
    board = soft.mark_rediscovered_pool_candidates({"news_candidates_for_menzo": [feed]})
    assert "_soft_board_existing" not in board["news_candidates_for_menzo"][0]
    snapshot = shadow.capture_opportunity(board, run_id="rediscovered",
        observation_timestamp="2026-10-10T08:00:00Z", history=[], defer_relation_build=True)
    active.preserve_bob_capacity_metadata(snapshot, board["news_candidates_for_menzo"])
    result = active.evaluate(snapshot, provider=lambda *_: classification([new_class]))
    projected = active.project(snapshot, result)
    stored = menzo.load_json(menzo.SOFTPOOL_FILE, {})["items"]
    if new_class == "SKIP":
        assert stored == [] and len(projected["skipped"]) == 1
    elif new_class == "SHOULD_PUBLISH":
        assert stored == [] and len(projected["selected"]) == 1
    else:
        assert len(stored) == 1 and stored[0]["editorial_director"]["policy_version"] == active.POLICY_VERSION
        assert stored[0]["soft_board_review_count"] == 1
        assert stored[0]["soft_board_first_seen_at"] == "2026-10-10T08:00:00+00:00"


def test_current_review_preserves_old_policy_rows_that_are_waiting(monkeypatch):
    old = candidate("https://ed6.test/old", policy=OLD_POLICY)
    current = candidate("https://ed6.test/current")
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [old, current]})
    def revalidate(rows):
        assert [row["url"] for row in rows] == [current["url"]]
        return rows, [], {}
    monkeypatch.setattr(soft, "_revalidate_pool_duplicates", revalidate)
    def provider(prompt, *_):
        payload = json.loads(prompt.split("INPUT=", 1)[1])
        assert len(payload["candidates"]) == 1
        return {"candidates": [{"ref": "s0", "disposition": "SOFT_MUST", "reason": "Useful production insight"}]}
    result = soft.apply(empty(), {"observation_timestamp": NOW, "remaining_slots": 20}, provider=provider)
    assert [row["url"] for row in result["selected"]] == [current["url"]]
    stored = menzo.load_json(menzo.SOFTPOOL_FILE, {})["items"]
    assert [row["url"] for row in stored] == [old["url"]]
    assert stored[0]["soft_board_review_count"] == 1


def test_waiting_old_policy_row_still_expires_at_original_midnight():
    row = candidate("https://ed6.test/expired", policy=OLD_POLICY)
    row["soft_board_day"] = "2026-10-09"
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
    result = soft.apply(empty(), {"observation_timestamp": "2026-10-09T22:05:00Z", "remaining_slots": 30},
                        provider=lambda *_: pytest.fail("expired row cannot trigger review"))
    assert result["pending"] == result["selected"] == []
    assert result["skipped"][0]["soft_board"]["disposition"] == "MIDNIGHT_TOMBSTONE"
    assert menzo.load_json(menzo.SOFTPOOL_FILE, {})["items"] == []


@pytest.mark.parametrize("path", ["all_duplicates", "review_unavailable", "no_capacity", "morning"])
def test_waiting_policy_rows_survive_other_pool_exit_paths(monkeypatch, path):
    old = candidate("https://ed6.test/old", policy=OLD_POLICY)
    current = candidate("https://ed6.test/current")
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [old, current]})
    monkeypatch.setattr(soft, "_revalidate_pool_duplicates",
        lambda rows: ([], rows, {}) if path == "all_duplicates" else (rows, [], {}))
    monkeypatch.setattr(soft, "_review", lambda *_: (None, {"status": "PROVIDER_FAILED"}))
    snapshot = {"observation_timestamp": "2026-10-10T08:00:00Z" if path == "morning" else NOW,
                "remaining_slots": 0 if path == "no_capacity" else 20}
    result = soft.apply(empty(), snapshot)
    stored = menzo.load_json(menzo.SOFTPOOL_FILE, {})["items"]
    held = next(row for row in stored if row["url"] == old["url"])
    assert held["soft_board"]["disposition"] == "WAIT_PRIMARY_POLICY"
    assert held["soft_board_review_count"] == 1
    assert result["postprocess"]["soft_board_meaningful_review"] is False
    assert result["selected"] == []
    assert len(stored) == (1 if path == "all_duplicates" else 2)


def test_current_policy_pool_identity_is_still_preserved():
    row = candidate("https://ed6.test/current")
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
    board = soft.mark_rediscovered_pool_candidates({"news_candidates_for_menzo": [row]})
    assert board["news_candidates_for_menzo"][0]["_soft_board_existing"] is True
    assert board["news_candidates_for_menzo"][0]["_soft_board_existing_review_count"] == 1
