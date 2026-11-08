"""TOTEM-R01 regression: preliminary Ringside articles cannot lock Simone reports."""
from datetime import datetime
from zoneinfo import ZoneInfo
import json

import pytest

from agents import simone
from modules import simone_report_integrity as integrity
from test_wrestleview_fallback_and_materiality import isolate_weekly

ROME = ZoneInfo("Europe/Rome")
SPOILER = "https://www.ringsidenews.com/wwe-smackdown-spoiler-results-november-6-2026"
RESULTS = "https://www.ringsidenews.com/wwe-smackdown-results-november-6-2026"


def source(title, url):
    return {
        "source": "ringsidenews",
        "title": title,
        "url": url,
        "published": "2026-11-06T21:03:45Z",
    }


@pytest.mark.parametrize("title,url", [
    ("WWE SmackDown Spoiler Results for November 6, 2026", SPOILER),
    ("WWE SmackDown Results for November 6, 2026", SPOILER), # slug evidence alone
    ("WWE SmackDown Results Preview for November 6, 2026", RESULTS),
    ("WWE SmackDown Quick Results November 6, 2026", RESULTS),
    ("WWE SmackDown Predictions and Results November 6, 2026", RESULTS),
])
def test_ringside_preliminary_results_rejected(title, url):
    assert not integrity.is_canonical_report_source(source(title, url))


def test_actual_smackdown_spoiler_cannot_match_weekly_or_be_elected():
    report = next(r for r in json.loads(integrity.REPORTS_CONFIG.read_text())["reports"]
                  if r["id"] == "wwe_smackdown")
    earlier = source("WWE SmackDown Spoiler Results for November 6, 2026", SPOILER)
    later = source("WWE SmackDown Results for November 6, 2026", RESULTS)
    assert not simone.candidate_matches_report(earlier, report, "2026-11-06")
    assert simone.candidate_matches_report(later, report, "2026-11-06")
    now = datetime(2026,11,7,7,0,tzinfo=ROME)
    selected, why = simone.choose_report_candidate([earlier, later], report,
        "2026-11-06", now=now, publish_date_iso="2026-11-07")
    assert why == "canonical_results_match"
    assert selected["url"] == RESULTS


def test_special_event_spoiler_results_not_report_substitute():
    report = {"report_key": "special_event_wwe_crown_jewel_2026_main_2026_11_07",
              "aliases": ["WWE Crown Jewel"], "date": "2026-11-07"}
    spoiler = source("WWE Crown Jewel 2026 Spoiler Results November 7",
                     "https://www.ringsidenews.com/wwe-crown-jewel-2026-spoiler-results-november-7")
    assert simone.candidate_matches_special_report(spoiler, report)[0] is False
    eligible = source("WWE Crown Jewel 2026 Results November 7",
                      "https://www.ringsidenews.com/wwe-crown-jewel-2026-results-november-7")
    assert simone.candidate_matches_special_report(eligible, report)[0] is True


def test_invalid_old_ringside_spoiler_lock_can_be_replaced_before_publication(tmp_path, monkeypatch):
    now = datetime(2026,10,16,6,40,tzinfo=ROME)
    paths = isolate_weekly(tmp_path, monkeypatch, now)
    bad_url = "https://www.ringsidenews.com/tna-impact-spoiler-results-october-15-2026"
    good_url = "https://www.ringsidenews.com/tna-impact-results-october-15-2026"
    bad = {
        "report_key": "tna_impact_2026_10_15",
        "report_id": "tna_impact", "date_local": "2026-10-15",
        "publish_date_local": "2026-10-16", "publish_after": "06:30",
        "source": "ringsidenews", "source_title": "TNA Impact Spoiler Results October 15 2026",
        "source_url": bad_url, "normalized_url": bad_url,
        "published": "2026-10-15T21:03:45Z",
        "status": "waiting_publish_after",
        "canonical_source_locked": True, "canonical_identity": "ringsidenews_results",
        "identity_reason": "canonical_source_locked",
    }
    paths["PENDING_REPORTS"].write_text(json.dumps({"reports": [bad]}))
    good = {"source":"ringsidenews", "title":"TNA Impact Results October 15 2026",
            "url":good_url, "published":"2026-10-15T23:00:00Z"}
    res = simone.run_simone({"report_candidates":[good]})
    rows = json.loads(paths["PENDING_REPORTS"].read_text())["reports"]
    invalid = next(x for x in rows if x["source_url"]==bad_url)
    assert invalid["status"] == "invalid_canonical_identity"
    assert invalid["canonical_source_locked"] is False
    valid = next(x for x in rows if x["source_url"]==good_url)
    assert valid["canonical_source_locked"] is True
    assert any(x["source_url"]==good_url for x in res["ready_reports"])


def test_no_results_source_means_wait_not_spoiler_report(tmp_path,monkeypatch):
    now=datetime(2026,10,16,6,40,tzinfo=ROME)
    paths=isolate_weekly(tmp_path,monkeypatch,now)
    earlier={"source":"ringsidenews","title":"TNA Impact Spoiler Results October 15 2026",
             "url":"https://www.ringsidenews.com/tna-impact-spoiler-results-october-15-2026",
             "published":"2026-10-15T21:00:00Z"}
    result=simone.run_simone({"report_candidates":[earlier]})
    assert not result["ready_reports"]
    assert not any(x.get("canonical_source_locked") for x in
                   json.loads(paths["PENDING_REPORTS"].read_text())["reports"])


def test_valid_results_source_remains_eligible_after_show():
    good = source("WWE SmackDown Results for November 6, 2026", RESULTS)
    assert integrity.is_canonical_report_source(good)
    assert integrity.is_canonical_report_source({
        "source":"wrestleview","url":"https://www.wrestleview.com/wwe-smackdown-results-november-6-2026",
        "title":"WWE SmackDown Results November 6 2026"})
