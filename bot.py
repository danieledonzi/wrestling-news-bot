#!/usr/bin/env python3
"""OpenWrestlingTV consolidated v93 bot entrypoint.

This is the stable command for VPS/cron usage:

    python bot.py

It intentionally does not contain the full newsroom logic inline. Instead it performs the
same idempotent bootstrap used by GitHub Actions, applying every v92/v93 patch in the
current repository checkout, then delegates to the v93 Virtual Newsroom runner.

Operational rule for VPS deployments:
- keep the repository updated with `git pull --ff-only` before running this file;
- this file will then consolidate the checked-out code by applying the patch chain.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BOT_VERSION = "v93_41_consolidated_vps_entrypoint"
ROOT = Path(__file__).resolve().parent
PATCH_CHAIN = ROOT / "scripts" / "apply_v92_report_workshop.py"
NEWSROOM_RUNNER = ROOT / "newsroom_runner.py"


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


def main() -> int:
    started = utc_now()
    print(f"===== BOT CONSOLIDATED RUN START [{started}] VERSION [{BOT_VERSION}] =====", flush=True)
    print(f"[BOT {BOT_VERSION}] repo={ROOT} git_head={git_head()}", flush=True)

    if not PATCH_CHAIN.exists():
        print(f"[BOT {BOT_VERSION}] ERRORE: patch chain non trovata: {PATCH_CHAIN}", flush=True)
        return 2
    if not NEWSROOM_RUNNER.exists():
        print(f"[BOT {BOT_VERSION}] ERRORE: newsroom_runner non trovato: {NEWSROOM_RUNNER}", flush=True)
        return 2

    env = os.environ.copy()
    # The v93 newsroom is the source of truth. Keep the legacy v92 fallback disabled unless
    # explicitly overridden for a test run.
    env.setdefault("V93_SKIP_V92_AFTER_BOB", "1")

    skip_bootstrap = env.get("OWTV_SKIP_PATCH_BOOTSTRAP", "").strip().lower() in {"1", "true", "yes", "on"}
    if skip_bootstrap:
        print(f"[BOT {BOT_VERSION}] patch bootstrap saltato per OWTV_SKIP_PATCH_BOOTSTRAP=1", flush=True)
    else:
        code = run_step("apply_idempotent_patch_chain", [sys.executable, str(PATCH_CHAIN)], env=env)
        if code != 0:
            print(f"[BOT {BOT_VERSION}] ERRORE: bootstrap patch fallito, fermo la run", flush=True)
            return code

    code = run_step("run_v93_newsroom", [sys.executable, str(NEWSROOM_RUNNER)], env=env)
    ended = utc_now()
    print(f"===== BOT CONSOLIDATED RUN END [{ended}] VERSION [{BOT_VERSION}] EXIT [{code}] =====", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
