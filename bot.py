#!/usr/bin/env python3
"""OpenWrestlingTV consolidated v93 bot entrypoint.

Stable VPS/cron command:

    python bot.py

v94.13 is VPS-safe: by default it never runs the historical patch
bootstrap from runtime. Production cron/VPS runs newsroom_runner.py against the
checked-out source; the historical patch chain is allowed only with
OWTV_FORCE_PATCH_BOOTSTRAP=1.

Operational VPS flow:

    cd /opt/owtv/wrestling-news-bot
    git pull --ff-only
    python bot.py
    git status --short

Expected result after the run: no modified tracked source files. Runtime files
must be ignored by .gitignore.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BOT_VERSION = "v94_13_disable_runtime_source_bootstrap"
ROOT = Path(__file__).resolve().parent
PATCH_CHAIN = ROOT / "scripts" / "apply_v92_report_workshop.py"
NEWSROOM_RUNNER = ROOT / "newsroom_runner.py"

CONSOLIDATED_MARKERS = {
    "agents/bob.py": ["v93_39_dynamic_article_capacity"],
    "agents/menzo_policy_v93_15.py": ["v93_39_capacity_buffer"],
    "agents/publisher.py": ["v93_40_publisher_capacity_audit"],
    "agents/publisher_policy_v93_20.py": ["v93_40_outer_publisher_handoff_audit"],
    "agents/massy_policy_v93_24.py": ["v93_32"],
    "agents/story_dedupe_v93_32.py": ["story"],
    "newsroom_runner.py": ["v93_20_process_refinements"],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_step(label: str, command: list[str], *, env: dict[str, str] | None = None) -> int:
    print(f"[BOT {BOT_VERSION}] {label} | cmd={' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=str(ROOT), env=env, check=False)
    print(f"[BOT {BOT_VERSION}] {label} | exit={result.returncode}", flush=True)
    return int(result.returncode)


def git_head() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True, capture_output=True, check=False)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return "unknown"


def git_tracked_source_status() -> list[str]:
    try:
        res = subprocess.run(["git", "status", "--short"], cwd=str(ROOT), text=True, capture_output=True, check=False)
        if res.returncode != 0:
            return []
        lines = []
        for line in res.stdout.splitlines():
            path = line[3:].strip() if len(line) >= 4 else ""
            if not path:
                continue
            if path.endswith(".py") or path.endswith(".yml") or path.endswith(".yaml") or path.endswith(".md") or path == ".gitignore":
                lines.append(line)
        return lines
    except Exception:
        return []


def source_is_consolidated() -> bool:
    missing: list[str] = []
    for rel_path, markers in CONSOLIDATED_MARKERS.items():
        path = ROOT / rel_path
        if not path.exists():
            missing.append(f"{rel_path}:missing")
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in markers:
            if marker not in text:
                missing.append(f"{rel_path}:{marker}")
    if missing:
        print(f"[BOT {BOT_VERSION}] consolidated_source=False missing_markers={missing}", flush=True)
        return False
    print(f"[BOT {BOT_VERSION}] consolidated_source=True", flush=True)
    return True


def main() -> int:
    started = utc_now()
    print(f"===== BOT CONSOLIDATED RUN START [{started}] VERSION [{BOT_VERSION}] =====", flush=True)
    print(f"[BOT {BOT_VERSION}] repo={ROOT} git_head={git_head()}", flush=True)

    if not NEWSROOM_RUNNER.exists():
        print(f"[BOT {BOT_VERSION}] ERRORE: newsroom_runner non trovato: {NEWSROOM_RUNNER}", flush=True)
        return 2

    env = os.environ.copy()
    env.setdefault("V93_SKIP_V92_AFTER_BOB", "1")

    force_bootstrap = env.get("OWTV_FORCE_PATCH_BOOTSTRAP", "").strip().lower() in {"1", "true", "yes", "on"}
    explicit_skip_bootstrap = env.get("OWTV_SKIP_PATCH_BOOTSTRAP", "").strip().lower() in {"1", "true", "yes", "on"}
    skip_bootstrap = not force_bootstrap

    # Diagnostic only: v94+ runtime must not use source marker state to decide
    # whether to mutate tracked source files. Historical patch bootstrap is
    # disabled by default and can only run with OWTV_FORCE_PATCH_BOOTSTRAP=1.
    source_is_consolidated()

    if force_bootstrap:
        print(f"[BOT {BOT_VERSION}] patch bootstrap forzato da OWTV_FORCE_PATCH_BOOTSTRAP=1", flush=True)
    elif explicit_skip_bootstrap:
        print(f"[BOT {BOT_VERSION}] patch bootstrap saltato da OWTV_SKIP_PATCH_BOOTSTRAP=1", flush=True)
    else:
        print(f"[BOT {BOT_VERSION}] patch bootstrap disabilitato di default; usare OWTV_FORCE_PATCH_BOOTSTRAP=1 per abilitarlo", flush=True)

    if not skip_bootstrap:
        if not PATCH_CHAIN.exists():
            print(f"[BOT {BOT_VERSION}] ERRORE: patch chain non trovata: {PATCH_CHAIN}", flush=True)
            return 2
        code = run_step("apply_idempotent_patch_chain", [sys.executable, str(PATCH_CHAIN)], env=env)
        if code != 0:
            print(f"[BOT {BOT_VERSION}] ERRORE: bootstrap patch fallito, fermo la run", flush=True)
            return code

    before_status = git_tracked_source_status()
    if before_status:
        print(f"[BOT {BOT_VERSION}] ATTENZIONE: sorgenti gia sporchi prima della run: {before_status}", flush=True)

    code = run_step("run_v93_newsroom", [sys.executable, str(NEWSROOM_RUNNER)], env=env)

    after_status = git_tracked_source_status()
    if after_status:
        print(f"[BOT {BOT_VERSION}] ATTENZIONE: sorgenti modificati dopo la run: {after_status}", flush=True)
    else:
        print(f"[BOT {BOT_VERSION}] vps_clean_check=ok tracked_source_status=clean", flush=True)

    ended = utc_now()
    print(f"===== BOT CONSOLIDATED RUN END [{ended}] VERSION [{BOT_VERSION}] EXIT [{code}] =====", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
