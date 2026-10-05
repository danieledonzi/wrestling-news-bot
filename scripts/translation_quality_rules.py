"""TQ-1 versioned local diagnostic rules; no editorial or publication authority."""
from __future__ import annotations

import re
from typing import Any

from scripts import translation_quality_audit as audit

POLICY_VERSION = "owtv_tq1_rules_v1"
LEXICAL_RULES = {
    "possible_match_mistranslation": r"\b(?:partita|partite|gara|gare|gioco|giochi)\b",
    "possible_release_mistranslation": r"\b(?:rilascio|rilasciat[oaie])\b",
    "possible_retirement_mistranslation": r"\b(?:pensione|pensionamento|pensionarsi|pensionat[oa])\b",
    "possible_cleared_mistranslation": r"\b(?:non\s+)?pulit[oaie]\b",
    "literal_connected_calque": r"\bha\s+collegato\b|\bsi\s+[èe]\s+collegat[oaie]\b",
    "literal_tide_turned_calque": r"\bla\s+marea\s+[èe]\s+cambiat[ao]\b",
    "literal_well_connected_calque": r"\bben\s+collegat[oaie]\s+nel\s+backstage\b",
    "promo_gender_warning": r"\buna\s+promo\b",
    "chop_gender_warning": r"\b(?:gli|degli)\s+chop\b",
    "ai_style_or_literalism_warning": r"\b(?:rivelatrice|prevalenza|coinvolto\s+in\s+una\s+dinamica|all'interno\s+della\s+compagnia|televisione\s+nazionale)\b",
}
SOURCE_RULES = {
    "possible_match_mistranslation": r"\bmatch(?:es)?\b",
    "possible_release_mistranslation": r"\breleas(?:e|ed|es|ing)\b",
    "possible_retirement_mistranslation": r"\bretir(?:e|ed|ement|ing)\b",
    "possible_cleared_mistranslation": r"\bclear(?:ed|ance)\b",
}
PATTERNS = {code: re.compile(value, re.I) for code, value in LEXICAL_RULES.items()}
STRUCTURAL_CODES = {"paragraph_count_drop", "blockquote_missing_for_long_quotes"}
COMPARATIVE_CODES = set(SOURCE_RULES) | {"published_text_too_short_vs_original", "quote_count_mismatch"}


def excerpt(text: str, match: re.Match[str]) -> str:
    return text[max(0, match.start() - 70): match.end() + 70].replace("\n", " ").strip()


def regex_result(pattern, text: str, material="final_published") -> dict[str, Any]:
    match = pattern.search(text)
    return {"matched": bool(match), "evidence": [{"material": material, "excerpt": excerpt(text, match)}] if match else []}


def evaluate(code: str, article: dict[str, Any], final_rules: dict) -> dict[str, Any]:
    """Reproduce a rule signal, never certify semantic correctness or blame an agent."""
    source = str(article.get("original_text") or "")
    final = str(article.get("published_text") or "")
    available = bool(article.get("final_published_material_available", bool(final))) and bool(final)
    if code == "title_too_long":
        title = str(article.get("title") or "")
        if not title:
            return {"missing": "title_material_unavailable"}
        return {"matched": len(title) > 95, "evidence": [{"material": "title", "excerpt": title[:200]}],
                "reason": "Final title length compared with Alfred's 95-character threshold."}
    if not available:
        return {"missing": "final_material_unavailable"}
    if code in STRUCTURAL_CODES:
        if article.get("final_markup_available") is not True:
            return {"missing": "final_structure_unavailable"}
        if code == "paragraph_count_drop":
            if article.get("source_markup_available") is not True:
                return {"missing": "source_structure_unavailable"}
            original, published = article.get("original_paragraph_count", 0), article.get("published_paragraph_count", 0)
            matched = original >= 5 and bool(published) and published <= max(1, original // 2)
        else:
            matched = audit.has_unblocked_long_direct_quote(final) and article.get("blockquote_count", 0) == 0
        return {"matched": bool(matched), "evidence": [{"material": "final_published", "excerpt": final[:200]}],
                "reason": "Structural audit predicate evaluated only with retained markup."}
    if code in COMPARATIVE_CODES and not (source and article.get("source_material_available", True)):
        return {"missing": "source_material_unavailable"}
    if code in PATTERNS:
        result = regex_result(PATTERNS[code], final)
        if code in SOURCE_RULES:
            source_result = regex_result(re.compile(SOURCE_RULES[code], re.I), source, "source")
            result["source_trigger_present"] = source_result["matched"]
            result["evidence"] += source_result["evidence"]
        result["reason"] = "Local lexical trigger reproduced; source context still requires editorial review."
        return result
    if code in {"published_text_too_short_vs_original", "quote_count_mismatch"}:
        if code == "quote_count_mismatch":
            if article.get("final_markup_available") is not True:
                return {"missing": "final_structure_unavailable"}
            matched = source.count('"') >= 4 and article.get("blockquote_count", 0) == 0 and final.count('"') < source.count('"') / 2
        else:
            matched = len(source) >= 800 and len(final) < len(source) * .45
        return {"matched": matched, "evidence": [
            {"material": "source", "excerpt": source[:160]}, {"material": "final_published", "excerpt": final[:160]}],
            "reason": "Comparative heuristic reproduced; punctuation/length is not proof of lost facts."}
    if code in final_rules:
        text = final
        material = "final_published"
        if code == "betting_odds_article_published" and final_rules[code].search(str(article.get("title") or "")):
            text, material = str(article["title"]), "title"
        result = regex_result(final_rules[code], text, material)
        if code == "untranslated_quote_or_residual_english":
            # Match the audit's full predicate, not just its broad keyword regex.
            result["matched"] = result["matched"] and len(re.findall(r"\b(?:the|and|of|to|for|with|said)\b", final, re.I)) >= 3
        result["reason"] = "Existing audit predicate evaluated on authoritative material."
        return result
    return {"missing": "evaluator_unavailable"}


def stage_trace(code: str, article: dict[str, Any], final_rules: dict) -> dict[str, Any]:
    """Show trigger presence separately in Bob, Alfred and final, without causal claims."""
    pattern = PATTERNS.get(code) or final_rules.get(code)
    trace = {}
    for name, field, availability in (
        ("bob", "translated_candidate_text", "translated_candidate_material_available"),
        ("alfred", "alfred_approved_text", "alfred_approved_material_available"),
        ("final", "published_text", "final_published_material_available"),
    ):
        text = str(article.get(field) or "")
        present = bool(text) and bool(article.get(availability, bool(text)))
        trace[name] = {"available": present, "trigger_present": bool(pattern.search(text)) if present and pattern else None}
        if present and pattern:
            match = pattern.search(text)
            if match:
                trace[name]["excerpt"] = excerpt(text, match)
    return trace
