from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.gemini_diagnostics import (
    MENZO_DECISIONS_FILES,
    build_gemini_diagnostics,
    load_ledger,
    parse_dt,
    render_gemini_diagnostics_markdown,
)

DETAILED_LEDGER_HEADING = "## Gemini / AI Detailed Ledger 24h"
COST_LEDGER_HEADING = "## Gemini / AI Cost Ledger 24h"


def load_operational_menzo_context(paths: tuple[Path, ...] = MENZO_DECISIONS_FILES) -> dict[str, Any] | None:
    """Best-effort Menzo context for operational report diagnostics."""
    for path in paths:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            continue
    return None


def render_gemini_detailed_ledger_24h(
    *,
    ledger_path: Path | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    now: datetime | None = None,
    menzo_context: dict[str, Any] | None = None,
) -> str:
    """Render the detailed Gemini diagnostics section without failing report generation."""
    try:
        if ledger_path is None:
            records, warnings = load_ledger(since=since, until=until, now=now)
        else:
            records, warnings = load_ledger(ledger_path, since=since, until=until, now=now)
        context = menzo_context if menzo_context is not None else load_operational_menzo_context()
        markdown = render_gemini_diagnostics_markdown(build_gemini_diagnostics(records, menzo_context=context)).rstrip()
        if warnings:
            markdown += "\n\n### Gemini ledger warnings\n" + "\n".join(f"- {w}" for w in warnings[:10])
        return markdown + "\n"
    except Exception as exc:
        return f"{DETAILED_LEDGER_HEADING}\n\n- warning: Gemini detailed ledger unavailable: {exc}\n"


def add_gemini_detailed_ledger_to_report(
    report_markdown: str,
    *,
    ledger_path: Path | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    now: datetime | None = None,
    menzo_context: dict[str, Any] | None = None,
) -> str:
    """Insert detailed Gemini diagnostics immediately after the aggregate cost section."""
    if DETAILED_LEDGER_HEADING in report_markdown:
        return report_markdown

    detailed = render_gemini_detailed_ledger_24h(
        ledger_path=ledger_path,
        since=since,
        until=until,
        now=now,
        menzo_context=menzo_context,
    ).rstrip()

    start = report_markdown.find(COST_LEDGER_HEADING)
    if start == -1:
        suffix = "" if report_markdown.endswith("\n") else "\n"
        return report_markdown + suffix + "\n" + detailed + "\n"

    next_section = report_markdown.find("\n## ", start + len(COST_LEDGER_HEADING))
    insert_at = len(report_markdown) if next_section == -1 else next_section + 1
    before = report_markdown[:insert_at].rstrip()
    after = report_markdown[insert_at:].lstrip("\n")
    return before + "\n\n" + detailed + ("\n" + after if after else "\n")


def _parse_arg_dt(value: str | None) -> datetime | None:
    return parse_dt(value) if value else None


if __name__ == "__main__":
    # No args: keep the historical behavior and print only the detailed section.
    # With a report path: update that markdown file in place for VPS shell scripts.
    if len(sys.argv) == 1:
        print(render_gemini_detailed_ledger_24h(), end="")
    else:
        report_path = Path(sys.argv[1])
        since = _parse_arg_dt(sys.argv[2]) if len(sys.argv) > 2 else None
        until = _parse_arg_dt(sys.argv[3]) if len(sys.argv) > 3 else None
        text = report_path.read_text(encoding="utf-8")
        report_path.write_text(add_gemini_detailed_ledger_to_report(text, since=since, until=until), encoding="utf-8")
