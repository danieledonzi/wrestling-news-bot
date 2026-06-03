from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.alfred import run_alfred as base_run_alfred

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
ALFRED_REVIEW_FILE = NEWSROOM_STATE_DIR / "alfred_review_latest.json"
ARTIFACT_ALFRED_FILE = ARTIFACT_DIR / "alfred_review.json"

VERSION = "v93_20_alfred_table_warning_precision"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def bob_by_url(bob_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        source_key(article.get("source_url") or ""): article
        for article in bob_result.get("articles", [])
        if isinstance(article, dict)
    }


def expected_tables_from_bob(article: dict[str, Any] | None) -> bool:
    if not isinstance(article, dict):
        return False
    brief = article.get("bob_brief") if isinstance(article.get("bob_brief"), dict) else {}
    diagnostics = article.get("extraction_diagnostics") if isinstance(article.get("extraction_diagnostics"), dict) else {}
    element_counts = article.get("element_counts") if isinstance(article.get("element_counts"), dict) else {}
    if brief.get("expected_tables") is True:
        return True
    if int(diagnostics.get("table_count", 0) or 0) > 0:
        return True
    if int(element_counts.get("table", 0) or 0) > 0:
        return True
    return False


def refine_review(review: dict[str, Any], article: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    if not isinstance(review, dict):
        return review, 0
    warnings = review.get("warnings") if isinstance(review.get("warnings"), list) else []
    kept: list[Any] = []
    removed = 0
    for warning in warnings:
        if isinstance(warning, dict) and warning.get("code") == "possible_missing_table" and not expected_tables_from_bob(article):
            removed += 1
            continue
        kept.append(warning)
    if removed:
        review = dict(review)
        review["warnings"] = kept
        review.setdefault("editorial_changes", [])
        review["editorial_changes"].append({
            "code": "false_table_warning_removed",
            "severity": "info",
            "message": "Rimosso warning tabella: nessun segnale reale da Bob o Menzo.",
        })
        blockers = [x for x in review.get("issues", []) if isinstance(x, dict) and x.get("severity") == "blocker"] if isinstance(review.get("issues"), list) else []
        review["quality_score"] = max(0, min(100, 100 - 25 * len(blockers) - 5 * len(kept)))
    return review, removed


def run_alfred(bob_result: dict[str, Any] | None = None) -> dict[str, Any]:
    bob = bob_result if isinstance(bob_result, dict) else {}
    result = base_run_alfred(bob_result)
    articles = bob_by_url(bob)
    total_removed = 0
    refined_reviews: list[dict[str, Any]] = []
    for review in result.get("reviews", []) if isinstance(result.get("reviews"), list) else []:
        refined, removed = refine_review(review, articles.get(source_key(review.get("source_url", ""))) if isinstance(review, dict) else None)
        total_removed += removed
        refined_reviews.append(refined)
    if refined_reviews:
        result["reviews"] = refined_reviews
    approved = []
    for review in result.get("reviews", []) if isinstance(result.get("reviews"), list) else []:
        if isinstance(review, dict) and review.get("decision") == "approved" and review.get("approved_article"):
            approved.append(review.get("approved_article"))
    result["approved_articles"] = approved
    result["version"] = VERSION
    result.setdefault("policy", {})["possible_missing_table_requires_real_table_signal"] = True
    result.setdefault("postprocess", {})["false_table_warnings_removed"] = total_removed
    if isinstance(result.get("handoff"), dict):
        result["handoff"]["warnings"] = sum(len(r.get("warnings", [])) for r in result.get("reviews", []) if isinstance(r, dict))
        result["handoff"]["approved"] = len(approved)
    write_json(ARTIFACT_ALFRED_FILE, result)
    write_json(ALFRED_REVIEW_FILE, result)
    print(f"[ALFRED v93.20] Table warning precision | removed={total_removed}", flush=True)
    return result
