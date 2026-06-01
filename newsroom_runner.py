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

NEWSROOM_VERSION = "v93_0_virtual_newsroom_bootstrap"
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


def main() -> int:
    ensure_artifacts()
    started_at = utc_now()
    timeline: list[dict[str, str]] = []

    print(f"===== NEWSROOM RUN START [{started_at}] VERSION [{NEWSROOM_VERSION}] =====", flush=True)
    print("[NEWSROOM v93] Avvio Virtual Newsroom bootstrap", flush=True)
    print("[NEWSROOM v93] Core runtime delegated to existing engine; no scoring/dedupe/translation changes", flush=True)

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
            "Jarvis wrapper does not duplicate WordPress checks in v93.0",
            "Existing runtime owns real WordPress diagnostics and stop-before-translation behavior",
        ],
    }
    write_json(ARTIFACT_DIR / "jarvis_status.json", jarvis_status)
    add_timeline(timeline, "Jarvis", "bootstrap_status_written", f"engine={engine}")

    for agent, note in [
        ("Massy", "feed scan delegated to existing runtime"),
        ("Simone", "report pipeline delegated to existing runtime"),
        ("Menzo", "news decision delegated to existing runtime"),
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
    run_summary = {
        "version": NEWSROOM_VERSION,
        "started_at": started_at,
        "ended_at": ended_at,
        "engine": engine,
        "newsroom_engine_override": is_test_override,
        "runtime_delegations": runtime_delegations,
        "runtime_exit_code": runtime_exit_code,
        "agents": {agent.lower(): "wrapped" for agent in AGENTS},
        "notes": [
            "v93.0 is a conservative wrapper/bootstrap release",
            "Core publishing logic is delegated to the existing runtime",
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
