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
import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORTS_DIR = ROOT / "reports"

SOURCE_INTRO_RE = re.compile(r"\b(?:welcome to|thanks for (?:reading|watching)|follow us|subscribe|sign up|newsletter|our coverage|this article originally|according to (?:the|a) report below)\b", re.I)
SOURCE_PROMO_RE = re.compile(r"\b(?:use promo code|affiliate|shop now|buy tickets|click here|subscribe to|patreon|merch|official store|download our app|exclusive offer)\b", re.I)
AI_FILLER_RE = re.compile(r"\b(?:it remains to be seen|only time will tell|fans will have to wait and see|what happens next|needless to say|at the end of the day|in the world of professional wrestling|the wrestling world is buzzing)\b", re.I)
WRESTLING_LEXICON_RE = re.compile(r"\b(?:lotta libera|lotta professionale|tallone\b|volto\b|babyface tradotto|promozi?one (?:del wrestler|sul ring)|prenotazione creativa)\b", re.I)
OFFICIAL_TITLE_RE = re.compile(r"\b(?:campionato universale|campione universale indiscusso|campionato intercontinentale|campionato degli stati uniti|titolo mondiale dei pesi massimi|campionato femminile)\b", re.I)
ENGLISH_RESIDUAL_RE = re.compile(r"\b(?:said|according to|sources? told|newsletter|backstage|booking|creative plans|main event|tag team|title shot|pay[- ]per[- ]view)\b", re.I)
MOJIBAKE_RE = re.compile(r"(?:Ã.|Â.|â€™|â€œ|â€\x9d|�|\bperchÃ|\bcosÃ|\bpiÃ|\bE\'\s)" )
BETTING_RE = re.compile(r"\b(?:betting odds|oddschecker|draftkings|fanduel|bet365|sportsbook|scommess[ae]|quote (?:scommesse|betting)|favorit[oi] secondo i bookmaker)\b", re.I)
LONG_QUOTE_RE = re.compile(r"[\"“”'‘’][^\"“”'‘’]{180,}[\"“”'‘’]")


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
    raw = re.sub(r"^(?:v\d+[_-])?(?:news|publisher|bob|alfred)[_-]", "", raw, flags=re.I)
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
    original_text_length: int = 0
    published_text_length: int = 0
    original_paragraph_count: int = 0
    published_paragraph_count: int = 0
    quote_count: int = 0
    blockquote_count: int = 0
    alfred_warnings: list[str] = field(default_factory=list)
    article_type: str = ""
    priority: str = ""
    score: Any = ""
    artifact_paths: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    possible_false_positive_warnings: list[str] = field(default_factory=list)


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


def item_key(item: dict[str, Any], path: Path | None = None) -> str:
    return norm_url(first(item, "source_url", "url", "original_url", "link")) or slugify(first(item, "wp_link", "published_url", "title", "title_it", "source_title") or (path.name if path else ""))


def merge_item(a: ArticleAudit, item: dict[str, Any], relpath: str) -> None:
    a.title = a.title or str(first(item, "title_it", "published_title", "title"))
    a.source_url = a.source_url or norm_url(first(item, "source_url", "url", "original_url"))
    a.wp_link = a.wp_link or str(first(item, "wp_link", "published_url", "final_url", "wordpress_url"))
    a.source_title = a.source_title or str(first(item, "source_title", "original_title", "headline"))
    text = str(first(item, "original_text", "source_text", "extracted_text", "article_text", "content_text"))
    if text and len(text) > len(a.original_text):
        a.original_text = text
    a.article_type = a.article_type or str(first(item, "article_type", "type", "kind"))
    a.priority = a.priority or str(first(item, "priority", "priority_label"))
    a.score = a.score or first(item, "score", "quality_score", "news_score")
    warnings = first(item, "alfred_warnings", "warnings", "warning_codes", "issues")
    if isinstance(warnings, list):
        a.alfred_warnings.extend(str(w) for w in warnings if w)
    elif isinstance(warnings, str) and warnings:
        a.alfred_warnings.append(warnings)
    if relpath not in a.artifact_paths:
        a.artifact_paths.append(relpath)


def discover(root: Path, hours: int, limit: int | None) -> list[ArticleAudit]:
    since = utc_now() - timedelta(hours=hours)
    articles: dict[str, ArticleAudit] = {}
    candidates = [root / "state" / "newsroom" / "master_log.jsonl"]
    for base in [root / "artifacts" / "newsroom", root / "artifacts" / "newsroom_runs", root / "review_packages", root / "state" / "newsroom"]:
        if base.exists():
            candidates.extend([p for p in base.rglob("*.json*") if p.is_file()])
    for p in candidates:
        if not p.exists() or (parse_dt(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()) or utc_now()) < since:
            continue
        rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
        for item in iter_json_objects(p):
            key = item_key(item, p)
            if not key:
                continue
            a = articles.setdefault(key, ArticleAudit(key=key))
            merge_item(a, item, rel)
    for base in [root / "published_html_review", root / "review_packages"]:
        if not base.exists():
            continue
        for p in base.rglob("*.html"):
            if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < since:
                continue
            raw = p.read_text(encoding="utf-8", errors="replace")
            st = html_stats(raw)
            key = slugify(p.name)
            # Prefer existing URL/title match when possible, otherwise file slug.
            a = articles.setdefault(key, ArticleAudit(key=key))
            a.title = a.title or st["title"] or slugify(p.name).replace("-", " ").title()
            a.published_text = st["text"] if len(st["text"]) > len(a.published_text) else a.published_text
            a.published_text_length = max(a.published_text_length, st["text_length"])
            a.published_paragraph_count = max(a.published_paragraph_count, st["paragraph_count"])
            a.blockquote_count = max(a.blockquote_count, st["blockquote_count"])
            a.quote_count = max(a.quote_count, st["quote_count"])
            rel = str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
            if rel not in a.artifact_paths:
                a.artifact_paths.append(rel)
    rows = list(articles.values())
    for a in rows:
        if a.original_text:
            a.original_text_length = len(" ".join(a.original_text.split()))
            a.original_paragraph_count = len([x for x in re.split(r"\n\s*\n", a.original_text) if x.strip()]) or (1 if a.original_text.strip() else 0)
        run_checks(a)
    rows.sort(key=lambda x: (len(x.issues), x.published_text_length), reverse=True)
    return rows[:limit] if limit else rows


def run_checks(a: ArticleAudit) -> None:
    issues: list[str] = []
    if a.original_text_length >= 800 and a.published_text_length and a.published_text_length < a.original_text_length * 0.45:
        issues.append("published_text_too_short_vs_original")
    if a.original_paragraph_count >= 5 and a.published_paragraph_count and a.published_paragraph_count <= max(1, a.original_paragraph_count // 2):
        issues.append("paragraph_count_drop")
    if a.original_text.count('"') >= 4 and a.blockquote_count == 0 and a.published_text.count('"') < a.original_text.count('"') / 2:
        issues.append("quote_count_mismatch")
    if LONG_QUOTE_RE.search(a.published_text) and a.blockquote_count == 0:
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
    for w in a.alfred_warnings:
        if "bet" in w.lower() and not BETTING_RE.search(f"{a.title} {text}"):
            a.possible_false_positive_warnings.append(w)


def markdown_report(rows: list[ArticleAudit], hours: int, generated_at: str) -> str:
    issue_counts = Counter(i for a in rows for i in a.issues)
    warning_counts = Counter(w for a in rows for w in a.alfred_warnings)
    review = [a for a in rows if a.issues or a.alfred_warnings]
    lines = [f"# OpenWrestlingTV Translation Quality Audit ({hours}h)", "", f"Generated: {generated_at}", "", "## 1. Summary", "", f"- Articles/reports inspected: {len(rows)}", f"- Articles needing human review: {len(review)}", f"- Distinct deterministic issue types: {len(issue_counts)}", f"- Distinct Alfred warnings: {len(warning_counts)}", "", "## 2. Top recurring issues", ""]
    lines += [f"- {k}: {v}" for k, v in issue_counts.most_common(20)] or ["- None detected."]
    lines += ["", "## 3. Alfred warning aggregation", ""]
    lines += [f"- {k}: {v}" for k, v in warning_counts.most_common(30)] or ["- None found in available artifacts."]
    lines += ["", "## 4. Articles needing human review", ""]
    if review:
        lines.append("| Title | Source URL | WP link | Issues | Alfred warnings | Artifacts |")
        lines.append("|---|---|---|---|---|---|")
        for a in review[:50]:
            lines.append(f"| {esc(a.title)} | {esc(a.source_url)} | {esc(a.wp_link)} | {esc(', '.join(a.issues))} | {esc(', '.join(a.alfred_warnings))} | {esc(', '.join(a.artifact_paths[:4]))} |")
    else:
        lines.append("- None detected.")
    fp = [(a, w) for a in rows for w in a.possible_false_positive_warnings]
    lines += ["", "## 5. Possible false-positive warning candidates", ""]
    lines += [f"- {esc(a.title)}: {esc(w)}" for a, w in fp[:30]] or ["- None detected."]
    lines += ["", "## 6. Suggested prompt/guardrail refinements", ""]
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
    rows = discover(root, hours, limit)
    generated_at = utc_now().isoformat()
    payload = {"artifact_marker": "owtv_translation_quality_audit_v1", "generated_at": generated_at, "hours": hours, "count": len(rows), "articles": [asdict(a) for a in rows]}
    latest = root / "state" / "reports" / "owtv_translation_quality_audit_latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outdir = Path(output_dir) if output_dir else DEFAULT_REPORTS_DIR
    if not outdir.is_absolute():
        outdir = root / outdir
    outdir.mkdir(parents=True, exist_ok=True)
    ts = generated_at.replace(":", "").replace("+", "Z").split(".")[0]
    md_path = outdir / f"owtv_translation_quality_audit_{hours}h_{ts}.md"
    md_path.write_text(markdown_report(rows, hours, generated_at), encoding="utf-8")
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
