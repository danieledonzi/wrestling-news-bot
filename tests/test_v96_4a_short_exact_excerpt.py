from agents import alfred, bob
from agents.translation_validation import (
    excerpt_translation_evidence,
    likely_short_english_prose,
    normalized,
)


SHORT_SOURCE = "Roman Reigns returns after WWE injury update"
SHORT_NEAR_SOURCE = "a b c d e f g h i j"
SHORT_NEAR_OUTPUT = "a b c d e f g h i k"
SOURCE_BODY = (
    "The company announced that Roman Reigns would return after the injury and that officials were "
    "preparing his next appearance on WWE television. "
) * 4
ITALIAN_BODY = (
    "La compagnia ha annunciato che Roman Reigns tornerà dopo l'infortunio e che i dirigenti stanno "
    "preparando la sua prossima apparizione negli show WWE. "
) * 4


def _units():
    return [{"id": "b1", "type": "text", "text": SOURCE_BODY}]


def _valid_data(excerpt):
    return {
        "title_it": "Aggiornamento sul ritorno di Roman Reigns in WWE",
        "excerpt_it": excerpt,
        "translations": {"b1": ITALIAN_BODY},
    }


def test_short_exact_excerpt_copy_is_rejected_by_bob():
    assert 0 < len(normalized(SHORT_SOURCE)) < 50
    assert likely_short_english_prose(SHORT_SOURCE) is False

    evidence = excerpt_translation_evidence(SHORT_SOURCE, SHORT_SOURCE)
    assert evidence["excerpt_exact_source"] is True
    assert evidence["excerpt_near_source"] is False
    assert evidence["excerpt_likely_untranslated"] is True

    result = bob.validate_translation(
        _valid_data(SHORT_SOURCE),
        True,
        _units(),
        "Roman Reigns Returns After WWE Injury Update",
        "",
        SHORT_SOURCE,
    )
    assert result["valid"] is False
    assert result["excerpt_exact_source"] is True
    assert "untranslated_excerpt" in result["reasons"]


def test_short_exact_excerpt_copy_is_blocked_by_alfred():
    article = {
        "status": "ready_for_alfred",
        "source_title": "Roman Reigns Returns After WWE Injury Update",
        "title_it": "Aggiornamento sul ritorno di Roman Reigns in WWE",
        "body_html": f"<p>{ITALIAN_BODY}</p>",
        "excerpt_it": SHORT_SOURCE,
        "meta": {"description": SHORT_SOURCE},
        "elements": [{"type": "text", "block_id": "b1", "text": SOURCE_BODY}],
        "element_counts": {"text": 1, "quote": 0, "table": 0},
    }

    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "untranslated_excerpt" in {item["code"] for item in review["issues"]}
    assert review["diagnostics"]["excerpt_translation_evidence"]["excerpt_exact_source"] is True


def test_short_nonidentical_excerpt_does_not_enter_near_match_branch():
    assert len(normalized(SHORT_NEAR_SOURCE)) < 50
    assert len(normalized(SHORT_NEAR_OUTPUT)) < 50

    evidence = excerpt_translation_evidence(SHORT_NEAR_SOURCE, SHORT_NEAR_OUTPUT)
    assert evidence["excerpt_exact_source"] is False
    assert evidence["excerpt_source_similarity"] >= 0.9
    assert evidence["excerpt_near_source"] is False
