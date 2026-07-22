#!/usr/bin/env python3
"""Deterministic, diagnostic-only investigation of translation audit warnings."""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Pattern, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import translation_quality_audit as audit

LATEST_AUDIT = ROOT / "state/reports/owtv_translation_quality_audit_latest.json"
LATEST_ANALYSIS = ROOT / "state/reports/owtv_translation_warning_analysis_latest.json"
STATUSES = {"reproduced", "not_reproduced", "possible_false_positive", "insufficient_material", "technical"}
TECHNICAL_CODES = set(audit.TECHNICAL_ALFRED_WARNINGS) | {"image_missing", "media_missing", "broken_image", "image_error"}
FINAL_RULES: Dict[str, Pattern[str]] = {
    "betting_odds_article_published": audit.BETTING_RE,
    "source_intro_leaked": audit.SOURCE_INTRO_RE,
    "source_promo_leaked": audit.SOURCE_PROMO_RE,
    "official_title_translated": audit.OFFICIAL_TITLE_RE,
    "mojibake_or_broken_accents": audit.MOJIBAKE_RE,
    "untranslated_quote_or_residual_english": audit.ENGLISH_RESIDUAL_RE,
    "wrestling_lexicon_issue": audit.WRESTLING_LEXICON_RE,
    "ai_style_filler": audit.AI_FILLER_RE,
}
COMPARATIVE_CODES = {"paragraph_count_drop", "published_text_too_short_vs_original", "possible_release_mistranslation", "possible_match_mistranslation"}


def _warning(value: Any) -> Tuple[str, Optional[str]]:
    parsed = value
    if isinstance(value, str):
        raw = value.strip()
        for loader in (json.loads, ast.literal_eval):
            try:
                candidate = loader(raw)
                if isinstance(candidate, dict):
                    parsed = candidate
                    break
            except Exception:
                pass
    if isinstance(parsed, dict):
        code = parsed.get("code") or parsed.get("warning") or parsed.get("issue") or parsed.get("message")
        severity = parsed.get("severity")
        return str(code or "").strip(), str(severity).lower() if severity else None
    return str(parsed or "").split(":", 1)[0].strip(), None


def _values(value: Any) -> Iterable[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.keys()
    return [value] if value not in (None, "") else []


def _excerpt(text: str, match: re.Match[str], radius: int = 70) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    excerpt = text[start:end].replace("\n", " ").strip()
    return ("…" if start else "") + excerpt + ("…" if end < len(text) else "")


def _material(article: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = article.get(key)
        if isinstance(value, str) and value.strip():
            return audit.html_stats(value)["text"]
    return ""


def _article_key(article: Dict[str, Any]) -> str:
    return str(article.get("key") or article.get("article_key") or article.get("source_url") or article.get("wp_link") or article.get("title") or "unknown")


def investigate_article(article: Dict[str, Any]) -> List[Dict[str, Any]]:
    instances: Dict[str, Dict[str, Any]] = {}
    severity_map = article.get("issue_severities") if isinstance(article.get("issue_severities"), dict) else {}
    false_positive_codes = {_warning(v)[0] for v in _values(article.get("possible_false_positive_warnings"))}
    inputs = (("issues", "audit"), ("issue_severities", "audit"), ("alfred_warnings", "alfred"), ("possible_false_positive_warnings", "possible_false_positive"))
    for field, origin in inputs:
        for value in _values(article.get(field)):
            code, supplied_severity = _warning(value)
            if not code:
                continue
            item = instances.setdefault(code, {"origins": set(), "severities": []})
            item["origins"].add(origin)
            severity = supplied_severity or severity_map.get(code) or audit.ISSUE_SEVERITY.get(code)
            if severity:
                item["severities"].append(str(severity).lower())

    final_text = _material(article, audit.FINAL_PUBLISHED_MATERIAL_KEYS) or str(article.get("published_text") or "")
    source_text = _material(article, audit.SOURCE_MATERIAL_KEYS) or str(article.get("original_text") or "")
    candidate_text = _material(article, audit.TRANSLATED_CANDIDATE_KEYS) or str(article.get("translated_candidate_text") or "")
    final_available = bool(article.get("final_published_material_available", article.get("published_material_available", bool(final_text)))) and bool(final_text)
    source_available = bool(article.get("source_material_available", bool(source_text))) and bool(source_text)
    candidate_available = bool(article.get("translated_candidate_material_available", bool(candidate_text))) and bool(candidate_text)
    comparative = bool(article.get("comparative_pair_available", source_available and final_available))
    results: List[Dict[str, Any]] = []
    rank = {"blocker": 5, "high": 4, "medium": 3, "low": 2, "warning": 1, "technical": 0}
    for code, meta in instances.items():
        severities = meta["severities"] or [audit.ISSUE_SEVERITY.get(code, "warning")]
        severity = max(severities, key=lambda value: rank.get(value, 1))
        evidence: List[Dict[str, str]] = []
        if code in false_positive_codes:
            status, reason = "possible_false_positive", "The audit explicitly marked this warning as a possible false positive."
        elif code in TECHNICAL_CODES or severity == "technical" or any(token in code for token in ("image", "media")):
            status, reason = "technical", "This is a technical/media-only warning; no editorial conclusion is drawn."
        elif code in COMPARATIVE_CODES and not comparative:
            status, reason = "insufficient_material", "Authoritative source and final published material are both required for this comparison."
        elif code in FINAL_RULES and not final_available:
            status, reason = "insufficient_material", "Authoritative final published material is unavailable."
        elif code in FINAL_RULES:
            match = FINAL_RULES[code].search(final_text)
            if match:
                status, reason = "reproduced", "The existing audit rule directly matches the available final published material."
                evidence.append({"material": "final_published", "excerpt": _excerpt(final_text, match)})
            else:
                status, reason = "not_reproduced", "The authoritative final material is available and the existing audit rule does not match it."
        else:
            status, reason = "insufficient_material", "No deterministic local reproduction rule with the required authoritative material is available for this warning."
        results.append({
            "article_key": _article_key(article), "title": str(article.get("title") or ""),
            "source_url": str(article.get("source_url") or ""), "wp_link": str(article.get("wp_link") or ""),
            "warning_code": code, "warning_origins": sorted(meta["origins"]), "original_severity": severity,
            "investigation_status": status, "evidence": evidence, "reason": reason,
            "recommended_action": "Review the cited material manually; this diagnostic does not alter publication state.",
            "source_material_available": source_available, "translated_candidate_material_available": candidate_available,
            "final_published_material_available": final_available, "comparative_pair_available": comparative,
            "source_material_provenance": str(article.get("source_material_provenance") or ""),
            "final_published_material_provenance": str(article.get("final_published_material_provenance") or ""),
            "artifact_paths": list(article.get("artifact_paths") or []),
        })
    return results


def build_analysis(audit_path: Path, hours: int = 24, now: Optional[datetime] = None) -> Dict[str, Any]:
    generated = now or datetime.now(timezone.utc)
    warnings: List[str] = []
    errors: List[str] = []
    payload: Dict[str, Any] = {}
    try:
        loaded = json.loads(audit_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("audit JSON root is not an object")
        payload = loaded
    except Exception as exc:
        errors.append("audit_read_failed:%s" % exc)
    investigations = [record for article in payload.get("articles", []) if isinstance(article, dict) for record in investigate_article(article)]
    status_counts = Counter(item["investigation_status"] for item in investigations)
    for status in STATUSES:
        status_counts.setdefault(status, 0)
    return {
        "schema_version": "v95.16a-1", "generated_at": generated.isoformat(), "hours": hours,
        "source_audit_path": str(audit_path), "source_audit_generated_at": payload.get("generated_at"),
        "total_investigations": len(investigations), "status_counts": dict(sorted(status_counts.items())),
        "severity_counts": dict(Counter(x["original_severity"] for x in investigations)),
        "warning_code_counts": dict(Counter(x["warning_code"] for x in investigations)),
        "articles_with_investigations": len({x["article_key"] for x in investigations}),
        "investigations": investigations, "warnings": warnings, "errors": errors,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    counts = report["status_counts"]
    lines = ["# OWTV Translation Warning Analysis (%sh)" % report["hours"], "", "Generated: %s" % report["generated_at"], "", "## Summary", "", "- Investigations: %s" % report["total_investigations"]]
    lines += ["- %s: %s" % (key, counts.get(key, 0)) for key in sorted(STATUSES)]
    lines += ["", "## Investigations", ""]
    if not report["investigations"]:
        lines.append("- No warnings to investigate.")
    for item in report["investigations"]:
        evidence = "; ".join("%s: %s" % (x["material"], x["excerpt"]) for x in item["evidence"]) or "none"
        lines += ["### %s — %s" % (item["title"] or item["article_key"], item["warning_code"]), "- Status: %s" % item["investigation_status"], "- Origins: %s" % ", ".join(item["warning_origins"]), "- Evidence: %s" % evidence, "- Reason: %s" % item["reason"], "- Recommended action: %s" % item["recommended_action"], ""]
    if report["errors"]:
        lines += ["## Diagnostic errors", ""] + ["- %s" % value for value in report["errors"]]
    return "\n".join(lines) + "\n"


def generate_outputs(audit_path: Optional[Path] = None, output_dir: Optional[Path] = None, state_dir: Optional[Path] = None, hours: int = 24, now: Optional[datetime] = None) -> Dict[str, Path]:
    effective_now = now or datetime.now(timezone.utc)
    source = audit_path or LATEST_AUDIT
    report = build_analysis(source, hours, effective_now)
    output = output_dir or ROOT / "reports"
    state = state_dir or ROOT / "state/reports"
    output.mkdir(parents=True, exist_ok=True); state.mkdir(parents=True, exist_ok=True)
    stamp = effective_now.strftime("%Y%m%d_%H%M%S")
    json_path = output / ("owtv_translation_warning_analysis_24h_%s.json" % stamp)
    md_path = output / ("owtv_translation_warning_analysis_24h_%s.md" % stamp)
    latest = state / LATEST_ANALYSIS.name
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_path.write_text(text, encoding="utf-8"); latest.write_text(text, encoding="utf-8"); md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "latest_json": latest}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-json", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()
    print(generate_outputs(args.audit_json, args.output_dir, args.state_dir, args.hours)["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
