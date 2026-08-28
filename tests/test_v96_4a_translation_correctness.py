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
LOW_MARKER_REPHRASED = LOW_MARKER_ENGLISH.replace("defeated", "beat", 1).replace("attacked", "assaulted", 1)
LOW_MARKER_ITALIAN = " ".join([
    "John Cena ha sconfitto Cody Rhodes per schienamento.",
    "Roman Reigns ha aggredito Seth Rollins a bordo ring.",
    "Rhea Ripley ha sfidato Bianca Belair nel backstage.",
    "Gunther ha colpito Jey Uso con una powerbomb sui gradoni.",
    "Bron Breakker ha travolto Oba Femi con una Spear dopo un'interferenza.",
] * 3)
ITALIAN_JUDGMENT_DAY = " ".join([
    "The Judgment Day domina WWE Raw con una strategia aggressiva.",
    "The Judgment Day attacca gli avversari vicino al ring.",
    "The Judgment Day controlla il match senza concedere spazio.",
    "The Judgment Day celebra la vittoria davanti al pubblico.",
] * 4)
SOURCE_DESCRIPTION = "Roman Reigns returned to WWE SmackDown after he was away from the show for several weeks."
ITALIAN_EXCERPT = "Roman Reigns è tornato a WWE SmackDown dopo diverse settimane di assenza dallo show."


def units():
    return [{"id": "b1", "text": ENGLISH[:210]}, {"id": "b2", "text": ENGLISH[211:]}]


def valid_data():
    return {"title_it": "Bully Ray commenta il ritorno delle star WWE", "translations": {"b1": ITALIAN[:220], "b2": ITALIAN[220:]}}


def test_valid_italian_with_wrestling_terms_and_names_is_accepted():
    result = bob.validate_translation(valid_data(), True, units(), "Bully Ray Explains What WWE Will Do After The Show")
    assert result["valid"] is True
    assert likely_macroscopic_english(ITALIAN) is False


def test_repeated_official_name_does_not_create_english_prose_evidence():
    assert len(ITALIAN_JUDGMENT_DAY.split()) >= 40
    assert ITALIAN_JUDGMENT_DAY.lower().split().count("the") >= 8
    assert likely_macroscopic_english(ITALIAN_JUDGMENT_DAY) is False
    result = bob.validate_translation(
        {"title_it": "The Judgment Day domina WWE Raw", "translations": {"b1": ITALIAN_JUDGMENT_DAY}},
        True, [{"id": "b1", "text": ENGLISH}], "Judgment Day WWE Raw News",
    )
    assert result["residual_english_body"] is False
    assert result["valid"] is True


def test_genuine_english_prose_still_has_diverse_marker_evidence():
    assert likely_macroscopic_english(ENGLISH) is True


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


def test_valid_italian_excerpt_is_accepted():
    result = bob.validate_translation(
        valid_data() | {"excerpt_it": ITALIAN_EXCERPT}, True, units(), "English source", "", SOURCE_DESCRIPTION,
    )
    assert result["excerpt_present"] is True
    assert result["excerpt_type_valid"] is True
    assert result["excerpt_likely_untranslated"] is False
    assert result["excerpt_residual_english"] is False
    assert result["valid"] is True


def test_empty_excerpt_remains_optional():
    result = bob.validate_translation(valid_data() | {"excerpt_it": ""}, True, units(), "English source", "", SOURCE_DESCRIPTION)
    assert result["excerpt_present"] is False
    assert result["excerpt_type_valid"] is True
    assert result["valid"] is True


def test_supplied_non_string_excerpt_is_rejected():
    for invalid in (None, 123, {"text": "excerpt"}, ["excerpt"]):
        result = bob.validate_translation(valid_data() | {"excerpt_it": invalid}, True, units(), "English source")
        assert result["excerpt_type_valid"] is False
        assert "excerpt_it_not_string" in result["reasons"]
        assert result["valid"] is False


def test_exact_english_source_description_excerpt_is_rejected():
    result = bob.validate_translation(
        valid_data() | {"excerpt_it": SOURCE_DESCRIPTION}, True, units(), "English source", "", SOURCE_DESCRIPTION,
    )
    assert result["excerpt_exact_source"] is True
    assert result["excerpt_likely_untranslated"] is True
    assert "untranslated_excerpt" in result["reasons"]
    assert result["valid"] is False


def test_rephrased_english_source_description_excerpt_is_rejected():
    rephrased = SOURCE_DESCRIPTION.replace("returned", "appeared")
    result = bob.validate_translation(
        valid_data() | {"excerpt_it": rephrased}, True, units(), "English source", "", SOURCE_DESCRIPTION,
    )
    assert result["excerpt_near_source"] is True
    assert result["excerpt_source_similarity"] >= 0.9
    assert "untranslated_excerpt" in result["reasons"]
    assert result["valid"] is False


def test_italian_excerpt_with_wrestling_terms_is_accepted():
    excerpt = "The Judgment Day ha attaccato Roman Reigns durante WWE RAW e tornerà a SmackDown dopo NXT."
    result = bob.validate_translation(valid_data() | {"excerpt_it": excerpt}, True, units(), "English source")
    assert result["excerpt_residual_english"] is False
    assert result["valid"] is True


def test_repeated_official_branding_does_not_invalidate_italian_excerpt():
    excerpt = "The Judgment Day domina il match, The Judgment Day festeggia e The Judgment Day saluta il pubblico italiano."
    result = bob.validate_translation(valid_data() | {"excerpt_it": excerpt}, True, units(), "English source")
    assert result["excerpt_residual_english"] is False
    assert result["valid"] is True


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


def test_low_marker_near_identical_english_copy_is_rejected():
    low_marker_units = [{"id": "b1", "text": LOW_MARKER_ENGLISH}]
    assert LOW_MARKER_REPHRASED != LOW_MARKER_ENGLISH
    assert likely_macroscopic_english(LOW_MARKER_REPHRASED) is False
    result = bob.validate_translation(
        {"title_it": "Risultati completi dello show WWE", "translations": {"b1": LOW_MARKER_REPHRASED}},
        True,
        low_marker_units,
        "WWE Results",
    )
    assert result["exact_body_unchanged"] is False
    assert result["near_identical_body"] is True
    assert result["source_output_similarity"] >= 0.94
    assert result["valid"] is False
    assert "unchanged_source_body" in result["reasons"]


def test_italian_translation_of_low_marker_results_is_not_near_identical():
    result = bob.validate_translation(
        {"title_it": "Risultati completi dello show WWE", "translations": {"b1": LOW_MARKER_ITALIAN}},
        True,
        [{"id": "b1", "text": LOW_MARKER_ENGLISH}],
        "WWE Results",
    )
    assert result["near_identical_body"] is False
    assert result["source_output_similarity"] < 0.94
    assert result["valid"] is True


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


def test_unchanged_prose_headline_is_rejected_without_marker_vocabulary():
    source_title = "Roman Reigns Returns To WWE SmackDown Following Injury Update"
    result = bob.validate_translation(valid_data() | {"title_it": source_title}, True, units(), source_title)
    assert result["body_likely_untranslated"] is False
    assert result["title_likely_untranslated"] is True
    assert result["valid"] is False


def test_marker_light_source_still_rejects_unchanged_prose_headline():
    source_title = "Roman Reigns Returns To WWE SmackDown Following Injury Update"
    assert likely_macroscopic_english(LOW_MARKER_ENGLISH) is False
    result = bob.validate_translation(
        {"title_it": source_title, "translations": {"b1": LOW_MARKER_ITALIAN}},
        True, [{"id": "b1", "text": LOW_MARKER_ENGLISH}], source_title,
    )
    assert result["body_likely_untranslated"] is False
    assert result["title_likely_untranslated"] is True
    assert result["title_source_match"] == "page"
    assert result["reasons"] == ["untranslated_title"]


def test_bob_rejects_title_copied_from_feed_when_page_title_differs():
    page_title = "Roman Reigns WWE Status After SmackDown"
    feed_title = "Roman Reigns Returns To WWE SmackDown Following Injury Update"
    result = bob.validate_translation(valid_data() | {"title_it": feed_title}, True, units(), page_title, feed_title)
    assert result["title_likely_untranslated"] is True
    assert result["title_source_match"] == "feed"
    assert "untranslated_title" in result["reasons"]


def test_bob_still_rejects_title_copied_from_page():
    page_title = "Roman Reigns Returns To WWE SmackDown Following Injury Update"
    result = bob.validate_translation(valid_data() | {"title_it": page_title}, True, units(), page_title, "Different Feed Headline")
    assert result["title_likely_untranslated"] is True
    assert result["title_source_match"] == "page"


def test_bob_accepts_italian_title_different_from_page_and_feed():
    result = bob.validate_translation(
        valid_data(), True, units(), "Roman Reigns WWE Status After SmackDown",
        "Roman Reigns Returns To WWE SmackDown Following Injury Update",
    )
    assert result["title_likely_untranslated"] is False
    assert result["title_source_match"] is None
    assert result["valid"] is True


def assert_official_unchanged_title_is_accepted(title):
    result = bob.validate_translation(valid_data() | {"title_it": title}, True, units(), title)
    assert result["body_likely_untranslated"] is False
    assert result["title_likely_untranslated"] is False
    assert result["valid"] is True


def test_unchanged_official_show_name_is_not_untranslated_title():
    assert_official_unchanged_title_is_accepted("WWE Saturday Night's Main Event")


def test_unchanged_official_championship_is_not_untranslated_title():
    assert_official_unchanged_title_is_accepted("World Heavyweight Championship")


def test_unchanged_womens_championship_is_not_untranslated_title():
    assert_official_unchanged_title_is_accepted("WWE Women's Championship")


def test_unchanged_nickname_branding_is_not_untranslated_title():
    assert_official_unchanged_title_is_accepted("The American Nightmare Cody Rhodes")


def test_short_official_title_is_not_rejected():
    result = bob.validate_translation(valid_data() | {"title_it": "WWE RAW"}, True, units(), "WWE RAW")
    assert result["title_likely_untranslated"] is False


def test_proper_names_and_short_english_quote_do_not_trigger():
    text = ITALIAN + ' Bully Ray ha concluso: "The Vision".'
    evidence = language_escape_evidence("", "Titolo italiano", {}, {"b1": text})
    assert evidence["residual_english_body"] is False


def test_unused_english_translation_key_does_not_contaminate_rendered_body():
    translations = {"b1": LOW_MARKER_ITALIAN, "unused_debug": ENGLISH * 3}
    result = bob.validate_translation(
        {"title_it": "Risultati completi dello show WWE", "translations": translations},
        True, [{"id": "b1", "text": LOW_MARKER_ENGLISH}], "WWE Results",
    )
    assert result["residual_english_body"] is False
    assert result["valid"] is True
    assert "unused_debug" not in bob.render_body([{"type": "text", "block_id": "b1", "text": LOW_MARKER_ENGLISH}], translations)
    assert ENGLISH not in bob.render_body([{"type": "text", "block_id": "b1", "text": LOW_MARKER_ENGLISH}], translations)


def test_required_english_unit_remains_rejected_with_foreign_key_present():
    result = bob.validate_translation(
        {"title_it": "Risultati completi dello show WWE", "translations": {"b1": ENGLISH * 2, "unused": LOW_MARKER_ITALIAN}},
        True, [{"id": "b1", "text": LOW_MARKER_ENGLISH}], "WWE Results",
    )
    assert result["residual_english_body"] is True
    assert result["valid"] is False


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


def test_alfred_blocks_low_marker_near_identical_body_escape():
    article = bob_article(LOW_MARKER_REPHRASED, title="Risultati completi dello show WWE")
    article["elements"] = [{"type": "text", "block_id": "b1", "text": LOW_MARKER_ENGLISH}]
    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "untranslated_body" in {item["code"] for item in review["issues"]}
    assert review["diagnostics"]["translation_escape_evidence"]["near_identical_body"] is True


def test_alfred_approves_italian_with_legitimate_english_terms():
    review = alfred.review_article(bob_article(ITALIAN))
    assert review["decision"] == "approved"


def test_alfred_blocks_english_excerpt_escape():
    article = bob_article(ITALIAN, title="Titolo italiano valido")
    article["excerpt_it"] = SOURCE_DESCRIPTION
    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "residual_english_excerpt" in {item["code"] for item in review["issues"]}
    assert review["diagnostics"]["excerpt_translation_evidence"]["excerpt_residual_english"] is True


def test_alfred_blocks_excerpt_unchanged_from_source_description():
    article = bob_article(ITALIAN, title="Titolo italiano valido")
    article["excerpt_it"] = SOURCE_DESCRIPTION
    article["meta"] = {"description": SOURCE_DESCRIPTION}
    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "untranslated_excerpt" in {item["code"] for item in review["issues"]}


def test_alfred_approves_valid_italian_excerpt():
    article = bob_article(ITALIAN, title="Titolo italiano valido")
    article["excerpt_it"] = ITALIAN_EXCERPT
    article["meta"] = {"description": SOURCE_DESCRIPTION}
    review = alfred.review_article(article)
    assert review["decision"] == "approved"
    assert review["diagnostics"]["excerpt_translation_evidence"]["excerpt_likely_untranslated"] is False


def test_alfred_accepts_italian_with_repeated_official_name():
    article = bob_article(ITALIAN_JUDGMENT_DAY, title="The Judgment Day domina WWE Raw")
    review = alfred.review_article(article)
    assert review["decision"] == "approved"
    assert "residual_english_body" not in {item["code"] for item in review["issues"]}


def test_alfred_marker_light_source_rejects_unchanged_prose_headline():
    source_title = "Roman Reigns Returns To WWE SmackDown Following Injury Update"
    article = bob_article(LOW_MARKER_ITALIAN, title=source_title, source_title=source_title)
    article["meta"] = {"source_title": source_title}
    article["elements"] = [{"type": "text", "block_id": "b1", "text": LOW_MARKER_ENGLISH}]
    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "untranslated_title" in {item["code"] for item in review["issues"]}
    assert review["diagnostics"]["translation_escape_evidence"]["title_source_match"] == "page"


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


def test_alfred_rejects_title_copied_from_feed_when_page_differs():
    feed_title = "Roman Reigns Returns To WWE SmackDown Following Injury Update"
    article = bob_article(ITALIAN, title=feed_title, source_title=feed_title)
    article["meta"] = {"source_title": "Roman Reigns WWE Status After SmackDown"}
    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "untranslated_title" in {item["code"] for item in review["issues"]}
    assert review["diagnostics"]["translation_escape_evidence"]["title_source_match"] == "feed"


def test_alfred_without_source_units_keeps_whole_body_english_fallback():
    article = bob_article(ENGLISH * 2, title="Titolo italiano valido")
    article.pop("elements")
    review = alfred.review_article(article)
    assert review["decision"] == "needs_revision"
    assert "residual_english_body" in {item["code"] for item in review["issues"]}


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
