import copy
import json
from pathlib import Path

from agents import menzo_editorial_director_shadow as ed


def snapshot(count=3):
    board = {"news_candidates_for_menzo": [
        {"source": "feed", "title": f"Story {i}", "url": f"https://v2.test/{i}",
         "summary": f"Central fact {i}", "published": "2026-09-01T00:00:00Z"}
        for i in range(count)]}
    return ed.capture_opportunity(board, run_id="run", observation_timestamp="now",
                                  publisher_count_24h=4, history=[])


def candidate(ref, cls="SHOULD_PUBLISH", action="DEFER", category="WWE", story="A fact"):
    return {"ref": ref, "editorial_class": cls, "recommended_action": action,
            "category": category, "story_core": story}


def valid(s):
    return {"candidates": [candidate(f"c{i}") for i in range(len(s["candidates"]))],
            "relations": [{"ref": f"r{i}", "decision": "NO_MATCH"}
                          for i in range(len(s["authorized_relations"]))]}


def relation_snapshot(scope="same_run"):
    s = snapshot(2)
    left, right = [x["candidate_id"] for x in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "pair_canonical", "scope": scope,
        "left_id": left, "right_id": right, "scorer_version": "v", "score": .7,
        "threshold": .55, "components": {"fact": 1}}]
    return s


def test_v2_schema_is_small_and_v1_is_retained():
    v2 = json.loads(Path("config/editorial_director_output_schema_v2.json").read_text())
    fields = set(v2["properties"]["candidates"]["items"]["properties"])
    assert fields == {"ref", "editorial_class", "recommended_action", "category", "story_core"}
    assert Path("config/editorial_director_output_schema_v1.json").exists()


def test_compact_refs_reconstruct_candidate_and_relation_identity():
    s = relation_snapshot(); output = valid(s)
    canonical, failures, _ = ed.canonicalize_output(output, s)
    assert not failures
    assert [x["candidate_id"] for x in canonical["candidates"]] == [x["candidate_id"] for x in s["candidates"]]
    relation = canonical["relations"][0]
    assert (relation["pair_id"], relation["left_id"], relation["right_id"], relation["scope"]) == (
        "pair_canonical", s["authorized_relations"][0]["left_id"], s["authorized_relations"][0]["right_id"], "same_run")


def test_exact_candidate_coverage_and_unique_refs_are_semantic_failures():
    s = snapshot(); output = valid(s); output["candidates"] = output["candidates"][:-1]
    assert "candidate_coverage" in ed.validate_output(output, s)
    output = valid(s); output["candidates"][1]["ref"] = "c0"
    assert "candidate_ref" in ed.validate_output(output, s)


def test_extra_fields_and_enum_case_are_local_not_failures():
    s = snapshot(1); output = valid(s); output["noise"] = 1
    output["candidates"][0].update(noise=True, editorial_class=" should_publish ", category=" world ")
    canonical, failures, telemetry = ed.canonicalize_output(output, s)
    assert not failures and canonical["candidates"][0]["category"] == "World"
    assert {x["family"] for x in telemetry} >= {"locally_canonicalized_extra_field", "locally_canonicalized_enum"}


def test_local_class_precedence_preserves_within_class_order_and_skip_is_unranked():
    s = snapshot(5)
    output = {"candidates": [candidate("c0", "PUBLISHABLE_SOFT", "DEFER"),
        candidate("c1", "MUST_PUBLISH", "SELECT"), candidate("c2", "SHOULD_PUBLISH", "SELECT"),
        candidate("c3", "MUST_PUBLISH", "SELECT"), candidate("c4", "SKIP", "SELECT")], "relations": []}
    canonical, failures, telemetry = ed.canonicalize_output(output, s)
    assert not failures
    assert [x["candidate_id"] for x in canonical["candidates"][:2]] == [s["candidates"][1]["candidate_id"], s["candidates"][3]["candidate_id"]]
    assert [x["relative_rank"] for x in canonical["candidates"]] == [1, 2, 3, 4, None]
    assert canonical["candidates"][-1]["recommended_action"] == "SKIP"
    assert any(x.get("detail") == "skip_invariant_overridden" for x in telemetry)


def test_action_is_diagnostic_and_soft_is_not_locally_selected():
    s = snapshot(1); output = {"candidates": [candidate("c0", "PUBLISHABLE_SOFT", "DEFER")], "relations": []}
    canonical, failures, _ = ed.canonicalize_output(output, s)
    assert not failures and canonical["candidates"][0]["recommended_action"] == "DEFER"
    del output["candidates"][0]["recommended_action"]
    canonical, failures, telemetry = ed.canonicalize_output(output, s)
    assert not failures and canonical["candidates"][0]["recommended_action"] is None
    assert any(x["family"] == "recommended_action" for x in telemetry)


def test_unauthorized_relation_is_dropped_but_missing_authorized_is_failure():
    s = relation_snapshot(); output = valid(s)
    output["relations"].append({"ref": "r99", "decision": "DUPLICATE", "shared_fact": "x"})
    canonical, failures, telemetry = ed.canonicalize_output(output, s)
    assert not failures and len(canonical["relations"]) == 1
    assert any(x.get("detail") == "unauthorized_dropped" for x in telemetry)
    output["relations"] = []
    assert "relation_coverage" in ed.validate_output(output, s)


def test_duplicate_shared_fact_and_material_update_grounding_contracts():
    s = relation_snapshot(); output = valid(s); output["relations"] = [{"ref": "r0", "decision": "DUPLICATE"}]
    assert "duplicate_shared_fact" in ed.validate_output(output, s)
    output["relations"][0]["shared_fact"] = "Same title changed hands in the same match"
    assert not ed.validate_output(output, s)
    output["relations"] = [{"ref": "r0", "decision": "MATERIAL_UPDATE", "new_fact": "New confirmation",
                            "temporal_basis": "BECAME_KNOWN_AFTER"}]
    assert "material_update_scope" in ed.validate_output(output, s)
    s = relation_snapshot("recent_history")
    output = valid(s); output["relations"] = [{"ref": "r0", "decision": "MATERIAL_UPDATE"}]
    families = ed.validate_output(output, s)
    assert {"material_update_new_fact", "material_update_temporal_basis"} <= set(families)


def test_mechanical_canonicalization_never_repairs_and_semantic_failure_repairs_once(monkeypatch):
    s = snapshot(1); ledger=[]; monkeypatch.setattr(ed, "record_gemini_attempt", lambda **kw: ledger.append(kw))
    mechanical = valid(s); mechanical["extra"] = True; mechanical["candidates"][0]["category"] = " wwe "
    calls=[]; result=ed.evaluate(s, {}, provider=lambda *_: calls.append(1) or mechanical)
    assert result["status"] == "VALIDATED" and len(calls) == 1
    broken = valid(s); del broken["candidates"][0]["category"]
    calls=[]; result=ed.evaluate(s, {}, provider=lambda *_: calls.append(1) or broken)
    assert result["status"] == "failed" and len(calls) == 2
    assert all(a["validation_families"][0]["family"] == "category" for a in result["validation_attempts"])


def test_each_missing_semantic_candidate_field_gets_maximum_one_repair(monkeypatch):
    for field, family in (("editorial_class", "editorial_class"), ("category", "category"), ("story_core", "story_core")):
        s=snapshot(1); output=valid(s); del output["candidates"][0][field]; calls=[]
        monkeypatch.setattr(ed, "record_gemini_attempt", lambda **kw: None)
        result=ed.evaluate(s, {}, provider=lambda *_: calls.append(1) or output)
        assert len(calls) == 2 and result["validation_errors"][0]["family"] == family


def test_provider_exception_is_fail_open_without_repair(monkeypatch):
    s=snapshot(1); calls=[]; monkeypatch.setattr(ed, "record_gemini_attempt", lambda **kw: None)
    def provider(*_): calls.append(1); raise TimeoutError("timeout")
    result=ed.evaluate(s, {}, provider=provider)
    assert result["status"] == "failed" and result["attempts"] == 1 and len(calls) == 1


def test_provider_input_preserves_facts_and_removes_machine_redundancy():
    s=relation_snapshot(); payload=ed.provider_input(s); serialized=json.dumps(payload)
    assert "Central fact" in serialized and "history" in payload
    assert "pair_canonical" not in serialized and '"threshold"' not in serialized and '"components"' not in serialized
    assert [x["ref"] for x in payload["candidates"]] == ["c0", "c1"]
    assert set(payload["authorized_relations"][0]) == {"ref", "scope", "left_ref", "right_ref"}
    assert "left" not in payload["authorized_relations"][0] and "right" not in payload["authorized_relations"][0]


def test_provider_input_history_has_short_refs_and_facts_exactly_once():
    history={"source_url":"https://history.test/a", "title":"Unique historical fact", "summary":"Only once",
             "published_at":"2026-09-01T00:00:00Z", "canonical_source_body":{"text":"Unique retained body"}}
    s=snapshot(1)
    captured=ed.capture_opportunity({"news_candidates_for_menzo":[s["candidates"][0]]}, run_id="run",
        observation_timestamp="now", publisher_count_24h=1, history=[history])
    payload=ed.provider_input(captured); serialized=json.dumps(payload)
    assert payload["history"][0]["ref"] == "h0" and "article_id" not in payload["history"][0]
    assert serialized.count("Unique historical fact") == 1
    assert serialized.count("Unique retained body") == 1


def test_scope_specific_endpoint_maps_cannot_collide():
    s=snapshot(2)
    shared_id=s["candidates"][0]["candidate_id"]
    s["publisher_history_12h"]=[{"article_id":shared_id, "title":"Historical copy",
                                  "source_url":s["candidates"][0]["url"]}]
    s["authorized_relations"]=[
        {"pair_id":"same", "scope":"same_run", "left_id":shared_id,
         "right_id":s["candidates"][1]["candidate_id"]},
        {"pair_id":"history", "scope":"recent_history", "left_id":shared_id, "right_id":shared_id},
    ]
    relations=ed.provider_input(s)["authorized_relations"]
    assert relations[0] == {"ref":"r0", "scope":"same_run", "left_ref":"c0", "right_ref":"c1"}
    assert relations[1] == {"ref":"r1", "scope":"recent_history", "left_ref":"c0", "right_ref":"h0"}


def test_canonical_candidate_url_variants_collapse_before_refs_relations_and_artifacts(tmp_path, monkeypatch):
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    board={"news_candidates_for_menzo":[
        {"source":"feed", "title":"First occurrence", "url":"https://www.example.com/a", "summary":"fact"},
        {"source":"feed", "title":"Duplicate occurrence", "url":"https://example.com/a", "summary":"fact"},
        {"source":"feed", "title":"Other", "url":"https://example.com/b", "summary":"other"},
    ]}
    monkeypatch.setattr(ed.menzo_duplicate_scorer, "score_pair", lambda *_: {
        "exact_duplicate":False, "above_threshold":True, "scorer_version":"test", "score":.7,
        "threshold":.55, "components":{}})
    s=ed.capture_opportunity(board, run_id="run", observation_timestamp="now", publisher_count_24h=0, history=[])
    assert len(s["candidates"]) == 2
    assert len({row["candidate_id"] for row in s["candidates"]}) == 2
    assert s["observed"]["canonical_candidate_duplicates_collapsed"] == 1
    assert [row["ref"] for row in ed.provider_input(s)["candidates"]] == ["c0", "c1"]
    assert ed.provider_input(s)["authorized_relations"][0]["left_ref"] != ed.provider_input(s)["authorized_relations"][0]["right_ref"]
    index=CanonicalArtifactIndex("run", index_path=tmp_path/"index.jsonl", material_root=tmp_path/"material",
                                 repository_root=tmp_path, enabled=True)
    monkeypatch.setattr(ed, "record_gemini_attempt", lambda **kw: None)
    result=ed.evaluate(s, {}, provider=lambda *_: valid(s), artifact_index=index)
    assert result["status"] == "VALIDATED" and len(result["output"]["candidates"]) == 2
    assert len(list((tmp_path/"material").rglob("editorial-director-shadow-*.json"))) == 2


def test_unresolved_internal_relation_avoids_provider_call():
    s=snapshot(1)
    s["authorized_relations"]=[{"pair_id":"broken", "scope":"same_run",
                                "left_id":s["candidates"][0]["candidate_id"], "right_id":"missing"}]
    finalized=ed._finalize_snapshot(s); calls=[]
    result=ed.evaluate(finalized, {}, provider=lambda *_: calls.append(1))
    assert finalized["limit_status"] == "projection_failed"
    assert result["status"] == "PROJECTION_FAILED" and result["attempts"] == 0 and calls == []
    assert "unresolved_relation_endpoint:r0:same_run" in result["projection_error"]


def test_actual_projected_provider_bytes_control_oversize_and_zero_calls(monkeypatch):
    s=relation_snapshot()
    actual_size=len(json.dumps(ed.provider_input(s), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    monkeypatch.setattr(ed, "MAX_INPUT_BYTES", actual_size - 1)
    finalized=ed._finalize_snapshot(copy.deepcopy(s))
    assert finalized["observed"]["serialized_input_bytes"] == actual_size
    assert finalized["limit_status"] == "exceeded"
    calls=[]; result=ed.evaluate(finalized, {}, provider=lambda *_: calls.append(1))
    assert result["status"] == "OVERSIZE_NOT_EVALUATED" and calls == []


def test_material_update_accepts_natural_language_temporal_grounding_without_invention():
    s=relation_snapshot("recent_history")
    natural="The promotion officially confirmed the change after the earlier article was published."
    output=valid(s); output["relations"]=[{"ref":"r0", "decision":"MATERIAL_UPDATE",
        "new_fact":"The match is now official", "temporal_basis":natural}]
    canonical,failures,_=ed.canonicalize_output(output,s)
    assert not failures and canonical["relations"][0]["temporal_basis"] == natural
    assert canonical["relations"][0]["new_fact"] == "The match is now official"
    for absent in (None, "   "):
        output["relations"][0]["temporal_basis"]=absent
        canonical,failures,_=ed.canonicalize_output(output,s)
        assert canonical is None and any(x["family"] == "material_update_temporal_basis" for x in failures)


def test_provider_output_bytes_measure_exact_raw_text_for_sdk_string_unicode_and_parse_failure(monkeypatch):
    s=snapshot(1); monkeypatch.setattr(ed, "record_gemini_attempt", lambda **kw: None)
    raw=json.dumps(valid(s), ensure_ascii=False)
    class SDKResponse:
        text=raw
    sdk=ed.evaluate(s, {}, provider=lambda *_: SDKResponse())
    assert sdk["validation_attempts"][0]["provider_output_bytes"] == len(raw.encode("utf-8"))
    unicode_raw=raw.replace("A fact", "Fatto: è così")
    direct=ed.evaluate(s, {}, provider=lambda *_: unicode_raw)
    assert direct["validation_attempts"][0]["provider_output_bytes"] == len(unicode_raw.encode("utf-8"))
    malformed="{malformed: è"
    failed=ed.evaluate(s, {}, provider=lambda *_: malformed)
    assert len(failed["validation_attempts"]) == 2
    assert all(row["provider_output_bytes"] == len(malformed.encode("utf-8")) for row in failed["validation_attempts"])
    mapping=ed.evaluate(s, {}, provider=lambda *_: valid(s))
    assert mapping["validation_attempts"][0]["provider_output_bytes"] is None
    assert mapping["validation_attempts"][0]["provider_output_bytes_available"] is False


def test_frozen_quality_corpus_has_required_exact_duplicate_evidence():
    corpus=json.loads(Path("tests/fixtures/editorial_director_v2/quality_corpus.json").read_text())
    relations={x["fixture_id"]: x for x in corpus["relations"]}
    assert relations["kofi_creed_vs_casino_gauntlet"]["gold_duplicate"] is False
    bischoff=("bischoff_sting_son_vs_moxley", "bischoff_sting_son_vs_omega_ospreay",
              "bischoff_moxley_vs_omega_ospreay")
    assert all(relations[key]["gold_duplicate"] is False and relations[key]["expected_decision"] == "NO_MATCH"
               for key in bischoff)
    assert relations["okada_international_title_change"]["gold_duplicate"] is True
    assert relations["okada_international_title_change"]["expected_decision"] == "DUPLICATE"
    assert "business_breadth_exact_labels" in corpus["owner_adjudication_required"]


def test_shadow_does_not_mutate_snapshot_or_legacy_and_model_is_fixed(monkeypatch):
    s=snapshot(1); legacy={"selected": [{"url": "https://legacy.test"}]}; before=(copy.deepcopy(s), copy.deepcopy(legacy))
    monkeypatch.setattr(ed, "record_gemini_attempt", lambda **kw: None)
    result=ed.evaluate(s, legacy, provider=lambda *_: valid(s))
    assert result["status"] == "VALIDATED" and (s, legacy) == before
    assert ed.MODEL == "gemini-3.1-flash-lite"


def test_failed_artifact_retains_attempts_without_success_event(tmp_path, monkeypatch):
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    from agents.canonical_event_ledger import CanonicalEventLedger, clear_active_ledger, install_active_ledger
    s=snapshot(1); broken=valid(s); del broken["candidates"][0]["story_core"]
    events_path=tmp_path/"events.jsonl"
    install_active_ledger(CanonicalEventLedger("run", path=events_path, enabled=True))
    index=CanonicalArtifactIndex("run", index_path=tmp_path/"index.jsonl", material_root=tmp_path/"material",
                                 repository_root=tmp_path, enabled=True)
    monkeypatch.setattr(ed, "record_gemini_attempt", lambda **kw: None)
    try:
        result=ed.evaluate(s, {}, provider=lambda *_: broken, artifact_index=index)
    finally:
        clear_active_ledger()
    package=json.loads(next((tmp_path/"material").rglob("editorial-director-shadow-*.json")).read_text())
    events=[json.loads(line) for line in events_path.read_text().splitlines()]
    assert result["status"] == "failed" and package["validation_status"] == "failed"
    assert len(package["validation_attempts"]) == 2
    assert not any(event.get("result") == "editorial_director_shadow_evaluated" for event in events)
