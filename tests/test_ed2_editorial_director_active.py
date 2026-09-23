from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_active_duplicate_pair_cache as pair_cache
import json
import pytest


@pytest.fixture(autouse=True)
def isolated_active_pair_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(pair_cache, "CACHE_FILE", tmp_path / "active-pair-cache.json")


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


def duplicate_confirmation(ref, left_evidence, right_evidence, decision="CONFIRM_DUPLICATE"):
    return {"ref": ref, "decision": decision,
            "left_central_subject": "the central subject in the left endpoint",
            "right_central_subject": "the central subject in the right endpoint",
            "left_central_development": "the concrete development reported by the left endpoint",
            "right_central_development": "the concrete development reported by the right endpoint",
            "left_evidence": left_evidence, "right_evidence": right_evidence,
            "confirmation_basis": "The endpoints were independently compared for subject and development."}


def suspicious_relation(s, left=0, right=1, *, scope="same_run", pair_id="pair-ab"):
    right_id = (s["candidates"][right]["candidate_id"] if scope == "same_run" else
                s["publisher_history_12h"][right]["article_id"])
    return {"pair_id": pair_id, "scope": scope,
            "left_id": s["candidates"][left]["candidate_id"], "right_id": right_id,
            "scorer_version": shadow.menzo_duplicate_scorer.SCORER_VERSION,
            "score": .75, "threshold": shadow.menzo_duplicate_scorer.effective_threshold(),
            "components": {"entity_subject": 1.0}}


def no_match_relations(count):
    return {"relations": [{"ref": f"r{i}", "decision": "NO_MATCH"} for i in range(count)]}


@pytest.mark.parametrize("invalid_index", [0, 2])
def test_partition_duplicate_gate_reindexes_each_original_ref_without_losing_provenance(invalid_index):
    s = snapshot(3)
    # Three authorized rows need four endpoints, so reuse directional pairs;
    # pair identity remains authoritative and unique.
    s["authorized_relations"] = [
        suspicious_relation(s, left=0, right=1, pair_id="pair-0"),
        suspicious_relation(s, left=0, right=2, pair_id="pair-1"),
        suspicious_relation(s, left=1, right=2, pair_id="pair-2")]
    rows = [{"ref": f"r{i}", "decision": "NO_MATCH"} for i in range(3)]
    bad = s["authorized_relations"][invalid_index]
    rows[invalid_index] = grounded_duplicate(
        f"r{invalid_index}", "fabricated left evidence", "fabricated right evidence")
    valid, unresolved, global_failures = active._partition_duplicate_gate({"relations": rows}, s)
    assert global_failures == []
    assert {row["pair_id"] for row in valid} == {
        row["pair_id"] for index, row in enumerate(s["authorized_relations"]) if index != invalid_index}
    assert len(unresolved) == 1 and unresolved[0]["pair_id"] == bad["pair_id"]
    assert unresolved[0]["ref"] == f"r{invalid_index}"
    assert all(failure.get("ref") in {None, f"r{invalid_index}"}
               for failure in unresolved[0]["failures"])


def test_active_pair_cache_reuses_final_no_match_and_material_update(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    for decision in ("NO_MATCH", "MATERIAL_UPDATE"):
        pair_cache.CACHE_FILE.unlink(missing_ok=True)
        first = snapshot(2); first["authorized_relations"] = [suspicious_relation(first)]
        gate_calls = []
        def provider_one(prompt, *_):
            if "DUPLICATE GATE" in prompt:
                gate_calls.append(prompt)
                row = {"ref": "r0", "decision": decision}
                if decision == "MATERIAL_UPDATE":
                    row.update(new_fact="a later confirmed development", temporal_basis="published later")
                return {"relations": [row]}
            return response(first, ("SELECT", "DEFER"))
        if decision == "MATERIAL_UPDATE":
            first["publisher_history_12h"] = [{"article_id": "history", "title": first["candidates"][1]["title"],
                                                "published_at": "2026-01-01T00:00:00Z"}]
            first["authorized_relations"] = [suspicious_relation(first, right=0, scope="recent_history")]
        assert active.evaluate(first, provider=provider_one)["status"] == "VALIDATED"
        # evaluate mutates the first snapshot after the gate, so rebuild the equivalent input.
        second = snapshot(2)
        if decision == "MATERIAL_UPDATE":
            second["publisher_history_12h"] = [{"article_id": "history", "title": second["candidates"][1]["title"],
                                                 "published_at": "2026-01-01T00:00:00Z"}]
            second["authorized_relations"] = [suspicious_relation(second, right=0, scope="recent_history")]
        else:
            second["authorized_relations"] = [suspicious_relation(second)]
        second_calls = []
        result = active.evaluate(second, provider=lambda prompt, *_:
            second_calls.append(prompt) or response(second, ("SELECT", "DEFER")))
        assert result["status"] == "VALIDATED" and result["duplicate_pair_cache_hits"] == 1
        assert not any("DUPLICATE GATE" in prompt for prompt in second_calls)


def test_active_pair_cache_confirmed_and_rejected_duplicate_are_final(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    for confirmation_decision, expected_candidates in (("CONFIRM_DUPLICATE", 1), ("REJECT_DUPLICATE", 2)):
        pair_cache.CACHE_FILE.unlink(missing_ok=True)
        first = snapshot(2)
        first["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
        first["authorized_relations"] = [suspicious_relation(first)]
        left, right = first["candidates"][0]["title"], first["candidates"][1]["title"]
        def provider(prompt, *_):
            if "CONFIRMATION PHASE" in prompt:
                return {"confirmations": [duplicate_confirmation("d0", left, right, confirmation_decision)]}
            if "DUPLICATE GATE" in prompt:
                return {"relations": [grounded_duplicate(
                    "r0", left, right, "Jasper Troy Becomes First Confirmed Release")]}
            return response(first, tuple("SELECT" for _ in first["candidates"]))
        assert active.evaluate(first, provider=provider)["status"] == "VALIDATED"
        second = snapshot(2)
        second["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
        second["authorized_relations"] = [suspicious_relation(second)]
        prompts = []
        result = active.evaluate(second, provider=lambda prompt, *_:
            prompts.append(prompt) or response(second, tuple("SELECT" for _ in second["candidates"])))
        assert result["status"] == "VALIDATED" and len(second["candidates"]) == expected_candidates
        assert not any("DUPLICATE GATE" in prompt or "CONFIRMATION PHASE" in prompt for prompt in prompts)
        relation = result["output"]["relations"][0]
        assert relation["duplicate_confirmation"]["decision"] == confirmation_decision
        if confirmation_decision == "REJECT_DUPLICATE":
            assert relation["primary_decision"] == "DUPLICATE" and relation["decision"] == "NO_MATCH"


def test_active_pair_cache_mixed_batch_sends_only_misses_and_failure_is_atomic(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    first = snapshot(3); first["authorized_relations"] = [suspicious_relation(first)]
    active.evaluate(first, provider=lambda prompt, *_:
        no_match_relations(1) if "DUPLICATE GATE" in prompt else response(first))
    mixed = snapshot(3)
    mixed["authorized_relations"] = [suspicious_relation(mixed),
        suspicious_relation(mixed, left=0, right=2, pair_id="pair-ac")]
    gate_prompts = []
    result = active.evaluate(mixed, provider=lambda prompt, *_:
        (gate_prompts.append(prompt) or no_match_relations(1)) if "DUPLICATE GATE" in prompt else response(mixed))
    assert result["status"] == "VALIDATED" and result["duplicate_pair_cache_hits"] == 1
    assert len(gate_prompts) == 1 and '"ref":"r0"' in gate_prompts[0] and '"ref":"r1"' not in gate_prompts[0]

    failing = snapshot(3); failing["authorized_relations"] = [suspicious_relation(failing),
        suspicious_relation(failing, left=0, right=2, pair_id="pair-ad")]
    before = [row["candidate_id"] for row in failing["candidates"]]
    failed = active.evaluate(failing, provider=lambda *_: (_ for _ in ()).throw(RuntimeError("down")))
    assert failed["status"] == "PROVIDER_FAILED"
    assert [row["candidate_id"] for row in failing["candidates"]] == before
    assert "semantic_duplicate_skips" not in failing


def test_cached_no_match_constrains_local_recovery_without_rejury(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    monkeypatch.setenv("OWTV_DUPLICATE_RECOVERY_JURY_MODELS", "one,two")
    monkeypatch.setattr(menzo, "hydrate_complete_article_bodies", lambda items: (False, []))
    seed = snapshot(3)
    seed["authorized_relations"] = [suspicious_relation(seed, left=0, right=2, pair_id="pair-ac")]
    assert active.evaluate(seed, provider=lambda prompt, *_:
        no_match_relations(1) if "DUPLICATE GATE" in prompt else response(seed, ("SELECT",) * 3))["status"] == "VALIDATED"

    state = snapshot(3)
    state["authorized_relations"] = [
        suspicious_relation(state, left=0, right=1, pair_id="pair-ab"),
        suspicious_relation(state, left=1, right=2, pair_id="pair-bc"),
        suspicious_relation(state, left=0, right=2, pair_id="pair-ac")]
    ids = [row["candidate_id"] for row in state["candidates"]]
    def provider_call(prompt, *_):
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate("r0", "fabricated", "fabricated"),
                                  grounded_duplicate("r1", "fabricated", "fabricated")]}
        if "MUST TRIAGE ONLY" in prompt:
            return {"decision": "NOT_MUST" if f'"candidate_id": "{ids[1]}"' in prompt else "MUST_PUBLISH",
                    "reason": "binding policy"}
        if "PAIR-ONLY DUPLICATE RECOVERY JURY" in prompt:
            payload = json.loads(prompt.split("<UNTRUSTED_SOURCE_DATA>\n", 1)[1].split(
                "\n</UNTRUSTED_SOURCE_DATA>", 1)[0])
            return {"decision": "UNCERTAIN", "reason": "cannot resolve",
                    "left_evidence": payload["left"]["title"],
                    "right_evidence": payload["right"]["title"]}
        return response(state, ("SELECT",) * len(state["candidates"]))
    result = active.evaluate(state, provider=provider_call)
    assert result["status"] == "VALIDATED" and result["duplicate_pair_cache_hits"] == 1
    assert set(state["_recovery_must_ids"]) == {ids[0], ids[2]}
    component = result["duplicate_recovery"]["components"][0]
    assert set(component["jury_results"]) == {"pair-ab", "pair-bc"}
    assert [row["pair_id"] for row in component["validated_distinct_constraints"]] == ["pair-ac"]
    assert result["duplicate_recovery"]["additional_calls"] == 7


def test_mixed_local_failure_stores_only_independently_final_pr131_relations(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    s = snapshot(3)
    s["authorized_relations"] = [
        suspicious_relation(s, left=0, right=1, pair_id="pair-valid-0"),
        suspicious_relation(s, left=0, right=2, pair_id="pair-valid-1"),
        suspicious_relation(s, left=1, right=2, pair_id="pair-unresolved")]
    stored = []
    monkeypatch.setattr(pair_cache, "store", lambda _cache, rows: stored.extend(rows) or len(rows))
    def provider(prompt, *_):
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [{"ref": "r0", "decision": "NO_MATCH"},
                {"ref": "r1", "decision": "NO_MATCH"},
                grounded_duplicate("r2", "fabricated left evidence", "fabricated right evidence")]}
        if "MUST TRIAGE ONLY" in prompt:
            return {"decision": "NOT_MUST", "reason": "not binding MUST"}
        return response(s, tuple("SELECT" for _ in s["candidates"]))
    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED"
    assert result["duplicate_pair_cache_entries_stored"] == 2
    assert {material["identity"]["pair_id"] for material, _relation in stored} == {
        "pair-valid-0", "pair-valid-1"}
    assert "pair-unresolved" not in {material["identity"]["pair_id"] for material, _ in stored}
    assert result["duplicate_recovery"]["status"] == "RECOVERED"


def test_active_pair_cache_material_contract_ignores_aliases_but_not_evidence_or_contract():
    relation = {"pair_id": "p", "scope": "recent_history", "scorer_version": "s",
                "score": .7, "threshold": .55, "components": {"x": 1}}
    endpoints = {"left": {"ref": "c0", "title": "A", "summary": "fact"},
                 "right": {"ref": "h0", "title": "B", "published_at": "2026-01-01"}}
    base = pair_cache.pair_material(relation, endpoints, "contract-a")
    aliases = {"left": {**endpoints["left"], "ref": "c9"},
               "right": {**endpoints["right"], "ref": "h7"}}
    assert pair_cache.pair_material(relation, aliases, "contract-a") == base
    changed = __import__("copy").deepcopy(endpoints); changed["right"]["published_at"] = "2026-01-02"
    assert pair_cache.pair_material(relation, changed, "contract-a") != base
    assert pair_cache.pair_material(relation, endpoints, "contract-b") != base


def test_active_pair_cache_malformed_and_write_failure_fail_open(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    pair_cache.CACHE_FILE.write_text("{broken", encoding="utf-8")
    malformed = snapshot(2); malformed["authorized_relations"] = [suspicious_relation(malformed)]
    gate_calls = []
    result = active.evaluate(malformed, provider=lambda prompt, *_:
        (gate_calls.append(prompt) or no_match_relations(1))
        if "DUPLICATE GATE" in prompt else response(malformed, ("SELECT", "DEFER")))
    assert result["status"] == "VALIDATED" and result["duplicate_pair_cache_load_status"] == "malformed"
    assert len(gate_calls) == 1

    pair_cache.CACHE_FILE.unlink(missing_ok=True)
    monkeypatch.setattr(pair_cache, "store", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))
    write_failure = snapshot(2)
    write_failure["authorized_relations"] = [suspicious_relation(write_failure)]
    result = active.evaluate(write_failure, provider=lambda prompt, *_:
        no_match_relations(1) if "DUPLICATE GATE" in prompt else response(write_failure, ("SELECT", "DEFER")))
    assert result["status"] == "VALIDATED" and result["duplicate_pair_cache_entries_stored"] == 0


def _confirmed_duplicate_provider(s, calls, confirmation_decision="CONFIRM_DUPLICATE"):
    left, right = s["candidates"][0]["title"], s["candidates"][1]["title"]
    def provider(prompt, *_):
        if "DUPLICATE CONFIRMATION PHASE ONLY" in prompt:
            calls.append("confirmation")
            return {"confirmations": [duplicate_confirmation(
                "d0", left, right, confirmation_decision)]}
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            calls.append("gate")
            return {"relations": [grounded_duplicate(
                "r0", left, right, "Jasper Troy Becomes First Confirmed Release")]}
        calls.append("classification")
        return response(s, tuple("SELECT" for _ in s["candidates"]))
    return provider


def _duplicate_cache_snapshot():
    value = snapshot(2)
    value["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
    value["authorized_relations"] = [suspicious_relation(value)]
    return value


def test_active_pair_cache_event_registry_change_invalidates_confirmed_duplicate(
        monkeypatch, tmp_path):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    registry = tmp_path / "event_registry.json"
    original = active.EVENT_REGISTRY_PATH.read_bytes()
    registry.write_bytes(original)
    monkeypatch.setattr(active, "EVENT_REGISTRY_PATH", registry)

    first = _duplicate_cache_snapshot(); first_calls = []
    assert active.evaluate(first, provider=_confirmed_duplicate_provider(first, first_calls))["status"] == "VALIDATED"
    unchanged = _duplicate_cache_snapshot(); unchanged_calls = []
    unchanged_result = active.evaluate(
        unchanged, provider=_confirmed_duplicate_provider(unchanged, unchanged_calls))
    assert unchanged_result["duplicate_pair_cache_hits"] == 1
    assert "gate" not in unchanged_calls and "confirmation" not in unchanged_calls

    registry.write_bytes(original + b"\n")
    changed = _duplicate_cache_snapshot(); changed_calls = []
    changed_result = active.evaluate(changed, provider=_confirmed_duplicate_provider(changed, changed_calls))
    assert changed_result["status"] == "VALIDATED" and changed_result["duplicate_pair_cache_hits"] == 0
    assert changed_calls.count("gate") == 1 and changed_calls.count("confirmation") == 1


def test_active_pair_cache_missing_registry_misses_then_restore_hits(monkeypatch, tmp_path):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    registry = tmp_path / "event_registry.json"
    original = active.EVENT_REGISTRY_PATH.read_bytes()
    registry.write_bytes(original)
    monkeypatch.setattr(active, "EVENT_REGISTRY_PATH", registry)

    first = _duplicate_cache_snapshot(); first_calls = []
    assert active.evaluate(first, provider=_confirmed_duplicate_provider(first, first_calls))["status"] == "VALIDATED"
    registry.unlink()
    unavailable = _duplicate_cache_snapshot(); unavailable_calls = []
    unavailable_result = active.evaluate(
        unavailable, provider=_confirmed_duplicate_provider(unavailable, unavailable_calls))
    assert unavailable_result["status"] == "failed"
    assert unavailable_result["duplicate_pair_cache_hits"] == 0
    assert unavailable_calls.count("gate") == 2

    registry.write_bytes(original)
    restored = _duplicate_cache_snapshot(); restored_calls = []
    restored_result = active.evaluate(
        restored, provider=_confirmed_duplicate_provider(restored, restored_calls))
    assert restored_result["status"] == "VALIDATED" and restored_result["duplicate_pair_cache_hits"] == 1
    assert "gate" not in restored_calls and "confirmation" not in restored_calls


@pytest.mark.parametrize("confirmation", [None, [], "CONFIRM_DUPLICATE", 1])
@pytest.mark.parametrize("decision,primary", [
    ("DUPLICATE", None), ("NO_MATCH", "DUPLICATE")])
def test_active_pair_cache_malformed_confirmation_is_a_miss(
        confirmation, decision, primary):
    material = {"identity": {"pair_id": "malformed", "scope": "same_run",
                             "left_id": "left", "right_id": "right"},
                "endpoint_material_hash": "endpoint", "relation_contract_hash": "relation",
                "contract_fingerprint": "contract"}
    relation = {"pair_id": "malformed", "scope": "same_run", "left_id": "left",
                "right_id": "right", "decision": decision,
                "duplicate_confirmation": confirmation}
    if primary is not None:
        relation["primary_decision"] = primary
    cache = {"entries": {"malformed": {**material, "final_relation": relation}}}
    assert pair_cache.lookup(cache, material) is None


@pytest.mark.parametrize("field", ["pair_id", "scope", "left_id", "right_id"])
def test_active_pair_cache_missing_final_relation_identity_is_a_miss(field):
    material, relation = _cache_identity_fixture()
    relation.pop(field)
    cache = {"entries": {"pair": {**material, "final_relation": relation}}}
    assert pair_cache.lookup(cache, material) is None


@pytest.mark.parametrize("field,value", [
    ("pair_id", "other-pair"), ("scope", "recent_history"),
    ("left_id", "other-left"), ("right_id", "other-right"),
    ("left_id", None)])
def test_active_pair_cache_mismatched_or_malformed_final_relation_identity_is_a_miss(
        field, value):
    material, relation = _cache_identity_fixture()
    relation[field] = value
    cache = {"entries": {"pair": {**material, "final_relation": relation}}}
    assert pair_cache.lookup(cache, material) is None


def _cache_identity_fixture():
    identity = {"pair_id": "pair", "scope": "same_run",
                "left_id": "left", "right_id": "right"}
    material = {"identity": identity, "endpoint_material_hash": "endpoint",
                "relation_contract_hash": "relation", "contract_fingerprint": "contract"}
    relation = {**identity, "decision": "NO_MATCH"}
    return material, relation


def test_active_pair_cache_matching_final_relation_identity_is_a_hit():
    material, relation = _cache_identity_fixture()
    cache = {"entries": {"pair": {**material, "final_relation": relation}}}
    assert pair_cache.lookup(cache, material)["decision"] == "NO_MATCH"


def test_active_pair_cache_store_caps_oldest_and_retains_recent_hit(monkeypatch, tmp_path):
    monkeypatch.setattr(pair_cache, "MAX_ENTRIES", 2)
    recent_material = {"identity": {"pair_id": "recent", "scope": "same_run",
                                    "left_id": "left", "right_id": "right"},
                       "endpoint_material_hash": "endpoint", "relation_contract_hash": "relation",
                       "contract_fingerprint": "contract"}
    recent_relation = {"pair_id": "recent", "scope": "same_run", "left_id": "left",
                       "right_id": "right", "decision": "NO_MATCH"}
    cache = {"schema_version": pair_cache.SCHEMA_VERSION, "entries": {
        "missing-time": {"final_relation": {"decision": "NO_MATCH"}},
        "invalid-time": {"stored_at": "not-a-time", "final_relation": {"decision": "NO_MATCH"}},
        "old": {"stored_at": "2020-01-01T00:00:00+00:00", "final_relation": {"decision": "NO_MATCH"}},
        "recent": {**recent_material, "stored_at": "2026-01-01T00:00:00+00:00",
                   "final_relation": recent_relation},
    }}
    new_material = {"identity": {"pair_id": "new", "scope": "same_run",
                                 "left_id": "new-left", "right_id": "new-right"},
                    "endpoint_material_hash": "new-endpoint", "relation_contract_hash": "new-relation",
                    "contract_fingerprint": "contract"}
    target = tmp_path / "bounded-cache.json"
    pair_cache.store(cache, [(new_material, {
        "pair_id": "new", "scope": "same_run", "left_id": "new-left",
        "right_id": "new-right", "decision": "NO_MATCH"})], target)
    serialized = __import__("json").loads(target.read_text(encoding="utf-8"))
    assert len(serialized["entries"]) == pair_cache.MAX_ENTRIES
    assert set(serialized["entries"]) == {"recent", "new"}
    assert pair_cache.lookup(serialized, recent_material)["decision"] == "NO_MATCH"


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
    s["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
    left, right = [x["candidate_id"] for x in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate("r0", s["candidates"][0]["title"],
                                                       s["candidates"][1]["title"],
                                                       "Jasper Troy Becomes First Confirmed Release")]}
        if "DUPLICATE CONFIRMATION PHASE ONLY" in prompt:
            return {"confirmations": [duplicate_confirmation(
                "d0", s["candidates"][0]["title"], s["candidates"][1]["title"])]}
        return response(s, ("SELECT",))
    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED" and len(calls) == 3
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
    assert not any(kwargs.get("model_role") == "editorial_director_duplicate_confirmation"
                   for _, kwargs in events)


def _two_candidate_relation_snapshot(left_title, right_title):
    s = _anchor_contract_snapshot(left_title, right_title)
    s["authorized_relations_complete"] = True
    return s


def test_confirmation_rejects_shared_promotion_wording_without_binding(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    left = "New Japan Pro Wrestling Signs Mercedes Mone"
    right = "New Japan Pro Wrestling Signs Kazuchika Okada"
    s = _two_candidate_relation_snapshot(left, right)
    calls = []

    def provider(prompt, *_):
        calls.append(prompt)
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate(
                "r0", left, right, "New Japan Pro Wrestling signs a wrestler")]}
        if "DUPLICATE CONFIRMATION PHASE ONLY" in prompt:
            assert "score" not in prompt and "threshold" not in prompt
            return {"confirmations": [duplicate_confirmation(
                "d0", left, right, "REJECT_DUPLICATE")]}
        return response(s, ("SELECT", "DEFER"))

    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED" and len(calls) == 3
    assert len(s["candidates"]) == 2 and not s["semantic_duplicate_skips"]
    relation = result["output"]["relations"][0]
    assert relation["primary_decision"] == "DUPLICATE"
    assert relation["decision"] == "NO_MATCH"
    assert relation["duplicate_confirmation"]["decision"] == "REJECT_DUPLICATE"
    assert result["duplicate_confirmation_logical_request_id"] != result["duplicate_gate_logical_request_id"]
    assert result["duplicate_confirmation_input_digest"] != result["duplicate_gate_input_digest"]


def test_confirmation_rejects_background_title_change_reaction(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    left = "Triple H Reacts To Stephanie Vaquer Winning Women's World Title"
    right = "Stephanie Vaquer Wins Women's World Title At WWE Live Event"
    s = _two_candidate_relation_snapshot(left, right)

    def provider(prompt, *_):
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate(
                "r0", left, right, "Stephanie Vaquer winning Women's World Title")]}
        if "DUPLICATE CONFIRMATION PHASE ONLY" in prompt:
            return {"confirmations": [duplicate_confirmation(
                "d0", left, right, "REJECT_DUPLICATE")]}
        return response(s, ("SELECT", "DEFER"))

    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED"
    assert len(s["candidates"]) == 2 and not s["semantic_duplicate_skips"]


def test_confirmation_provider_failure_is_atomic(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    left = "Jasper Troy signs a new WWE contract today"
    right = "Jasper Troy signs a new WWE contract today again"
    s = _two_candidate_relation_snapshot(left, right)

    def provider(prompt, *_):
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate(
                "r0", left, right, "Jasper Troy signs a new WWE contract today")]}
        raise TimeoutError("confirmation unavailable")

    result = active.evaluate(s, provider=provider)
    assert result["status"] == "PROVIDER_FAILED"
    assert result["duplicate_confirmation_logical_request_id"]
    assert len(s["candidates"]) == 2 and "semantic_duplicate_skips" not in s


def test_invalid_confirmation_repairs_once_then_confirms(monkeypatch):
    ledger = []
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **kwargs: ledger.append(kwargs))
    left = "Jasper Troy signs a new WWE contract today"
    right = "Jasper Troy signs a new WWE contract today again"
    s = _two_candidate_relation_snapshot(left, right)
    confirmation_attempt = 0

    def provider(prompt, *_):
        nonlocal confirmation_attempt
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate(
                "r0", left, right, "Jasper Troy signs a new WWE contract today")]}
        if "DUPLICATE CONFIRMATION PHASE ONLY" in prompt:
            confirmation_attempt += 1
            if confirmation_attempt == 1:
                return {"confirmations": []}
            return {"confirmations": [duplicate_confirmation("d0", left, right)]}
        return response(s, ("SELECT",))

    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED" and confirmation_attempt == 2
    confirmation_ledger = [row for row in ledger
                           if row["workload"] == "editorial_director_duplicate_confirmation"]
    assert [row["repair"] for row in confirmation_ledger] == [False, True]
    attempts = [row for row in result["validation_attempts"]
                if row.get("phase") == "duplicate_confirmation"]
    assert [row["valid"] for row in attempts] == [False, True]


def test_repeated_invalid_confirmation_fails_atomically(monkeypatch):
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    left = "Jasper Troy signs a new WWE contract today"
    right = "Jasper Troy signs a new WWE contract today again"
    s = _two_candidate_relation_snapshot(left, right)
    confirmation_calls = 0

    def provider(prompt, *_):
        nonlocal confirmation_calls
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate(
                "r0", left, right, "Jasper Troy signs a new WWE contract today")]}
        confirmation_calls += 1
        return {"confirmations": []}

    result = active.evaluate(s, provider=provider)
    assert result["status"] == "failed" and confirmation_calls == 4
    assert result["fallback_reason"] == "duplicate_recovery_triage_failed"
    assert len(s["candidates"]) == 2 and "semantic_duplicate_skips" not in s


def test_multiple_duplicates_use_one_batched_confirmation_request(monkeypatch):
    ledger = []
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **kwargs: ledger.append(kwargs))
    titles = [
        "Jasper Troy signs a new WWE contract today",
        "Jasper Troy signs a new WWE contract today again",
        "Stephanie Vaquer wins the WWE championship tonight",
        "Stephanie Vaquer wins the WWE championship tonight in Chile",
    ]
    s = shadow.capture_opportunity({"news_candidates_for_menzo": [
        {"title": title, "summary": title, "url": f"https://batch.test/{index}"}
        for index, title in enumerate(titles)]}, run_id="confirmation-batch",
        observation_timestamp="now", publisher_count_24h=0, history=[])
    ids = [row["candidate_id"] for row in s["candidates"]]
    s["authorized_relations"] = [
        {"pair_id": f"batch-{index}", "scope": "same_run", "left_id": ids[index * 2],
         "right_id": ids[index * 2 + 1], "scorer_version": "test", "score": .9,
         "threshold": .55, "components": {}} for index in range(2)]
    s["authorized_relations_complete"] = True

    def provider(prompt, *_):
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [
                grounded_duplicate("r0", titles[0], titles[1],
                                   "Jasper Troy signs a new WWE contract today"),
                grounded_duplicate("r1", titles[2], titles[3],
                                   "Stephanie Vaquer wins the WWE championship tonight"),
            ]}
        if "DUPLICATE CONFIRMATION PHASE ONLY" in prompt:
            return {"confirmations": [
                duplicate_confirmation("d0", titles[0], titles[1]),
                duplicate_confirmation("d1", titles[2], titles[3]),
            ]}
        return response(s, ("SELECT", "DEFER"))

    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED" and len(s["candidates"]) == 2
    confirmation_calls = [row for row in ledger
                          if row["workload"] == "editorial_director_duplicate_confirmation"]
    assert len(confirmation_calls) == 1 and confirmation_calls[0]["relation_count"] == 2


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
    assert result["status"] == "failed" and len(calls) == 3
    assert result["fallback_reason"] == "duplicate_recovery_triage_failed"
    assert "semantic_duplicate_skips" not in s and len(s["candidates"]) == 1
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    index = CanonicalArtifactIndex("incident", index_path=tmp_path / "index.jsonl",
        material_root=tmp_path / "materials", repository_root=tmp_path, enabled=True)
    assert index.summary()["artifacts_archived"] == 0 and not (tmp_path / "index.jsonl").exists()


def test_duplicate_evidence_cannot_cross_relation_endpoints():
    board = {"news_candidates_for_menzo": [
        {"title": "Alpha Wrestler signs a new contract", "url": "https://cross.test/a", "summary": "Alpha Wrestler signs"},
        {"title": "Beta Wrestler returns at the arena", "url": "https://cross.test/b", "summary": "Beta Wrestler returns"}]}
    history = [
        {"source_title": "Alpha Wrestler signs a new contract", "source_url": "https://cross.test/ha"},
        {"source_title": "Beta Wrestler returns at the arena", "source_url": "https://cross.test/hb"}]
    s = shadow.capture_opportunity(board, run_id="cross", observation_timestamp="now",
        publisher_count_24h=0, history=history)
    candidate_ids = [row["candidate_id"] for row in s["candidates"]]
    history_ids = [row["article_id"] for row in s["publisher_history_12h"]]
    s["authorized_relations"] = [
        {"pair_id": "p0", "scope": "recent_history", "left_id": candidate_ids[0],
         "right_id": history_ids[0], "scorer_version": "v", "score": .7, "threshold": .55, "components": {}},
        {"pair_id": "p1", "scope": "recent_history", "left_id": candidate_ids[1],
         "right_id": history_ids[1], "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    rows = [grounded_duplicate("r0", "Alpha Wrestler signs a new contract",
                               "Alpha Wrestler signs a new contract",
                               "Alpha Wrestler signs a new contract"),
            grounded_duplicate("r1", "Alpha Wrestler signs a new contract",
                               "Beta Wrestler returns at the arena",
                               "Beta Wrestler returns at the arena")]
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

    confirmation_schema = json.loads(active.CONFIRMATION_SCHEMA_PATH.read_text())
    assert schema_keywords(confirmation_schema).isdisjoint(unsupported)
    item = confirmation_schema["properties"]["confirmations"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["properties"]["decision"]["enum"]) == {
        "CONFIRM_DUPLICATE", "REJECT_DUPLICATE"}
    assert {"ref", "decision", *active.CONFIRMATION_FIELDS} == set(item["required"])


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


def _anchor_contract_snapshot(left_title, right_title):
    s = shadow.capture_opportunity({"news_candidates_for_menzo": [
        {"title": left_title, "summary": left_title, "url": "https://anchor.test/left"},
        {"title": right_title, "summary": right_title, "url": "https://anchor.test/right"}]},
        run_id="anchor", observation_timestamp="now", publisher_count_24h=0, history=[])
    left_id, right_id = [row["candidate_id"] for row in s["candidates"]]
    s["authorized_relations"] = [{"pair_id": "anchor-pair", "scope": "same_run",
        "left_id": left_id, "right_id": right_id, "scorer_version": "test", "score": .9,
        "threshold": .55, "components": {}}]
    return s


def _validate_anchor_relation(s, *, left_evidence, right_evidence, shared_fact,
                              left_central=None, right_central=None):
    relation = grounded_duplicate("r0", left_evidence, right_evidence, shared_fact)
    relation["left_central_development"] = left_central or shared_fact
    relation["right_central_development"] = right_central or shared_fact
    return active._validate_duplicate_gate({"relations": [relation]}, s)


def test_generic_common_evidence_has_no_binding_subject_anchor():
    fixtures = [
        ("More Details On CM Punk Contract Talks", "More Details On Rhea Ripley Injury Status", "More Details"),
        ("Live Event Update On CM Punk", "Live Event Update On Rhea Ripley", "Live Event"),
        ("WrestleMania Main Event Adds Seth Rollins Match",
         "WrestleMania Main Event Announces Roman Reigns Match", "WrestleMania Main"),
        ("SummerSlam Main Event Adds Seth Rollins Match",
         "SummerSlam Main Event Announces Roman Reigns Match", "SummerSlam Main"),
        ("WrestleMania Night One Adds Seth Rollins Match",
         "WrestleMania Night One Announces Roman Reigns Match", "Night One"),
        ("Night Two Update On CM Punk", "Night Two Update On Rhea Ripley", "Night Two"),
        ("Day One Update On CM Punk", "Day One Update On Rhea Ripley", "Day One"),
        ("Part One Update On CM Punk", "Part One Update On Rhea Ripley", "Part One"),
    ]
    for left, right, phrase in fixtures:
        s = _anchor_contract_snapshot(left, right)
        canonical, failures, _ = _validate_anchor_relation(s, left_evidence=phrase,
            right_evidence=phrase, shared_fact=f"{phrase} reported")
        assert canonical is None
        assert any(row["family"] == "duplicate_relation_anchor_grounding" and
                   row["detail"] == "no_shared_explicit_subject" for row in failures)


def test_registered_event_aliases_cannot_bind_as_subjects():
    fixtures = (
        ("AEW Grand Slam", "Grand Slam"),
        ("AEW Forbidden Door", "Forbidden Door"),
        ("AEW Full Gear", "Full Gear"),
        ("AEW Beach Break", "Beach Break"),
        ("TNA Victory Road", "Victory Road"),
        ("ROH Final Battle", "Final Battle"),
    )
    for event_prefix, event_anchor in fixtures:
        left = f"{event_prefix} Adds Kenny Omega Match"
        right = f"{event_prefix} Announces Jon Moxley Match"
        s = _anchor_contract_snapshot(left, right)
        canonical, failures, _ = _validate_anchor_relation(
            s, left_evidence=left, right_evidence=right,
            shared_fact=f"{event_anchor} announces a wrestling match",
            left_central=f"{event_anchor} adds a wrestling match",
            right_central=f"{event_anchor} announces a wrestling match")
        assert canonical is None
        assert any(row["family"] == "duplicate_relation_anchor_grounding" and
                   row["detail"] == "no_shared_explicit_subject" for row in failures)


def test_registered_event_span_preserves_wrestler_subjects():
    phrases = active._registered_event_phrases()
    subjects = active._explicit_endpoint_subjects(
        {"title": "AEW Grand Slam Adds Kenny Omega Match"}, phrases)
    assert "grand slam" not in subjects
    assert "kenny omega" in subjects


def test_registered_event_boundary_compounds_cannot_bind():
    phrases = active._registered_event_phrases()
    left = "AEW Grand Slam Results: Kenny Omega Wins Title"
    right = "AEW Grand Slam Results: Jon Moxley Wins Match"
    left_subjects = active._explicit_endpoint_subjects({"title": left}, phrases)
    right_subjects = active._explicit_endpoint_subjects({"title": right}, phrases)
    assert "grand slam" not in left_subjects
    assert "slam results" not in left_subjects
    assert "kenny omega" in left_subjects
    assert "jon moxley" in right_subjects

    snapshot = _anchor_contract_snapshot(left, right)
    canonical, failures, _ = _validate_anchor_relation(
        snapshot, left_evidence=left, right_evidence=right,
        shared_fact="Grand Slam Results report wrestling wins",
        left_central="Grand Slam Results report Kenny Omega wins",
        right_central="Grand Slam Results report Jon Moxley wins")
    assert canonical is None
    assert any(row["family"] == "duplicate_relation_anchor_grounding" and
               row["detail"] == "no_shared_explicit_subject" for row in failures)


def test_event_registry_failure_rejects_duplicate_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(active, "EVENT_REGISTRY_PATH", tmp_path / "missing-event-registry.json")
    left = "Stephanie Vaquer wins the championship tonight"
    right = "Stephanie Vaquer wins the championship tonight in Chile"
    s = _anchor_contract_snapshot(left, right)
    canonical, failures, _ = _validate_anchor_relation(
        s, left_evidence=left, right_evidence=right,
        shared_fact="Stephanie Vaquer wins the championship tonight")
    assert canonical is None
    assert ("duplicate_event_registry_grounding", "registry_unavailable") in {
        (row["family"], row.get("detail")) for row in failures}


def test_generic_championship_compound_cannot_bind_full_title_evidence():
    left = "Women's World Championship: Rhea Ripley wins title"
    right = "Women's World Championship: Iyo Sky wins title"
    s = _anchor_contract_snapshot(left, right)
    canonical, failures, _ = _validate_anchor_relation(s, left_evidence=left,
        right_evidence=right, shared_fact="Women's World Championship title win",
        left_central="Women's World Championship Rhea Ripley title win",
        right_central="Women's World Championship Iyo Sky title win")
    assert canonical is None
    assert any(row["family"] == "duplicate_relation_anchor_grounding" and
               row["detail"] == "no_shared_explicit_subject" for row in failures)
    assert not s.get("semantic_duplicate_skips")


def test_canonical_apostrophe_anchor_validates_across_endpoint_forms():
    left = "Kevin O'Reilly signs a new WWE contract"
    right = "Kevin O’Reilly signs a new WWE contract"
    s = _anchor_contract_snapshot(left, right)
    canonical, failures, _ = _validate_anchor_relation(s, left_evidence=left,
        right_evidence=right, shared_fact="Kevin O'Reilly signs a new contract")
    assert canonical is not None and not failures


def test_connector_boilerplate_cannot_bind_unrelated_headlines():
    left = "WWE Hall Of Famer Trish Stratus Comments On Becky Lynch"
    right = "WWE Hall Of Famer Hulk Hogan Comments On Donald Trump"
    s = _anchor_contract_snapshot(left, right)
    canonical, failures, _ = _validate_anchor_relation(s, left_evidence=left,
        right_evidence=right, shared_fact="Hall Of Famer comments on public figures",
        left_central="Hall Of Famer Trish Stratus comments on Becky Lynch",
        right_central="Hall Of Famer Hulk Hogan comments on Donald Trump")
    assert canonical is None
    assert any(row["family"] == "duplicate_relation_anchor_grounding" and
               row["detail"] == "no_shared_explicit_subject" for row in failures)


def test_diacritic_canonical_anchor_validates_and_is_fully_subtracted():
    left = "Mercedes Moné wins the world championship tonight"
    right = "Mercedes Mone wins the world championship tonight"
    s = _anchor_contract_snapshot(left, right)
    canonical, failures, _ = _validate_anchor_relation(s, left_evidence=left,
        right_evidence=right, shared_fact="Mercedes Mone wins the world championship tonight")
    assert canonical is not None and not failures
    assert active._non_anchor_lexical_overlap(
        "Mercedes Moné alpha", "Mercedes Mone beta", "mercedes mone") == 0


def test_leading_article_stage_name_fails_open_without_identity_exception():
    left = "The Rock returns to WWE after long absence"
    right = "The Rock returns to WWE after long absence"
    s = _anchor_contract_snapshot(left, right)
    canonical, failures, _ = _validate_anchor_relation(s, left_evidence=left,
        right_evidence=right, shared_fact="The Rock returns to WWE after long absence")
    assert canonical is None
    assert any(row["family"] == "duplicate_relation_anchor_grounding" and
               row["detail"] == "no_shared_explicit_subject" for row in failures)


def test_retained_body_capitalization_cannot_supply_binding_anchor():
    s = _anchor_contract_snapshot("CM Punk Signs New WWE Contract", "Rhea Ripley Suffers New Injury")
    for candidate, body in zip(s["candidates"], (
            "According to sources, the agreement was finalized yesterday.",
            "According to sources, medical tests were performed yesterday.")):
        candidate["retained_body"] = body
    canonical, failures, _ = _validate_anchor_relation(s,
        left_evidence="According to sources", right_evidence="According to sources",
        shared_fact="According to sources reported")
    assert canonical is None
    assert any(row["family"] == "duplicate_relation_anchor_grounding" and
               row["detail"] == "no_shared_explicit_subject" for row in failures)
    assert "according to" not in active._explicit_endpoint_subjects(
        {"title": "CM Punk Signs New WWE Contract", "retained_body": "According to sources"})


def test_shared_subject_elsewhere_does_not_rescue_generic_evidence():
    s = _anchor_contract_snapshot(
        "Stephanie Vaquer wins the world title", "Stephanie Vaquer captures the world title")
    canonical, failures, _ = _validate_anchor_relation(s, left_evidence="world title",
        right_evidence="world title", shared_fact="Stephanie Vaquer wins the title")
    assert canonical is None
    grounding = {(row["family"], row.get("detail")) for row in failures}
    assert ("duplicate_left_evidence_grounding", "missing_shared_subject_anchor") in grounding
    assert ("duplicate_right_evidence_grounding", "missing_shared_subject_anchor") in grounding


def test_shared_fact_and_central_developments_link_to_evidence_anchor():
    s = _anchor_contract_snapshot(
        "Stephanie Vaquer won the championship", "Stephanie Vaquer captured the championship")
    valid, failures, _ = _validate_anchor_relation(s,
        left_evidence="Stephanie Vaquer won the championship",
        right_evidence="Stephanie Vaquer captured the championship",
        shared_fact="Stephanie Vaquer won the championship")
    assert valid is not None and not failures

    invalid_claim, failures, _ = _validate_anchor_relation(s,
        left_evidence="Stephanie Vaquer won the championship",
        right_evidence="Stephanie Vaquer captured the championship",
        shared_fact="An unrelated championship claim")
    assert invalid_claim is None
    assert any(row["family"] == "duplicate_claim_anchor_grounding" and
               row["detail"] == "missing_shared_subject_anchor" for row in failures)

    punk = _anchor_contract_snapshot("CM Punk won the championship", "CM Punk captured the championship")
    invalid_central, failures, _ = _validate_anchor_relation(punk,
        left_evidence="CM Punk won the championship", right_evidence="CM Punk captured the championship",
        shared_fact="CM Punk won the championship", right_central="Unrelated controversy")
    assert invalid_central is None
    assert any(row["family"] == "duplicate_centrality_contract" and
               "missing_shared_subject_anchor" in row.get("details", []) for row in failures)


def test_anchor_tokens_do_not_count_as_factual_linkage():
    s = _anchor_contract_snapshot(
        "John Cena criticizes his retirement match", "John Cena praises Cody Rhodes")
    canonical, failures, _ = _validate_anchor_relation(s,
        left_evidence="John Cena criticizes his retirement match",
        right_evidence="John Cena praises Cody Rhodes", shared_fact="John Cena makes comments")
    assert canonical is None
    details = {(row["family"], row.get("detail")) for row in failures}
    assert ("duplicate_claim_anchor_grounding",
            "insufficient_left_evidence_factual_linkage") in details
    assert ("duplicate_claim_anchor_grounding",
            "insufficient_right_evidence_factual_linkage") in details

    central_snapshot = _anchor_contract_snapshot(
        "John Cena discusses his retirement match", "John Cena discusses his retirement match")
    canonical, failures, _ = _validate_anchor_relation(central_snapshot,
        left_evidence="John Cena discusses his retirement match",
        right_evidence="John Cena discusses his retirement match",
        shared_fact="John Cena discusses retirement match",
        right_central="John Cena unrelated statement")
    assert canonical is None
    assert any(row["family"] == "duplicate_centrality_contract" and
               "insufficient_evidence_factual_linkage" in row.get("details", []) for row in failures)


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
               "title": "Jasper Troy release confirmed earlier", "input_coverage": "RSS_SUMMARY_ONLY"}
    s["publisher_history_12h"] = [history]
    s["authorized_relations"] = [{"pair_id": "p", "scope": "recent_history",
        "left_id": candidate_id, "right_id": "published", "scorer_version": "v", "score": .7,
        "threshold": .55, "components": {}}]
    def provider(prompt, *_):
        if "DUPLICATE CONFIRMATION PHASE ONLY" in prompt:
            return {"confirmations": [duplicate_confirmation(
                "d0", s["candidates"][0]["title"], history["title"])]}
        return {"relations": [grounded_duplicate(
            "r0", s["candidates"][0]["title"], history["title"], "Jasper Troy release confirmed")]}
    result = active.evaluate(s, provider=provider)
    assert result["status"] == "VALIDATED" and len(ledger) == 2
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


def test_duplicate_recovery_hold_is_nonterminal_and_preserves_existing_softpool(monkeypatch, tmp_path):
    from agents.canonical_event_ledger import CanonicalEventLedger
    held = {"source": "feed", "title": "Temporarily held", "summary": "Central factual development",
        "url": "https://hold.test/story", "from_softpool": True,
        "decision_authority": "editorial_director",
        "editorial_director": {"recommended_action": "DEFER"}}
    s = {"candidates": [], "duplicate_recovery_holds": [{**held, "candidate_id": "held-id"}],
         "deterministic_exact_skips": [], "semantic_duplicate_skips": []}
    result = {"output": {"candidates": [], "relations": []}}
    for field in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                  "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, field, tmp_path / f"{field}.json")
    menzo.write_json(menzo.SOFTPOOL_FILE, {"items": [held]})
    projected = active.project(s, result)
    assert not projected["selected"] and not projected["pending"] and not projected["skipped"]
    assert projected["held"][0]["decision"] == "hold"
    assert held["url"] not in projected["allowed_urls_for_v92"]
    assert menzo.load_json(menzo.HARD_SKIP_FILE, {"items": []})["items"] == []
    assert [row["url"] for row in menzo.load_json(menzo.SOFTPOOL_FILE, {"items": []})["items"]] == [held["url"]]
    ledger = CanonicalEventLedger("run", path=tmp_path / "events.jsonl", enabled=True)
    ledger.observe_menzo(projected)
    events = [__import__("json").loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()] \
        if (tmp_path / "events.jsonl").exists() else []
    assert not any(row["event_type"] == "candidate_skipped" for row in events)
    assert projected["handoff"] == {"to_bob_or_v92": 0, "pending": 0, "skipped": 0,
                                    "decision_authority": "editorial_director"}


def test_active_artifacts_preserve_duplicate_gate_and_recovery_authority(tmp_path):
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    ordinary = {"candidate_id": "gate-id", "url": "https://duplicate.test/gate",
                "title": "Ordinary duplicate", "semantic_duplicate_scope": "same_run"}
    recovered = {"candidate_id": "recovery-id", "url": "https://duplicate.test/recovery",
                 "title": "Recovery duplicate", "semantic_duplicate_scope": "same_run_recovery",
                 "semantic_duplicate_authority": "validated_jury"}
    snapshot = {"candidates": [], "semantic_duplicate_skips": [ordinary, recovered]}
    result = {"schema_version": active.SCHEMA_VERSION, "policy_version": active.POLICY_VERSION,
              "status": "VALIDATED", "validation_attempts": []}
    index = CanonicalArtifactIndex("run", index_path=tmp_path / "index.jsonl",
        material_root=tmp_path / "materials", repository_root=tmp_path, enabled=True)
    index.observe_editorial_director_active(snapshot, {"candidates": [], "relations": []}, result)
    rows = [json.loads(line) for line in (tmp_path / "index.jsonl").read_text().splitlines()]
    packages = [json.loads((tmp_path / row["path"]).read_text()) for row in rows]
    authority_by_id = {package["candidate"]["candidate_id"]: package["decision_authority"]
                       for package in packages}
    assert authority_by_id == {"gate-id": "semantic_duplicate_gate",
                               "recovery-id": "semantic_duplicate_recovery"}


@pytest.mark.parametrize("scope", ["same_run_recovery", "recent_history_recovery"])
def test_validated_recovery_duplicate_is_terminal_hard_skip_with_distinct_authority(
        monkeypatch, tmp_path, scope):
    duplicate = {"candidate_id": "duplicate-id", "source": "feed", "title": "Validated duplicate",
        "summary": "same central development", "url": f"https://recovery-skip.test/{scope}",
        "semantic_duplicate_scope": scope, "semantic_duplicate_of": "covered-id",
        "semantic_duplicate_authority": "validated_jury"}
    s = {"candidates": [], "duplicate_recovery_holds": [], "deterministic_exact_skips": [],
         "semantic_duplicate_skips": [duplicate]}
    result = {"output": {"candidates": [], "relations": []}}
    for field in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                  "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, field, tmp_path / f"{field}.json")
    projected = active.project(s, result)
    assert projected["skipped"][0]["decision_authority"] == "semantic_duplicate_recovery"
    memory_file = menzo.load_json(menzo.HARD_SKIP_FILE, {})
    assert memory_file["ttl_hours"] == menzo.HARD_SKIP_TTL_HOURS
    assert len(memory_file["items"]) == 1
    stored = memory_file["items"][0]
    assert stored["decision_authority"] == "semantic_duplicate_recovery"
    assert stored["expires_after_hours"] == menzo.HARD_SKIP_TTL_HOURS
    assert stored["reason"] == f"semantic_{scope}_duplicate"


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
    s["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
    s["authorized_relations"] = [{"pair_id": "p", "scope": "same_run", "left_id": left,
        "right_id": right, "scorer_version": "v", "score": .7, "threshold": .55, "components": {}}]
    active.prepare_snapshot(s)
    pre_gate_digest = s["input_digest"]
    def provider(prompt, *_):
        if "DUPLICATE GATE PHASE ONLY" in prompt:
            return {"relations": [grounded_duplicate("r0", s["candidates"][0]["title"],
                                                       s["candidates"][1]["title"],
                                                       "Jasper Troy Becomes First Confirmed Release")]}
        if "DUPLICATE CONFIRMATION PHASE ONLY" in prompt:
            return {"confirmations": [duplicate_confirmation(
                "d0", s["candidates"][0]["title"], s["candidates"][1]["title"])]}
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
    assert eliminated["duplicate_confirmation_logical_request_id"] == (
        result["duplicate_confirmation_logical_request_id"])
    assert eliminated["duplicate_confirmation_input_digest"] == (
        result["duplicate_confirmation_input_digest"])
    assert "logical_request_id" not in eliminated and "input_digest" not in eliminated
    assert eliminated["relations"][0]["decision"] == "DUPLICATE"
    assert eliminated["relations"][0]["left_evidence"]
    assert eliminated["relations"][0]["right_evidence"]
    assert eliminated["relations"][0]["centrality_basis"]
    assert eliminated["relations"][0]["duplicate_confirmation"]["decision"] == "CONFIRM_DUPLICATE"
    assert eliminated["relations"][0]["duplicate_confirmation_provenance"]["logical_request_id"] == (
        result["duplicate_confirmation_logical_request_id"])
