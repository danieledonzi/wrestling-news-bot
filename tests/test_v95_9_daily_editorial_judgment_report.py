from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.daily_editorial_judgment import (
    build_report,
    day_type,
    email_summary,
    generate_daily_editorial_judgment_outputs,
    generate_daily_editorial_judgment_report,
    load_inputs,
    render_markdown,
    top_discarded,
)


def write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_report_generated_with_available_audit_artifacts(tmp_path: Path) -> None:
    menzo = write_json(tmp_path / "menzo.json", {"selected": [{"title": "WWE contract update", "url": "https://x/a", "score": 82, "article_type": "hard_news"}], "pending": [], "skipped": []})
    story = write_json(tmp_path / "story.json", {"same_story_clusters": [{"id": "c1"}], "story_review": [{"title": "Review duplicate"}]})
    out = generate_daily_editorial_judgment_report({"menzo_latest": menzo, "story_cluster_audit": story}, tmp_path / "reports", datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
    text = out.read_text(encoding="utf-8")
    assert out.name == "owtv_daily_editorial_judgment_24h_20260710_120000.md"
    assert "## Daily Editorial Judgment" in text
    assert "Story_review inclusi" in text


def test_structured_json_companion_and_latest_state_are_written(tmp_path: Path) -> None:
    menzo = write_json(tmp_path / "menzo.json", {"selected": [], "pending": [{"title": "WWE title change", "url": "https://x/title", "score": 88, "article_type": "hard_news"}], "skipped": []})
    outputs = generate_daily_editorial_judgment_outputs(
        {"menzo_latest": menzo, "master_log": tmp_path / "missing-master.json"},
        output_dir=tmp_path / "reports",
        state_dir=tmp_path / "state" / "reports",
        now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
    )
    payload = json.loads(outputs["json"].read_text(encoding="utf-8"))
    latest = json.loads(outputs["latest_json"].read_text(encoding="utf-8"))
    assert outputs["markdown"].name == "owtv_daily_editorial_judgment_24h_20260710_120000.md"
    assert outputs["json"].name == "owtv_daily_editorial_judgment_24h_20260710_120000.json"
    assert latest == payload
    assert set(payload) >= {
        "judgment",
        "day_type",
        "summary",
        "daily_numbers",
        "hard_soft_balance",
        "top_discarded_candidates",
        "borderline_published",
        "redundancy_risks",
        "recommended_actions",
        "generated_at",
        "source_artifacts_used",
        "missing_artifacts",
    }
    assert payload["top_discarded_candidates"][0]["url"] == "https://x/title"
    assert any("missing-master.json" in item for item in payload["missing_artifacts"])


def test_missing_artifacts_are_non_fatal(tmp_path: Path) -> None:
    data = load_inputs({"menzo_latest": tmp_path / "missing.json", "story_cluster_audit": tmp_path / "nope.json"})
    text = render_markdown(build_report(data))
    assert "news published: 0" in text
    assert "Nessun forte candidato" in text


def test_top_3_discarded_candidates_are_selected_from_skipped_pending_high_score_items() -> None:
    menzo = {"skipped": [{"title": "Low", "url": "l", "score": 10}], "pending": [
        {"title": "AEW injury", "url": "a", "score": 70, "article_type": "hard_news"},
        {"title": "WWE roster move", "url": "b", "score": 68, "priority": "high"},
        {"title": "Contract business", "url": "c", "score": 66, "article_type": "contract"},
        {"title": "Soft interview", "url": "d", "score": 90, "article_type": "soft_news"},
    ]}
    urls = [x["url"] for x in top_discarded(menzo)]
    assert urls == ["a", "b", "c"]


def test_no_discarded_candidates_case() -> None:
    report = build_report({"menzo_latest": {"selected": [], "pending": [], "skipped": []}})
    assert report["top_discarded"] == []
    assert "Nessun forte candidato" in render_markdown(report)


def test_day_type_classification_intensa_normale_scarica_post_show() -> None:
    assert day_type(20, 0, 3) == "intensa"
    assert day_type(8, 0, 3) == "normale"
    assert day_type(2, 0, 1) == "scarica"
    assert day_type(2, 1, 1) == "post-show"


def test_softpool_used_not_used_explanation() -> None:
    used = build_report({"menzo_latest": {"selected": [{"title": "Soft", "from_softpool": True, "article_type": "soft_news"}], "pending": [], "skipped": []}})
    not_used = build_report({"menzo_latest": {"selected": [], "pending": [], "skipped": []}})
    assert "softpool usato" in used["summary"]
    assert "Softpool non usato" in render_markdown(not_used)


def test_story_review_inclusion() -> None:
    report = build_report({"story_cluster_audit": {"story_reviews": [{"title": "Same story"}]}})
    assert "Same story" in render_markdown(report)


def test_email_summary_generation_if_implemented() -> None:
    report = build_report({"menzo_latest": {"selected": [], "pending": [{"title": "WWE title", "url": "https://x/top", "score": 88, "article_type": "hard_news"}], "skipped": []}})
    summary = email_summary(report)
    assert "Judgment:" in summary
    assert "Top discarded URL: https://x/top" in summary
