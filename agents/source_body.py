"""Canonical, reusable source-article hydration for editorial agents."""
from __future__ import annotations

import hashlib
import re
from typing import Any

SCHEMA = "owtv_canonical_source_body_v1"
MIN_COMPLETE_CHARS = 200


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def valid_contract(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("complete") is not True:
        return False
    text = _clean(value.get("cleaned_full_text"))
    provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
    coverage = value.get("coverage") if isinstance(value.get("coverage"), dict) else {}
    return bool(len(text) >= MIN_COMPLETE_CHARS and provenance.get("extractor") == "bob.extract_elements" and provenance.get("body_complete") is True and coverage.get("extraction_finished") is True and value.get("sha256") == _digest(text))


def contract_text(item: dict[str, Any]) -> str:
    contract = item.get("canonical_source_body")
    if valid_contract(contract):
        return _clean(contract["cleaned_full_text"])
    return ""


def contract_from_elements(url: str, elements: list[dict[str, Any]], diagnostics: dict[str, Any]) -> dict[str, Any] | None:
    parts = [_clean(e.get("text") or e.get("markdown")) for e in elements if isinstance(e, dict) and e.get("type") in {"text", "heading", "quote", "table"}]
    extracted_text = _clean(" ".join(part for part in parts if part))
    structured_text = _clean(diagnostics.get("structured_article_body"))
    text = structured_text if len(structured_text) > len(extracted_text) else extracted_text
    complete = diagnostics.get("extraction_finished") is True and diagnostics.get("body_complete") is True and len(text) >= MIN_COMPLETE_CHARS and int(diagnostics.get("clean_element_count") or len(elements)) > 0
    if not complete:
        return None
    return {
        "schema": SCHEMA,
        "complete": True,
        "cleaned_full_text": text,
        "sha256": _digest(text),
        "char_count": len(text),
        "provenance": {"extractor": "bob.extract_elements", "source_url": url, "stage": diagnostics.get("stage"), "body_complete": True, "body_complete_reason": diagnostics.get("body_complete_reason")},
        "coverage": {"extraction_finished": True, "root_text_chars": diagnostics.get("root_text_chars"), "extracted_text_chars": diagnostics.get("extracted_text_chars"), "root_coverage_ratio": diagnostics.get("root_coverage_ratio"), "structured_article_body_chars": diagnostics.get("structured_article_body_chars"), "structured_coverage_ratio": diagnostics.get("structured_coverage_ratio"), "structured_token_overlap_ratio": diagnostics.get("structured_token_overlap_ratio"), "truncation_access_markers": diagnostics.get("truncation_access_markers") or []},
    }


def hydrate(item: dict[str, Any]) -> tuple[bool, str]:
    """Mutate ``item`` only after Bob's extractor proves a complete source body."""
    if contract_text(item):
        return True, "canonical_cache"
    url = str(item.get("source_url") or item.get("url") or "").strip()
    if not url:
        return False, "missing_source_url"
    try:
        from agents.bob import extract_elements, fetch_html
        raw_html = fetch_html(url)
        _meta, _raw, elements, _removed, diagnostics = extract_elements(url, raw_html)
        contract = contract_from_elements(url, elements, diagnostics)
        if not contract:
            return False, "incomplete_extraction"
        item["canonical_source_body"] = contract
        return True, "bob_source_extraction"
    except Exception as exc:
        return False, f"source_extraction_error:{type(exc).__name__}"
