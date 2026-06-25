from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from agents.alfred import run_alfred as base_run_alfred

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
ALFRED_REVIEW_FILE = NEWSROOM_STATE_DIR / "alfred_review_latest.json"
ARTIFACT_ALFRED_FILE = ARTIFACT_DIR / "alfred_review.json"

VERSION = "v94_14_alfred_translation_guardrail_warnings"

TRANSLATION_GUARDRAIL_PATTERNS = [
    (re.compile(r"\b(partita|partite|gara|gare|gioco|giochi)\b", re.I), "possible_match_mistranslation", "Nel contesto wrestling 'match' non deve diventare partita/gara/gioco."),
    (re.compile(r"\b(rilascio|rilasciato|rilasciata|rilasciati|rilasciate)\b", re.I), "possible_release_mistranslation", "release/released non deve diventare rilascio/rilasciato: usare licenziamento, licenziato/licenziata, addio o uscita secondo contesto."),
    (re.compile(r"\b(pensione|pensionamento|pensionarsi|pensionato|pensionata)\b", re.I), "possible_retirement_mistranslation", "retirement nel wrestling va reso come ritiro/ritirarsi, non pensione/pensionamento."),
    (re.compile(r"\b(non\s+)?pulit[oaie]\b", re.I), "possible_cleared_mistranslation", "cleared/not cleared va reso come autorizzato/non autorizzato a lottare, non pulito/non pulito."),
    (re.compile(r"\bha\s+collegato\b|\bsi\s+è\s+collegat[oaie]\b|\bsi\s+e\s+collegat[oaie]\b", re.I), "literal_connected_calque", "connected with una mossa non va reso come collegato: usare ha colpito con / ha messo a segno."),
    (re.compile(r"\bla\s+marea\s+(?:è|e)\s+cambiat[ao]\b", re.I), "literal_tide_turned_calque", "tide turned va reso come l'inerzia del match e' cambiata."),
    (re.compile(r"\bben\s+collegat[oaie]\s+nel\s+backstage\b", re.I), "literal_well_connected_calque", "well-connected backstage va reso come ben introdotto nel backstage / con agganci nel backstage."),
    (re.compile(r"\buna\s+promo\b", re.I), "promo_gender_warning", "Promo in italiano wrestling e' maschile: un promo."),
    (re.compile(r"\b(gli|degli)\s+chop\b", re.I), "chop_gender_warning", "Chop in italiano wrestling e' femminile: le chop / delle chop."),
    (re.compile(r"\b(rivelatrice|prevalenza|coinvolto\s+in\s+una\s+dinamica|all'interno\s+della\s+compagnia|televisione\s+nazionale)\b", re.I), "ai_style_or_literalism_warning", "Formula innaturale o troppo da traduzione letterale/AI."),
]

PROTECTED_TITLE_MISTRANSLATION_PATTERNS = [
    (re.compile(r"\b(titolo|campionato)\s+mondiale\s+dei\s+pesi\s+massimi\b", re.I), "official_title_translated", "World Heavyweight Championship non va tradotto."),
    (re.compile(r"\b(titolo|campionato)\s+intercontinentale\b", re.I), "official_title_translated", "Intercontinental Championship non va tradotto."),
    (re.compile(r"\b(titolo|campionato)\s+degli\s+stati\s+uniti\b", re.I), "official_title_translated", "United States Championship non va tradotto."),
    (re.compile(r"\b(titolo|campionato)\s+knockouts\b", re.I), "official_title_translated", "TNA Knockouts Title / TNA Knockouts World Championship non va tradotto."),
    (re.compile(r"\b(match\s+con\s+scala|match\s+scala)\b", re.I), "official_match_type_translated", "Ladder Match non va tradotto."),
    (re.compile(r"\b(match\s+in\s+gabbia|gabbia\s+d'acciaio)\b", re.I), "official_match_type_translated", "Steel Cage Match / Steel Cage non va tradotto se e' nome stipulazione."),
    (re.compile(r"\bultimo\s+uomo\s+in\s+piedi\b", re.I), "official_match_type_translated", "Last Man Standing Match non va tradotto."),
]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(value or ""))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(value)).strip()


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


def translation_guardrail_warnings(review: dict[str, Any], article: dict[str, Any] | None) -> list[dict[str, str]]:
    text_parts = [str(review.get("title_it") or "")]
    if isinstance(review.get("approved_article"), dict):
        text_parts.append(str(review["approved_article"].get("body_html") or ""))
    if isinstance(article, dict):
        text_parts.append(str(article.get("body_html") or ""))
    plain = clean_text(" ".join(text_parts))
    if not plain:
        return []
    warnings: list[dict[str, str]] = []
    for pattern, code, message in TRANSLATION_GUARDRAIL_PATTERNS + PROTECTED_TITLE_MISTRANSLATION_PATTERNS:
        match = pattern.search(plain)
        if match:
            warnings.append({
                "code": code,
                "severity": "warning",
                "message": message,
                "evidence": match.group(0)[:300],
            })
    # Deduplicate warnings by code+evidence, preserving order.
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for warning in warnings:
        key = (warning.get("code", ""), warning.get("evidence", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped[:8]


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
    new_translation_warnings = translation_guardrail_warnings(review, article)
    if removed or new_translation_warnings:
        review = dict(review)
        existing_keys = {
            (w.get("code", ""), w.get("evidence", ""))
            for w in kept
            if isinstance(w, dict)
        }
        for warning in new_translation_warnings:
            key = (warning.get("code", ""), warning.get("evidence", ""))
            if key not in existing_keys:
                kept.append(warning)
                existing_keys.add(key)
        review["warnings"] = kept
        review.setdefault("editorial_changes", [])
        if removed:
            review["editorial_changes"].append({
                "code": "false_table_warning_removed",
                "severity": "info",
                "message": "Rimosso warning tabella: nessun segnale reale da Bob o Menzo.",
            })
        if new_translation_warnings:
            review["editorial_changes"].append({
                "code": "translation_guardrails_checked_v94_14",
                "severity": "info",
                "message": "Applicato controllo leggero Alfred sui guardrail linguistici v94.14.",
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
    result.setdefault("policy", {})["translation_guardrail_warnings_v94_14"] = True
    result.setdefault("postprocess", {})["false_table_warnings_removed"] = total_removed
    result.setdefault("postprocess", {})["translation_guardrail_warning_count"] = sum(
        1
        for r in result.get("reviews", [])
        if isinstance(r, dict)
        for w in r.get("warnings", [])
        if isinstance(w, dict) and str(w.get("code", "")).endswith(("mistranslation", "calque", "warning", "translated"))
    )
    if isinstance(result.get("handoff"), dict):
        result["handoff"]["warnings"] = sum(len(r.get("warnings", [])) for r in result.get("reviews", []) if isinstance(r, dict))
        result["handoff"]["approved"] = len(approved)
    write_json(ARTIFACT_ALFRED_FILE, result)
    write_json(ALFRED_REVIEW_FILE, result)
    print(f"[ALFRED v94.14] Translation guardrail warnings + table precision | removed={total_removed}", flush=True)
    return result
