"""Focused V96.1 canonical Andrea/Alfred read-model contracts."""
from datetime import datetime, timezone
import json

import newsroom_runner
from scripts.observability_snapshot import _canonical_event_sections

NOW = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)


def event(kind, agent, cid, *, result=None, run="run-1", suffix=""):
    row = {"timestamp_utc": NOW.isoformat(), "run_id": run, "correlation_id": f"corr-{run}-{cid}{suffix}",
           "content_id": cid, "event_type": kind, "agent": agent}
    if result is not None:
        row["result"] = result
    return row


def canonical(rows, coverage="full"):
    return _canonical_event_sections(rows, NOW.replace(hour=0), NOW.replace(hour=23),
                                     {"p1_1": coverage, "warnings": coverage,
                                      "failures": coverage, "ai": "unavailable"})


def chain(cid, outcome, *, bob=None):
    rows = [event("candidate_selected", "Menzo", cid),
            event("content_sufficiency_checked", "Andrea", cid, result=outcome)]
    expected = outcome != "blocked" if bob is None else bob
    if expected:
        rows.append(event("article_generation_requested", "Bob", cid))
    return rows


def test_andrea_all_outcomes_occurrence_and_unique_grains():
    rows = chain("a", "passed") + chain("b", "passed_with_exception") + chain("c", "blocked")
    # A later run for the same content is a second occurrence, not a second unique item.
    rows += [dict(r, run_id="run-2", correlation_id=r["correlation_id"].replace("run-1", "run-2"))
             for r in chain("a", "passed")]
    result = canonical(rows)["andrea"]
    assert result["available"] is True
    assert result["events"] == {"checked": 4, "passed": 2, "passed_with_exception": 1, "blocked": 1}
    assert result["unique"] == {"checked": 3, "passed": 1, "passed_with_exception": 1, "blocked": 1}


def test_andrea_complete_quiet_window_is_authoritative_zero():
    result = canonical([])["andrea"]
    assert result["available"] is True
    assert result["events"] == result["unique"] == {
        "checked": 0, "passed": 0, "passed_with_exception": 0, "blocked": 0}


def test_andrea_missing_or_inconsistent_correlations_are_null():
    cases = [
        [event("candidate_selected", "Menzo", "missing")],
        chain("passed-no-bob", "passed", bob=False),
        chain("blocked-with-bob", "blocked", bob=True),
        [event("content_sufficiency_checked", "Andrea", "orphan", result="passed")],
    ]
    for rows in cases:
        result = canonical(rows)["andrea"]
        assert result["available"] is False
        assert result["events"]["checked"] is None
        assert result["unique"]["checked"] is None
    assert canonical([], "partial")["andrea"]["events"]["checked"] is None


def test_andrea_lifecycle_may_span_window_start_without_expanding_counts():
    rows = chain("start-boundary", "passed")
    rows[0]["timestamp_utc"] = NOW.replace(day=19, hour=23, minute=59).isoformat()
    result = canonical(rows)["andrea"]
    assert result["available"] is True
    assert result["events"] == {"checked": 1, "passed": 1,
                                "passed_with_exception": 0, "blocked": 0}
    blocked = chain("blocked-boundary", "blocked")
    blocked[0]["timestamp_utc"] = NOW.replace(day=19, hour=23, minute=59).isoformat()
    assert canonical(blocked)["andrea"]["blocked"]["event_count"] == 1


def test_andrea_lifecycle_may_span_window_end_without_expanding_counts():
    rows = chain("end-boundary", "passed")
    rows[-1]["timestamp_utc"] = NOW.replace(day=21, hour=0).isoformat()
    result = canonical(rows)["andrea"]
    assert result["available"] is True
    assert result["checked"]["event_count"] == 1
    assert result["passed"]["event_count"] == 1


def test_andrea_boundary_validation_still_rejects_genuinely_missing_selection():
    result = canonical([event("content_sufficiency_checked", "Andrea", "still-orphan", result="passed"),
                        event("article_generation_requested", "Bob", "still-orphan")])["andrea"]
    assert result["available"] is False
    assert result["checked"]["event_count"] is None


def test_nested_real_andrea_blocks_keep_identity_and_avoids_are_attempt_free(monkeypatch):
    real = {"source_url": "https://example.test/real", "title": "Real",
            "decision": "blocked_before_bob"}
    payload = {"andrea": {"items": [real, {"source_url": "https://example.test/pass",
                                             "decision": "passed"}]},
               "handoff": {"blocked": 1}}
    assert newsroom_runner.andrea_blocked_items(payload) == [real]
    captured = []
    monkeypatch.setattr("agents.gemini_ledger.record_andrea_avoided", lambda item: captured.append(item))
    newsroom_runner.record_andrea_avoids_from_result(payload)
    assert captured == [real]
    # The runner only delegates avoided accounting; it never creates attempt/token/cost fields.
    assert not ({"attempt_id", "tokens", "cost"} & captured[0].keys())


def test_alfred_explicit_warning_and_blocker_grains_preserve_history():
    rows = chain("article", "passed")
    rows += [event("quality_review_completed", "Alfred", "article", result="needs_revision"),
             event("warning_recorded", "Alfred", "article"), event("warning_recorded", "Alfred", "article"),
             event("blocker_recorded", "Alfred", "article")]
    later = (NOW.replace(hour=13)).isoformat()
    rows += [dict(event("quality_review_completed", "Alfred", "article", result="approved"), timestamp_utc=later),
             dict(event("publication_completed", "Publisher", "article"), timestamp_utc=later)]
    result = canonical(rows)["alfred"]
    assert result["warning_occurrences"] == 2
    assert result["warning_bearing_reviews"] == 1
    assert result["articles_with_warnings"] == 1
    assert result["blocker_occurrences"] == 1
    assert result["blocker_bearing_reviews"] == 1
    assert result["articles_with_blockers"] == 1
    assert result["final_blockers"] == 0


def test_repeated_same_run_reviews_keep_warning_review_occurrences_distinct():
    rows = chain("repeat-warning", "passed") + [
        event("quality_review_completed", "Alfred", "repeat-warning", result="approved"),
        event("warning_recorded", "Alfred", "repeat-warning"),
        event("quality_review_completed", "Alfred", "repeat-warning", result="approved"),
        event("warning_recorded", "Alfred", "repeat-warning"),
    ]
    result = canonical(rows)["alfred"]
    assert result["warning_occurrences"] == 2
    assert result["warning_bearing_reviews"] == 2
    assert result["articles_with_warnings"] == 1

    clean_second = rows[:-1]
    result = canonical(clean_second)["alfred"]
    assert result["warning_bearing_reviews"] == 1
    assert result["articles_with_warnings"] == 1


def test_repeated_same_run_reviews_keep_blocker_review_occurrences_and_final_state():
    rows = chain("repeat-blocker", "passed") + [
        event("quality_review_completed", "Alfred", "repeat-blocker", result="needs_revision"),
        event("blocker_recorded", "Alfred", "repeat-blocker"),
        event("quality_review_completed", "Alfred", "repeat-blocker", result="needs_revision"),
        event("blocker_recorded", "Alfred", "repeat-blocker"),
    ]
    result = canonical(rows)["alfred"]
    assert result["blocker_occurrences"] == 2
    assert result["blocker_bearing_reviews"] == 2
    assert result["articles_with_blockers"] == 1
    assert result["final_blockers"] == 1

    clean_second = rows[:-1]
    clean_second[-1] = dict(clean_second[-1], result="approved",
                            timestamp_utc=NOW.replace(hour=13).isoformat())
    result = canonical(clean_second)["alfred"]
    assert result["blocker_bearing_reviews"] == 1
    assert result["articles_with_blockers"] == 1
    assert result["final_blockers"] == 0


def test_unassociated_alfred_audit_event_makes_review_grain_unavailable():
    result = canonical([event("warning_recorded", "Alfred", "no-review")])["alfred"]
    assert result["warning_occurrences"] == 1
    assert result["warning_bearing_reviews"] is None


def test_blocker_only_never_becomes_warning_and_corrupt_evidence_is_null():
    rows = chain("blocked-review", "passed") + [event("blocker_recorded", "Alfred", "blocked-review")]
    result = canonical(rows)["alfred"]
    assert result["blocker_occurrences"] == 1
    assert result["warning_occurrences"] == result["warning_bearing_reviews"] == 0
    unavailable = canonical(rows, "unavailable")
    assert unavailable["alfred"]["blocker_occurrences"] is None
    assert unavailable["alfred"]["warning_occurrences"] is None


def test_articles_with_blockers_requires_full_warning_coverage():
    rows = chain("partial-blocker", "passed") + [event("blocker_recorded", "Alfred", "partial-blocker")]
    for warning_coverage in ("partial", "unavailable"):
        coverage = {"p1_1": "full", "warnings": warning_coverage,
                    "failures": "full", "ai": "unavailable"}
        result = _canonical_event_sections(
            rows, NOW.replace(hour=0), NOW.replace(hour=23), coverage)
        assert result["alfred"]["articles_with_blockers"] is None


def test_generic_markdown_counters_have_no_canonical_mismatch_diagnostics():
    source = open("scripts/daily_editorial_judgment.py", encoding="utf-8").read()
    assert "observability_alfred_warning_occurrences_differs_from_markdown" not in source
    assert "observability_alfred_final_blockers_differs_from_markdown" not in source


def test_catalog_has_unique_v96_1_grains():
    metrics = json.load(open("config/metrics_catalog_v1.json", encoding="utf-8"))["metrics"]
    names = [metric["canonical_name"] for metric in metrics]
    assert len(names) == len(set(names))
    required = {"andrea.passed_with_exception_content", "andrea.passed_with_exception_occurrences",
                "alfred.warning_bearing_reviews", "alfred.blocker_occurrences",
                "alfred.blocker_bearing_reviews", "alfred.unique_articles_with_blockers"}
    assert required <= set(names)
