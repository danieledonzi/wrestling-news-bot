from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from agents.gemini_diagnostics import build_email_gemini_summary, build_gemini_diagnostics, load_ledger

BOT_DIR = Path("/opt/owtv/wrestling-news-bot")
DAILY_JUDGMENT_LATEST_JSON = BOT_DIR / "state" / "reports" / "owtv_daily_editorial_judgment_latest.json"
DAILY_JUDGMENT_MARKDOWN_GLOB = "owtv_daily_editorial_judgment_24h_*.md"


def gemini_email_summary_24h() -> str:
    records, _warnings = load_ledger()
    return build_email_gemini_summary(build_gemini_diagnostics(records))


def generate_daily_editorial_judgment_24h() -> tuple[Path | None, Path | None, str | None]:
    """Generate the VPS daily editorial judgment output without blocking email delivery."""
    try:
        subprocess.run(
            [
                "/usr/bin/python3",
                str(BOT_DIR / "scripts" / "daily_editorial_judgment.py"),
                "--hours",
                "24",
            ],
            cwd=BOT_DIR,
            check=True,
        )
        markdown = newest_daily_editorial_judgment_markdown()
        latest_json = DAILY_JUDGMENT_LATEST_JSON if DAILY_JUDGMENT_LATEST_JSON.exists() else None
        print(f"[DAILY JUDGMENT] generated {markdown or 'no markdown found'}")
        return markdown, latest_json, None
    except Exception as exc:
        warning = f"Daily Editorial Judgment skipped/error: {exc}"
        print(f"[DAILY JUDGMENT] skipped/error {exc}")
        return None, DAILY_JUDGMENT_LATEST_JSON if DAILY_JUDGMENT_LATEST_JSON.exists() else None, warning


def newest_daily_editorial_judgment_markdown() -> Path | None:
    reports_dir = BOT_DIR / "reports"
    matches = [path for path in reports_dir.glob(DAILY_JUDGMENT_MARKDOWN_GLOB) if path.is_file()]
    return max(matches, key=lambda path: (path.stat().st_mtime, path.name)) if matches else None


def daily_editorial_judgment_body_section(json_path: Path = DAILY_JUDGMENT_LATEST_JSON) -> str:
    """Build the compact email-body section from the latest judgment JSON."""
    if not json_path.exists():
        return ""
    try:
        payload: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[DAILY JUDGMENT] skipped/error JSON read failed: {exc}")
        return f"\nDAILY EDITORIAL JUDGMENT\n- JSON read failed: {exc}\n"

    daily_numbers = payload.get("daily_numbers") if isinstance(payload.get("daily_numbers"), dict) else {}
    alfred = daily_numbers.get("alfred")
    if not isinstance(alfred, dict):
        alfred = {}
    warnings = alfred.get("warnings")
    blockers = alfred.get("blockers")
    if warnings is None:
        warnings = daily_numbers.get("alfred_warnings")
    if blockers is None:
        blockers = daily_numbers.get("alfred_blockers")
    gemini_total = payload.get("gemini_3_5_called_total")
    if gemini_total is None:
        gemini_total = daily_numbers.get("gemini_3_5_called_total")

    lines = [
        "",
        "DAILY EDITORIAL JUDGMENT",
        f"- judgment: {payload.get('judgment', 'n.d.')}",
        f"- day_type: {payload.get('day_type', 'n.d.')}",
        f"- summary: {payload.get('summary', 'n.d.')}",
        f"- news_published: {daily_numbers.get('news_published', 'n.d.')}",
        f"- reports_published: {daily_numbers.get('reports_published', 'n.d.')}",
        f"- Alfred warnings/blockers: {warnings if warnings is not None else 'n.d.'}/{blockers if blockers is not None else 'n.d.'}",
        f"- gemini_3_5_called_total: {gemini_total if gemini_total is not None else 'n.d.'}",
    ]
    return "\n".join(lines) + "\n"


def append_daily_editorial_judgment_attachments(attachments: list[Path]) -> list[Path]:
    """Append generated daily judgment markdown and latest JSON to an email attachment list."""
    markdown = newest_daily_editorial_judgment_markdown()
    for path in (markdown, DAILY_JUDGMENT_LATEST_JSON if DAILY_JUDGMENT_LATEST_JSON.exists() else None):
        if path and path.exists() and path not in attachments:
            attachments.append(path)
            print(f"[DAILY JUDGMENT] attached {path}")
    return attachments


from scripts.daily_editorial_judgment import build_report as build_daily_editorial_judgment, email_summary as daily_editorial_judgment_email_summary, generate_daily_editorial_judgment_outputs, generate_daily_editorial_judgment_report, load_inputs as load_daily_editorial_judgment_inputs


def daily_editorial_judgment_summary_24h() -> str:
    """Compact newsroom summary for the 12:00 daily email body.

    VPS note: /opt/owtv/send_daily_report.py is outside the git checkout, so it
    must call this repo implementation (or the stable CLI
    `python3 /opt/owtv/wrestling-news-bot/scripts/daily_editorial_judgment.py --hours 24`)
    to attach the latest judgment output generated from /opt/owtv/reports.
    """
    return daily_editorial_judgment_email_summary(build_daily_editorial_judgment(load_daily_editorial_judgment_inputs()))


def daily_editorial_judgment_attachment_24h() -> str:
    """Generate the markdown/JSON report pair and return the markdown path for email attachment/reference."""
    return str(generate_daily_editorial_judgment_outputs()["markdown"])


if __name__ == "__main__":
    print(gemini_email_summary_24h())
