from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts import daily_editorial_judgment as judgment
from scripts.translation_warning_analysis import build_analysis, generate_outputs


NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def write_audit(path: Path, articles: list[dict]) -> Path:
    path.write_text(json.dumps({"generated_at": NOW.isoformat(), "articles": articles}), encoding="utf-8")
    return path


def test_reproduced_has_compact_final_evidence(tmp_path: Path) -> None:
    path = write_audit(tmp_path / "audit.json", [{"key": "a", "title": "A", "issues": ["source_promo_leaked"], "published_text": "Notizia. Use promo code SAVE per ottenere altro. Fine.", "final_published_material_available": True}])
    item = build_analysis(path)["investigations"][0]
    assert item["investigation_status"] == "reproduced"
    assert item["evidence"][0]["material"] == "final_published"
    assert "promo code" in item["evidence"][0]["excerpt"]
    assert len(item["evidence"][0]["excerpt"]) < 200


def test_false_positive_insufficient_technical_and_dedup(tmp_path: Path) -> None:
    path = write_audit(tmp_path / "audit.json", [
        {"key": "fp", "issues": ["wrestling_lexicon_issue"], "possible_false_positive_warnings": ["wrestling_lexicon_issue"]},
        {"key": "missing", "issues": ["paragraph_count_drop"]},
        {"key": "media", "alfred_warnings": [{"code": "image_placeholder_present", "severity": "technical"}]},
        {"key": "both", "issues": ["source_intro_leaked"], "issue_severities": {"source_intro_leaked": "high"}, "alfred_warnings": [{"code": "source_intro_leaked"}]},
    ])
    report = build_analysis(path)
    by_key = {item["article_key"]: item for item in report["investigations"]}
    assert by_key["fp"]["investigation_status"] == "possible_false_positive"
    assert by_key["missing"]["investigation_status"] == "insufficient_material"
    assert by_key["media"]["investigation_status"] == "technical"
    assert by_key["both"]["warning_origins"] == ["alfred", "audit"]
    assert len([item for item in report["investigations"] if item["article_key"] == "both"]) == 1


def test_zero_and_malformed_inputs_write_diagnostic_outputs(tmp_path: Path) -> None:
    empty = write_audit(tmp_path / "empty.json", [])
    outputs = generate_outputs(empty, tmp_path / "reports", tmp_path / "state", now=NOW)
    payload = json.loads(outputs["json"].read_text())
    assert payload["total_investigations"] == 0
    assert "No warnings to investigate" in outputs["markdown"].read_text()
    malformed = tmp_path / "bad.json"
    malformed.write_text("{", encoding="utf-8")
    bad = build_analysis(malformed)
    assert bad["total_investigations"] == 0
    assert bad["errors"][0].startswith("audit_read_failed:")


def test_generated_at_reconstructs_exact_output_filenames(tmp_path: Path) -> None:
    audit = write_audit(tmp_path / "audit.json", [])
    outputs = generate_outputs(audit, tmp_path / "reports", tmp_path / "state", now=NOW)
    payload = json.loads(outputs["json"].read_text())
    generated = datetime.fromisoformat(payload["generated_at"])
    stamp = generated.strftime("%Y%m%d_%H%M%S")
    assert outputs["json"].name == f"owtv_translation_warning_analysis_24h_{stamp}.json"
    assert outputs["markdown"].name == f"owtv_translation_warning_analysis_24h_{stamp}.md"


def test_explicit_path_does_not_discover_real_reports(tmp_path: Path, monkeypatch) -> None:
    explicit = write_audit(tmp_path / "only.json", [])
    monkeypatch.setattr(Path, "glob", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("discovery")))
    assert build_analysis(explicit)["source_audit_path"] == str(explicit)


def test_daily_judgment_loads_and_renders_analysis(tmp_path: Path) -> None:
    analysis = tmp_path / "analysis.json"
    analysis.write_text(json.dumps({"total_investigations": 1, "status_counts": {"reproduced": 1}, "warning_code_counts": {"source_promo_leaked": 1}, "investigations": [{"title": "A", "warning_code": "source_promo_leaked", "investigation_status": "reproduced", "original_severity": "high", "evidence": [{"excerpt": "promo code SAVE"}], "recommended_action": "Review."}]}), encoding="utf-8")
    data = judgment.load_inputs({"translation_warning_analysis": analysis}, now=NOW)
    report = judgment.build_report(data, generated_at=NOW)
    structured = judgment.structured_json(report)
    assert structured["translation_warning_analysis"]["reproduced"] == 1
    markdown = judgment.render_markdown(report)
    assert "Automatic Warning Investigation" in markdown
    assert "promo code SAVE" in markdown


def test_email_failure_does_not_use_stale_latest(tmp_path: Path, monkeypatch) -> None:
    import send_daily_report as daily
    stale = tmp_path / "state/reports/owtv_translation_warning_analysis_latest.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({"generated_at": "2020-01-01T00:00:00+00:00", "total_investigations": 99, "investigations": [{"title": "stale"}]}), encoding="utf-8")
    reports = tmp_path / "reports"
    reports.mkdir()
    stale_markdown = reports / "owtv_translation_warning_analysis_24h_20200101_000000.md"
    stale_markdown.write_text("stale", encoding="utf-8")
    monkeypatch.setattr(daily, "BOT_DIR", tmp_path)
    monkeypatch.setattr(daily, "TRANSLATION_WARNING_LATEST_JSON", stale)
    monkeypatch.setattr(daily.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    markdown, latest, warning = daily.generate_translation_warning_analysis_24h(tmp_path / "audit.json")
    assert markdown is not None and latest == stale
    assert "boom" in warning
    payload = json.loads(stale.read_text())
    assert payload["total_investigations"] == 0
    assert payload["investigations"] == []
    assert "boom" in payload["errors"][0]
    assert daily.newest_translation_warning_analysis_markdown() == markdown
    assert daily.newest_translation_warning_analysis_markdown() != stale_markdown
    data = judgment.load_inputs({"translation_warning_analysis": stale}, now=NOW)
    report = judgment.build_report(data, generated_at=NOW)
    assert report["translation_warning_analysis"]["total"] == 0
    assert "boom" in report["translation_warning_analysis"]["diagnostic_errors"][0]
    attachments = daily.append_translation_warning_analysis_attachments([])
    assert markdown in attachments and stale in attachments and stale_markdown not in attachments


def test_real_module_cli_from_repository_root(tmp_path: Path) -> None:
    audit = write_audit(tmp_path / "audit.json", [])
    repository = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.translation_warning_analysis", "--audit-json", str(audit),
         "--output-dir", str(tmp_path / "reports"), "--state-dir", str(tmp_path / "state")],
        cwd=repository, check=True, capture_output=True, text=True,
    )
    assert "owtv_translation_warning_analysis_24h_" in completed.stdout
    assert (tmp_path / "state/owtv_translation_warning_analysis_latest.json").is_file()


def test_required_execution_order(monkeypatch, tmp_path: Path) -> None:
    import send_daily_report as daily
    calls: list[str] = []
    audit_json = tmp_path / "audit.json"
    monkeypatch.setattr(daily, "generate_translation_quality_audit_24h", lambda: (calls.append("audit") or (None, audit_json, None)))
    monkeypatch.setattr(daily, "generate_translation_warning_analysis_24h", lambda path: (calls.append("analysis") or (None, None, None)))
    monkeypatch.setattr(daily, "generate_daily_editorial_judgment_24h", lambda: (calls.append("judgment") or (None, None, None)))
    daily.generate_daily_diagnostics_24h()
    assert calls == ["audit", "analysis", "judgment"]


def test_existing_attachment_helper_includes_audit_and_current_analysis(tmp_path: Path, monkeypatch) -> None:
    import send_daily_report as daily
    reports = tmp_path / "reports"
    state = tmp_path / "state/reports"
    reports.mkdir(parents=True); state.mkdir(parents=True)
    audit_md = reports / "owtv_translation_quality_audit_24h_20260722.md"
    audit_md.write_text("audit", encoding="utf-8")
    audit_json = state / "owtv_translation_quality_audit_latest.json"
    audit_json.write_text("{}", encoding="utf-8")
    analysis_md = reports / "owtv_translation_warning_analysis_24h_20260722_120000.md"
    analysis_md.write_text("analysis", encoding="utf-8")
    analysis_json = state / "owtv_translation_warning_analysis_latest.json"
    analysis_json.write_text(json.dumps({"generated_at": "2026-07-22T12:00:00+00:00"}), encoding="utf-8")
    monkeypatch.setattr(daily, "BOT_DIR", tmp_path)
    monkeypatch.setattr(daily, "TRANSLATION_QUALITY_LATEST_JSON", audit_json)
    monkeypatch.setattr(daily, "TRANSLATION_WARNING_LATEST_JSON", analysis_json)
    monkeypatch.setattr(daily, "TRANSLATION_QUALITY_CURRENT_FAILED", False)
    attachments = daily.append_translation_quality_audit_attachments([])
    assert attachments == [audit_md, audit_json, analysis_md, analysis_json]


def test_legacy_summary_replaces_stale_analysis_after_audit_failure(tmp_path: Path, monkeypatch) -> None:
    import send_daily_report as daily
    reports = tmp_path / "reports"
    state = tmp_path / "state/reports"
    reports.mkdir(parents=True); state.mkdir(parents=True)
    stale_audit = state / "owtv_translation_quality_audit_latest.json"
    stale_audit.write_text(json.dumps({"count": 77, "articles": []}), encoding="utf-8")
    stale_audit_md = reports / "owtv_translation_quality_audit_24h_20200101.md"
    stale_audit_md.write_text("stale audit", encoding="utf-8")
    stale_analysis = state / "owtv_translation_warning_analysis_latest.json"
    stale_analysis.write_text(json.dumps({"generated_at": "2020-01-01T00:00:00+00:00", "total_investigations": 88}), encoding="utf-8")
    stale_analysis_md = reports / "owtv_translation_warning_analysis_24h_20200101_000000.md"
    stale_analysis_md.write_text("stale analysis", encoding="utf-8")
    monkeypatch.setattr(daily, "BOT_DIR", tmp_path)
    monkeypatch.setattr(daily, "TRANSLATION_QUALITY_LATEST_JSON", stale_audit)
    monkeypatch.setattr(daily, "TRANSLATION_WARNING_LATEST_JSON", stale_analysis)
    monkeypatch.setattr(daily.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit boom")))

    body = daily.translation_quality_audit_summary_24h()
    assert "Articles inspected: 77" not in body
    assert "current analysis unavailable" not in body
    assert "audit boom" in body
    current = json.loads(stale_analysis.read_text())
    assert current["total_investigations"] == 0 and current["investigations"] == []
    assert "audit boom" in current["errors"][0]
    current_md = daily.newest_translation_warning_analysis_markdown()
    assert current_md is not None and current_md != stale_analysis_md
    attachments = daily.append_translation_quality_audit_attachments([])
    assert current_md in attachments and stale_analysis in attachments
    assert stale_analysis_md not in attachments
    assert stale_audit not in attachments and stale_audit_md not in attachments
