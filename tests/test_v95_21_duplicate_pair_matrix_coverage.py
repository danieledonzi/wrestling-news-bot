from agents.duplicate_pair_identity import article_id, recent_history_pair_id, same_run_pair_id
from agents.duplicate_pair_matrix import (
    _coverage,
    build_recent_history_pair_specs,
    build_same_run_pair_specs,
    evaluate_pair_matrix,
)
from agents import menzo_policy_v93_15 as menzo
from agents.menzo_duplicate_scorer import SCORER_VERSION
from agents.publisher_history import prune_record
from datetime import datetime, timezone
import json


def item(number):
    return {"source_url": f"https://www.example.test/news/{number}/?utm_source=x", "title": f"Story {number}"}


def valid_score(value=.1):
    return {"score": value, "threshold": .55, "above_threshold": value >= .55,
            "exact_duplicate": False, "exact_reason": "", "components": {},
            "penalties": {}, "reasons": [], "scorer_version": SCORER_VERSION}


def test_article_and_scoped_pair_identities_are_stable():
    first = article_id({"url": "HTTPS://WWW.Example.test/a/?utm_source=x#fragment"})
    assert first == article_id({"source_url": "https://example.test/a"})
    assert first.startswith("art_") and len(first) == 68
    assert article_id({"title": "no URL fallback"}) == ""
    other = article_id({"url": "https://example.test/b"})
    assert same_run_pair_id(first, other) == same_run_pair_id(other, first)
    assert recent_history_pair_id(first, other) != recent_history_pair_id(other, first)


def test_four_by_twelve_pair_matrix_is_six_plus_forty_eight():
    candidates = [item(n) for n in range(4)]
    history = [item(n + 100) for n in range(12)]
    same = build_same_run_pair_specs(candidates)
    recent = build_recent_history_pair_specs(candidates, history)
    assert len(same) == len({x.pair_id for x in same}) == 6
    assert len(recent) == len({x.pair_id for x in recent}) == 48
    assert len(same) + len(recent) == 54
    assert all(sum(x.left_article_id == article_id(candidate) for x in recent) == 12 for candidate in candidates)


def test_evaluator_exception_forces_complete_replay():
    specs = build_same_run_pair_specs([item(n) for n in range(4)])
    calls = []
    def evaluator(spec, evaluation_pass):
        calls.append((spec.pair_id, evaluation_pass))
        if evaluation_pass == "normal" and spec == specs[-1]:
            raise RuntimeError("artificial omission")
        return valid_score()
    result = evaluate_pair_matrix(specs, evaluator=evaluator)
    assert result["forced_full_replay_triggered"] is True
    assert result["forced_replay_pair_count"] == 6
    assert result["coverage_complete"] is True
    assert sum(p == "forced_full_replay" for _, p in calls) == 6


def test_replay_still_incomplete_remains_fail_closed():
    specs = build_same_run_pair_specs([item(1), item(2)])
    result = evaluate_pair_matrix(specs, evaluator=lambda *_: (_ for _ in ()).throw(RuntimeError("no score")))
    assert result["coverage_complete"] is False
    assert result["missing_pair_ids_after_replay"] == [specs[0].pair_id]


def test_foreign_technical_identity_is_ignored_without_replay():
    specs = build_same_run_pair_specs([item(1), item(2), item(3)])
    count = 0
    def evaluator(spec, evaluation_pass):
        nonlocal count
        count += 1
        value = valid_score()
        if evaluation_pass == "normal" and count == 1:
            value["pair_id"] = "ignored_by_record_builder"
        return value
    result = evaluate_pair_matrix(specs, evaluator=evaluator)
    assert result["coverage_complete"] and not result["forced_full_replay_triggered"]
    assert {record["pair_id"] for record in result["records"]} == {spec.pair_id for spec in specs}


def test_invalid_score_forces_full_replay():
    specs = build_same_run_pair_specs([item(1), item(2)])
    def evaluator(_spec, evaluation_pass):
        return valid_score() if evaluation_pass == "forced_full_replay" else {**valid_score(), "score": float("nan")}
    result = evaluate_pair_matrix(specs, evaluator=evaluator)
    assert result["forced_full_replay_triggered"] and result["coverage_complete"]
    assert result["forced_replay_pair_count"] == 1


def test_missing_pair_is_detected_independently_of_record_count():
    specs = build_same_run_pair_specs([item(1), item(2), item(3)])
    records = evaluate_pair_matrix(specs)["records"][:-1]
    coverage = _coverage({spec.pair_id for spec in specs}, records)
    assert not coverage["coverage_complete"]
    assert coverage["missing_pair_ids"] == [specs[-1].pair_id]


def test_recent_history_candidate_counts_only_left_endpoint():
    shared = item(1)
    candidates = [dict(shared), item(2)]
    history = [dict(shared), item(100)]
    specs = build_recent_history_pair_specs(candidates, history)
    result = {"selected": candidates, "pending": [], "skipped": [], "postprocess": {}}
    matrix = menzo._v9521_stage(result, "recent_history", specs)
    assert matrix["coverage_complete"]
    assert all(candidate["recent_history_pair_count_expected"] == len(history) for candidate in candidates)
    assert all(candidate["recent_history_pair_count_evaluated"] == len(history) for candidate in candidates)
    second_id = article_id(candidates[1])
    assert all(record["left_article_id"] == second_id for record in matrix["records"]
               if record["pair_id"] in candidates[1]["duplicate_suspicious_pair_ids"])


def test_royal_rumble_literal_regression_uses_real_scorer():
    candidate = {
        "title": "WWE Royal Rumble Coming To Arizona In 2027 As Part Of Multi-Year Partnership With TKO",
        "source_url": "https://www.wrestlinginc.com/2230325/wwe-royal-rumble-arizona-2027-tko-multi-year-partnership/",
    }
    published = {
        "title": "Svelata la location della WWE Royal Rumble 2027",
        "source_url": "https://www.ringsidenews.com/wwe-royal-rumble-2027-location-venue-revealed/",
        "status": "publish", "published_at": "2026-08-04T18:02:35.574855+00:00",
    }
    candidate_id, published_id = article_id(candidate), article_id(published)
    specs = build_recent_history_pair_specs([candidate], [published])
    result = evaluate_pair_matrix(specs)
    assert candidate_id and published_id and candidate_id != published_id
    assert len(specs) == 1
    assert specs[0].pair_id == recent_history_pair_id(candidate_id, published_id)
    assert specs[0].pair_id.startswith("pair_rh_")
    assert len(result["records"]) == 1 and result["coverage_complete"]
    record = result["records"][0]
    assert record["score"] == .61875 and record["threshold"] == .55
    assert record["above_threshold"] is True and not record["exact_duplicate"]


def test_publisher_history_new_and_legacy_records_receive_article_id():
    legacy = {"source_url": "https://example.test/legacy", "status": "published"}
    saved = prune_record(legacy)
    assert saved["article_id"] == article_id(legacy)


def test_stale_publisher_history_identity_is_recalculated(tmp_path):
    record = {"source_url": "https://example.test/current", "article_id": "art_stale",
              "status": "publish", "published_at": datetime.now(timezone.utc).isoformat()}
    path = tmp_path / "history.json"
    path.write_text(json.dumps([record]), encoding="utf-8")
    loaded = menzo.load_authoritative_publisher_history(path=path)
    assert loaded[0]["article_id"] == article_id(record)
    assert loaded[0]["article_id_migrated_from"] == "art_stale"


def test_prune_record_replaces_stale_identity():
    record = {"source_url": "https://example.test/current", "article_id": "art_stale"}
    saved = prune_record(record)
    assert saved["article_id"] == article_id(record)
    assert saved["article_id_migrated_from"] == "art_stale"


def test_recent_history_stale_identity_uses_recalculated_endpoints(monkeypatch, tmp_path):
    candidate = item(7)
    old = {**item(8), "article_id": "art_stale", "status": "publish",
           "published_at": datetime.now(timezone.utc).isoformat()}
    path = tmp_path / "history.json"; path.write_text(json.dumps([old]), encoding="utf-8")
    monkeypatch.setattr(menzo, "publisher_history_file", lambda: path)
    monkeypatch.setattr(menzo, "DUPLICATE_PAIR_COVERAGE_FILE", tmp_path / "coverage.json")
    result = {"selected": [candidate], "pending": [], "skipped": [], "postprocess": {}}
    menzo.apply_recent_published_duplicate_guard(result)
    artifact = json.loads((tmp_path / "coverage.json").read_text())
    pair = artifact["recent_history"]["pairs"][0]
    assert artifact["recent_history"]["coverage_complete"] is True
    assert pair["left_article_id"] == article_id(candidate)
    assert pair["right_article_id"] == article_id(old)


def test_below_threshold_and_exact_records_are_terminal():
    below_specs = build_same_run_pair_specs([item(1), item(2)])
    below_result = {"selected": [item(1), item(2)], "pending": [], "skipped": [], "postprocess": {}}
    menzo._v9521_stage(below_result, "same_run", below_specs)
    below = below_result["postprocess"]["_duplicate_pair_coverage_detail"]["same_run"]["records"][0]
    assert (below["gemini_decision"], below["final_disposition"]) == ("NOT_REQUIRED", "below_threshold")

    exact_item = item(3)
    exact_specs = build_recent_history_pair_specs([exact_item], [dict(exact_item)])
    exact_result = {"selected": [exact_item], "pending": [], "skipped": [], "postprocess": {}}
    menzo._v9521_stage(exact_result, "recent_history", exact_specs)
    exact = exact_result["postprocess"]["_duplicate_pair_coverage_detail"]["recent_history"]["records"][0]
    menzo.update_pair_coverage_record(exact_result, "recent_history", exact["pair_id"],
        gemini_decision="EXACT_DUPLICATE", final_disposition="candidate_blocked")
    assert exact["gemini_decision"] == "EXACT_DUPLICATE" and exact["final_disposition"] != "pending"


def test_semantic_and_failure_dispositions_propagate_by_pair_id():
    left, right = item(20), item(21)
    specs = build_same_run_pair_specs([left, right])
    result = {"selected": [left, right], "pending": [], "skipped": [], "postprocess": {}}
    matrix = menzo._v9521_stage(result, "same_run", specs)
    pair_id = matrix["records"][0]["pair_id"]
    for decision, cache, disposition in (("NO_MATCH", "miss", "ordinary_pair"),
                                         ("DUPLICATE", "miss", "duplicate_applied"),
                                         ("NO_MATCH", "hit", "ordinary_pair"),
                                         ("ARBITRATION_FAILED", "miss", "component_fail_closed")):
        menzo.update_pair_coverage_record(result, "same_run", pair_id, gemini_decision=decision,
                                          cache_status=cache, final_disposition=disposition)
        record = result["postprocess"]["_duplicate_pair_coverage_detail"]["same_run"]["records"][0]
        assert (record["gemini_decision"], record["cache_status"], record["final_disposition"]) == (decision, cache, disposition)
