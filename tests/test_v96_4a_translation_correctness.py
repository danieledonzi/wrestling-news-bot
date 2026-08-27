import json
from pathlib import Path

from agents import alfred, bob
from agents.translation_validation import language_escape_evidence, likely_macroscopic_english


ENGLISH = (
    "Bully Ray said that the WWE star was expected to return after the event, and that he would "
    "work with Bron Breakker while the company prepared the next match. The veteran explained that "
    "this was the plan for several months, but officials have not confirmed when they will announce "
    "the match. He also said the performers were working with Paul Heyman before the show and that "
    "they could appear together during the foreseeable future."
)
ITALIAN = (
    "Bully Ray ha detto che la star della WWE dovrebbe tornare dopo l'evento e lavorare con Bron "
    "Breakker mentre la compagnia prepara il prossimo incontro. Il veterano ha spiegato che il piano "
    "esiste da diversi mesi, ma i dirigenti non hanno confermato quando annunceranno il match. Ha "
    "aggiunto che gli atleti hanno lavorato con Paul Heyman prima dello show e potrebbero apparire "
    "insieme anche in futuro su Sunday Night's Main Event e a Busted Open Radio."
)
LOW_MARKER_ENGLISH = " ".join([
    "John Cena defeated Cody Rhodes via pinfall.",
    "Roman Reigns attacked Seth Rollins ringside.",
    "Rhea Ripley challenged Bianca Belair backstage.",
    "Gunther powerbombed Jey Uso onto steel steps.",
    "Bron Breakker speared Oba Femi after interference.",
] * 3)


def units():
    return [{"id": "b1", "text": ENGLISH[:210]}, {"id": "b2", "text": ENGLISH[211:]}]


def valid_data():
    return {"title_it": "Bully Ray commenta il ritorno delle star WWE", "translations": {"b1": ITALIAN[:220], "b2": ITALIAN[220:]}}


def test_valid_italian_with_wrestling_terms_and_names_is_accepted():
    result = bob.validate_translation(valid_data(), True, units(), "Bully Ray Explains What WWE Will Do After The Show")
    assert result["valid"] is True
    assert likely_macroscopic_english(ITALIAN) is False


def test_malformed_json_is_not_translation_success():
    data, parse_valid = bob.parse_bob_json_with_validity("provider returned non-empty prose")
    result = bob.validate_translation(data, parse_valid, units(), "An English Source Title About WWE")
    assert result["valid"] is False
    assert "invalid_bob_json" in result["reasons"]


def test_parse_bob_json_remains_dict_compatible():
    parsed = bob.parse_bob_json(json.dumps(valid_data()))
    assert isinstance(parsed, dict)
    assert parsed.get("title_it") == valid_data()["title_it"]


def test_parse_bob_json_malformed_compatibility_fallback_is_dict():
    parsed = bob.parse_bob_json("not json")
    assert isinstance(parsed, dict)
    assert parsed.get("translations") == {}


def test_missing_and_empty_units_are_rejected():
    missing = bob.validate_translation({"title_it": "Titolo italiano", "translations": {"b1": ITALIAN}}, True, units(), "Source")
    empty = bob.validate_translation({"title_it": "Titolo italiano", "translations": {"b1": ITALIAN, "b2": "  "}}, True, units(), "Source")
    assert "missing_translation_units" in missing["reasons"]
    assert "empty_translation_units" in empty["reasons"]


def test_translation_values_must_be_nonempty_strings():
    for invalid in (None, 123, {"text": "Italiano"}, ["Italiano"]):
        data = {"title_it": "Titolo italiano", "translations": {"b1": invalid, "b2": ITALIAN}}
        result = bob.validate_translation(data, True, units(), "English source")
        assert result["valid"] is False
        assert result["invalid_value_type_units"] == ["b1"]
        assert "translation_unit_not_string" in result["reasons"]


def test_title_must_be_nonempty_string():
    result = bob.validate_translation(valid_data() | {"title_it": 123}, True, units(), "English source")
    assert result["valid"] is False
    assert result["title_type_valid"] is False
    assert "title_it_not_string" in result["reasons"]


def test_unchanged_english_body_and_title_are_rejected():
    source_title = "Bully Ray Explains What WWE Will Do After The Show"
    data = {"title_it": source_title, "translations": {u["id"]: u["text"] for u in units()}}
    result = bob.validate_translation(data, True, units(), source_title)
    assert result["valid"] is False
    assert result["body_likely_untranslated"] is True
    assert result["title_likely_untranslated"] is True


def test_low_marker_exact_english_copy_is_rejected():
    low_marker_units = [
        {"id": "b1", "text": LOW_MARKER_ENGLISH[:150]},
        {"id": "b2", "text": LOW_MARKER_ENGLISH[150:300]},
        {"id": "b3", "text": LOW_MARKER_ENGLISH[300:]},
    ]
    translations = {unit["id"]: unit["text"] for unit in low_marker_units}
    assert likely_macroscopic_english(LOW_MARKER_ENGLISH) is False
    result = bob.validate_translation(
        {"title_it": "Risultati completi dello show WWE", "translations": translations},
        True,
        low_marker_units,
        "WWE Results",
    )
    assert result["exact_body_unchanged"] is True
    assert result["body_substantially_unchanged"] is True
    assert result["valid"] is False
    assert "unchanged_source_body" in result["reasons"]


def test_untranslated_english_title_rejected_with_translated_body():
    source_title = "What The WWE Stars Will Do After The Main Event"
    result = bob.validate_translation(valid_data() | {"title_it": source_title}, True, units(), source_title)
    assert result["title_likely_untranslated"] is True
    assert result["valid"] is False


def test_actual_bully_ray_title_uses_english_source_body_context():
    source_title = "Bully Ray Talks Potential WWE Return During Bron Breakker Vs. Oba Femi Match At SNME - Wrestling Inc."
    result = bob.validate_translation(valid_data() | {"title_it": source_title}, True, units(), source_title)
    assert result["body_likely_untranslated"] is False
    assert result["title_likely_untranslated"] is True
    assert result["valid"] is False


def assert_official_unchanged_title_is_accepted(title):
    result = bob.validate_translation(valid_data() | {"title_it": title}, True, units(), title)
    assert result["body_likely_untranslated"] is False
    assert result["title_likely_untranslated"] is False
    assert result["valid"] is True


def test_unchanged_official_show_name_is_not_untranslated_title():
    assert_official_unchanged_title_is_accepted("WWE Saturday Night's Main Event")


def test_unchanged_official_championship_is_not_untranslated_title():
    assert_official_unchanged_title_is_accepted("World Heavyweight Championship")


def test_unchanged_nickname_branding_is_not_untranslated_title():
    assert_official_unchanged_title_is_accepted("The American Nightmare Cody Rhodes")


def test_short_official_title_is_not_rejected():
    result = bob.validate_translation(valid_data() | {"title_it": "WWE RAW"}, True, units(), "WWE RAW")
    assert result["title_likely_untranslated"] is False


def test_proper_names_and_short_english_quote_do_not_trigger():
    text = ITALIAN + ' Bully Ray ha concluso: "The Vision".'
    evidence = language_escape_evidence("", "Titolo italiano", {}, {"b1": text})
    assert evidence["residual_english_body"] is False


def bob_article(body, title="Bully Ray commenta il ritorno in WWE", source_title="Bully Ray Explains What WWE Will Do After The Show"):
    return {
        "status": "ready_for_alfred", "source_title": source_title, "title_it": title,
        "body_html": f"<p>{body}</p>", "element_counts": {"text": 1, "quote": 0, "table": 0},
        "elements": [{"type": "text", "block_id": "b1", "text": ENGLISH}],
    }


def test_alfred_blocks_english_escape():
    review = alfred.review_article(bob_article(ENGLISH, title="Bully Ray Explains What WWE Will Do After The Show"))
    assert review["decision"] == "needs_revision"
    assert {item["code"] for item in review["issues"]} & {"untranslated_body", "residual_english_body"}


def test_alfred_blocks_low_marker_exact_body_escape():
    article = bob_article(LOW_MARKER_ENGLISH, title="Risultati completi dello show WWE")
    article["elements"] = [{"type": "text", "block_id": "b1", "text": LOW_MARKER_ENGLISH}]
    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "untranslated_body" in {item["code"] for item in review["issues"]}
    assert review["diagnostics"]["translation_escape_evidence"]["exact_body_unchanged"] is True


def test_alfred_approves_italian_with_legitimate_english_terms():
    review = alfred.review_article(bob_article(ITALIAN))
    assert review["decision"] == "approved"


def test_alfred_retains_bob_validation_failure_reasons():
    article = bob_article("")
    article.update({"status": "translation_validation_failed", "translation_validation": {"valid": False, "reasons": ["invalid_bob_json"]}})
    review = alfred.review_article(article)
    assert review["diagnostics"]["bob_translation_validation"]["reasons"] == ["invalid_bob_json"]


def test_alfred_prefers_page_title_like_bob():
    actual = "Bully Ray Talks Potential WWE Return During Bron Breakker Vs. Oba Femi Match At SNME - Wrestling Inc."
    article = bob_article(ITALIAN, title=actual, source_title="Short feed headline")
    article["meta"] = {"source_title": actual}
    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "untranslated_title" in {item["code"] for item in review["issues"]}


def test_effective_runtime_versions_and_runner_summary_are_v96_4a():
    from agents import alfred_policy_v93_20, bob_policy_v93_15
    assert "v96.4a" in bob_policy_v93_15.VERSION
    assert "v96.4a" in alfred_policy_v93_20.VERSION
    runner_source = (Path(__file__).parents[1] / "newsroom_runner.py").read_text(encoding="utf-8")
    assert "validation_failed={translation_validation_failed}" in runner_source


def test_article_package_validation_does_not_make_an_extra_provider_call(monkeypatch):
    calls = []
    elements = [{"type": "text", "block_id": "b1", "text": ENGLISH}]
    monkeypatch.setattr(bob, "fetch_html", lambda url: "<html>source</html>")
    monkeypatch.setattr(bob, "extract_elements", lambda url, raw: ({"source_title": "English WWE News That Will Be Discussed Today", "description": ""}, elements, elements, [], {}))
    monkeypatch.setattr(bob.source_body, "contract_from_elements", lambda *args: {})
    def provider(*args, **kwargs):
        calls.append(1)
        return json.dumps({"title_it": "English WWE News That Will Be Discussed Today", "translations": {"b1": ENGLISH}}), "model", []
    monkeypatch.setattr(bob, "call_gemini", provider)
    package = bob.article_package({"url": "https://example.test/story", "title": "English WWE News That Will Be Discussed Today"})
    assert package["status"] == "translation_validation_failed"
    assert package["body_html"] == ""
    assert len(calls) == 1


def test_run_bob_console_summary_counts_validation_failures(monkeypatch, capsys):
    monkeypatch.setattr(bob, "article_package", lambda item: {"status": "translation_validation_failed"})
    monkeypatch.setattr(bob, "write_json", lambda *args: None)
    result = bob.run_bob({"version": "test", "selected": [{"url": "https://example.test/story"}]})
    output = capsys.readouterr().out
    assert result["handoff"]["translation_validation_failed"] == 1
    assert "[BOB V96.4A]" in output
    assert "ready=0 pending=0 validation_failed=1 empty=0 errors=0" in output
