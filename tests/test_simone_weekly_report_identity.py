import json
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import simone
from modules import simone_report_integrity


REPORTS = {
    report["id"]: report
    for report in json.loads((Path(__file__).parents[1] / "config" / "reports_v92.json").read_text())["reports"]
}


@pytest.fixture(autouse=True)
def no_dynamic_special_events(tmp_path, monkeypatch):
    config = tmp_path / "special_events.json"
    config.write_text('{"events": []}')
    monkeypatch.setattr(simone, "SPECIAL_EVENTS_CONFIG", config)


def candidate(title, *, source="wrestlinginc", summary=""):
    slug = simone.normalize(title).replace(" ", "-")
    domain = "www.ringsidenews.com" if source == "ringsidenews" else "www.wrestlinginc.com"
    return {
        "source": source,
        "title": title,
        "url": f"https://{domain}/{slug}/",
        "summary": summary,
    }


@pytest.mark.parametrize(
    ("report_id", "title", "date_iso"),
    [
        ("tna_impact", "TNA Impact Results 9/3/2026", "2026-09-03"),
        ("tna_impact", "TNA Thursday Night Impact Results 9/3/2026", "2026-09-03"),
        ("tna_impact", "TNA Thursday Night Impact Results 9/3 - International Title #1 Contenders Match & More", "2026-09-03"),
        ("wwe_smackdown", "WWE SmackDown Results 9/4/2026", "2026-09-04"),
        ("wwe_smackdown", "WWE Friday Night SmackDown Results 9/4/2026", "2026-09-04"),
        ("wwe_smackdown", "WWE Friday Night SmackDown Results 9/4 - Undisputed Title Match & More", "2026-09-04"),
        ("aew_dynamite", "AEW Wednesday Night Dynamite Results 9/2/2026", "2026-09-02"),
        ("aew_dynamite", "AEW Dynamite Rebel Heart Results 9/9/2026", "2026-09-09"),
        ("aew_dynamite", "AEW Dynamite Grand Slam Mexico Results 8/5/2026", "2026-08-05"),
        ("aew_dynamite", "AEW Dynamite Results 9/9/2026", "2026-09-09"),
    ],
)
def test_configured_result_identity_accepts_normal_and_modified_titles(report_id, title, date_iso):
    assert simone.candidate_report_identity(candidate(title), REPORTS[report_id], date_iso) == (
        True,
        "canonical_results_match",
    )


@pytest.mark.parametrize(
    ("item", "report_id", "date_iso", "reason"),
    [
        (candidate("WWE Friday Night SmackDown Preview 9/4/2026"), "wwe_smackdown", "2026-09-04", "waiting_for_canonical_results_source"),
        (candidate("TNA Thursday Night Impact Results 9/3/2026"), "tna_impact", "2026-08-27", "rejected_conflicting_weekly_identity"),
        (candidate("WWE Raw Results 9/4/2026"), "wwe_smackdown", "2026-09-04", "rejected_conflicting_weekly_identity"),
        ({**candidate("TNA Impact Results 9/3/2026", source="another-source"), "url": "https://example.com/tna-impact-results"}, "tna_impact", "2026-09-03", "waiting_for_canonical_results_source"),
        (
            candidate("Championship Results 9/4/2026", summary="WWE Friday Night SmackDown Results"),
            "wwe_smackdown",
            "2026-09-04",
            "rejected_conflicting_weekly_identity",
        ),
    ],
)
def test_weekly_identity_protections_remain_mandatory(item, report_id, date_iso, reason):
    assert simone.candidate_report_identity(item, REPORTS[report_id], date_iso) == (False, reason)


def test_special_event_results_remain_rejected_as_weekly():
    item = candidate("TNA Victory Road Results 9/3/2026")
    item["special_event_match"] = {
        "canonical_identity": "wrestlinginc_results",
        "report_key": "special_event_tna_victory_road_2026_main_2026_09_03",
        "aliases": ["TNA Victory Road"],
        "date_local": "2026-09-03",
    }
    assert simone.candidate_report_identity(item, REPORTS["tna_impact"], "2026-09-03") == (
        False,
        "rejected_special_event_as_weekly",
    )


def test_empty_show_name_with_generic_keywords_fails_closed():
    report = {"show_name": "", "match_keywords": ["wwe", "weekly recap"]}
    item = candidate("Wrestling Results 9/4/2026")
    assert simone.candidate_report_identity(item, report, "2026-09-04") == (
        False,
        "rejected_conflicting_weekly_identity",
    )


def no_mercy_registry():
    return {
        "events": [{
            "key": "nxt_no_mercy_2026",
            "promotion": "WWE",
            "event_name": "No Mercy",
            "status": "confirmed",
            "aliases": ["NXT No Mercy", "No Mercy"],
            "nights": [{"night_key": "nxt_no_mercy_main", "date_local": "2026-09-01", "enabled": True}],
        }],
    }


def test_structured_special_match_cannot_steal_modified_weekly_results():
    item = candidate("WWE Tuesday Night NXT Results 9/1 - Final Stop Before No Mercy")
    item["special_event_match"] = {
        "canonical_identity": "wrestlinginc_results",
        "report_key": "special_event_nxt_no_mercy_main_2026_09_01",
        "aliases": ["NXT No Mercy", "No Mercy"],
        "date_local": "2026-09-01",
    }
    assert simone.candidate_report_identity(item, REPORTS["wwe_nxt"], "2026-09-01") == (
        True,
        "canonical_results_match",
    )


def test_dynamic_special_match_cannot_steal_modified_weekly_results():
    item = candidate("WWE Tuesday Night NXT Results 9/1 - Final Stop Before No Mercy")
    assert simone_report_integrity.dynamic_special_event_match(item, no_mercy_registry()) == (
        None,
        "rejected_conflicting_weekly_identity",
    )


def test_genuine_special_event_still_matches_without_weekly_results_identity():
    item = candidate("NXT No Mercy Results 9/1 - Championship Match")
    match, reason = simone_report_integrity.dynamic_special_event_match(item, no_mercy_registry())
    assert reason == "canonical_results_match"
    assert match is not None and match["event_key"] == "nxt_no_mercy_2026"


def test_bounded_modifier_does_not_turn_special_event_into_weekly_identity():
    assert not simone_report_integrity.matches_weekly_result_identity(
        "NXT No Mercy Results 9/1/2026", REPORTS["wwe_nxt"]
    )


def test_weekly_fallback_waits_before_cutoff_and_is_selected_after_cutoff():
    fallback = candidate("AEW Dynamite Results 9/9/2026", source="ringsidenews")
    report = REPORTS["aew_dynamite"]
    before = datetime(2026, 9, 10, 8, 29, tzinfo=ZoneInfo("Europe/Rome"))
    after = datetime(2026, 9, 10, 8, 30, tzinfo=ZoneInfo("Europe/Rome"))

    assert simone.choose_report_candidate([fallback], report, "2026-09-09", now=before) == (
        None, "waiting_for_canonical_results_source"
    )
    assert simone.choose_report_candidate([fallback], report, "2026-09-09", now=after) == (
        fallback, "fallback_results_match"
    )


def test_preferred_weekly_source_wins_over_fallback_after_cutoff():
    preferred = candidate("AEW Dynamite Rebel Heart Results 9/9/2026")
    fallback = candidate("AEW Dynamite Results 9/9/2026", source="ringsidenews")
    after = datetime(2026, 9, 10, 9, 0, tzinfo=ZoneInfo("Europe/Rome"))

    assert simone.choose_report_candidate(
        [fallback, preferred], REPORTS["aew_dynamite"], "2026-09-09", now=after
    ) == (preferred, "canonical_results_match")


def test_wrong_show_and_date_remain_rejected_with_branded_identity():
    item = candidate("AEW Dynamite Rebel Heart Results 9/9/2026")
    assert simone.candidate_report_identity(item, REPORTS["aew_collision"], "2026-09-09")[0] is False
    assert simone.candidate_report_identity(item, REPORTS["aew_dynamite"], "2026-09-02")[0] is False


def test_existing_weekly_source_lock_cannot_be_replaced_by_later_fallback(tmp_path):
    path = tmp_path / "pending.json"
    identity = {
        "report_key": "aew_dynamite_2026_09_09",
        "report_id": "aew_dynamite",
        "date_local": "2026-09-09",
    }
    now = datetime(2026, 9, 10, 9, 0, tzinfo=ZoneInfo("Europe/Rome"))
    preferred = candidate("AEW Dynamite Rebel Heart Results 9/9/2026")
    fallback = candidate("AEW Dynamite Results 9/9/2026", source="ringsidenews")

    first = simone_report_integrity.reserve_report(preferred, identity, now=now, pending_path=path)
    retained = simone_report_integrity.reserve_report(fallback, identity, now=now, pending_path=path)
    rows = json.loads(path.read_text())["reports"]

    assert retained["source_url"] == first["source_url"] == preferred["url"].rstrip("/")
    assert next(row for row in rows if row["source"] == "ringsidenews")["status"] == "later_canonical_candidate_ignored"
