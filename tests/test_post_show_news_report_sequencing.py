"""Offline runner regressions for the existing pre-report scheduling contract."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import newsroom_runner as runner
from agents import bob, menzo_editorial_director_active as active
from agents import menzo_policy_v93_15 as menzo
from agents.news_scheduling import REPORT_PUBLICATION_PLANNED


KEY = "aew_dynamite_2026_09_30"


class Observer:
    def safely(self, *_args, **_kwargs):
        pass

    def summary(self):
        return {}


@pytest.fixture
def run_cycle(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEWSROOM_ENGINE", raising=False)
    monkeypatch.setenv("NEWSROOM_RUN_ID", "sequencing-test")
    monkeypatch.setenv("OWTV_EDITORIAL_DIRECTOR_ACTIVE_ENABLED", "true")
    monkeypatch.setenv("OWTV_EDITORIAL_DIRECTOR_SHADOW_ENABLED", "false")
    monkeypatch.setenv("V93_SKIP_V92_AFTER_BOB", "1")
    monkeypatch.setattr(runner, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(runner, "initialize_canonical_ledger", lambda *_: Observer())
    monkeypatch.setattr(runner, "initialize_canonical_artifact_index", lambda *_: Observer())
    monkeypatch.setattr(runner, "write_master_log_safe", lambda *_a, **_k: {})
    monkeypatch.setattr(runner, "gemini_ledger_summary", lambda: {})
    monkeypatch.setattr(runner, "record_andrea_avoids_from_result", lambda *_: None)
    monkeypatch.setattr(bob, "report_was_published_or_attempted", lambda: False)
    monkeypatch.setattr(bob, "MAX_ARTICLES_WITH_REPORT", 4)
    for name in ("SOFTPOOL_FILE", "HARD_SKIP_FILE", "MENZO_DECISIONS_FILE",
                 "ARTIFACT_DECISIONS_FILE", "V92_ALLOWED_URLS_FILE"):
        monkeypatch.setattr(menzo, name, tmp_path / (name + ".json"))

    def run(*, editorial_class="SHOULD_PUBLISH", action="SELECT", published=False,
            related=True, ready=True, fail=None, slots=30, fallback=False,
            stale_report_status=False):
        calls = []
        captured = []
        decisions = []
        monkeypatch.setattr(bob, "report_was_published_or_attempted", lambda: stale_report_status)
        report = {"report_id": "aew_dynamite", "report_key": KEY}
        metadata = {"show_report_id": "aew_dynamite", "event_report_key": KEY,
                    "corresponding_report_published": published} if related else {}
        source = {"candidate_id": "candidate-1", "title": "Show result",
                  "url": "https://example.test/news", "summary": "Confirmed fact"}
        snapshot = {"candidates": [source], "remaining_slots": slots,
                    "_active_bob_capacity_metadata": {"candidate-1": metadata}}

        def capture(*_args, **kwargs):
            calls.append("capture")
            captured.append(kwargs)
            return copy.deepcopy(snapshot), None, (True, "ready")

        def evaluate(*_args, **_kwargs):
            calls.append("evaluate")
            if fallback:
                return {"status": "failed", "fallback_reason": "test_provider_failure"}
            return {"status": "VALIDATED", "output": {"candidates": [{
                "candidate_id": "candidate-1", "editorial_class": editorial_class,
                "recommended_action": action, "category": "AEW", "story_core": "Confirmed result",
            }], "relations": []}}

        def step(name, result):
            def call(*args, **kwargs):
                calls.append(name)
                if fail == name:
                    raise RuntimeError("test stage failure")
                if name == "andrea":
                    decisions.append(copy.deepcopy(args[0]))
                    return args[0]
                if name == "bob":
                    assert REPORT_PUBLICATION_PLANNED.get() is ready
                    assert bob.dynamic_article_capacity({}, [])[0] == (4 if ready else bob.MAX_ARTICLES_PER_RUN)
                return copy.deepcopy(result)
            return lambda: call

        monkeypatch.setattr(runner, "capture_editorial_director_opportunity", capture)
        monkeypatch.setattr(active, "evaluate", evaluate)
        monkeypatch.setattr(runner, "import_massy", step("massy", {"handoff": {}}))
        monkeypatch.setattr(runner, "import_simone", step("simone", {
            "ready_reports": [report] if ready else [], "handoff": {}}))
        monkeypatch.setattr(runner, "import_simone_report_publisher", step("report", {
            "results": [{"report_key": KEY, "status": "published"}] if ready else [],
            "handoff": {"published": int(ready)}}))
        legacy = {"selected": [{**source, **metadata}], "pending": [], "skipped": [], "handoff": {}}
        monkeypatch.setattr(runner, "import_menzo", step("legacy", legacy))
        monkeypatch.setattr(runner, "import_andrea", step("andrea", {}))
        monkeypatch.setattr(runner, "import_bob", step("bob", {"articles": [], "handoff": {}}))
        monkeypatch.setattr(runner, "import_alfred", step("alfred", {"reviews": [], "handoff": {}}))
        monkeypatch.setattr(runner, "import_publisher", step("news", {"results": [], "handoff": {}}))
        monkeypatch.setattr(runner, "import_archivista", step("audit", {"summary": {}, "handoff": {}}))
        assert runner.main() == 0
        assert not REPORT_PUBLICATION_PLANNED.get()
        summary = json.loads((tmp_path / "artifacts/run_summary.json").read_text())
        return calls, captured, decisions, summary

    return run


def test_same_run_should_select_precedes_ready_report(run_cycle):
    calls, captured, decisions, summary = run_cycle(editorial_class="SHOULD_PUBLISH", action="SELECT")
    assert calls.index("evaluate") < calls.index("news") < calls.index("report")
    assert calls.count("evaluate") == calls.count("report") == calls.count("news") == 1
    selected = decisions[0]["selected"][0]
    assert selected["editorial_director"]["recommended_action"] == "SELECT"
    assert selected["editorial_director"]["editorial_class"] == "SHOULD_PUBLISH"
    assert captured[0]["ready_weekly_report_keys"] == {"aew_dynamite": KEY}
    assert summary["news_report_sequence"] == "selected_show_news_first"


def test_same_run_soft_is_held_and_does_not_delay_ready_report(run_cycle):
    calls, _, decisions, summary = run_cycle(editorial_class="PUBLISHABLE_SOFT", action="DEFER")
    assert decisions[0]["selected"] == []
    assert calls.index("report") < calls.index("news")
    assert summary["news_report_sequence"] == "report_before_news_generation"


@pytest.mark.parametrize("fail", ["andrea", "bob", "alfred", "news"])
def test_news_stage_failure_does_not_cancel_or_retry_report(run_cycle, fail):
    calls, _, _, _ = run_cycle(fail=fail)
    assert calls.index("news") < calls.index("report")
    assert calls.count("report") == 1


@pytest.mark.parametrize("options", [
    {"published": True}, {"related": False},
])
def test_selected_strong_news_not_tied_to_ready_report_leaves_report_first(run_cycle, options):
    calls, _, decisions, summary = run_cycle(**options)
    assert len(decisions[0]["selected"]) == 1
    assert calls.index("report") < calls.index("bob")
    assert summary["news_report_sequence"] == "report_before_news_generation"


def test_skip_leaves_report_before_generation(run_cycle):
    calls, _, decisions, summary = run_cycle(editorial_class="SKIP", action="SKIP")
    assert decisions[0]["selected"] == []
    assert calls.index("report") < calls.index("bob")
    assert summary["news_report_sequence"] == "report_before_news_generation"


def test_strong_news_is_not_suppressed_by_zero_daily_slots(run_cycle):
    calls, _, decisions, summary = run_cycle(slots=0)
    assert len(decisions[0]["selected"]) == 1
    assert calls.index("news") < calls.index("report")
    assert summary["news_report_sequence"] == "selected_show_news_first"


def test_normally_selected_post_report_story_remains_selected(run_cycle):
    calls, _, decisions, _ = run_cycle(published=True, action="SELECT")
    assert len(decisions[0]["selected"]) == 1
    assert "scheduling_override" not in decisions[0]["selected"][0]
    assert calls.index("report") < calls.index("bob")


def test_active_failure_is_fail_closed_and_report_still_runs_once(run_cycle):
    calls, _, decisions, summary = run_cycle(fallback=True)
    assert "legacy" not in calls
    assert calls.index("report") < calls.index("news")
    assert calls.count("report") == 1
    assert decisions[0]["selected"] == []
    assert summary["news_report_sequence"] == "report_before_news_generation"


@pytest.mark.parametrize("stale_report_status", [False, True])
def test_no_ready_report_does_not_reserve_report_capacity(run_cycle, stale_report_status):
    calls, _, _, _ = run_cycle(ready=False, stale_report_status=stale_report_status)
    assert calls.index("report") < calls.index("bob")


@pytest.mark.parametrize("key", ["aew_dynamite_2026_09_23", "special_event_night_2_2026_09_30"])
def test_different_occurrence_does_not_delay_ready_report(key):
    assert not runner.selected_news_precede_report(
        {"selected": [{"show_report_id": "aew_dynamite", "event_report_key": key}]},
        {"ready_reports": [{"report_id": "aew_dynamite", "report_key": KEY}]})


def test_special_event_matching_uses_exact_report_key():
    key = "special_event_night_1_2026_09_30"
    assert runner.selected_news_precede_report(
        {"selected": [{"special_event_match": {"report_key": key}}]},
        {"ready_reports": [{"report_key": key}]})


def test_planned_capacity_is_reset_even_when_runner_exits_unexpectedly(monkeypatch):
    def fail():
        REPORT_PUBLICATION_PLANNED.set(True)
        raise RuntimeError("unexpected runner exit")
    monkeypatch.setattr(runner, "_run_newsroom", fail)
    with pytest.raises(RuntimeError):
        runner.main()
    assert not REPORT_PUBLICATION_PLANNED.get()


@pytest.mark.parametrize("published_key,published", [(KEY, True), ("aew_dynamite_2026_09_23", False)])
@pytest.mark.parametrize("report_ready", [True, False, "older_replay"])
def test_capture_reads_publication_for_weekly_occurrence(monkeypatch, tmp_path, published_key, published, report_ready):
    from agents import menzo_editorial_director_shadow as shadow
    from agents import simone_publisher_v93_18 as publisher
    from modules import simone_report_integrity as integrity

    pending = tmp_path / "pending.json"
    history = tmp_path / "history.json"
    pending.write_text(json.dumps({"reports": []}))
    history.write_text(json.dumps({published_key: {"wp_post_id": 12}}))
    monkeypatch.setattr(integrity, "PENDING_REPORTS", pending)
    monkeypatch.setattr(publisher, "SIMONE_REPORT_HISTORY_FILE", history)
    monkeypatch.setattr(shadow, "costly_work_eligibility", lambda: (True, "ready"))
    monkeypatch.setattr(shadow, "softpool_augmented_board", copy.deepcopy)
    monkeypatch.setattr(menzo, "published_today_count", lambda: 0)
    monkeypatch.setattr(menzo, "load_authoritative_publisher_history", lambda *_: [])
    observed = []
    monkeypatch.setattr(shadow, "capture_opportunity", lambda board, **_k: observed.append(board) or {})
    runner.capture_editorial_director_opportunity(
        {"news_candidates_for_menzo": [{"show_report_id": "aew_dynamite"}], "published_due_reports": {}},
        run_id="capture-test", observation_timestamp="2026-10-01T04:30:00+00:00",
        ready_weekly_report_keys=({"aew_dynamite": "aew_dynamite_2026_09_23"}
                                  if report_ready == "older_replay" else
                                  {"aew_dynamite": KEY} if report_ready else None))
    row = observed[0]["news_candidates_for_menzo"][0]
    assert row["event_report_key"] == KEY
    assert row["corresponding_report_published"] is published


@pytest.mark.parametrize("manual", [None, {}, {"report_key": KEY}])
def test_future_explicit_occurrence_is_not_covered_by_current_weekly_report(monkeypatch, tmp_path, manual):
    from agents import menzo_editorial_director_shadow as shadow
    from agents import simone_publisher_v93_18 as publisher
    from modules import simone_report_integrity as integrity

    pending = tmp_path / "pending.json"
    history = tmp_path / "history.json"
    pending.write_text(json.dumps({"reports": []}))
    history.write_text(json.dumps({KEY: {"wp_post_id": 12}}))
    monkeypatch.setattr(integrity, "PENDING_REPORTS", pending)
    monkeypatch.setattr(publisher, "SIMONE_REPORT_HISTORY_FILE", history)
    monkeypatch.setattr(shadow, "costly_work_eligibility", lambda: (True, "ready"))
    monkeypatch.setattr(shadow, "softpool_augmented_board", copy.deepcopy)
    monkeypatch.setattr(menzo, "published_today_count", lambda: 0)
    monkeypatch.setattr(menzo, "load_authoritative_publisher_history", lambda *_: [])
    observed = []
    monkeypatch.setattr(shadow, "capture_opportunity", lambda board, **_k: observed.append(board) or {})
    future_key = "aew_dynamite_2026_10_07"
    runner.capture_editorial_director_opportunity(
        {"news_candidates_for_menzo": [{"show_report_id": "aew_dynamite", "event_report_key": future_key}],
         "published_due_reports": {} if manual is None else {"aew_dynamite": manual}},
        run_id="future-test", observation_timestamp="2026-10-01T04:30:00+00:00")
    row = observed[0]["news_candidates_for_menzo"][0]
    assert row["event_report_key"] == future_key
    assert row["corresponding_report_published"] is False


@pytest.mark.parametrize("planned", [True, False])
def test_runtime_capacity_patch_preserves_consolidated_planned_capacity(tmp_path, monkeypatch, planned):
    root = Path(runner.__file__).resolve().parent
    (tmp_path / "agents").mkdir()
    for name in ("bob.py", "menzo_policy_v93_15.py"):
        shutil.copyfile(root / "agents" / name, tmp_path / "agents" / name)
    original = (tmp_path / "agents/bob.py").read_bytes()
    patch = root / "scripts/apply_v93_capacity_patch.py"
    for _ in range(2):
        subprocess.run([sys.executable, str(patch)], cwd=tmp_path, check=True, capture_output=True)
        assert (tmp_path / "agents/bob.py").read_bytes() == original
    spec = importlib.util.spec_from_file_location("ps1_patched_bob", tmp_path / "agents/bob.py")
    patched_bob = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patched_bob)
    monkeypatch.setattr(patched_bob, "report_was_published_or_attempted", lambda: not planned)
    token = REPORT_PUBLICATION_PLANNED.set(planned)
    try:
        expected = patched_bob.MAX_ARTICLES_WITH_REPORT if planned else patched_bob.MAX_ARTICLES_PER_RUN
        assert patched_bob.dynamic_article_capacity({}, [])[0] == expected
    finally:
        REPORT_PUBLICATION_PLANNED.reset(token)
