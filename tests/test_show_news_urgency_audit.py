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
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


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
    write_json(
        tmp_path / "state" / "newsroom" / "publisher_history.json",
        {str(i): history_row(i, "2026-10-04T05:00:00+00:00") for i in range(30)},
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
