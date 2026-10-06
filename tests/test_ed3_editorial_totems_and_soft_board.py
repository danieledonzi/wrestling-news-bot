from datetime import datetime, timezone
import copy

from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_soft_board as soft_board
from agents import publisher


def _soft_item(name="soft", reviews=0):
    return {
        "source": "feed",
        "title": name,
        "summary": "secondary but legitimate story",
        "url": f"https://ed3.test/{name}",
        "soft_board_review_count": reviews,
        "editorial_director": {
            "editorial_class": "PUBLISHABLE_SOFT",
            "recommended_action": "DEFER",
            "story_core": f"{name} core",
            "category": "WWE",
        },
        "decision_authority": "editorial_director",
    }


def _snapshot_at(hour, *, published=10):
    value = shadow.capture_opportunity(
        {"news_candidates_for_menzo": []},
        run_id="run",
        observation_timestamp=f"2026-10-06T{hour:02d}:00:00+02:00",
        published_news_today_local=published,
        history=[],
    )
    value["candidates"] = []
    value["remaining_slots"] = max(0, 30 - published)
    value["_active_bob_capacity_metadata"] = {}
    return value


def test_primary_provider_input_hides_day_load():
    snapshot = _snapshot_at(14, published=27)
    payload = active.primary_provider_input(snapshot)
    context = payload["publication_context"]
    assert context == {
        "classification_contract": "intrinsic_editorial_value_only",
        "day_load_must_not_change_primary_class": True,
    }
    assert "published_news_today_local" not in context
    assert "remaining_news_slots_today" not in context


def test_primary_class_action_totems():
    snapshot = _snapshot_at(14)
    snapshot["candidates"] = [
        {"candidate_id": "m", "url": "https://ed3.test/m", "title": "M"},
        {"candidate_id": "h", "url": "https://ed3.test/h", "title": "H"},
        {"candidate_id": "s", "url": "https://ed3.test/s", "title": "S"},
        {"candidate_id": "x", "url": "https://ed3.test/x", "title": "X"},
    ]
    good = {"candidates": [
        {"ref": "c0", "editorial_class": "MUST_PUBLISH", "recommended_action": "SELECT", "category": "WWE", "story_core": "m"},
        {"ref": "c1", "editorial_class": "SHOULD_PUBLISH", "recommended_action": "SELECT", "category": "WWE", "story_core": "h"},
        {"ref": "c2", "editorial_class": "PUBLISHABLE_SOFT", "recommended_action": "DEFER", "category": "WWE", "story_core": "s"},
        {"ref": "c3", "editorial_class": "SKIP", "recommended_action": "SKIP", "category": "WWE", "story_core": "x"},
    ], "relations": []}
    canonical, failures, _ = active._validate_active(good, snapshot)
    assert canonical is not None and not failures

    bad = copy.deepcopy(good)
    bad["candidates"][1]["recommended_action"] = "DEFER"
    canonical, failures, _ = active._validate_active(bad, snapshot)
    assert canonical is None
    assert failures[0]["family"] == "class_action_incompatibility"


def test_morning_soft_hold_is_not_a_competitive_review(monkeypatch):
    snapshot = _snapshot_at(3)
    item = _soft_item("morning", reviews=2)
    projected = {"selected": [], "pending": [item], "skipped": [], "postprocess": {}}
    soft_board.apply(projected, snapshot)
    assert not projected["selected"]
    assert len(projected["pending"]) == 1
    held = projected["pending"][0]
    assert held["soft_board_review_count"] == 2
    assert held["soft_board"]["phase"] == "morning_accumulation"
    assert held["soft_board"]["meaningful_review"] is False


def test_post_noon_soft_board_can_publish_zero_with_free_capacity(monkeypatch):
    snapshot = _snapshot_at(14, published=8)
    item = _soft_item("quiet-run")

    def provider(*_args):
        return {"candidates": [{"ref": "s0", "disposition": "SOFT_SHOULD",
                                "reason": "Not strong enough to publish now"}]}

    projected = {"selected": [], "pending": [item], "skipped": [], "postprocess": {}}
    soft_board.apply(projected, snapshot, provider=provider)
    assert projected["selected"] == []
    assert len(projected["pending"]) == 1
    assert projected["pending"][0]["soft_board_review_count"] == 1
    assert projected["postprocess"]["soft_board"]["soft_slots_available"] > 0


def test_soft_should_expires_after_meaningful_review_limit(monkeypatch):
    snapshot = _snapshot_at(14, published=8)
    item = _soft_item("aging", reviews=soft_board.MAX_MEANINGFUL_REVIEWS - 1)

    def provider(*_args):
        return {"candidates": [{"ref": "s0", "disposition": "SOFT_SHOULD",
                                "reason": "Still not worth publishing"}]}

    projected = {"selected": [], "pending": [item], "skipped": [], "postprocess": {}}
    soft_board.apply(projected, snapshot, provider=provider)
    assert projected["pending"] == []
    assert len(projected["skipped"]) == 1
    assert projected["skipped"][0]["reason"] == "soft_board_repeatedly_outranked"


def test_soft_must_is_selected_but_primary_class_remains_soft(monkeypatch):
    snapshot = _snapshot_at(14, published=8)
    item = _soft_item("winner")

    def provider(*_args):
        return {"candidates": [{"ref": "s0", "disposition": "SOFT_MUST",
                                "reason": "Best worthwhile soft on the board"}]}

    projected = {"selected": [], "pending": [item], "skipped": [], "postprocess": {}}
    soft_board.apply(projected, snapshot, provider=provider)
    assert len(projected["selected"]) == 1
    winner = projected["selected"][0]
    assert winner["editorial_director"]["editorial_class"] == "PUBLISHABLE_SOFT"
    assert winner["soft_board"]["disposition"] == "SOFT_MUST"


def test_rediscovered_story_keeps_soft_state(monkeypatch, tmp_path):
    monkeypatch.setattr(menzo, "SOFTPOOL_FILE", tmp_path / "soft.json")
    monkeypatch.setattr(menzo, "HARD_SKIP_FILE", tmp_path / "hard.json")
    today = menzo._softpool_local_day()
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [{
        **_soft_item("same"),
        "softpool_added_at": datetime.now(timezone.utc).isoformat(),
        "softpool_day_local": today,
        "soft_board_review_count": 2,
        "softpool_deferrals": 2,
        "last_soft_board_disposition": "SOFT_SHOULD",
    }]})
    board = {"news_candidates_for_menzo": [{
        "source": "feed", "title": "same", "summary": "rediscovered",
        "url": "https://ed3.test/same",
    }]}
    augmented = menzo.augment_board_with_softpool(board)
    row = augmented["news_candidates_for_menzo"][0]
    assert row["soft_board_review_count"] == 2
    assert row["last_soft_board_disposition"] == "SOFT_SHOULD"
    assert row["from_softpool"] is True


def test_midnight_tombstones_previous_day_soft_and_filters_rediscovery(monkeypatch, tmp_path):
    monkeypatch.setattr(menzo, "SOFTPOOL_FILE", tmp_path / "soft.json")
    monkeypatch.setattr(menzo, "HARD_SKIP_FILE", tmp_path / "hard.json")
    yesterday = "2000-01-01"
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [{
        **_soft_item("old"),
        "softpool_added_at": datetime.now(timezone.utc).isoformat(),
        "softpool_day_local": yesterday,
    }]})
    board = {"news_candidates_for_menzo": [{
        "source": "feed", "title": "old", "summary": "rediscovered",
        "url": "https://ed3.test/old",
    }]}
    augmented = menzo.augment_board_with_softpool(board)
    assert augmented["news_candidates_for_menzo"] == []
    hard = menzo.load_json(menzo.HARD_SKIP_FILE, {"items": []})["items"]
    assert hard and hard[0]["reason"] == "soft_board_midnight_tombstone"


def test_duplicate_fail_closed_never_authorizes_urls(monkeypatch, tmp_path):
    for name in ("HARD_SKIP_FILE", "MENZO_DECISIONS_FILE", "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / f"{name}.json")
    snapshot = _snapshot_at(14)
    snapshot["candidates"] = [{
        "candidate_id": "candidate", "source": "feed", "title": "Potential MUST",
        "url": "https://ed3.test/unverified", "summary": "major story",
    }]
    blocked = active.project_duplicate_fail_closed(snapshot, "duplicate_gate_failed")
    assert blocked["selected"] == []
    assert blocked["pending"] == []
    assert blocked["allowed_urls_for_v92"] == []
    assert blocked["skipped"][0]["decision_authority"] == "duplicate_gate_fail_closed"


def test_publisher_allows_hard_over_nominal_ceiling_but_blocks_soft(monkeypatch):
    history = {str(i): {"status": "published", "published_at": "2026-10-06T10:00:00+00:00"}
               for i in range(30)}
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "ok"))
    monkeypatch.setattr(publisher, "publisher_duplicate_safety_filter", lambda articles, history: (articles, []))
    monkeypatch.setattr(publisher, "load_json", lambda path, default:
                        history if path == publisher.PUBLISHER_HISTORY_FILE else default)
    monkeypatch.setattr("agents.news_scheduling.datetime", type("Clock", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)),
        "fromisoformat": staticmethod(datetime.fromisoformat),
    }))
    attempted = []
    monkeypatch.setattr(publisher, "publish_article",
                        lambda article, *_: attempted.append(article["source_url"]) or {"status": "published"})
    monkeypatch.setattr(publisher, "write_json", lambda *_: None)
    hard = {"source_url": "https://ed3.test/hard", "editorial_director": {
        "editorial_class": "SHOULD_PUBLISH", "recommended_action": "SELECT"}}
    soft = {"source_url": "https://ed3.test/soft", "editorial_director": {
        "editorial_class": "PUBLISHABLE_SOFT", "recommended_action": "DEFER"},
        "soft_board": {"disposition": "SOFT_MUST"}}
    result = publisher.run_publisher({"approved_articles": [soft, hard]})
    assert attempted == ["https://ed3.test/hard"]
    assert result["handoff"]["skipped_capacity"] == 1
