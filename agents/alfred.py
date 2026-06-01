from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

BOB_ARTICLES_FILE = NEWSROOM_STATE_DIR / "bob_articles_latest.json"
ALFRED_REVIEW_FILE = NEWSROOM_STATE_DIR / "alfred_review_latest.json"
ARTIFACT_ALFRED_FILE = ARTIFACT_DIR / "alfred_review.json"

ALFRED_VERSION = "v93_5_1_conservative_quality_editor"

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

ALLOWED_ENGLISH_TERMS = {
    "raw", "nxt", "aew", "wwe", "tna", "roh", "aaa", "evolve", "money in the bank",
    "worlds collide", "mask vs. mask", "fatal 5-way", "main roster", "call-up", "title shot",
    "booking", "storyline", "stable", "push", "turn", "premium live event", "dirty dom",
}

IMAGE_INLINE_RE = re.compile(r"<p>\s*(<!--IMAGE:[^>]+-->)\s*([^<\s][\s\S]*?)</p>", re.I)
EMBED_INLINE_RE = re.compile(r"<p>\s*(<!--EMBED:[^>]+-->)\s*([^<\s][\s\S]*?)</p>", re.I)


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


def review_article(article: dict[str, Any]) -> dict[str, Any]:
    original_body_html = str(article.get("body_html") or "")
    body_html, placeholder_changes = normalize_placeholders(original_body_html)
    body_html, style_changes = apply_style_normalizations(body_html)
    editorial_changes = placeholder_changes + style_changes

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
    if re.search(r"<script|<iframe|onerror=|onclick=", body_html, re.I):
        issues.append(issue("unsafe_html", "blocker", "HTML potenzialmente non sicuro nel corpo articolo."))

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
    if int(element_counts.get("text", 0) or 0) == 0:
        issues.append(issue("no_text_elements", "blocker", "Bob non ha fornito blocchi testuali puliti."))

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
        },
    }


def run_alfred(bob_result: dict[str, Any] | None = None) -> dict[str, Any]:
    bob = bob_result if isinstance(bob_result, dict) else load_json(BOB_ARTICLES_FILE, {})
    articles = bob.get("articles", []) if isinstance(bob, dict) else []
    if not isinstance(articles, list):
        articles = []
    print(f"[ALFRED v93.5] Avvio revisione qualità | articles={len(articles)}", flush=True)
    reviews = [review_article(article) for article in articles if isinstance(article, dict)]
    approved = [r["approved_article"] for r in reviews if r.get("decision") == "approved" and r.get("approved_article")]
    result = {
        "agent": "Alfred",
        "version": ALFRED_VERSION,
        "generated_at": utc_now(),
        "mode": "conservative_quality_editor",
        "input": {
            "bob_version": bob.get("version") if isinstance(bob, dict) else None,
            "articles": len(articles),
        },
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
            "checks": [
                "untranslated_quotes",
                "cta_residue",
                "source_credit_residue",
                "unsafe_html",
                "missing_or_short_body",
                "image_embed_placeholders",
                "title_clickbait_or_length",
            ],
            "deterministic_normalizations": [
                "split_inline_image_embed_placeholders",
                "funzionari_wwe_to_dirigenti_wwe",
            ],
            "ai_used": False,
            "auto_rewrite": False,
            "conservative_mode": True,
        },
    }
    write_json(ARTIFACT_ALFRED_FILE, result)
    write_json(ALFRED_REVIEW_FILE, result)
    print(
        "[ALFRED v93.5] Revisione pronta | "
        f"approved={result['handoff']['approved']} needs_revision={result['handoff']['needs_revision']} "
        f"blockers={result['handoff']['blockers']} warnings={result['handoff']['warnings']} "
        f"changes={result['handoff']['editorial_changes']}",
        flush=True,
    )
    return result


if __name__ == "__main__":
    out = run_alfred()
    print(json.dumps(out.get("handoff", {}), ensure_ascii=False, indent=2))
