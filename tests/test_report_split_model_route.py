"""Regression for stage-aware RAW/SmackDown report provider routing."""
import json
from types import SimpleNamespace

import pytest
from modules import report_workshop_v92 as report
from modules import report_postshow as postshow_module
from modules.report_retry_guard import route_contract_version


class RequestStub:
    def __init__(self, *args, **kwargs):
        self.attempt_number = 0

    def start(self, *args, **kwargs):
        self.attempt_number += 1
        return object()

    def completed(self, *args, **kwargs):
        pass

    def failed(self, *args, **kwargs):
        pass

    def avoided(self, *args, **kwargs):
        pass


def fake_provider(monkeypatch, models, *, bad_models=()):
    calls = []
    monkeypatch.setattr(report, "GEMINI_API_KEY", "test-only")
    monkeypatch.setattr(report, "REPORT_MODEL_CHAIN", list(models))
    monkeypatch.setattr(report, "REPORT_TRANSLATION_BATCH_SIZE", 8)
    monkeypatch.delenv("REPORT_BODY_GEMINI_MODEL_CHAIN", raising=False)
    monkeypatch.setattr(report, "OperationalAIRequest", RequestStub)
    monkeypatch.setattr(report, "record_gemini_attempt", lambda **kw: None)
    monkeypatch.setattr(report, "record_gemini_event", lambda **kw: None)

    class Provider:
        def generate_content(self, *, model, contents, config=None):
            calls.append((model, config))
            batch = json.loads(contents.split("BLOCCHI JSON:\n", 1)[1])
            if model in bad_models:
                blocks = [{"i": batch[0]["i"], "text": ""}]
            else:
                blocks = [{"i": item["i"], "text": "tradotto " + str(item["i"])} for item in batch]
            output = {"items": blocks}
            if "POSTSHOW_TEST_CONTEXT" in contents:
                output["postshow"] = {"strict_test_card": True}
            return SimpleNamespace(text=json.dumps(output))

    monkeypatch.setattr(report.genai, "Client", lambda **kw: SimpleNamespace(models=Provider()))
    return calls


def test_first_postshow_batch_premium_second_body_lite(monkeypatch):
    calls = fake_provider(monkeypatch, ["gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"])
    monkeypatch.setattr(postshow_module, "postshow_prompt",
                        lambda *args, **kw: "POSTSHOW_TEST_CONTEXT")
    def validate(value, plan):
        if value != {"strict_test_card": True}:
            raise ValueError("missing postshow card")
        return value
    monkeypatch.setattr(postshow_module, "validate_postshow", validate)
    blocks = [{"type": "paragraph", "text": f"segment {i}"} for i in range(16)]
    plan = {"replace_indexes": set()}
    translation = report.translate_report_blocks("Raw", blocks, "Raw title", postshow=plan)
    assert len(translation) == 16
    assert [model for model, _ in calls] == ["gemini-3.8-flash", "gemini-3.1-flash-lite"]
    assert calls[0][1] == {"response_mime_type": "application/json"}
    assert calls[1][1] is None
    assert plan["final"] == {"strict_test_card": True}


def test_body_incomplete_lite_falls_back_to_premium(monkeypatch):
    calls = fake_provider(monkeypatch, ["gemini-3.8-flash", "gemini-3.1-flash-lite"],
                          bad_models={"gemini-3.1-flash-lite"})
    blocks = [{"type": "paragraph", "text": f"segment {i}"} for i in range(8)]
    result = report.translate_report_blocks("source", blocks, "title")
    assert len(result) == 8
    assert [model for model, _ in calls] == ["gemini-3.1-flash-lite", "gemini-3.8-flash"]


def test_two_body_failures_do_not_trigger_terminal_postshow_lock(monkeypatch):
    calls = fake_provider(monkeypatch,
        ["gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"],
        bad_models={"gemini-3.1-flash-lite", "gemini-3.5-flash-lite"})
    blocks = [{"type": "paragraph", "text": f"segment {i}"} for i in range(8)]
    result = report.translate_report_blocks("source", blocks, "title")
    assert len(result) == 8
    assert [model for model, _ in calls] == [
        "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"
    ]


def test_lite_first_default_is_promoted_for_strict_postshow(monkeypatch):
    """Regression for Codex P2: missing env must not make Lite first for the card."""
    calls = fake_provider(monkeypatch, [
        "gemini-3.1-flash-lite", "gemini-3.5-flash-lite",
        "gemini-3.8-flash", "gemini-3.5-flash",
    ])
    monkeypatch.setattr(postshow_module, "postshow_prompt",
                        lambda *args, **kw: "POSTSHOW_TEST_CONTEXT")

    def check(value, plan):
        if value != {"strict_test_card": True}:
            raise ValueError("invalid result card")
        return value

    monkeypatch.setattr(postshow_module, "validate_postshow", check)
    blocks = [{"type": "paragraph", "text": f"segment {i}"} for i in range(16)]
    report.translate_report_blocks("Raw", blocks, "Raw title",
                                   postshow={"replace_indexes": set()})
    assert [model for model, _ in calls] == [
        "gemini-3.8-flash", "gemini-3.1-flash-lite"
    ]
    assert report.report_postshow_model_chain() == [
        "gemini-3.8-flash", "gemini-3.5-flash",
        "gemini-3.1-flash-lite", "gemini-3.5-flash-lite",
    ]


def test_body_route_affects_retry_fingerprint(monkeypatch):
    monkeypatch.setattr(report, "REPORT_MODEL_CHAIN", ["gemini-3.8-flash", "gemini-3.1-flash-lite"])
    monkeypatch.delenv("REPORT_BODY_GEMINI_MODEL_CHAIN", raising=False)
    first = route_contract_version(report.effective_report_route())
    assert report.report_body_model_chain() == ["gemini-3.1-flash-lite", "gemini-3.8-flash"]
    monkeypatch.setenv("REPORT_BODY_GEMINI_MODEL_CHAIN", "gemini-3.5-flash-lite,gemini-3.8-flash")
    assert report.report_body_model_chain() == ["gemini-3.5-flash-lite", "gemini-3.8-flash"]
    assert route_contract_version(report.effective_report_route()) != first
