import copy
import json

import pytest

from modules import report_workshop_v92 as workshop
from modules.report_postshow import plan_postshow, render_postshow, validate_postshow


def blocks():
    # Reduced regression excerpts from Raw 26 October 2026, with an added
    # unknown-outcome item to test the distinction from explicit cancellation.
    return [
        {"type": "paragraph", "text": "Tonight's Raw promises Becky Lynch vs. Stephanie Vaquer."},
        {"type": "heading", "text": "Matches & Key Moments Scheduled for WWE RAW", "level": "h2"},
        {"type": "paragraph", "text": "Becky Lynch vs. Stephanie Vaquer", "list_type": "ul"},
        {"type": "paragraph", "text": "A vs. B", "list_type": "ul"},
        {"type": "embed", "url": "https://twitter.com/WWE/status/123"},
        {"type": "heading", "text": "WWE RAW Results (10/26/26): Live Match Updates and Highlights", "level": "h2"},
        {"type": "paragraph", "text": "Adam Pearce says Stephanie Vaquer is not medically cleared. Becky Lynch will instead challenge Liv Morgan tonight."},
        {"type": "paragraph", "text": "Sami Zayn defeated Je'Von Evans in an added match."},
        {"type": "image", "src": "https://source.test/action.jpg"},
        {"type": "quote", "text": "I will defend the title next week."},
        {"type": "paragraph", "text": "Liv Morgan retained against Becky Lynch. Tiffany's attempted cash-in was stopped."},
        {"type": "embed", "url": "https://twitter.com/WWE/status/456"},
    ]


def final():
    return {"intro": {"text": "Liv Morgan ha conservato il titolo contro Becky Lynch dopo il cambio di programma.", "source_indexes": [6, 10]},
        "card": [
            {"text": "Vaquer–Lynch: incontro sostituito per l'indisponibilità di Vaquer.", "status": "CHANGED", "result_index": None, "source_indexes": [6], "preview_indexes": [2]},
            {"text": "A–B", "status": "UNCONFIRMED", "result_index": None, "source_indexes": [], "preview_indexes": [3]},
            {"text": "Sami Zayn ha battuto Je'Von Evans.", "status": "HELD", "result_index": 7, "source_indexes": [7], "preview_indexes": []},
            {"text": "Liv Morgan ha conservato il titolo contro Becky Lynch.", "status": "HELD", "result_index": 10, "source_indexes": [10], "preview_indexes": []},
        ]}


def test_only_bounded_preview_is_replaced_and_media_remain_in_order(monkeypatch):
    source = blocks()
    original = copy.deepcopy(source)
    plan = plan_postshow(source)
    assert plan["replace_indexes"] == [0, 1, 2, 3]
    plan["final"] = validate_postshow(final(), plan)
    translated = {i: b["text"] for i, b in enumerate(source) if "text" in b and i >= plan["body_start"]}
    monkeypatch.setattr(workshop, "upload_media", lambda src: (1, src))
    rendered = workshop.render_blocks(source, translated, job={}, postshow=plan)
    assert "Tonight's Raw promises" not in rendered
    assert "Card finale e variazioni" in rendered
    assert "esito non riportato nella fonte" in rendered
    assert rendered.index("status/123") < rendered.index("Adam Pearce") < rendered.index("action.jpg") < rendered.index("next week") < rendered.index("status/456")
    assert "I will defend the title next week." in rendered  # in-show quote is not retroactively rewritten
    assert source == original


@pytest.mark.parametrize("source", [[], [{"type": "paragraph", "text": "A live promo without a safe boundary."}],
    [{"type": "heading", "text": "Results", "level": "h2"}, {"type": "paragraph", "text": "A wins."}]])
def test_no_guessing_when_no_preamble_can_be_isolated(source):
    assert plan_postshow(source) is None


def test_narrative_start_and_preshow_are_retained_as_body():
    for boundary in [{"type": "paragraph", "text": "The show opens with the commentators."},
                     {"type": "heading", "text": "Countdown pre-show results", "level": "h2"}]:
        source = [{"type": "paragraph", "text": "Tonight's preview."}, boundary]
        assert plan_postshow(source)["body_start"] == 1


@pytest.mark.parametrize("mutate", [
    lambda x: x.pop("intro"),
    lambda x: x["intro"].update(source_indexes=[999]),
    lambda x: x["intro"].update(source_indexes=[True]),
    lambda x: x["card"].pop(0),
    lambda x: x["card"].append(copy.deepcopy(x["card"][0])),
    lambda x: x["card"][0].update(source_indexes=[]),
    lambda x: x["card"][1].update(status="CANCELLED"),
    lambda x: x["card"][1].update(source_indexes=[6]),
    lambda x: x["card"][2].update(text="<script>bad</script>"),
])
def test_invalid_evidence_or_missing_preview_coverage_stops_publication(mutate):
    value = final()
    mutate(value)
    with pytest.raises(ValueError, match="Report postshow"):
        validate_postshow(value, plan_postshow(blocks()))


def test_aaa_unknown_outcome_does_not_become_a_cancellation():
    plan = {"source_indexes": [10], "preview_indexes": [2]}
    value = {"intro": {"text": "Si è svolto Heroes Inmortales.", "source_indexes": [10]},
             "card": [{"text": "Rey Fenix–Mini Vikingo", "status": "UNCONFIRMED", "result_index": None, "source_indexes": [], "preview_indexes": [2]}]}
    plan["final"] = validate_postshow(value, plan)
    assert "esito non riportato nella fonte" in render_postshow(plan)
    assert "annullato" not in render_postshow(plan)


def test_full_final_context_only_in_first_existing_batch(monkeypatch):
    source = blocks() + [{"type": "paragraph", "text": f"Body action {i}."} for i in range(16)]
    source.append({"type": "paragraph", "text": "FINAL SOURCE DETAIL BEYOND FIRST BATCH"})
    plan = plan_postshow(source)
    monkeypatch.setattr(workshop, "REPORT_TRANSLATION_BATCH_SIZE", 8)
    prompts = []

    def generate(prompt, **kwargs):
        prompts.append(prompt)
        batch, _ = json.JSONDecoder().raw_decode(prompt.split("BLOCCHI JSON:\n", 1)[1].lstrip())
        data = {"items": [{"i": b["i"], "text": b["text"]} for b in batch]}
        if len(prompts) == 1:
            data["postshow"] = final()
        return data, "offline"

    monkeypatch.setattr(workshop, "generate_json", generate)
    translated = workshop.translate_report_blocks("Raw", source, "Raw report", postshow=plan)
    assert len(prompts) == 3
    assert "FINAL SOURCE DETAIL BEYOND FIRST BATCH" in prompts[0]
    assert "RACCONTO CONCLUSIVO COMPLETO" not in prompts[1]
    assert len(translated) == len([i for i in plan["source_indexes"]])
    assert plan["final"] == validate_postshow(final(), plan)


@pytest.mark.parametrize("primary_output, lite_output, expected", [
    ("not JSON", '{"ok":true}', ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]),
    ("{}", '{"ok":true}', ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]),
    ("not JSON", "not JSON", ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-pro"]),
])
def test_report_tries_lite_before_pro_on_invalid_json(monkeypatch, primary_output, lite_output, expected):
    calls = []
    monkeypatch.setattr(workshop, "GEMINI_API_KEY", "offline")
    monkeypatch.setattr(workshop, "REPORT_MODEL_CHAIN", ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-pro"])
    monkeypatch.setattr(workshop, "record_gemini_attempt", lambda **kw: None)
    outputs = [primary_output, lite_output, '{"ok":true}']

    class Models:
        def generate_content(self, model, contents, config=None):
            assert config == {"response_mime_type": "application/json"}
            calls.append(model)
            return type("Response", (), {"text": outputs[len(calls)-1]})()

    monkeypatch.setattr(workshop.genai, "Client", lambda **kw: type("Client", (), {"models": Models()})())
    def validate(data):
        if not data.get("ok"):
            raise ValueError("missing contract field")

    data, model = workshop.generate_json("offline", chain_name="report_blocks_test", response_validator=validate)
    assert data == {"ok": True}
    assert calls == expected and model == expected[-1]


def test_future_match_announcement_cannot_become_a_held_match():
    source = blocks() + [{"type": "paragraph", "text": "Adam Pearce makes The Vision vs. Penta and Evans official for Crown Jewel."}]
    plan = plan_postshow(source)
    value = final()
    value["card"].append({"text": "The Vision contro Penta e Evans", "status": "HELD", "source_indexes": [12], "result_index": 12, "preview_indexes": []})
    with pytest.raises(ValueError, match="actual result evidence"):
        validate_postshow(value, plan)


def test_disqualification_cannot_be_relabelled_as_no_contest():
    source = blocks()
    source[10]["text"] = "The winner of the match due to a disqualification is Becky Lynch, but still champion, Liv Morgan!"
    plan = plan_postshow(source)
    value = final()
    value["intro"] = {"text": "Liv Morgan e Becky Lynch hanno chiuso con un No Contest.", "source_indexes": [10]}
    with pytest.raises(ValueError, match="unsupported result method"):
        validate_postshow(value, plan)


def test_every_explicit_result_must_appear_once_in_final_card():
    source = blocks()
    source[7]["text"] = "The winner and still champion, Sami Zayn!"
    plan = plan_postshow(source)
    value = final()
    value["card"] = [e for e in value["card"] if e.get("result_index") != 7]
    with pytest.raises(ValueError, match="missing or repeated actual result"):
        validate_postshow(value, plan)


def test_played_match_card_uses_translated_actual_result_not_generated_preview_label():
    source = blocks()
    plan = plan_postshow(source)
    value = final()
    value["card"][-1]["text"] = "Vecchia stipulazione ormai superata"
    plan["final"] = value
    translated = {i: b["text"] for i, b in enumerate(source) if "text" in b and i >= plan["body_start"]}
    rendered = render_postshow(plan, source, translated)
    assert "Vecchia stipulazione" not in rendered
    assert "Liv Morgan retained against Becky Lynch" in rendered


def test_preview_metadata_refs_are_allowed_but_not_as_occurrence_evidence():
    plan = plan_postshow(blocks())
    value = final()
    value["card"][2]["source_indexes"] = [0, 7]
    assert validate_postshow(value, plan)
    value["card"][2]["source_indexes"] = [0]
    with pytest.raises(ValueError, match="preview is not occurrence evidence"):
        validate_postshow(value, plan)


def test_metadata_citation_does_not_hide_actual_disqualification_evidence():
    source = blocks()
    source[10]["text"] = "The winner of the match due to a disqualification is Becky Lynch!"
    plan = plan_postshow(source)
    value = final()
    value["intro"] = {"text": "Becky Lynch ha vinto per squalifica.", "source_indexes": [0]}
    assert validate_postshow(value, plan)


def test_segment_cannot_keep_the_initial_future_announcement():
    plan = plan_postshow(blocks())
    value = final()
    value["card"].append({"text": "Jay White parlerà allo show", "status": "SEGMENT", "source_indexes": [6], "result_index": None, "preview_indexes": []})
    with pytest.raises(ValueError, match="still phrased as a preview"):
        validate_postshow(value, plan)


@pytest.mark.parametrize("heading", ["Countdown Pre-Show", "Pre-Show", "Zero Hour", "Buy In", "Kickoff"])
def test_preshow_without_results_heading_remains_complete_and_collapsible(heading):
    source = [
        {"type": "paragraph", "text": "Tonight's event preview."},
        {"type": "heading", "text": heading, "level": "h2"},
        {"type": "heading", "text": "A vs. B", "level": "h3"},
        {"type": "paragraph", "text": "A wins!"},
        {"type": "embed", "url": "https://twitter.com/WWE/status/123"},
        {"type": "heading", "text": "Main show results", "level": "h2"},
        {"type": "paragraph", "text": "The show opens with the main event."},
    ]
    plan = plan_postshow(source)
    assert plan["body_start"] == 1 and plan["replace_indexes"] == [0]
    assert 3 in plan["result_indexes"]
    plan["final"] = {"intro": {"text": "L'evento si è concluso.", "source_indexes": [3]},
        "card": [{"text": "A batte B.", "status": "HELD", "source_indexes": [2, 3], "result_index": 3, "preview_indexes": []}]}
    translated = {i: b["text"] for i, b in enumerate(source) if "text" in b and i >= 1}
    rendered = workshop.render_blocks(source, translated, job={"event_type": "PLE"}, postshow=plan)
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(rendered, "html.parser")
    assert "A wins!" in soup.find("details").get_text()
    assert "status/123" in str(soup.find("details"))
    assert "Main show results" not in soup.find("details").get_text()


@pytest.mark.parametrize("outcome", ["A wins!", "A defeats B.", "A pins B.", "A submits B.",
                                      "A won!", "A pinned B.", "A submitted B."])
def test_ordinary_completed_outcomes_are_valid_held_evidence(outcome):
    source = blocks()
    source[10]["text"] = outcome
    plan = plan_postshow(source)
    assert 10 in plan["result_indexes"]
    assert validate_postshow(final(), plan)


@pytest.mark.parametrize("prediction", ["A will win!", "A will defeat B.", "A will pin B.", "A will submit B."])
def test_future_win_predictions_are_not_result_evidence(prediction):
    source = blocks()
    source[10]["text"] = prediction
    plan = plan_postshow(source)
    assert 10 not in plan["result_indexes"]
    with pytest.raises(ValueError, match="actual result evidence"):
        validate_postshow(final(), plan)


@pytest.mark.parametrize("has_metadata", [True, False])
def test_final_card_never_exposes_result_inline_link_markers(has_metadata):
    from bs4 import BeautifulSoup
    source = blocks()
    url = "https://twitter.com/WWE/status/789"
    if has_metadata:
        source[10]["inline_media_links"] = [{"index": 0, "url": url}]
    plan = plan_postshow(source)
    plan["final"] = final()
    translated = {i: b["text"] for i, b in enumerate(source) if "text" in b and i >= plan["body_start"]}
    translated[10] = "Vincitrice: [OWTVLINK0]Liv Morgan[/OWTVLINK0]."
    rendered = render_postshow(plan, source, translated)
    assert "OWTVLINK" not in rendered
    soup = BeautifulSoup(rendered, "html.parser")
    assert (soup.select_one('li a[href="' + url + '"]') is not None) == has_metadata
    assert "Vincitrice: Liv Morgan." in soup.get_text()
