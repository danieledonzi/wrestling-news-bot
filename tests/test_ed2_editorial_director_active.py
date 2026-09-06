from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo


def snapshot(count=3, published=0):
    board = {"news_candidates_for_menzo": [
        {"source": "feed", "title": title, "url": f"https://ed2.test/{i}", "summary": "fact"}
        for i, title in enumerate([
            "WWE Starts Cutting NXT Roster as Jasper Troy Becomes First Confirmed Release",
            "Report: WWE Releasing NXT Talents",
            "Jasper Troy Sparks WWE Release Speculation With Cryptic ‘30 Days’ Message",
        ][:count])]}
    return shadow.capture_opportunity(board, run_id="run", observation_timestamp="now",
                                      publisher_count_24h=published, history=[])


def response(s, actions=("SELECT", "DEFER", "SKIP")):
    classes = ("MUST_PUBLISH", "PUBLISHABLE_SOFT", "SKIP")
    return {"candidates": [{"ref": f"c{i}", "editorial_class": classes[i],
             "recommended_action": actions[i], "category": "NXT", "story_core": f"core {i}"}
            for i in range(len(s["candidates"]))], "relations": [{"ref": f"r{i}", "decision": "NO_MATCH"}
            for i in range(len(s["authorized_relations"]))]}


def test_active_flag_is_separate_and_defaults_off():
    assert not active.enabled({})
    assert not active.enabled({"OWTV_EDITORIAL_DIRECTOR_ACTIVE_ENABLED": "false",
                               "OWTV_EDITORIAL_DIRECTOR_SHADOW_ENABLED": "true"})


def test_active_provider_policy_contains_no_shadow_authority_language():
    policy = active.POLICY_PATH.read_text().lower()
    forbidden = ("policy v2.1", "non-binding ed-1.1", "non-binding diagnostic evidence",
                 "does not alter production", "diagnostic action")
    assert not any(term in policy for term in forbidden)
    assert "mandatory and authoritative" in policy and "remaining_slots" in policy


def test_valid_active_result_projects_jasper_fixture_without_legacy_scoring(monkeypatch, tmp_path):
    s = snapshot(); monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    monkeypatch.setattr(menzo, "SOFTPOOL_FILE", tmp_path / "softpool.json")
    monkeypatch.setattr(menzo, "MENZO_DECISIONS_FILE", tmp_path / "menzo.json")
    monkeypatch.setattr(menzo, "ARTIFACT_DECISIONS_FILE", tmp_path / "artifact.json")
    monkeypatch.setattr(menzo, "V92_ALLOWED_URLS_FILE", tmp_path / "allowed.json")
    monkeypatch.setattr(menzo, "HARD_SKIP_FILE", tmp_path / "hard-skips.json")
    (tmp_path / "menzo.json").write_text('{"decision_authority":"legacy_menzo","selected":[{"url":"https://stale"}]}')
    result = active.evaluate(s, provider=lambda *_: response(s))
    handoff = active.project(s, result)
    assert result["status"] == "VALIDATED" and result["attempts"] == 1
    assert [len(handoff[x]) for x in ("selected", "pending", "skipped")] == [1, 1, 1]
    assert handoff["selected"][0]["title"].startswith("WWE Starts Cutting")
    assert handoff["skipped"][0]["title"].startswith("Jasper Troy Sparks")
    assert handoff["selected"][0]["editorial_director"] == {
        "policy_version": active.POLICY_VERSION, "candidate_id": s["candidates"][0]["candidate_id"],
        "editorial_class": "MUST_PUBLISH", "recommended_action": "SELECT", "relative_rank": 1,
        "category": "NXT", "story_core": "core 0", "decision_authority": "editorial_director"}
    assert handoff["pending"][0]["decision"] == "defer"
    persisted = menzo.load_json(tmp_path / "softpool.json", {})["items"]
    assert [item["url"] for item in persisted] == ["https://ed2.test/1"]
    assert menzo.augment_board_with_softpool({"news_candidates_for_menzo": []})["news_candidates_for_menzo"][0]["from_softpool"]
    assert menzo.load_json(tmp_path / "menzo.json", {})["decision_authority"] == "editorial_director"
    assert menzo.load_json(tmp_path / "allowed.json", {})["allowed_urls"] == ["https://ed2.test/0"]
    assert handoff["allowed_urls_for_v92"] == ["https://ed2.test/0"]
    hard_skips = menzo.load_json(tmp_path / "hard-skips.json", {})["items"]
    assert [item["url"] for item in hard_skips] == ["https://ed2.test/2"]
    from agents import publisher
    monkeypatch.setattr(publisher, "MENZO_DECISIONS_FILE", tmp_path / "menzo.json")
    monkeypatch.setattr(publisher, "BOB_ARTICLES_FILE", tmp_path / "missing-bob.json")
    trace = publisher.build_trace_metadata_index({})[publisher.source_key("https://ed2.test/0")]
    assert trace["pipeline_version"] == active.POLICY_VERSION and trace["menzo_decision"] == "select"

    from agents import massy_policy_v93_24 as massy
    monkeypatch.setattr(massy, "MENZO_HARD_SKIP_FILE", tmp_path / "hard-skips.json")
    monkeypatch.setattr(massy, "base_run_massy", lambda: {"news_candidates_for_menzo": [
        {"url": "https://ed2.test/2", "title": "repeat"}], "report_candidates": [],
        "hard_skipped": [], "handoff": {}})
    monkeypatch.setattr(massy, "report_coverage", lambda *_: ([], [], []))
    monkeypatch.setattr(massy, "configured_reports", lambda: [])
    monkeypatch.setattr(massy, "ARTIFACT_MASSY_FILE", tmp_path / "massy-artifact.json")
    monkeypatch.setattr(massy, "MASSY_BOARD_FILE", tmp_path / "massy-state.json")
    massy_result = massy.run_massy()
    assert massy_result["news_candidates_for_menzo"] == []
    assert massy_result["hard_skipped"][0]["reason"] == "menzo_hard_skip_memory"


def test_missing_action_and_capacity_violation_each_repair_once(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(1); bad = response(s, ("SELECT",)); del bad["candidates"][0]["recommended_action"]
    calls = []; result = active.evaluate(s, provider=lambda *_: calls.append(1) or bad)
    assert result["status"] == "failed" and len(calls) == 2
    s = snapshot(1, published=30); calls = []
    result = active.evaluate(s, provider=lambda *_: calls.append(1) or response(s, ("SELECT",)))
    assert result["status"] == "failed" and len(calls) == 2
    assert result["validation_errors"][0]["family"] == "publication_capacity"


def test_provider_failure_and_oversize_are_whole_result_failures(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(1)
    result = active.evaluate(s, provider=lambda *_: (_ for _ in ()).throw(TimeoutError()))
    assert result["status"] == "PROVIDER_FAILED" and result["attempts"] == 1
    monkeypatch.setattr(shadow, "MAX_INPUT_BYTES", 1)
    assert active.evaluate(s, provider=lambda *_: None)["status"] == "OVERSIZE_NOT_EVALUATED"


def test_contradictory_duplicate_actions_repair_then_fail(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(2)
    left, right = [x["candidate_id"] for x in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    out = response(s, ("SELECT", "SELECT")); out["relations"] = [
        {"ref": "r0", "decision": "DUPLICATE", "shared_fact": "same confirmed release"}]
    calls = []; result = active.evaluate(s, provider=lambda *_: calls.append(1) or out)
    assert len(calls) == 2 and result["validation_errors"][0]["family"] == "same_run_duplicate_action"


def test_duplicate_requires_only_one_same_run_eligible_endpoint(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(2); s["downstream_capacity"] = 5
    left, right = [x["candidate_id"] for x in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    for actions, valid in ((('SELECT', 'SKIP'), True), (('DEFER', 'SKIP'), True),
                           (('SKIP', 'SKIP'), True), (('SELECT', 'DEFER'), False),
                           (('DEFER', 'DEFER'), False), (('DEFER', 'SELECT'), False)):
        out = response(s, actions); out["relations"] = [{"ref": "r0", "decision": "DUPLICATE", "shared_fact": "same"}]
        canonical, failures, _ = active._validate_active(out, s)
        assert bool(canonical) is valid and bool(failures) is not valid


def test_recent_duplicate_requires_skip_not_defer():
    s = snapshot(1); s["downstream_capacity"] = 5; candidate_id = s["candidates"][0]["candidate_id"]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "recent_history", "left_id": candidate_id,
        "right_id": "history", "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    for action, valid in (("SKIP", True), ("SELECT", False), ("DEFER", False)):
        out = response(s, (action,)); out["relations"] = [{"ref": "r0", "decision": "DUPLICATE", "shared_fact": "same"}]
        canonical, failures, _ = active._validate_active(out, s)
        assert bool(canonical) is valid and bool(failures) is not valid


def test_exact_duplicates_are_removed_before_gemini_relations(monkeypatch):
    same = {"source": "feed", "title": "Identical material", "summary": "Identical fact"}
    board = {"news_candidates_for_menzo": [{**same, "url": "https://one.test/a"},
                                             {**same, "url": "https://two.test/b"}]}
    s = shadow.capture_opportunity(board, run_id="run", observation_timestamp="now",
                                   publisher_count_24h=0, history=[])
    active.prepare_snapshot(s)
    assert len(s["candidates"]) == 1 and len(s["deterministic_exact_skips"]) == 1
    assert s["authorized_relations"] == []
    history = [{**same, "source_url": "https://published.test/a"}]
    s = shadow.capture_opportunity({"news_candidates_for_menzo": [{**same, "url": "https://new.test/a"}]},
        run_id="run", observation_timestamp="now", publisher_count_24h=1, history=history)
    active.prepare_snapshot(s)
    assert s["candidates"] == [] and s["deterministic_exact_skips"][0]["exact_duplicate_scope"] == "recent_history"
    assert s["authorized_relations"] == []
    result = active.evaluate(s, provider=lambda *_: (_ for _ in ()).throw(AssertionError("no provider call")))
    assert result["status"] == "VALIDATED" and result["attempts"] == 0


def test_deterministic_exact_skip_is_persisted_to_existing_hard_memory(monkeypatch, tmp_path):
    same = {"source": "feed", "title": "Identical", "summary": "same"}
    s = shadow.capture_opportunity({"news_candidates_for_menzo": [
        {**same, "url": "https://exact.test/one"}, {**same, "url": "https://exact.test/two"}]},
        run_id="run", observation_timestamp="now", publisher_count_24h=0, history=[])
    monkeypatch.setattr(menzo, "hydrate_complete_article_bodies", lambda items: (True, []))
    result = active.evaluate(s, provider=lambda *_: response(s, ("SELECT",)))
    for name in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                 "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / f"{name}.json")
    projected = active.project(s, result)
    memory = menzo.load_json(menzo.HARD_SKIP_FILE, {})["items"]
    assert len(projected["skipped"]) == 1 and len(memory) == 1
    assert memory[0]["reason"] == "exact_duplicate"


def test_active_defer_uses_bounded_softpool_decay_without_overriding_select(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    def project_action(action, deferrals, name):
        row = {"source": "feed", "title": f"Candidate {name}", "summary": "fact",
               "url": f"https://decay.test/{name}", "from_softpool": True,
               "softpool_added_at": datetime.now(timezone.utc).isoformat(),
               "softpool_deferrals": deferrals, "decision_authority": "editorial_director",
               "editorial_director": {"recommended_action": "DEFER"}}
        s = shadow.capture_opportunity({"news_candidates_for_menzo": [row]}, run_id="run",
            observation_timestamp="now", publisher_count_24h=0, history=[])
        result = active.evaluate(s, provider=lambda *_: response(s, (action,)))
        root = tmp_path / name
        for field in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                      "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
            monkeypatch.setattr(menzo, field, root / f"{field}.json")
        menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [row]})
        return active.project(s, result), menzo.load_json(menzo.SOFTPOOL_FILE, {"items": []})["items"]

    below, below_pool = project_action("DEFER", menzo.SOFTPOOL_OUTRANKED_DEFERRALS - 1, "below")
    assert len(below["pending"]) == 1 and not below["skipped"]
    assert below_pool[0]["softpool_deferrals"] == menzo.SOFTPOOL_OUTRANKED_DEFERRALS

    bounded, bounded_pool = project_action("DEFER", menzo.SOFTPOOL_OUTRANKED_DEFERRALS, "bounded")
    assert not bounded["pending"] and not bounded_pool and len(bounded["skipped"]) == 1
    ended = bounded["skipped"][0]
    assert ended["editorial_director"]["recommended_action"] == "DEFER"
    assert ended["menzo_policy"]["softpool_repeatedly_outranked"] is True
    assert bounded["handoff"]["pending"] == 0 and bounded["handoff"]["skipped"] == 1

    selected, selected_pool = project_action("SELECT", menzo.SOFTPOOL_OUTRANKED_DEFERRALS, "selected")
    assert len(selected["selected"]) == 1 and not selected["skipped"] and not selected_pool
    skipped, skipped_pool = project_action("SKIP", menzo.SOFTPOOL_OUTRANKED_DEFERRALS, "skipped")
    assert len(skipped["skipped"]) == 1 and not skipped["pending"] and not skipped_pool


def test_failed_late_active_persistence_restores_every_state_file(monkeypatch, tmp_path):
    s = snapshot(); monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    result = active.evaluate(s, provider=lambda *_: response(s))
    fields = ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
              "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE")
    before = {}
    for index, field in enumerate(fields):
        path = tmp_path / f"{field}.json"
        monkeypatch.setattr(menzo, field, path)
        if field != "V92_ALLOWED_URLS_FILE":
            content = f"pre-active-{index}".encode()
            path.write_bytes(content); before[path] = content
        else:
            before[path] = None
    original_write = menzo.write_json
    def fail_late(path, value):
        if path == menzo.V92_ALLOWED_URLS_FILE:
            raise OSError("late allowed-url failure")
        return original_write(path, value)
    monkeypatch.setattr(menzo, "write_json", fail_late)
    import pytest
    with pytest.raises(OSError, match="late allowed-url failure"):
        active.project(s, result)
    for path, content in before.items():
        assert (path.read_bytes() if path.exists() else None) == content


def test_exact_winner_uses_legacy_hydration_then_canonical_winner(monkeypatch):
    same = {"source": "feed", "title": "Exact", "summary": "Same material"}
    s = shadow.capture_opportunity({"news_candidates_for_menzo": [
        {**same, "url": "https://thin.test/a"}, {**same, "url": "https://rich.test/a"}]},
        run_id="run", observation_timestamp="now", publisher_count_24h=0, history=[])
    def hydrate(items):
        for item in items:
            text = "short body" if "thin" in item["url"] else "rich factual body " * 30
            item["canonical_source_body"] = {"schema_version": "owtv_canonical_source_body_v1",
                "source_url": item["url"], "text": text, "provenance": "test"}
        return True, []
    monkeypatch.setattr(menzo, "hydrate_complete_article_bodies", hydrate)
    local = [dict(item) for item in s["candidates"]]; hydrate(local)
    legacy_winner, _ = menzo.canonical_richer_winner(local)
    active.prepare_snapshot(s)
    assert s["candidates"][0]["candidate_id"] == legacy_winner["candidate_id"]
    assert "canonical_source_body" not in s["candidates"][0]


def test_active_refinalizes_effective_provider_evidence(monkeypatch):
    same = {"source": "feed", "title": "Exact", "summary": "Same material"}
    s = shadow.capture_opportunity({"news_candidates_for_menzo": [
        {**same, "url": "https://one.test/a"}, {**same, "url": "https://two.test/a"}]},
        run_id="run", observation_timestamp="now", publisher_count_24h=2, history=[])
    capture_digest = s["input_digest"]
    active.prepare_snapshot(s)
    encoded = __import__("json").dumps(active.active_provider_input(s), ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()
    assert s["observed"]["candidate_count"] == 1 and s["observed"]["relation_count"] == 0
    assert s["observed"]["serialized_input_bytes"] == len(encoded)
    assert s["input_digest"] == __import__("hashlib").sha256(encoded).hexdigest()
    assert s["input_digest"] != capture_digest and s["capture_input_digest"] == capture_digest
    other = snapshot(1); active.prepare_snapshot(other)
    assert other["input_digest"] != s["input_digest"]
    monkeypatch.setattr(shadow, "MAX_INPUT_BYTES", len(encoded) - 1)
    active._finalize_active_input(s)
    assert s["limit_status"] == "exceeded"


def test_oversize_exact_collapse_rebuilds_nonexact_suspicion_relations(monkeypatch):
    rows = [{"source": "feed", "title": f"Story {i}", "summary": f"Fact {i}",
             "url": f"https://rebuild.test/{i}"} for i in range(shadow.MAX_CANDIDATES + 1)]
    def score(left, right):
        pair = {left.get("url"), right.get("url")}
        exact = pair == {"https://rebuild.test/0", "https://rebuild.test/1"}
        suspicious = pair == {"https://rebuild.test/2", "https://rebuild.test/3"}
        return {"exact_duplicate": exact, "above_threshold": exact or suspicious,
                "scorer_version": "test", "score": .9 if exact or suspicious else 0,
                "threshold": .55, "components": {"central_fact_action": 1 if suspicious else 0}}
    monkeypatch.setattr(shadow.menzo_duplicate_scorer, "score_pair", score)
    monkeypatch.setattr(menzo, "hydrate_complete_article_bodies", lambda items: (True, []))
    s = shadow.capture_opportunity({"news_candidates_for_menzo": rows}, run_id="run",
        observation_timestamp="now", publisher_count_24h=0, history=[])
    assert s["limit_status"] == "exceeded" and not s["authorized_relations_complete"]
    active.prepare_snapshot(s)
    assert s["limit_status"] != "exceeded" and s["observed"]["candidate_count"] == shadow.MAX_CANDIDATES
    assert len(s["deterministic_exact_skips"]) == 1
    assert len(s["authorized_relations"]) == 1
    relation = s["authorized_relations"][0]
    retained = {item["candidate_id"]: item["url"] for item in s["candidates"]}
    assert {retained[relation["left_id"]], retained[relation["right_id"]]} == {
        "https://rebuild.test/2", "https://rebuild.test/3"}
    provider_relations = active.active_provider_input(s)["authorized_relations"]
    assert len(provider_relations) == 1 and provider_relations[0]["ref"] == "r0"


def test_effective_bob_capacity_is_an_active_validation_bound(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    monkeypatch.setattr("agents.bob.dynamic_article_capacity", lambda *_: (1, "test_capacity"))
    s = snapshot(2); out = response(s, ("SELECT", "SELECT")); calls = []
    result = active.evaluate(s, provider=lambda *_: calls.append(1) or out)
    assert len(calls) == 2 and result["validation_errors"][0]["family"] == "downstream_capacity"


def test_actual_selected_set_not_pool_controls_post_show_capacity(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    rows = []
    for i in range(7):
        rows.append({"source": "feed", "title": (f"Raw result {i}" if i < 3 else f"General item {i}"),
                     "url": f"https://capacity.test/{i}", "summary": "distinct"})
    s = shadow.capture_opportunity({"news_candidates_for_menzo": rows}, run_id="run",
        observation_timestamp="now", publisher_count_24h=0, history=[])
    out = {"candidates": [{"ref": f"c{i}", "editorial_class": "SHOULD_PUBLISH",
        "recommended_action": "SKIP" if i < 3 else "SELECT", "category": "WWE", "story_core": str(i)}
        for i in range(7)], "relations": [{"ref": f"r{i}", "decision": "NO_MATCH"}
        for i in range(len(s["authorized_relations"]))]}
    # Add two non-post-show selections while retaining fewer than three selected post-show items.
    out["candidates"][0]["recommended_action"] = "SELECT"
    out["candidates"][1]["recommended_action"] = "SELECT"
    calls = []; result = active.evaluate(s, provider=lambda *_: calls.append(1) or out)
    assert len(calls) == 2 and result["validation_errors"][0]["family"] == "downstream_capacity"


def test_hidden_capacity_metadata_preserves_six_hard_news_selects(monkeypatch, tmp_path):
    from agents import bob
    monkeypatch.setattr(bob, "report_was_published_or_attempted", lambda: False)
    rows = [{"source": "feed", "title": f"Distinct {i}", "url": f"https://six.test/{i}",
             "summary": f"fact {i}", "article_type": "hard_news",
             "source_title": f"Capacity source marker {i}", "reason": "factual",
             "ai_editorial_reason": "retained", "event_key": f"event-{i}",
             "category_hint": "old-category"} for i in range(6)]
    s = shadow.capture_opportunity({"news_candidates_for_menzo": rows}, run_id="run",
        observation_timestamp="now", publisher_count_24h=0, history=[])
    without_sidecar = __import__("copy").deepcopy(s)
    active.preserve_bob_capacity_metadata(s, rows)
    active.prepare_snapshot(s); active.prepare_snapshot(without_sidecar)
    assert s["input_digest"] == without_sidecar["input_digest"]
    assert s["observed"]["serialized_input_bytes"] == without_sidecar["observed"]["serialized_input_bytes"]
    provider = active.active_provider_input(s)
    serialized = __import__("json").dumps(provider)
    assert "_active_bob_capacity_metadata" not in provider
    assert "hard_news" not in serialized and "Capacity source marker" not in serialized
    out = {"candidates": [{"ref": f"c{i}", "editorial_class": "MUST_PUBLISH",
        "recommended_action": "SELECT", "category": "WWE", "story_core": f"core {i}"}
        for i in range(6)], "relations": [{"ref": f"r{i}", "decision": "NO_MATCH"}
        for i in range(len(s["authorized_relations"]))]}
    result = active.evaluate(s, provider=lambda *_: out)
    assert result["status"] == "VALIDATED"
    for field in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                  "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, field, tmp_path / f"{field}.json")
    projected = active.project(s, result)
    capacity, reason = bob.dynamic_article_capacity(projected, projected["selected"])
    assert len(projected["selected"]) == 6 and (capacity, reason) == (6, "post_show_event_heavy")
    assert all(item["article_type"] == "hard_news" and item["source_title"].startswith("Capacity source")
               and item["category_hint"] == "WWE" for item in projected["selected"])


def test_skip_class_action_contradiction_is_not_rewritten(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    for action, valid in (("SELECT", False), ("DEFER", False), ("SKIP", True)):
        s = snapshot(1); out = response(s, (action,)); out["candidates"][0]["editorial_class"] = "SKIP"
        canonical, failures, _ = active._validate_active(out, active.prepare_snapshot(s))
        assert bool(canonical) is valid and bool(failures) is not valid


def test_fallback_provenance_is_persisted_for_publisher(monkeypatch, tmp_path):
    import newsroom_runner
    from agents import publisher
    for name in ("MENZO_DECISIONS_FILE", "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / f"{name}.json")
    decision = {"version": "legacy", "selected": [{"url": "https://fallback.test/a", "decision": "selected"}],
                "pending": [], "skipped": [], "allowed_urls_for_v92": ["https://fallback.test/a"], "handoff": {}}
    newsroom_runner.persist_active_fallback(decision, "provider_failed")
    monkeypatch.setattr(publisher, "MENZO_DECISIONS_FILE", menzo.MENZO_DECISIONS_FILE)
    monkeypatch.setattr(publisher, "BOB_ARTICLES_FILE", tmp_path / "none.json")
    persisted = menzo.load_json(menzo.MENZO_DECISIONS_FILE, {})
    trace = publisher.build_trace_metadata_index({})[publisher.source_key("https://fallback.test/a")]
    assert persisted["decision_authority"] == "legacy_menzo_fallback"
    assert trace["decision_authority"] == "legacy_menzo_fallback" and trace["fallback_reason"] == "provider_failed"


def test_active_fallback_reason_preserves_structured_specificity():
    import newsroom_runner
    error = RuntimeError("fallback")
    assert newsroom_runner.active_fallback_reason(
        {"status": "NOT_ELIGIBLE_WP_NOT_READY", "reason": "wp_not_ready"}, error) == "wp_not_ready"
    assert newsroom_runner.active_fallback_reason(
        {"status": "failed", "reason": "less_specific", "fallback_reason": "provider_failed"}, error) == "provider_failed"
    assert newsroom_runner.active_fallback_reason({"status": "failed"}, error) == "failed"
    assert newsroom_runner.active_fallback_reason({"status": "VALIDATED"}, OSError("projection")) == "OSError"
    assert newsroom_runner.active_fallback_reason(None, ValueError("unexpected")) == "ValueError"


def test_runner_routes_active_success_without_legacy_and_failure_once(monkeypatch, tmp_path):
    import newsroom_runner
    from agents import menzo_editorial_director_shadow as shadow_module
    observed = []; authority_events = []
    from agents import canonical_event_ledger
    monkeypatch.setattr(canonical_event_ledger, "active_event",
                        lambda *args, **kwargs: authority_events.append((args, kwargs)))
    class Observer:
        def safely(self, *args, **_k): observed.append(args[0] if args else "")
        def summary(self): return {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OWTV_EDITORIAL_DIRECTOR_ACTIVE_ENABLED", "true")
    monkeypatch.setenv("OWTV_EDITORIAL_DIRECTOR_SHADOW_ENABLED", "true")
    monkeypatch.setenv("V93_SKIP_V92_AFTER_BOB", "1")
    monkeypatch.setattr(newsroom_runner, "initialize_canonical_ledger", lambda *_: Observer())
    monkeypatch.setattr(newsroom_runner, "initialize_canonical_artifact_index", lambda *_: Observer())
    monkeypatch.setattr(newsroom_runner, "capture_editorial_director_opportunity",
                        lambda *_a, **_k: ({"candidates": [{}]}, None, (True, "ready")))
    monkeypatch.setattr(newsroom_runner, "write_master_log_safe", lambda *_a, **_k: {})
    monkeypatch.setattr(newsroom_runner, "gemini_ledger_summary", lambda: {})
    monkeypatch.setattr(shadow_module, "evaluate", lambda *_a, **_k:
                        (_ for _ in ()).throw(AssertionError("shadow must be suppressed")))
    legacy_calls = []
    def safe_agent(**kwargs):
        if kwargs["agent"] == "Menzo":
            legacy_calls.append(kwargs["phase"])
            return {"version": "legacy", "selected": [], "pending": [], "skipped": [],
                    "allowed_urls_for_v92": [], "handoff": {}}
        return {"handoff": {}}
    monkeypatch.setattr(newsroom_runner, "safe_agent", safe_agent)
    monkeypatch.setattr(active, "evaluate", lambda *_a, **_k: {"status": "VALIDATED", "output": {}})
    monkeypatch.setattr(active, "project", lambda *_a, **_k: {"version": "active", "selected": [],
        "pending": [], "skipped": [], "handoff": {"decision_authority": "editorial_director"}})
    assert newsroom_runner.main() == 0 and legacy_calls == []
    assert "observe_editorial_director_active" in observed
    assert any(kwargs.get("result") == "editorial_director_active_authorized" for _, kwargs in authority_events)
    observed.clear(); authority_events.clear()
    monkeypatch.setattr(active, "project", lambda *_a, **_k:
                        (_ for _ in ()).throw(OSError("projection failed")))
    persisted = []
    def persist_projection_fallback(decision, reason):
        decision["decision_authority"] = "legacy_menzo_fallback"
        persisted.append((decision, reason))
        return decision
    monkeypatch.setattr(newsroom_runner, "persist_active_fallback", persist_projection_fallback)
    assert newsroom_runner.main() == 0
    assert legacy_calls == ["legacy_menzo_fallback"]
    assert persisted[0][0]["decision_authority"] == "legacy_menzo_fallback"
    assert persisted[0][1] == "OSError" and persisted[0][1] != "VALIDATED"
    assert "observe_editorial_director_active" not in observed
    assert not any(kwargs.get("result") == "editorial_director_active_authorized" for _, kwargs in authority_events)
    legacy_calls.clear(); observed.clear(); authority_events.clear()
    monkeypatch.setattr(active, "project", lambda *_a, **_k: {"version": "active", "selected": [],
        "pending": [], "skipped": [], "handoff": {"decision_authority": "editorial_director"}})
    monkeypatch.setattr(active, "evaluate", lambda *_a, **_k:
                        {"status": "failed", "fallback_reason": "invalid"})
    persisted = []
    monkeypatch.setattr(newsroom_runner, "persist_active_fallback",
                        lambda decision, reason: persisted.append((decision, reason)) or decision)
    assert newsroom_runner.main() == 0
    assert legacy_calls == ["legacy_menzo_fallback"] and persisted[0][1] == "invalid"
    monkeypatch.setattr(newsroom_runner, "capture_editorial_director_opportunity", lambda *_a, **_k:
        (None, {"status": "NOT_ELIGIBLE_WP_NOT_READY", "reason": "wp_not_ready", "attempts": 0},
         (False, "wp_not_ready")))
    legacy_calls.clear(); persisted.clear()
    assert newsroom_runner.main() == 0
    assert legacy_calls == ["legacy_menzo_fallback"] and persisted[0][1] == "wp_not_ready"


def test_active_artifact_is_authoritative_and_not_shadow_labelled(monkeypatch, tmp_path):
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    index = CanonicalArtifactIndex("run", index_path=tmp_path / "index.jsonl",
        material_root=tmp_path / "materials", repository_root=tmp_path, enabled=True)
    s = snapshot(1); out = response(s, ("SELECT",)); result = {
        "schema_version": active.SCHEMA_VERSION, "policy_version": active.POLICY_VERSION,
        "logical_request_id": "lrq", "status": "VALIDATED", "validation_attempts": []}
    canonical, failures, _ = active._validate_active(out, active.prepare_snapshot(s))
    assert not failures
    index.observe_editorial_director_active(s, canonical, result)
    row = __import__("json").loads((tmp_path / "index.jsonl").read_text().splitlines()[0])
    package_path = tmp_path / row["path"]
    package = __import__("json").loads(package_path.read_text())
    assert "editorial-director-active" in row["path"] and "shadow" not in row["path"]
    assert row["authority_claims"] == [{"purpose": "pipeline_observability", "level": "authoritative"}]
    assert package["decision_authority"] == "editorial_director"
