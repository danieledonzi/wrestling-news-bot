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
    value = shadow.capture_opportunity(board, run_id="run", observation_timestamp="now",
                                       publisher_count_24h=published, history=[])
    value["authorized_relations"] = []
    value["authorized_relations_complete"] = True
    return value


def response(s, actions=("SELECT", "DEFER", "SKIP")):
    classes = tuple("MUST_PUBLISH" if action == "SELECT" else
                    "PUBLISHABLE_SOFT" if action == "DEFER" else "SKIP" for action in actions)
    return {"candidates": [{"ref": f"c{i}", "editorial_class": classes[i],
             "recommended_action": actions[i], "category": "NXT", "story_core": f"core {i}"}
            for i in range(len(s["candidates"]))], "relations": [{"ref": f"r{i}", "decision": "NO_MATCH"}
            for i in range(len(s["authorized_relations"]))]}


def grounded_duplicate(ref, left_evidence, right_evidence, shared_fact="same confirmed development"):
    return {"ref": ref, "decision": "DUPLICATE", "shared_fact": shared_fact,
            "left_evidence": left_evidence, "right_evidence": right_evidence,
            "left_central_development": shared_fact,
            "right_central_development": shared_fact,
            "centrality_basis": "The supported shared fact is the autonomous central development of both endpoints."}


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
    assert hard_skips[0]["reason"] == "editorial_class_skip"
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


def test_missing_action_repairs_and_must_select_survives_daily_reference(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(1); bad = response(s, ("SELECT",)); del bad["candidates"][0]["recommended_action"]
    calls = []; result = active.evaluate(s, provider=lambda *_: calls.append(1) or bad)
    assert result["status"] == "failed" and len(calls) == 2
    s = snapshot(1, published=30); calls = []
    result = active.evaluate(s, provider=lambda *_: calls.append(1) or response(s, ("SELECT",)))
    assert result["status"] == "VALIDATED" and len(calls) == 1


def test_provider_failure_and_oversize_are_whole_result_failures(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(1)
    result = active.evaluate(s, provider=lambda *_: (_ for _ in ()).throw(TimeoutError()))
    assert result["status"] == "PROVIDER_FAILED" and result["attempts"] == 1
    monkeypatch.setattr(shadow, "MAX_INPUT_BYTES", 1)
    assert active.evaluate(s, provider=lambda *_: None)["status"] == "OVERSIZE_NOT_EVALUATED"


def test_same_run_duplicate_is_removed_before_editorial_classification(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(2)
    left, right = [x["candidate_id"] for x in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate("r0", s["candidates"][0]["title"],
                                                       s["candidates"][1]["title"],
                                                       "same confirmed release")]}
        return response(s, ("SELECT",))
    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED" and len(calls) == 2
    assert len(result["output"]["candidates"]) == 1
    assert len(s["semantic_duplicate_skips"]) == 1


def test_duplicate_gate_lifecycle_and_cost_precede_classification(monkeypatch):
    from agents import canonical_event_ledger
    events, ledger, calls = [], [], []
    monkeypatch.setattr(canonical_event_ledger, "active_event",
                        lambda event, *args, **kwargs: events.append((event, kwargs)))
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **kwargs: ledger.append(kwargs))
    s = snapshot(2); left, right = [row["candidate_id"] for row in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    replies = iter([
        {"relations": [{"ref": "r0", "decision": "NO_MATCH"}]},
        response(s, ("SELECT", "DEFER")),
    ])
    result = active.evaluate(s, provider=lambda *_: calls.append(1) or next(replies))
    assert result["status"] == "VALIDATED" and len(calls) == 2
    assert [row["workload"] for row in ledger] == [
        "editorial_director_duplicate_gate", "editorial_director_active"]
    roles = [kwargs.get("model_role") for event, kwargs in events if event == "logical_ai_request_created"]
    assert roles == ["editorial_director_duplicate_gate", "editorial_director_active"]
    gate_completed = next(i for i, row in enumerate(events) if row[0] == "model_attempt_completed")
    classification_created = next(i for i, row in enumerate(events)
                                  if row[0] == "logical_ai_request_created" and
                                  row[1].get("model_role") == "editorial_director_active")
    assert gate_completed < classification_created


def test_empty_relation_matrix_creates_no_duplicate_gate_attempt(monkeypatch):
    from agents import canonical_event_ledger
    events, ledger = [], []
    monkeypatch.setattr(canonical_event_ledger, "active_event",
                        lambda event, *args, **kwargs: events.append((event, kwargs)))
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **kwargs: ledger.append(kwargs))
    s = snapshot(1)
    result = active.evaluate(s, provider=lambda *_: response(s, ("SELECT",)))
    assert result["status"] == "VALIDATED" and len(ledger) == 1
    assert ledger[0]["workload"] == "editorial_director_active"
    assert not any(kwargs.get("model_role") == "editorial_director_duplicate_gate"
                   for _, kwargs in events)


def test_duplicate_gate_invalid_then_repair_records_two_attempts(monkeypatch):
    from agents import canonical_event_ledger
    events, ledger = [], []
    monkeypatch.setattr(canonical_event_ledger, "active_event",
                        lambda event, *args, **kwargs: events.append((event, kwargs)))
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **kwargs: ledger.append(kwargs))
    s = snapshot(2); left, right = [row["candidate_id"] for row in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    replies = iter([{"relations": []}, {"relations": [{"ref": "r0", "decision": "NO_MATCH"}]},
                    response(s, ("SELECT", "DEFER"))])
    result = active.evaluate(s, provider=lambda *_: next(replies))
    gate_ledger = [row for row in ledger if row["workload"] == "editorial_director_duplicate_gate"]
    assert result["status"] == "VALIDATED" and len(gate_ledger) == 2
    assert [row["repair"] for row in gate_ledger] == [False, True]
    gate_events = [(event, kwargs) for event, kwargs in events
                   if kwargs.get("model_role") == "editorial_director_duplicate_gate"]
    failed = [kwargs for event, kwargs in gate_events if event == "model_attempt_failed"]
    assert failed[0]["error_class"] == "validation" and failed[0]["error_terminal"] is False
    assert any(event == "model_attempt_completed" for event, _ in gate_events)


def _production_incident_snapshot(title, summary=""):
    board = {"news_candidates_for_menzo": [{"source": "feed", "title": title,
        "url": "https://incident.test/current", "summary": summary}]}
    history = [{"source_url": "https://incident.test/history", "source_title":
        "Stephanie Vaquer wins WWE Women's World Championship at live event in Chile"}]
    value = shadow.capture_opportunity(board, run_id="incident", observation_timestamp="now",
        publisher_count_24h=0, history=history)
    candidate_id = value["candidates"][0]["candidate_id"]
    history_id = value["publisher_history_12h"][0]["article_id"]
    value["authorized_relations"] = [{"pair_id": "incident-pair", "scope": "recent_history",
        "left_id": candidate_id, "right_id": history_id, "scorer_version": "test", "score": .9,
        "threshold": .55, "components": {}}]
    value["authorized_relations_complete"] = True
    return value


def _ungrounded_vaquer_duplicate():
    return {"relations": [{"ref": "r0", "decision": "DUPLICATE",
        "shared_fact": "Stephanie Vaquer title win",
        "left_evidence": "Stephanie Vaquer title win",
        "right_evidence": "Stephanie Vaquer wins WWE Women's World Championship",
        "left_central_development": "Stephanie Vaquer won the title",
        "right_central_development": "Stephanie Vaquer won the title",
        "centrality_basis": "The title win is central to both endpoints."}]}


def test_case_a_ungrounded_duplicate_repairs_to_no_match_before_binding(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = _production_incident_snapshot(
        "AEW's Maya World Addresses Dave Meltzer Not Rating Her PPV Match With Mercedes Mone",
        "Former AEW TBS Champion Maya World addressed Dave Meltzer not rating her "
        "AEW x NJPW Forbidden Door bout against Mercedes Mone.")
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if len(calls) == 1:
            assert "DUPLICATE GATE PHASE ONLY" in prompt
            return _ungrounded_vaquer_duplicate()
        if len(calls) == 2:
            assert "duplicate_left_evidence_grounding" in prompt
            assert not s.get("semantic_duplicate_skips")
            return {"relations": [{"ref": "r0", "decision": "NO_MATCH"}]}
        return response(s, ("SELECT",))
    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED" and len(calls) == 3
    gate_attempts = [row for row in result["validation_attempts"] if row.get("phase") == "duplicate_gate"]
    assert [row["valid"] for row in gate_attempts] == [False, True]
    assert gate_attempts[0]["validation_families"][0]["family"] == "duplicate_left_evidence_grounding"
    assert not s["semantic_duplicate_skips"] and len(s["candidates"]) == 1


def test_case_a_repeated_ungrounded_duplicate_fails_atomically_without_artifact(monkeypatch, tmp_path):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = _production_incident_snapshot(
        "AEW's Maya World Addresses Dave Meltzer Not Rating Her PPV Match With Mercedes Mone",
        "Former AEW TBS Champion Maya World addressed Dave Meltzer not rating her match.")
    calls = []
    result = active.evaluate(s, provider=lambda *_: calls.append(1) or _ungrounded_vaquer_duplicate())
    assert result["status"] == "failed" and len(calls) == 2
    assert result["fallback_reason"] == "duplicate_left_evidence_grounding"
    assert "semantic_duplicate_skips" not in s and len(s["candidates"]) == 1
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    index = CanonicalArtifactIndex("incident", index_path=tmp_path / "index.jsonl",
        material_root=tmp_path / "materials", repository_root=tmp_path, enabled=True)
    assert index.summary()["artifacts_archived"] == 0 and not (tmp_path / "index.jsonl").exists()


def test_duplicate_evidence_cannot_cross_relation_endpoints():
    board = {"news_candidates_for_menzo": [
        {"title": "Alpha signs a new contract", "url": "https://cross.test/a", "summary": "Alpha signs"},
        {"title": "Beta returns at the arena", "url": "https://cross.test/b", "summary": "Beta returns"}]}
    history = [
        {"source_title": "Alpha signs a new contract", "source_url": "https://cross.test/ha"},
        {"source_title": "Beta returns at the arena", "source_url": "https://cross.test/hb"}]
    s = shadow.capture_opportunity(board, run_id="cross", observation_timestamp="now",
        publisher_count_24h=0, history=history)
    candidate_ids = [row["candidate_id"] for row in s["candidates"]]
    history_ids = [row["article_id"] for row in s["publisher_history_12h"]]
    s["authorized_relations"] = [
        {"pair_id": "p0", "scope": "recent_history", "left_id": candidate_ids[0],
         "right_id": history_ids[0], "scorer_version": "v", "score": .7, "threshold": .55, "components": {}},
        {"pair_id": "p1", "scope": "recent_history", "left_id": candidate_ids[1],
         "right_id": history_ids[1], "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    rows = [grounded_duplicate("r0", "Alpha signs", "Alpha signs"),
            grounded_duplicate("r1", "Alpha signs", "Beta returns")]
    canonical, failures, _ = active._validate_duplicate_gate({"relations": rows}, s)
    assert canonical is None
    assert {row["family"] for row in failures} == {"duplicate_left_evidence_grounding"}
    assert failures[0]["ref"] == "r1"


def test_case_b_policy_schema_and_no_match_survival(monkeypatch):
    import json
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    policy = active.POLICY_PATH.read_text().casefold()
    assert "reaction, criticism, comment, response, controversy, consequence, or follow-up" in policy
    assert "cause, background, or" in policy and "central new" in policy
    schema = json.loads(active.RELATION_SCHEMA_PATH.read_text())
    branches = schema["properties"]["relations"]["items"]["anyOf"]
    by_decision = {branch["properties"]["decision"]["enum"][0]: branch for branch in branches}
    duplicate_then = by_decision["DUPLICATE"]
    assert set(("left_evidence", "right_evidence", "left_central_development",
                "right_central_development", "centrality_basis")) <= set(duplicate_then["required"])
    s = _production_incident_snapshot(
        "Triple H Gets Dragged Over Stephanie Vaquer Winning Women’s World Title at WWE Live Event")
    replies = iter([{"relations": [{"ref": "r0", "decision": "NO_MATCH"}]}, response(s, ("SELECT",))])
    result = active.evaluate(s, provider=lambda *_: next(replies))
    assert result["status"] == "VALIDATED" and not s["semantic_duplicate_skips"]


def test_duplicate_gate_provider_schema_uses_supported_union_keywords_only():
    import json
    schema = json.loads(active.RELATION_SCHEMA_PATH.read_text())
    unsupported = {"allOf", "if", "then", "const", "pattern", "minLength", "maxLength"}

    def schema_keywords(value):
        found = set()
        if isinstance(value, dict):
            for key, child in value.items():
                found.add(key)
                if key == "properties" and isinstance(child, dict):
                    for property_schema in child.values():
                        found.update(schema_keywords(property_schema))
                else:
                    found.update(schema_keywords(child))
        elif isinstance(value, list):
            for child in value:
                found.update(schema_keywords(child))
        return found

    assert schema_keywords(schema).isdisjoint(unsupported)
    branches = schema["properties"]["relations"]["items"]["anyOf"]
    assert len(branches) == 3
    by_decision = {branch["properties"]["decision"]["enum"][0]: branch for branch in branches}
    assert set(by_decision) == {"DUPLICATE", "MATERIAL_UPDATE", "NO_MATCH"}
    assert all(len(branch["properties"]["decision"]["enum"]) == 1 for branch in branches)
    assert {"left_evidence", "right_evidence", "left_central_development",
            "right_central_development", "centrality_basis"} <= set(by_decision["DUPLICATE"]["required"])
    assert {"new_fact", "temporal_basis"} <= set(by_decision["MATERIAL_UPDATE"]["required"])
    assert set(by_decision["NO_MATCH"]["required"]) == {"ref", "decision"}


def test_grounding_normalization_is_formatting_only():
    endpoint = {"title": "Wrestler’s return — officially confirmed"}
    assert active._grounded_evidence("  WRESTLER'S   RETURN - officially ", endpoint) == (True, "title")
    assert active._grounded_evidence("confirmed return by a synonym", endpoint)[0] is False


def test_grounding_rejects_trivial_and_partial_token_spans():
    endpoint = {"title": "Alpha title announcement confirms a major return"}
    assert active._grounded_evidence("a", endpoint) == (False, "insufficient_meaningful_span")
    assert active._grounded_evidence("title", endpoint) == (False, "insufficient_meaningful_span")
    assert active._grounded_evidence("pha title", endpoint) == (False, "not_token_boundary_aligned")
    assert active._grounded_evidence("Alpha title", endpoint) == (True, "title")


def test_duplicate_gate_provider_failure_has_terminal_lifecycle_and_no_classification(monkeypatch):
    from agents import canonical_event_ledger
    events, ledger = [], []
    monkeypatch.setattr(canonical_event_ledger, "active_event",
                        lambda event, *args, **kwargs: events.append((event, kwargs)))
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **kwargs: ledger.append(kwargs))
    s = snapshot(2); left, right = [row["candidate_id"] for row in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    result = active.evaluate(s, provider=lambda *_: (_ for _ in ()).throw(TimeoutError()))
    assert result["status"] == "PROVIDER_FAILED" and ledger[0]["status"] == "failed"
    failed = [kwargs for event, kwargs in events if event == "model_attempt_failed"]
    assert len(failed) == 1 and failed[0]["error_terminal"] is True
    assert not any(event == "logical_ai_request_created" and
                   kwargs.get("model_role") == "editorial_director_active" for event, kwargs in events)


def test_gate_eliminates_all_without_creating_classification_request(monkeypatch, tmp_path):
    from agents import canonical_event_ledger
    events, ledger = [], []
    monkeypatch.setattr(canonical_event_ledger, "active_event",
                        lambda event, *args, **kwargs: events.append((event, kwargs)))
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **kwargs: ledger.append(kwargs))
    s = snapshot(1); candidate_id = s["candidates"][0]["candidate_id"]
    history = {"article_id": "published", "source_url": "https://history.test/old",
               "title": "Earlier title change", "input_coverage": "RSS_SUMMARY_ONLY"}
    s["publisher_history_12h"] = [history]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "recent_history",
        "left_id": candidate_id, "right_id": "published", "scorer_version": "v", "score": .7,
        "threshold": .55, "components": {}}]
    result = active.evaluate(s, provider=lambda *_: {"relations": [grounded_duplicate(
        "r0", s["candidates"][0]["title"], history["title"], "same title change")]})
    assert result["status"] == "VALIDATED" and len(ledger) == 1
    assert result["duplicate_gate_input_digest"]
    assert "logical_request_id" not in result
    assert any(event == "model_attempt_completed" for event, _ in events)
    assert not any(event == "logical_ai_request_created" and
                   kwargs.get("model_role") == "editorial_director_active" for event, kwargs in events)
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    index = CanonicalArtifactIndex("run", index_path=tmp_path / "index.jsonl",
        material_root=tmp_path / "materials", repository_root=tmp_path, enabled=True)
    index.observe_editorial_director_active(s, result["output"], result)
    rows = [__import__("json").loads(line) for line in (tmp_path / "index.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    package = __import__("json").loads((tmp_path / rows[0]["path"]).read_text())
    assert package["decision_authority"] == "semantic_duplicate_gate"
    assert package["director_output"] is None
    assert package["semantic_duplicate_scope"] == "recent_history"
    assert package["semantic_duplicate_of"] == "published"
    assert package["duplicate_gate_logical_request_id"] == result["duplicate_gate_logical_request_id"]
    assert package["duplicate_gate_input_digest"] == result["duplicate_gate_input_digest"]
    assert "logical_request_id" not in package and "input_digest" not in package
    assert package["relations"][0]["pair_id"] == "p"


def test_class_action_matrix_is_a_validator_invariant():
    allowed = {"MUST_PUBLISH": {"SELECT"}, "SHOULD_PUBLISH": {"SELECT", "DEFER"},
               "PUBLISHABLE_SOFT": {"SELECT", "DEFER"}, "SKIP": {"SKIP"}}
    for editorial_class, valid_actions in allowed.items():
        for action in ("SELECT", "DEFER", "SKIP"):
            s = snapshot(1); out = response(s, (action,))
            out["candidates"][0]["editorial_class"] = editorial_class
            canonical, failures, _ = active._validate_active(out, active.prepare_snapshot(s))
            assert bool(canonical) is (action in valid_actions)
            assert bool(failures) is (action not in valid_actions)


def test_active_contract_uses_canonicalized_enum_values(monkeypatch):
    monkeypatch.setattr("agents.bob.dynamic_article_capacity", lambda *_: (0, "test"))
    cases = [
        ("must_publish", "DEFER", False, "class_action_incompatibility"),
        ("must_publish", "SKIP", False, "class_action_incompatibility"),
        ("must_publish", "select", True, None),
        ("should_publish", "SKIP", False, "class_action_incompatibility"),
        ("publishable_soft", "defer", True, None),
        ("skip", "SELECT", False, "skip_action_invariant"),
    ]
    for editorial_class, action, valid, family in cases:
        s = snapshot(1); out = response(s, ("SELECT",))
        out["candidates"][0].update(editorial_class=editorial_class, recommended_action=action)
        canonical, failures, _ = active._validate_active(out, active.prepare_snapshot(s))
        assert bool(canonical) is valid
        if family:
            assert family in {row["family"] for row in failures}


def test_preclassification_capacity_hint_is_conservative(monkeypatch):
    from agents import bob
    monkeypatch.setattr(bob, "report_was_published_or_attempted", lambda: False)
    def make_snapshot(post_show_count, ordinary_count):
        rows = [{"source": "feed", "title": f"Post {i}", "url": f"https://hint.test/p{i}",
                 "summary": "distinct", "article_type": "hard_news"}
                for i in range(post_show_count)] + [
               {"source": "feed", "title": f"Other {i}", "url": f"https://hint.test/o{i}",
                "summary": "distinct"} for i in range(ordinary_count)]
        s = shadow.capture_opportunity({"news_candidates_for_menzo": rows}, run_id="run",
            observation_timestamp="now", publisher_count_24h=0, history=[])
        s["authorized_relations"] = []
        active.preserve_bob_capacity_metadata(s, rows)
        active.prepare_snapshot(s)
        return s

    raw_post_show_pool = make_snapshot(3, 3)
    assert (raw_post_show_pool["downstream_capacity"],
            raw_post_show_pool["downstream_capacity_reason"]) == (5, "normal")
    provider_input = active.active_provider_input(raw_post_show_pool)
    assert provider_input["publication_context"]["downstream_capacity_hint"] == 5

    monkeypatch.setattr(bob, "report_was_published_or_attempted", lambda: True)
    report_run = make_snapshot(3, 3)
    assert (report_run["downstream_capacity"], report_run["downstream_capacity_reason"]) == (4, "report_run")

    monkeypatch.setattr(bob, "report_was_published_or_attempted", lambda: False)
    limited = make_snapshot(3, 3)
    limited["remaining_slots"] = 2
    active._refresh_capacity_hint(limited)
    assert limited["downstream_capacity"] == 2


def test_vaquer_title_change_must_rejects_skip_and_defer():
    for action, valid in (("SKIP", False), ("DEFER", False), ("SELECT", True)):
        s = snapshot(1)
        s["candidates"][0]["title"] = ("Stephanie Vaquer defeats Liv Morgan to win the WWE Women's "
                                        "World Championship")
        out = response(s, (action,))
        out["candidates"][0].update(editorial_class="MUST_PUBLISH",
                                    story_core="Vaquer defeats Morgan to win the championship")
        canonical, failures, _ = active._validate_active(out, active.prepare_snapshot(s))
        assert bool(canonical) is valid and bool(failures) is not valid


def test_recent_duplicate_material_update_and_no_match_gate_states():
    for decision, eliminated in (("DUPLICATE", True), ("MATERIAL_UPDATE", False), ("NO_MATCH", False)):
        s = snapshot(1)
        candidate_id = s["candidates"][0]["candidate_id"]
        relation = {"pair_id": "p", "scope": "recent_history", "left_id": candidate_id,
                    "right_id": "published", "decision": decision, "shared_fact": None,
                    "new_fact": "new autonomous fact" if decision == "MATERIAL_UPDATE" else None,
                    "temporal_basis": "officially confirmed after publication" if decision == "MATERIAL_UPDATE" else None,
                    "scorer": {}}
        active._apply_duplicate_gate(s, [relation])
        assert bool(s["semantic_duplicate_skips"]) is eliminated
        assert bool(s["candidates"]) is not eliminated
        assert s["duplicate_gate_relations"][0]["decision"] == decision


def test_recent_history_duplicate_eliminates_entire_same_run_component(monkeypatch, tmp_path):
    def run_case(edges, history_member, winner_id, history_decision="DUPLICATE"):
        candidates = [{"candidate_id": candidate_id, "url": f"https://component.test/{candidate_id}",
                       "title": candidate_id} for candidate_id in sorted({x for edge in edges for x in edge})]
        s = {"candidates": candidates, "authorized_relations": [], "publisher_history_12h": [],
             "remaining_slots": 30, "publisher_count_rolling_24h": 0, "policy_reference": 30,
             "observed": {}, "deterministic_exact_skips": []}
        relations = [{"pair_id": f"{left}-{right}", "scope": "same_run", "left_id": left,
                      "right_id": right, "decision": "DUPLICATE", "scorer": {}}
                     for left, right in edges]
        relations.append({"pair_id": "history", "scope": "recent_history", "left_id": history_member,
                          "right_id": "published", "decision": history_decision,
                          "new_fact": "new fact" if history_decision == "MATERIAL_UPDATE" else None,
                          "temporal_basis": "confirmed later" if history_decision == "MATERIAL_UPDATE" else None,
                          "scorer": {}})
        monkeypatch.setattr(menzo, "hydrate_complete_article_bodies", lambda *_: (True, []))
        monkeypatch.setattr(menzo, "canonical_richer_winner",
                            lambda items: (next(row for row in items if row["candidate_id"] == winner_id), "test"))
        active._apply_duplicate_gate(s, relations)
        return s

    cases = [([("A", "B")], "A", "B"),
             ([("A", "B")], "B", "A"),
             ([("A", "B"), ("B", "C")], "A", "C")]
    for case_index, (edges, history_member, winner) in enumerate(cases):
        s = run_case(edges, history_member, winner)
        assert s["candidates"] == []
        eliminated = {row["candidate_id"]: row for row in s["semantic_duplicate_skips"]}
        assert eliminated[winner]["semantic_duplicate_scope"] == "recent_history"
        assert eliminated[winner]["semantic_duplicate_of"] == "published"
        assert all(row["semantic_duplicate_scope"] == "same_run"
                   for candidate_id, row in eliminated.items() if candidate_id != winner)
        from agents.canonical_artifact_index import CanonicalArtifactIndex
        root = tmp_path / str(case_index)
        index = CanonicalArtifactIndex("run", index_path=root / "index.jsonl",
            material_root=root / "materials", repository_root=tmp_path, enabled=True)
        result = {"schema_version": active.SCHEMA_VERSION, "policy_version": active.POLICY_VERSION,
                  "status": "VALIDATED", "validation_attempts": [],
                  "duplicate_gate_logical_request_id": "gate", "duplicate_gate_input_digest": "gate-digest"}
        index.observe_editorial_director_active(s, {"candidates": [],
            "relations": s["duplicate_gate_relations"]}, result)
        artifact_rows = [__import__("json").loads(line) for line in (root / "index.jsonl").read_text().splitlines()]
        assert len(artifact_rows) == len(eliminated)
        packages = [__import__("json").loads((tmp_path / row["path"]).read_text()) for row in artifact_rows]
        assert all(package["decision_authority"] == "semantic_duplicate_gate" and
                   package["director_output"] is None for package in packages)
        representative = next(package for package in packages
                              if package["candidate"]["candidate_id"] == winner)
        assert {relation["pair_id"] for relation in representative["relations"]} == {
            relation["pair_id"] for relation in s["duplicate_gate_relations"]}
        history_relation = next(relation for relation in representative["relations"]
                                if relation["scope"] == "recent_history")
        assert history_relation["left_id"] == history_member

    for decision in ("NO_MATCH", "MATERIAL_UPDATE"):
        s = run_case([("A", "B")], "A", "B", decision)
        assert [row["candidate_id"] for row in s["candidates"]] == ["B"]


def test_legacy_routing_marker_memory_is_not_binding(monkeypatch, tmp_path):
    from agents import massy_policy_v93_24 as massy
    memory = tmp_path / "hard-skips.json"
    memory.write_text('{"ttl_hours":168,"items":[{"url":"https://poison.test/a",'
                      '"reason":"requires_menzo_classification","added_at":"2099-01-01T00:00:00+00:00"}]}')
    monkeypatch.setattr(massy, "MENZO_HARD_SKIP_FILE", memory)
    assert massy.menzo_skip_memory() == {}


def test_policy_keeps_central_fact_negative_controls_explicit():
    policy = active.POLICY_PATH.read_text().lower()
    assert "title change" in policy and "title retention" in policy
    assert "mentioned as background is not a death story" in policy
    assert "weak social reactions" in policy


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
        projected = active.project(s, result)
        return (projected, menzo.load_json(menzo.SOFTPOOL_FILE, {"items": []})["items"],
                menzo.load_json(menzo.HARD_SKIP_FILE, {"items": []})["items"])

    below, below_pool, below_memory = project_action(
        "DEFER", menzo.SOFTPOOL_OUTRANKED_DEFERRALS - 1, "below")
    assert len(below["pending"]) == 1 and not below["skipped"]
    assert below_pool[0]["softpool_deferrals"] == menzo.SOFTPOOL_OUTRANKED_DEFERRALS
    assert below_memory == []

    bounded, bounded_pool, bounded_memory = project_action(
        "DEFER", menzo.SOFTPOOL_OUTRANKED_DEFERRALS, "bounded")
    assert not bounded["pending"] and not bounded_pool and len(bounded["skipped"]) == 1
    ended = bounded["skipped"][0]
    assert ended["editorial_director"]["recommended_action"] == "DEFER"
    assert ended["editorial_director"]["editorial_class"] == "PUBLISHABLE_SOFT"
    assert ended["decision_authority"] == "softpool_decay"
    assert ended["menzo_policy"]["softpool_repeatedly_outranked"] is True
    assert bounded_memory[0]["reason"] == "softpool_repeatedly_outranked"
    assert bounded_memory[0]["decision_authority"] == "softpool_decay"
    assert bounded["handoff"]["pending"] == 0 and bounded["handoff"]["skipped"] == 1

    selected, selected_pool, _ = project_action("SELECT", menzo.SOFTPOOL_OUTRANKED_DEFERRALS, "selected")
    assert len(selected["selected"]) == 1 and not selected["skipped"] and not selected_pool
    skipped, skipped_pool, skipped_memory = project_action(
        "SKIP", menzo.SOFTPOOL_OUTRANKED_DEFERRALS, "skipped")
    assert len(skipped["skipped"]) == 1 and not skipped["pending"] and not skipped_pool
    assert skipped_memory[0]["reason"] == "editorial_class_skip"


def test_active_defer_expiry_persists_binding_softpool_decay(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from agents import massy_policy_v93_24 as massy
    row = {"source": "feed", "title": "Expired candidate", "summary": "fact",
           "url": "https://decay.test/expired", "from_softpool": True,
           "softpool_added_at": (datetime.now(timezone.utc) - timedelta(
               hours=menzo.SOFTNEWS_TTL_HOURS + 1)).isoformat(), "softpool_deferrals": 0}
    s = shadow.capture_opportunity({"news_candidates_for_menzo": [row]}, run_id="run",
        observation_timestamp="now", publisher_count_24h=0, history=[])
    result = active.evaluate(s, provider=lambda *_: response(s, ("DEFER",)))
    for field in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                  "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, field, tmp_path / f"{field}.json")
    projected = active.project(s, result)
    ended = projected["skipped"][0]
    assert ended["reason"] == "softpool_expired_not_fresh"
    assert ended["decision_authority"] == "softpool_decay"
    assert ended["editorial_director"]["editorial_class"] == "PUBLISHABLE_SOFT"
    memory = menzo.load_json(menzo.HARD_SKIP_FILE, {})["items"]
    assert memory[0]["reason"] == "softpool_expired_not_fresh"
    monkeypatch.setattr(massy, "MENZO_HARD_SKIP_FILE", menzo.HARD_SKIP_FILE)
    assert massy.source_key(row["url"]) in massy.menzo_skip_memory()


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
    for row in out["candidates"]:
        row["editorial_class"] = "SHOULD_PUBLISH"
    result = active.evaluate(s, provider=lambda *_: calls.append(1) or out)
    assert len(calls) == 2 and result["validation_errors"][0]["family"] == "downstream_capacity"


def test_active_validation_counts_only_ordinary_against_bob_capacity(monkeypatch):
    monkeypatch.setattr("agents.bob.dynamic_article_capacity", lambda *_: (5, "normal"))
    for ordinary_count, valid in ((1, True), (5, True), (6, False)):
        s = snapshot(5 + ordinary_count)
        # snapshot() has only three fixtures, so construct the requested distinct survivor set.
        template = s["candidates"][0]
        s["candidates"] = [{**template, "candidate_id": f"id-{i}", "url": f"https://mixed.test/{i}"}
                           for i in range(5 + ordinary_count)]
        s["remaining_slots"] = 30
        out = {"candidates": [{"ref": f"c{i}",
            "editorial_class": "MUST_PUBLISH" if i < 5 else "SHOULD_PUBLISH",
            "recommended_action": "SELECT", "category": "WWE", "story_core": str(i)}
            for i in range(5 + ordinary_count)], "relations": []}
        canonical, failures, _ = active._validate_active(out, s)
        assert bool(canonical) is valid
        if not valid:
            assert failures[0]["ordinary_selected"] == 6


def test_actual_selected_set_not_pool_controls_post_show_capacity(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    rows = []
    for i in range(7):
        rows.append({"source": "feed", "title": (f"Raw result {i}" if i < 3 else f"General item {i}"),
                     "url": f"https://capacity.test/{i}", "summary": "distinct"})
    s = shadow.capture_opportunity({"news_candidates_for_menzo": rows}, run_id="run",
        observation_timestamp="now", publisher_count_24h=0, history=[])
    s["authorized_relations"] = []
    out = {"candidates": [{"ref": f"c{i}", "editorial_class": "SHOULD_PUBLISH",
        "recommended_action": "DEFER" if i < 3 else "SELECT", "category": "WWE", "story_core": str(i)}
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
    s["authorized_relations"] = []
    without_sidecar = __import__("copy").deepcopy(s)
    active.preserve_bob_capacity_metadata(s, rows)
    active.prepare_snapshot(s); active.prepare_snapshot(without_sidecar)
    assert (s["downstream_capacity"], s["downstream_capacity_reason"]) == (5, "normal")
    assert (without_sidecar["downstream_capacity"], without_sidecar["downstream_capacity_reason"]) == (5, "normal")
    assert s["input_digest"] == without_sidecar["input_digest"]
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


def test_bob_active_capacity_keeps_all_must_plus_ordinary_capacity(monkeypatch):
    from agents import bob
    monkeypatch.setattr(bob, "article_package", lambda item: {"id": item["id"], "status": "ready_for_alfred"})
    monkeypatch.setattr(bob, "dynamic_article_capacity", lambda *_: (5, "normal"))
    must = lambda i: {"id": f"m{i}", "editorial_director": {"editorial_class": "MUST_PUBLISH"}}
    ordinary = lambda i: {"id": f"o{i}", "editorial_director": {"editorial_class": "SHOULD_PUBLISH"}}

    six = bob.run_bob({"decision_authority": "editorial_director",
                       "selected": [must(i) for i in range(5)] + [ordinary(0)]})
    assert [row["id"] for row in six["articles"]] == [f"m{i}" for i in range(5)] + ["o0"]
    assert six["handoff"]["publishable_left_out_by_capacity"] == 0

    eleven = bob.run_bob({"decision_authority": "editorial_director",
                          "selected": [must(i) for i in range(5)] + [ordinary(i) for i in range(6)]})
    assert [row["id"] for row in eleven["articles"]] == [f"m{i}" for i in range(5)] + [f"o{i}" for i in range(5)]
    assert eleven["handoff"]["ordinary_left_out_by_capacity"] == 1
    assert eleven["handoff"]["must_left_out_by_capacity"] == 0


def test_bob_report_capacity_and_order_never_slice_late_must(monkeypatch):
    from agents import bob
    monkeypatch.setattr(bob, "article_package", lambda item: {"id": item["id"], "status": "ready_for_alfred"})
    monkeypatch.setattr(bob, "dynamic_article_capacity", lambda *_: (4, "report_run"))
    must = {"id": "must", "editorial_director": {"editorial_class": "MUST_PUBLISH"}}
    ordinary = [{"id": f"o{i}", "editorial_director": {"editorial_class": "SHOULD_PUBLISH"}}
                for i in range(6)]
    result = bob.run_bob({"decision_authority": "editorial_director",
                          "selected": ordinary + [must]})
    assert [row["id"] for row in result["articles"]] == ["o0", "o1", "o2", "o3", "must"]
    assert result["handoff"]["ordinary_left_out_by_capacity"] == 2
    assert result["handoff"]["must_left_out_by_capacity"] == 0


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
    assert package["logical_request_id"] == "lrq"
    assert "duplicate_gate_logical_request_id" not in package


def test_active_artifact_preserves_gate_and_classification_provenance(monkeypatch, tmp_path):
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(2); left, right = [row["candidate_id"] for row in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    active.prepare_snapshot(s)
    pre_gate_digest = s["input_digest"]
    def provider(prompt, *_):
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate("r0", s["candidates"][0]["title"],
                                                       s["candidates"][1]["title"], "same release")]}
        return response(s, ("SELECT",))
    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED"
    assert result["duplicate_gate_input_digest"] == pre_gate_digest
    assert result["input_digest"] == s["input_digest"] != pre_gate_digest
    assert result["logical_request_id"] != result["duplicate_gate_logical_request_id"]
    index = CanonicalArtifactIndex("run", index_path=tmp_path / "index.jsonl",
        material_root=tmp_path / "materials", repository_root=tmp_path, enabled=True)
    index.observe_editorial_director_active(s, result["output"], result)
    rows = [__import__("json").loads(line) for line in (tmp_path / "index.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    packages = [__import__("json").loads((tmp_path / row["path"]).read_text()) for row in rows]
    survivor = next(package for package in packages if package["decision_authority"] == "editorial_director")
    eliminated = next(package for package in packages if package["decision_authority"] == "semantic_duplicate_gate")
    assert survivor["logical_request_id"] == result["logical_request_id"]
    assert survivor["input_digest"] == result["input_digest"]
    assert survivor["director_output"] is not None
    assert eliminated["director_output"] is None
    assert eliminated["semantic_duplicate_scope"] == "same_run"
    assert eliminated["semantic_duplicate_of"] == survivor["candidate"]["candidate_id"]
    assert eliminated["duplicate_gate_logical_request_id"] == result["duplicate_gate_logical_request_id"]
    assert eliminated["duplicate_gate_input_digest"] == pre_gate_digest
    assert "logical_request_id" not in eliminated and "input_digest" not in eliminated
    assert eliminated["relations"][0]["decision"] == "DUPLICATE"
    assert eliminated["relations"][0]["left_evidence"]
    assert eliminated["relations"][0]["right_evidence"]
    assert eliminated["relations"][0]["centrality_basis"]
