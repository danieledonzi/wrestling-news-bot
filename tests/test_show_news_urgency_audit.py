from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import show_news_urgency_audit as audit


NOW = datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_master(root: Path, rows: list[dict]) -> None:
    path = root / "state" / "newsroom" / "master_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [{"schema_version": audit.MASTER_SCHEMA_VERSION, **row} for row in rows]
    path.write_text("\n".join(json.dumps(row) for row in normalized) + "\n", encoding="utf-8")


def history_row(index: int, published_at: str) -> dict:
    return {
        "source_url": f"https://published.test/{index}",
        "status": "publish",
        "published_at": published_at,
        "title_it": f"Published {index}",
    }


def test_no_opportunity_distinguishes_inactive_feature_from_failure(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [], "pending": []},
        "publisher": {"results": []},
    }])
    history = {str(i): history_row(i, "2026-10-04T05:00:00+00:00") for i in range(30)}
    history["future"] = history_row(999, "2026-10-05T05:00:00+00:00")
    write_json(
        tmp_path / "state" / "newsroom" / "publisher_history.json",
        history,
    )

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "no_opportunity"
    assert result["runs"] == 1
    assert result["daily_ceiling"]["published_today_local"] == 30
    assert result["checks"]["daily_ceiling_respected"] is True
    assert result["show_news_urgency"]["opportunity_observed"] is False


def test_urgency_promotion_and_publisher_provenance_are_linked(tmp_path: Path) -> None:
    url = "https://news.test/show-update"
    item = {
        "source_url": url,
        "show_report_id": "aew_dynamite",
        "corresponding_report_published": False,
        "editorial_director": {
            "editorial_class": "SHOULD_PUBLISH",
            "recommended_action": "DEFER",
        },
        "scheduling_override": {
            "reason": audit.URGENCY_REASON,
            "original_recommended_action": "DEFER",
        },
    }
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [item], "pending": []},
        "publisher": {"results": [{**item, "status": "published"}]},
    }])
    write_json(
        tmp_path / "state" / "newsroom" / "publisher_history.json",
        {url: {"source_url": url, "status": "publish", "published_at": "2026-10-04T07:35:00+00:00"}},
    )

    result = audit.build_audit(root=tmp_path, now=NOW)

    urgency = result["show_news_urgency"]
    assert result["status"] == "ok"
    assert urgency["opportunity_observed"] is True
    assert urgency["show_identity_unique_urls"] == 1
    assert urgency["promoted_unique_urls"] == 1
    assert urgency["published_with_provenance_unique_urls"] == 1
    assert urgency["lost_provenance_urls"] == []
    assert result["checks"]["urgency_provenance_preserved"] is True


def test_audit_flags_ceiling_post_report_and_lost_provenance(tmp_path: Path) -> None:
    url = "https://news.test/bad-urgency"
    selected = {
        "source_url": url,
        "show_report_id": "wwe_raw",
        "corresponding_report_published": True,
        "editorial_director": {
            "editorial_class": "SHOULD_PUBLISH",
            "recommended_action": "DEFER",
        },
        "scheduling_override": {"reason": audit.URGENCY_REASON},
    }
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [selected], "pending": []},
        "publisher": {
            "results": [{
                "source_url": url,
                "status": "published",
            }]
        },
    }])
    history = {
        str(i): history_row(i, "2026-10-04T05:00:00+00:00")
        for i in range(31)
    }
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", history)

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "attention"
    assert result["checks"] == {
        "daily_ceiling_respected": False,
        "no_post_report_urgency": False,
        "urgency_provenance_preserved": False,
    }
    assert result["daily_ceiling"]["published_today_local"] == 31
    assert result["show_news_urgency"]["urgency_after_report_urls"] == [url]
    assert result["show_news_urgency"]["lost_provenance_urls"] == [url]


def test_master_log_persists_urgency_and_capacity_observability(tmp_path: Path) -> None:
    from agents.master_log_v93_19 import build_master_record

    url = "https://news.test/persisted-urgency"
    item = {
        "source_url": url,
        "show_report_id": "wwe_raw",
        "event_report_key": "wwe_raw_2026_10_04",
        "special_event_match": {"report_key": "special_raw", "event_key": "raw"},
        "corresponding_report_published": False,
        "editorial_director": {
            "editorial_class": "SHOULD_PUBLISH",
            "recommended_action": "DEFER",
        },
        "scheduling_override": {
            "reason": audit.URGENCY_REASON,
            "original_recommended_action": "DEFER",
        },
    }
    record = build_master_record(
        run_summary={"started_at": NOW.isoformat(), "ended_at": NOW.isoformat()},
        timeline=[],
        massy={},
        simone={},
        simone_publish={},
        menzo={"selected": [item], "pending": []},
        bob={},
        alfred={},
        publisher={
            "results": [{**item, "status": "published"}],
            "skipped_approved_articles": [{
                "source_url": "https://news.test/capacity",
                "status": "skipped_capacity",
                "reason": "daily_news_ceiling:30",
            }],
        },
        archivista={},
    )

    assert record["schema_version"] == audit.MASTER_SCHEMA_VERSION
    selected = record["menzo"]["selected"][0]
    assert selected["show_report_id"] == "wwe_raw"
    assert selected["editorial_director"]["recommended_action"] == "DEFER"
    assert selected["scheduling_override"]["reason"] == audit.URGENCY_REASON
    assert record["publisher"]["results"][0]["scheduling_override"]["reason"] == audit.URGENCY_REASON
    skipped = record["publisher"]["skipped_approved_articles"][0]
    assert skipped["status"] == "skipped_capacity"
    assert skipped["reason"] == "daily_news_ceiling:30"

    write_master(tmp_path, [record])
    write_json(
        tmp_path / "state" / "newsroom" / "publisher_history.json",
        {url: {"source_url": url, "status": "publish", "published_at": NOW.isoformat()}},
    )
    result = audit.build_audit(root=tmp_path, now=NOW)
    assert result["daily_ceiling"]["skipped_capacity_unique_urls"] == 1
    assert result["daily_ceiling"]["daily_ceiling_skips_unique_urls"] == 1
    assert result["show_news_urgency"]["promoted_unique_urls"] == 1
    assert result["show_news_urgency"]["published_with_provenance_unique_urls"] == 1


def test_missing_authoritative_sources_are_unavailable(tmp_path: Path) -> None:
    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "unavailable"
    assert result["checks"]["daily_ceiling_respected"] is None
    assert result["checks"]["no_post_report_urgency"] is None
    assert result["checks"]["urgency_provenance_preserved"] is None
    assert "missing_master_log" in result["warnings"]
    assert "missing_publisher_history" in result["warnings"]


def test_malformed_publisher_history_is_unavailable(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [], "pending": []},
        "publisher": {"results": []},
    }])
    history = tmp_path / "state" / "newsroom" / "publisher_history.json"
    history.write_text("{", encoding="utf-8")

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "unavailable"
    assert result["checks"]["daily_ceiling_respected"] is None
    assert any(str(w).startswith("publisher_history_read_failed:") for w in result["warnings"])


def test_undated_master_row_makes_urgency_coverage_partial(tmp_path: Path) -> None:
    master = tmp_path / "state" / "newsroom" / "master_log.jsonl"
    master.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "schema_version": audit.MASTER_SCHEMA_VERSION,
            "run": {"started_at": "2026-10-04T07:30:00+00:00"},
            "menzo": {"selected": [], "pending": []},
            "publisher": {"results": []},
        },
        {
            "schema_version": audit.MASTER_SCHEMA_VERSION,
            "menzo": {"selected": [{"source_url": "https://news.test/hidden-opportunity", "show_report_id": "wwe_raw"}], "pending": []},
            "publisher": {"results": []},
        },
    ]
    master.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", {})

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "partial_coverage"
    assert result["source_coverage"]["master_log"]["undated_rows"] == 1
    assert result["source_coverage"]["master_log"]["urgency_complete_window"] is False
    assert result["show_news_urgency"]["opportunity_observed"] is None
    assert result["checks"]["no_post_report_urgency"] is None
    assert result["checks"]["urgency_provenance_preserved"] is None
    assert "master_log_undated_rows:1" in result["warnings"]


def test_malformed_master_log_is_unavailable(tmp_path: Path) -> None:
    master = tmp_path / "state" / "newsroom" / "master_log.jsonl"
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_text("{not-json}\n", encoding="utf-8")
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", {})

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "unavailable"
    assert result["checks"]["no_post_report_urgency"] is None
    assert result["checks"]["urgency_provenance_preserved"] is None
    assert "master_log_no_parseable_rows" in result["warnings"]


def test_pending_sample_truncation_makes_urgency_coverage_partial(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {
            "selected": [],
            "pending": [],
            "pending_sample_truncated": True,
            "pending_total": 21,
            "pending_sample_size": 20,
        },
        "publisher": {"results": []},
    }])
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", {})

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "partial_coverage"
    assert result["source_coverage"]["master_log"]["pending_truncated_runs"] == 1
    assert result["source_coverage"]["master_log"]["urgency_complete_window"] is False
    assert result["checks"]["no_post_report_urgency"] is None
    assert result["checks"]["urgency_provenance_preserved"] is None
    assert "urgency_pending_sample_truncated_runs:1" in result["warnings"]


def test_record_level_corrupt_publisher_history_is_unavailable(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [], "pending": []},
        "publisher": {"results": []},
    }])
    write_json(
        tmp_path / "state" / "newsroom" / "publisher_history.json",
        {"good": history_row(1, "2026-10-04T05:00:00+00:00"), "bad": "corrupt"},
    )

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "unavailable"
    assert result["checks"]["daily_ceiling_respected"] is None
    assert result["source_coverage"]["publisher_history"]["malformed_records"] == 1
    assert "publisher_history_malformed_records:1" in result["warnings"]


def test_incomplete_dictionary_history_record_is_unavailable(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [], "pending": []},
        "publisher": {"results": []},
    }])
    write_json(
        tmp_path / "state" / "newsroom" / "publisher_history.json",
        {"broken": {"status": "publish"}},
    )

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "unavailable"
    assert result["checks"]["daily_ceiling_respected"] is None
    assert result["source_coverage"]["publisher_history"]["malformed_records"] == 1


def test_audit_uses_same_legacy_success_status_and_timestamp_as_ceiling(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [], "pending": []},
        "publisher": {"results": []},
    }])
    history = {}
    for index in range(30):
        history[str(index)] = {
            "source_url": f"https://legacy.test/{index}",
            "status": "succeeded" if index == 0 else "publish",
            "updated_at": "2026-10-04T05:00:00+00:00" if index == 0 else None,
            "published_at": None if index == 0 else "2026-10-04T05:00:00+00:00",
        }
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", history)

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["daily_ceiling"]["published_today_local"] == 30
    assert result["checks"]["daily_ceiling_respected"] is True


def test_daily_ceiling_counts_successful_records_not_unique_urls(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [], "pending": []},
        "publisher": {"results": []},
    }])
    history = [
        {
            "source_url": f"https://published.test/{min(index, 29)}",
            "status": "publish",
            "published_at": "2026-10-04T05:00:00+00:00",
        }
        for index in range(31)
    ]
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", history)

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["daily_ceiling"]["published_today_local"] == 31
    assert result["daily_ceiling"]["published_unique_last_window"] == 30
    assert result["checks"]["daily_ceiling_respected"] is False
    assert result["status"] == "attention"


def test_show_identity_without_eligible_urgency_remains_no_opportunity(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {
            "selected": [{
                "source_url": "https://news.test/normal-show-selection",
                "show_report_id": "wwe_raw",
                "corresponding_report_published": False,
                "editorial_director": {
                    "editorial_class": "MUST_PUBLISH",
                    "recommended_action": "SELECT",
                },
            }],
            "pending": [],
        },
        "publisher": {"results": []},
    }])
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", {})

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["show_news_urgency"]["show_identity_unique_urls"] == 1
    assert result["show_news_urgency"]["promoted_unique_urls"] == 0
    assert result["show_news_urgency"]["pending_eligible_unique_urls"] == 0
    assert result["show_news_urgency"]["opportunity_observed"] is False
    assert result["status"] == "no_opportunity"


def test_legacy_master_rows_report_partial_coverage(tmp_path: Path) -> None:
    write_master(tmp_path, [{
        "schema_version": "v93_19_newsroom_master_log",
        "run": {"started_at": "2026-10-04T07:30:00+00:00"},
        "menzo": {"selected": [], "pending": []},
        "publisher": {"results": []},
    }])
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", {})

    result = audit.build_audit(root=tmp_path, now=NOW)

    assert result["status"] == "partial_coverage"
    assert result["source_coverage"]["master_log"]["urgency_supported_runs"] == 0
    assert result["source_coverage"]["master_log"]["urgency_complete_window"] is False
    assert result["checks"]["daily_ceiling_respected"] is True
    assert result["checks"]["no_post_report_urgency"] is None
    assert result["checks"]["urgency_provenance_preserved"] is None
    assert result["show_news_urgency"]["opportunity_observed"] is None


def test_generate_outputs_writes_latest_json_and_markdown(tmp_path: Path) -> None:
    write_master(tmp_path, [])
    write_json(tmp_path / "state" / "newsroom" / "publisher_history.json", {})

    outputs = audit.generate_outputs(root=tmp_path, now=NOW)

    assert outputs["json"].exists()
    assert outputs["markdown"].exists()
    assert outputs["latest_json"].exists()
    latest = json.loads(outputs["latest_json"].read_text(encoding="utf-8"))
    assert latest["schema_version"] == "show_news_urgency_audit_v1"
    assert "Show News Urgency Audit" in outputs["markdown"].read_text(encoding="utf-8")


def test_email_body_section_marks_no_opportunity(tmp_path: Path, monkeypatch) -> None:
    import send_daily_report as daily

    state = tmp_path / "state" / "reports"
    state.mkdir(parents=True)
    payload = {
        "status": "no_opportunity",
        "runs": 48,
        "daily_ceiling": {
            "timezone": "Europe/Rome",
            "published_today_local": 20,
            "published_unique_last_window": 42,
            "limit": 30,
            "skipped_capacity_unique_urls": 0,
            "daily_ceiling_skips_unique_urls": 0,
        },
        "show_news_urgency": {
            "opportunity_observed": False,
            "show_identity_unique_urls": 0,
            "promoted_unique_urls": 0,
            "published_with_provenance_unique_urls": 0,
            "pending_eligible_unique_urls": 0,
        },
        "checks": {
            "daily_ceiling_respected": True,
            "no_post_report_urgency": True,
            "urgency_provenance_preserved": True,
        },
    }
    path = state / "owtv_show_news_urgency_audit_latest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(daily, "SHOW_NEWS_URGENCY_LATEST_JSON", path)

    body = daily.show_news_urgency_audit_body_section(path)

    assert "20 / 30" in body
    assert "Stato audit: no_opportunity" in body
    assert "non è stata esercitata" in body
    assert body.count("OK") == 3
