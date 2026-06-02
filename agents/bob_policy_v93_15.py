from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from agents.bob import run_bob as base_run_bob

ROOT = Path(__file__).resolve().parents[1]
NEWSROOM_STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
BOB_ARTICLES_FILE = NEWSROOM_STATE_DIR / "bob_articles_latest.json"
ARTIFACT_BOB_FILE = ARTIFACT_DIR / "bob_articles.json"

VERSION = "v93_15_bob_residual_cleanup_quote_split"

RESIDUAL_BIO_PATTERNS = [
    re.compile(r"\b(felix\s+upton|steve\s+carrier)\b.*\b(ringside\s+news|esperienza|fondatore|giornalismo|wrestling)\b", re.I),
    re.compile(r"\b(ha\s+oltre|vanta\s+oltre)\s+\d+\s+anni\s+di\s+esperienza\b", re.I),
    re.compile(r"\bfondatore\s+di\s+ringside\s+news\b", re.I),
    re.compile(r"\b(le|i)\s+sue\s+(storie|articoli|notizie)\s+sono\s+state\s+pubblicate\b", re.I),
    re.compile(r"\b(tmz|forbes|bleacher\s+report)\b.*\b(ringside\s+news|pubblicate|riprese)\b", re.I),
    re.compile(r"\bsegu(i|ilo|ici)\s+.+\s+su\s+(x|twitter|instagram|facebook|bluesky)\b", re.I),
]
CTA_PATTERNS = [
    re.compile(r"\bfateci\s+sapere\b|\bdicci\s+la\s+tua\b|\bcosa\s+ne\s+pensate\b", re.I),
    re.compile(r"\bcommenti\s+qui\s+sotto\b|\blascia\s+un\s+commento\b", re.I),
]
QUOTE_RE = re.compile(r"(.*?)([“\"]([^”\"]{35,})[”\"])(.*)", re.S)
P_RE = re.compile(r"<p>(.*?)</p>", re.S | re.I)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(value or ""))


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(value)).strip()


def should_remove_paragraph(inner: str) -> str:
    text = clean_text(inner)
    for pattern in RESIDUAL_BIO_PATTERNS:
        if pattern.search(text):
            return "residual_author_bio"
    for pattern in CTA_PATTERNS:
        if pattern.search(text):
            return "residual_cta"
    return ""


def split_quote_paragraph(inner: str) -> str | None:
    text = html.unescape(re.sub(r"<[^>]+>", "", inner or "")).strip()
    m = QUOTE_RE.match(text)
    if not m:
        return None
    before, quote, _quote_inner, after = m.groups()
    before = before.strip()
    quote = quote.strip()
    after = after.strip()
    if not quote or len(_quote_inner.strip()) < 35:
        return None
    parts: list[str] = []
    if before:
        parts.append(f"<p>{html.escape(before)}</p>")
    parts.append(f"<blockquote>{html.escape(quote)}</blockquote>")
    if after:
        parts.append(f"<p>{html.escape(after)}</p>")
    return "\n".join(parts)


def postprocess_body(body_html: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        remove_reason = should_remove_paragraph(inner)
        if remove_reason:
            changes.append({"code": remove_reason, "severity": "info", "message": "Paragrafo residuo rimosso da Bob v93.15.", "evidence": clean_text(inner)[:300]})
            return ""
        split = split_quote_paragraph(inner)
        if split:
            changes.append({"code": "inline_quote_split", "severity": "info", "message": "Citazione tra virgolette separata in blockquote dedicato.", "evidence": clean_text(inner)[:300]})
            return split
        return match.group(0)

    body_html = P_RE.sub(repl, body_html or "")
    body_html = re.sub(r"\n{3,}", "\n\n", body_html).strip()
    return body_html, changes


def run_bob(menzo_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    result = base_run_bob(menzo_decision)
    total_changes = 0
    for article in result.get("articles", []) if isinstance(result, dict) else []:
        if not isinstance(article, dict):
            continue
        body, changes = postprocess_body(str(article.get("body_html") or ""))
        if changes:
            article["body_html"] = body
            article.setdefault("editorial_changes", []).extend(changes)
            article.setdefault("diagnostic_warnings", [])
            total_changes += len(changes)
    result["version"] = VERSION
    result.setdefault("policy", {})["residual_author_bio_cleanup"] = True
    result.setdefault("policy", {})["split_inline_quoted_text"] = True
    result.setdefault("postprocess", {})["bob_v93_15_changes"] = total_changes
    write_json(ARTIFACT_BOB_FILE, result)
    write_json(BOB_ARTICLES_FILE, result)
    print(f"[BOB v93.15] Cleanup finale applicato | changes={total_changes}", flush=True)
    return result
