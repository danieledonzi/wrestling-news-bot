from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents import andrea_policy_v94_15 as andrea_policy
from agents.master_log_v93_19 import build_master_record
from scripts.daily_editorial_judgment import render_markdown
from scripts.observability_snapshot import build_snapshot
from scripts.patch_runtime_daily_report_v95_19_3 import transform
from send_daily_report import daily_editorial_judgment_body_section

NOW = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)


def _master_row(*, minutes: int, andrea_handoff=None):
    row = {
        "schema_version": "v93_19",
        "recorded_at": (NOW - timedelta(minutes=minutes)).isoformat(),
        "run": {
            "ended_at": (NOW - timedelta(minutes=minutes)).isoformat(),
            "runtime_exit_code": 0,
        },
    }
    if andrea_handoff is not None:
        row["andrea"] = {"handoff": andrea_handoff}
    return row


def test_andrea_policy_exposes_exception_reason_counts(monkeypatch, tmp_path):
    checks = iter([
        {
            "ok": True,
            "decision": "passed_with_exception",
            "reason": "editorial_exception_prevents_false_block",
            "exceptions": ["breaking_exception", "quote_based_exception"],
            "saved_gemini_call": False,
            "andrea_fetch_performed": True,
            "bob_may_reextract": True,
            "body_chars": 300,
            "meaningful_text_blocks": 1,
            "paragraph_count": 1,
            "sentence_count": 2,
            "quote_count": 1,
            "embed_count": 0,
            "source_url": "https://example.test/a",
        },
        {
            "ok": True,
            "decision": "passed_with_exception",
            "reason": "editorial_exception_prevents_false_block",
            "exceptions": ["breaking_exception"],
            "saved_gemini_call": False,
            "andrea_fetch_performed": False,
            "bob_may_reextract": False,
            "body_chars": 350,
            "meaningful_text_blocks": 1,
            "paragraph_count": 1,
            "sentence_count": 3,
            "quote_count": 0,
            "embed_count": 1,
            "source_url": "https://example.test/b",
        },
    ])
    monkeypatch.setattr(andrea_policy, "pre_bob_content_sufficiency_check", lambda _candidate: next(checks))
    monkeypatch.setattr(andrea_policy, "write_json", lambda *_args, **_kwargs: None)

    result = andrea_policy.run_andrea({"selected": [{"url": "a"}, {"url": "b"}], "handoff": {}})

    assert result["handoff"]["andrea_passed_with_exception"] == 2
    assert result["handoff"]["andrea_exception_reasons"] == {
        "breaking_exception": 2,
        "quote_based_exception": 1,
    }
    assert result["handoff"]["andrea_fetch_performed"] == 1
    assert result["handoff"]["andrea_bob_may_reextract"] == 1


def test_master_log_persists_andrea_handoff():
    handoff = {
        "andrea_checked": 2,
        "andrea_passed": 2,
        "andrea_passed_with_exception": 1,
        "andrea_blocked": 0,
        "andrea_exception_reasons": {"breaking_exception": 1},
    }
    record = build_master_record(
        run_summary={"andrea_handoff": handoff},
        timeline=[],
        massy={},
        simone={},
        simone_publish={},
        menzo={},
        bob={},
        alfred={},
        publisher={},
        archivista={},
    )
    assert record["andrea"]["handoff"] == handoff


def test_observability_aggregates_andrea_with_partial_coverage(tmp_path):
    state = tmp_path / "state/newsroom"
    state.mkdir(parents=True)
    rows = [
        _master_row(minutes=30),
        _master_row(
            minutes=5,
            andrea_handoff={
                "andrea_checked": 3,
                "andrea_passed": 3,
                "andrea_blocked": 0,
                "andrea_passed_with_exception": 2,
                "andrea_saved_gemini_calls": 0,
                "andrea_fetch_performed": 1,
                "andrea_bob_may_reextract": 1,
                "andrea_exception_reasons": {
                    "breaking_exception": 2,
                    "quote_based_exception": 1,
                },
            },
        ),
    ]
    (state / "master_log.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )

    snapshot = build_snapshot(NOW - timedelta(hours=24), NOW, tmp_path)
    andrea = snapshot["andrea"]

    assert andrea["available"] is True
    assert (andrea["covered_runs"], andrea["total_runs"]) == (1, 2)
    assert andrea["events"]["checked"] == 3
    assert andrea["events"]["passed_with_exception"] == 2
    assert andrea["exception_reasons"] == {
        "breaking_exception": 2,
        "quote_based_exception": 1,
    }
    assert "andrea_event_stream_partial_coverage" in andrea["schema_warnings"]
    assert snapshot["section_metadata"]["andrea"]["available"] is True


def test_email_body_uses_canonical_metrics_and_classified_warnings(tmp_path):
    path = tmp_path / "judgment.json"
    path.write_text(
        json.dumps(
            {
                "judgment": "BUONO",
                "day_type": "post-show",
                "summary": "Sintesi canonica.",
                "daily_numbers": {
                    "news_published": 25,
                    "reports_published": 1,
                    "alfred": {"warnings": 193, "blockers": 22},
                    "canonical_metrics": {
                        "menzo": {
                            "unique_actionable_candidates": 27,
                            "unique_downstream_handoffs": 25,
                            "unique_final_publications": 25,
                            "handoff_to_publication_ratio": 1.0,
                        },
                        "andrea": {
                            "available": True,
                            "covered_runs": 20,
                            "total_runs": 47,
                            "events": {
                                "checked": 12,
                                "passed": 12,
                                "passed_with_exception": 7,
                                "blocked": 0,
                            },
                            "exception_reasons": {
                                "breaking_exception": 5,
                                "quote_based_exception": 2,
                            },
                        },
                        "alfred": {
                            "articles_reviewed": 25,
                            "articles_with_warnings": 21,
                            "final_blockers": 0,
                        },
                    },
                },
                "translation_warning_analysis": {
                    "available": True,
                    "reproduced": 1,
                    "insufficient_material": 7,
                    "possible_false_positive": 0,
                    "technical": 21,
                },
            }
        ),
        encoding="utf-8",
    )

    text = daily_editorial_judgment_body_section(path)

    assert "Menzo handoff unici / pubblicazioni finali uniche: 25/25" in text
    assert "Rapporto handoff/pubblicazioni Menzo: 100.0%" in text
    assert "Warning confermati / materiale insufficiente / possibili falsi positivi / tecnici: 1/7/0/21" in text
    assert "Andrea copertura: 20/47 run" in text
    assert "breaking_exception (5)" in text
    assert "Alfred warnings/blockers" not in text
    assert "193" not in text


def _runtime_fixture() -> str:
    return '''def main():
    repository_report, diagnostics = run_repository_diagnostics()
    daily_judgment_json = diagnostics["daily_editorial_judgment"][1]
    daily_judgment_error = diagnostics["daily_editorial_judgment"][2]
    daily_judgment_summary = daily_judgment_body_summary(daily_judgment_error)

    ed_news = extract_line(editorial_report, "- News pubblicate dal Publisher:")
    ed_reports = extract_line(editorial_report, "- Report show pubblicati da Simone:")
    ed_html = extract_line(editorial_report, "- HTML finali rilevati nel periodo:")
    ed_fp = extract_line(editorial_report, "- Duplicati footprint rilevati da Menzo:")
    ed_fingerprint = extract_line(editorial_report, "- Duplicati fingerprint rilevati da Menzo:")
    ed_warn = extract_line(editorial_report, "- Warning Alfred:")
    ed_block = extract_line(editorial_report, "- Blocker Alfred:")
    ed_ratio = extract_line(editorial_report, "- Rapporto selected finale / candidati MenzoAI:")

    body = f"""SINTESI EDITORIALE
{ed_news}
{ed_reports}
{ed_html}
{ed_fp}
{ed_fingerprint}
{ed_warn}
{ed_block}
{ed_ratio}

STORY CLUSTER AUDIT v94.7.1

DAILY EDITORIAL JUDGMENT
{daily_judgment_summary}

TRANSLATION QUALITY AUDIT

Nota:
L'audit editoriale v1.1 non usa AI aggiuntiva. Serve a monitorare selezione MenzoAI, distribuzione editoriale, report show, warning Alfred, duplicati e campioni consigliati per revisione umana.
"""
'''


def test_runtime_patcher_is_fail_closed_and_idempotent():
    patched, changes = transform(_runtime_fixture())

    assert "canonical_judgment_helper" in changes
    assert "SINTESI EDITORIALE AUTOREVOLE" in patched
    assert "{ed_news}" not in patched
    assert patched.count("{daily_judgment_summary}") == 1
    assert "diagnostica legacy" in patched

    same, second_changes = transform(patched)
    assert same == patched
    assert second_changes == ["already_patched"]



def test_email_body_renders_missing_menzo_metrics_as_nd(tmp_path):
    path = tmp_path / "judgment_missing_menzo.json"
    path.write_text(
        json.dumps(
            {
                "daily_numbers": {
                    "canonical_metrics": {
                        "menzo": {
                            "unique_actionable_candidates": None,
                            "unique_downstream_handoffs": None,
                            "unique_final_publications": None,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    text = daily_editorial_judgment_body_section(path)

    assert "Menzo candidati unici actionable: n.d." in text
    assert (
        "Menzo handoff unici / pubblicazioni finali uniche: n.d./n.d."
        in text
    )
    assert "None" not in text


def test_email_body_preserves_zero_menzo_metrics(tmp_path):
    path = tmp_path / "judgment_zero_menzo.json"
    path.write_text(
        json.dumps(
            {
                "daily_numbers": {
                    "canonical_metrics": {
                        "menzo": {
                            "unique_actionable_candidates": 0,
                            "unique_downstream_handoffs": 0,
                            "unique_final_publications": 0,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    text = daily_editorial_judgment_body_section(path)

    assert "Menzo candidati unici actionable: 0" in text
    assert (
        "Menzo handoff unici / pubblicazioni finali uniche: 0/0"
        in text
    )


def _minimal_markdown_report(canonical_andrea):
    return {
        "story": {
            "duplicate_candidates": 0,
            "same_story_clusters": 0,
            "same_event_clusters": 0,
            "story_reviews": 0,
            "pairs_above_threshold": 0,
            "suspicious_pairs": [],
            "story_review_items": [],
        },
        "canonical_menzo": {},
        "canonical_andrea": canonical_andrea,
        "canonical_alfred": {},
        "canonical_gemini": {},
        "canonical_simone": {},
        "translation_warning_analysis": {
            "available": False,
            "top_warning_codes": [],
            "top_investigations": [],
            "diagnostic_errors": [],
        },
        "gemini_called": None,
        "judgment": "BUONO",
        "day_type": "standard",
        "summary": "Sintesi.",
        "runs_completed": None,
        "news_published_count": 0,
        "reports_published_count": 0,
        "article_types": {},
        "hard_count": 0,
        "soft_count": 0,
        "softpool": False,
        "observability_snapshot": {},
        "selected": [],
        "pending": [],
        "skipped": [],
        "top_discarded": [],
        "borderline": [],
        "news_records": [],
        "report_records": [],
        "schema_warnings": [],
    }


def test_markdown_reports_unavailable_andrea_as_unavailable():
    text = render_markdown(_minimal_markdown_report({}))

    assert "Andrea event coverage: unavailable" in text
    assert (
        "Andrea checked/passed/passed with exception/blocked events: "
        "n.d./n.d./n.d./n.d."
        in text
    )
    assert "Andrea exception reason occurrences: n.d." in text
    assert "Andrea exception reason occurrences: none recorded" not in text


def test_markdown_reports_full_canonical_andrea_without_run_counts_or_reasons():
    text = render_markdown(
        _minimal_markdown_report(
            {
                "available": True,
                "metadata": {"coverage": "full", "complete_window": True},
                "events": {
                    "checked": 3,
                    "passed": 3,
                    "passed_with_exception": 0,
                    "blocked": 0,
                },
            }
        )
    )

    assert "Andrea event coverage: full" in text
    assert "0/0 runs" not in text
    assert (
        "Andrea checked/passed/passed with exception/blocked events: "
        "3/3/0/0"
        in text
    )
    assert "Andrea exception reason occurrences: n.d." in text
    assert "Andrea exception reason occurrences: none recorded" not in text


def test_markdown_labels_legacy_andrea_exception_reasons_as_diagnostic():
    report = _minimal_markdown_report(
        {
            "available": True,
            "metadata": {"coverage": "full", "complete_window": True},
            "events": {},
        }
    )
    report["observability_snapshot"] = {
        "andrea": {"exception_reasons": {"missing_body": 2}}
    }

    text = render_markdown(report)

    assert "Andrea exception reason occurrences (legacy diagnostic): missing_body (2)" in text
