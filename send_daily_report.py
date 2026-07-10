from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from agents.gemini_diagnostics import build_email_gemini_summary, build_gemini_diagnostics, load_ledger

BOT_DIR = Path("/opt/owtv/wrestling-news-bot")
DAILY_JUDGMENT_LATEST_JSON = BOT_DIR / "state" / "reports" / "owtv_daily_editorial_judgment_latest.json"
DAILY_JUDGMENT_MARKDOWN_GLOB = "owtv_daily_editorial_judgment_24h_*.md"
TRANSLATION_QUALITY_LATEST_JSON = BOT_DIR / "state" / "reports" / "owtv_translation_quality_audit_latest.json"
TRANSLATION_QUALITY_MARKDOWN_GLOB = "owtv_translation_quality_audit_24h_*.md"


def generate_translation_quality_audit_24h() -> tuple[Path | None, Path | None, str | None]:
    """Generate the translation quality audit without blocking email delivery."""
    try:
        subprocess.run(
            [
                "python3",
                str(BOT_DIR / "scripts" / "translation_quality_audit.py"),
                "--hours",
                "24",
                "--limit",
                "25",
                "--output-dir",
                "reports",
            ],
            cwd=BOT_DIR,
            check=True,
        )
        markdown = newest_translation_quality_audit_markdown()
        latest_json = TRANSLATION_QUALITY_LATEST_JSON if TRANSLATION_QUALITY_LATEST_JSON.exists() else None
        print(f"[TRANSLATION QUALITY] generated {markdown or 'no markdown found'}")
        return markdown, latest_json, None
    except Exception as exc:
        warning = f"Translation Quality Audit skipped/error: {exc}"
        print(f"[TRANSLATION QUALITY] skipped/error {exc}")
        return None, TRANSLATION_QUALITY_LATEST_JSON if TRANSLATION_QUALITY_LATEST_JSON.exists() else None, warning


def newest_translation_quality_audit_markdown() -> Path | None:
    reports_dir = BOT_DIR / "reports"
    matches = [path for path in reports_dir.glob(TRANSLATION_QUALITY_MARKDOWN_GLOB) if path.is_file()]
    return max(matches, key=lambda path: (path.stat().st_mtime, path.name)) if matches else None


def _count_article_severities(articles: list[Any]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0, "technical": 0}
    for article in articles:
        if not isinstance(article, dict):
            continue
        severities = article.get("issue_severities")
        if isinstance(severities, dict):
            iterable = severities.values()
        else:
            iterable = article.get("severities", [])
        for severity in iterable if isinstance(iterable, list) else list(iterable):
            if severity in counts:
                counts[severity] += 1
    return counts


def _top_counts_from_articles(articles: list[Any], key: str, nested_key: str | None = None, technical_only: bool = False) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for article in articles:
        if not isinstance(article, dict):
            continue
        values = article.get(key, [])
        if isinstance(values, dict):
            values = list(values.values())
        if not isinstance(values, list):
            continue
        for value in values:
            if technical_only:
                code = value.get("code") if isinstance(value, dict) else str(value)
                severity = value.get("severity") if isinstance(value, dict) else ""
                if code != "image_placeholder_present" and severity != "technical":
                    continue
            if nested_key and isinstance(value, dict):
                value = value.get(nested_key) or value.get("code") or value.get("warning")
            if isinstance(value, dict):
                value = value.get("code") or value.get("warning") or value.get("message")
            if value:
                text = str(value)
                counts[text] = counts.get(text, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]


def _format_top_counts(items: list[tuple[str, int]]) -> str:
    return ", ".join(f"{name} ({count})" for name, count in items) if items else "none detected"


def translation_quality_audit_body_section(json_path: Path = TRANSLATION_QUALITY_LATEST_JSON, warning: str | None = None) -> str:
    """Build the compact email-body section from the latest translation audit JSON."""
    if not json_path.exists():
        return f"\nTRANSLATION QUALITY AUDIT\n- Warning: {warning or 'latest JSON not available'}\n"
    try:
        payload: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[TRANSLATION QUALITY] skipped/error JSON read failed: {exc}")
        return f"\nTRANSLATION QUALITY AUDIT\n- JSON read failed: {exc}\n"

    articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
    severity = _count_article_severities(articles)
    review_count = 0
    for article in articles:
        if not isinstance(article, dict):
            continue
        issue_severities = article.get("issue_severities")
        severity_values = issue_severities.values() if isinstance(issue_severities, dict) else []
        if article.get("needs_human_review") is True or any(sev in {"high", "medium"} for sev in severity_values):
            review_count += 1
    top_issues = _top_counts_from_articles(articles, "issues")
    technical_warnings = _top_counts_from_articles(articles, "alfred_warnings", "code", technical_only=True)
    if severity["high"]:
        attention = "Review high-severity translation issues before relying on the affected articles."
    elif severity["medium"]:
        attention = "Spot-check medium-severity translation issues when time allows."
    else:
        attention = "No high/medium translation issues detected in available artifacts."

    lines = [
        "",
        "TRANSLATION QUALITY AUDIT",
        f"- Articles inspected: {payload.get('count', len(articles))}",
        f"- Articles needing human review: {review_count}",
        f"- Severity: high {severity['high']} / medium {severity['medium']} / low {severity['low']} / technical {severity['technical']}",
        f"- Top issues: {_format_top_counts(top_issues)}",
        f"- Technical/media warnings: {_format_top_counts(technical_warnings)}",
        f"- Recommended attention: {attention}",
    ]
    if warning:
        lines.append(f"- Warning: {warning}")
    return "\n".join(lines) + "\n"


def append_translation_quality_audit_attachments(attachments: list[Path]) -> list[Path]:
    """Append generated translation audit markdown and latest JSON to an email attachment list."""
    markdown = newest_translation_quality_audit_markdown()
    for path in (markdown, TRANSLATION_QUALITY_LATEST_JSON if TRANSLATION_QUALITY_LATEST_JSON.exists() else None):
        if path and path.exists() and path not in attachments:
            attachments.append(path)
            print(f"[TRANSLATION QUALITY] attached {path}")
    return attachments


def translation_quality_audit_summary_24h() -> str:
    """Run the 24h translation audit and return its compact daily-email section."""
    _markdown, latest_json, warning = generate_translation_quality_audit_24h()
    return translation_quality_audit_body_section(latest_json or TRANSLATION_QUALITY_LATEST_JSON, warning=warning)


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
