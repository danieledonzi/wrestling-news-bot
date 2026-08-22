#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
REPO = Path(
    os.environ.get("OWTV_REPO_ROOT", str(SCRIPT_PATH.parents[1]))
).resolve()
sys.path.insert(0, str(REPO))

try:
    from agents.gemini_diagnostics import (
        build_gemini_diagnostics,
        load_ledger,
        render_gemini_diagnostics_markdown,
    )
except Exception:
    build_gemini_diagnostics = None
    load_ledger = None
    render_gemini_diagnostics_markdown = None


LEDGER = REPO / "state" / "newsroom" / "gemini_call_ledger.jsonl"


def parse_ts(value: Any) -> datetime | None:
    try:
        if not value:
            return None
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def fmt_counter(counter: Counter) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in sorted(counter.items(), key=lambda x: str(x[0])))


def main() -> int:
    try:
        hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    except Exception:
        hours = 24

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    records: list[dict[str, Any]] = []

    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if not isinstance(r, dict):
                    continue
                ts = parse_ts(r.get("timestamp"))
                if ts and cutoff <= ts <= now:
                    records.append(r)
            except Exception:
                continue

    calls = [r for r in records if r.get("status") == "called"]
    failed = [r for r in records if r.get("status") == "failed"]
    avoided = [r for r in records if r.get("status") == "avoided"]

    calls_by_agent = Counter(str(r.get("agent") or "unknown") for r in calls)
    failed_by_agent = Counter(str(r.get("agent") or "unknown") for r in failed)
    calls_by_model = Counter(str(r.get("model") or "unknown") for r in calls)
    failed_by_model = Counter(str(r.get("model") or "unknown") for r in failed)
    avoided_by_agent = Counter(str(r.get("agent") or "unknown") for r in avoided)

    runs = {r.get("run_id") for r in records if r.get("run_id")}

    print("")
    print(f"## Gemini / AI Call and Usage Diagnostics (NON-AUTHORITATIVE) {hours}h")
    print(f"- Ledger file: {LEDGER}")
    print(f"- Ledger records: {len(records)}")
    print(f"- Runs with Gemini ledger activity: {len(runs)}")
    print(f"- Gemini calls total: {len(calls)}")
    print(f"- Gemini calls by agent: {fmt_counter(calls_by_agent)}")
    print(f"- Gemini calls by model: {fmt_counter(calls_by_model)}")
    print(f"- Gemini calls failed: {len(failed)}")
    print(f"- Gemini failures by agent: {fmt_counter(failed_by_agent)}")
    print(f"- Gemini failures by model: {fmt_counter(failed_by_model)}")
    print(f"- Gemini calls avoided total: {len(avoided)}")
    print(f"- Gemini calls avoided by agent: {fmt_counter(avoided_by_agent)}")

    if failed:
        print("- Recent Gemini failures:")
        for r in failed[-5:]:
            title = str(r.get("title") or "")[:90]
            model = r.get("model") or "unknown"
            agent = r.get("agent") or "unknown"
            result = str(r.get("result") or "")[:140].replace("\n", " ")
            print(f"  - {agent} | {model} | {title} | {result}")

    if avoided:
        print("- Recent avoided calls:")
        for r in avoided[-5:]:
            title = str(r.get("title") or "")[:90]
            agent = r.get("agent") or "unknown"
            reason = str(r.get("reason") or "")[:140].replace("\n", " ")
            print(f"  - {agent} | {title} | {reason}")

    print("")
    if build_gemini_diagnostics and load_ledger and render_gemini_diagnostics_markdown:
        try:
            detailed_records, warnings, metadata = load_ledger(
                LEDGER,
                since=cutoff,
                until=now,
                strict_bounded=True,
                return_metadata=True,
            )
            economic_available = bool(
                metadata["readable"]
                and metadata["malformed_rows"] == 0
                and metadata["undated_rows"] == 0
            )
            print(
                render_gemini_diagnostics_markdown(
                    build_gemini_diagnostics(
                        detailed_records,
                        economic_available=economic_available,
                    ),
                    hours=hours,
                ).rstrip()
            )
            if warnings:
                print("")
                print("### Gemini ledger warnings")
                for warning in warnings[:10]:
                    print(f"- {warning}")
        except Exception as exc:
            print(f"## Gemini / AI Detailed Ledger {hours}h")
            print(f"- warning: Gemini detailed ledger unavailable: {exc}")
    else:
        print(f"## Gemini / AI Detailed Ledger {hours}h")
        print("- warning: Gemini detailed ledger unavailable: diagnostics helper import failed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
