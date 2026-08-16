import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

from agents import source_body
from agents.canonical_artifact_index import CanonicalArtifactIndex, artifact_id, validate_manifest_entry
from scripts.validate_canonical_artifact_index import validate_index


def contract(url="https://example.com/story"):
    text = "Complete source sentence. " * 20
    return {"schema": source_body.SCHEMA, "complete": True, "cleaned_full_text": text,
            "sha256": hashlib.sha256(" ".join(text.split()).encode()).hexdigest(), "char_count": len(text),
            "provenance": {"extractor": "bob.extract_elements", "source_url": url, "body_complete": True},
            "coverage": {"extraction_finished": True}}


def make_index(tmp_path, enabled=True):
    return CanonicalArtifactIndex("run-1", tmp_path / "index.jsonl", tmp_path / "material",
                                  enabled=enabled, repository_root=tmp_path)


def rows(tmp_path):
    return [json.loads(line) for line in (tmp_path / "index.jsonl").read_text().splitlines()]


def test_standalone_validator_cli_bootstraps_repository_imports(tmp_path):
    index = make_index(tmp_path)
    index.observe_bob({"articles": [{"source_url": "https://example.com/a",
                                      "status": "ready_for_alfred", "body_html": "x"}]})
    repository = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(repository / "scripts/validate_canonical_artifact_index.py"),
         str(tmp_path / "index.jsonl"), "--root", str(tmp_path)],
        cwd=tmp_path, env=environment, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["valid_rows"] == 1


@pytest.mark.parametrize("non_object", [[], None])
def test_validator_rejects_non_object_and_continues_later_rows(tmp_path, non_object):
    index = make_index(tmp_path)
    index.observe_bob({"articles": [
        {"source_url": "https://example.com/a", "status": "ready_for_alfred", "body_html": "a"},
        {"source_url": "https://example.com/b", "status": "ready_for_alfred", "body_html": "b"},
    ]})
    valid = (tmp_path / "index.jsonl").read_text().splitlines()
    (tmp_path / "index.jsonl").write_text("\n".join((valid[0], json.dumps(non_object), valid[1])) + "\n")
    report, code = validate_index(tmp_path / "index.jsonl", tmp_path)
    assert code == 1
    assert report["rows"] == 3 and report["valid_rows"] == 2 and report["invalid_rows"] == 1


def test_artifact_id_deterministic_and_all_inputs_matter():
    base = artifact_id("r", "c", "generation", "source_material", b"x")
    assert base == artifact_id("r", "c", "generation", "source_material", b"x")
    assert len({base, artifact_id("r2", "c", "generation", "source_material", b"x"),
                artifact_id("r", "c2", "generation", "source_material", b"x"),
                artifact_id("r", "c", "quality", "source_material", b"x"),
                artifact_id("r", "c", "generation", "quality_review", b"x"),
                artifact_id("r", "c", "generation", "source_material", b"y")}) == 6


def test_full_chain_exact_immutable_idempotent_and_valid(tmp_path):
    index = make_index(tmp_path)
    bob = {"articles": [{"source_url": "https://example.com/story", "status": "ready_for_alfred",
                         "canonical_source_body": contract(), "body_html": "<p> Bob exact </p>\n"}]}
    alfred = {"reviews": [{"source_url": "https://example.com/story", "decision": "approved", "quality_score": 9,
                           "issues": [], "approved_article": {"source_url": "https://example.com/story",
                                                               "body_html": "<p>Alfred exact</p>"}}]}
    publisher = {"results": [{"source_url": "https://example.com/story", "status": "published",
                               "published_cleaned_full_text": "Final exact text"}]}
    originals = copy.deepcopy((bob, alfred, publisher))
    index.observe_bob(bob); index.observe_alfred(alfred); index.observe_publisher(publisher)
    assert (bob, alfred, publisher) == originals
    emitted = rows(tmp_path)
    assert len(emitted) == 5 and all(not validate_manifest_entry(row) for row in emitted)
    assert all(row["storage_class"] == "runtime_state" for row in emitted)
    assert {row["content_id"] for row in emitted}.__len__() == 1
    assert {row["correlation_id"] for row in emitted}.__len__() == 1
    assert next((tmp_path / row["path"]).read_bytes() for row in emitted if row["path"].endswith(".html") and "bob-" in row["path"]) == b"<p> Bob exact </p>\n"
    before = (tmp_path / "index.jsonl").read_bytes()
    index.observe_bob(bob)
    assert (tmp_path / "index.jsonl").read_bytes() == before
    report, code = validate_index(tmp_path / "index.jsonl", tmp_path)
    assert code == 0 and report["valid_rows"] == 5
    assert report["material_chain_coverage"]["contents_with_source_bob_alfred_final"] == 1


def test_publisher_final_json_preference_fallback_and_exact_text(tmp_path):
    index = make_index(tmp_path)
    index.observe_publisher({"results": [
        {"source_url": "https://example.com/preferred", "status": "published",
         "published_cleaned_full_text": " Preferred\nexact  ", "cleaned_full_text": "wrong"},
        {"source_url": "https://example.com/fallback", "status": "published",
         "cleaned_full_text": " Fallback\nexact  "},
        {"source_url": "https://example.com/missing", "status": "published"},
        {"source_url": "https://example.com/not-published", "status": "dry_run",
         "published_cleaned_full_text": "must not retain"},
    ]})
    emitted = rows(tmp_path)
    assert len(emitted) == 2
    assert all(row["format"] == "json" and row["path"].endswith(".json") for row in emitted)
    retained = [json.loads((tmp_path / row["path"]).read_bytes()) for row in emitted]
    assert {(item["representation"], item["text"]) for item in retained} == {
        ("published_cleaned_full_text", " Preferred\nexact  "),
        ("cleaned_full_text", " Fallback\nexact  "),
    }


def test_default_material_root_rows_use_runtime_state_storage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OWTV_CANONICAL_ARTIFACT_INDEX_PATH", raising=False)
    monkeypatch.delenv("OWTV_MATERIAL_CHAIN_ROOT", raising=False)
    index = CanonicalArtifactIndex("run-default", repository_root=tmp_path)
    index.observe_bob({"articles": [{"source_url": "https://example.com/default",
                                      "status": "ready_for_alfred", "body_html": "exact"}]})
    emitted = [json.loads(line) for line in
               (tmp_path / "state/newsroom/canonical_artifact_index.jsonl").read_text().splitlines()]
    assert emitted[0]["path"].startswith("state/newsroom/material_chain/")
    assert all(row["storage_class"] == "runtime_state" for row in emitted)


def _observe_chain(index, *, bob=True, alfred=True, final=True):
    url = "https://example.com/repeated"
    if bob:
        index.observe_bob({"articles": [{"source_url": url, "status": "ready_for_alfred",
                                          "canonical_source_body": contract(url), "body_html": "<p>Bob</p>"}]})
    if alfred:
        index.observe_alfred({"reviews": [{"source_url": url, "decision": "approved",
                                            "approved_article": {"source_url": url, "body_html": "<p>Alfred</p>"}}]})
    if final:
        index.observe_publisher({"results": [{"source_url": url, "status": "published",
                                               "published_cleaned_full_text": "Final"}]})


def test_coverage_never_mixes_runs_and_counts_complete_reruns(tmp_path):
    index_path, material = tmp_path / "index.jsonl", tmp_path / "material"
    run_a = CanonicalArtifactIndex("run-a", index_path, material, repository_root=tmp_path)
    _observe_chain(run_a, alfred=False, final=False)
    run_b = CanonicalArtifactIndex("run-b", index_path, material, repository_root=tmp_path)
    _observe_chain(run_b, bob=False)
    split, code = validate_index(index_path, tmp_path)
    assert code == 0
    assert split["material_chain_coverage"]["contents_with_source_bob_alfred_final"] == 0
    assert split["distinct_content_ids"] == 1

    complete_path, complete_material = tmp_path / "complete.jsonl", tmp_path / "complete-material"
    for run_id in ("run-a", "run-b"):
        _observe_chain(CanonicalArtifactIndex(run_id, complete_path, complete_material, repository_root=tmp_path))
    complete, code = validate_index(complete_path, tmp_path)
    assert code == 0
    assert complete["material_chain_coverage"]["contents_with_source_bob_alfred_final"] == 2
    assert complete["distinct_content_ids"] == 1


@pytest.mark.parametrize("failure", ["missing", "sha", "size", "artifact_id", "correlation", "manifest"])
def test_invalid_artifact_never_completes_material_chain(tmp_path, failure):
    index = make_index(tmp_path)
    _observe_chain(index)
    emitted = rows(tmp_path)
    bob_row = next(row for row in emitted if row["producer_agent"] == "Bob" and
                   row["semantic_roles"] == ["translated_candidate"])
    if failure == "missing":
        (tmp_path / bob_row["path"]).unlink()
    elif failure == "sha":
        bob_row["sha256"] = "0" * 64
    elif failure == "size":
        bob_row["size_bytes"] += 1
    elif failure == "artifact_id":
        bob_row["artifact_id"] = "afi_" + "0" * 64
    elif failure == "correlation":
        bob_row["correlation_id"] = "corr_" + "0" * 64
    else:
        bob_row["unexpected"] = True
    if failure != "missing":
        (tmp_path / "index.jsonl").write_text(
            "".join(json.dumps(bob_row if row["artifact_id"] == emitted[1]["artifact_id"] else row) + "\n"
                    for row in emitted)
        )
    report, code = validate_index(tmp_path / "index.jsonl", tmp_path)
    assert code == 1
    assert report["material_chain_coverage"]["contents_with_source_bob_alfred_final"] == 0


def test_alfred_review_and_approved_body_coverage_are_separate(tmp_path):
    index = make_index(tmp_path)
    _observe_chain(index)
    emitted = rows(tmp_path)
    review = lambda row: row["producer_agent"] == "Alfred" and row["semantic_roles"] == ["quality_review"]
    body = lambda row: row["producer_agent"] == "Alfred" and "translated_candidate" in row["semantic_roles"]

    def coverage(name, include):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in emitted if include(row)))
        report, code = validate_index(path, tmp_path)
        assert code == 0
        return report["material_chain_coverage"]

    body_only = coverage("body-only", body)
    assert body_only["contents_with_alfred_approved_body"] == 1
    assert body_only["contents_with_alfred_review"] == 0
    review_only = coverage("review-only", review)
    assert review_only["contents_with_alfred_review"] == 1
    assert review_only["contents_with_alfred_approved_body"] == 0
    both = coverage("both", lambda row: review(row) or body(row))
    assert both["contents_with_alfred_review"] == both["contents_with_alfred_approved_body"] == 1
    without_review = coverage("chain-without-review", lambda row: not review(row))
    assert without_review["contents_with_source_bob_alfred_final"] == 0
    full = coverage("full", lambda row: True)
    assert full["contents_with_source_bob_alfred_final"] == 1


def test_filters_invalid_source_statuses_and_missing_alfred_body(tmp_path):
    index = make_index(tmp_path)
    index.observe_bob({"articles": [{"source_url": "https://example.com/a", "status": status,
                                     "body_html": "x", "canonical_source_body": {}}
                                    for status in ("error", "pending", "extraction_empty")]})
    index.observe_alfred({"reviews": [{"source_url": "https://example.com/a", "decision": "needs_revision"}]})
    index.observe_publisher({"results": [{"source_url": f"https://example.com/{status}", "status": status,
                                          "published_cleaned_full_text": "x"}
                                         for status in ("already_published", "dry_run", "wp_not_ready", "publish_error", "skipped")]})
    emitted = rows(tmp_path)
    assert len(emitted) == 1 and emitted[0]["semantic_roles"] == ["quality_review"]


def test_disabled_and_archive_failure_fail_open(tmp_path):
    disabled = make_index(tmp_path, False)
    disabled.observe_bob({"articles": [{"source_url": "https://example.com/a", "status": "ready_for_alfred", "body_html": "x"}]})
    assert not (tmp_path / "index.jsonl").exists()
    bad_root = tmp_path / "not-directory"
    bad_root.write_text("x")
    index = CanonicalArtifactIndex("r", tmp_path / "i.jsonl", bad_root / "child", repository_root=tmp_path)
    index.safely("observe_bob", {"articles": [{"source_url": "https://example.com/a", "status": "ready_for_alfred", "body_html": "x"}]})
    assert index.summary()["archive_write_errors"] == 1


def test_closed_envelope_and_validator_failures(tmp_path):
    index = make_index(tmp_path)
    index.observe_bob({"articles": [{"source_url": "https://example.com/a", "status": "ready_for_alfred", "body_html": "x"}]})
    row = rows(tmp_path)[0]
    assert validate_manifest_entry({**row, "unknown": True}) == ["unknown field: unknown"]
    with (tmp_path / "index.jsonl").open("a") as handle:
        handle.write(json.dumps({**row, "correlation_id": "corr_bad"}) + "\n")
    (tmp_path / row["path"]).write_text("changed")
    report, code = validate_index(tmp_path / "index.jsonl", tmp_path)
    assert code == 1
    assert report["duplicate_artifact_ids"] == 1 and report["identity_errors"] >= 1
    assert report["integrity_errors"] >= 2


def test_a3_nested_contract_mutations(tmp_path):
    index = make_index(tmp_path)
    index.observe_bob({"articles": [{"source_url": "https://example.com/a", "status": "ready_for_alfred", "body_html": "x"}]})
    row = rows(tmp_path)[0]
    mutations = [
        {"retention_policy": {"mode": "bounded_count", "value_source": "fixed_contract", "max_items": True}},
        {"retention_policy": {"mode": "bounded_count", "value_source": "fixed_contract", "max_items": 0}},
        {"retention_policy": {"mode": "bounded_time", "value_source": "fixed_contract", "max_age_days": True}},
        {"retention_policy": {"mode": "bounded_time", "value_source": "fixed_contract", "max_age_days": 0}},
        {"authority_claims": [{"purpose": "source_material", "level": "supporting", "selector": 3}]},
        {"authority_claims": [{"purpose": "source_material", "level": "supporting", "note": False}]},
        {"artifact_schema_version": {"status": "known", "version": 3}},
        {"artifact_schema_version": {"status": "producer_version_only", "version": ""}},
    ]
    assert all(validate_manifest_entry({**row, **mutation}) for mutation in mutations)


def test_valid_source_observation_never_hydrates_fetches_calls_model_or_wp(tmp_path, monkeypatch):
    from agents import bob, publisher
    forbidden = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("forbidden call"))
    monkeypatch.setattr(source_body, "hydrate", forbidden)
    monkeypatch.setattr(bob, "fetch_html", forbidden)
    monkeypatch.setattr(bob, "call_gemini", forbidden)
    monkeypatch.setattr(publisher, "wp_request", forbidden)
    index = make_index(tmp_path)
    index.observe_bob({"articles": [{"source_url": "https://example.com/story", "status": "ready_for_alfred",
                                      "canonical_source_body": contract(), "body_html": "exact"}]})
    assert len(rows(tmp_path)) == 2


def test_index_append_failure_is_fail_open(tmp_path):
    index_parent = tmp_path / "index-parent"
    index_parent.write_text("not a directory")
    index = CanonicalArtifactIndex("run", index_parent / "index.jsonl", tmp_path / "material",
                                   repository_root=tmp_path)
    index.safely("observe_bob", {"articles": [{"source_url": "https://example.com/a",
                                                 "status": "ready_for_alfred", "body_html": "exact"}]})
    assert index.summary()["index_write_errors"] == 1


@pytest.mark.parametrize("failure", ["malformed", "missing", "sha", "size", "correlation", "artifact_id"])
def test_validator_individual_failures(tmp_path, failure):
    case = tmp_path / failure
    case.mkdir()
    index = CanonicalArtifactIndex("run", case / "index.jsonl", case / "material", repository_root=case)
    index.observe_bob({"articles": [{"source_url": "https://example.com/a", "status": "ready_for_alfred", "body_html": "x"}]})
    row = json.loads((case / "index.jsonl").read_text())
    artifact_path = case / row["path"]
    if failure == "malformed":
        (case / "index.jsonl").write_text("{bad json\n")
    elif failure == "missing":
        artifact_path.unlink()
    elif failure == "sha":
        row["sha256"] = "0" * 64
        (case / "index.jsonl").write_text(json.dumps(row) + "\n")
    elif failure == "size":
        row["size_bytes"] += 1
        (case / "index.jsonl").write_text(json.dumps(row) + "\n")
    elif failure == "correlation":
        row["correlation_id"] = "corr_" + "0" * 64
        (case / "index.jsonl").write_text(json.dumps(row) + "\n")
    else:
        row["artifact_id"] = "afi_" + "0" * 64
        (case / "index.jsonl").write_text(json.dumps(row) + "\n")
    report, code = validate_index(case / "index.jsonl", case)
    assert code == 1 and report["invalid_rows"] >= 1
    if failure == "artifact_id":
        assert report["identity_errors"] == 1


def test_newsroom_artifact_initialization_failure_reaches_publisher(tmp_path, monkeypatch):
    import newsroom_runner as runner
    reached = {"publisher": False}
    item = {"source_url": "https://example.test/source"}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEWSROOM_RUN_ID", "artifact-init-failure")
    monkeypatch.setattr(runner, "ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(runner, "canonical_artifact_index_factory",
                        lambda _run_id: (_ for _ in ()).throw(RuntimeError("forced artifact init failure")))
    monkeypatch.setattr(runner, "import_massy", lambda: lambda: {"news_candidates_for_menzo": [item], "handoff": {}})
    monkeypatch.setattr(runner, "import_simone", lambda: lambda board: {"ready_reports": [], "handoff": {}})
    monkeypatch.setattr(runner, "import_simone_report_publisher", lambda: lambda decision: {"results": [], "handoff": {}})
    monkeypatch.setattr(runner, "import_menzo", lambda: lambda board: {"selected": [item], "handoff": {}})
    monkeypatch.setattr(runner, "import_andrea", lambda: lambda decision: decision)
    monkeypatch.setattr(runner, "import_bob", lambda: lambda decision: {"articles": [], "handoff": {}})
    monkeypatch.setattr(runner, "import_alfred", lambda: lambda bob: {"reviews": [], "approved_articles": [], "handoff": {}})

    def publish(_alfred):
        reached["publisher"] = True
        return {"results": [], "handoff": {}}

    monkeypatch.setattr(runner, "import_publisher", lambda: publish)
    monkeypatch.setattr(runner, "import_archivista", lambda: lambda **kwargs: {"overall_status": "ok", "summary": {}})
    monkeypatch.setattr(runner, "gemini_ledger_summary", lambda: {})
    monkeypatch.setattr(runner, "write_master_log_safe", lambda *args, **kwargs: {})
    assert runner.main() == 0 and reached["publisher"]
    summary = json.loads((tmp_path / "artifacts" / "run_summary.json").read_text())
    diagnostic = summary["canonical_artifact_index"]
    assert diagnostic["enabled"] is False
    assert "forced artifact init failure" in diagnostic["initialization_error"]
