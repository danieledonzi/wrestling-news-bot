from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest

from agents.canonical_event_ledger import content_id
from scripts import current_editorial_report as report
from scripts import daily_report_email as mail
from scripts import observability_snapshot as observation
from scripts.install_noon_report_runner import install

UNTIL = datetime(2026, 10, 11, 10, tzinfo=timezone.utc)
SINCE = UNTIL - timedelta(hours=24)
RELEASE = {"head": "installed-sha", "last_pr": 156, "merged_at": "2026-10-11T13:41:57Z"}


def article(name="a", cl="PUBLISHABLE_SOFT", **extra):
    return {"url": f"https://source.test/{name}", "title": name, "editorial_class": cl, **extra}


def first(row, at=SINCE + timedelta(minutes=1)):
    return {**row, "classified_at": at.isoformat(), "story_core": "Il fatto descritto dalla fonte"}


def run(at, *, candidates=(), pending=(), skipped=(), published=(), version="v9", scheduling=None, relations=()):
    return {"run": {"started_at": at.isoformat(), "ended_at": (at + timedelta(seconds=10)).isoformat()},
        "editorial_pipeline": {"prefilter": {"policy_version": version, "candidates": list(candidates), "relations": list(relations)},
            "scheduling": scheduling or {}},
        "menzo": {"selected": [], "pending": list(pending), "skipped_sample": list(skipped)},
        "publisher": {"published": list(published)}}


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def sources(tmp_path, monkeypatch, runs, frozen, *, skips=(), soft=(), priority=(), published=()):
    write(tmp_path / "state/newsroom/menzo_primary_classifications_v1.json", {"entries": {report.url_key(a): first(a) for a in frozen}})
    write(tmp_path / "state/newsroom/menzo_hard_skips.json", {"items": list(skips)})
    for name, items in (("menzo_softpool", soft), ("menzo_priority_queue", priority)):
        write(tmp_path / f"state/newsroom/{name}.json", {"items": list(items), "updated_at": UNTIL.isoformat()})
    (tmp_path / "state/newsroom/gemini_call_ledger.jsonl").write_text("")
    monkeypatch.setattr(observation, "load_master_runs", lambda *a, **k: (runs, ["master_log"], [], True, {"master_log_malformed_lines": 0}))
    return {"authoritative": {"publication": {"metadata": {"complete_window": True},
        "news": {"content_ids": [content_id(a) for a in published]},
        "unique_news_publications": len(published), "unique_report_publications": 2},
        "runs": {"completed_unique_run_count": len(runs) - 1}}}


def build(root, snapshot):
    return report.build_report(root, until=UNTIL, snapshot=snapshot, release=RELEASE, quality_report={})


def test_softpool_activity_is_not_erased_by_empty_closing_snapshot(tmp_path, monkeypatch):
    a = article()
    rows = [run(SINCE - timedelta(minutes=1)),
        run(SINCE + timedelta(hours=1), candidates=[a], pending=[a], scheduling={"soft_board_status": "REVIEWED", "soft_board_admitted_items": [a], "soft_board_pool_size": 1}),
        run(UNTIL - timedelta(minutes=10), published=[a], scheduling={"soft_board_status": "EMPTY", "soft_board_pool_size": 0})]
    snapshot = sources(tmp_path, monkeypatch, rows, [a], published=[a])
    data = build(tmp_path, snapshot)
    soft = data["lifecycle"]["softpool"]
    assert soft["admitted_unique"] == soft["published_unique_observed"] == 1
    assert soft["closing_last_observed"] == []
    assert data["publications"]["news_by_first_class"] == {"PUBLISHABLE_SOFT": 1}
    assert data["publications"]["reports_unique_separate"] == 2
    assert data["daily_note"]["text"] == report.NO_ACTION


def test_unique_cohort_and_repeated_observations_are_distinct(tmp_path, monkeypatch):
    a = article("a", "SHOULD_PUBLISH")
    rows = [run(SINCE - timedelta(minutes=1))] + [run(SINCE + timedelta(hours=i), candidates=[a], pending=[a]) for i in (1, 2, 3)]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [a]))
    assert data["lifecycle"]["cohorts"]["SHOULD_PUBLISH"]["new_unique_urls"] == 1
    assert data["lifecycle"]["immutability"]["primary_observations"] == 3
    assert data["lifecycle"]["immutability"]["urls_observed_multiple_runs"] == 1


def test_historical_reclassification_does_not_propose_fix_to_current_version(tmp_path, monkeypatch):
    a = article()
    changed = {**a, "editorial_class": "SHOULD_PUBLISH"}
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1), candidates=[changed], version="v6"), run(UNTIL - timedelta(minutes=5), candidates=[a])]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [a]))
    assert data["patterns"][0]["status"] == "historical_or_unavailable"
    assert data["daily_note"]["text"] == report.NO_ACTION
    assert data["daily_note"]["proposals"] == []


def test_current_invariant_failure_has_specific_review_proposal(tmp_path, monkeypatch):
    a = article()
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1), candidates=[{**a, "editorial_class": "SHOULD_PUBLISH"}])]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [a]))
    assert data["daily_note"]["approval_required"] is True
    assert data["daily_note"]["proposals"][0]["id"] == "primary_class_changed"
    assert "prima classe persistita" in data["daily_note"]["proposals"][0]["proposed_rule"]


def test_terminal_skip_is_checked_for_reintroduction_and_comparisons(tmp_path, monkeypatch):
    a = article("a", "SKIP", candidate_id="c0")
    b = article("b", candidate_id="c1")
    tomb = {**a, "terminal": True, "added_at": (SINCE + timedelta(minutes=5)).isoformat()}
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1), candidates=[a, b], relations=[{"pair_id": "p1", "left_id": "c0", "right_id": "c1", "decision": "NO_MATCH"}])]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [a, b], skips=[tomb]))
    assert len(data["lifecycle"]["terminal_skip"]["resurrections"]) == 1
    assert len(data["lifecycle"]["terminal_skip"]["skipped_pair_endpoints"]) == 1
    assert data["lifecycle"]["cohorts"]["SKIP"]["outcomes"] == {"terminal_skip": 1}


def test_production_relation_urls_include_closed_history_endpoint(tmp_path, monkeypatch):
    a = article("a")
    old = article("old", "SKIP", terminal=True, added_at=(SINCE - timedelta(hours=1)).isoformat())
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1), candidates=[a], relations=[
        {"pair_id": "history-pair", "scope": "recent_history", "left_url": a["url"], "right_url": old["url"], "admission_basis": "same factual development"}])]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [a], skips=[old]))
    assert data["lifecycle"]["terminal_skip"]["skipped_pair_endpoints"][0]["url"] == old["url"]
    assert data["lifecycle"]["duplicates"]["decisions_observed"] is None
    assert data["lifecycle"]["duplicates"]["unique_admitted_pairs_observed"] == 1


def test_queue_does_not_claim_already_published_item_is_waiting(tmp_path, monkeypatch):
    a = article("a", "SHOULD_PUBLISH")
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1), published=[a])]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [a], priority=[a], published=[a]))
    queue = data["current_snapshots"]["menzo_priority_queue"]
    assert queue["raw_items_count"] == queue["excluded_already_published_observed"] == 1
    assert queue["effective_pending_observed"] == 0
    assert data["daily_note"]["text"] == report.NO_ACTION


@pytest.mark.parametrize("bad", [{}, {"entries": []}, {"entries": {"bad": {"url": "https://source/a", "editorial_class": "BOGUS"}}}])
def test_invalid_primary_store_is_unavailable_not_zero(tmp_path, monkeypatch, bad):
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1))]
    snapshot = sources(tmp_path, monkeypatch, rows, [])
    write(tmp_path / "state/newsroom/menzo_primary_classifications_v1.json", bad)
    data = build(tmp_path, snapshot)
    assert data["lifecycle"]["cohorts"]["MUST_PUBLISH"]["new_unique_urls"] is None
    assert data["lifecycle"]["immutability"]["verdict"] == "unavailable"
    assert "nuovi URL n.d." in report.render_summary(data)


def test_missing_or_truncated_windows_cannot_certify_zeros(tmp_path, monkeypatch):
    rows = [run(SINCE + timedelta(hours=1))]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, []))
    assert data["lifecycle"]["available"] is False
    assert data["weekly"]["available"] is False
    assert data["daily_note"]["text"] == report.NO_ACTION


@pytest.mark.parametrize("start", [None, "absent"])
def test_accepted_fallback_run_timestamps_do_not_break_report(tmp_path, monkeypatch, start):
    a = article()
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1), candidates=[a]),
        run(UNTIL - timedelta(minutes=10), published=[a])]
    for row in rows:
        if start == "absent": row["run"].pop("started_at")
        else: row["run"]["started_at"] = None
    rows[-1]["recorded_at"] = (UNTIL - timedelta(minutes=5)).isoformat()
    rows.append({"run": {}, "recorded_at": "invalid"})
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [a], published=[a]))
    assert data["lifecycle"]["runs_observed"] == 2
    assert data["lifecycle"]["cohorts"]["PUBLISHABLE_SOFT"]["outcomes"] == {"published": 1}
    assert data["lifecycle"]["terminal_skip"]["run_chronology_unavailable"] == 2
    assert data["publications"]["news_unique"] == 1


def test_fallback_end_timestamp_does_not_invent_same_run_skip_violation(tmp_path, monkeypatch):
    a = article("a", "SKIP")
    row = run(SINCE + timedelta(hours=1), candidates=[a], skipped=[a])
    tomb = {**a, "terminal": True, "added_at": (SINCE + timedelta(hours=1, seconds=5)).isoformat()}
    row["run"]["started_at"] = None
    rows = [run(SINCE - timedelta(minutes=1)), row]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [a], skips=[tomb]))
    assert data["lifecycle"]["terminal_skip"]["resurrections"] == []
    assert data["lifecycle"]["terminal_skip"]["run_chronology_unavailable"] == 1
    assert data["daily_note"]["text"] == report.NO_ACTION


def test_unknown_publication_class_is_not_estimated_from_volume(tmp_path, monkeypatch):
    a = article()
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1), published=[a])]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, [], published=[a]))
    assert data["publications"]["news_by_first_class"] is None
    assert data["coverage"]["publication_class_enrichment"] == "partial_or_unavailable"
    summary = report.render_summary(data)
    assert "OTTIMO" not in summary and "hard" not in summary
    assert data["daily_note"]["text"] == report.NO_ACTION


def test_corrupt_cost_ledger_returns_unknown_not_free(tmp_path):
    path = tmp_path / "state/newsroom/gemini_call_ledger.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{broken\n")
    economics = report.economic_sections(tmp_path, SINCE, UNTIL)
    assert economics["overall"]["real_attempts"] is None
    assert economics["workloads"]["pair_admission"]["complete_window_computed_list_price_cost"] is None


def test_costs_keep_admission_and_final_judgment_separate(tmp_path):
    from agents.gemini_ledger import calculate_v96_2_cost
    from decimal import Decimal
    pricing = calculate_v96_2_cost({"usage_available": True, "input_tokens": 100, "cached_input_tokens": 0,
        "output_tokens": 10, "thinking_tokens": 0, "total_tokens": 110, "total_tokens_provider_reported": True}, "gemini-2.5-flash")
    phases = ["editorial_director_active", "editorial_duplicate_admission", "editorial_soft_duplicate_admission", "editorial_director_duplicate_gate", "editorial_soft_board"]
    rows = [{"timestamp": UNTIL.isoformat(), "workload": phase, "status": "called", "ledger_schema_version": "v3",
        "provider_attempt_id": str(i), "actual_model": "gemini-2.5-flash", **pricing} for i, phase in enumerate(phases)]
    path = tmp_path / "state/newsroom/gemini_call_ledger.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('\n'.join(json.dumps(r) for r in rows))
    economics = report.economic_sections(tmp_path, SINCE, UNTIL)
    assert economics["workloads"]["pair_admission"]["real_attempts"] == 2
    assert economics["workloads"]["duplicate_verdict"]["real_attempts"] == 1
    assert Decimal(economics["overall"]["complete_window_computed_list_price_cost"]) == sum(Decimal(v["complete_window_computed_list_price_cost"]) for v in economics["workloads"].values())


def test_daily_note_append_preserves_prior_release_and_deduplicates(tmp_path, monkeypatch):
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1))]
    data = build(tmp_path, sources(tmp_path, monkeypatch, rows, []))
    original = copy.deepcopy(data)
    assert len(report.note_history(tmp_path, data, persist=True)) == 1
    assert len(report.note_history(tmp_path, data, persist=True)) == 1
    data["daily_note"]["local_day"] = "2026-10-12"
    data["release"] = {**RELEASE, "last_pr": 157}
    history = report.note_history(tmp_path, data, persist=True)
    assert len(history) == 2
    assert history[0]["release"] == original["release"]
    assert history[0]["text"] == report.NO_ACTION
    assert history[1]["release"]["last_pr"] == 157


def test_corrupt_note_journal_is_not_overwritten(tmp_path):
    path = tmp_path / "state/reports/editorial_observation_notes.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("broken")
    with pytest.raises(ValueError):
        report.note_history(tmp_path, {}, persist=True)
    assert path.read_text() == "broken"


def test_semantic_translation_hints_do_not_trigger_change_proposal(tmp_path, monkeypatch):
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1))]
    snapshot = sources(tmp_path, monkeypatch, rows, [])
    quality = {"generated_at": UNTIL.isoformat(), "status_counts": {"reproduced": 5}, "investigations": [{"semantic_verdict": "not_assessed"}]}
    data = report.build_report(tmp_path, until=UNTIL, snapshot=snapshot, release=RELEASE, quality_report=quality)
    assert data["translation_signals"]["available"] is True
    assert data["translation_signals"]["semantic_errors_confirmed"] is None
    assert data["daily_note"]["text"] == report.NO_ACTION


def test_preview_never_reads_credentials_or_connects_smtp(tmp_path, monkeypatch):
    attachment = tmp_path / "current.json"
    attachment.write_text("{}")
    def forbidden(*a, **kw):
        raise AssertionError("Mail credentials or SMTP accessed in preview")
    monkeypatch.setattr(mail, "load_config", forbidden)
    monkeypatch.setattr(mail, "send_message", forbidden)
    assert mail.main(["--preview"], root=tmp_path, bundle=lambda *args: (report.NO_ACTION, [attachment])) == 0
    message = BytesParser(policy=policy.default).parsebytes(next((tmp_path / "reports").glob("*.eml")).read_bytes())
    assert [a.get_filename() for a in message.iter_attachments()] == ["current.json"]
    assert report.NO_ACTION in message.get_body(preferencelist=("plain",)).get_content()


def test_failed_current_diagnostics_never_attach_old_latest(tmp_path, monkeypatch):
    from scripts import translation_quality_audit, build_weekly_pattern_report
    stale = tmp_path / "state/reports/owtv_translation_warning_analysis_latest.json"
    write(stale, {"generated_at": UNTIL.isoformat(), "status_counts": {"reproduced": 99}})
    def unavailable(*args, **kwargs):
        raise OSError("material unavailable")
    monkeypatch.setattr(translation_quality_audit, "build_audit", unavailable)
    monkeypatch.setattr(build_weekly_pattern_report, "generate_outputs", unavailable)
    received = []
    def current(*args, **kwargs):
        received.append(kwargs["quality_report"])
        raise ValueError("report unavailable")
    monkeypatch.setattr(mail, "generate_outputs", current)
    body, attachments = mail.diagnostic_bundle(tmp_path, tmp_path / "reports", UNTIL)
    assert attachments == []
    assert received == [{}]
    assert "NON DISPONIBILE" in body
    assert "Nessuna azione proposta" in body
    assert stale.exists()


def test_runner_backup_and_install_are_idempotent(tmp_path):
    launcher = tmp_path / "send_daily_report.py"
    launcher.write_text("# old runner\n")
    backup = install(tmp_path, launcher)
    assert backup.read_text() == "# old runner\n"
    assert "scripts.daily_report_email" in launcher.read_text()
    assert install(tmp_path, launcher) is None
    assert len(list(tmp_path.glob("send_daily_report.py.backup_*"))) == 1


def test_generated_report_writes_only_report_artifacts(tmp_path, monkeypatch):
    rows = [run(SINCE - timedelta(minutes=1)), run(SINCE + timedelta(hours=1))]
    snapshot = sources(tmp_path, monkeypatch, rows, [])
    monkeypatch.setattr(observation, "build_snapshot", lambda *a, **k: snapshot)
    before = {p: p.read_bytes() for p in (tmp_path / "state/newsroom").glob("*")}
    outputs = report.generate_outputs(tmp_path, until=UNTIL, quality_report={})
    assert all(p.read_bytes() == data for p, data in before.items())
    assert outputs["markdown"].exists() and outputs["json"].exists()
    assert report.NO_ACTION in outputs["markdown"].read_text()


def test_real_bundle_generates_eight_current_artifacts_without_legacy_reports(tmp_path):
    body, attachments = mail.diagnostic_bundle(tmp_path, tmp_path / "reports", UNTIL)
    assert len(attachments) == 8
    assert all(p.is_file() for p in attachments)
    assert not any("operational_report" in p.name or "story_cluster" in p.name or "editorial_audit_v1_1" in p.name for p in attachments)
    assert "nuovi URL n.d." in body
    assert report.NO_ACTION in body


@pytest.mark.parametrize("port,tls", [(465, False), (587, True)])
def test_existing_smtp_transport_is_preserved_without_network(monkeypatch, port, tls):
    calls = []
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self, **kwargs): calls.append("tls")
        def login(self, user, password): calls.append("login")
        def send_message(self, message): calls.append("send")
    def connect(*args, **kwargs):
        calls.append("connect")
        return Client()
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", connect)
    monkeypatch.setattr(mail.smtplib, "SMTP", connect)
    config = {"SMTP_HOST": "smtp.example.invalid", "SMTP_PORT": str(port), "SMTP_USER": "fixture@example.invalid", "SMTP_PASSWORD": "test-fixture", "MAIL_TO": "owner@example.invalid"}
    message = mail.build_message(report.NO_ACTION, [], UNTIL, config)
    mail.send_message(message, config)
    assert calls == (["connect", "tls", "login", "send"] if tls else ["connect", "login", "send"])
