from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agents.canonical_artifact_index import CanonicalArtifactIndex
from agents.canonical_event_ledger import content_id
from agents import source_body
from scripts import translation_quality_audit as audit
from scripts import translation_warning_analysis as analysis
from scripts import build_weekly_pattern_report as weekly


@pytest.mark.parametrize("case", json.loads((Path(__file__).parent / "fixtures/translation_quality/tq1_corpus.json").read_text()), ids=lambda case: case["id"])
def test_minimized_regression_corpus(tmp_path, case):
    row = investigate(tmp_path, {"key": case["id"], "alfred_warnings": [case["code"]],
                               "original_text": case["source"], "published_text": case["final"]})
    assert row["investigation_status"] == case["status"]
    assert row["semantic_verdict"] == "not_assessed"


def investigate(tmp_path, article):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps({"articles": [article]}))
    return analysis.build_analysis(path)["investigations"][0]


@pytest.mark.parametrize("code,source,final", [
    ("possible_match_mistranslation", "He returned to the ring.", "È pronto a rimettersi in gioco."),
    ("possible_release_mistranslation", "He never made the comments.", "Non ha mai rilasciato le dichiarazioni."),
    ("possible_retirement_mistranslation", "She announced her retirement.", "Ha annunciato il pensionamento."),
    ("possible_cleared_mistranslation", "He is cleared to wrestle.", "È pulito per lottare."),
    ("promo_gender_warning", "A promo.", "Ha tenuto una promo."),
    ("chop_gender_warning", "Chops.", "Ha colpito con gli chop."),
    ("ai_style_or_literalism_warning", "A television segment.", "Una presenza in televisione nazionale."),
])
def test_lexical_signals_are_reproduced_without_semantic_verdict(tmp_path, code, source, final):
    row = investigate(tmp_path, {"key": "a", "alfred_warnings": [code], "original_text": source, "published_text": final})
    assert row["investigation_status"] == "reproduced"
    assert row["semantic_verdict"] == "not_assessed"
    assert any(e["material"] == "final_published" for e in row["evidence"])


def test_stage_comparison_keeps_bob_and_alfred_separate(tmp_path):
    row = investigate(tmp_path, {"key": "a", "issues": ["source_promo_leaked"],
        "translated_candidate_text": "Use promo code SAVE.", "alfred_approved_text": "Notizia completa.",
        "published_text": "Notizia completa."})
    assert row["investigation_status"] == "not_reproduced"
    assert row["stage_trace"]["bob"]["trigger_present"] is True
    assert row["stage_trace"]["alfred"]["trigger_present"] is False
    assert row["stage_trace"]["final"]["trigger_present"] is False


def test_residual_english_uses_full_audit_predicate(tmp_path):
    row = investigate(tmp_path, {"key": "a", "issues": ["untranslated_quote_or_residual_english"],
                                "published_text": "Ha conquistato una title shot al pay-per-view."})
    assert row["investigation_status"] == "not_reproduced"
    assert row["semantic_verdict"] == "not_assessed"


def test_legacy_material_aliases_remain_supported(tmp_path):
    row = investigate(tmp_path, {"key": "a", "issues": ["source_promo_leaked"],
                                "final_html": "<p>Use promo code SAVE.</p>"})
    assert row["investigation_status"] == "reproduced"


@pytest.mark.parametrize("article,reason", [
    ({"issues": ["blockquote_missing_for_long_quotes"], "published_text": "Prosa appiattita."}, "final_structure_unavailable"),
    ({"issues": ["paragraph_count_drop"], "published_text": "Prosa", "final_markup_available": True}, "source_structure_unavailable"),
    ({"issues": ["possible_match_mistranslation"], "published_text": "Il gioco."}, "source_material_unavailable"),
    ({"issues": ["unknown_code"], "published_text": "Prosa."}, "evaluator_unavailable"),
    ({"issues": ["source_promo_leaked"]}, "final_material_unavailable"),
])
def test_unavailable_material_and_evaluators_have_distinct_reasons(tmp_path, article, reason):
    row = investigate(tmp_path, {"key": "a", **article})
    assert row["investigation_status"] == "insufficient_material"
    assert row["unavailable_reason"] == reason


def test_title_length_reproduces_alfred_threshold_without_body(tmp_path):
    for size, expected in [(95, "not_reproduced"), (96, "reproduced")]:
        row = investigate(tmp_path, {"key": "a", "title": "x" * size, "alfred_warnings": ["title_too_long"]})
        assert row["investigation_status"] == expected


def test_flattened_final_text_is_not_evidence_of_missing_blockquotes():
    a = audit.ArticleAudit(key="a")
    audit.set_final_published_material(a, 'Ha detto: "' + "Una dichiarazione lunga. " * 20 + '"', 1000, "canonical_json")
    audit.run_checks(a)
    assert a.final_markup_available is False
    assert "blockquote_missing_for_long_quotes" not in a.issues
    audit.merge_final_html(a, '<p>Ha detto:</p><blockquote>"' + "Una dichiarazione lunga. " * 20 + '"</blockquote>', "final.html", 1100)
    audit.run_checks(a)
    assert a.final_markup_available is True and a.blockquote_count == 1
    assert "blockquote_missing_for_long_quotes" not in a.issues


def test_canonical_bob_and_alfred_bodies_resolved_in_publication_instance(tmp_path, monkeypatch):
    url = "https://example.com/story"
    cid = content_id({"source_url": url})
    index = CanonicalArtifactIndex("published-run", tmp_path / "state/newsroom/canonical_artifact_index.jsonl",
                                  tmp_path / "material", enabled=True, repository_root=tmp_path)
    text = "Complete source sentence. " * 20
    contract = {"schema": source_body.SCHEMA, "complete": True, "cleaned_full_text": text,
        "sha256": hashlib.sha256(" ".join(text.split()).encode()).hexdigest(), "char_count": len(text),
        "provenance": {"extractor": "bob.extract_elements", "source_url": url, "body_complete": True},
        "coverage": {"extraction_finished": True}}
    index.observe_bob({"articles": [{"source_url": url, "status": "ready_for_alfred",
        "canonical_source_body": contract, "body_html": "<p>Bob: una promo.</p>"}]})
    index.observe_alfred({"reviews": [{"source_url": url, "decision": "approved", "warnings": [],
        "approved_article": {"source_url": url, "body_html": "<p>Alfred: un promo.</p>"}}]})
    index.observe_publisher({"results": [{"source_url": url, "status": "published", "published_cleaned_full_text": "Finale: un promo."}]})
    # A later failed attempt must never replace the published instance's Bob.
    later = CanonicalArtifactIndex("failed-run", index.index_path, tmp_path / "material", enabled=True, repository_root=tmp_path)
    later.observe_bob({"articles": [{"source_url": url, "status": "ready_for_alfred", "body_html": "<p>Later</p>"}]})
    monkeypatch.setattr(audit, "build_observability_snapshot", lambda *a, **k: {
        "section_metadata": {"p1_1_lifecycle": {"complete_window": True}},
        "authoritative": {"publication": {"news": {"content_ids": [cid]}}},
        "publication": {"records": [{"source_url": url, "title": "Title"}]}})
    row = audit.discover(tmp_path, 24, None)[0]
    assert row.translated_candidate_text == "Bob: una promo."
    assert row.alfred_approved_text == "Alfred: un promo."
    assert "bob-" in row.translated_candidate_provenance
    assert row.final_markup_available is False
    assert row.published_text == "Finale: un promo."


def pattern_payload(articles):
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "hours": 168,
        "coverage": {"publication_authority_available": True, "authoritative_total": len(articles),
                     "audit_population_total": len(articles), "detailed_rows_returned": len(articles)}, "articles": articles}


def test_weekly_unique_grain_rates_and_no_invented_false_positive_rate(tmp_path):
    articles = [{"key": str(i), "alfred_warnings": ["title_too_long", "title_too_long"], "title": "x" * (96 if i < 2 else 90)} for i in range(3)]
    path = tmp_path / "audit.json"
    payload = pattern_payload(articles)
    path.write_text(json.dumps(payload))
    report = weekly.build_patterns(payload, analysis.build_analysis(path, 168))
    p = report["patterns"][0]
    assert report["available"] is True and p["articles_unique"] == 3
    assert p["reproduction_rate"] == pytest.approx(2/3)
    assert p["confirmed_false_positive_rate"] is None
    assert p["recurring"] is True and len(p["examples"]) == 3


@pytest.mark.parametrize("mutation", ["authority", "truncated", "duplicate"])
def test_weekly_incomplete_populations_are_unavailable(mutation):
    payload = pattern_payload([{"key": "a"}])
    if mutation == "authority": payload["coverage"]["publication_authority_available"] = False
    if mutation == "truncated": payload["coverage"]["audit_population_total"] = 2
    if mutation == "duplicate": payload["articles"].append({"key": "a"})
    report = weekly.build_patterns(payload, {"investigations": [], "errors": []})
    assert report["available"] is False and report["publication_population_unique"] is None
    assert report["errors"]


def test_weekly_failure_replaces_latest_and_keeps_daily_audit(tmp_path, monkeypatch):
    daily = tmp_path / "state/reports/owtv_translation_quality_audit_latest.json"
    daily.parent.mkdir(parents=True)
    daily.write_text("daily unchanged")
    latest = daily.parent / weekly.LATEST_NAME
    latest.write_text(json.dumps({"available": True, "patterns": ["stale"]}))
    monkeypatch.setattr(audit, "build_audit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    outputs = weekly.generate_outputs(tmp_path)
    assert daily.read_text() == "daily unchanged"
    payload = json.loads(outputs["latest_json"].read_text())
    assert payload["available"] is False and payload["patterns"] == []
    assert "boom" in payload["errors"][0]


def test_weekly_email_failure_never_reuses_stale_current_result(tmp_path, monkeypatch):
    import send_daily_report as daily
    from scripts import build_weekly_pattern_report
    monkeypatch.setattr(daily, "BOT_DIR", tmp_path)
    monkeypatch.setattr(daily, "WEEKLY_QUALITY_CURRENT_RESULT", (tmp_path / "old.md", tmp_path / "old.json", None))
    monkeypatch.setattr(build_weekly_pattern_report, "generate_outputs", lambda **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert daily.generate_weekly_quality_patterns()[:2] == (None, None)
    assert "boom" in daily.weekly_quality_patterns_body_section()
