from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import agents.simone as simone


def configure_isolated_simone(tmp_path, monkeypatch):
    paths = {
        "REPORT_STATUS_FILE": tmp_path / "report_status.json",
        "REPORT_REGISTRY_FILE": tmp_path / "report_publication_registry.json",
        "MANUAL_RUNS_FILE": tmp_path / "manual_runs.json",
        "SIMONE_EXPECTED_EVENTS_FILE": tmp_path / "simone_expected_events_latest.json",
        "ARTIFACT_EXPECTED_EVENTS_FILE": tmp_path / "artifact_expected_events_latest.json",
        "SIMONE_DECISIONS_FILE": tmp_path / "simone_reports_latest.json",
        "ARTIFACT_SIMONE_FILE": tmp_path / "simone_reports.json",
    }
    for name, path in paths.items():
        monkeypatch.setattr(simone, name, path)
    monkeypatch.setattr(
        simone,
        "rome_now",
        lambda: datetime(2026, 6, 29, 8, 0, tzinfo=ZoneInfo("Europe/Rome")),
    )
    monkeypatch.setattr(simone, "local_now", lambda: datetime(2026, 6, 29, 8, 0))
    return paths


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def run_with_candidates(candidates):
    return simone.run_simone({"version": "test", "report_candidates": candidates})


def test_forbidden_door_special_event_candidate_becomes_ready(tmp_path, monkeypatch):
    configure_isolated_simone(tmp_path, monkeypatch)

    result = run_with_candidates(
        [
            {
                "source": "WrestlingInc",
                "title": "AEW x NJPW Forbidden Door 2026 Results: Full results and recap",
                "url": "https://www.wrestlinginc.com/aew-forbidden-door-2026-results-full-results-recap/",
                "published": "2026-06-29T05:00:00Z",
                "show_hint": "Forbidden Door results",
            }
        ]
    )

    special_ready = result["special_ready"]
    assert len(special_ready) == 1
    assert special_ready[0]["event_key"] == "aew_forbidden_door_2026"
    assert special_ready[0]["night_key"] == "aew_forbidden_door_2026_main"
    assert special_ready[0]["report_type"] == "special_event"
    assert special_ready[0]["counts_as_news"] is False
    assert any(r.get("report_type") == "special_event" for r in result["ready_reports"])


def test_forbidden_door_manual_report_status_is_already_published(tmp_path, monkeypatch):
    paths = configure_isolated_simone(tmp_path, monkeypatch)
    write_json(
        paths["REPORT_STATUS_FILE"],
        {
            "manual:aew_forbidden_door_2026_main": {
                "report_key": "manual:aew_forbidden_door_2026_main",
                "event_key": "aew_forbidden_door_2026_main",
                "night_key": "aew_forbidden_door_2026_main",
                "status": "published",
                "wp_post_id": 7233,
            }
        },
    )

    result = run_with_candidates(
        [
            {
                "source": "WrestlingInc",
                "title": "AEW x NJPW Forbidden Door 2026 Results: Full results and recap",
                "url": "https://www.wrestlinginc.com/aew-forbidden-door-2026-results-full-results-recap/",
                "show_hint": "Forbidden Door results",
            }
        ]
    )

    already = [item for item in result["special_already_published"] if item["night_key"] == "aew_forbidden_door_2026_main"]
    assert len(already) == 1
    assert not [item for item in result["special_ready"] if item["night_key"] == "aew_forbidden_door_2026_main"]
    assert not [item for item in result["special_missing"] if item["night_key"] == "aew_forbidden_door_2026_main"]


def test_great_american_bash_manual_run_is_already_published(tmp_path, monkeypatch):
    paths = configure_isolated_simone(tmp_path, monkeypatch)
    write_json(
        paths["MANUAL_RUNS_FILE"],
        [
            {
                "wp_post_id": 7242,
                "job": {
                    "report_key": "manual:nxt_great_american_bash_2026_main",
                    "event_key": "nxt_great_american_bash_2026_main",
                    "night_key": "nxt_great_american_bash_2026_main",
                    "status": "published",
                },
            }
        ],
    )

    result = run_with_candidates(
        [
            {
                "source": "WrestlingInc",
                "title": "WWE NXT The Great American Bash 2026 Results And Recap",
                "url": "https://www.wrestlinginc.com/nxt-great-american-bash-2026-results-recap/",
                "show_hint": "NXT Great American Bash results",
            }
        ]
    )

    already = [item for item in result["special_already_published"] if item["night_key"] == "nxt_great_american_bash_2026_main"]
    assert len(already) == 1
    assert not [item for item in result["special_ready"] if item["night_key"] == "nxt_great_american_bash_2026_main"]
    assert not [item for item in result["special_missing"] if item["night_key"] == "nxt_great_american_bash_2026_main"]


def test_wrestlinginc_report_hint_without_results_word_becomes_ready(tmp_path, monkeypatch):
    configure_isolated_simone(tmp_path, monkeypatch)

    result = run_with_candidates(
        [
            {
                "source": "WrestlingInc",
                "title": "WWE NXT The Great American Bash 2026: Five Championships On The Line & More",
                "url": "https://www.wrestlinginc.com/2203101/wwe-nxt-the-great-american-bash-2026-five-championships-on-line-more/",
                "kind_hint": "report",
                "show_hint": "NXT Great American Bash",
                "article_type": "RESULTS_REPORT",
            }
        ]
    )

    ready = [item for item in result["special_ready"] if item["night_key"] == "nxt_great_american_bash_2026_main"]
    assert len(ready) == 1
    assert ready[0]["report_type"] == "special_event"
    assert ready[0]["counts_as_news"] is False


def test_preview_card_odds_candidate_does_not_become_ready(tmp_path, monkeypatch):
    configure_isolated_simone(tmp_path, monkeypatch)

    result = run_with_candidates(
        [
            {
                "source": "WrestlingInc",
                "title": "WWE NXT Great American Bash 2026 Preview, Card, Start Time And How To Watch",
                "url": "https://www.wrestlinginc.com/nxt-great-american-bash-2026-preview-card-start-time/",
                "kind_hint": "report",
                "show_hint": "NXT Great American Bash",
                "article_type": "RESULTS_REPORT",
            }
        ]
    )

    assert not [item for item in result["special_ready"] if item["night_key"] == "nxt_great_american_bash_2026_main"]
    missing = [item for item in result["special_missing"] if item["night_key"] == "nxt_great_american_bash_2026_main"]
    assert len(missing) == 1
    assert missing[0]["reason"] == "only_non_report_event_news_found"
