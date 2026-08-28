from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.translation_validation import excerpt_translation_evidence, language_escape_evidence, plain_text

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

BOB_ARTICLES_FILE = NEWSROOM_STATE_DIR / "bob_articles_latest.json"
ALFRED_REVIEW_FILE = NEWSROOM_STATE_DIR / "alfred_review_latest.json"
ARTIFACT_ALFRED_FILE = ARTIFACT_DIR / "alfred_review.json"

ALFRED_VERSION = "v93_8_alfred_structured_content_checks"

CTA_PATTERNS = [
    re.compile(r"\b(fateci sapere|dicci la tua|lascia un commento|commenti qui sotto|cosa ne pensate)\b", re.I),
    re.compile(r"\b(sound off|let us know|share your thoughts|what do you think)\b", re.I),
    re.compile(r"\b(iscriviti|newsletter|seguici su|connect with us|add as a preferred source)\b", re.I),
]

SOURCE_CREDIT_PATTERNS = [
    re.compile(r"\bh/?t\s+(to|a)\b", re.I),
    re.compile(r"\bfor the transcription\b", re.I),
    re.compile(r"\bplease credit\b", re.I),
    re.compile(r"\bper la trascrizione\b", re.I),
    re.compile(r"\btutto lo staff di wrestling inc\.? augura\b", re.I),
]

CLICKBAIT_TITLE_PATTERNS = [
    re.compile(r"\bshock\b", re.I),
    re.compile(r"\bclamoroso\b", re.I),
    re.compile(r"\bincredibile\b", re.I),
    re.compile(r"\bnon ci crederai\b", re.I),
]

STYLE_NORMALIZATIONS = [
    (re.compile(r"\bfunzionari\s+della\s+WWE\b", re.I), "dirigenti WWE"),
    (re.compile(r"\bfunzionari\s+WWE\b", re.I), "dirigenti WWE"),
]

ENGLISH_COMMON_WORDS = {
    "the", "and", "that", "with", "from", "this", "while", "will", "would", "could", "should",
    "likely", "several", "months", "good", "worse", "time", "work", "working", "expected",
    "returning", "injury", "officials", "learned", "appear", "future", "foreseeable",
}

IMAGE_INLINE_RE = re.compile(r"<p>\s*(<!--IMAGE:[^>]+-->)\s*([^<\s][\s\S]*?)</p>", re.I)
EMBED_INLINE_RE = re.compile(r"<p>\s*(<!--EMBED:[^>]+-->)\s*([^<\s][\s\S]*?)</p>", re.I)
LONG_QUOTE_PARAGRAPH_RE = re.compile(r"<p>\s*[“\"][\s\S]{90,}?[”\"][\s\S]*?</p>", re.I)
TABLE_HEADING_RE = re.compile(r"\b(ascolti|viewership|rating|dati|prestazioni|confronto|range|media mobile|ultimi 12 mesi)\b", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def extract_quoted_segments(text: str) -> list[str]:
    segments: list[str] = []
    for pattern in [r"\"([^\"]{8,})\"", r"“([^”]{8,})”", r"'([^']{8,})'"]:
        segments.extend(re.findall(pattern, text or ""))
    return segments


def likely_english(text: str) -> bool:
    lowered = (text or "").lower()
    words = re.findall(r"[a-zA-Z']+", lowered)
    if len(words) < 4:
        return False
    hits = sum(1 for word in words if word in ENGLISH_COMMON_WORDS)
    return hits >= 3 or (hits >= 2 and len(words) <= 9)


def issue(code: str, severity: str, message: str, evidence: str = "") -> dict[str, str]:
    out = {"code": code, "severity": severity, "message": message}
    if evidence:
        out["evidence"] = evidence[:700]
    return out


def normalize_placeholders(body_html: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []

    def image_repl(match: re.Match[str]) -> str:
        changes.append(issue("image_placeholder_split", "info", "Placeholder immagine separato dal paragrafo di testo.", match.group(1)))
        return f"{match.group(1)}\n<p>{match.group(2).strip()}</p>"

    def embed_repl(match: re.Match[str]) -> str:
        changes.append(issue("embed_placeholder_split", "info", "Placeholder embed separato dal paragrafo di testo.", match.group(1)))
        return f"{match.group(1)}\n<p>{match.group(2).strip()}</p>"

    body_html = IMAGE_INLINE_RE.sub(image_repl, body_html)
    body_html = EMBED_INLINE_RE.sub(embed_repl, body_html)
    return body_html, changes


def apply_style_normalizations(body_html: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []
    for pattern, replacement in STYLE_NORMALIZATIONS:
        if pattern.search(body_html):
            body_html = pattern.sub(replacement, body_html)
            changes.append(issue("style_normalization", "info", f"Normalizzato in '{replacement}'.", pattern.pattern))
    return body_html, changes


def normalize_quote_paragraphs(body_html: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []

    def repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        inner = re.sub(r"^<p>\s*|\s*</p>$", "", raw, flags=re.I).strip()
        changes.append(issue("quote_paragraph_to_blockquote", "info", "Citazione lunga convertita in blockquote.", clean_text(inner)[:350]))
        return f"<blockquote>{inner}</blockquote>"

    body_html = LONG_QUOTE_PARAGRAPH_RE.sub(repl, body_html or "")
    return body_html, changes


def review_article(article: dict[str, Any]) -> dict[str, Any]:
    original_body_html = str(article.get("body_html") or "")
    body_html, placeholder_changes = normalize_placeholders(original_body_html)
    body_html, quote_changes = normalize_quote_paragraphs(body_html)
    body_html, style_changes = apply_style_normalizations(body_html)
    editorial_changes = placeholder_changes + quote_changes + style_changes

    title = clean_text(str(article.get("title_it") or ""))
    plain = clean_text(body_html)
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if article.get("status") != "ready_for_alfred":
        issues.append(issue("bob_not_ready", "blocker", "Bob non ha consegnato l'articolo come ready_for_alfred.", str(article.get("status"))))
    if not title:
        issues.append(issue("missing_title", "blocker", "Titolo italiano mancante."))
    if not body_html or len(plain) < 350:
        issues.append(issue("body_too_short", "blocker", "Corpo articolo mancante o troppo corto.", plain[:300]))
    if "<!--IMAGE:" in body_html:
        warnings.append(issue("image_placeholder_present", "warning", "Presente placeholder immagine da gestire nel Publisher.", "<!--IMAGE:...-->"))
    if "<!--EMBED:" in body_html:
        warnings.append(issue("embed_placeholder_present", "warning", "Presente placeholder embed da gestire nel Publisher.", "<!--EMBED:...-->"))
    if "<script" in body_html.lower():
        issues.append(issue("unsafe_html", "blocker", "HTML non consentito nel corpo articolo."))

    source_units = {}
    for element in article.get("elements", []) if isinstance(article.get("elements"), list) else []:
        if isinstance(element, dict) and element.get("block_id") and element.get("text"):
            source_units[str(element["block_id"])] = str(element["text"])
    meta = article.get("meta") if isinstance(article.get("meta"), dict) else {}
    excerpt_value = article.get("excerpt_it")
    excerpt = clean_text(str(excerpt_value or ""))
    excerpt_evidence = excerpt_translation_evidence(str(meta.get("description") or ""), excerpt)
    evidence = language_escape_evidence(
        str(meta.get("source_title") or article.get("source_title") or ""),
        title,
        source_units,
        {"body": plain_text(body_html)},
        [("page", str(meta.get("source_title") or "")), ("feed", str(article.get("source_title") or ""))],
    )
    # Direct source comparison is possible when Bob retained ordered elements; the whole-body
    # language check remains a safety net for older or synthetic Bob handoffs.
    if source_units:
        source_plain = " ".join(source_units.values())
        direct = language_escape_evidence("", "", {"body": source_plain}, {"body": plain})
        evidence["body_likely_untranslated"] = evidence["body_likely_untranslated"] or direct["body_likely_untranslated"]
        evidence["body_substantially_unchanged"] = evidence["body_substantially_unchanged"] or direct["body_substantially_unchanged"]
        evidence.update({k: direct[k] for k in ("exact_body_unchanged", "near_identical_body", "source_output_similarity", "residual_english_body")})
    if evidence["body_substantially_unchanged"]:
        issues.append(issue("untranslated_body", "blocker", "Corpo sostanzialmente invariato rispetto alla fonte inglese.", plain[:700]))
    elif evidence["residual_english_body"]:
        issues.append(issue("residual_english_body", "blocker", "Corpo composto macroscopicamente da prosa inglese.", plain[:700]))
    if evidence["title_likely_untranslated"]:
        issues.append(issue("untranslated_title", "blocker", "Titolo chiaramente inglese e invariato rispetto alla fonte.", title))
    if excerpt_evidence["excerpt_likely_untranslated"]:
        issues.append(issue("untranslated_excerpt", "blocker", "Excerpt sostanzialmente invariato rispetto alla descrizione inglese.", excerpt))
    elif excerpt_evidence["excerpt_residual_english"]:
        issues.append(issue("residual_english_excerpt", "blocker", "Excerpt composto da prosa inglese.", excerpt))

    for pattern in CTA_PATTERNS:
        match = pattern.search(plain)
        if match:
            issues.append(issue("cta_residue", "blocker", "Residuo di CTA/comment bait nel testo italiano.", match.group(0)))
            break
    for pattern in SOURCE_CREDIT_PATTERNS:
        match = pattern.search(plain)
        if match:
            issues.append(issue("source_credit_residue", "blocker", "Residuo di credito/trascrizione del sito fonte nel testo italiano.", match.group(0)))
            break

    for segment in extract_quoted_segments(plain):
        if likely_english(segment):
            issues.append(issue("untranslated_quote", "blocker", "Citazione rimasta in inglese o non tradotta integralmente.", segment))
            break

    for pattern in CLICKBAIT_TITLE_PATTERNS:
        match = pattern.search(title)
        if match:
            warnings.append(issue("clickbait_title", "warning", "Titolo potenzialmente clickbait.", title))
            break
    if len(title) > 95:
        warnings.append(issue("title_too_long", "warning", "Titolo probabilmente troppo lungo per SEO/social.", title))

    element_counts = article.get("element_counts", {}) if isinstance(article.get("element_counts"), dict) else {}
    quote_count = int(element_counts.get("quote", 0) or 0)
    table_count = int(element_counts.get("table", 0) or 0)
    if int(element_counts.get("text", 0) or 0) == 0:
        issues.append(issue("no_text_elements", "blocker", "Bob non ha fornito blocchi testuali puliti."))
    if quote_count > 0 and "<blockquote" not in body_html.lower():
        issues.append(issue("quote_semantics_lost", "blocker", "Bob ha estratto citazioni ma il body non contiene blockquote.", title))
    if table_count > 0 and "<table" not in body_html.lower():
        issues.append(issue("table_semantics_lost", "blocker", "Bob ha estratto tabelle ma il body non contiene table HTML.", title))
    if table_count == 0 and TABLE_HEADING_RE.search(body_html):
        warnings.append(issue("possible_missing_table", "warning", "Articolo con dati potenzialmente tabellari ma nessuna tabella estratta.", title))

    blockers = [i for i in issues if i.get("severity") == "blocker"]
    score = 100 - 25 * len(blockers) - 5 * len(warnings)
    score = max(0, min(100, score))
    decision = "approved" if not blockers else "needs_revision"

    return {
        "source_url": article.get("source_url"),
        "source": article.get("source"),
        "category_hint": article.get("category_hint"),
        "title_it": title,
        "decision": decision,
        "quality_score": score,
        "issues": issues,
        "warnings": warnings,
        "editorial_changes": editorial_changes,
        "approved_article": {
            "source_url": article.get("source_url"),
            "source_title": article.get("source_title"),
            "title_it": title,
            "body_html": body_html,
            "excerpt_it": article.get("excerpt_it"),
            "category_hint": article.get("category_hint"),
            "source": article.get("source"),
            "meta": article.get("meta"),
            "element_counts": element_counts,
            "bob_translation_model": article.get("translation_model"),
            **{k: article[k] for k in ["canonical_source_body", "menzo_duplicate_checked", "menzo_duplicate_scope", "menzo_duplicate_decision", "menzo_authorized", "menzo_compared_with_url", "menzo_duplicate_reason", "menzo_new_fact", "menzo_winner_url", "menzo_duplicate_audit", "menzo_duplicate_comparisons"] if k in article},
        } if decision == "approved" else None,
        "diagnostics": {
            "plain_chars": len(plain),
            "title_chars": len(title),
            "bob_status": article.get("status"),
            "bob_diagnostic_stage": article.get("diagnostic_stage"),
            "bob_removed_before_gemini": article.get("removed_before_gemini"),
            "bob_clean_element_count": article.get("clean_element_count"),
            "bob_translation_model": article.get("translation_model"),
            "editorial_changes": len(editorial_changes),
            "quote_count": quote_count,
            "table_count": table_count,
            "translation_escape_evidence": evidence,
            "excerpt_translation_evidence": excerpt_evidence,
            "bob_translation_validation": article.get("translation_validation") if isinstance(article.get("translation_validation"), dict) else None,
        },
    }


def run_alfred(bob_result: dict[str, Any] | None = None) -> dict[str, Any]:
    bob = bob_result if isinstance(bob_result, dict) else load_json(BOB_ARTICLES_FILE, {})
    articles = bob.get("articles", []) if isinstance(bob, dict) else []
    if not isinstance(articles, list):
        articles = []
    print(f"[ALFRED v93.8] Avvio revisione qualità | articles={len(articles)}", flush=True)
    reviews = [review_article(article) for article in articles if isinstance(article, dict)]
    approved = [r["approved_article"] for r in reviews if r.get("decision") == "approved" and r.get("approved_article")]
    result = {
        "agent": "Alfred",
        "version": ALFRED_VERSION,
        "generated_at": utc_now(),
        "mode": "structured_content_quality_editor",
        "input": {"bob_version": bob.get("version") if isinstance(bob, dict) else None, "articles": len(articles)},
        "reviews": reviews,
        "approved_articles": approved,
        "handoff": {
            "approved": len(approved),
            "needs_revision": sum(1 for r in reviews if r.get("decision") == "needs_revision"),
            "warnings": sum(len(r.get("warnings", [])) for r in reviews),
            "blockers": sum(len(r.get("issues", [])) for r in reviews),
            "editorial_changes": sum(len(r.get("editorial_changes", [])) for r in reviews),
        },
        "policy": {
            "checks": ["untranslated_quotes", "quote_semantics", "table_semantics", "possible_missing_table", "cta_residue", "source_credit_residue", "unsafe_html", "missing_or_short_body", "image_embed_placeholders", "title_clickbait_or_length"],
            "deterministic_normalizations": ["split_inline_image_embed_placeholders", "long_quote_paragraphs_to_blockquote", "funzionari_wwe_to_dirigenti_wwe"],
            "ai_used": False,
            "auto_rewrite": False,
            "conservative_mode": True,
        },
    }
    write_json(ARTIFACT_ALFRED_FILE, result)
    write_json(ALFRED_REVIEW_FILE, result)
    print("[ALFRED v93.8] Revisione pronta | approved={approved} needs_revision={needs_revision} blockers={blockers} warnings={warnings} changes={changes}".format(approved=result["handoff"]["approved"], needs_revision=result["handoff"]["needs_revision"], blockers=result["handoff"]["blockers"], warnings=result["handoff"]["warnings"], changes=result["handoff"]["editorial_changes"]), flush=True)
    return result


if __name__ == "__main__":
    out = run_alfred()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
