import json
import pytest

from agents import menzo_duplicate_recovery as recovery


def candidate(cid, title=None):
    return {"candidate_id": cid, "title": title or cid, "source": "Test",
            "summary": f"Central development for {cid}", "retained_body": f"Complete facts for {cid}"}


def relation(pair, left, right, scope="same_run", family="duplicate_centrality_contract"):
    return {"pair_id": pair, "ref": pair, "left_id": left, "right_id": right, "scope": scope,
            "failures": [{"family": family, "ref": pair}]}


def provider(triage, votes=()):
    remaining = iter(votes)
    def call(prompt, *_):
        if "MUST TRIAGE ONLY" in prompt:
            cid = next(key for key in triage if f'"candidate_id": "{key}"' in prompt)
            return {"decision": triage[cid], "reason": "binding policy"}
        vote = next(remaining)
        if isinstance(vote, Exception):
            raise vote
        payload = json.loads(prompt.split("<UNTRUSTED_SOURCE_DATA>\n", 1)[1].split(
            "\n</UNTRUSTED_SOURCE_DATA>", 1)[0])
        if isinstance(vote, dict):
            return vote
        return {"decision": vote, "reason": "central development",
                "left_evidence": payload["left"]["summary"],
                "right_evidence": payload["right"]["summary"]}
    return call


def snapshot(*ids, history=()):
    return {"candidates": [candidate(cid) for cid in ids], "publisher_history_12h": list(history),
            "authorized_relations": []}


def test_connected_components_are_relation_components():
    rows = [relation("ab", "a", "b"), relation("bc", "b", "c"), relation("de", "d", "e")]
    assert [[x["pair_id"] for x in group] for group in recovery.connected_components(rows)] == [
        ["ab", "bc"], ["de"]]


def test_zero_must_holds_component_without_jury():
    state = snapshot("a", "b", "safe")
    result = recovery.recover(state, [relation("ab", "a", "b")],
                              provider({"a": "NOT_MUST", "b": "NOT_MUST"}), "policy")
    assert result["status"] == "RECOVERED" and result["jury_calls"] == 0
    assert {x["candidate_id"] for x in state["duplicate_recovery_holds"]} == {"a", "b"}
    assert [x["candidate_id"] for x in state["candidates"]] == ["safe"]


def test_three_node_single_must_survives_without_jury():
    state = snapshot("a", "b", "c")
    result = recovery.recover(state, [relation("ab", "a", "b"), relation("bc", "b", "c")],
                              provider({"a": "NOT_MUST", "b": "MUST_PUBLISH", "c": "NOT_MUST"}), "policy")
    assert result["jury_calls"] == 0 and state["_recovery_must_ids"] == ["b"]
    assert [x["candidate_id"] for x in state["candidates"]] == ["b"]


def test_jury_majority_and_failures_do_not_manufacture_quorum():
    models = ["one", "two", "three"]
    assert recovery.jury_verdict([{"status": "valid", "vote": "DUPLICATE"},
                                  {"status": "valid", "vote": "DUPLICATE"},
                                  {"status": "valid", "vote": "UNCERTAIN"}], models) == "DUPLICATE"
    assert recovery.jury_verdict([{"status": "valid", "vote": "DUPLICATE"},
                                  {"status": "valid", "vote": "NOT_DUPLICATE"},
                                  {"status": "failed"}], models) == "UNRESOLVED"
    assert recovery.quorum(2) == 2


def test_multi_must_unresolved_uses_richer_survivor(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two,three")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (True, []))
    monkeypatch.setattr("agents.menzo_policy_v93_15.canonical_richer_winner",
                        lambda items: (next(x for x in items if x["candidate_id"] == "a"), "test"))
    state = snapshot("a", "b")
    result = recovery.recover(state, [relation("ab", "a", "b")],
        provider({"a": "MUST_PUBLISH", "b": "MUST_PUBLISH"},
                 ("DUPLICATE", "NOT_DUPLICATE", "UNCERTAIN")), "policy")
    assert result["jury_calls"] == 3 and state["_recovery_must_ids"] == ["a"]
    assert state["duplicate_recovery_holds"][0]["candidate_id"] == "b"
    assert not state.get("semantic_duplicate_skips")


def test_history_unresolved_preserves_current_must(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two,three")
    old = {**candidate("h"), "article_id": "h"}
    state = snapshot("c", history=(old,))
    result = recovery.recover(state, [relation("ch", "c", "h", "recent_history")],
        provider({"c": "MUST_PUBLISH"}, ("DUPLICATE", "MATERIAL_UPDATE_OR_AUTONOMOUS", "UNCERTAIN")), "policy")
    assert result["status"] == "RECOVERED" and state["_recovery_must_ids"] == ["c"]
    assert [x["candidate_id"] for x in state["candidates"]] == ["c"]


def test_triage_failure_requires_global_fallback():
    state = snapshot("a", "b")
    result = recovery.recover(state, [relation("ab", "a", "b")],
                              provider({"a": "MUST_PUBLISH"}), "policy")
    assert result["status"] == "GLOBAL_FALLBACK_REQUIRED"
    assert result["additional_calls"] == 2
    assert result["components"][0]["whole_run_legacy_fallback_used"] is True


def test_fabricated_and_cross_endpoint_evidence_are_invalid(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    state = snapshot("a", "b")
    fabricated = {"decision": "DUPLICATE", "reason": "same", "left_evidence": "fabricated evidence",
                  "right_evidence": "fabricated evidence"}
    result = recovery.recover(state, [relation("ab", "a", "b")],
        provider({"a": "MUST_PUBLISH", "b": "MUST_PUBLISH"}, (fabricated, fabricated)), "policy")
    votes = result["components"][0]["jury_votes"]["ab"]
    assert result["components"][0]["jury_results"]["ab"] == "UNRESOLVED"
    assert [vote["status"] for vote in votes] == ["invalid", "invalid"]
    state = snapshot("a", "b")
    cross = {"decision": "DUPLICATE", "reason": "same",
             "left_evidence": "Central development for b", "right_evidence": "Central development for a"}
    result = recovery.recover(state, [relation("ab", "a", "b")],
        provider({"a": "MUST_PUBLISH", "b": "MUST_PUBLISH"}, (cross, cross)), "policy")
    assert result["components"][0]["jury_results"]["ab"] == "UNRESOLVED"


def test_mixed_component_reconciles_same_run_and_history_edges(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    old = {**candidate("h"), "article_id": "h"}
    state = snapshot("a", "b", history=(old,))
    result = recovery.recover(state, [relation("ab", "a", "b"), relation("bh", "b", "h", "recent_history")],
        provider({"a": "MUST_PUBLISH", "b": "MUST_PUBLISH"},
                 ("NOT_DUPLICATE", "NOT_DUPLICATE", "UNCERTAIN", "UNCERTAIN")), "policy")
    component = result["components"][0]
    assert set(component["jury_results"]) == {"ab", "bh"}
    assert component["final_component_reconciliation"] == "mixed_edge_component_reconciled"
    assert set(state["_recovery_must_ids"]) == {"a", "b"}


def test_mixed_component_single_must_triaged_once_and_history_checked(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    old = {**candidate("h"), "article_id": "h"}; calls = []
    wrapped = provider({"a": "MUST_PUBLISH", "b": "NOT_MUST"}, ("UNCERTAIN",) * 4)
    def recording(*args): calls.append(args[0]); return wrapped(*args)
    state = snapshot("a", "b", history=(old,))
    result = recovery.recover(state, [relation("ab", "a", "b"), relation("ah", "a", "h", "recent_history")],
                              recording, "policy")
    assert sum("MUST TRIAGE ONLY" in prompt for prompt in calls) == 2
    assert result["components"][0]["jury_results"] == {"ab": "UNRESOLVED", "ah": "UNRESOLVED"}
    assert state["_recovery_must_ids"] == ["a"]


def test_not_duplicate_constraints_survive_unresolved_paths(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    rows = [relation("ab", "a", "b"), relation("bc", "b", "c"), relation("ac", "a", "c")]
    # Each pair consumes two votes in relation order.
    votes = ("UNCERTAIN", "UNCERTAIN", "UNCERTAIN", "UNCERTAIN", "NOT_DUPLICATE", "NOT_DUPLICATE")
    state = snapshot("a", "b", "c")
    recovery.recover(state, rows, provider({x: "MUST_PUBLISH" for x in "abc"}, votes), "policy")
    assert {"a", "c"} <= set(state["_recovery_must_ids"])


def test_duplicate_class_and_proven_autonomous_class_both_survive(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    monkeypatch.setattr("agents.menzo_policy_v93_15.canonical_richer_winner", lambda items: (items[0], "test"))
    rows = [relation("ab", "a", "b"), relation("bc", "b", "c"), relation("ac", "a", "c")]
    votes = ("DUPLICATE", "DUPLICATE", "UNCERTAIN", "UNCERTAIN", "NOT_DUPLICATE", "NOT_DUPLICATE")
    state = snapshot("a", "b", "c")
    recovery.recover(state, rows, provider({x: "MUST_PUBLISH" for x in "abc"}, votes), "policy")
    assert set(state["_recovery_must_ids"]) == {"a", "c"}
    assert state["semantic_duplicate_skips"][0]["candidate_id"] == "b"


@pytest.mark.parametrize("edge_votes,expected_survivors,expected_suppressed", [
    (("DUPLICATE", "DUPLICATE", "DUPLICATE", "DUPLICATE"), {"a"}, {"b", "c"}),
    (("DUPLICATE", "DUPLICATE", "NOT_DUPLICATE", "NOT_DUPLICATE"), {"a", "c"}, {"b"}),
    (("UNCERTAIN", "UNCERTAIN", "UNCERTAIN", "UNCERTAIN"), {"a"}, set()),
    (("NOT_DUPLICATE", "NOT_DUPLICATE", "NOT_DUPLICATE", "NOT_DUPLICATE"), {"a", "c"}, set()),
])
def test_two_must_candidates_connected_through_nonmust_are_reconciled(
        monkeypatch, edge_votes, expected_survivors, expected_suppressed):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    monkeypatch.setattr("agents.menzo_policy_v93_15.canonical_richer_winner", lambda items: (items[0], "test"))
    state = snapshot("a", "b", "c")
    result = recovery.recover(state, [relation("ab", "a", "b"), relation("bc", "b", "c")],
        provider({"a": "MUST_PUBLISH", "b": "NOT_MUST", "c": "MUST_PUBLISH"}, edge_votes), "policy")
    component = result["components"][0]
    expected_ab = edge_votes[0] if edge_votes[0] == edge_votes[1] else "UNRESOLVED"
    expected_bc = edge_votes[2] if edge_votes[2] == edge_votes[3] else "UNRESOLVED"
    assert component["jury_results"] == {
        "ab": "UNRESOLVED" if expected_ab == "UNCERTAIN" else expected_ab,
        "bc": "UNRESOLVED" if expected_bc == "UNCERTAIN" else expected_bc}
    assert set(state["_recovery_must_ids"]) == expected_survivors
    assert {row["candidate_id"] for row in state["semantic_duplicate_skips"]} == expected_suppressed
    if all(v == "UNCERTAIN" for v in edge_votes):
        assert not state["semantic_duplicate_skips"]
        assert component["unresolved_class_edges"]


def test_four_node_nonmust_bridge_juries_entire_must_connecting_subgraph(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    monkeypatch.setattr("agents.menzo_policy_v93_15.canonical_richer_winner", lambda items: (items[0], "test"))
    state = snapshot("a", "b", "c", "d")
    rows = [relation("ab", "a", "b"), relation("bc", "b", "c"), relation("cd", "c", "d")]
    result = recovery.recover(state, rows,
        provider({"a": "MUST_PUBLISH", "b": "NOT_MUST", "c": "NOT_MUST", "d": "MUST_PUBLISH"},
                 ("UNCERTAIN",) * 6), "policy")
    assert set(result["components"][0]["jury_results"]) == {"ab", "bc", "cd"}
    assert len(state["_recovery_must_ids"]) == 1
    assert not state["semantic_duplicate_skips"]


@pytest.mark.parametrize("history_votes,publishes", [
    (("DUPLICATE", "DUPLICATE"), False),
    (("MATERIAL_UPDATE_OR_AUTONOMOUS", "MATERIAL_UPDATE_OR_AUTONOMOUS"), True),
    (("UNCERTAIN", "UNCERTAIN"), True),
])
def test_history_risk_from_nonmust_member_follows_must_class_representative(
        monkeypatch, history_votes, publishes):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    old = {**candidate("h"), "article_id": "h"}
    state = snapshot("a", "b", history=(old,))
    result = recovery.recover(state, [relation("ab", "a", "b"), relation("bh", "b", "h", "recent_history")],
        provider({"a": "MUST_PUBLISH", "b": "NOT_MUST"},
                 ("DUPLICATE", "DUPLICATE", *history_votes)), "policy")
    component = result["components"][0]
    remap = component["history_class_remaps"][0]
    assert remap["representative"] == "a" and remap["history_id"] == "h"
    assert remap["original_relations"][0]["original_current_member"] == "b"
    assert remap["original_relations"][0]["original_pair_id"] == "bh"
    assert remap["original_relations"][0]["validated_same_run_duplicate_pair_ids"] == ["ab"]
    assert ("a" in state["_recovery_must_ids"]) is publishes
    if publishes:
        assert "a" not in {row["candidate_id"] for row in state["semantic_duplicate_skips"]}
        if history_votes[0] == "UNCERTAIN":
            assert state["_recovery_provenance_by_id"]["a"]["history_recovery"][0]["verdict"] == "UNRESOLVED"
    else:
        suppressed = next(row for row in state["semantic_duplicate_skips"] if row["candidate_id"] == "a")
        assert suppressed["semantic_duplicate_of"] == "h"
        assert suppressed["semantic_duplicate_history_provenance"][0]["original_relations"][0][
            "original_current_member"] == "b"


def test_history_duplicate_suppresses_one_class_but_autonomous_must_survives(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    state = snapshot("a", "b", "c", history=({**candidate("h"), "article_id": "h"},))
    rows = [relation("ab", "a", "b"), relation("bc", "b", "c"),
            relation("bh", "b", "h", "recent_history")]
    recovery.recover(state, rows, provider({"a": "MUST_PUBLISH", "b": "NOT_MUST", "c": "MUST_PUBLISH"},
        ("DUPLICATE", "DUPLICATE", "NOT_DUPLICATE", "NOT_DUPLICATE", "DUPLICATE", "DUPLICATE")), "policy")
    assert state["_recovery_must_ids"] == ["c"]
    assert {row["candidate_id"] for row in state["semantic_duplicate_skips"]} == {"a", "b"}


@pytest.mark.parametrize("first,second,publishes", [
    ("DUPLICATE", "DUPLICATE", False),
    ("DUPLICATE", "UNCERTAIN", False),
    ("DUPLICATE", "MATERIAL_UPDATE_OR_AUTONOMOUS", False),
    ("MATERIAL_UPDATE_OR_AUTONOMOUS", "UNCERTAIN", True),
])
def test_multiple_history_rule_any_valid_duplicate_is_sufficient(monkeypatch, first, second, publishes):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    history = ({**candidate("h1"), "article_id": "h1"}, {**candidate("h2"), "article_id": "h2"})
    state = snapshot("a", "b", history=history)
    rows = [relation("ab", "a", "b"), relation("ah1", "a", "h1", "recent_history"),
            relation("bh2", "b", "h2", "recent_history")]
    recovery.recover(state, rows, provider({"a": "MUST_PUBLISH", "b": "NOT_MUST"},
        ("DUPLICATE", "DUPLICATE", first, first, second, second)), "policy")
    assert ("a" in state["_recovery_must_ids"]) is publishes


def test_recovery_prompts_mark_and_delimit_untrusted_source_data(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    prompts = []; wrapped = provider({"a": "MUST_PUBLISH", "b": "MUST_PUBLISH"},
                                    ("UNCERTAIN", "UNCERTAIN"))
    def recording(prompt, *args): prompts.append(prompt); return wrapped(prompt, *args)
    recovery.recover(snapshot("a", "b"), [relation("ab", "a", "b")], recording, "policy")
    assert prompts and all("UNTRUSTED factual data" in prompt for prompt in prompts)
    assert all("<UNTRUSTED_SOURCE_DATA>" in prompt and "</UNTRUSTED_SOURCE_DATA>" in prompt
               for prompt in prompts)


def test_component_hydration_body_is_used_for_grounding(monkeypatch):
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    hydrated = "Hydrated exclusive contract signing confirmed by the promotion " * 5
    def hydrate(items):
        from agents import source_body
        for item in items:
            item["canonical_source_body"] = source_body.contract_from_elements(item.get("url", ""),
                [{"type": "text", "text": hydrated}], {"stage": "test", "extraction_finished": True,
                 "body_complete": True, "clean_element_count": 1})
        return True, [{"status": "hydrated"}]
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", hydrate)
    state = snapshot("a", "b")
    vote = {"decision": "DUPLICATE", "reason": "same", "left_evidence": "Hydrated exclusive contract signing",
            "right_evidence": "Hydrated exclusive contract signing"}
    result = recovery.recover(state, [relation("ab", "a", "b")],
        provider({"a": "MUST_PUBLISH", "b": "MUST_PUBLISH"}, (vote, vote)), "policy")
    assert result["components"][0]["body_coverage"] == {"a": "FULL_BODY", "b": "FULL_BODY"}
    assert result["components"][0]["jury_results"]["ab"] == "DUPLICATE"


def test_provider_typeerror_is_one_failed_attempt(monkeypatch):
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    calls = []
    def broken(*args): calls.append(args); raise TypeError("inside provider")
    state = snapshot("a")
    result = recovery.recover(state, [relation("ah", "a", "h", "recent_history")], broken, "policy")
    assert result["status"] == "GLOBAL_FALLBACK_REQUIRED"
    assert len(calls) == 1 and result["additional_calls"] == 1


def test_representative_remap_preserves_provenance_and_deduplicates():
    rows = [relation("bc", "b", "c"), relation("ca", "c", "a")]
    remapped, failure = recovery.remap_unresolved_relations(rows, {"a": "a", "b": "a", "c": "c"},
                                                             {"a", "c"}, set())
    assert failure is None and len(remapped) == 1
    assert remapped[0]["left_id"] == "a" and remapped[0]["right_id"] == "c"
    assert {x["pair_id"] for x in remapped[0]["merged_original_relations"]} == {"bc", "ca"}


def test_validated_duplicate_representative_remaps_following_risk(monkeypatch):
    from agents import menzo_editorial_director_active as active
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    monkeypatch.setattr("agents.menzo_policy_v93_15.canonical_richer_winner",
                        lambda items: (next(x for x in items if x["candidate_id"] == "a"), "test"))
    state = snapshot("a", "b", "c")
    mapping = active._apply_duplicate_gate(state, [{"pair_id": "ab", "scope": "same_run",
        "left_id": "a", "right_id": "b", "decision": "DUPLICATE"}])
    remapped, failure = recovery.remap_unresolved_relations(
        [relation("bc", "b", "c")], mapping,
        {x["candidate_id"] for x in state["candidates"]}, set())
    assert failure is None and mapping["b"] == "a"
    assert (remapped[0]["left_id"], remapped[0]["right_id"]) == ("a", "c")
    assert remapped[0]["original_relation"]["pair_id"] == "bc"


def test_request_identity_matches_ledger_for_success_and_failure(monkeypatch):
    ledger = []
    monkeypatch.setattr("agents.gemini_ledger.record_gemini_attempt", lambda **row: ledger.append(row))
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    state = snapshot("a", "b")
    result = recovery.recover(state, [relation("ab", "a", "b")],
                              provider({"a": "NOT_MUST", "b": "NOT_MUST"}), "policy")
    triage_rows = result["components"][0]["must_triage"]
    assert {row["logical_request_id"] for row in triage_rows.values()} == {
        row["logical_request_id"] for row in ledger}
    assert all(row["operation_id"] == row["logical_request_id"] and row["status"] == "called" for row in ledger)
    ledger.clear(); state = snapshot("a")
    def fail(*_): raise RuntimeError("provider down")
    result = recovery.recover(state, [relation("ah", "a", "h", "recent_history")], fail, "policy")
    assert result["additional_calls"] == 1
    assert ledger[0]["status"] == "failed" and ledger[0]["error_class"] == "RuntimeError"
    assert ledger[0]["operation_id"] == ledger[0]["logical_request_id"]


def test_failed_recovery_diagnostic_is_persisted_without_editorial_authority(tmp_path):
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    index = CanonicalArtifactIndex("run", index_path=tmp_path / "index.jsonl",
        material_root=tmp_path / "materials", repository_root=tmp_path, enabled=True)
    result = {"status": "failed", "policy_version": "policy",
        "duplicate_recovery": {"recovery_contract_version": recovery.CONTRACT_VERSION,
            "additional_calls": 1, "components": [{"component_id": "component",
                "duplicate_layer_whole_run_fallback_avoided": False,
                "whole_run_legacy_fallback_used": True}]}}
    index.observe_duplicate_recovery({"run_id": "run", "observation_timestamp": "now"}, result)
    files = list((tmp_path / "materials").rglob("*duplicate-recovery*.json"))
    assert len(files) == 1
    package = json.loads(files[0].read_text())
    assert package["authority"] == "diagnostic_supporting"
    assert package["component"]["whole_run_legacy_fallback_used"] is True


def test_recent_history_jury_uses_captured_canonical_body(monkeypatch):
    from agents import menzo_editorial_director_shadow as shadow, source_body
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr("agents.menzo_policy_v93_15.hydrate_complete_article_bodies", lambda items: (False, []))
    historical_text = ("Historic promotion confirmed the exclusive contract signing on Monday. " +
                       "Retained factual context for comparison remains available. " * 4)
    current_text = ("Current source confirms the exclusive contract signing happened today. " +
                    "Current retained factual context remains available for comparison. " * 4)
    contract = source_body.contract_from_elements("https://history.test/story",
        [{"type": "text", "text": historical_text}], {"stage": "test", "extraction_finished": True,
         "body_complete": True, "clean_element_count": 1})
    state = shadow.capture_opportunity({"news_candidates_for_menzo": [{"source": "feed",
        "title": "Current contract update", "url": "https://current.test/story", "summary": "Current report",
        "canonical_source_body": source_body.contract_from_elements("https://current.test/story",
            [{"type": "text", "text": current_text}], {"stage": "test", "extraction_finished": True,
             "body_complete": True, "clean_element_count": 1})}]},
        run_id="run", observation_timestamp="now", publisher_count_24h=1, history=[{
            "source_url": "https://history.test/story", "title": "Historic contract report",
            "summary": "Earlier contract report", "published_at": "2026-09-21T00:00:00Z",
            "canonical_source_body": contract}])
    cid = state["candidates"][0]["candidate_id"]; hid = state["publisher_history_12h"][0]["article_id"]
    vote = {"decision": "DUPLICATE", "reason": "same contract",
            "left_evidence": "Current source confirms the exclusive contract signing happened today",
            "right_evidence": "Historic promotion confirmed the exclusive contract signing on Monday"}
    result = recovery.recover(state, [relation("history", cid, hid, "recent_history")],
        provider({cid: "MUST_PUBLISH"}, (vote, vote)), "policy")
    component = result["components"][0]
    assert component["jury_results"]["history"] == "DUPLICATE"
    assert component["body_coverage"] == {cid: "RETAINED_BODY"}
    assert component["historical_body_coverage"] == {hid: "RETAINED_BODY"}
    assert historical_text.strip() == state["_duplicate_recovery_body_by_id"][hid]["retained_body"]
    assert "retained_body" not in state["publisher_history_12h"][0]
