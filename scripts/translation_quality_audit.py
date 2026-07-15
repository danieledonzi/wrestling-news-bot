#!/usr/bin/env python3
"""OpenWrestlingTV Translation Quality Audit.

Diagnostic-only audit for comparing available source/extraction artifacts with
published/review HTML and Alfred warnings. This script is intentionally
non-blocking: it reads local artifacts and writes reports only; it does not
modify Bob, Alfred, Menzo, Publisher, Daily Judgment, model chains, or any
publication registry.
"""
from __future__ import annotations

import argparse
import ast
import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
import sys
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.observability_snapshot import build_snapshot as build_observability_snapshot, identity_aliases
DEFAULT_REPORTS_DIR = ROOT / "reports"

SOURCE_INTRO_RE = re.compile(r"\b(?:welcome to|thanks for (?:reading|watching)|follow us|subscribe|sign up|newsletter|our coverage|this article originally|according to (?:the|a) report below)\b", re.I)
SOURCE_PROMO_RE = re.compile(r"\b(?:use promo code|affiliate|shop now|buy tickets|click here|subscribe to|patreon|merch|official store|download our app|exclusive offer)\b", re.I)
AI_FILLER_RE = re.compile(r"\b(?:it remains to be seen|only time will tell|fans will have to wait and see|what happens next|needless to say|at the end of the day|in the world of professional wrestling|the wrestling world is buzzing)\b", re.I)
WRESTLING_LEXICON_RE = re.compile(r"\b(?:lotta libera|lotta professionale|tallone\b|volto\b|babyface tradotto|promozi?one (?:del wrestler|sul ring)|prenotazione creativa)\b", re.I)
OFFICIAL_TITLE_RE = re.compile(r"\b(?:campionato universale|campione universale indiscusso|campionato intercontinentale|campionato degli stati uniti|titolo mondiale dei pesi massimi|campionato femminile)\b", re.I)
ENGLISH_RESIDUAL_RE = re.compile(r"\b(?:said|according to|sources? told|newsletter|creative plans|title shot|pay[- ]per[- ]view)\b", re.I)
PROTECTED_WRESTLING_TERMS_RE = re.compile(r"\b(?:mark|heel|babyface|booking|backstage|promo|tag team|main event)\b", re.I)
GIOCO_FALSE_POSITIVE_RE = re.compile(r"\b(?:fa parte del gioco|entrare in gioco|gioco di potere)\b", re.I)
MOJIBAKE_RE = re.compile(r"(?:Ã.|Â.|â€™|â€œ|â€\x9d|�|\bperchÃ|\bcosÃ|\bpiÃ|\bE\'\s)" )
BETTING_RE = re.compile(r"\b(?:betting odds|oddschecker|draftkings|fanduel|bet365|sportsbook|bookmaker|quote (?:scommesse|betting)|favorit[oi] secondo i bookmaker)\b", re.I)
LONG_DIRECT_QUOTE_RE = re.compile(r"(?:[\"“«][^\"”»]{180,}[\"”»]|[\"”»][^\"“«]{180,}[\"”»])")
QUOTE_REPORTING_VERB_RE = re.compile(r"\b(?:ha detto|ha dichiarato|ha aggiunto|ha spiegato|ha raccontato|ha affermato|secondo|said|stated|told|added|explained|commented)\b", re.I)

ISSUE_SEVERITY: dict[str, str] = {
    "betting_odds_article_published": "high",
    "source_intro_leaked": "high",
    "source_promo_leaked": "high",
    "official_title_translated": "high",
    "mojibake_or_broken_accents": "high",
    "untranslated_quote_or_residual_english": "medium",
    "possible_release_mistranslation": "medium",
    "possible_match_mistranslation": "medium",
    "wrestling_lexicon_issue": "medium",
    "ai_style_filler": "low",
    "blockquote_missing_for_long_quotes": "low",
    "paragraph_count_drop": "low",
    "published_text_too_short_vs_original": "low",
    "title_too_long": "low",
    "image_placeholder_present": "technical",
}
HUMAN_REVIEW_ISSUE_SEVERITIES = {"high", "medium"}
TECHNICAL_ALFRED_WARNINGS = {"image_placeholder_present"}
SOURCE_MATERIAL_KEYS = ("original_text", "source_text", "extracted_text", "article_text", "content_text")
SOURCE_HTML_KEYS = ("source_html", "original_html", "raw_source_html")
TRANSLATED_CANDIDATE_KEYS = ("body_html", "translated_html", "translated_text", "draft_html", "candidate_html")
FINAL_PUBLISHED_MATERIAL_KEYS = ("published_text", "published_html", "final_text", "final_html", "final_body_text", "published_body")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(str(v))
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None


def norm_url(u: Any) -> str:
    raw = html.unescape(str(u or "").strip())
    if not raw:
        return ""
    p = urlsplit(raw)
    return urlunsplit((p.scheme.lower(), p.netloc.lower().replace("www.", ""), p.path.rstrip("/"), "", ""))


def slugify(v: Any) -> str:
    raw = str(v or "")
    raw = re.sub(r"\.(?:html|json|md|txt)$", "", Path(raw).name, flags=re.I)
    raw = re.sub(r"^(?:v\d+[_-])?(?:news|publisher|published|bob|alfred)[_-]", "", raw, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if d.get(k) not in (None, "", []):
            return d.get(k)
    return ""


class TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.p_count = 0
        self.bq_count = 0
        self.title = ""
        self._tag_stack: list[str] = []
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag_stack.append(tag.lower())
        if tag.lower() == "p":
            self.p_count += 1
        elif tag.lower() == "blockquote":
            self.bq_count += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title_parts and not self.title:
            self.title = " ".join(self._title_parts).strip()
        if tag in {"p", "div", "br", "blockquote", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")
        if tag in self._tag_stack[::-1]:
            idx = len(self._tag_stack) - 1 - self._tag_stack[::-1].index(tag)
            del self._tag_stack[idx:]

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if self._tag_stack and self._tag_stack[-1] == "title":
            self._title_parts.append(data.strip())
        if not any(t in {"script", "style", "noscript"} for t in self._tag_stack):
            self.parts.append(data.strip())


def html_stats(raw: str) -> dict[str, Any]:
    parser = TextHTMLParser()
    parser.feed(raw or "")
    text = html.unescape(" ".join(" ".join(parser.parts).split()))
    if parser.p_count == 0 and text:
        parser.p_count = max(1, len([x for x in re.split(r"\n\s*\n", raw) if x.strip()]))
    return {"text": text, "title": parser.title, "text_length": len(text), "paragraph_count": parser.p_count, "blockquote_count": parser.bq_count, "quote_count": len(re.findall(r"[“”\"]", text)) // 2}


@dataclass
class ArticleAudit:
    key: str
    title: str = ""
    source_url: str = ""
    wp_link: str = ""
    source_title: str = ""
    original_text: str = ""
    published_text: str = ""
    translated_candidate_text: str = ""
    original_text_length: int = 0
    published_text_length: int = 0
    original_paragraph_count: int = 0
    published_paragraph_count: int = 0
    quote_count: int = 0
    blockquote_count: int = 0
    alfred_warnings: list[Any] = field(default_factory=list)
    article_type: str = ""
    priority: str = ""
    score: Any = ""
    artifact_paths: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    issue_severities: dict[str, str] = field(default_factory=dict)
    possible_false_positive_warnings: list[Any] = field(default_factory=list)
    source_material_available: bool = False
    translated_candidate_material_available: bool = False
    final_published_material_available: bool = False
    published_material_available: bool = False
    comparative_pair_available: bool = False
    source_material_missing_reason: str = "source_material_not_found"
    final_published_material_missing_reason: str = "final_published_material_not_found"
    published_material_missing_reason: str = "final_published_material_not_found"
    non_comparative_reason: str = "missing_source_and_final_published_material"
    source_material_provenance: str = ""
    source_material_rank: int = 0
    translated_candidate_provenance: str = ""
    translated_candidate_rank: int = 0
    final_published_material_provenance: str = ""
    final_published_material_rank: int = 0
    unclassified_html_artifacts: list[str] = field(default_factory=list)


def iter_json_objects(path: Path) -> Iterable[dict[str, Any]]:
    try:
        if path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip():
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        yield obj
        else:
            obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            yield from flatten_dicts(obj)
    except Exception:
        return


def flatten_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from flatten_dicts(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from flatten_dicts(x)


def best_record_dt(item: dict[str, Any]) -> datetime | None:
    """Return the best available row-level timestamp for window filtering."""
    for key in ("recorded_at", "created_at", "timestamp", "published_at"):
        dt = parse_dt(item.get(key))
        if dt:
            return dt
    for path in (("run", "started_at"), ("event", "timestamp"), ("item", "published_at")):
        cur: Any = item
        for key in path:
            cur = cur.get(key) if isinstance(cur, dict) else None
        dt = parse_dt(cur)
        if dt:
            return dt
    return None


def iter_master_log_objects(path: Path, since: datetime) -> Iterable[dict[str, Any]]:
    """Yield only in-window master_log rows; undated rows keep legacy fallback behavior."""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                continue
            dt = best_record_dt(obj)
            if dt is not None and dt < since:
                continue
            yield from flatten_dicts(obj)
    except Exception:
        return


def article_match_slugs(a: ArticleAudit) -> set[str]:
    values = [a.title, a.source_title, a.wp_link]
    slugs = {slugify(v) for v in values if v}
    return {s for s in slugs if s}


def safe_slug_contains(left: str, right: str) -> bool:
    if not left or not right or left == right:
        return False
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) < 14 or len(shorter.split("-")) < 3:
        return False
    return shorter in longer


def find_matching_article(articles: dict[str, ArticleAudit], file_slug: str, html_title: str = "") -> ArticleAudit | None:
    """Conservatively attach published HTML to an existing metadata record."""
    title_slug = slugify(html_title)
    needles = {s for s in (file_slug, title_slug) if s}
    # Exact key or exact known title/url-derived slug match first.
    for key in needles:
        if key in articles:
            return articles[key]
    for a in articles.values():
        slugs = article_match_slugs(a)
        if needles & slugs:
            return a
    # Conservative containment fallback for production filenames that add/remove
    # small suffixes around a stable title slug.
    for a in articles.values():
        for existing in article_match_slugs(a):
            if any(safe_slug_contains(existing, needle) or safe_slug_contains(needle, existing) for needle in needles):
                return a
    return None


def item_key(item: dict[str, Any], path: Path | None = None) -> str:
    return norm_url(first(item, "source_url", "url", "original_url", "link")) or slugify(first(item, "wp_link", "published_url", "title", "title_it", "source_title") or (path.name if path else ""))



def first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def first_html_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    raw = first_text(item, keys)
    return html_stats(raw)["text"] if raw else ""


def refresh_material_flags(a: ArticleAudit) -> None:
    a.source_material_available = bool(a.original_text.strip())
    a.translated_candidate_material_available = bool(getattr(a, "translated_candidate_text", "").strip())
    a.final_published_material_available = bool(a.published_text.strip())
    a.published_material_available = a.final_published_material_available
    a.comparative_pair_available = a.source_material_available and a.final_published_material_available
    a.source_material_missing_reason = "" if a.source_material_available else "source_material_not_found"
    if a.final_published_material_available:
        a.final_published_material_missing_reason = ""
    elif a.translated_candidate_material_available:
        a.final_published_material_missing_reason = "translated_candidate_only"
    else:
        a.final_published_material_missing_reason = "final_published_material_not_found"
    a.published_material_missing_reason = a.final_published_material_missing_reason
    if a.comparative_pair_available:
        a.non_comparative_reason = ""
    elif not a.source_material_available and a.translated_candidate_material_available and not a.final_published_material_available:
        a.non_comparative_reason = "source_material_missing_and_translated_candidate_only"
    elif a.source_material_available and a.translated_candidate_material_available and not a.final_published_material_available:
        a.non_comparative_reason = "translated_candidate_only"
    elif a.source_material_available:
        a.non_comparative_reason = "final_published_material_missing"
    elif a.final_published_material_available:
        a.non_comparative_reason = "source_material_missing"
    else:
        a.non_comparative_reason = "missing_source_and_final_published_material"

def choose_material(existing_text: str, existing_rank: int, new_text: str, new_rank: int) -> bool:
    if not new_text or not new_text.strip():
        return False
    if new_rank > existing_rank:
        return True
    return new_rank == existing_rank and len(new_text) > len(existing_text)


def set_source_material(a: ArticleAudit, text: str, rank: int, provenance: str, stats: dict[str, Any] | None = None) -> bool:
    if not choose_material(a.original_text, a.source_material_rank, text, rank):
        refresh_material_flags(a)
        return False
    a.original_text = text
    a.source_material_rank = rank
    a.source_material_provenance = provenance
    if stats is not None:
        a.original_text_length = int(stats.get("text_length", len(text)))
        a.original_paragraph_count = int(stats.get("paragraph_count", 0))
    else:
        a.original_text_length = len(text)
        a.original_paragraph_count = 0
    refresh_material_flags(a)
    return True


def set_translated_candidate_material(a: ArticleAudit, text: str, rank: int, provenance: str) -> bool:
    if not choose_material(a.translated_candidate_text, a.translated_candidate_rank, text, rank):
        refresh_material_flags(a)
        return False
    a.translated_candidate_text = text
    a.translated_candidate_rank = rank
    a.translated_candidate_provenance = provenance
    refresh_material_flags(a)
    return True


def set_final_published_material(a: ArticleAudit, text: str, rank: int, provenance: str, stats: dict[str, Any] | None = None) -> bool:
    if not choose_material(a.published_text, a.final_published_material_rank, text, rank):
        refresh_material_flags(a)
        return False
    a.published_text = text
    a.final_published_material_rank = rank
    a.final_published_material_provenance = provenance
    if stats is not None:
        a.published_text_length = int(stats.get("text_length", len(text)))
        a.published_paragraph_count = int(stats.get("paragraph_count", 0))
        a.blockquote_count = int(stats.get("blockquote_count", 0))
        a.quote_count = int(stats.get("quote_count", 0))
    else:
        a.published_text_length = len(text)
        a.published_paragraph_count = len([part for part in re.split(r"\n\s*\n", text) if part.strip()]) or (1 if text.strip() else 0)
        a.blockquote_count = 0
        a.quote_count = len(re.findall(r'[“”"]', text)) // 2
    refresh_material_flags(a)
    return True


def add_unclassified_html(a: ArticleAudit, rel: str) -> None:
    if rel not in a.unclassified_html_artifacts:
        a.unclassified_html_artifacts.append(rel)
    if rel not in a.artifact_paths:
        a.artifact_paths.append(rel)
    refresh_material_flags(a)


def merge_item(a: ArticleAudit, item: dict[str, Any], relpath: str) -> tuple[bool, bool]:
    a.title = a.title or str(first(item, "title_it", "published_title", "title"))
    a.source_url = a.source_url or norm_url(first(item, "source_url", "url", "original_url"))
    a.wp_link = a.wp_link or str(first(item, "wp_link", "published_url", "final_url", "wordpress_url"))
    a.source_title = a.source_title or str(first(item, "source_title", "original_title", "headline"))
    source_added = False
    published_added = False
    text = first_text(item, SOURCE_MATERIAL_KEYS)
    if not text:
        html_text = first_html_text(item, SOURCE_HTML_KEYS)
        text = html_text
    if text:
        source_added = set_source_material(a, text, 250, f"explicit_source_field:{relpath}")
    candidate = first_text(item, TRANSLATED_CANDIDATE_KEYS)
    if candidate:
        if "<" in candidate and ">" in candidate:
            candidate = html_stats(candidate)["text"]
        set_translated_candidate_material(a, candidate, 250, f"translated_candidate_field:{relpath}")
    published = first_text(item, FINAL_PUBLISHED_MATERIAL_KEYS)
    if published:
        if "<" in published and ">" in published:
            published = html_stats(published)["text"]
        published_added = set_final_published_material(a, published, 250, f"explicit_final_field:{relpath}")
    a.article_type = a.article_type or str(first(item, "article_type", "type", "kind"))
    a.priority = a.priority or str(first(item, "priority", "priority_label"))
    a.score = a.score or first(item, "score", "quality_score", "news_score")
    warnings = first(item, "alfred_warnings", "warnings", "warning_codes", "issues")
    if isinstance(warnings, list):
        a.alfred_warnings.extend(w for w in warnings if w)
    elif isinstance(warnings, str) and warnings:
        a.alfred_warnings.append(warnings)
    if relpath not in a.artifact_paths:
        a.artifact_paths.append(relpath)
    refresh_material_flags(a)
    return source_added, published_added



def resolve_authoritative_key(item: dict[str, Any], fallback_key: str, authoritative_keys: set[str] | None, alias_to_canonical_key: dict[str, str]) -> str | None:
    aliases = identity_aliases(item) | ({fallback_key} if fallback_key else set())
    matched_aliases = aliases & authoritative_keys if authoritative_keys is not None else set()
    if authoritative_keys is not None and not matched_aliases:
        return None
    return next((alias_to_canonical_key[a] for a in matched_aliases if a in alias_to_canonical_key), fallback_key)


def merge_source_html(a: ArticleAudit, raw: str, rel: str, rank: int = 400, provenance: str | None = None) -> bool:
    st = html_stats(raw)
    changed = set_source_material(a, st["text"], rank, provenance or f"source_html:{rel}", st)
    if rel not in a.artifact_paths:
        a.artifact_paths.append(rel)
    refresh_material_flags(a)
    return changed


def merge_final_html(a: ArticleAudit, raw: str, rel: str, rank: int = 350, provenance: str | None = None) -> bool:
    st = html_stats(raw)
    changed = set_final_published_material(a, st["text"], rank, provenance or f"final_html:{rel}", st)
    if rel not in a.artifact_paths:
        a.artifact_paths.append(rel)
    refresh_material_flags(a)
    return changed


def relpath(root: Path, path: Path) -> str:
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def merge_candidate_html(a: ArticleAudit, raw: str, rel: str, rank: int = 150, provenance: str | None = None) -> bool:
    st = html_stats(raw)
    changed = set_translated_candidate_material(a, st["text"], rank, provenance or f"candidate_html:{rel}")
    if rel not in a.artifact_paths:
        a.artifact_paths.append(rel)
    refresh_material_flags(a)
    return changed




def parse_archive_time_from_name(path: Path) -> datetime | None:
    for part in [path.stem, *(parent.name for parent in list(path.parents)[:3])]:
        m = re.search(r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?:[-_T]?([0-2]\d)[-_]?([0-5]\d)(?:[-_]?([0-5]\d))?)?", part)
        if not m:
            continue
        year, month, day, hour, minute, second = m.groups()
        try:
            return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0), tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def archive_record_time(metadata: dict[str, Any] | None, metadata_path: Path | None, html_paths: list[Path]) -> datetime | None:
    metadata = metadata or {}
    for key in ("created_at", "published_at", "generated_at"):
        dt = parse_dt(metadata.get(key))
        if dt:
            return dt
    for path in ([metadata_path] if metadata_path else []) + html_paths:
        if path is None:
            continue
        dt = parse_archive_time_from_name(path)
        if dt:
            return dt
    for path in ([metadata_path] if metadata_path else []) + html_paths:
        if path and path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return None


def in_window(dt: datetime | None, since: datetime, until: datetime) -> bool:
    return dt is not None and since <= dt <= until


def has_exact_authoritative_url(item: dict[str, Any], authoritative_keys: set[str] | None) -> bool:
    if authoritative_keys is None:
        return False
    aliases = identity_aliases(item)
    return any(alias.startswith(("source:", "wp:")) and alias in authoritative_keys for alias in aliases)


def archive_allowed_for_window(metadata: dict[str, Any], metadata_path: Path | None, html_paths: list[Path], since: datetime, until: datetime, authoritative_keys: set[str] | None, exact_authority_url: bool = False) -> bool:
    if authoritative_keys is not None and exact_authority_url:
        return True
    return in_window(archive_record_time(metadata, metadata_path, html_paths), since, until)

def merge_archive_metadata(
    root: Path,
    articles: dict[str, ArticleAudit],
    authoritative_keys: set[str] | None,
    alias_to_canonical_key: dict[str, str],
    metadata_path: Path,
    original_path: Path | None,
    final_path: Path | None,
    unmatched_authoritative: dict[str, str],
) -> set[Path]:
    processed: set[Path] = set()
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    meta_key = item_key(metadata, metadata_path) or slugify(metadata_path.stem.replace("_metadata", "")) or slugify(metadata_path.parent.name)
    canonical_key = resolve_authoritative_key(metadata, meta_key, authoritative_keys, alias_to_canonical_key)
    if canonical_key is None:
        return processed
    a = articles.setdefault(canonical_key, ArticleAudit(key=canonical_key))
    merge_item(a, metadata, relpath(root, metadata_path))
    if original_path and original_path.exists():
        if merge_source_html(a, original_path.read_text(encoding="utf-8", errors="replace"), relpath(root, original_path)):
            unmatched_authoritative.pop(canonical_key, None)
        processed.add(original_path)
    if final_path and final_path.exists():
        if merge_final_html(a, final_path.read_text(encoding="utf-8", errors="replace"), relpath(root, final_path)):
            unmatched_authoritative.pop(canonical_key, None)
        processed.add(final_path)
    return processed


def metadata_declared_path(metadata: dict[str, Any], metadata_path: Path, field: str, fallback: Path) -> Path:
    declared = metadata.get(field)
    if isinstance(declared, str) and declared.strip():
        candidate = Path(declared)
        if not candidate.is_absolute():
            candidate = metadata_path.parent / candidate
        return candidate
    return fallback


def resolve_archive_article_for_html(
    articles: dict[str, ArticleAudit],
    key_slug: str,
    html_title: str,
    authoritative_keys: set[str] | None,
    alias_to_canonical_key: dict[str, str],
) -> ArticleAudit | None:
    matched = find_matching_article(articles, key_slug, html_title)
    if matched is not None:
        return matched
    title_alias = "title:" + re.sub(r"[^a-z0-9]+", " ", str(html_title or "").lower()).strip() if html_title else ""
    canonical_key = alias_to_canonical_key.get(title_alias) if title_alias else None
    if authoritative_keys is not None and canonical_key is None:
        return None
    return articles.setdefault(canonical_key or key_slug, ArticleAudit(key=canonical_key or key_slug))

def discover(root: Path, hours: int, limit: int | None) -> list[ArticleAudit]:
    until = utc_now()
    since = until - timedelta(hours=hours)
    articles: dict[str, ArticleAudit] = {}
    authoritative_keys: set[str] | None = None
    alias_to_canonical_key: dict[str, str] = {}
    unmatched_authoritative: dict[str, str] = {}
    try:
        snap = build_observability_snapshot(since, until, root)
        authoritative_records = snap.get("publication", {}).get("records", [])
        authoritative_keys = set() if snap.get("authority_available", True) else None
        for rec in authoritative_records:
            aliases = identity_aliases(rec)
            key = item_key(rec) or next(iter(sorted(aliases)), "")
            if key:
                aliases.add(key)
                for alias in aliases:
                    authoritative_keys.add(alias)
                    alias_to_canonical_key[alias] = key
                a = articles.setdefault(key, ArticleAudit(key=key))
                merge_item(a, rec, "observability_snapshot.authoritative_publication")
                unmatched_authoritative[key] = "no_local_source_or_html_match_yet"
    except Exception:
        authoritative_keys = None
    candidates = [root / "state" / "newsroom" / "master_log.jsonl"]
    for base in [root / "artifacts" / "newsroom", root / "artifacts" / "newsroom_runs", root / "review_packages", root / "state" / "newsroom"]:
        if base.exists():
            candidates.extend([p for p in base.rglob("*.json*") if p.is_file()])
    for p in candidates:
        if not p.exists() or (parse_dt(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()) or utc_now()) < since:
            continue
        rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        source_iter = iter_master_log_objects(p, since) if p.name == "master_log.jsonl" else iter_json_objects(p)
        for item in source_iter:
            key = item_key(item, p)
            if not key:
                continue
            canonical_key = resolve_authoritative_key(item, key, authoritative_keys, alias_to_canonical_key)
            if canonical_key is None:
                continue
            a = articles.setdefault(canonical_key, ArticleAudit(key=canonical_key))
            source_added, published_added = merge_item(a, item, rel)
            if source_added or published_added:
                unmatched_authoritative.pop(canonical_key, None)
    processed_html: set[Path] = set()
    published_review = root / "published_html_review"
    if published_review.exists():
        for metadata_path in published_review.rglob("metadata.json"):
            article_dir = metadata_path.parent
            try:
                metadata_for_window = json.loads(metadata_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                metadata_for_window = {}
            if not isinstance(metadata_for_window, dict):
                metadata_for_window = {}
            html_paths = [article_dir / "original.html", article_dir / "final.html"]
            if not archive_allowed_for_window(metadata_for_window, metadata_path, html_paths, since, until, authoritative_keys, has_exact_authoritative_url(metadata_for_window, authoritative_keys)):
                continue
            processed_html.update(merge_archive_metadata(root, articles, authoritative_keys, alias_to_canonical_key, metadata_path, article_dir / "original.html", article_dir / "final.html", unmatched_authoritative))

        for metadata_path in published_review.rglob("*_metadata.json"):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            base_name = metadata_path.name[:-len("_metadata.json")]
            original_path = metadata_declared_path(metadata, metadata_path, "original_html_file", metadata_path.with_name(f"{base_name}_original.html"))
            final_path = metadata_declared_path(metadata, metadata_path, "final_html_file", metadata_path.with_name(f"{base_name}_final.html"))
            if not archive_allowed_for_window(metadata, metadata_path, [original_path, final_path], since, until, authoritative_keys, has_exact_authoritative_url(metadata, authoritative_keys)):
                continue
            processed_html.update(merge_archive_metadata(root, articles, authoritative_keys, alias_to_canonical_key, metadata_path, original_path, final_path, unmatched_authoritative))

        for p in published_review.rglob("*.html"):
            lower_name = p.name.lower()
            if lower_name.startswith(("v93-news-", "v93-news_", "v93_news-", "v93_news_")):
                if not archive_allowed_for_window({}, None, [p], since, until, authoritative_keys, False):
                    processed_html.add(p)
                    continue
                raw = p.read_text(encoding="utf-8", errors="replace")
                st = html_stats(raw)
                key_slug = re.sub(r"^v93[-_]news[-_]", "", p.stem, flags=re.I)
                a = resolve_archive_article_for_html(articles, slugify(key_slug), st["title"], authoritative_keys, alias_to_canonical_key)
                if a is not None:
                    a.title = a.title or st["title"] or slugify(key_slug).replace("-", " ").title()
                    merge_candidate_html(a, raw, relpath(root, p), 350, f"v93-news:{relpath(root, p)}")
                processed_html.add(p)
            elif lower_name.startswith(("v93-publisher-", "v93-publisher_", "v93_publisher-", "v93_publisher_")):
                if not archive_allowed_for_window({}, None, [p], since, until, authoritative_keys, False):
                    processed_html.add(p)
                    continue
                raw = p.read_text(encoding="utf-8", errors="replace")
                st = html_stats(raw)
                key_slug = re.sub(r"^v93[-_]publisher[-_]", "", p.stem, flags=re.I)
                a = resolve_archive_article_for_html(articles, slugify(key_slug), st["title"], authoritative_keys, alias_to_canonical_key)
                if a is not None and merge_final_html(a, raw, relpath(root, p), 400, f"v93-publisher:{relpath(root, p)}"):
                    unmatched_authoritative.pop(a.key, None)
                processed_html.add(p)

    for base in [root / "published_html_review", root / "review_packages"]:
        if not base.exists():
            continue
        for p in base.rglob("*.html"):
            lower_name = p.name.lower()
            if p in processed_html:
                continue
            if base.name == "published_html_review" and lower_name in {"original.html", "final.html"}:
                continue
            if base.name == "published_html_review" and lower_name.endswith(("_original.html", "_final.html")):
                continue
            if lower_name.startswith(("v93-news-", "v93-news_", "v93_news-", "v93_news_", "v93-publisher-", "v93-publisher_", "v93_publisher-", "v93_publisher_")):
                continue
            if base.name == "published_html_review" and (p.parent / "metadata.json").exists():
                continue
            if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < since:
                continue
            raw = p.read_text(encoding="utf-8", errors="replace")
            st = html_stats(raw)
            key = slugify(p.name)
            matched = find_matching_article(articles, key, st["title"])
            title_alias = "title:" + re.sub(r"[^a-z0-9]+", " ", str(st.get("title") or "").lower()).strip() if st.get("title") else ""
            canonical_key = alias_to_canonical_key.get(title_alias) if title_alias else None
            if authoritative_keys is not None and matched is None and canonical_key is None:
                continue
            a = matched or articles.setdefault(canonical_key or key, ArticleAudit(key=canonical_key or key))
            a.title = a.title or st["title"] or slugify(p.name).replace("-", " ").title()
            rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            if base.name == "review_packages":
                if lower_name in {"original.html", "source.html"} or lower_name.endswith(("_original.html", "_source.html")):
                    merge_source_html(a, raw, rel, 150, f"review_package_source:{rel}")
                elif lower_name in {"translated.html", "candidate.html", "body.html"} or lower_name.endswith(("_translated.html", "_candidate.html", "_body.html")):
                    merge_candidate_html(a, raw, rel, 150, f"review_package_candidate:{rel}")
                else:
                    add_unclassified_html(a, rel)
                continue
            # Unknown published_html_review HTML is diagnostic-only unless handled by a known adapter above.
            add_unclassified_html(a, rel)
    rows = list(articles.values())
    for a in rows:
        if a.original_text:
            a.original_text_length = len(" ".join(a.original_text.split()))
            if not a.original_paragraph_count:
                a.original_paragraph_count = len([x for x in re.split(r"\n\s*\n", a.original_text) if x.strip()]) or (1 if a.original_text.strip() else 0)
        refresh_material_flags(a)
        if unmatched_authoritative.get(a.key) and not a.comparative_pair_available:
            marker = unmatched_authoritative[a.key]
            if marker not in a.artifact_paths:
                a.artifact_paths.append(marker)
        run_checks(a)
    rows.sort(key=lambda x: (len(x.issues), x.published_text_length), reverse=True)
    out_rows = rows[:limit] if limit else rows
    discover.last_metadata = {"publication_authority_available": authoritative_keys is not None}
    return out_rows


def run_checks(a: ArticleAudit) -> None:
    issues: list[str] = []
    if a.original_text_length >= 800 and a.published_text_length and a.published_text_length < a.original_text_length * 0.45:
        issues.append("published_text_too_short_vs_original")
    if a.original_paragraph_count >= 5 and a.published_paragraph_count and a.published_paragraph_count <= max(1, a.original_paragraph_count // 2):
        issues.append("paragraph_count_drop")
    if a.original_text.count('"') >= 4 and a.blockquote_count == 0 and a.published_text.count('"') < a.original_text.count('"') / 2:
        issues.append("quote_count_mismatch")
    if has_unblocked_long_direct_quote(a.published_text) and a.blockquote_count == 0:
        issues.append("blockquote_missing_for_long_quotes")
    text = a.published_text
    if SOURCE_INTRO_RE.search(text): issues.append("source_intro_leaked")
    if SOURCE_PROMO_RE.search(text): issues.append("source_promo_leaked")
    if AI_FILLER_RE.search(text): issues.append("ai_style_filler")
    if WRESTLING_LEXICON_RE.search(text): issues.append("wrestling_lexicon_issue")
    if OFFICIAL_TITLE_RE.search(text): issues.append("official_title_translated")
    if ENGLISH_RESIDUAL_RE.search(text) and len(re.findall(r"\b(?:the|and|of|to|for|with|said)\b", text, re.I)) >= 3:
        issues.append("untranslated_quote_or_residual_english")
    if MOJIBAKE_RE.search(text): issues.append("mojibake_or_broken_accents")
    if BETTING_RE.search(f"{a.title} {text}"): issues.append("betting_odds_article_published")
    a.issues = sorted(set(issues))
    a.issue_severities = {issue: issue_severity(issue) for issue in a.issues}
    for w in a.alfred_warnings:
        lw = str(w).lower()
        if (("bet" in lw and not BETTING_RE.search(f"{a.title} {text}")) or ("match" in lw and GIOCO_FALSE_POSITIVE_RE.search(text)) or ("english" in lw and PROTECTED_WRESTLING_TERMS_RE.search(text) and not ENGLISH_RESIDUAL_RE.search(text))):
            a.possible_false_positive_warnings.append(w)


def issue_severity(issue: str) -> str:
    return ISSUE_SEVERITY.get(issue, "low")


def alfred_warning_code(warning: Any) -> str:
    if isinstance(warning, dict):
        return str(warning.get("code") or "").strip()
    raw = str(warning or "").strip()
    if not raw:
        return ""
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw)
        except Exception:
            continue
        if isinstance(parsed, dict) and parsed.get("code"):
            return str(parsed["code"]).strip()
    return raw.split(":", 1)[0].strip()


def render_alfred_warning(warning: Any) -> str:
    """Render Alfred warning payloads compactly for human-facing reports.

    Alfred artifacts may contain legacy strings, JSON/repr-encoded dicts, or
    structured dictionaries. Keep the stable code prominent while adding compact
    evidence/message context when available. Malformed inputs fall back safely.
    """
    code = alfred_warning_code(warning)
    parsed: Any = warning if isinstance(warning, dict) else None
    if parsed is None and isinstance(warning, str):
        raw = warning.strip()
        for parser in (json.loads, ast.literal_eval):
            try:
                candidate = parser(raw)
            except Exception:
                continue
            if isinstance(candidate, dict):
                parsed = candidate
                break
    if isinstance(parsed, dict):
        parts = [code] if code else []
        details = []
        for key in ("evidence", "message"):
            value = parsed.get(key)
            if value not in (None, "", []):
                details.append(f"{key}={esc(value)}")
        if details:
            parts.append(f"({'; '.join(details)})")
        if parts:
            return " ".join(parts)
    return esc(code or warning)


def json_safe(value: Any) -> Any:
    """Return a JSON-serializable value without stringifying dict warnings."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def article_payload(a: ArticleAudit) -> dict[str, Any]:
    return json_safe(asdict(a))


def alfred_warning_severity(warning: Any) -> str:
    code = alfred_warning_code(warning)
    if code in TECHNICAL_ALFRED_WARNINGS:
        return "technical"
    if "blocker" in str(warning).lower():
        return "blocker"
    return "warning"


def has_unblocked_long_direct_quote(text: str) -> bool:
    """Return True only for long quote-marked speech with nearby attribution evidence."""
    if not text:
        return False
    for match in LONG_DIRECT_QUOTE_RE.finditer(text):
        start, end = match.span()
        nearby = text[max(0, start - 160): min(len(text), end + 160)]
        if QUOTE_REPORTING_VERB_RE.search(nearby):
            return True
    return False


def needs_human_review(a: ArticleAudit) -> bool:
    severities = [issue_severity(issue) for issue in a.issues]
    medium_count = sum(1 for severity in severities if severity == "medium")
    return (
        any(severity in HUMAN_REVIEW_ISSUE_SEVERITIES for severity in severities)
        or medium_count >= 2
        or any(alfred_warning_severity(w) == "blocker" for w in a.alfred_warnings)
    )



def audit_coverage(rows: list[ArticleAudit], authority_available: bool = True, detailed_rows_returned: int | None = None, detail_limit: int | None = None) -> dict[str, Any]:
    population_total = len(rows)
    return {
        "publication_authority_available": bool(authority_available),
        "authoritative_total": population_total if authority_available else None,
        "audit_population_total": population_total,
        "detailed_rows_returned": population_total if detailed_rows_returned is None else detailed_rows_returned,
        "detail_limit": detail_limit,
        "legacy_artifacts_inspected": 0 if authority_available else population_total,
        "source_material_available": sum(1 for a in rows if a.source_material_available),
        "translated_candidate_material_available": sum(1 for a in rows if a.translated_candidate_material_available),
        "final_published_material_available": sum(1 for a in rows if a.final_published_material_available),
        "published_material_available": sum(1 for a in rows if a.published_material_available),
        "comparative_pairs_available": sum(1 for a in rows if a.comparative_pair_available),
        "missing_source_material": sum(1 for a in rows if not a.source_material_available),
        "missing_final_published_material": sum(1 for a in rows if not a.final_published_material_available),
        "missing_published_material": sum(1 for a in rows if not a.published_material_available),
    }

def markdown_report(rows: list[ArticleAudit], hours: int, generated_at: str, authority_available: bool = True, detail_rows: list[ArticleAudit] | None = None, detail_limit: int | None = None) -> str:
    detail_rows = rows if detail_rows is None else detail_rows
    issue_counts = Counter(i for a in rows for i in a.issues)
    warning_counts = Counter(alfred_warning_code(w) or render_alfred_warning(w) for a in rows for w in a.alfred_warnings)
    severity_counts = Counter(issue_severity(i) for a in rows for i in a.issues)
    technical_warning_counts = Counter(alfred_warning_code(w) or render_alfred_warning(w) for a in rows for w in a.alfred_warnings if alfred_warning_severity(w) == "technical")
    review_population = [a for a in rows if needs_human_review(a)]
    review_detail = [a for a in detail_rows if needs_human_review(a)]
    coverage = audit_coverage(rows, authority_available, len(detail_rows), detail_limit)
    lines = [f"# OpenWrestlingTV Translation Quality Audit ({hours}h)", "", f"Generated: {generated_at}", "", "## 1. Summary", "", f"- Articles/reports inspected: {len(rows)}", f"- Articles needing human review: {len(review_population)}", f"- Human-review articles shown: {len(review_detail)} of {len(review_population)}", f"- Publication authority available: {coverage['publication_authority_available']}", f"- Authoritative publications: {coverage['authoritative_total']}", f"- Legacy artifacts inspected: {coverage['legacy_artifacts_inspected']}", f"- Audit population total: {coverage['audit_population_total']}", f"- Detailed articles shown: {coverage['detailed_rows_returned']}", f"- Detail limit: {coverage['detail_limit']}", f"- Source material available: {coverage['source_material_available']}", f"- Translated candidate material available: {coverage['translated_candidate_material_available']}", f"- Final published material available: {coverage['final_published_material_available']}", f"- Comparative pairs available: {coverage['comparative_pairs_available']}", f"- Missing source material: {coverage['missing_source_material']}", f"- Missing final published material: {coverage['missing_final_published_material']}", f"- Distinct deterministic issue types: {len(issue_counts)}", f"- Distinct Alfred warnings: {len(warning_counts)}", "", "### Severity summary", ""]
    lines += [f"- {k}: {v}" for k, v in sorted(severity_counts.items())] or ["- None detected."]
    lines += ["", "## 2. Top recurring issues", ""]
    lines += [f"- {k}: {v}" for k, v in issue_counts.most_common(20)] or ["- None detected."]
    lines += ["", "## 3. Alfred warning aggregation", ""]
    lines += [f"- {k}: {v}" for k, v in warning_counts.most_common(30)] or ["- None found in available artifacts."]
    lines += ["", "## 4. Technical/media warnings", ""]
    lines += [f"- {k}: {v}" for k, v in technical_warning_counts.most_common(30)] or ["- None found in available artifacts."]
    lines += ["", "## 5. Articles needing human review", ""]
    if review_detail:
        lines.append("| Title | Source URL | WP link | Issues | Severities | Alfred warnings | Artifacts |")
        lines.append("|---|---|---|---|---|---|---|")
        for a in review_detail[:50]:
            severities = ", ".join(f"{issue}:{issue_severity(issue)}" for issue in a.issues)
            lines.append(f"| {esc(a.title)} | {esc(a.source_url)} | {esc(a.wp_link)} | {esc(', '.join(a.issues))} | {esc(severities)} | {esc(', '.join(render_alfred_warning(w) for w in a.alfred_warnings))} | {esc(', '.join(a.artifact_paths[:4]))} |")
    else:
        lines.append("- None detected.")
    fp = [(a, w) for a in detail_rows for w in a.possible_false_positive_warnings]
    lines += ["", "## 6. Possible false-positive warning candidates", ""]
    lines += [f"- {esc(a.title)}: {render_alfred_warning(w)}" for a, w in fp[:30]] or ["- None detected."]
    lines += ["", "## 7. Suggested prompt/guardrail refinements", ""]
    suggestions = {
        "source_intro_leaked": "Add a deterministic strip-list for source boilerplate intros and newsletter/subscription language before translation.",
        "source_promo_leaked": "Strengthen prompt language and post-processing filters against ads, affiliate, merch, app, and promo-code copy.",
        "ai_style_filler": "Ask Bob to avoid generic transition/conclusion filler and add a final regex lint for recurring AI-style phrases.",
        "official_title_translated": "Maintain a protected glossary of WWE/AEW/TNA/ROH championship and event names that must remain official.",
        "mojibake_or_broken_accents": "Add UTF-8 normalization/repair checks before review packaging and before WordPress publication.",
        "published_text_too_short_vs_original": "Review summarization thresholds for long source items; require preserving all material facts when adapting.",
        "betting_odds_article_published": "Consider a hard diagnostic guardrail for sportsbook/odds-only stories unless editorially approved.",
    }
    for issue, text in suggestions.items():
        if issue in issue_counts:
            lines.append(f"- {issue}: {text}")
    if not any(issue in issue_counts for issue in suggestions):
        lines.append("- No recurring deterministic issue exceeded the available-artifact threshold.")
    return "\n".join(lines) + "\n"


def esc(v: Any) -> str:
    return str(v or "").replace("|", "\\|").replace("\n", " ")[:300]


def build_audit(hours: int = 24, limit: int | None = None, output_dir: str | Path | None = None, root: Path = ROOT) -> tuple[dict[str, Any], Path, Path]:
    rows = discover(root, hours, None)
    detail_rows = rows[:limit] if limit else rows
    metadata = getattr(discover, "last_metadata", {"publication_authority_available": True})
    authority_available = bool(metadata.get("publication_authority_available"))
    generated_at = utc_now().isoformat()
    payload = {"artifact_marker": "owtv_translation_quality_audit_v1", "generated_at": generated_at, "hours": hours, "count": len(detail_rows), "coverage": audit_coverage(rows, authority_available, len(detail_rows), limit), "articles": [article_payload(a) for a in detail_rows]}
    latest = root / "state" / "reports" / "owtv_translation_quality_audit_latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outdir = Path(output_dir) if output_dir else DEFAULT_REPORTS_DIR
    if not outdir.is_absolute():
        outdir = root / outdir
    outdir.mkdir(parents=True, exist_ok=True)
    ts = generated_at.replace(":", "").replace("+", "Z").split(".")[0]
    md_path = outdir / f"owtv_translation_quality_audit_{hours}h_{ts}.md"
    md_path.write_text(markdown_report(rows, hours, generated_at, authority_available, detail_rows, limit), encoding="utf-8")
    return payload, latest, md_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnostic OpenWrestlingTV translation quality audit")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--output-dir", default=str(DEFAULT_REPORTS_DIR))
    args = ap.parse_args()
    payload, latest, md = build_audit(args.hours, args.limit, args.output_dir)
    print(f"Inspected {payload['count']} articles/reports")
    print(f"JSON: {latest}")
    print(f"Markdown: {md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
