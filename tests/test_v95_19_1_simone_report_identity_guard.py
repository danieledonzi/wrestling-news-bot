from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import simone
from agents import simone_publisher_v93_18 as publisher


ROME = ZoneInfo("Europe/Rome")
COLLISION_URL = "https://www.wrestlinginc.com/2223339/aew-collision-july-25-results/"
REDEMPTION_URL = "https://www.wrestlinginc.com/2223102/aew-redemption-2026-six-championships-on-line-double-chain-match-more/"


def registry(dates=("2026-07-26",)):
    return {
        "default_report_publish_after_local": "06:30",
        "events": [{
            "key": "aew_redemption_2026", "promotion": "AEW", "event_name": "Redemption",
            "status": "confirmed", "aliases": ["AEW Redemption", "Redemption Results"],
            "nights": [{"night_key": f"aew_redemption_2026_night_{i}" if len(dates) > 1 else "aew_redemption_2026_main", "date_local": date, "enabled": True} for i, date in enumerate(dates, 1)],
        }],
    }


def special_report():
    expected, _ = simone.build_expected_special_reports(registry(), datetime(2026, 7, 27, 6, 30, tzinfo=ROME))
    return expected[0]


def test_special_event_is_due_only_on_next_morning():
    expected, blocked = simone.build_expected_special_reports(registry(), datetime(2026, 7, 26, 6, 30, tzinfo=ROME))
    assert expected == []
    assert blocked[0]["reason"] == "not_due_yet"
    assert blocked[0]["due_at_local"] == "2026-07-27T06:30:00+02:00"
    expected, _ = simone.build_expected_special_reports(registry(), datetime(2026, 7, 27, 6, 30, tzinfo=ROME))
    assert expected[0]["publish_date_local"] == "2026-07-27"


def test_multinight_events_each_have_a_next_morning_due_time():
    expected, blocked = simone.build_expected_special_reports(registry(("2026-07-25", "2026-07-26")), datetime(2026, 7, 27, 6, 30, tzinfo=ROME))
    assert [item["due_at_local"] for item in expected] == ["2026-07-26T06:30:00+02:00", "2026-07-27T06:30:00+02:00"]
    assert blocked == []


def test_malformed_night_is_fail_soft_and_valid_night_is_still_evaluated():
    cfg = registry(("not-a-date", "2026-07-26"))
    expected, blocked = simone.build_expected_special_reports(cfg, datetime(2026, 7, 27, 6, 30, tzinfo=ROME))
    assert [item["date"] for item in expected] == ["2026-07-26"]
    assert [(item["night_key"], item["reason"]) for item in blocked] == [
        ("aew_redemption_2026_night_1", "invalid_special_event_schedule")
    ]


def test_explicit_weekly_identity_wins_over_supporting_event_mention():
    candidate = {"title": "AEW Collision Results 7/25 - Two Ladder Match Qualifiers, Trios Titles On The Line", "url": COLLISION_URL, "summary": "Tomorrow is Redemption..."}
    assert simone.candidate_matches_special_report(candidate, special_report()) == (False, "conflicting_explicit_show_identity")


def test_contextual_explicit_event_alias_does_not_cancel_weekly_results_identity():
    report = special_report()
    candidate = {
        "title": "AEW Collision Results 7/25 - Final Stop Before Redemption",
        "url": COLLISION_URL,
    }
    assert simone.candidate_matches_special_report(candidate, report) == (False, "conflicting_explicit_show_identity")
    candidate["special_event_match"] = {"report_key": report["report_key"]}
    assert simone.candidate_matches_special_report(candidate, report) == (False, "conflicting_explicit_show_identity")


def test_brand_name_alone_does_not_block_genuine_branded_special_event():
    report = {"report_key": "special_event_nxt_heatwave_main_2026_08_22", "aliases": ["NXT Heatwave", "Heatwave"]}
    candidate = {"title": "WWE NXT Heatwave Results - Championship Main Event", "url": "https://example.test/wwe-nxt-heatwave-results"}
    assert simone.candidate_matches_special_report(candidate, report) == (True, "special_report_match")
    candidate["special_event_match"] = {"report_key": report["report_key"]}
    assert simone.candidate_matches_special_report(candidate, report) == (True, "structured_special_event_match")


def test_results_oriented_nxt_keyword_still_wins_over_contextual_heatwave_alias():
    report = {"report_key": "special_event_nxt_heatwave_main_2026_08_22", "aliases": ["NXT Heatwave", "Heatwave"]}
    candidate = {"title": "WWE NXT Results - Final Stop Before Heatwave", "url": "https://example.test/wwe-nxt-results-before-heatwave"}
    assert simone.candidate_matches_special_report(candidate, report) == (False, "conflicting_explicit_show_identity")


def test_structured_special_match_contract_respects_explicit_identity():
    report = special_report()
    exact = {"title": "AEW Redemption Results", "url": REDEMPTION_URL, "special_event_match": {"report_key": report["report_key"]}}
    assert simone.candidate_matches_special_report(exact, report) == (True, "structured_special_event_match")
    collision = {"title": "AEW Collision Results 7/25", "url": COLLISION_URL, "special_event_match": {"report_key": report["report_key"]}}
    assert simone.candidate_matches_special_report(collision, report) == (False, "conflicting_explicit_show_identity")
    different = {"title": "Unidentified live coverage", "url": "https://example.test/live", "special_event_match": {"report_key": "another_report"}}
    assert simone.candidate_matches_special_report(different, report) == (False, "event_alias_not_found")
    different_with_generic_evidence = {"title": "AEW Redemption Results", "url": REDEMPTION_URL, "special_event_match": {"report_key": "another_report"}}
    assert simone.candidate_matches_special_report(different_with_generic_evidence, report) == (True, "special_report_match")


def test_genuine_special_and_normal_collision_sources_still_match():
    genuine = {"title": "AEW Redemption Results 7/26 - Six Championships On The Line", "url": REDEMPTION_URL}
    assert simone.candidate_matches_special_report(genuine, special_report()) == (True, "special_report_match")
    collision = next(item for item in json.loads(simone.REPORTS_CONFIG.read_text())["reports"] if item["id"] == "aew_collision")
    chosen, reason = simone.choose_report_candidate([{"title": "AEW Collision Results 7/25", "url": COLLISION_URL, "source": "wrestlinginc"}], collision, "2026-07-25")
    assert chosen is not None and reason == "preferred_source"


def publisher_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "PENDING_REPORTS", tmp_path / "pending.json")
    monkeypatch.setattr(publisher, "ARTIFACT_SIMONE_PUBLISH_FILE", tmp_path / "artifact.json")
    monkeypatch.setattr(publisher, "SIMONE_REPORT_STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(publisher, "SIMONE_REPORT_HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(publisher, "DRY_RUN", False)
    monkeypatch.setattr(publisher, "scrape_article", lambda _url: ([{"text": "A defeated B by pinfall."}], "", None))
    monkeypatch.setattr(publisher, "jarvis_wp_preflight", lambda: (True, "ok", {}))
    monkeypatch.setattr(publisher, "wp_ready", lambda: (True, "ok", {}))


def test_same_batch_keeps_only_explicit_assignment_before_workshop(tmp_path, monkeypatch):
    publisher_paths(tmp_path, monkeypatch)
    calls = []
    scrape_calls = []
    monkeypatch.setattr(publisher, "scrape_article", lambda url: (scrape_calls.append(url) or ([{"text": "A defeated B."}], "", None)))
    monkeypatch.setattr(publisher, "run_report_workshop", lambda job, *_: (calls.append(job["report_key"]) or (8614, {"link": "https://wp/8614"})))
    reports = [
        {"report_key": "aew_collision_2026_07_25", "report_id": "aew_collision", "source_url": COLLISION_URL, "source_title": "AEW Collision Results 7/25"},
        {"report_key": "special_event_aew_redemption_2026_main_2026_07_26", "report_id": "aew_redemption_2026_main", "event_name": "Redemption", "aliases": ["AEW Redemption"], "source_url": COLLISION_URL.rstrip("/") + "?utm_source=x", "source_title": "AEW Collision Results 7/25"},
    ]
    result = publisher.run_simone_report_publisher({"ready_reports": reports})
    assert calls == ["aew_collision_2026_07_25"]
    assert scrape_calls == [COLLISION_URL]
    assert next(item for item in result["results"] if "redemption" in item["report_key"])["reason"] == "source_url_identity_collision"
    assert result["handoff"]["source_url_identity_collisions"] == 1


def test_ambiguous_explicit_same_url_assignments_are_all_blocked(tmp_path, monkeypatch):
    publisher_paths(tmp_path, monkeypatch)
    scrape_calls = []
    workshop_calls = []
    monkeypatch.setattr(publisher, "scrape_article", lambda url: (scrape_calls.append(url) or ([], "", None)))
    monkeypatch.setattr(publisher, "run_report_workshop", lambda *args: workshop_calls.append(args))
    reports = [
        {"report_key": "first", "event_name": "Collision", "source_url": COLLISION_URL, "source_title": "AEW Collision Results"},
        {"report_key": "second", "event_name": "Collision", "source_url": COLLISION_URL.rstrip("/"), "source_title": "AEW Collision Results"},
    ]
    result = publisher.run_simone_report_publisher({"ready_reports": reports})
    assert scrape_calls == [] and workshop_calls == []
    assert [item["report_key"] for item in result["results"]] == ["first", "second"]
    assert all(item["reason"] == "source_url_identity_collision" for item in result["results"])


def test_contextual_collision_redemption_conflict_never_reaches_scrape_or_workshop(tmp_path, monkeypatch):
    publisher_paths(tmp_path, monkeypatch)
    scrape_calls = []
    workshop_calls = []
    monkeypatch.setattr(publisher, "scrape_article", lambda url: (scrape_calls.append(url) or ([], "", None)))
    monkeypatch.setattr(publisher, "run_report_workshop", lambda *args: workshop_calls.append(args))
    source_title = "AEW Collision Results 7/25 - Final Stop Before Redemption"
    reports = [
        {"report_key": "aew_collision_2026_07_25", "report_id": "aew_collision", "source_url": COLLISION_URL, "source_title": source_title},
        {"report_key": "special_event_aew_redemption_2026_main_2026_07_26", "event_name": "Redemption", "source_url": COLLISION_URL, "source_title": source_title},
    ]
    result = publisher.run_simone_report_publisher({"ready_reports": reports})
    assert scrape_calls == [] and workshop_calls == []
    assert len(result["results"]) == 2
    assert all(item["reason"] == "source_url_identity_collision" for item in result["results"])


def test_history_binding_blocks_old_url_but_later_correct_url_publishes(tmp_path, monkeypatch):
    publisher_paths(tmp_path, monkeypatch)
    publisher.SIMONE_REPORT_HISTORY_FILE.write_text(json.dumps({"aew_collision_2026_07_25": {"report_key": "aew_collision_2026_07_25", "source_url": COLLISION_URL, "wp_post_id": 8614}}))
    calls = []
    monkeypatch.setattr(publisher, "run_report_workshop", lambda job, *_: (calls.append(job["source_url"]) or (8616, {"link": "https://wp/8616"})))
    reports = [
        {"report_key": "false_redemption", "source_url": COLLISION_URL.rstrip("/"), "source_title": "Collision"},
        {"report_key": "correct_redemption", "source_url": REDEMPTION_URL, "source_title": "AEW Redemption Results"},
    ]
    result = publisher.run_simone_report_publisher({"ready_reports": reports})
    assert calls == [REDEMPTION_URL]
    assert next(item for item in result["results"] if item["report_key"] == "false_redemption")["reason"] == "source_url_already_bound_to_different_report_key"


def test_old_pending_event_identity_replay_wins_same_url_collision(tmp_path, monkeypatch):
    publisher_paths(tmp_path, monkeypatch)
    old_replay = {
        "report_key": "special_event_aew_redemption_2026_main_2026_07_26",
        "report_id": "aew_redemption_2026_main",
        "event_identity": "Redemption",
        "source_url": REDEMPTION_URL,
        "source_title": "AEW Redemption 2026 Results",
        "status": "waiting_publish_after",
    }
    weak_assignment = {
        "report_key": "unrelated_report",
        "source_url": REDEMPTION_URL + "?utm_source=replay",
        "source_title": "Championship results",
        "status": "waiting_publish_after",
    }
    publisher.PENDING_REPORTS.write_text(json.dumps({"reports": [old_replay, weak_assignment]}))
    scrape_calls = []
    workshop_calls = []
    monkeypatch.setattr(publisher, "scrape_article", lambda url: (scrape_calls.append(url) or ([{"text": "A defeated B."}], "", None)))
    monkeypatch.setattr(publisher, "run_report_workshop", lambda job, *_: (workshop_calls.append(job["report_key"]) or (8617, {"link": "https://wp/8617"})))
    result = publisher.run_simone_report_publisher({"ready_reports": [old_replay, weak_assignment]})
    assert scrape_calls == [REDEMPTION_URL]
    assert workshop_calls == [old_replay["report_key"]]
    assert next(item for item in result["results"] if item["report_key"] == "unrelated_report")["reason"] == "source_url_identity_collision"


def test_old_and_new_special_reservation_identity_shapes_are_explicit():
    base = {"source_url": REDEMPTION_URL, "source_title": "AEW Redemption Results"}
    assert publisher.source_identity_is_explicit({**base, "event_identity": "Redemption"})
    assert publisher.source_identity_is_explicit({**base, "event_identity": "Redemption", "event_name": "Redemption", "aliases": ["AEW Redemption"]})
