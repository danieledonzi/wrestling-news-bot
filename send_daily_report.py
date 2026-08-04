from __future__ import annotations

import ast
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.gemini_diagnostics import build_email_gemini_summary, build_gemini_diagnostics, load_ledger

BOT_DIR = Path("/opt/owtv/wrestling-news-bot")
DAILY_JUDGMENT_LATEST_JSON = BOT_DIR / "state" / "reports" / "owtv_daily_editorial_judgment_latest.json"
DAILY_JUDGMENT_MARKDOWN_GLOB = "owtv_daily_editorial_judgment_24h_*.md"
TRANSLATION_QUALITY_LATEST_JSON = BOT_DIR / "state" / "reports" / "owtv_translation_quality_audit_latest.json"
TRANSLATION_QUALITY_MARKDOWN_GLOB = "owtv_translation_quality_audit_24h_*.md"
TRANSLATION_WARNING_LATEST_JSON = BOT_DIR / "state" / "reports" / "owtv_translation_warning_analysis_latest.json"
TRANSLATION_WARNING_MARKDOWN_GLOB = "owtv_translation_warning_analysis_24h_*.md"
TRANSLATION_QUALITY_BLOCKER_WARNING_CODES = {"untranslated_quote"}
TRANSLATION_QUALITY_CURRENT_FAILED = False


def generate_translation_quality_audit_24h() -> tuple[Path | None, Path | None, str | None]:
    """Generate the translation quality audit without blocking email delivery."""
    global TRANSLATION_QUALITY_CURRENT_FAILED
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
        TRANSLATION_QUALITY_CURRENT_FAILED = False
        print(f"[TRANSLATION QUALITY] generated {markdown or 'no markdown found'}")
        return markdown, latest_json, None
    except Exception as exc:
        TRANSLATION_QUALITY_CURRENT_FAILED = True
        warning = f"Translation Quality Audit skipped/error: {exc}"
        print(f"[TRANSLATION QUALITY] skipped/error {exc}")
        return None, None, warning


def newest_translation_quality_audit_markdown() -> Path | None:
    reports_dir = BOT_DIR / "reports"
    matches = [path for path in reports_dir.glob(TRANSLATION_QUALITY_MARKDOWN_GLOB) if path.is_file()]
    return max(matches, key=lambda path: (path.stat().st_mtime, path.name)) if matches else None


def newest_translation_warning_analysis_markdown() -> Path | None:
    """Return only the Markdown paired with the current latest JSON."""
    if not TRANSLATION_WARNING_LATEST_JSON.exists():
        return None
    try:
        payload = json.loads(TRANSLATION_WARNING_LATEST_JSON.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        stamp = generated_at.strftime("%Y%m%d_%H%M%S")
    except Exception:
        return None
    path = BOT_DIR / "reports" / f"owtv_translation_warning_analysis_24h_{stamp}.md"
    return path if path.is_file() else None


def _write_translation_warning_failure(audit_json: Path | None, exc: Exception) -> tuple[Path | None, Path | None]:
    """Replace stale latest state with a controlled current-run failure report."""
    try:
        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%d_%H%M%S")
        error = f"execution_failed:{type(exc).__name__}:{exc}"
        payload = {
            "schema_version": "v95.16a-1", "generated_at": now.isoformat(), "hours": 24,
            "source_audit_path": str(audit_json) if audit_json is not None else None,
            "source_audit_generated_at": None, "total_investigations": 0,
            "status_counts": {name: 0 for name in ("insufficient_material", "not_reproduced", "possible_false_positive", "reproduced", "technical")},
            "severity_counts": {}, "warning_code_counts": {}, "articles_with_investigations": 0,
            "investigations": [], "warnings": [], "errors": [error],
        }
        reports = BOT_DIR / "reports"
        latest_dir = TRANSLATION_WARNING_LATEST_JSON.parent
        reports.mkdir(parents=True, exist_ok=True)
        latest_dir.mkdir(parents=True, exist_ok=True)
        json_path = reports / f"owtv_translation_warning_analysis_24h_{stamp}.json"
        markdown = reports / f"owtv_translation_warning_analysis_24h_{stamp}.md"
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        json_path.write_text(text, encoding="utf-8")
        TRANSLATION_WARNING_LATEST_JSON.write_text(text, encoding="utf-8")
        markdown.write_text(
            "# OWTV Translation Warning Analysis (24h)\n\n"
            f"Generated: {payload['generated_at']}\n\n## Summary\n\n- Investigations: 0\n\n"
            f"## Diagnostic errors\n\n- {error}\n",
            encoding="utf-8",
        )
        return markdown, TRANSLATION_WARNING_LATEST_JSON
    except Exception as artifact_exc:
        print(f"[WARNING INVESTIGATION] failure artifact write error: {artifact_exc}")
        return None, None


def generate_translation_warning_analysis_24h(audit_json: Path) -> tuple[Path | None, Path | None, str | None]:
    """Run warning investigation for this audit only; never return stale output on failure."""
    try:
        subprocess.run([
            "python3", "-m", "scripts.translation_warning_analysis",
            "--hours", "24", "--audit-json", str(audit_json),
        ], cwd=BOT_DIR, check=True)
        markdown = newest_translation_warning_analysis_markdown()
        latest = TRANSLATION_WARNING_LATEST_JSON if TRANSLATION_WARNING_LATEST_JSON.exists() else None
        print(f"[WARNING INVESTIGATION] generated {markdown or 'no markdown found'}")
        return markdown, latest, None
    except Exception as exc:
        warning = f"Automatic Warning Investigation skipped/error: {exc}"
        print(f"[WARNING INVESTIGATION] skipped/error {exc}")
        markdown, latest = _write_translation_warning_failure(audit_json, exc)
        return markdown, latest, warning


def translation_warning_analysis_body_section(json_path: Path | None, warning: str | None = None) -> str:
    if json_path is None or not json_path.exists():
        return "\nAUTOMATIC WARNING INVESTIGATION\n- Diagnostic warning: %s\n" % (warning or "current analysis unavailable")
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return "\nAUTOMATIC WARNING INVESTIGATION\n- Diagnostic warning: JSON read failed: %s\n" % exc
    counts = payload.get("status_counts", {})
    top_codes = sorted(payload.get("warning_code_counts", {}).items(), key=lambda item: (-int(item[1]), item[0]))[:3]
    lines = ["", "AUTOMATIC WARNING INVESTIGATION", "- Investigations: %s" % payload.get("total_investigations", 0), "- Reproduced: %s" % counts.get("reproduced", 0), "- Possible false positives: %s" % counts.get("possible_false_positive", 0), "- Insufficient material: %s" % counts.get("insufficient_material", 0), "- Technical: %s" % counts.get("technical", 0), "- Top warning codes: %s" % (_format_top_counts(top_codes))]
    priority = {"blocker": 5, "high": 4, "medium": 3, "low": 2, "warning": 1, "technical": 0}
    investigations = sorted((item for item in payload.get("investigations", []) if isinstance(item, dict)), key=lambda item: (-priority.get(str(item.get("original_severity", "warning")), 1), str(item.get("title", ""))))
    for item in investigations[:3]:
        evidence = "; ".join(str(x.get("excerpt", "")) for x in item.get("evidence", []) if isinstance(x, dict)) or "none"
        lines.append("- %s: %s / %s — %s — %s" % (item.get("title") or item.get("article_key"), item.get("warning_code"), item.get("investigation_status"), evidence[:180], item.get("recommended_action", "")))
    diagnostic_errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    if diagnostic_errors:
        lines.append("- Diagnostic warning: " + "; ".join(str(value) for value in diagnostic_errors))
    if warning:
        lines.append("- Diagnostic warning: %s" % warning)
    return "\n".join(lines) + "\n"


def _parse_translation_quality_alfred_warning(warning: Any) -> Any:
    if isinstance(warning, dict):
        return warning
    if not isinstance(warning, str):
        return None
    raw = warning.strip()
    if not raw:
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _translation_quality_alfred_warning_code(warning: Any) -> str:
    parsed = _parse_translation_quality_alfred_warning(warning)
    if isinstance(parsed, dict):
        return str(parsed.get("code") or "").strip()
    raw = str(warning or "").strip()
    return raw.split(":", 1)[0].strip() if raw else ""


def _translation_quality_alfred_warning_severity(warning: Any) -> str:
    parsed = _parse_translation_quality_alfred_warning(warning)
    if isinstance(parsed, dict):
        severity = str(parsed.get("severity") or "").strip().lower()
        if severity:
            return severity
    if "blocker" in str(warning or "").lower():
        return "blocker"
    if _translation_quality_alfred_warning_code(warning) == "image_placeholder_present":
        return "technical"
    return "warning"


def _article_needs_translation_human_review(article: dict[str, Any]) -> bool:
    if article.get("needs_human_review") is True:
        return True
    issue_severities = article.get("issue_severities")
    severity_values = issue_severities.values() if isinstance(issue_severities, dict) else []
    if any(str(sev).lower() in {"high", "medium"} for sev in severity_values):
        return True
    warnings = article.get("alfred_warnings", [])
    if not isinstance(warnings, list):
        warnings = list(warnings.values()) if isinstance(warnings, dict) else [warnings]
    for warning in warnings:
        if _translation_quality_alfred_warning_severity(warning) == "blocker":
            return True
        if _translation_quality_alfred_warning_code(warning) in TRANSLATION_QUALITY_BLOCKER_WARNING_CODES:
            return True
    return False


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
                code = _translation_quality_alfred_warning_code(value)
                severity = _translation_quality_alfred_warning_severity(value)
                if code != "image_placeholder_present" and severity != "technical":
                    continue
            if nested_key:
                value = _translation_quality_alfred_warning_code(value) if nested_key == "code" else value
            if isinstance(value, dict):
                value = value.get("code") or value.get("warning") or value.get("message")
            if value:
                text = str(value)
                counts[text] = counts.get(text, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:3]


def _format_top_counts(items: list[tuple[str, int]]) -> str:
    return ", ".join(f"{name} ({count})" for name, count in items) if items else "none detected"


def translation_quality_audit_body_section(json_path: Path | None = TRANSLATION_QUALITY_LATEST_JSON, warning: str | None = None) -> str:
    """Build the compact email-body section from the latest translation audit JSON."""
    if json_path is None or not json_path.exists():
        return f"\nTRANSLATION QUALITY AUDIT\n- Warning: {warning or 'latest JSON not available'}\n"
    try:
        payload: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[TRANSLATION QUALITY] skipped/error JSON read failed: {exc}")
        return f"\nTRANSLATION QUALITY AUDIT\n- JSON read failed: {exc}\n"

    articles = payload.get("articles") if isinstance(payload.get("articles"), list) else []
    severity = _count_article_severities(articles)
    review_count = sum(
        1
        for article in articles
        if isinstance(article, dict) and _article_needs_translation_human_review(article)
    )
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
    if not TRANSLATION_QUALITY_CURRENT_FAILED:
        markdown = newest_translation_quality_audit_markdown()
        for path in (markdown, TRANSLATION_QUALITY_LATEST_JSON if TRANSLATION_QUALITY_LATEST_JSON.exists() else None):
            if path and path.exists() and path not in attachments:
                attachments.append(path)
                print(f"[TRANSLATION QUALITY] attached {path}")
    return append_translation_warning_analysis_attachments(attachments)


def append_translation_warning_analysis_attachments(attachments: list[Path]) -> list[Path]:
    """Append the full investigation artifacts while retaining audit attachments."""
    markdown = newest_translation_warning_analysis_markdown()
    for path in (markdown, TRANSLATION_WARNING_LATEST_JSON if TRANSLATION_WARNING_LATEST_JSON.exists() else None):
        if path and path.exists() and path not in attachments:
            attachments.append(path)
            print(f"[WARNING INVESTIGATION] attached {path}")
    return attachments


def translation_quality_audit_summary_24h() -> str:
    """Run the 24h translation audit and return its compact daily-email section."""
    audit_result = generate_translation_quality_audit_24h()
    latest_json, warning = audit_result[1], audit_result[2]
    audit_section = translation_quality_audit_body_section(latest_json, warning=warning)
    _markdown, analysis_json, analysis_warning = _analysis_after_audit(audit_result)
    return audit_section + translation_warning_analysis_body_section(analysis_json, analysis_warning)


def _analysis_after_audit(audit_result: tuple[Path | None, Path | None, str | None]) -> tuple[Path | None, Path | None, str | None]:
    """Run analysis or register one current failure state for an unavailable audit."""
    audit_json, audit_warning = audit_result[1], audit_result[2]
    if audit_warning or audit_json is None:
        failure = RuntimeError(audit_warning or "current audit JSON unavailable")
        markdown, latest = _write_translation_warning_failure(audit_json, failure)
        return markdown, latest, str(failure)
    return generate_translation_warning_analysis_24h(audit_json)


def generate_daily_diagnostics_24h() -> dict[str, tuple[Path | None, Path | None, str | None]]:
    """Run the diagnostic chain in its required order; every stage is non-blocking."""
    audit_result = generate_translation_quality_audit_24h()
    analysis_result = _analysis_after_audit(audit_result)
    judgment_result = generate_daily_editorial_judgment_24h()
    return {"translation_quality_audit": audit_result, "translation_warning_analysis": analysis_result, "daily_editorial_judgment": judgment_result}


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


def daily_editorial_judgment_body_section(
    json_path: Path = DAILY_JUDGMENT_LATEST_JSON,
    warning: str | None = None,
) -> str:
    """Build the authoritative compact editorial section for the daily email."""
    if not json_path.exists():
        return "\nSINTESI EDITORIALE AUTOREVOLE\n- Stato: non disponibile.\n"
    try:
        payload: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[DAILY JUDGMENT] skipped/error JSON read failed: {exc}")
        return f"\nSINTESI EDITORIALE AUTOREVOLE\n- JSON non leggibile: {exc}\n"

    daily_numbers = payload.get("daily_numbers") if isinstance(payload.get("daily_numbers"), dict) else {}
    canonical = daily_numbers.get("canonical_metrics") if isinstance(daily_numbers.get("canonical_metrics"), dict) else {}
    menzo = canonical.get("menzo") if isinstance(canonical.get("menzo"), dict) else {}
    andrea = canonical.get("andrea") if isinstance(canonical.get("andrea"), dict) else {}
    alfred = canonical.get("alfred") if isinstance(canonical.get("alfred"), dict) else {}
    analysis = payload.get("translation_warning_analysis") if isinstance(payload.get("translation_warning_analysis"), dict) else {}
    analysis_available = analysis.get("available")
    if analysis_available is None:
        analysis_available = bool(analysis) and any(
            key in analysis
            for key in ("reproduced", "insufficient_material", "possible_false_positive", "technical")
        )
    warning_value = lambda key: analysis.get(key, 0) if analysis_available else "n.d."

    ratio = menzo.get("handoff_to_publication_ratio")
    ratio_label = f"{ratio:.1%}" if isinstance(ratio, (int, float)) else "non disponibile"

    andrea_events = andrea.get("events") if isinstance(andrea.get("events"), dict) else {}
    andrea_reasons = andrea.get("exception_reasons") if isinstance(andrea.get("exception_reasons"), dict) else {}
    andrea_available = andrea.get("available") is True
    if andrea_available:
        andrea_coverage = f"{andrea.get('covered_runs', 0)}/{andrea.get('total_runs', 0)} run"
        andrea_counts = "{}/{}/{}/{}".format(
            andrea_events.get("checked", 0),
            andrea_events.get("passed", 0),
            andrea_events.get("passed_with_exception", 0),
            andrea_events.get("blocked", 0),
        )
        reasons_label = ", ".join(
            f"{name} ({count})"
            for name, count in sorted(andrea_reasons.items(), key=lambda item: (-int(item[1]), item[0]))
        ) or "nessuna"
    else:
        andrea_coverage = "non ancora disponibile"
        andrea_counts = "n.d."
        reasons_label = "n.d."

    lines = [
        "",
        "SINTESI EDITORIALE AUTOREVOLE",
        f"- Giudizio: {payload.get('judgment', 'n.d.')}",
        f"- Tipo di giornata: {payload.get('day_type', 'n.d.')}",
        f"- Sintesi: {payload.get('summary', 'n.d.')}",
        f"- Pubblicazioni uniche: {daily_numbers.get('news_published', 'n.d.')} news / {daily_numbers.get('reports_published', 'n.d.')} report",
        f"- Menzo candidati unici actionable: {menzo.get('unique_actionable_candidates', 'n.d.')}",
        f"- Menzo handoff unici / pubblicazioni finali uniche: {menzo.get('unique_downstream_handoffs', 'n.d.')}/{menzo.get('unique_final_publications', 'n.d.')}",
        f"- Rapporto handoff/pubblicazioni Menzo: {ratio_label}",
        f"- Warning confermati / materiale insufficiente / possibili falsi positivi / tecnici: {warning_value('reproduced')}/{warning_value('insufficient_material')}/{warning_value('possible_false_positive')}/{warning_value('technical')}",
        f"- Alfred articoli revisionati / con warning / blocker finali unici: {alfred.get('articles_reviewed', 'n.d.')}/{alfred.get('articles_with_warnings', 'n.d.')}/{alfred.get('final_blockers', 'n.d.')}",
        f"- Andrea copertura: {andrea_coverage}",
        f"- Andrea checked/passed/con eccezione/blocked: {andrea_counts}",
        f"- Ragioni eccezioni Andrea: {reasons_label}",
    ]
    if warning:
        lines.append(f"- Avviso diagnostico: {warning}")
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
