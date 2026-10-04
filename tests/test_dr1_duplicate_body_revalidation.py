"""DR-1 acceptance: real validators and handoff, isolated external calls and state."""
import copy
import hashlib
import json

import pytest

from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_active_duplicate_pair_cache as cache
from agents import menzo_policy_v93_15 as menzo
from agents import source_body
from test_ed2_editorial_director_active import (
    snapshot, response, suspicious_relation, no_match_relations,
    grounded_duplicate, duplicate_confirmation,
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_FILE", tmp_path / "pairs.json")
    monkeypatch.setattr(source_body, "hydrate", lambda item: (False, "offline"))
    monkeypatch.setattr(menzo, "hydrate_complete_article_bodies", lambda rows: (False, []))
    ledger = []
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **facts: ledger.append(facts))
    return ledger


def add_bodies(state):
    state["_duplicate_revalidation_bodies"] = {
        row.get("candidate_id", row.get("article_id")): {
            "text": (row.get("title", "Historical facts") + " More confirmed article facts.") * 8,
            "coverage": "FULL_BODY"}
        for row in state["candidates"] + state["publisher_history_12h"]}


def invalid_gate():
    return {"relations": [{"ref": "r0", "decision": "UNCERTAIN"}]}


def select_all(state):
    return response(state, tuple("SELECT" for _ in state["candidates"]))


def canonical_body(text):
    text = text.strip()
    return {"schema": source_body.SCHEMA, "complete": True, "cleaned_full_text": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "provenance": {"extractor": "bob.extract_elements", "body_complete": True},
            "coverage": {"extraction_finished": True}}


def test_capture_private_canonical_body_preserves_ordinary_digest_and_legacy():
    raw = {"url": "https://dr1.test/a", "title": "New WWE release", "summary": "RSS facts"}
    text = "Complete independently extracted source article facts. " * 8
    base = shadow.capture_opportunity({"news_candidates_for_menzo": [raw]}, run_id="run",
        observation_timestamp="now", history=[])
    enriched = shadow.capture_opportunity({"news_candidates_for_menzo": [
        {**raw, "canonical_source_body": canonical_body(text)}]}, run_id="run",
        observation_timestamp="now", history=[])
    assert enriched["input_digest"] == base["input_digest"]
    assert enriched["observed"] == base["observed"]
    assert shadow.provider_input(enriched) == shadow.provider_input(base)
    assert next(iter(enriched["_duplicate_revalidation_bodies"].values()))["text"] == text.strip()
    legacy = shadow.capture_opportunity({"news_candidates_for_menzo": [
        {**raw, "canonical_source_body": {"text": text}}]}, run_id="run",
        observation_timestamp="now", history=[])
    assert legacy["candidates"][0]["retained_body"] == text
    active.prepare_snapshot(base); active.prepare_snapshot(enriched)
    assert active.active_provider_input(base) == active.active_provider_input(enriched)
    assert base["input_digest"] == enriched["input_digest"]


def test_capture_history_body_is_private_and_not_recrawled(monkeypatch):
    text = "Retained full historical source material. " * 9
    raw = {"url": "https://dr1.test/current", "title": "Current development"}
    old = {"source_url": "https://dr1.test/history", "source_title": "Historical development",
           "canonical_source_body": canonical_body(text)}
    state = shadow.capture_opportunity({"news_candidates_for_menzo": [raw]}, run_id="r",
                                       observation_timestamp="now", history=[old])
    assert "retained_body" not in state["publisher_history_12h"][0]
    cid = state["candidates"][0]["candidate_id"]
    hid = state["publisher_history_12h"][0]["article_id"]
    state["_duplicate_revalidation_bodies"][cid] = {"text": text, "coverage": "FULL_BODY"}
    monkeypatch.setattr(source_body, "hydrate", lambda _: pytest.fail("retained bodies must not fetch"))
    local, coverage = active._body_pair_snapshot(state, suspicious_relation(state, right=0, scope="recent_history"))
    assert local["publisher_history_12h"][0]["retained_body"] == text.strip()
    assert coverage[hid]["coverage"] == "FULL_BODY"


def test_single_pair_body_revalidation_recovers_without_cache_pollution(isolated):
    state = snapshot(2); state["authorized_relations"] = [suspicious_relation(state)]
    add_bodies(state); calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if "DR1 BODY-AWARE" in prompt:
            assert '"retained_body"' in prompt
            return no_match_relations(1)
        return invalid_gate() if "DUPLICATE GATE" in prompt else select_all(state)
    result = active.evaluate(state, provider=provider)
    assert result["status"] == "VALIDATED"
    assert result["duplicate_body_revalidation"]["attempts"] == 1
    assert len([p for p in calls if "DR1 BODY-AWARE" in p]) == 1
    assert result["attempts"] == len(calls) == 4
    assert cache.load()["entries"] == {}
    assert len(state["candidates"]) == 2
    rows = [row for row in isolated if row["workload"] == "editorial_director_duplicate_body_revalidation"]
    assert len(rows) == 1 and rows[0]["logical_request_id"] == result["duplicate_body_revalidation"]["requests"][0]["logical_request_id"]


@pytest.mark.parametrize("confirmation", ["CONFIRM_DUPLICATE", "REJECT_DUPLICATE"])
def test_body_duplicate_requires_independent_confirmation(confirmation):
    state = snapshot(2); state["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
    state["authorized_relations"] = [suspicious_relation(state)]; add_bodies(state)
    left, right = [row["title"] for row in state["candidates"]]
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if "DR1 BODY-AWARE" in prompt:
            if "CONFIRMATION PHASE" in prompt:
                return {"confirmations": [duplicate_confirmation("d0", left, right, confirmation)]}
            return {"relations": [grounded_duplicate("r0", left, right, "Jasper Troy Becomes First Confirmed Release")]}
        return invalid_gate() if "DUPLICATE GATE" in prompt else select_all(state)
    result = active.evaluate(state, provider=provider)
    assert result["status"] == "VALIDATED"
    assert result["duplicate_body_revalidation"]["attempts"] == 2
    assert len(state["candidates"]) == (1 if confirmation == "CONFIRM_DUPLICATE" else 2)
    assert len([p for p in calls if "CONFIRMATION PHASE" in p]) == 1
    assert cache.load()["entries"] == {}


@pytest.mark.parametrize("failure", ["invalid", "exception"])
def test_failed_local_confirmation_does_not_suppress_or_cache(failure, isolated):
    state = snapshot(2); state["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
    state["authorized_relations"] = [suspicious_relation(state)]; add_bodies(state)
    before = copy.deepcopy(state["candidates"]); left, right = [r["title"] for r in before]
    def provider(prompt, *_):
        if "DR1 BODY-AWARE" in prompt:
            if "CONFIRMATION PHASE" in prompt:
                if failure == "exception":
                    raise RuntimeError("offline provider error")
                return {"confirmations": []}
            return {"relations": [grounded_duplicate("r0", left, right, "Jasper Troy Becomes First Confirmed Release")]}
        return invalid_gate()
    result = active.evaluate(state, provider=provider)
    assert result["status"] != "VALIDATED" and state["candidates"] == before
    assert "semantic_duplicate_skips" not in state
    assert cache.load()["entries"] == {}
    assert result["duplicate_body_revalidation"]["attempts"] == 2
    assert len(result["duplicate_body_revalidation"]["requests"]) == 2
    assert len([r for r in isolated if "body_" in r["workload"]]) == 2


def test_partial_ordinary_no_match_is_cached_on_remaining_fallback():
    state = snapshot(3)
    state["authorized_relations"] = [suspicious_relation(state), suspicious_relation(state, right=2, pair_id="ac")]
    before = copy.deepcopy(state["candidates"])
    gate = {"relations": [{"ref": "r0", "decision": "NO_MATCH"}, {"ref": "r1", "decision": "UNCERTAIN"}]}
    result = active.evaluate(state, provider=lambda *_: gate)
    assert result["status"] != "VALIDATED"
    assert state["candidates"] == before and "semantic_duplicate_skips" not in state
    assert set(cache.load()["entries"]) == {"pair-ab"}
    assert result["duplicate_pair_cache_entries_stored"] == 1


@pytest.mark.parametrize("decision", ["CONFIRM_DUPLICATE", "REJECT_DUPLICATE"])
def test_failed_ordinary_confirmation_gets_one_local_attempt(decision):
    state = snapshot(2); state["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
    state["authorized_relations"] = [suspicious_relation(state)]; add_bodies(state)
    left, right = [r["title"] for r in state["candidates"]]
    def provider(prompt, *_):
        if "CONFIRMATION PHASE" in prompt:
            return {"confirmations": [duplicate_confirmation("d0", left, right, decision)]} if "DR1 BODY-AWARE" in prompt else {"confirmations": []}
        if "DUPLICATE GATE" in prompt:
            return {"relations": [grounded_duplicate("r0", left, right, "Jasper Troy Becomes First Confirmed Release")]}
        return select_all(state)
    result = active.evaluate(state, provider=provider)
    assert result["status"] == "VALIDATED" and result["duplicate_body_revalidation"]["attempts"] == 1
    assert len(state["candidates"]) == (1 if decision == "CONFIRM_DUPLICATE" else 2)
    assert result["output"]["relations"][0]["duplicate_confirmation_provenance"]["phase"] == "editorial_director_duplicate_body_confirmation"
    assert cache.load()["entries"] == {}


def test_cached_duplicate_class_and_history_no_match_bypass_local_attempt():
    def make():
        state = snapshot(2)
        state["candidates"][1]["title"] = "Jasper Troy Becomes First Confirmed Release"
        state["publisher_history_12h"] = [{"article_id": "h", "title": "An unrelated historical development"}]
        return state
    first = make()
    first["authorized_relations"] = [suspicious_relation(first), suspicious_relation(first, right=0, scope="recent_history", pair_id="ah")]
    left, right = [r["title"] for r in first["candidates"]]
    def seed(prompt, *_):
        if "CONFIRMATION PHASE" in prompt:
            return {"confirmations": [duplicate_confirmation("d0", left, right)]}
        if "DUPLICATE GATE" in prompt:
            return {"relations": [grounded_duplicate("r0", left, right, "Jasper Troy Becomes First Confirmed Release"),
                                  {"ref": "r1", "decision": "NO_MATCH"}]}
        return select_all(first)
    assert active.evaluate(first, provider=seed)["status"] == "VALIDATED"
    second = make(); add_bodies(second)
    second["authorized_relations"] = [suspicious_relation(second),
        suspicious_relation(second, right=0, scope="recent_history", pair_id="ah"),
        suspicious_relation(second, left=1, right=0, scope="recent_history", pair_id="bh")]
    prompts = []
    def provider(prompt, *_):
        prompts.append(prompt)
        return invalid_gate() if "DUPLICATE GATE" in prompt else select_all(second)
    result = active.evaluate(second, provider=provider)
    assert result["status"] == "VALIDATED" and result["duplicate_pair_cache_hits"] == 2
    assert not any("DR1 BODY-AWARE" in p for p in prompts)
    assert next(r for r in result["output"]["relations"] if r["pair_id"] == "bh")["validated_equivalence"]["source_pair_id"] == "ah"
    assert "bh" not in cache.load()["entries"]


def test_local_refs_keep_invalid_pair_identity_and_valid_row_is_not_revoked_by_repair():
    state = snapshot(3); add_bodies(state)
    state["authorized_relations"] = [suspicious_relation(state), suspicious_relation(state, right=2, pair_id="ac")]
    normal_calls = 0
    def provider(prompt, *_):
        nonlocal normal_calls
        if "DR1 BODY-AWARE" in prompt:
            data = json.loads(prompt.split("INPUT=", 1)[1])
            assert [r["title"] for r in data["candidates"]] == [state["candidates"][0]["title"], state["candidates"][2]["title"]]
            assert len(data["authorized_relations"]) == 1
            return no_match_relations(1)
        if "DUPLICATE GATE" in prompt:
            normal_calls += 1
            return {"relations": [{"ref": "r0", "decision": "NO_MATCH" if normal_calls == 1 else "UNCERTAIN"},
                                  {"ref": "r1", "decision": "UNCERTAIN"}]}
        return select_all(state)
    result = active.evaluate(state, provider=provider)
    assert result["status"] == "VALIDATED"
    assert result["duplicate_body_revalidation"]["pair_id"] == "ac"
    assert {r["pair_id"] for r in result["output"]["relations"]} == {"pair-ab", "ac"}
    assert set(cache.load()["entries"]) == {"pair-ab"}
    assert result["duplicate_pair_cache_entries_stored"] == 1


@pytest.mark.parametrize("kind", ["missing_body", "root", "ambiguous_ref", "multiple_pairs", "provider_exception"])
def test_unsupported_failures_keep_atomic_fallback(kind):
    state = snapshot(3); state["authorized_relations"] = [suspicious_relation(state)]
    if kind != "missing_body":
        add_bodies(state)
    if kind == "multiple_pairs":
        state["authorized_relations"].append(suspicious_relation(state, right=2, pair_id="ac"))
    before = copy.deepcopy(state["candidates"]); calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if kind == "root":
            return {"wrong_root": []}
        if kind == "ambiguous_ref":
            return {"relations": [{"ref": "r0", "decision": "NO_MATCH"}] * 2}
        if kind == "provider_exception":
            raise RuntimeError("provider offline")
        return {"relations": [{"ref": f"r{i}", "decision": "UNCERTAIN"} for i in range(len(state["authorized_relations"]))]}
    result = active.evaluate(state, provider=provider)
    assert result["status"] != "VALIDATED" and state["candidates"] == before
    assert not any("DR1 BODY-AWARE" in p for p in calls)
    assert cache.load()["entries"] == {}


def test_no_match_constraint_follows_every_member_of_validated_class():
    duplicate = {"pair_id": "ab", "scope": "same_run", "left_id": "a", "right_id": "b", "decision": "DUPLICATE",
                 "duplicate_confirmation": {"decision": "CONFIRM_DUPLICATE"}}
    distinct = {"pair_id": "ah", "scope": "recent_history", "left_id": "a", "right_id": "h", "decision": "NO_MATCH"}
    target = {"pair_id": "bh", "scope": "recent_history", "left_id": "b", "right_id": "h", "decision": "DUPLICATE"}
    covered = active._covered_no_match(target, [duplicate, distinct])
    assert covered["decision"] == "NO_MATCH" and covered["pair_id"] == "bh"
    assert covered["validated_equivalence"]["source_pair_id"] == "ah"
    assert "duplicate_confirmation" not in covered
    assert active._covered_no_match(target, [{**duplicate, "decision": "UNRESOLVED"}, distinct]) is None


def test_only_affected_current_endpoints_are_hydrated(monkeypatch):
    state = snapshot(3); calls = []
    def hydrate(row):
        calls.append(row["candidate_id"])
        row["canonical_source_body"] = canonical_body("Complete article source facts. " * 12)
        return True, "offline fixture"
    monkeypatch.setattr(source_body, "hydrate", hydrate)
    local, _ = active._body_pair_snapshot(state, suspicious_relation(state, left=1, right=2))
    assert local is not None and set(calls) == {r["candidate_id"] for r in state["candidates"][1:]}
    assert all("canonical_source_body" not in r for r in state["candidates"])


def test_body_projection_byte_bound_and_no_new_evidence(monkeypatch):
    state = snapshot(2); add_bodies(state)
    monkeypatch.setattr(shadow, "MAX_INPUT_BYTES", 100)
    local, reason = active._body_pair_snapshot(state, suspicious_relation(state))
    assert local is None and reason == "body_projection_exceeded"
    monkeypatch.setattr(shadow, "MAX_INPUT_BYTES", 120000)
    for row in state["candidates"]:
        row["retained_body"] = state["_duplicate_revalidation_bodies"][row["candidate_id"]]["text"]
    local, reason = active._body_pair_snapshot(state, suspicious_relation(state))
    assert local is None and reason == "no_new_body_evidence"
