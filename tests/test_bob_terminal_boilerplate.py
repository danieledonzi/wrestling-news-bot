import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
