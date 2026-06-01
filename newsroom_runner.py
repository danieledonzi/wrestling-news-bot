#!/usr/bin/env python3
"""OpenWrestlingTV v93 Virtual Newsroom bootstrap runner.

This is a conservative wrapper around the existing runtime.
It does not import bot_v92.py or bot.py. It delegates once through subprocess,
records newsroom artifacts, and propagates the runtime exit code.

Compatibility marker for existing workflow validation:
v93_0_virtual_newsroom_bootstrap
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NEWSROOM_VERSION = "v93_6_publisher_wordpress"
ARTIFACT_DIR = Path("artifacts") / "newsroom"

AGENTS = [
    "Jarvis",
    "Massy",
    "Simone",
    "Menzo",
    "Bob",
    "Alfred",
    "Publisher",
    "Archivista",
]


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
    item = {
        "timestamp": utc_now(),
        "agent": agent,
        "phase": phase,
    }
    if note:
        item["note"] = note
    timeline.append(item)
    label = f"[{agent.upper()} v93]"
    print(f"{label} {phase}" + (f" - {note}" if note else ""), flush=True)


def runtime_command() -> list[str]:
    override = os.getenv("NEWSROOM_ENGINE", "").strip()
    if override:
        return [sys.executable, override]
    return [sys.executable, "bot_v92.py"]


def run_massy_sentinel(timeline: list[dict[str, str]]) -> dict[str, Any]:
    try:
        from agents.massy import run_massy
    except Exception as exc:
        error = {
            "agent": "Massy",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": f"import_failed: {exc}",
            "handoff": {"to_simone": 0, "to_menzo": 0, "hard_skipped": 0, "already_worked": 0},
        }
        write_json(ARTIFACT_DIR / "massy_board.json", error)
        add_timeline(timeline, "Massy", "error", f"import_failed={exc}")
        return error

    try:
        board = run_massy()
        handoff = board.get("handoff", {}) if isinstance(board, dict) else {}
        add_timeline(
            timeline,
            "Massy",
            "sentinel_board_ready",
            "to_simone={to_simone} to_menzo={to_menzo} hard_skip={hard_skipped} already={already_worked}".format(
                to_simone=handoff.get("to_simone", 0),
                to_menzo=handoff.get("to_menzo", 0),
                hard_skipped=handoff.get("hard_skipped", 0),
                already_worked=handoff.get("already_worked", 0),
            ),
        )
        return board
    except Exception as exc:
        error = {
            "agent": "Massy",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": str(exc),
            "handoff": {"to_simone": 0, "to_menzo": 0, "hard_skipped": 0, "already_worked": 0},
        }
        write_json(ARTIFACT_DIR / "massy_board.json", error)
        add_timeline(timeline, "Massy", "error", str(exc))
        return error


def run_simone_reports(timeline: list[dict[str, str]], massy_board: dict[str, Any]) -> dict[str, Any]:
    try:
        from agents.simone import run_simone
    except Exception as exc:
        error = {
            "agent": "Simone",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": f"import_failed: {exc}",
            "handoff": {"ready": 0, "waiting": 0, "skipped": 0},
        }
        write_json(ARTIFACT_DIR / "simone_reports.json", error)
        add_timeline(timeline, "Simone", "error", f"import_failed={exc}")
        return error

    try:
        decision = run_simone(massy_board)
        handoff = decision.get("handoff", {}) if isinstance(decision, dict) else {}
        add_timeline(
            timeline,
            "Simone",
            "report_decision_ready",
            "ready={ready} waiting={waiting} skipped={skipped}".format(
                ready=handoff.get("ready", 0),
                waiting=handoff.get("waiting", 0),
                skipped=handoff.get("skipped", 0),
            ),
        )
        return decision
    except Exception as exc:
        error = {
            "agent": "Simone",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": str(exc),
            "handoff": {"ready": 0, "waiting": 0, "skipped": 0},
        }
        write_json(ARTIFACT_DIR / "simone_reports.json", error)
        add_timeline(timeline, "Simone", "error", str(exc))
        return error


def run_menzo_editorial(timeline: list[dict[str, str]], massy_board: dict[str, Any]) -> dict[str, Any]:
    try:
        from agents.menzo import run_menzo
    except Exception as exc:
        error = {
            "agent": "Menzo",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": f"import_failed: {exc}",
            "handoff": {"to_bob_or_v92": 0, "pending": 0, "skipped": 0},
        }
        write_json(ARTIFACT_DIR / "menzo_decisions.json", error)
        add_timeline(timeline, "Menzo", "error", f"import_failed={exc}")
        return error

    try:
        decision = run_menzo(massy_board)
        handoff = decision.get("handoff", {}) if isinstance(decision, dict) else {}
        add_timeline(
            timeline,
            "Menzo",
            "editorial_decision_ready",
            "selected={selected} pending={pending} skipped={skipped}".format(
                selected=handoff.get("to_bob_or_v92", 0),
                pending=handoff.get("pending", 0),
                skipped=handoff.get("skipped", 0),
            ),
        )
        return decision
    except Exception as exc:
        error = {
            "agent": "Menzo",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": str(exc),
            "handoff": {"to_bob_or_v92": 0, "pending": 0, "skipped": 0},
        }
        write_json(ARTIFACT_DIR / "menzo_decisions.json", error)
        add_timeline(timeline, "Menzo", "error", str(exc))
        return error


def run_bob_writer(timeline: list[dict[str, str]], menzo_decision: dict[str, Any]) -> dict[str, Any]:
    try:
        from agents.bob import run_bob
    except Exception as exc:
        error = {
            "agent": "Bob",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": f"import_failed: {exc}",
            "handoff": {"ready_for_alfred": 0, "translation_pending": 0, "errors": 0},
        }
        write_json(ARTIFACT_DIR / "bob_articles.json", error)
        add_timeline(timeline, "Bob", "error", f"import_failed={exc}")
        return error
    try:
        result = run_bob(menzo_decision)
        handoff = result.get("handoff", {}) if isinstance(result, dict) else {}
        add_timeline(
            timeline,
            "Bob",
            "article_packages_ready",
            "ready={ready} pending={pending} errors={errors}".format(
                ready=handoff.get("ready_for_alfred", 0),
                pending=handoff.get("translation_pending", 0),
                errors=handoff.get("errors", 0),
            ),
        )
        return result
    except Exception as exc:
        error = {
            "agent": "Bob",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": str(exc),
            "handoff": {"ready_for_alfred": 0, "translation_pending": 0, "errors": 0},
        }
        write_json(ARTIFACT_DIR / "bob_articles.json", error)
        add_timeline(timeline, "Bob", "error", str(exc))
        return error


def run_alfred_review(timeline: list[dict[str, str]], bob_result: dict[str, Any]) -> dict[str, Any]:
    try:
        from agents.alfred import run_alfred
    except Exception as exc:
        error = {
            "agent": "Alfred",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": f"import_failed: {exc}",
            "handoff": {"approved": 0, "needs_revision": 0, "warnings": 0, "blockers": 0, "editorial_changes": 0},
        }
        write_json(ARTIFACT_DIR / "alfred_review.json", error)
        add_timeline(timeline, "Alfred", "error", f"import_failed={exc}")
        return error
    try:
        result = run_alfred(bob_result)
        handoff = result.get("handoff", {}) if isinstance(result, dict) else {}
        add_timeline(
            timeline,
            "Alfred",
            "quality_review_ready",
            "approved={approved} needs_revision={needs_revision} blockers={blockers} warnings={warnings}".format(
                approved=handoff.get("approved", 0),
                needs_revision=handoff.get("needs_revision", 0),
                blockers=handoff.get("blockers", 0),
                warnings=handoff.get("warnings", 0),
            ),
        )
        return result
    except Exception as exc:
        error = {
            "agent": "Alfred",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": str(exc),
            "handoff": {"approved": 0, "needs_revision": 0, "warnings": 0, "blockers": 0, "editorial_changes": 0},
        }
        write_json(ARTIFACT_DIR / "alfred_review.json", error)
        add_timeline(timeline, "Alfred", "error", str(exc))
        return error


def run_publisher_agent(timeline: list[dict[str, str]], alfred_result: dict[str, Any]) -> dict[str, Any]:
    try:
        from agents.publisher import run_publisher
    except Exception as exc:
        error = {
            "agent": "Publisher",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": f"import_failed: {exc}",
            "handoff": {"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0},
        }
        write_json(ARTIFACT_DIR / "publisher_result.json", error)
        add_timeline(timeline, "Publisher", "error", f"import_failed={exc}")
        return error
    try:
        result = run_publisher(alfred_result)
        handoff = result.get("handoff", {}) if isinstance(result, dict) else {}
        add_timeline(
            timeline,
            "Publisher",
            "publication_ready",
            "published={published} already={already} dry={dry} wp_not_ready={wp_not_ready} errors={errors}".format(
                published=handoff.get("published", 0),
                already=handoff.get("already_published", 0),
                dry=handoff.get("dry_run", 0),
                wp_not_ready=handoff.get("wp_not_ready", 0),
                errors=handoff.get("errors", 0),
            ),
        )
        return result
    except Exception as exc:
        error = {
            "agent": "Publisher",
            "version": NEWSROOM_VERSION,
            "generated_at": utc_now(),
            "status": "error",
            "error": str(exc),
            "handoff": {"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 1},
        }
        write_json(ARTIFACT_DIR / "publisher_result.json", error)
        add_timeline(timeline, "Publisher", "error", str(exc))
        return error


def main() -> int:
    ensure_artifacts()
    started_at = utc_now()
    timeline: list[dict[str, str]] = []

    print(f"===== NEWSROOM RUN START [{started_at}] VERSION [{NEWSROOM_VERSION}] =====", flush=True)
    print("[NEWSROOM v93] Avvio Virtual Newsroom", flush=True)
    print("[NEWSROOM v93] Massy, Simone, Menzo, Bob, Alfred and Publisher are real", flush=True)

    command = runtime_command()
    engine = command[1] if len(command) > 1 else "unknown"
    is_test_override = bool(os.getenv("NEWSROOM_ENGINE", "").strip())

    jarvis_status = {
        "version": NEWSROOM_VERSION,
        "created_at": utc_now(),
        "agent": "Jarvis",
        "mode": "bootstrap_wrapper",
        "engine": engine,
        "newsroom_engine_override": is_test_override,
        "wp_status_source": "v93_publisher",
        "can_translate": "v93_bob",
        "can_review": "v93_alfred",
        "can_publish": "v93_publisher",
        "notes": [
            "Jarvis wrapper uses v93 Publisher for WordPress publication in v93.6",
            "v92 fallback remains skipped by default to avoid legacy patch side effects",
        ],
    }
    write_json(ARTIFACT_DIR / "jarvis_status.json", jarvis_status)
    add_timeline(timeline, "Jarvis", "bootstrap_status_written", f"engine={engine}")

    massy_board = run_massy_sentinel(timeline)
    simone_decision = run_simone_reports(timeline, massy_board)
    menzo_decision = run_menzo_editorial(timeline, massy_board)
    bob_result = run_bob_writer(timeline, menzo_decision)
    alfred_result = run_alfred_review(timeline, bob_result)
    publisher_result = run_publisher_agent(timeline, alfred_result)

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
    massy_handoff = massy_board.get("handoff", {}) if isinstance(massy_board, dict) else {}
    simone_handoff = simone_decision.get("handoff", {}) if isinstance(simone_decision, dict) else {}
    menzo_handoff = menzo_decision.get("handoff", {}) if isinstance(menzo_decision, dict) else {}
    bob_handoff = bob_result.get("handoff", {}) if isinstance(bob_result, dict) else {}
    alfred_handoff = alfred_result.get("handoff", {}) if isinstance(alfred_result, dict) else {}
    publisher_handoff = publisher_result.get("handoff", {}) if isinstance(publisher_result, dict) else {}
    run_summary = {
        "version": NEWSROOM_VERSION,
        "started_at": started_at,
        "ended_at": ended_at,
        "engine": engine,
        "newsroom_engine_override": is_test_override,
        "runtime_delegations": runtime_delegations,
        "runtime_exit_code": runtime_exit_code,
        "agents": {
            "jarvis": "wrapped",
            "massy": "real_sentinel_control",
            "simone": "real_report_director",
            "menzo": "real_editorial_director",
            "bob": "real_article_writer",
            "alfred": "real_quality_editor",
            "publisher": "real_wordpress_publisher",
            "archivista": "wrapped",
        },
        "massy_handoff": massy_handoff,
        "simone_handoff": simone_handoff,
        "menzo_handoff": menzo_handoff,
        "bob_handoff": bob_handoff,
        "alfred_handoff": alfred_handoff,
        "publisher_handoff": publisher_handoff,
        "notes": [
            "v93.6 introduces Publisher as WordPress publisher",
            "Publisher consumes Alfred approved_articles and writes publisher history by source URL",
            "v92 fallback is skipped by default after v93 Publisher",
        ],
    }

    add_timeline(timeline, "Archivista", "summary_saved", "writing newsroom artifacts")
    write_json(ARTIFACT_DIR / "agent_timeline.json", timeline)
    write_json(ARTIFACT_DIR / "run_summary.json", run_summary)

    print(f"[ARCHIVISTA v93] Saved {ARTIFACT_DIR / 'run_summary.json'}", flush=True)
    print(f"===== NEWSROOM RUN END [{ended_at}] VERSION [{NEWSROOM_VERSION}] EXIT [{runtime_exit_code}] =====", flush=True)
    return runtime_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
