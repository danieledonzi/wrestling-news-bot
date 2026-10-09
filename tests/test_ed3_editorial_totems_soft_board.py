import json
from pathlib import Path

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_soft_board as soft
from agents import massy_policy_v93_24 as massy


def _soft(url: str, title: str = "Soft story"):
    return {
        "url": url,
        "title": title,
        "summary": "A legitimate but expendable wrestling story.",
        "decision": "defer",
        "priority": "medium",
        "decision_authority": "editorial_director",
        "editorial_director": {
            "policy_version": active.POLICY_VERSION,
            "editorial_class": "PUBLISHABLE_SOFT",
            "recommended_action": "DEFER",
            "category": "WWE",
            "story_core": "A secondary interview or reaction without a major new fact.",
        },
    }


def _strong(url: str, cls: str):
    return {
        "url": url,
        "title": cls,
        "decision": "select",
        "priority": "high",
        "decision_authority": "editorial_director",
        "editorial_director": {
            "editorial_class": cls,
            "recommended_action": "SELECT",
            "category": "WWE",
            "story_core": "Strong factual development.",
        },
    }


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(menzo, "SOFTPOOL_FILE", tmp_path / "softpool.json")
    monkeypatch.setattr(menzo, "HARD_SKIP_FILE", tmp_path / "hard_skips.json")
    monkeypatch.setattr(menzo, "MENZO_DECISIONS_FILE", tmp_path / "menzo.json")
    monkeypatch.setattr(menzo, "ARTIFACT_DECISIONS_FILE", tmp_path / "artifact.json")
    monkeypatch.setattr(menzo, "V92_ALLOWED_URLS_FILE", tmp_path / "allowed.json")
    history = tmp_path / "publisher_history.json"
    history.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(menzo, "publisher_history_file", lambda: history)
    monkeypatch.setattr(soft, "record_gemini_attempt", lambda **_: None)
    monkeypatch.setattr("agents.bob.dynamic_article_capacity", lambda *_: (5, "test"))
    return tmp_path


def test_primary_provider_projection_has_no_pacing_context():
    s = shadow.capture_opportunity(
        {"news_candidates_for_menzo": [{"url": "https://ed3.test/a", "title": "A", "summary": "fact"}]},
        run_id="run", observation_timestamp="2026-10-07T10:00:00+00:00",
        published_news_today_local=17, history=[])
    active.prepare_snapshot(s)
    value = active.active_provider_input(s)
    assert "publication_context" not in value


def test_ed3_primary_action_matrix_is_fixed():
    allowed = {
        "MUST_PUBLISH": "SELECT",
        "SHOULD_PUBLISH": "SELECT",
        "PUBLISHABLE_SOFT": "DEFER",
        "SKIP": "SKIP",
    }
    for editorial_class, required_action in allowed.items():
        for action in ("SELECT", "DEFER", "SKIP"):
            s = shadow.capture_opportunity(
                {"news_candidates_for_menzo": [{"url": "https://ed3.test/a", "title": "A", "summary": "fact"}]},
                run_id="run", observation_timestamp="2026-10-07T10:00:00+00:00",
                published_news_today_local=0, history=[])
            active.prepare_snapshot(s)
            out = {"candidates": [{
                "ref": "c0", "editorial_class": editorial_class,
                "recommended_action": action, "category": "WWE", "story_core": "fact",
            }], "relations": []}
            canonical, failures, _ = active._validate_active(out, s)
            assert bool(canonical) is (action == required_action)
            assert bool(failures) is (action != required_action)


def test_morning_soft_is_held_without_competition(isolated_state):
    called = []
    projected = {"selected": [_strong("https://ed3.test/m", "MUST_PUBLISH")],
                 "pending": [_soft("https://ed3.test/s")], "skipped": [], "postprocess": {}}
    snapshot = {"observation_timestamp": "2026-10-07T07:00:00+00:00",  # 09:00 Rome
                "remaining_slots": 20}
    result = soft.apply(projected, snapshot, provider=lambda *_: called.append(True))
    assert called == []
    assert [x["soft_board"]["disposition"] for x in result["pending"]] == ["MORNING_HOLD"]
    assert result["pending"][0]["soft_board_review_count"] == 0
    assert result["selected"][0]["editorial_director"]["editorial_class"] == "MUST_PUBLISH"


def test_post_noon_board_can_publish_none(isolated_state, monkeypatch):
    monkeypatch.setattr(soft, "_revalidate_pool_duplicates",
                        lambda pool: (pool, [], {}))
    projected = {"selected": [_strong("https://ed3.test/sh", "SHOULD_PUBLISH")],
                 "pending": [_soft("https://ed3.test/a"), _soft("https://ed3.test/b")],
                 "skipped": [], "postprocess": {}}
    snapshot = {"observation_timestamp": "2026-10-07T11:00:00+00:00",  # 13:00 Rome
                "remaining_slots": 20}
    def provider(*_):
        return {"candidates": [
            {"ref": "s0", "disposition": "SOFT_SHOULD", "reason": "Worth another look, not now."},
            {"ref": "s1", "disposition": "SOFT_SKIP", "reason": "Too weak for today's board."},
        ]}
    result = soft.apply(projected, snapshot, provider=provider)
    assert len(result["selected"]) == 1  # only the primary SHOULD
    assert len(result["pending"]) == 1
    assert result["pending"][0]["soft_board"]["disposition"] == "SOFT_SHOULD"
    assert result["pending"][0]["soft_board_review_count"] == 1
    assert any(x.get("decision_authority") == "soft_board" for x in result["skipped"])


def test_post_noon_soft_must_uses_only_residual_capacity(isolated_state, monkeypatch):
    monkeypatch.setattr(soft, "_revalidate_pool_duplicates",
                        lambda pool: (pool, [], {}))
    projected = {"selected": [_strong("https://ed3.test/sh1", "SHOULD_PUBLISH"),
                              _strong("https://ed3.test/sh2", "SHOULD_PUBLISH")],
                 "pending": [_soft("https://ed3.test/a"), _soft("https://ed3.test/b")],
                 "skipped": [], "postprocess": {}}
    snapshot = {"observation_timestamp": "2026-10-07T12:00:00+00:00",
                "remaining_slots": 10}
    def provider(*_):
        return {"candidates": [
            {"ref": "s0", "disposition": "SOFT_MUST", "reason": "Best soft story and worth publishing now."},
            {"ref": "s1", "disposition": "SOFT_SHOULD", "reason": "Useful but not necessary now."},
        ]}
    result = soft.apply(projected, snapshot, provider=provider)
    assert [x.get("soft_board", {}).get("disposition") for x in result["selected"]] == [None, None, "SOFT_MUST"]
    assert len(result["pending"]) == 1


def test_no_residual_capacity_means_no_soft_review_or_loss(isolated_state, monkeypatch):
    monkeypatch.setattr("agents.bob.dynamic_article_capacity", lambda *_: (2, "test"))
    projected = {"selected": [_strong("https://ed3.test/sh1", "SHOULD_PUBLISH"),
                              _strong("https://ed3.test/sh2", "SHOULD_PUBLISH")],
                 "pending": [_soft("https://ed3.test/a")], "skipped": [], "postprocess": {}}
    called = []
    result = soft.apply(
        projected,
        {"observation_timestamp": "2026-10-07T12:00:00+00:00", "remaining_slots": 10},
        provider=lambda *_: called.append(True))
    assert called == []
    assert result["pending"][0]["soft_board"]["disposition"] == "WAIT_CAPACITY"
    assert result["pending"][0]["soft_board_review_count"] == 0


def test_repeated_meaningful_soft_should_expires(isolated_state, monkeypatch):
    monkeypatch.setattr(soft, "MAX_MEANINGFUL_REVIEWS", 3)
    url = "https://ed3.test/aging"
    row = _soft(url)
    row.update({
        "soft_board_day": "2026-10-07",
        "soft_board_review_count": 2,
        "soft_board_first_seen_at": "2026-10-07T08:00:00+00:00",
        "softpool_added_at": "2026-10-07T08:00:00+00:00",
        "soft_board_content_fingerprint": soft._content_fingerprint(row),
    })
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
    projected = {"selected": [], "pending": [], "skipped": [], "postprocess": {}}
    def provider(*_):
        return {"candidates": [{"ref": "s0", "disposition": "SOFT_SHOULD",
                                "reason": "Still not strong enough for publication."}]}
    result = soft.apply(
        projected,
        {"observation_timestamp": "2026-10-07T13:00:00+00:00", "remaining_slots": 10},
        provider=provider)
    assert result["pending"] == []
    assert result["skipped"][0]["reason"] == "soft_board_repeatedly_outranked"
    assert menzo.load_json(menzo.SOFTPOOL_FILE, {})["items"] == []


def test_midnight_tombstone_kills_previous_day_pool(isolated_state):
    row = _soft("https://ed3.test/yesterday")
    row.update({
        "soft_board_day": "2026-10-06",
        "soft_board_review_count": 1,
        "soft_board_first_seen_at": "2026-10-06T15:00:00+00:00",
        "softpool_added_at": "2026-10-06T15:00:00+00:00",
        "soft_board_content_fingerprint": soft._content_fingerprint(row),
    })
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
    result = soft.apply(
        {"selected": [], "pending": [], "skipped": [], "postprocess": {}},
        {"observation_timestamp": "2026-10-06T22:05:00+00:00", "remaining_slots": 30},
        provider=lambda *_: pytest.fail("midnight expiry should not invoke soft review"))
    assert result["pending"] == []
    assert result["skipped"][0]["reason"] == "soft_board_midnight_tombstone"


def test_unchanged_pool_rediscovery_still_crosses_duplicate_gate(isolated_state):
    row = _soft("https://ed3.test/repeat")
    fingerprint = soft._content_fingerprint(row)
    row.update({"soft_board_day": "2026-10-07",
                "soft_board_content_fingerprint": fingerprint,
                "soft_board_first_seen_at": "2026-10-07T02:00:00+00:00",
                "softpool_added_at": "2026-10-07T02:00:00+00:00"})
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
    fresh = {"url": row["url"], "title": row["title"], "summary": row["summary"]}
    board = soft.mark_rediscovered_pool_candidates({"news_candidates_for_menzo": [fresh]})
    assert len(board["news_candidates_for_menzo"]) == 1
    assert board["news_candidates_for_menzo"][0]["_soft_board_existing"] is True
    assert board["soft_board"]["unchanged_pool_rediscoveries_marked"] == 1


def test_unchanged_soft_cannot_be_promoted_by_primary_reclassification(isolated_state):
    row = _soft("https://ed3.test/repeat-promote")
    row.update({"soft_board_day": "2026-10-07",
                "soft_board_content_fingerprint": soft._content_fingerprint(row),
                "soft_board_first_seen_at": "2026-10-07T02:00:00+00:00",
                "softpool_added_at": "2026-10-07T02:00:00+00:00",
                "soft_board_review_count": 1})
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
    promoted = _strong(row["url"], "SHOULD_PUBLISH")
    promoted.update({"title": row["title"], "summary": row["summary"], "_soft_board_existing": True})
    result = soft.apply(
        {"selected": [promoted], "pending": [], "skipped": [], "postprocess": {}},
        {"observation_timestamp": "2026-10-07T07:00:00+00:00", "remaining_slots": 20},
        provider=lambda *_: pytest.fail("morning carried soft must not invoke review"))
    assert result["selected"] == []
    assert len(result["pending"]) == 1
    assert result["pending"][0]["editorial_director"]["editorial_class"] == "PUBLISHABLE_SOFT"
    assert result["pending"][0]["soft_board"]["disposition"] == "MORNING_HOLD"
    assert result["pending"][0]["soft_board_review_count"] == 1


def test_rediscovery_marker_survives_capture_via_active_sidecar(isolated_state):
    row = _soft("https://ed3.test/sidecar")
    row.update({
        "soft_board_day": "2026-10-07",
        "soft_board_content_fingerprint": soft._content_fingerprint(row),
        "soft_board_first_seen_at": "2026-10-07T02:00:00+00:00",
        "softpool_added_at": "2026-10-07T02:00:00+00:00",
        "soft_board_review_count": 1,
    })
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
    fresh = {"url": row["url"], "title": row["title"], "summary": row["summary"]}
    augmented = soft.mark_rediscovered_pool_candidates(
        menzo.augment_board_with_softpool({"news_candidates_for_menzo": [fresh]})
    )
    snapshot = shadow.capture_opportunity(
        augmented, run_id="run", observation_timestamp="2026-10-07T08:00:00+00:00",
        published_news_today_local=0, history=[])
    active.preserve_bob_capacity_metadata(snapshot, augmented["news_candidates_for_menzo"])
    cid = snapshot["candidates"][0]["candidate_id"]
    sidecar = snapshot["_active_bob_capacity_metadata"][cid]
    assert sidecar["_soft_board_existing"] is True
    assert sidecar["_soft_board_existing_review_count"] == 1
    assert sidecar["_soft_board_existing_fingerprint"] == row["soft_board_content_fingerprint"]


def test_active_capture_keeps_soft_pool_outside_candidate_limit(isolated_state, monkeypatch):
    import newsroom_runner as runner

    rows = []
    for index in range(45):
        row = _soft(f"https://ed3.test/pool-{index}", title=f"Pool soft {index}")
        row.update({
            "soft_board_day": "2026-10-07",
            "soft_board_first_seen_at": "2026-10-07T02:00:00+00:00",
            "softpool_added_at": "2026-10-07T02:00:00+00:00",
            "soft_board_content_fingerprint": soft._content_fingerprint(row),
        })
        rows.append(row)
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": rows})

    monkeypatch.setattr(shadow, "costly_work_eligibility", lambda: (True, "ready"))
    monkeypatch.setattr(menzo, "load_authoritative_publisher_history", lambda *_a, **_k: [])
    monkeypatch.setattr(menzo, "load_soft_tombstone_duplicate_history", lambda *_a, **_k: [])
    monkeypatch.setattr(menzo, "published_today_count", lambda: 0)

    board = {
        "news_candidates_for_menzo": [{
            "url": "https://ed3.test/fresh",
            "title": "Fresh feed candidate",
            "summary": "A current feed development.",
        }],
        "published_due_reports": {},
    }
    snapshot, diagnostic, _ = runner.capture_editorial_director_opportunity(
        board, run_id="run", observation_timestamp="2026-10-07T08:00:00+00:00",
        preserve_active_metadata=True)

    assert diagnostic is None
    assert len(snapshot["candidates"]) == 1
    assert snapshot["candidates"][0]["url"] == "https://ed3.test/fresh"
    assert snapshot["limit_status"] != "exceeded"


def test_noon_soft_board_can_review_pool_larger_than_active_candidate_limit(isolated_state):
    rows = []
    for index in range(45):
        row = _soft(f"https://ed3.test/noon-{index}", title=f"Noon soft {index}")
        row.update({
            "soft_board_day": "2026-10-07",
            "soft_board_first_seen_at": "2026-10-07T02:00:00+00:00",
            "softpool_added_at": "2026-10-07T02:00:00+00:00",
            "soft_board_content_fingerprint": soft._content_fingerprint(row),
            "soft_board_review_count": 0,
        })
        rows.append(row)
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": rows})
    prompts = []

    def provider(prompt, *_):
        prompts.append(prompt)
        return {"candidates": [
            {"ref": f"s{index}", "disposition": "SOFT_SHOULD",
             "reason": "Still eligible but not worth publishing now."}
            for index in range(45)
        ]}

    result = soft.apply(
        {"selected": [], "pending": [], "skipped": [], "postprocess": {}},
        {"observation_timestamp": "2026-10-07T11:00:00+00:00", "remaining_slots": 30},
        provider=provider)

    assert len(prompts) == 1
    assert '"ref":"s44"' in prompts[0]
    assert len(result["pending"]) == 45
    assert result["postprocess"]["soft_board_pool_size"] == 45
    assert result["postprocess"]["soft_board_meaningful_review"] is True


def test_changed_same_url_after_midnight_remains_tombstoned(isolated_state):
    prior = _soft("https://ed3.test/midnight-change", title="Original soft story")
    prior["summary"] = "Original secondary detail."
    prior.update({
        "soft_board_day": "2026-10-06",
        "soft_board_first_seen_at": "2026-10-06T15:00:00+00:00",
        "softpool_added_at": "2026-10-06T15:00:00+00:00",
    })
    prior["soft_board_content_fingerprint"] = soft._content_fingerprint(prior)
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [prior]})

    changed = _soft(prior["url"], title="Original soft story")
    changed["summary"] = "Edited or refreshed text on the same canonical URL."
    result = soft.apply(
        {"selected": [], "pending": [changed], "skipped": [], "postprocess": {}},
        {"observation_timestamp": "2026-10-06T22:05:00+00:00", "remaining_slots": 30},
        provider=lambda *_: pytest.fail("same-URL tombstone must not invoke review"))

    assert result["pending"] == []
    tombstones = [x for x in result["skipped"] if x.get("reason") == "soft_board_midnight_tombstone"]
    assert len(tombstones) >= 1

def test_fingerprint_drift_without_material_update_keeps_soft_identity(isolated_state):
    prior = _soft("https://ed3.test/drift", title="Soft interview")
    prior["summary"] = "Original wording."
    prior.update({
        "soft_board_day": "2026-10-07",
        "soft_board_first_seen_at": "2026-10-07T02:00:00+00:00",
        "softpool_added_at": "2026-10-07T02:00:00+00:00",
        "soft_board_review_count": 1,
    })
    prior["soft_board_content_fingerprint"] = soft._content_fingerprint(prior)
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [prior]})

    refreshed = _strong(prior["url"], "SHOULD_PUBLISH")
    refreshed["title"] = prior["title"]
    refreshed["summary"] = "Edited feed wording only."
    refreshed["_soft_board_existing"] = True

    result = soft.apply(
        {"selected": [refreshed], "pending": [], "skipped": [], "postprocess": {}},
        {"observation_timestamp": "2026-10-07T07:00:00+00:00", "remaining_slots": 20},
        provider=lambda *_: pytest.fail("morning carried soft must not invoke review"))

    assert result["selected"] == []
    assert len(result["pending"]) == 1
    assert result["pending"][0]["editorial_director"]["editorial_class"] == "PUBLISHABLE_SOFT"
    assert result["pending"][0]["soft_board_review_count"] == 1
    assert result["pending"][0]["soft_board"]["disposition"] == "MORNING_HOLD"


def test_massy_same_url_tombstone_is_unconditional(monkeypatch):
    candidate = {
        "url": "https://ed3.test/tombstone-reworded",
        "title": "Same URL, rewritten headline",
        "summary": "Edited wording only.",
    }
    stored = {
        "decision_authority": "soft_board",
        "reason": "soft_board_midnight_tombstone",
        "soft_board_content_fingerprint": "prior-fingerprint",
        "added_at": "2026-10-07T00:00:00+00:00",
        "soft_board_tombstone_snapshot": {
            "title": "Original headline",
            "summary": "Original wording.",
            "story_core": "Same secondary story.",
            "soft_board_day": "2026-10-06",
        },
    }
    key = massy.source_key(candidate["url"])
    monkeypatch.setattr(massy, "base_run_massy", lambda: {
        "news_candidates_for_menzo": [dict(candidate)],
        "report_candidates": [], "hard_skipped": [], "handoff": {},
    })
    monkeypatch.setattr(massy, "report_coverage", lambda *_: ({}, set(), set()))
    monkeypatch.setattr(massy, "build_suspicious_story_clusters", lambda *_: [])
    monkeypatch.setattr(massy, "menzo_skip_memory", lambda: {key: stored})
    monkeypatch.setattr(massy, "configured_reports", lambda: [])
    monkeypatch.setattr(massy, "old_news_reason", lambda *_: None)

    board = massy.run_massy()
    assert board["news_candidates_for_menzo"] == []
    assert board["handoff"]["menzo_memory_hard_skipped"] == 1


def test_soft_tombstone_history_is_available_to_duplicate_gate(isolated_state):
    row = _soft("https://ed3.test/old-soft", title="Wrestler discusses contract status")
    row["summary"] = "The wrestler says there is no signed deal yet."
    row.update({
        "soft_board_day": "2026-10-06",
        "soft_board_first_seen_at": "2026-10-06T15:00:00+00:00",
        "softpool_added_at": "2026-10-06T15:00:00+00:00",
    })
    row["soft_board_content_fingerprint"] = soft._content_fingerprint(row)
    skipped = soft._terminal_skip(row, "soft_board_midnight_tombstone", "MIDNIGHT_TOMBSTONE",
                                  soft._parse_dt("2026-10-07T00:05:00+00:00"))
    menzo.save_hard_skips({"selected": [], "pending": [], "skipped": [skipped]})

    history = menzo.load_soft_tombstone_duplicate_history()
    assert len(history) == 1
    assert history[0]["source_url"] == row["url"]
    assert history[0]["history_state"] == "soft_tombstone"
    assert "no signed deal" in history[0]["summary"]


def test_new_url_can_be_compared_with_tombstoned_story(isolated_state):
    old = {
        "source_url": "https://ed3.test/old-soft",
        "source_title": "Wrestler contract status update",
        "title_it": "Wrestler contract status update",
        "summary": "Wrestler says there is no signed deal yet.",
        "published_at": "2026-10-06T20:00:00+00:00",
        "history_state": "soft_tombstone",
    }
    new = {
        "url": "https://ed3.test/new-development",
        "title": "Wrestler contract status update",
        "summary": "Wrestler says there is no signed deal yet.",
    }
    snapshot = shadow.capture_opportunity(
        {"news_candidates_for_menzo": [new]},
        run_id="run", observation_timestamp="2026-10-07T08:00:00+00:00",
        published_news_today_local=0, history=[old])
    assert snapshot["publisher_history_12h"][0]["history_state"] == "soft_tombstone"
    assert snapshot["authorized_relations"]
    assert snapshot["authorized_relations"][0]["scope"] == "recent_history"
    active.prepare_snapshot(snapshot)
    assert snapshot["candidates"]  # semantic gate, not URL identity, decides the different-URL relation

def test_soft_board_review_retains_exact_day_context(isolated_state):
    projected = {
        "selected": [_strong("https://ed3.test/should-context", "SHOULD_PUBLISH")],
        "pending": [_soft("https://ed3.test/soft-context")],
        "skipped": [],
        "postprocess": {},
    }
    snapshot = {
        "observation_timestamp": "2026-10-07T11:00:00+00:00",
        "remaining_slots": 20,
    }

    def provider(*_):
        return {"candidates": [{
            "ref": "s0", "disposition": "SOFT_SHOULD",
            "reason": "Still useful but not worth publishing in this run.",
        }]}

    result = soft.apply(projected, snapshot, provider=provider)
    context = result["postprocess"]["soft_board_review_day_context"]
    assert context["local_time"].startswith("2026-10-07T13:00:00")
    assert context["published_total_today"] == 0
    assert context["soft_capacity_this_run"] >= 0
    assert context["unused_capacity_is_not_a_target"] is True
    assert context["zero_soft_publications_is_valid"] is True


def test_first_post_midnight_primary_select_cannot_revive_expired_soft(isolated_state):
    prior = _soft("https://ed3.test/midnight-selected", title="Expired soft")
    prior.update({
        "soft_board_day": "2026-10-06",
        "soft_board_first_seen_at": "2026-10-06T18:00:00+00:00",
        "softpool_added_at": "2026-10-06T18:00:00+00:00",
        "soft_board_content_fingerprint": soft._content_fingerprint(prior),
    })
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [prior]})

    promoted = _strong(prior["url"], "SHOULD_PUBLISH")
    promoted["title"] = prior["title"]
    promoted["_soft_board_existing"] = True

    result = soft.apply(
        {"selected": [promoted], "pending": [], "skipped": [], "postprocess": {}},
        {"observation_timestamp": "2026-10-06T22:05:00+00:00", "remaining_slots": 30},
        provider=lambda *_: pytest.fail("expired carried URL must not reach soft review"))

    assert result["selected"] == []
    assert result["pending"] == []
    assert any(item.get("reason") == "soft_board_midnight_tombstone"
               for item in result["skipped"])


def test_active_input_safety_ceiling_is_one_megabyte():
    assert shadow.MAX_INPUT_BYTES == 1_000_000


def test_duplicate_revalidation_runs_before_soft_board_review(isolated_state, monkeypatch):
    row = _soft("https://ed3.test/pool-duplicate", title="Already covered story")
    row.update({
        "soft_board_day": "2026-10-07",
        "soft_board_first_seen_at": "2026-10-07T02:00:00+00:00",
        "softpool_added_at": "2026-10-07T02:00:00+00:00",
        "soft_board_content_fingerprint": soft._content_fingerprint(row),
    })
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})

    def same_run_guard(work, _board):
        return None

    def recent_guard(work):
        item = work["selected"].pop()
        item["decision"] = "skip"
        item["priority"] = "skip"
        item["article_type"] = "duplicate"
        item["reason"] = "skip:duplicate_recently_published"
        item["decision_authority"] = "semantic_duplicate_gate"
        work["skipped"].append(item)

    monkeypatch.setattr(menzo, "apply_same_story_duplicate_guard", same_run_guard)
    monkeypatch.setattr(menzo, "apply_recent_published_duplicate_guard", recent_guard)

    result = soft.apply(
        {"selected": [], "pending": [], "skipped": [], "postprocess": {}},
        {"observation_timestamp": "2026-10-07T11:00:00+00:00", "remaining_slots": 30},
        provider=lambda *_: pytest.fail("duplicate row must be removed before Soft Board Gemini"))

    assert result["selected"] == []
    assert result["pending"] == []
    assert result["postprocess"]["soft_board_duplicates_removed"] == 1
    assert result["postprocess"]["soft_board_status"] == "EMPTY_AFTER_DUPLICATE_REVALIDATION"
    assert any(item.get("reason") == "skip:duplicate_recently_published"
               for item in result["skipped"])
