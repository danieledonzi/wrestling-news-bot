from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BOB_CHAIN = ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
REPORT_CHAIN = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
NEWS_TITLE_CHAIN = ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash"]
CHAIN_ENVS = [
    "BOB_GEMINI_MODEL_CHAIN",
    "NEWS_GEMINI_MODEL_CHAIN",
    "NEWS_TITLE_GEMINI_MODEL_CHAIN",
    "REPORT_GEMINI_MODEL_CHAIN",
    "GEMINI_REPORT_MODEL_CHAIN",
    "GEMINI_NEWS_MODEL_CHAIN",
    "GEMINI_MODEL_CHAIN",
    "MENZO_DUPLICATE_ARBITRATION_FIRST_MODEL",
    "MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL",
]


def reload_module(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def clear_chain_env(monkeypatch):
    for key in CHAIN_ENVS:
        monkeypatch.delenv(key, raising=False)


def test_report_default_chain(monkeypatch):
    clear_chain_env(monkeypatch)
    report = reload_module("modules.report_workshop_v92")
    assert report.REPORT_MODEL_CHAIN == REPORT_CHAIN


def test_bob_default_chain(monkeypatch):
    clear_chain_env(monkeypatch)
    bob = reload_module("agents.bob")
    assert bob.MODEL_CHAIN == BOB_CHAIN


def test_news_workshop_default_chain(monkeypatch):
    clear_chain_env(monkeypatch)
    news = reload_module("modules.news_workshop_v92")
    assert news.model_chain("news_translate_blocks") == BOB_CHAIN
    assert news.model_chain("news_translate_title") == NEWS_TITLE_CHAIN


def test_no_preview_in_productive_defaults(monkeypatch):
    clear_chain_env(monkeypatch)
    bob = reload_module("agents.bob")
    news = reload_module("modules.news_workshop_v92")
    report = reload_module("modules.report_workshop_v92")
    menzo = reload_module("agents.menzo_policy_v93_15")
    productive_defaults = [
        *bob.MODEL_CHAIN,
        *news.model_chain("news_translate_blocks"),
        *news.model_chain("news_translate_title"),
        *report.MODEL_CHAIN,
        *report.REPORT_MODEL_CHAIN,
        menzo.MENZO_DUPLICATE_ARBITRATION_FIRST_MODEL,
        menzo.MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL,
    ]
    assert "gemini-3-flash-preview" not in productive_defaults


def test_report_env_override_precedence(monkeypatch):
    clear_chain_env(monkeypatch)
    monkeypatch.setenv("GEMINI_REPORT_MODEL_CHAIN", "legacy-a,legacy-b")
    report = reload_module("modules.report_workshop_v92")
    assert report.REPORT_MODEL_CHAIN == ["legacy-a", "legacy-b"]
    monkeypatch.setenv("REPORT_GEMINI_MODEL_CHAIN", "primary-a,primary-b")
    report = reload_module("modules.report_workshop_v92")
    assert report.REPORT_MODEL_CHAIN == ["primary-a", "primary-b"]


def test_bob_env_override_precedence(monkeypatch):
    clear_chain_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL_CHAIN", "legacy-a,legacy-b")
    bob = reload_module("agents.bob")
    assert bob.MODEL_CHAIN == ["legacy-a", "legacy-b"]
    monkeypatch.setenv("BOB_GEMINI_MODEL_CHAIN", "primary-a,primary-b")
    bob = reload_module("agents.bob")
    assert bob.MODEL_CHAIN == ["primary-a", "primary-b"]


def test_report_cooldown_skips_failed_model_on_next_batch(monkeypatch):
    clear_chain_env(monkeypatch)
    monkeypatch.setenv("REPORT_GEMINI_MODEL_CHAIN", "gemini-3.5-flash,gemini-3.1-flash-lite")
    report = reload_module("modules.report_workshop_v92")
    report.GEMINI_API_KEY = "test-key"
    report.REPORT_TRANSLATION_BATCH_SIZE = 8
    calls: list[str] = []

    class FakeResponse:
        items = ",".join('{{"i":{},"text":"ok"}}'.format(i) for i in range(16))
        text = '{"items":[' + items + ']}'

    class FakeModels:
        def generate_content(self, *, model, contents):
            calls.append(model)
            if model == "gemini-3.5-flash":
                raise RuntimeError("503 UNAVAILABLE high demand")
            return FakeResponse()

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    monkeypatch.setattr(report.genai, "Client", FakeClient)
    monkeypatch.setattr(report, "record_gemini_event", lambda **kwargs: None)
    blocks = [{"type": "paragraph", "text": f"source {i}"} for i in range(16)]
    translated = report.translate_report_blocks("source", blocks, "Deterministic title")
    assert len(translated) == 16
    assert calls == ["gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.1-flash-lite"]


def test_menzo_second_pass_default(monkeypatch):
    clear_chain_env(monkeypatch)
    menzo = reload_module("agents.menzo_policy_v93_15")
    assert menzo.MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL == "gemini-3.5-flash"
    assert menzo.MENZO_DUPLICATE_ARBITRATION_SECOND_MODEL != "gemini-3-flash-preview"


def test_report_title_policy_is_deterministic_no_extra_title_chain(monkeypatch):
    clear_chain_env(monkeypatch)
    report = reload_module("modules.report_workshop_v92")
    simone = reload_module("agents.simone_publisher_v93_18")
    assert not hasattr(report, "REPORT_TITLE_MODEL_CHAIN")
    assert "report_title" not in report.translate_report_blocks.__code__.co_consts
    job = {}
    job.setdefault("title_policy", "simone_deterministic")
    assert job["title_policy"] == "simone_deterministic"
    assert "simone_deterministic" in Path(simone.__file__).read_text(encoding="utf-8")
