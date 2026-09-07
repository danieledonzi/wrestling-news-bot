import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import bob
from agents import source_body


AJ_NOTICE = (
    "This transcript was produced exclusively for Ringside News from the original recording. "
    "Republishing the full transcript is prohibited. When using excerpts, prominent credit and "
    "a link to this article are required."
)
SHORT_NOTICE = "This transcript was produced from the original recording."
AUTHOR_BIO = (
    "H Jenkins has been breaking pro wrestling news on Ringside News for nearly a decade, "
    "with his reports featured by TMZ, Forbes, The Sun, and more."
)
CTA = "Follow Ringside News and add us as a preferred source for more wrestling updates."
EDITORIAL = "AJ Styles explained why the final match was important to his career."


def elements(*texts, kinds=None):
    kinds = kinds or ["text"] * len(texts)
    return [{"type": kind, "text": text} for kind, text in zip(kinds, texts)]


def response(*rows):
    return json.dumps({"decisions": [
        {"id": f"tail_{index}", "decision": decision, "category": category}
        for index, (decision, category) in enumerate(rows, start=1)
    ]})


def install_response(monkeypatch, raw, calls=None):
    def fake(prompt, *, ledger_context):
        if calls is not None:
            calls.append((prompt, ledger_context))
        return raw, "gemini-3.1-flash-lite"
    monkeypatch.setattr(bob, "call_terminal_tail_classifier", fake)


@pytest.mark.parametrize(
    ("footer", "category"),
    [
        (AJ_NOTICE, "CREDIT_COPYRIGHT"),
        (SHORT_NOTICE, "TRANSCRIPT_NOTICE"),
        (AUTHOR_BIO, "BIO"),
        (CTA, "CTA"),
    ],
)
def test_real_terminal_residue_removed_before_translation(monkeypatch, footer, category):
    install_response(monkeypatch, response(("KEEP", "EDITORIAL"), ("DROP", category)))
    cleaned, telemetry = bob.sanitize_terminal_tail(elements(EDITORIAL, footer))

    assert [item["text"] for item in cleaned] == [EDITORIAL]
    units = bob.build_translation_units(cleaned)
    assert [unit["text"] for unit in units] == [EDITORIAL]
    assert all(footer not in unit["text"] for unit in units)
    assert telemetry["semantic_tail_blocks_removed"] == 1
    assert telemetry["semantic_tail_removed_blocks"] == [{"id": "tail_2", "category": category}]
    assert telemetry["semantic_tail_sanitizer_status"] == "validated"
    assert telemetry["semantic_tail_fail_open_used"] is False


def test_multi_block_footer_removed_in_one_request(monkeypatch):
    calls = []
    install_response(monkeypatch, response(
        ("KEEP", "EDITORIAL"),
        ("DROP", "TRANSCRIPT_NOTICE"),
        ("DROP", "BIO"),
        ("DROP", "CTA"),
    ), calls)
    cleaned, telemetry = bob.sanitize_terminal_tail(elements(EDITORIAL, SHORT_NOTICE, AUTHOR_BIO, CTA))

    assert [item["text"] for item in cleaned] == [EDITORIAL]
    assert len(calls) == 1
    assert calls[0][0].count('"id": "tail_') == 4
    assert telemetry["semantic_tail_blocks_removed"] == 3


@pytest.mark.parametrize(
    "closing",
    [
        'Rhea Ripley said, "I kept fighting because this championship means everything to me."',
        "The court transcript is central to the genuine copyright and source-credit dispute in this case.",
    ],
)
def test_legitimate_final_editorial_content_is_retained(monkeypatch, closing):
    install_response(monkeypatch, response(("KEEP", "EDITORIAL"), ("KEEP", "EDITORIAL")))
    original = elements(EDITORIAL, closing, kinds=["text", "quote"])
    cleaned, telemetry = bob.sanitize_terminal_tail(original)
    assert cleaned == original
    assert telemetry["semantic_tail_blocks_removed"] == 0


def test_interior_drop_cannot_be_removed_past_terminal_keep(monkeypatch):
    install_response(monkeypatch, response(("DROP", "OTHER_BOILERPLATE"), ("KEEP", "EDITORIAL")))
    original = elements("A possible footer-looking sentence.", "A genuine closing quote.")
    cleaned, telemetry = bob.sanitize_terminal_tail(original)
    assert cleaned == original
    assert telemetry["semantic_tail_blocks_removed"] == 0


@pytest.mark.parametrize("raw", ["", "not json", json.dumps({"decisions": []}), response(("KEEP", "EDITORIAL"))])
def test_malformed_or_missing_decisions_fail_open(monkeypatch, raw):
    install_response(monkeypatch, raw)
    original = elements(EDITORIAL, SHORT_NOTICE)
    cleaned, telemetry = bob.sanitize_terminal_tail(original)
    assert cleaned == original
    assert telemetry["semantic_tail_sanitizer_status"] == "malformed_response"
    assert telemetry["semantic_tail_fail_open_used"] is True


def test_provider_failure_fails_open_and_one_call_maximum(monkeypatch):
    calls = []
    install_response(monkeypatch, None, calls)
    original = elements(EDITORIAL, SHORT_NOTICE)
    cleaned, telemetry = bob.sanitize_terminal_tail(original)
    assert cleaned == original
    assert len(calls) == 1
    assert telemetry["semantic_tail_sanitizer_status"] == "provider_failed"
    assert telemetry["semantic_tail_fail_open_used"] is True


def test_provider_exception_fails_open(monkeypatch):
    calls = 0
    def fail(prompt, *, ledger_context):
        nonlocal calls
        calls += 1
        raise TimeoutError("timed out")
    monkeypatch.setattr(bob, "call_terminal_tail_classifier", fail)
    original = elements(EDITORIAL, SHORT_NOTICE)
    cleaned, telemetry = bob.sanitize_terminal_tail(original)
    assert cleaned == original
    assert calls == 1
    assert telemetry["semantic_tail_sanitizer_status"] == "provider_failed"


def test_provider_client_has_bounded_timeout_and_no_sdk_retry(monkeypatch):
    from google import genai

    clients = []
    ledger = []

    class FakeModels:
        def generate_content(self, *, model, contents):
            return type("Response", (), {"text": response(("KEEP", "EDITORIAL"))})()

    class FakeClient:
        def __init__(self, **kwargs):
            clients.append(kwargs)
            self.models = FakeModels()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(bob, "record_gemini_attempt", lambda **kwargs: ledger.append(kwargs))

    cleaned, telemetry = bob.sanitize_terminal_tail(elements(EDITORIAL))

    assert cleaned == elements(EDITORIAL)
    assert telemetry["semantic_tail_sanitizer_status"] == "validated"
    assert len(clients) == 1
    http_options = clients[0]["http_options"]
    assert http_options.timeout == bob.REQUEST_TIMEOUT * 1000
    assert http_options.retry_options.attempts == 1
    assert len(ledger) == 1
    assert ledger[0]["purpose"] == "bob_terminal_tail_sanitizer"
    assert ledger[0]["retry"] is False
    assert ledger[0]["fallback"] is False


def test_only_last_five_textual_blocks_are_supplied(monkeypatch):
    calls = []
    install_response(monkeypatch, response(*[("KEEP", "EDITORIAL")] * 5), calls)
    original = elements(*[f"paragraph {index}" for index in range(7)])
    cleaned, telemetry = bob.sanitize_terminal_tail(original, title="Title", source="example.test")
    assert cleaned == original
    assert telemetry["semantic_tail_blocks_examined"] == 5
    assert "paragraph 0" not in calls[0][0]
    assert "paragraph 2" in calls[0][0]


def test_no_textual_tail_does_not_call_provider(monkeypatch):
    monkeypatch.setattr(bob, "call_terminal_tail_classifier", lambda *args, **kwargs: pytest.fail("unexpected call"))
    original = [{"type": "image", "url": "https://example.test/image.jpg"}]
    cleaned, telemetry = bob.sanitize_terminal_tail(original)
    assert cleaned == original
    assert telemetry["semantic_tail_sanitizer_attempted"] is False
    assert telemetry["semantic_tail_sanitizer_status"] == "no_tail"


def test_shared_extractor_keeps_base_terminal_prefilter():
    base_cta = "Subscribe to the site for more wrestling updates."
    cleaned, removed = bob.sanitize_elements(elements(AJ_NOTICE, AUTHOR_BIO, base_cta), "")
    assert cleaned == []
    assert removed[0]["reason"] == "footer_start"


def test_source_body_hydration_filters_footer_without_semantic_provider_call(monkeypatch):
    article = (
        "AJ Styles explained the match result, the decisive sequence, and what the conclusion "
        "means for his wrestling career and future championship plans. " * 3
    )
    html = f"<html><body><article><p>{article}</p><p>{AUTHOR_BIO}</p></article></body></html>"
    calls = []
    monkeypatch.setattr(bob, "fetch_html", lambda url: html)
    monkeypatch.setattr(
        bob,
        "call_terminal_tail_classifier",
        lambda *args, **kwargs: calls.append((args, kwargs)) or pytest.fail("unexpected semantic call"),
    )
    item = {"source_url": "https://www.ringsidenews.com/story"}

    hydrated, reason = source_body.hydrate(item)

    assert (hydrated, reason) == (True, "bob_source_extraction")
    assert source_body.valid_contract(item["canonical_source_body"])
    assert AUTHOR_BIO not in item["canonical_source_body"]["cleaned_full_text"]
    assert calls == []


def test_terminal_cutoff_removes_bio_and_later_avatar(monkeypatch):
    install_response(monkeypatch, response(("KEEP", "EDITORIAL"), ("DROP", "BIO")))
    original = elements(EDITORIAL, AUTHOR_BIO) + [{"type": "image", "url": "https://example.test/avatar.jpg"}]
    cleaned, _ = bob.sanitize_terminal_tail(original)
    assert cleaned == elements(EDITORIAL)


def test_terminal_cutoff_removes_notice_and_later_promotional_embed(monkeypatch):
    install_response(monkeypatch, response(("KEEP", "EDITORIAL"), ("DROP", "TRANSCRIPT_NOTICE")))
    original = elements(EDITORIAL, SHORT_NOTICE) + [{"type": "embed", "url": "https://youtube.com/watch?v=promo"}]
    cleaned, _ = bob.sanitize_terminal_tail(original)
    assert cleaned == elements(EDITORIAL)


def test_terminal_cutoff_retains_earlier_editorial_image(monkeypatch):
    install_response(monkeypatch, response(("KEEP", "EDITORIAL"), ("DROP", "BIO")))
    image = {"type": "image", "url": "https://example.test/editorial.jpg"}
    original = [image] + elements(EDITORIAL, AUTHOR_BIO)
    cleaned, _ = bob.sanitize_terminal_tail(original)
    assert cleaned == [image, {"type": "text", "text": EDITORIAL}]


def test_terminal_keep_after_drop_retains_later_non_text_element(monkeypatch):
    install_response(monkeypatch, response(("DROP", "OTHER_BOILERPLATE"), ("KEEP", "EDITORIAL")))
    image = {"type": "image", "url": "https://example.test/closing.jpg"}
    original = elements("Possible boilerplate.", EDITORIAL) + [image]
    cleaned, telemetry = bob.sanitize_terminal_tail(original)
    assert cleaned == original
    assert telemetry["semantic_tail_blocks_removed"] == 0


def test_terminal_cutoff_removes_interleaved_footer_media(monkeypatch):
    install_response(monkeypatch, response(
        ("KEEP", "EDITORIAL"),
        ("DROP", "TRANSCRIPT_NOTICE"),
        ("DROP", "BIO"),
    ))
    original = (
        elements(EDITORIAL, SHORT_NOTICE)
        + [{"type": "image", "url": "https://example.test/footer.jpg"}]
        + elements(AUTHOR_BIO)
        + [{"type": "embed", "url": "https://youtube.com/watch?v=promo"}]
    )
    cleaned, telemetry = bob.sanitize_terminal_tail(original)
    assert cleaned == elements(EDITORIAL)
    assert telemetry["semantic_tail_blocks_removed"] == 2


def test_article_package_sanitizes_before_translation_units(monkeypatch):
    install_response(monkeypatch, response(("KEEP", "EDITORIAL"), ("DROP", "CREDIT_COPYRIGHT")))
    monkeypatch.setattr(bob, "fetch_html", lambda url: "<html></html>")
    monkeypatch.setattr(
        bob,
        "extract_elements",
        lambda url, raw: (
            {"source_title": "AJ Styles interview", "description": "AJ Styles parla del suo futuro.", "featured_image": ""},
            elements(EDITORIAL, AJ_NOTICE),
            elements(EDITORIAL, AJ_NOTICE),
            [],
            {"stage": "extraction_finished"},
        ),
    )
    translation_prompts = []
    def translate(prompt, **kwargs):
        translation_prompts.append(prompt)
        return json.dumps({
            "title_it": "AJ Styles parla del suo ultimo match",
            "excerpt_it": "AJ Styles riflette sulla sua carriera.",
            "translations": {"b1": "AJ Styles ha spiegato perché l'ultimo match era importante per la sua carriera."},
            "notes": [],
        }), "gemini-3.1-flash-lite", ["gemini-3.1-flash-lite"]
    monkeypatch.setattr(bob, "call_gemini", translate)

    package = bob.article_package({"url": "https://www.ringsidenews.com/story", "title": "AJ Styles interview"})

    assert package["status"] == "ready_for_alfred"
    assert package["translation_unit_count"] == 1
    assert [item["block_id"] for item in package["elements"]] == ["b1"]
    assert AJ_NOTICE not in translation_prompts[0]
    assert package["semantic_tail_blocks_removed"] == 1


def schema_article_html(editorial, footer, structured_suffix=""):
    article_body = f"{editorial} {footer} {structured_suffix}".strip()
    schema = json.dumps({"@context": "https://schema.org", "@type": "NewsArticle", "articleBody": article_body})
    return f"<html><head><script type='application/ld+json'>{schema}</script></head><body><article><p>{editorial}</p><p>{footer}</p></article></body></html>"


def test_article_package_contract_does_not_reintroduce_trimmed_structured_footer(monkeypatch):
    editorial = (
        "AJ Styles explained the match result, the decisive sequence, and the importance of the "
        "conclusion for his wrestling career and future championship plans. " * 5
    )
    calls = []
    install_response(monkeypatch, response(("KEEP", "EDITORIAL"), ("DROP", "TRANSCRIPT_NOTICE")), calls)
    monkeypatch.setattr(bob, "fetch_html", lambda url: schema_article_html(editorial, SHORT_NOTICE))
    monkeypatch.setattr(bob, "call_gemini", lambda *args, **kwargs: ("", "unavailable", []))

    package = bob.article_package({"url": "https://example.test/schema-story", "title": "AJ Styles interview"})

    assert [item["text"] for item in package["elements"]] == [bob.clean_text(editorial)]
    contract_text = package["canonical_source_body"]["cleaned_full_text"]
    assert SHORT_NOTICE not in contract_text
    assert "AJ Styles explained the match result" in contract_text
    assert len(calls) == 1


def test_article_package_keeps_structured_body_preference_when_tail_not_removed(monkeypatch):
    editorial = (
        "Rhea Ripley described the match result, the decisive sequence, and the importance of the "
        "conclusion for her wrestling career and future championship plans. " * 5
    )
    closing = "She said the final decision belongs to the champion."
    structured_only = "Verified structured-only source context."
    calls = []
    install_response(monkeypatch, response(("KEEP", "EDITORIAL"), ("KEEP", "EDITORIAL")), calls)
    monkeypatch.setattr(
        bob, "fetch_html", lambda url: schema_article_html(editorial, closing, structured_only),
    )
    monkeypatch.setattr(bob, "call_gemini", lambda *args, **kwargs: ("", "unavailable", []))

    package = bob.article_package({"url": "https://example.test/schema-keep", "title": "Rhea Ripley interview"})

    assert package["semantic_tail_blocks_removed"] == 0
    assert structured_only in package["canonical_source_body"]["cleaned_full_text"]
    assert len(calls) == 1


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
