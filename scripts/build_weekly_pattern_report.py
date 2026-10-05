#!/usr/bin/env python3
"""TQ-1 rolling 168h patterns from one unique publication population.

Read-only toward production state: writes diagnostic reports only, no network or AI.
Never sums overlapping daily reports or replaces their latest audit.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import translation_quality_audit as audit
from scripts import translation_warning_analysis as analysis
from scripts.translation_quality_rules import POLICY_VERSION

LATEST_NAME = "owtv_weekly_quality_patterns_latest.json"


def build_patterns(payload: dict[str, Any], investigation: dict[str, Any]) -> dict[str, Any]:
    coverage = payload.get("coverage", {})
    errors = list(investigation.get("errors", []))
    articles = payload.get("articles", [])
    if payload.get("hours") != 168:
        errors.append("unsupported_audit_window")
    if coverage.get("publication_authority_available") is not True:
        errors.append("publication_population_unavailable")
    if coverage.get("detailed_rows_returned") != coverage.get("audit_population_total"):
        errors.append("audit_population_truncated")
    keys = [str(a.get("key") or "") for a in articles]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        errors.append("article_identity_missing_or_duplicated")
    groups = defaultdict(list)
    for item in investigation.get("investigations", []):
        groups[item["warning_code"]].append(item)
    patterns = []
    for code, rows in sorted(groups.items()):
        unique = {row["article_key"]: row for row in rows}
        rows = list(unique.values())
        counts = Counter(row["investigation_status"] for row in rows)
        evaluated = counts["reproduced"] + counts["not_reproduced"]
        patterns.append({
            "warning_code": code, "articles_unique": len(rows), "status_counts": dict(counts),
            "evaluated_articles": evaluated,
            "reproduction_rate": counts["reproduced"] / evaluated if evaluated else None,
            "possible_false_positive_candidates": counts["possible_false_positive"],
            "confirmed_false_positive_rate": None,
            "recurring": len(rows) >= 3,
            "recommended_action": "review_pattern" if len(rows) >= 3 and counts["technical"] != len(rows) else "observe",
            "unavailable_reason_counts": dict(Counter(row["unavailable_reason"] for row in rows if row.get("unavailable_reason"))),
            "examples": rows[:3],
        })
    generated = payload.get("generated_at")
    until = audit.parse_dt(payload.get("window_until") or generated)
    return {
        "schema_version": "owtv_tq1_weekly_patterns_v1", "policy_version": POLICY_VERSION,
        "generated_at": generated, "hours": 168,
        "window_since": payload.get("window_since") or ((until - timedelta(hours=168)).isoformat() if until else None),
        "window_until": payload.get("window_until") or generated,
        "available": not errors,
        "population_source": "translation_quality_audit.canonical_publication_population",
        "publication_population_unique": coverage.get("authoritative_total") if not errors else None,
        "material_coverage": coverage,
        "articles_with_investigations": investigation.get("articles_with_investigations", 0),
        "investigations_unique": investigation.get("total_investigations", 0),
        "status_counts": investigation.get("status_counts", {}),
        "patterns": sorted(patterns, key=lambda row: (-row["articles_unique"], row["warning_code"])),
        "warnings": ["Rule reproduction is not a confirmed editorial error; false-positive rates require human labels.",
                     "Published news population only; blocked candidates and report-show material are outside this audit's canonical coverage."],
        "errors": errors,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# OWTV Weekly Translation Quality Patterns (168h)", "",
             "Generated: %s" % report["generated_at"], "",
             "- Available: %s" % report["available"],
             "- Unique published news: %s" % report.get("publication_population_unique"),
             "- Unique article/code investigations: %s" % report.get("investigations_unique", 0), "",
             "| Code | Unique articles | Reproduced | Not reproduced | Possible FP | Unavailable | Technical |", "|---|---:|---:|---:|---:|---:|---:|"]
    for p in report.get("patterns", []):
        c = p["status_counts"]
        lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (p["warning_code"], p["articles_unique"], c.get("reproduced", 0), c.get("not_reproduced", 0), c.get("possible_false_positive", 0), c.get("insufficient_material", 0), c.get("technical", 0)))
    lines += ["", "## Review queue", ""]
    for p in report.get("patterns", []):
        if p["recommended_action"] != "review_pattern":
            continue
        lines += ["### %s" % p["warning_code"], "",
                  "- Unavailable reasons: %s" % json.dumps(p["unavailable_reason_counts"], sort_keys=True)]
        for item in p["examples"]:
            lines.append("- %s (%s): %s; %s" % (item.get("title") or item["article_key"], item["article_key"], item["investigation_status"], json.dumps(item.get("evidence", []), ensure_ascii=False)))
        lines.append("")
    lines += ["## Limits", ""] + ["- %s" % w for w in report.get("warnings", [])]
    if report.get("errors"):
        lines += ["", "## Diagnostic errors", ""] + ["- %s" % e for e in report["errors"]]
    return "\n".join(lines) + "\n"


def generate_outputs(root: Path = ROOT, output_dir: Path | None = None,
                     state_dir: Path | None = None) -> dict[str, Path]:
    output = output_dir or root / "reports"
    state = state_dir or root / "state/reports"
    output.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    # Separate weekly audit latest; the daily pipeline keeps its exact 24h input.
    audit_path = state / "owtv_translation_quality_audit_weekly_latest.json"
    try:
        payload, audit_path, _ = audit.build_audit(168, None, output, root, latest_path=audit_path)
        investigated = analysis.build_analysis(audit_path, 168)
        report = build_patterns(payload, investigated)
    except Exception as exc:
        report = {"schema_version": "owtv_tq1_weekly_patterns_v1", "policy_version": POLICY_VERSION,
                  "generated_at": datetime.now(timezone.utc).isoformat(), "hours": 168, "available": False,
                  "publication_population_unique": None, "patterns": [], "warnings": [],
                  "errors": ["execution_failed:%s:%s" % (type(exc).__name__, exc)]}
    stamp = audit.parse_dt(report["generated_at"]).strftime("%Y%m%d_%H%M%S")
    latest = state / LATEST_NAME
    json_path = output / ("owtv_weekly_quality_patterns_168h_%s.json" % stamp)
    md_path = output / ("owtv_weekly_quality_patterns_168h_%s.md" % stamp)
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    json_path.write_text(text, encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "latest_json": latest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args()
    print(json.dumps({k: str(v) for k, v in generate_outputs(args.root, args.output_dir, args.state_dir).items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
