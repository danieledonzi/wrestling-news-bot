"""Real apostrophe false positives must not disable untranslated-quote checks."""
import json
from pathlib import Path

import pytest

from agents import alfred
from agents import alfred_policy_v93_20 as policy


FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "alfred_vic_joseph_quotes_20261026.json").read_text(encoding="utf-8")
)
ENGLISH = "We will return to the ring and show the world what we can do"


def article(body):
    return {
        "status": "ready_for_alfred",
        "source_url": "https://example.test/vic-joseph",
        "source_title": "Vic Joseph announces a new NXT show",
        "title_it": "Vic Joseph annuncia un nuovo programma di NXT",
        "body_html": body,
        "element_counts": {"text": 3},
    }


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f["archive"].split("/")[1] for f in FIXTURES])
def test_retained_vic_joseph_articles_pass_without_resolver(fixture, monkeypatch):
    def forbidden_call(*args, **kwargs):
        raise AssertionError("A translated paragraph must not call the resolver")

    monkeypatch.setattr(policy, "call_quote_resolver_gemini", forbidden_call)
    source = article(fixture["body_html"])
    review, _, stats = policy.refine_review(alfred.review_article(source), source)

    assert review["decision"] == "approved"
    assert stats["calls"] == 0
    assert not review["issues"]
    assert review["approved_article"]["body_html"] == source["body_html"]


@pytest.mark.parametrize("apostrophe", ["'", "’"])
def test_italian_elisions_and_english_contractions_are_not_quote_delimiters(apostrophe):
    text = (
        f"L{apostrophe}universo di Beyond The Bell si ritrova nell{apostrophe}annuncio di The CW. "
        f"D{apostrophe}Angelo interviene e l{apostrophe}atleta torna sul ring. "
        f"It{apostrophe}s the show and they don{apostrophe}t change the name."
    )
    assert alfred.extract_quoted_segments(text) == []


@pytest.mark.parametrize("opening,closing", [('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"), ("«", "»")])
@pytest.mark.parametrize("padding", ["", " "])
def test_real_english_quotes_still_block(opening, closing, padding, monkeypatch):
    body = FIXTURES[0]["body_html"] + f"<p>Ha dichiarato: {opening}{padding}{ENGLISH}{padding}{closing}.</p>"
    source = article(body)
    monkeypatch.setattr(policy, "call_quote_resolver_gemini", lambda *a, **k: pytest.fail("Clear English needs no resolver"))
    review, _, _ = policy.refine_review(alfred.review_article(source), source)

    assert review["decision"] == "needs_revision"
    assert any(i["code"] == "untranslated_quote" and i["evidence"].strip() == ENGLISH for i in review["issues"])
    assert review["approved_article"] is None


@pytest.mark.parametrize("opening,closing,apostrophe", [("'", "'", "'"), ("'", "'", "’"), ("‘", "’", "’")])
def test_apostrophes_inside_real_single_quoted_speech_are_preserved(opening, closing, apostrophe):
    phrase = f"We don{apostrophe}t know when the wrestler{apostrophe}s return will happen and the show starts"
    text = f"L'annuncio contiene {opening}{phrase}{closing}, ha dichiarato."
    assert alfred.extract_quoted_segments(text) == [phrase]
    assert alfred.likely_english(phrase)


@pytest.mark.parametrize("outer,inner", [(('“', '”'), ("'", "'")), (('"', '"'), ("‘", "’")), (("'", "'"), ('"', '"'))])
def test_nested_quotes_do_not_hide_english_or_include_surrounding_elisions(outer, inner):
    phrase = f"We will bring {inner[0]}The Best in the World{inner[1]} to the show"
    text = f"L'universo del wrestling ascolta {outer[0]}{phrase}{outer[1]}, nell'annuncio ufficiale."
    segments = alfred.extract_quoted_segments(text)
    assert phrase in segments
    assert "The Best in the World" in segments
    assert all("universo" not in s and "annuncio" not in s for s in segments)
    assert any(alfred.likely_english(s) for s in segments)


@pytest.mark.parametrize("text", ["Ha detto 'Una frase non chiusa", "L'universo di The CW cita 'Beyond The Bell", 'Ha detto “Una frase non chiusa'])
def test_unclosed_quotes_do_not_fabricate_a_complete_segment(text):
    assert alfred.extract_quoted_segments(text) == []


def test_one_apostrophe_change_cannot_restore_the_vic_joseph_false_positive():
    # The fourth live translation happened to pair l'azione with l'universo.
    # Removing one of those apostrophes previously created a false quote again.
    body = alfred.clean_text(FIXTURES[3]["body_html"]).replace("l'universo", "l’universo")
    assert not any(alfred.likely_english(s) for s in alfred.extract_quoted_segments(body))


def test_short_names_do_not_shift_double_quote_pairing():
    text = f'Il programma "WWE NXT" contiene "Beyond The Bell". Ha dichiarato: "{ENGLISH}".'
    assert alfred.extract_quoted_segments(text) == ["Beyond The Bell", ENGLISH]


@pytest.mark.parametrize("opening,closing", [('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"), ("«", "»")])
def test_empty_quotes_do_not_shift_the_next_real_quote(opening, closing):
    text = f"Il titolo {opening}{closing} precede {opening}{ENGLISH}{closing}."
    assert alfred.extract_quoted_segments(text) == [ENGLISH]
