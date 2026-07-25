import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.observability_snapshot import build_snapshot, repository_diagnostics

NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)


def write_runtime(root: Path, rows, ledger=()):
    path = root / "state/newsroom"
    path.mkdir(parents=True)
    (path / "master_log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in rows))
    (path / "gemini_call_ledger.jsonl").write_text("".join(json.dumps(x) + "\n" for x in ledger))


def run(**parts):
    return {"schema_version": "v93_19", "recorded_at": NOW.isoformat(), "run": {"ended_at": NOW.isoformat(), "runtime_exit_code": 0}, **parts}


def test_linked_menzo_ratio_uses_unique_identities(tmp_path):
    selected = [{"source_url": "https://x/a"}, {"source_url": "https://x/a"}, {"source_url": "https://x/b"}]
    published = [{"source_url": "https://x/a", "status": "published"}]
    write_runtime(tmp_path, [run(menzo={"selected": selected}, publisher={"results": published})])
    metric = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["funnel"]["canonical"]
    assert metric["unique_downstream_handoffs"] == 2
    assert metric["linked_handoff_publication_overlap"] == 1
    assert metric["handoff_to_publication_ratio"] == .5


def test_menzo_ratio_is_null_when_linkage_unavailable(tmp_path):
    write_runtime(tmp_path, [run(menzo={"selected": [{"source_url": "https://x/a"}]}, publisher={})])
    assert build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["funnel"]["canonical"]["handoff_to_publication_ratio"] is None


def test_alfred_warning_dimensions_are_distinct(tmp_path):
    reviews = [{"source_url": "https://x/a", "warnings": ["a", "b"]}, {"source_url": "https://x/a", "warnings": ["c"]}, {"source_url": "https://x/b", "warnings": ["d", "e"]}]
    write_runtime(tmp_path, [run(alfred={"reviews": reviews})])
    alfred = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["alfred"]
    assert alfred["unique"]["articles_with_warnings"] == 2
    assert alfred["events"]["warning_events"] == 3
    assert alfred["events"]["warning_occurrences"] == 5


def test_gemini_35_statuses_and_future_exclusion(tmp_path):
    ledger = [{"timestamp": NOW.isoformat(), "model": "gemini-3.5-flash", "status": s} for s in ("called", "failed", "avoided")]
    ledger.append({"timestamp": (NOW + timedelta(seconds=1)).isoformat(), "model": "gemini-3.5-flash", "status": "called"})
    write_runtime(tmp_path, [], ledger)
    gemini = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["gemini"]
    assert [gemini[k] for k in ("gemini_3_5_attempts", "gemini_3_5_completed_calls", "gemini_3_5_failures", "gemini_3_5_avoided_calls")] == [2, 1, 1, 1]


def test_simone_legacy_errors_are_not_terminal(tmp_path):
    write_runtime(tmp_path, [run(simone={"publish_handoff": {"errors": 4}, "published_reports": []})])
    simone = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["simone"]
    assert simone["legacy_errors_diagnostic"] == 4
    assert simone["terminal_errors"] is None
    assert simone["terminal_errors_available"] is False


def test_expected_runtime_dirt_does_not_hide_source_change(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "source.py").write_text("old")
    subprocess.run(["git", "add", "source.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "source.py").write_text("new")
    (tmp_path / ".bot_exit_code").write_text("0")
    (tmp_path / "logs").mkdir(); (tmp_path / "logs/master_log.log").write_text("runtime")
    diag = repository_diagnostics(tmp_path)
    assert {".bot_exit_code", "logs/master_log.log"} <= set(diag["expected_runtime_untracked_paths"])
    assert any("source.py" in line for line in diag["actual_source_modifications"])


def test_daily_judgment_renders_canonical_labels_and_old_data(monkeypatch):
    import scripts.daily_editorial_judgment as dej
    report = dej.build_report({"menzo_latest": {"selected": [], "pending": [], "skipped": []}})
    report["canonical_menzo"] = {"handoff_to_publication_ratio": None}
    report["canonical_alfred"] = {"articles_reviewed": 2, "articles_with_warnings": 2, "warning_events": 3, "warning_occurrences": 5, "final_blockers": 1}
    report["canonical_gemini"] = {"gemini_3_5_attempts": 2, "gemini_3_5_completed_calls": 1, "gemini_3_5_failures": 1, "gemini_3_5_avoided_calls": 1}
    report["canonical_simone"] = {"legacy_errors_diagnostic": 4}
    text = dej.render_markdown(report)
    assert "Menzo handoff-to-publication ratio: unavailable" in text
    assert "Alfred articles reviewed/articles with warnings/warning events/warning occurrences" in text
    assert "Gemini 3.5 attempts/completed/failed/avoided: 2/1/1/1" in text
    assert "Simone legacy errors (diagnostic; not terminal): 4" in text


def test_nonempty_populations_without_real_aliases_are_unlinkable(tmp_path):
    write_runtime(tmp_path, [run(menzo={"selected": [{}]}, publisher={"results": [{"status": "published"}]})])
    funnel = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["funnel"]
    assert funnel["canonical"]["linked_handoff_publication_overlap"] is None
    assert funnel["canonical"]["handoff_to_publication_ratio"] is None
    assert "selected_publication_linkage_not_supported_by_available_identities" in funnel["schema_warnings"]


def test_simone_already_present_uses_publish_handoff(tmp_path):
    write_runtime(tmp_path, [run(simone={"publish_handoff": {"published": 1, "already_published": 1, "errors": 0}, "published_reports": [{"source_url": "https://x/report", "status": "published"}]})])
    simone = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["simone"]
    assert simone["reports_published"] == 1
    assert simone["already_present_events"] == 1


def test_missing_gemini_ledger_is_unavailable(tmp_path):
    state = tmp_path / "state/newsroom"; state.mkdir(parents=True)
    (state / "master_log.jsonl").write_text("")
    snap = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)
    assert snap["section_metadata"]["gemini"]["available"] is False
    assert snap["gemini"]["gemini_3_5_attempts"] is None


def test_unreadable_gemini_ledger_is_unavailable(tmp_path):
    state = tmp_path / "state/newsroom"; state.mkdir(parents=True)
    (state / "master_log.jsonl").write_text("")
    (state / "gemini_call_ledger.jsonl").mkdir()
    snap = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)
    assert snap["section_metadata"]["gemini"]["available"] is False
    assert snap["gemini"]["completed_calls"] is None


def test_undated_gemini_row_is_diagnostic_not_bounded_zero(tmp_path):
    write_runtime(tmp_path, [], [{"model": "gemini-3.5-flash", "status": "called"}])
    snap = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)
    assert snap["section_metadata"]["gemini"]["available"] is False
    assert snap["gemini"]["gemini_3_5_attempts"] is None
    assert snap["gemini"]["undated_rows_diagnostic"] == 1


def test_partial_gemini_ledger_is_available_with_warning(tmp_path):
    state = tmp_path / "state/newsroom"; state.mkdir(parents=True)
    (state / "master_log.jsonl").write_text("")
    (state / "gemini_call_ledger.jsonl").write_text(json.dumps({"timestamp": NOW.isoformat(), "model": "gemini-3.5-flash", "status": "called"}) + "\n{bad\n")
    snap = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)
    assert snap["section_metadata"]["gemini"]["available"] is True
    assert snap["section_metadata"]["gemini"]["coverage"]["malformed_rows"] == 1
    assert snap["gemini"]["gemini_3_5_completed_calls"] == 1
    assert snap["section_metadata"]["gemini"]["diagnostic_warnings"]


def test_daily_judgment_uses_available_gemini_without_master_authority(monkeypatch):
    import scripts.daily_editorial_judgment as dej
    snapshot = {"authority_available": False, "section_metadata": {"gemini": {"available": True}}, "gemini": {"gemini_3_5_attempts": 2, "gemini_3_5_completed_calls": 1, "gemini_3_5_failures": 1, "gemini_3_5_avoided_calls": 0}}
    monkeypatch.setattr(dej, "build_observability_snapshot", lambda *a, **k: snapshot)
    report = dej.build_report({"__input_provenance__": {"discovery_mode": "default"}, "menzo_latest": {"selected": [], "pending": [], "skipped": []}})
    assert "Gemini 3.5 attempts/completed/failed/avoided: 2/1/1/0" in dej.render_markdown(report)


def test_menzo_incomparable_source_and_wp_namespaces_are_unavailable(tmp_path):
    write_runtime(tmp_path, [run(
        menzo={"selected": [{"source_url": "https://source.example/article"}]},
        publisher={"results": [{"wp_link": "https://news.example/article", "status": "published"}]},
    )])
    funnel = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["funnel"]
    assert funnel["canonical"]["linked_handoff_publication_overlap"] is None
    assert funnel["canonical"]["handoff_to_publication_ratio"] is None
    assert funnel["selected_publication_linkage_unavailability_reason"] == "selected_publication_linkage_no_shared_namespace"


def test_menzo_comparable_source_namespaces_allow_real_zero(tmp_path):
    write_runtime(tmp_path, [run(
        menzo={"selected": [{"source_url": "https://source.example/a"}]},
        publisher={"results": [{"source_url": "https://source.example/b", "status": "published"}]},
    )])
    canonical = build_snapshot(NOW - timedelta(days=1), NOW, tmp_path)["funnel"]["canonical"]
    assert canonical["linked_handoff_publication_overlap"] == 0
    assert canonical["handoff_to_publication_ratio"] == 0.0


def test_daily_judgment_legacy_gemini_is_diagnostic_only():
    import scripts.daily_editorial_judgment as dej
    report = dej.build_report({"menzo_latest": {"selected": [], "pending": [], "skipped": []}})
    report["canonical_gemini"] = {}
    report["gemini_called"] = 7
    text = dej.render_markdown(report)
    assert "Gemini 3.5 attempts/completed/failed/avoided: n.d./n.d./n.d./n.d." in text
    assert "Legacy Gemini 3.5 called total (diagnostic): 7" in text
    assert "attempts/completed/failed/avoided: 7/7" not in text


def test_daily_judgment_gemini_canonical_and_legacy_both_unavailable():
    import scripts.daily_editorial_judgment as dej
    report = dej.build_report({"menzo_latest": {"selected": [], "pending": [], "skipped": []}})
    report["canonical_gemini"] = {}
    report["gemini_called"] = "n.d."
    text = dej.render_markdown(report)
    assert "Gemini 3.5 attempts/completed/failed/avoided: n.d./n.d./n.d./n.d." in text
    assert "Legacy Gemini 3.5 called total" not in text
