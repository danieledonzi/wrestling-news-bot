#!/usr/bin/env python3
"""OpenWrestlingTV v93 Virtual Newsroom runner.

Compatibility marker for workflow validation:
v93_0_virtual_newsroom_bootstrap

The runner does not import or execute bot_v92.py by default.  NEWSROOM_ENGINE
remains available only as an explicit test override, and runtime_delegations is
kept in the summary for backward-compatible verification.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

NEWSROOM_VERSION = "v93_7_archivista_audit"
ARTIFACT_DIR = Path("artifacts") / "newsroom"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def add_timeline(timeline: list[dict[str, str]], agent: str, phase: str, note: str = "") -> None:
    item = {"timestamp": utc_now(), "agent": agent, "phase": phase}
    if note:
        item["note"] = note
    timeline.append(item)
    print(f"[{agent.upper()} v93] {phase}" + (f" - {note}" if note else ""), flush=True)


def runtime_command() -> list[str]:
    override = os.getenv("NEWSROOM_ENGINE", "").strip()
    if override:
        return [sys.executable, override]
    return [sys.executable, "bot_v92.py"]


def handoff(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("handoff", {}) if isinstance(data.get("handoff"), dict) else {}


def safe_agent(
    *,
    timeline: list[dict[str, str]],
    agent: str,
    phase: str,
    import_fn: Callable[[], Callable[..., dict[str, Any]]],
    call_args: tuple[Any, ...] = (),
    artifact_name: str,
    default_handoff: dict[str, Any],
    note_fn: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    try:
        fn = import_fn()
    except Exception as exc:
        error = {"agent": agent, "version": NEWSROOM_VERSION, "generated_at": utc_now(), "status": "error", "error": f"import_failed: {exc}", "handoff": default_handoff}
        write_json(ARTIFACT_DIR / artifact_name, error)
        add_timeline(timeline, agent, "error", f"import_failed={exc}")
        return error
    try:
        result = fn(*call_args)
        add_timeline(timeline, agent, phase, note_fn(result if isinstance(result, dict) else {}))
        return result if isinstance(result, dict) else {"agent": agent, "status": "invalid_result", "handoff": default_handoff}
    except Exception as exc:
        error = {"agent": agent, "version": NEWSROOM_VERSION, "generated_at": utc_now(), "status": "error", "error": str(exc), "handoff": default_handoff}
        write_json(ARTIFACT_DIR / artifact_name, error)
        add_timeline(timeline, agent, "error", str(exc))
        return error


def import_massy():
    from agents.massy import run_massy
    return run_massy


def import_simone():
    from agents.simone import run_simone
    return run_simone


def import_menzo():
    from agents.menzo import run_menzo
    return run_menzo


def import_bob():
    from agents.bob import run_bob
    return run_bob


def import_alfred():
    from agents.alfred import run_alfred
    return run_alfred


def import_publisher():
    from agents.publisher import run_publisher
    return run_publisher


def import_archivista():
    from agents.archivista import run_archivista
    return run_archivista


def main() -> int:
    ensure_artifacts()
    started_at = utc_now()
    timeline: list[dict[str, str]] = []
    print(f"===== NEWSROOM RUN START [{started_at}] VERSION [{NEWSROOM_VERSION}] =====", flush=True)
    print("[NEWSROOM v93] Avvio Virtual Newsroom", flush=True)
    print("[NEWSROOM v93] Massy, Simone, Menzo, Bob, Alfred, Publisher and Archivista are real", flush=True)
    command = runtime_command()
    engine = command[1] if len(command) > 1 else "unknown"
    is_test_override = bool(os.getenv("NEWSROOM_ENGINE", "").strip())
    jarvis_status = {"version": NEWSROOM_VERSION, "created_at": utc_now(), "agent": "Jarvis", "mode": "v93_orchestrator", "engine": engine, "newsroom_engine_override": is_test_override, "wp_status_source": "v93_publisher", "can_translate": "v93_bob", "can_review": "v93_alfred", "can_publish": "v93_publisher", "can_audit": "v93_archivista"}
    write_json(ARTIFACT_DIR / "jarvis_status.json", jarvis_status)
    add_timeline(timeline, "Jarvis", "bootstrap_status_written", f"engine={engine}")
    massy_board = safe_agent(timeline=timeline, agent="Massy", phase="sentinel_board_ready", import_fn=import_massy, artifact_name="massy_board.json", default_handoff={"to_simone": 0, "to_menzo": 0, "hard_skipped": 0, "already_worked": 0}, note_fn=lambda r: "to_simone={to_simone} to_menzo={to_menzo} hard_skip={hard_skipped} already={already_worked}".format(**{**{"to_simone": 0, "to_menzo": 0, "hard_skipped": 0, "already_worked": 0}, **handoff(r)}))
    simone_decision = safe_agent(timeline=timeline, agent="Simone", phase="report_decision_ready", import_fn=import_simone, call_args=(massy_board,), artifact_name="simone_reports.json", default_handoff={"ready": 0, "waiting": 0, "skipped": 0}, note_fn=lambda r: "ready={ready} waiting={waiting} skipped={skipped}".format(**{**{"ready": 0, "waiting": 0, "skipped": 0}, **handoff(r)}))
    menzo_decision = safe_agent(timeline=timeline, agent="Menzo", phase="editorial_decision_ready", import_fn=import_menzo, call_args=(massy_board,), artifact_name="menzo_decisions.json", default_handoff={"to_bob_or_v92": 0, "pending": 0, "skipped": 0}, note_fn=lambda r: "selected={to_bob_or_v92} pending={pending} skipped={skipped}".format(**{**{"to_bob_or_v92": 0, "pending": 0, "skipped": 0}, **handoff(r)}))
    bob_result = safe_agent(timeline=timeline, agent="Bob", phase="article_packages_ready", import_fn=import_bob, call_args=(menzo_decision,), artifact_name="bob_articles.json", default_handoff={"ready_for_alfred": 0, "translation_pending": 0, "errors": 0, "extraction_empty": 0}, note_fn=lambda r: "ready={ready_for_alfred} pending={translation_pending} empty={extraction_empty} errors={errors}".format(**{**{"ready_for_alfred": 0, "translation_pending": 0, "errors": 0, "extraction_empty": 0}, **handoff(r)}))
    alfred_result = safe_agent(timeline=timeline, agent="Alfred", phase="quality_review_ready", import_fn=import_alfred, call_args=(bob_result,), artifact_name="alfred_review.json", default_handoff={"approved": 0, "needs_revision": 0, "warnings": 0, "blockers": 0, "editorial_changes": 0}, note_fn=lambda r: "approved={approved} needs_revision={needs_revision} blockers={blockers} warnings={warnings} changes={editorial_changes}".format(**{**{"approved": 0, "needs_revision": 0, "warnings": 0, "blockers": 0, "editorial_changes": 0}, **handoff(r)}))
    publisher_result = safe_agent(timeline=timeline, agent="Publisher", phase="publication_ready", import_fn=import_publisher, call_args=(alfred_result,), artifact_name="publisher_result.json", default_handoff={"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}, note_fn=lambda r: "published={published} already={already_published} dry={dry_run} wp_not_ready={wp_not_ready} errors={errors}".format(**{**{"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}, **handoff(r)}))
    runtime_delegations = 0
    runtime_exit_code = 0
    skip_v92 = str(os.getenv("V93_SKIP_V92_AFTER_BOB", "1")).strip().lower() not in {"0", "false", "no", "off"}
    if skip_v92 and not is_test_override:
        add_timeline(timeline, "Jarvis", "runtime_skipped", "v93 Publisher completed; v92 fallback skipped")
        print("[NEWSROOM v93] v92 fallback skipped because V93_SKIP_V92_AFTER_BOB=1", flush=True)
    else:
        runtime_delegations = 1
        add_timeline(timeline, "Jarvis", "runtime_start", "delegating once via subprocess")
        print(f"[NEWSROOM v93] Runtime command: {' '.join(command)}", flush=True)
        result = subprocess.run(command, check=False)
        runtime_exit_code = int(result.returncode)
        add_timeline(timeline, "Publisher", "runtime_finished", f"exit_code={runtime_exit_code}")
    ended_at = utc_now()
    run_summary = {"version": NEWSROOM_VERSION, "started_at": started_at, "ended_at": ended_at, "engine": engine, "newsroom_engine_override": is_test_override, "runtime_delegations": runtime_delegations, "runtime_exit_code": runtime_exit_code, "agents": {"jarvis": "real_orchestrator", "massy": "real_sentinel_control", "simone": "real_report_director", "menzo": "real_editorial_director", "bob": "real_article_writer", "alfred": "real_quality_editor", "publisher": "real_wordpress_publisher", "archivista": "real_audit_agent"}, "massy_handoff": handoff(massy_board), "simone_handoff": handoff(simone_decision), "menzo_handoff": handoff(menzo_decision), "bob_handoff": handoff(bob_result), "alfred_handoff": handoff(alfred_result), "publisher_handoff": handoff(publisher_result)}
    archivista_result = safe_agent(timeline=timeline, agent="Archivista", phase="audit_ready", import_fn=import_archivista, call_args=(), artifact_name="archivista_report.json", default_handoff={"overall_status": "error"}, note_fn=lambda r: "status={status} anomalies={anomalies}".format(status=r.get("overall_status", "unknown"), anomalies=(r.get("summary", {}) if isinstance(r.get("summary"), dict) else {}).get("anomalies", 0)))
    if archivista_result.get("status") != "error":
        try:
            from agents.archivista import run_archivista
            archivista_result = run_archivista(timeline=timeline, run_summary=run_summary, massy=massy_board, simone=simone_decision, menzo=menzo_decision, bob=bob_result, alfred=alfred_result, publisher=publisher_result)
            add_timeline(timeline, "Archivista", "audit_context_refreshed", f"status={archivista_result.get('overall_status')}")
        except Exception as exc:
            add_timeline(timeline, "Archivista", "error", str(exc))
    run_summary["archivista_handoff"] = archivista_result.get("summary", {}) if isinstance(archivista_result, dict) else {}
    run_summary["archivista_status"] = archivista_result.get("overall_status") if isinstance(archivista_result, dict) else "error"
    write_json(ARTIFACT_DIR / "agent_timeline.json", timeline)
    write_json(ARTIFACT_DIR / "run_summary.json", run_summary)
    print(f"[ARCHIVISTA v93] Saved {ARTIFACT_DIR / 'run_summary.json'}", flush=True)
    print(f"===== NEWSROOM RUN END [{ended_at}] VERSION [{NEWSROOM_VERSION}] EXIT [{runtime_exit_code}] =====", flush=True)
    return runtime_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
