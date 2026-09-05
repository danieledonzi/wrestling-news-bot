import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import simone


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
    return {
        "source": source,
        "title": title,
        "url": f"https://www.wrestlinginc.com/{slug}/",
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
