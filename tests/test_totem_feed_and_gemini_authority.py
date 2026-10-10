"""Owner-ratified feed scope and final Gemini semantics, with offline providers."""
import copy
import json

import pytest

from agents import massy, massy_policy_v93_24 as massy_policy
from agents import menzo_active_duplicate_pair_cache as cache
from agents import menzo_editorial_director_active as active
from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo
from agents import menzo_soft_board as soft
from test_dr1_duplicate_body_revalidation import canonical_body
from test_ed2_editorial_director_active import (
    grounded_duplicate, no_match_relations, response, snapshot, suspicious_relation,
)


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_FILE", tmp_path / "pairs.json")
    monkeypatch.setattr(active, "record_gemini_attempt", lambda **_: None)
    monkeypatch.setattr(active.source_body, "hydrate", lambda _: (False, "offline"))
    monkeypatch.setattr(menzo, "hydrate_complete_article_bodies", lambda _: (False, []))


@pytest.mark.parametrize("scope", ["same_run", "recent_history"])
def test_opening_announcement_without_headline_names_is_final_and_cached(scope):
    def state():
        value = snapshot(2)
        value["candidates"][0]["title"] = "Surprising Opening Match For Money In The Bank Announced"
        value["candidates"][1]["title"] = "Opening Match For The PLE Revealed"
        if scope == "recent_history":
            value["publisher_history_12h"] = [{"article_id": "old", "source_url": "https://old.test/news",
                "source_title": value["candidates"][1]["title"]}]
        value["authorized_relations"] = [suspicious_relation(value, right=0 if scope == "recent_history" else 1, scope=scope)]
        return value
    first = state()
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        if "DUPLICATE GATE" in prompt:
            return {"relations": [grounded_duplicate("r0", "Roman Reigns faces LA Knight",
                "World championship bout opens the show", "The same opening bout was announced")]}
        return response(first, ("SELECT", "SELECT"))
    result = active.evaluate(first, provider=provider)
    assert result["status"] == "VALIDATED" and len(calls) == 3
    assert len(first["semantic_duplicate_skips"]) == 1
    relation = result["output"]["relations"][0]
    assert relation["decision"] == "DUPLICATE" and relation["semantic_authority"] == "gemini_final"
    assert not any("CONFIRMATION" in prompt or "REPAIR" in prompt for prompt in calls)
    second = state()
    def cached_provider(prompt, *_):
        assert "DUPLICATE GATE" not in prompt and "CONFIRMATION" not in prompt
        return response(second, ("SELECT", "SELECT"))
    replay = active.evaluate(second, provider=cached_provider)
    assert replay["status"] == "VALIDATED"
    assert replay["output"]["relations"] == []
    assert menzo.terminal_skip_memory()


@pytest.mark.parametrize("decision", ["NO_MATCH", "MATERIAL_UPDATE"])
def test_nonduplicate_verdict_never_gets_semantic_repair(decision):
    value = snapshot(1)
    value["publisher_history_12h"] = [{"article_id": "old", "source_url": "https://old.test/news", "title": "Earlier facts"}]
    value["authorized_relations"] = [suspicious_relation(value, right=0, scope="recent_history")]
    row = {"ref": "r0", "decision": decision}
    if decision == "MATERIAL_UPDATE":
        row.update(new_fact="He can now train again", temporal_basis="The change became known after the prior story")
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        return {"relations": [row]} if "DUPLICATE GATE" in prompt else response(value, ("SELECT",))
    result = active.evaluate(value, provider=provider)
    assert result["status"] == "VALIDATED" and len(calls) == 3
    assert len(value["candidates"]) == 1 and value["semantic_duplicate_skips"] == []


@pytest.mark.parametrize("fault", ["missing_row", "invalid_decision", "duplicate_ref", "missing_field", "wrong_ref", "malformed_ref"])
def test_actual_technical_errors_still_fail_closed(fault):
    value = snapshot(2)
    value["authorized_relations"] = [suspicious_relation(value)]
    row = grounded_duplicate("r0", "left factual span", "right factual span")
    if fault == "invalid_decision": row["decision"] = "UNCERTAIN"
    if fault == "missing_field": row.pop("decision")
    if fault == "wrong_ref": row["ref"] = "r99"
    if fault == "malformed_ref": row["ref"] = []
    rows = [] if fault == "missing_row" else [row, copy.deepcopy(row)] if fault == "duplicate_ref" else [row]
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        return {"relations": rows} if "DUPLICATE GATE" in prompt else response(value, ("SELECT", "SELECT"))
    result = active.evaluate(value, provider=provider)
    assert result["status"] != "VALIDATED"
    assert len(value["candidates"]) == 2 and not value.get("semantic_duplicate_skips")
    assert len([prompt for prompt in calls if "DUPLICATE GATE" in prompt]) == 1
    assert cache.load()["entries"] == {}


def test_invalid_sibling_cannot_revoke_a_valid_duplicate():
    value = snapshot(3)
    value["authorized_relations"] = [suspicious_relation(value), suspicious_relation(value, right=2, pair_id="ac")]
    attempts = []
    def provider(prompt, *_):
        if "DUPLICATE GATE" not in prompt:
            return response(value, ("SELECT", "SELECT", "SELECT"))
        attempts.append(prompt)
        if len(attempts) == 1:
            return {"relations": [grounded_duplicate("r0", "first endpoint fact", "second endpoint fact"),
                {"ref": "r1", "decision": "UNCERTAIN"}]}
        assert 'REPAIR ONLY THESE RELATION REFS=["r1"]' in prompt
        return {"relations": [{"ref": "r0", "decision": "NO_MATCH"}, {"ref": "r1", "decision": "NO_MATCH"}]}
    result = active.evaluate(value, provider=provider)
    assert result["status"] != "VALIDATED"
    assert len(attempts) == 1
    assert cache.load()["entries"]["pair-ab"]["final_relation"]["decision"] == "DUPLICATE"
    assert len(value["semantic_duplicate_skips"]) == 1


def test_canonical_bodies_are_projected_only_for_authorized_endpoints():
    text = "Roman Reigns will defend against LA Knight in the opening match. " * 8
    rows = [{"url": f"https://body.test/{i}", "title": "Opening announcement", "canonical_source_body": canonical_body(text)} for i in range(3)]
    history = [{"source_url": f"https://history.test/{i}", "source_title": "Earlier opening announcement", "canonical_source_body": canonical_body(text)} for i in range(2)]
    value = shadow.capture_opportunity({"news_candidates_for_menzo": rows}, run_id="body", observation_timestamp="now", history=history)
    value["authorized_relations"] = [suspicious_relation(value, right=0, scope="recent_history")]
    payload = active.active_provider_input(value)
    assert payload["candidates"][0]["retained_body"] == text.strip()
    assert payload["history"][0]["retained_body"] == text.strip()
    assert all("retained_body" not in row for row in payload["candidates"][1:] + payload["history"][1:])
    assert "canonical_source_body" not in json.dumps(payload)
    value["authorized_relations"] = []
    assert "retained_body" not in json.dumps(active.active_provider_input(value))


def test_invalid_reply_with_already_supplied_bodies_does_not_trigger_another_body_call():
    value = snapshot(2)
    value["authorized_relations"] = [suspicious_relation(value)]
    value["_duplicate_revalidation_bodies"] = {
        row["candidate_id"]: {"text": "Complete supplied factual article body. " * 10, "coverage": "FULL_BODY"}
        for row in value["candidates"]}
    calls = []
    def provider(prompt, *_):
        calls.append(prompt)
        return {"relations": [{"ref": "r0", "decision": "UNCERTAIN"}]} if "DUPLICATE GATE" in prompt else response(value, ("SELECT", "SELECT"))
    result = active.evaluate(value, provider=provider)
    assert result["status"] != "VALIDATED" and len(calls) == 3
    assert "duplicate_body_revalidation" not in result


def test_active_report_presence_cannot_drop_feed_news_at_massy(monkeypatch):
    monkeypatch.setenv("OWTV_EDITORIAL_DIRECTOR_ACTIVE_ENABLED", "true")
    news = {"url": "https://feed.test/finish", "title": "SmackDown key moments", "summary": "Individual segment facts"}
    report = {"id": "wwe_smackdown", "show_name": "SmackDown"}
    monkeypatch.setattr(massy_policy, "base_run_massy", lambda: {"news_candidates_for_menzo": [dict(news)], "report_candidates": [], "hard_skipped": [], "handoff": {}})
    monkeypatch.setattr(massy_policy, "report_coverage", lambda _: ({"wwe_smackdown": {}}, {"wwe_smackdown"}, set()))
    monkeypatch.setattr(massy_policy, "configured_reports", lambda: [report])
    monkeypatch.setattr(massy_policy, "menzo_skip_memory", lambda: {})
    monkeypatch.setattr(massy_policy, "old_news_reason", lambda _: None)
    monkeypatch.setattr(massy_policy, "build_suspicious_story_clusters", lambda _: [])
    board = massy_policy.run_massy()
    assert [row["url"] for row in board["news_candidates_for_menzo"]] == [news["url"]]
    assert not board["hard_skipped"] and board["binding"]["feed_news_independent_of_report"] is True


def test_report_body_cannot_manufacture_news_urls():
    report = {"source": "wrestlinginc", "url": "https://www.wrestlinginc.com/smackdown-results-10-9-2026/",
        "title": "WWE SmackDown Results 10/9/2026", "summary": "Trick Williams wins. GUNTHER attacks Finn Balor. Women's titles change hands."}
    result = massy.classify_entries([report], set(), set())
    assert len(result["report_candidates"]) == 1 and result["news_candidates_for_menzo"] == []


@pytest.mark.parametrize("cls", ["MUST_PUBLISH", "SHOULD_PUBLISH"])
@pytest.mark.parametrize("published", [False, True])
def test_live_feed_strong_news_is_selected_independently_of_report(cls, published, monkeypatch, tmp_path):
    for name in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE", "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / name)
    monkeypatch.setattr("agents.bob.dynamic_article_capacity", lambda *_: (5, "test"))
    value = snapshot(1)
    active.preserve_bob_capacity_metadata(value, [{"url": value["candidates"][0]["url"],
        "show_report_id": "wwe_smackdown", "corresponding_report_published": published}])
    result = active.evaluate(value, provider=lambda *_: {"candidates": [{"ref": "c0", "editorial_class": cls,
        "recommended_action": "SELECT", "category": "WWE", "story_core": "A concrete live match result"}], "relations": []})
    projected = active.project(value, result)
    assert len(projected["selected"]) == 1 and projected["pending"] == projected["skipped"] == []
    assert projected["selected"][0]["corresponding_report_published"] is published


def test_v6_primary_admissions_survive_v7_release():
    row = {"editorial_director": {"policy_version": "owtv_editorial_director_policy_v6_active",
        "editorial_class": "PUBLISHABLE_SOFT", "recommended_action": "DEFER",
        "category": "WWE", "story_core": "A valid original fact"}}
    assert soft._current_primary_soft(row)
    row["editorial_director"]["policy_version"] = "owtv_editorial_director_policy_v5_active"
    assert soft._current_primary_soft(row)


def test_soft_duplicate_validator_trusts_semantics_but_requires_technical_fields():
    row = {"current_id": "c0", "published_id": "p0", "decision": "MATERIAL_UPDATE", "shared_facts": ["Recovery"],
        "new_fact": "He can train again", "temporal_basis": "BECAME_KNOWN_AFTER",
        "temporal_evidence_excerpt": "Il recupero permette ora l'allenamento", "reason": "A new recovery milestone"}
    records = {"c0": {"full_body": "Supplied facts"}}, {"p0": {"full_body": "Earlier facts"}}
    assert menzo.validate_recent_history_batch({"comparisons": [row]}, *records)[0]
    assert menzo.validate_recent_history_batch({"comparisons": [{**row, "new_fact": ""}]}, *records)[0] is None
    assert menzo.validate_recent_history_batch({"comparisons": [{**row, "temporal_basis": "UNKNOWN"}]}, *records)[0] is None
