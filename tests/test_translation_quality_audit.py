import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import translation_quality_audit as audit


def test_source_intro_leak_detection():
    a = audit.ArticleAudit(key="x", published_text="Welcome to our coverage. La notizia riguarda la WWE.")
    audit.run_checks(a)
    assert "source_intro_leaked" in a.issues


def test_published_text_too_short_vs_original():
    a = audit.ArticleAudit(key="x", original_text="a" * 1200, published_text="breve", published_text_length=5)
    a.original_text_length = 1200
    audit.run_checks(a)
    assert "published_text_too_short_vs_original" in a.issues


def test_normal_quote_citation_not_flagged_as_betting():
    a = audit.ArticleAudit(key="x", title="CM Punk commenta Raw", published_text='CM Punk ha detto: "Sono pronto" durante Raw.')
    audit.run_checks(a)
    assert "betting_odds_article_published" not in a.issues


def test_mojibake_detection():
    a = audit.ArticleAudit(key="x", published_text="PerchÃ© il match sarÃ importante per il roster.")
    audit.run_checks(a)
    assert "mojibake_or_broken_accents" in a.issues


def test_ai_filler_detection():
    a = audit.ArticleAudit(key="x", published_text="Only time will tell cosa succederà nel prossimo episodio.")
    audit.run_checks(a)
    assert "ai_style_filler" in a.issues


def test_build_audit_writes_json_and_markdown(tmp_path):
    pub = tmp_path / "published_html_review"
    pub.mkdir()
    (pub / "story.html").write_text("<html><title>Story</title><p>Welcome to our coverage.</p></html>", encoding="utf-8")
    payload, latest, md = audit.build_audit(hours=24, output_dir=tmp_path / "reports", root=tmp_path)
    assert latest.exists()
    assert md.exists()
    assert payload["artifact_marker"] == "owtv_translation_quality_audit_v1"
    assert "source_intro_leaked" in latest.read_text(encoding="utf-8")
