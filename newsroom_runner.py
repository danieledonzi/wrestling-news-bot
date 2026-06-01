#!/usr/bin/env python3
"""OpenWrestlingTV v93 Virtual Newsroom bootstrap runner.

This is a conservative wrapper around the existing runtime.
It does not import bot_v92.py or bot.py. It delegates once through subprocess,
records newsroom artifacts, and propagates the runtime exit code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NEWSROOM_VERSION = "v93_1_massy_sentinel_control"
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
    """Run Massy before the legacy runtime.

    In v93.1 Massy is a real sentinel and its hard skips/report/news split
    is written to artifacts and state. The legacy runtime is still delegated
    afterward while Menzo and Simone are progressively moved to real control.
    """

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


def main() -> int:
    ensure_artifacts()
    started_at = utc_now()
    timeline: list[dict[str, str]] = []

    print(f"===== NEWSROOM RUN START [{started_at}] VERSION [{NEWSROOM_VERSION}] =====", flush=True)
    print("[NEWSROOM v93] Avvio Virtual Newsroom", flush=True)
    print("[NEWSROOM v93] Massy is real; downstream runtime still delegated during staged takeover", flush=True)

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
        "wp_status_source": "existing_runtime",
        "can_translate": "delegated_to_existing_runtime",
        "can_publish": "delegated_to_existing_runtime",
        "notes": [
            "Jarvis wrapper does not duplicate WordPress checks in v93.1",
            "Existing runtime owns real WordPress diagnostics and stop-before-translation behavior",
        ],
    }
    write_json(ARTIFACT_DIR / "jarvis_status.json", jarvis_status)
    add_timeline(timeline, "Jarvis", "bootstrap_status_written", f"engine={engine}")

    massy_board = run_massy_sentinel(timeline)

    for agent, note in [
        ("Simone", "report discretion will consume Massy report_candidates in a future step"),
        ("Menzo", "news decision will consume Massy news_candidates_for_menzo in a future step"),
        ("Bob", "translation delegated to existing runtime"),
        ("Alfred", "guardrails/QA delegated to existing runtime"),
        ("Publisher", "WordPress publication delegated to existing runtime"),
    ]:
        add_timeline(timeline, agent, "wrapped", note)

    runtime_delegations = 1
    add_timeline(timeline, "Jarvis", "runtime_start", "delegating once via subprocess")
    print(f"[NEWSROOM v93] Runtime command: {' '.join(command)}", flush=True)

    result = subprocess.run(command, check=False)
    runtime_exit_code = int(result.returncode)

    add_timeline(timeline, "Publisher", "runtime_finished", f"exit_code={runtime_exit_code}")

    ended_at = utc_now()
    handoff = massy_board.get("handoff", {}) if isinstance(massy_board, dict) else {}
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
            "simone": "wrapped_pending_takeover",
            "menzo": "wrapped_pending_takeover",
            "bob": "wrapped",
            "alfred": "wrapped",
            "publisher": "wrapped",
            "archivista": "wrapped",
        },
        "massy_handoff": handoff,
        "notes": [
            "v93.1 introduces Massy as a real sentinel-control board",
            "Massy hard skips are binding for newsroom planning, while bot_v92 remains delegated until Menzo/Simone takeover",
            "Reports remain excluded from the daily news target by design documentation",
            "Target daily news volume is documented as 20-30 news excluding reports",
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
