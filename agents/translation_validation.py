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
    distinct_english = len({word for word in words if word in ENGLISH_MARKERS})
    italian = sum(word in ITALIAN_MARKERS for word in words)
    return distinct_english >= 3 and english >= 8 and english / len(words) >= 0.12 and english >= (italian * 2 + 4)


def likely_english_title(value: str) -> bool:
    words = re.findall(r"[a-zA-ZÀ-ÿ']+", plain_text(value).casefold())
    english = sum(word in ENGLISH_MARKERS for word in words)
    italian = sum(word in ITALIAN_MARKERS for word in words)
    return len(words) >= 6 and english >= 2 and english >= italian + 2


def likely_prose_headline(value: str) -> bool:
    """Separate long headline structure from short official names and branding."""
    words = re.findall(r"[a-zA-ZÀ-ÿ']+", plain_text(value).casefold())
    matchup_separator = re.search(r"(?<!\w)(?:vs\.?|versus)(?!\w)", plain_text(value), re.I)
    has_english_marker = any(word in ENGLISH_MARKERS for word in words)
    return len(words) >= 8 and (matchup_separator is None or has_english_marker)


def likely_clear_match_card(value: str) -> bool:
    text = plain_text(value)
    # Bob flattens ordinary <p>/<li> whitespace, so only explicit bullet glyphs remain a
    # trustworthy multi-entry boundary inside one translation unit. Separate <li> nodes
    # already become separate (normally short) units and need no long-unit exemption.
    entries = [entry.strip() for entry in re.split(r"[•●▪◦]", text) if entry.strip()]
    if len(entries) < 2:
        return False
    for entry in entries:
        separators = re.findall(r"(?<!\w)(?:vs\.?|versus)(?!\w)", entry, re.I)
        without_vs_dots = re.sub(r"(?<!\w)vs\.(?!\w)", "vs", entry, flags=re.I)
        words = re.findall(r"[A-Za-zÀ-ÿ]+", entry)
        if not separators or re.search(r"[.!?]", without_vs_dots) or len(words) > 12 * len(separators):
            return False
    return True


def prose_like_table_cell(value: str) -> bool:
    text = plain_text(value)
    words = re.findall(r"[A-Za-zÀ-ÿ]+", text)
    lowercase = sum(token.islower() for token in words)
    matchup = re.search(r"(?<!\w)(?:vs\.?|versus)(?!\w)", text, re.I)
    return len(words) >= 5 and lowercase >= 2 and matchup is None


def token_similarity(source: str, output: str) -> float:
    source_tokens = normalized(source).split()
    output_tokens = normalized(output).split()
    if not source_tokens or not output_tokens:
        return 0.0
    return SequenceMatcher(None, source_tokens, output_tokens, autojunk=False).ratio()


def likely_short_english_prose(value: str) -> bool:
    """Conservative English evidence for excerpts shorter than normal articles."""
    words = re.findall(r"[a-zA-ZÀ-ÿ']+", plain_text(value).casefold())
    if len(words) < 8:
        return False
    english_words = [word for word in words if word in ENGLISH_MARKERS]
    italian = sum(word in ITALIAN_MARKERS for word in words)
    return (
        len(set(english_words)) >= 3
        and len(english_words) >= 3
        and len(english_words) / len(words) >= 0.2
        and len(english_words) >= italian + 2
    )


def excerpt_translation_evidence(source_description: str, excerpt: str) -> dict[str, Any]:
    source_norm = normalized(source_description)
    excerpt_norm = normalized(excerpt)
    similarity = token_similarity(source_description, excerpt)
    substantive = len(source_norm) >= 50 and len(excerpt_norm) >= 50
    exact = bool(substantive and source_norm == excerpt_norm)
    near = bool(substantive and not exact and similarity >= 0.9)
    residual = likely_short_english_prose(excerpt)
    return {
        "excerpt_likely_untranslated": exact or near,
        "excerpt_residual_english": residual,
        "excerpt_exact_source": exact,
        "excerpt_near_source": near,
        "excerpt_source_similarity": round(similarity, 3),
    }


def language_escape_evidence(
    source_title: str,
    translated_title: str,
    source_units: dict[str, str],
    translated_units: dict[str, str],
    source_title_candidates: list[tuple[str, str]] | None = None,
    source_unit_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    unit_types = source_unit_types or {}
    unchanged: list[str] = []
    substantive_unchanged: list[str] = []
    unchanged_table_units: list[str] = []
    prose_like_unchanged_table_units: list[str] = []
    table_stats: dict[str, dict[str, int]] = {}
    fallback_output_norm = normalized(" ".join(translated_units.values()))
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
        exact_or_rendered = source_norm == output_norm or (unit_id not in translated_units and source_norm in fallback_output_norm)
        unit_type = str(unit_types.get(unit_id) or "")
        if unit_type == "table_cell":
            match = re.match(r"^(b\d+)_r\d+_c\d+$", unit_id)
            if match:
                parent = match.group(1)
                stats = table_stats.setdefault(parent, {"cells": 0, "source_chars": 0, "unchanged_cells": 0, "unchanged_chars": 0, "prose_like": 0})
                stats["cells"] += 1
                stats["source_chars"] += len(source_norm)
                if exact_or_rendered:
                    stats["unchanged_cells"] += 1
                    stats["unchanged_chars"] += len(source_norm)
                    unchanged_table_units.append(unit_id)
                    if prose_like_table_cell(source):
                        stats["prose_like"] += 1
                        prose_like_unchanged_table_units.append(unit_id)
        if len(source_norm) >= 160 and exact_or_rendered and (
            (unit_type == "table_cell" and prose_like_table_cell(source))
            or (unit_type != "table_cell" and not likely_clear_match_card(source))
        ):
            substantive_unchanged.append(unit_id)

    substantive_tables: list[str] = []
    table_coverage: dict[str, float] = {}
    for parent, stats in list(table_stats.items())[:30]:
        coverage = stats["unchanged_chars"] / stats["source_chars"] if stats["source_chars"] else 0.0
        table_coverage[parent] = round(coverage, 3)
        if stats["cells"] >= 3 and stats["unchanged_cells"] >= 3 and stats["source_chars"] >= 160 and coverage >= 0.75 and stats["prose_like"] >= 2:
            substantive_tables.append(parent)

    source_body = " ".join(source_units.values())
    aligned_output_body = " ".join(translated_units.get(unit_id, "") for unit_id in source_units)
    output_body = aligned_output_body if source_units else " ".join(translated_units.values())
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
    substantive_unit_unchanged = bool(substantive_unchanged)
    overwhelmingly_unchanged = exact_body_unchanged or near_identical_body or partial_overwhelmingly_unchanged or substantive_unit_unchanged or bool(substantive_tables)
    body_english = likely_macroscopic_english(output_body)
    candidates = source_title_candidates or [("source", source_title)]
    title_source_match = None
    for label, candidate in candidates[:3]:
        if (
            len(normalized(candidate)) >= 20
            and normalized(candidate) == normalized(translated_title)
            and (
                likely_english_title(candidate)
                or likely_prose_headline(candidate)
            )
        ):
            title_source_match = str(label)[:20]
            break
    title_unchanged = title_source_match is not None
    return {
        "unchanged_units": unchanged[:30],
        "substantive_unchanged_units": substantive_unchanged[:30],
        "unchanged_table_units": unchanged_table_units[:30],
        "prose_like_unchanged_table_units": prose_like_unchanged_table_units[:30],
        "substantive_unchanged_table_blocks": substantive_tables[:30],
        "unchanged_table_coverage": table_coverage,
        "unchanged_source_ratio": round(unchanged_chars / source_chars, 3) if source_chars else None,
        "body_likely_untranslated": overwhelmingly_unchanged or body_english,
        "body_substantially_unchanged": overwhelmingly_unchanged,
        "exact_body_unchanged": exact_body_unchanged,
        "near_identical_body": near_identical_body,
        "partial_overwhelmingly_unchanged": partial_overwhelmingly_unchanged,
        "source_output_similarity": round(source_output_similarity, 3),
        "residual_english_body": body_english,
        "title_likely_untranslated": title_unchanged,
        "title_source_match": title_source_match,
    }
