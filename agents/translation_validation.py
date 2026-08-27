"""Pure, conservative evidence for failed English-to-Italian translation."""

from __future__ import annotations

import html
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

ENGLISH_MARKERS = {
    "the", "and", "that", "this", "with", "from", "for", "was", "were", "has", "have",
    "had", "but", "not", "who", "which", "would", "could", "should", "will", "after",
    "before", "about", "into", "during", "when", "while", "their", "they", "his", "her",
}
ITALIAN_MARKERS = {
    "il", "lo", "la", "i", "gli", "le", "un", "una", "che", "con", "per", "dal", "dalla",
    "del", "della", "dei", "delle", "nel", "nella", "sono", "era", "ha", "hanno", "non",
    "anche", "dopo", "prima", "durante", "quando", "mentre", "suo", "sua", "loro",
}


def plain_text(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<!--.*?-->|<[^>]+>", " ", value, flags=re.S)
    return re.sub(r"\s+", " ", value).strip()


def normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", plain_text(value)).casefold()
    return re.sub(r"[^\w']+", " ", value).strip()


def likely_macroscopic_english(value: str, *, minimum_words: int = 40) -> bool:
    """Require sustained English grammar evidence, not isolated names or show terms."""
    words = re.findall(r"[a-zA-ZÀ-ÿ']+", plain_text(value).casefold())
    if len(words) < minimum_words:
        return False
    english = sum(word in ENGLISH_MARKERS for word in words)
    italian = sum(word in ITALIAN_MARKERS for word in words)
    return english >= 8 and english / len(words) >= 0.12 and english >= (italian * 2 + 4)


def likely_english_title(value: str) -> bool:
    words = re.findall(r"[a-zA-ZÀ-ÿ']+", plain_text(value).casefold())
    english = sum(word in ENGLISH_MARKERS for word in words)
    italian = sum(word in ITALIAN_MARKERS for word in words)
    return len(words) >= 6 and english >= 2 and english >= italian + 2


def likely_prose_headline(value: str) -> bool:
    """Separate long headline structure from short official names and branding."""
    words = re.findall(r"[a-zA-ZÀ-ÿ']+", plain_text(value).casefold())
    return len(words) >= 8


def token_similarity(source: str, output: str) -> float:
    source_tokens = normalized(source).split()
    output_tokens = normalized(output).split()
    if not source_tokens or not output_tokens:
        return 0.0
    return SequenceMatcher(None, source_tokens, output_tokens, autojunk=False).ratio()


def language_escape_evidence(
    source_title: str,
    translated_title: str,
    source_units: dict[str, str],
    translated_units: dict[str, str],
) -> dict[str, Any]:
    unchanged: list[str] = []
    source_chars = unchanged_chars = 0
    for unit_id, source in source_units.items():
        source_norm = normalized(source)
        output_norm = normalized(translated_units.get(unit_id, ""))
        if not source_norm:
            continue
        source_chars += len(source_norm)
        if len(source_norm) >= 60 and source_norm == output_norm:
            unchanged.append(unit_id)
            unchanged_chars += len(source_norm)

    source_body = " ".join(source_units.values())
    output_body = " ".join(translated_units.values())
    aligned_output_body = " ".join(translated_units.get(unit_id, "") for unit_id in source_units)
    source_body_norm = normalized(source_body)
    exact_body_unchanged = bool(
        len(source_body_norm) >= 160
        and source_body_norm == normalized(aligned_output_body)
    )
    source_output_similarity = token_similarity(source_body, aligned_output_body)
    near_identical_body = bool(
        len(source_body_norm) >= 160
        and len(normalized(aligned_output_body)) >= 160
        and not exact_body_unchanged
        and source_output_similarity >= 0.94
    )
    partial_overwhelmingly_unchanged = (
        source_chars >= 160
        and unchanged_chars / source_chars >= 0.75
        and likely_macroscopic_english(source_body)
    )
    overwhelmingly_unchanged = exact_body_unchanged or near_identical_body or partial_overwhelmingly_unchanged
    body_english = likely_macroscopic_english(output_body)
    title_unchanged = bool(
        len(normalized(source_title)) >= 20
        and normalized(source_title) == normalized(translated_title)
        and (
            likely_english_title(source_title)
            or (likely_prose_headline(source_title) and likely_macroscopic_english(source_body))
        )
    )
    return {
        "unchanged_units": unchanged[:30],
        "unchanged_source_ratio": round(unchanged_chars / source_chars, 3) if source_chars else None,
        "body_likely_untranslated": overwhelmingly_unchanged or body_english,
        "body_substantially_unchanged": overwhelmingly_unchanged,
        "exact_body_unchanged": exact_body_unchanged,
        "near_identical_body": near_identical_body,
        "source_output_similarity": round(source_output_similarity, 3),
        "residual_english_body": body_english,
        "title_likely_untranslated": title_unchanged,
    }
