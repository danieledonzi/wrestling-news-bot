import json

from agents import menzo_editorial_director_shadow as shadow
from agents import menzo_policy_v93_15 as menzo


def test_historical_weekly_row_does_not_disable_future_urgency(monkeypatch, tmp_path):
    import newsroom_runner
    from modules import simone_report_integrity
    from agents import simone_publisher_v93_18

    pending = tmp_path / "pending_reports.json"
    pending.write_text(json.dumps({"reports": [{
        "report_key": "aew_dynamite_2026_09_24",
        "report_id": "aew_dynamite",
        "status": "published",
    }]}), encoding="utf-8")
    history = tmp_path / "simone_report_history.json"
    history.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(simone_report_integrity, "PENDING_REPORTS", pending)
    monkeypatch.setattr(simone_publisher_v93_18, "SIMONE_REPORT_HISTORY_FILE", history)
    monkeypatch.setattr(shadow, "costly_work_eligibility", lambda: (True, "ok"))
    monkeypatch.setattr(menzo, "published_today_count", lambda: 0)
    monkeypatch.setattr(menzo, "load_authoritative_publisher_history", lambda hours: [])

    board = {
        "news_candidates_for_menzo": [{
            "source": "feed",
            "title": "Next Dynamite standalone development",
            "url": "https://example.test/next-dynamite-story",
            "summary": "fact",
            "show_report_id": "aew_dynamite",
            "corresponding_report_published": False,
        }],
        "published_due_reports": {},
    }

    snapshot, diagnostic, _ = newsroom_runner.capture_editorial_director_opportunity(
        board,
        run_id="run-next-week",
        observation_timestamp="2026-10-09T05:40:00+00:00",
        preserve_active_metadata=True,
    )

    assert diagnostic is None
    cid = snapshot["candidates"][0]["candidate_id"]
    sidecar = snapshot["_active_bob_capacity_metadata"][cid]
    assert sidecar["show_report_id"] == "aew_dynamite"
    assert sidecar["corresponding_report_published"] is False
