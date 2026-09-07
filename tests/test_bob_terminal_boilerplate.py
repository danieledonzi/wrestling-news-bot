import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup

from agents import bob


TRANSCRIPT_BOILERPLATE = (
    "This transcript was produced exclusively for Ringside News from the original recording. "
    "Republishing the transcription in full is prohibited. When using excerpts, provide "
    "prominent credit and a link to this article."
)
AUTHOR_BIO = (
    "H Jenkins has been breaking pro wrestling news on Ringside News for nearly a decade, "
    "with his reports featured by TMZ, Forbes, The Sun, and more."
)


def text_elements(*texts):
    return [{"type": "text", "text": text} for text in texts]


def cleaned_texts(*texts):
    cleaned, _ = bob.sanitize_elements(text_elements(*texts), "")
    return [item["text"] for item in cleaned]


def extracted_paragraphs(*texts):
    soup = BeautifulSoup("".join(f"<p>{text}</p>" for text in texts), "html.parser")
    return [item for node in soup.find_all("p") if (item := bob.element_from_node(node, "https://example.test"))]


def test_exact_production_boilerplate_never_becomes_translation_units():
    for boilerplate in (TRANSCRIPT_BOILERPLATE, AUTHOR_BIO):
        cleaned, removed = bob.sanitize_elements(text_elements(boilerplate), "")
        assert bob.build_translation_units(cleaned) == []
        assert removed[0]["reason"] == "footer_start"


def test_bounded_signal_combinations_cover_wording_variants():
    transcript_variant = (
        "This transcription was prepared exclusively from the original Ringside News recording. "
        "Please credit this article when using excerpts."
    )
    bio_variant = (
        "H Jenkins has covered professional wrestling for Ringside News for many years and his "
        "reporting has appeared in major publications."
    )
    assert cleaned_texts(transcript_variant) == []
    assert cleaned_texts(bio_variant) == []


def test_individual_keywords_and_legitimate_quoted_transcript_survive():
    editorial = [
        "Ringside News reported that Rhea Ripley discussed the injuries she has accumulated during her career.",
        "TMZ and Forbes previously covered the wrestler’s mainstream media appearances.",
        'Rhea Ripley said in the transcript, "My shoulder hurt, but I kept wrestling and finished the match."',
    ]
    assert cleaned_texts(*editorial) == editorial


def test_terminal_marker_truncates_only_footer_material_in_production_sequence():
    editorial = [
        "Rhea Ripley described the physical toll of wrestling for nearly fourteen years.",
        "She explained that several injuries continued to affect her in recent matches.",
    ]
    trailing_footer = "Subscribe to the site for more wrestling updates."
    cleaned, removed = bob.sanitize_elements(
        text_elements(*editorial, TRANSCRIPT_BOILERPLATE, AUTHOR_BIO, trailing_footer), ""
    )
    assert [item["text"] for item in cleaned] == editorial
    assert removed == [
        {"index": 3, "reason": "footer_start", "item": {"type": "text", "text": TRANSCRIPT_BOILERPLATE}}
    ]
    assert [unit["text"] for unit in bob.build_translation_units(cleaned)] == editorial


def test_ordinary_source_mention_does_not_trigger_terminal_truncation():
    first = "Ringside News reported that the wrestler discussed her recovery timetable."
    second = "The champion then described the treatment she received after the match."
    assert cleaned_texts(first, second) == [first, second]


def test_transcript_signals_without_recognized_source_do_not_truncate():
    first = (
        "During the interview, the wrestler reviewed the transcript from the original recording "
        "and asked for credit whenever excerpts were quoted."
    )
    second = "She then explained why preserving the context of her remarks mattered."
    assert cleaned_texts(first, second) == [first, second]


def test_editorial_transcript_report_does_not_trigger_truncation():
    first = "Fightful's report includes a transcript of the original audio and a link to the complete interview."
    second = "The wrestler then explained why the complete interview provided important context."
    extracted = extracted_paragraphs(first, second)
    cleaned, _ = bob.sanitize_elements(extracted, "")
    assert [item["text"] for item in cleaned] == [first, second]


def test_legal_dispute_transcript_does_not_trigger_truncation():
    first = (
        "Fightful obtained the transcript of the hearing, which says the court prohibited "
        "republication of the confidential exhibit."
    )
    second = "The parties will return to court next week for another hearing."
    extracted = extracted_paragraphs(first, second)
    cleaned, _ = bob.sanitize_elements(extracted, "")
    assert [item["text"] for item in cleaned] == [first, second]


def test_reporting_source_is_not_mistaken_for_transcript_owner():
    first = (
        "Fightful reported that WWE prepared the hearing transcript exclusively for the court, "
        "while excerpts require attribution to the witness."
    )
    second = "The court will consider the witness's objections at the next hearing."
    extracted = extracted_paragraphs(first, second)
    cleaned, _ = bob.sanitize_elements(extracted, "")
    assert [item["text"] for item in cleaned] == [first, second]


def test_source_reporting_and_bare_tenure_do_not_trigger_truncation():
    first = "For years, Fightful has been covering WWE news, and its latest report says that plans changed."
    second = "The promotion will announce the revised match before Friday's event."
    assert cleaned_texts(first, second) == [first, second]


def test_transitive_reports_featured_does_not_trigger_truncation():
    first = (
        "Fightful has been covering WWE news, and its reports featured several contradictory "
        "accounts from talent."
    )
    second = "The promotion has not yet clarified which account is accurate."
    extracted = extracted_paragraphs(first, second)
    cleaned, _ = bob.sanitize_elements(extracted, "")
    assert [item["text"] for item in cleaned] == [first, second]


def test_legacy_bio_filter_does_not_gain_terminal_authority():
    legacy_bio = "John Cena has over 20 years of experience in professional wrestling."
    editorial = "He then explained why his recent match was especially important."
    extracted = extracted_paragraphs(legacy_bio, editorial)
    cleaned, _ = bob.sanitize_elements(extracted, "")
    assert [item["text"] for item in cleaned] == [editorial]


def test_new_source_terminal_marker_reaches_sanitize_and_truncates():
    trailing = AUTHOR_BIO
    extracted = extracted_paragraphs(TRANSCRIPT_BOILERPLATE, trailing)
    assert [item["text"] for item in extracted] == [TRANSCRIPT_BOILERPLATE, trailing]
    cleaned, removed = bob.sanitize_elements(extracted, "")
    assert cleaned == []
    assert removed[0]["reason"] == "footer_start"


def test_first_person_source_terminal_marker_survives_source_self_reference_filter():
    marker = (
        "We at Wrestling Inc. prepared this transcript exclusively from the original recording; "
        "please credit this article when using excerpts."
    )
    trailing = AUTHOR_BIO
    assert bob.is_high_confidence_source_terminal_boilerplate(marker) is True
    extracted = extracted_paragraphs(marker, trailing)
    assert [item["text"] for item in extracted] == [marker, trailing]
    cleaned, removed = bob.sanitize_elements(extracted, "")
    assert cleaned == []
    assert removed[0]["reason"] == "footer_start"


def test_recognized_source_boilerplate_does_not_truncate_later_editorial_content():
    introduction = "Introduzione."
    marker = (
        "This transcript was produced exclusively for Ringside News from the original recording. "
        "When using excerpts, provide prominent credit to Ringside News."
    )
    conclusion = "Un ultimo paragrafo editoriale chiude davvero l'articolo."
    assert bob.is_high_confidence_source_terminal_boilerplate(marker) is True
    extracted = extracted_paragraphs(introduction, marker, conclusion)
    cleaned, removed = bob.sanitize_elements(extracted, "")
    assert [item["text"] for item in cleaned] == [marker, conclusion]
    assert removed == []


def test_plural_passive_author_credential_is_terminal():
    bio = (
        "H Jenkins has been breaking pro wrestling news on Ringside News, and his reports have "
        "been featured by TMZ."
    )
    cleaned, removed = bob.sanitize_elements(text_elements(bio), "")
    assert cleaned == []
    assert removed[0]["reason"] == "footer_start"
    assert bob.build_translation_units(cleaned) == []


def test_empty_genuine_editorial_translation_remains_invalid():
    units = [{"id": "b1", "type": "text", "text": "The wrestler discussed her injury after the match."}]
    validation = bob.validate_translation(
        {"title_it": "La wrestler parla del suo infortunio", "translations": {"b1": ""}},
        True,
        units,
        "Wrestler Discusses Injury After Match",
    )
    assert validation["valid"] is False
    assert validation["empty_units"] == ["b1"]
    assert "empty_translation_units" in validation["reasons"]
