from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
PUBLISHED_DIR = ROOT / "published"
REVIEW_DIR = ROOT / "published_html_review"

ARCHIVISTA_REPORT_FILE = NEWSROOM_STATE_DIR / "archivista_report_latest.json"
ARCHIVISTA_LEDGER_FILE = NEWSROOM_STATE_DIR / "archivista_ledger.json"
ARTIFACT_ARCHIVISTA_FILE = ARTIFACT_DIR / "archivista_report.json"
ARTIFACT_ARCHIVISTA_MD = ARTIFACT_DIR / "ARCHIVISTA_REPORT.md"

ARCHIVISTA_VERSION = "v93_7_archivista_audit"
LEDGER_HOURS = 48
PREVIEW_CHARS = 7000


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def utc_now() -> str:
    return utc_now_dt().isoformat()


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


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


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def safe_text(path: Path, limit: int = PREVIEW_CHARS) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")[:limit]
    except Exception:
        return ""
    return ""


def slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:100] or "owtv-news"


def source_key(url: str) -> str:
    raw = str(url or "").strip().lower()
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    return raw.rstrip("/")


def by_source(items: list[dict[str, Any]], url_field: str = "source_url") -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if isinstance(item, dict):
            key = source_key(str(item.get(url_field) or ""))
            if key:
                out[key] = item
    return out


def issue(code: str, severity: str, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if context:
        out["context"] = context
    return out


def make_article_dossiers(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    bob = inputs.get("bob", {}) if isinstance(inputs.get("bob"), dict) else {}
    alfred = inputs.get("alfred", {}) if isinstance(inputs.get("alfred"), dict) else {}
    publisher = inputs.get("publisher", {}) if isinstance(inputs.get("publisher"), dict) else {}
    menzo = inputs.get("menzo", {}) if isinstance(inputs.get("menzo"), dict) else {}

    bob_articles = bob.get("articles", []) if isinstance(bob.get("articles"), list) else []
    alfred_reviews = alfred.get("reviews", []) if isinstance(alfred.get("reviews"), list) else []
    publisher_results = publisher.get("results", []) if isinstance(publisher.get("results"), list) else []
    menzo_selected = menzo.get("selected", []) if isinstance(menzo.get("selected"), list) else []

    bob_map = by_source(bob_articles)
    alfred_map = by_source(alfred_reviews)
    publisher_map = by_source(publisher_results)
    menzo_map = by_source(menzo_selected, "url")
    all_keys = sorted(set(bob_map) | set(alfred_map) | set(publisher_map) | set(menzo_map))

    dossiers: list[dict[str, Any]] = []
    for key in all_keys:
        b = bob_map.get(key, {})
        a = alfred_map.get(key, {})
        p = publisher_map.get(key, {})
        m = menzo_map.get(key, {})
        approved_article = a.get("approved_article") if isinstance(a.get("approved_article"), dict) else {}
        title = str(approved_article.get("title_it") or b.get("title_it") or p.get("title_it") or m.get("title") or "")
        slug = slugify(title)
        review_file = REVIEW_DIR / f"v93_publisher_{slug}.html"
        published_file = PUBLISHED_DIR / f"v93_news_{slug}.html"
        body_bob = str(b.get("body_html") or "")
        body_alfred = str(approved_article.get("body_html") or "")
        dossier = {
            "source_url": key,
            "title_it": title,
            "category_hint": approved_article.get("category_hint") or b.get("category_hint") or m.get("category_hint"),
            "source": approved_article.get("source") or b.get("source") or m.get("source"),
            "menzo": {
                "present": bool(m),
                "score": m.get("score"),
                "classification": m.get("classification") or m.get("bucket"),
                "reason": m.get("reason"),
            },
            "bob": {
                "present": bool(b),
                "status": b.get("status"),
                "diagnostic_stage": b.get("diagnostic_stage"),
                "translation_model": b.get("translation_model"),
                "translation_used": b.get("translation_used"),
                "raw_element_count": b.get("raw_element_count"),
                "clean_element_count": b.get("clean_element_count"),
                "removed_before_gemini": b.get("removed_before_gemini"),
                "element_counts": b.get("element_counts"),
                "error": b.get("error"),
            },
            "alfred": {
                "present": bool(a),
                "decision": a.get("decision"),
                "quality_score": a.get("quality_score"),
                "issues": a.get("issues", []),
                "warnings": a.get("warnings", []),
                "editorial_changes": a.get("editorial_changes", []),
            },
            "publisher": {
                "present": bool(p),
                "status": p.get("status"),
                "wp_post_id": p.get("wp_post_id"),
                "wp_link": p.get("wp_link"),
                "featured_media": p.get("featured_media"),
                "categories": p.get("categories"),
                "error": p.get("error"),
            },
            "html_audit": {
                "translation_prompt_preview": str(b.get("translation_prompt_preview") or "")[:PREVIEW_CHARS],
                "bob_body_html_preview": body_bob[:PREVIEW_CHARS],
                "alfred_final_html_preview": body_alfred[:PREVIEW_CHARS],
                "publisher_review_file": str(review_file),
                "publisher_review_html_preview": safe_text(review_file),
                "published_file": str(published_file),
                "published_html_preview": safe_text(published_file),
            },
        }
        dossiers.append(dossier)
    return dossiers


def detect_anomalies(inputs: dict[str, Any], dossiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    massy = inputs.get("massy", {}) if isinstance(inputs.get("massy"), dict) else {}
    menzo = inputs.get("menzo", {}) if isinstance(inputs.get("menzo"), dict) else {}
    bob = inputs.get("bob", {}) if isinstance(inputs.get("bob"), dict) else {}
    alfred = inputs.get("alfred", {}) if isinstance(inputs.get("alfred"), dict) else {}
    publisher = inputs.get("publisher", {}) if isinstance(inputs.get("publisher"), dict) else {}

    for agent_name, data in [("Massy", massy), ("Menzo", menzo), ("Bob", bob), ("Alfred", alfred), ("Publisher", publisher)]:
        if isinstance(data, dict) and data.get("status") == "error":
            anomalies.append(issue("agent_error", "error", f"{agent_name} ha restituito errore.", {"error": data.get("error")}))

    bob_h = bob.get("handoff", {}) if isinstance(bob.get("handoff"), dict) else {}
    if int(bob_h.get("errors", 0) or 0):
        anomalies.append(issue("bob_errors", "error", "Bob ha prodotto errori di estrazione/traduzione.", bob_h))
    if int(bob_h.get("extraction_empty", 0) or 0):
        anomalies.append(issue("bob_empty", "warning", "Bob ha avuto estrazioni vuote.", bob_h))

    alfred_h = alfred.get("handoff", {}) if isinstance(alfred.get("handoff"), dict) else {}
    if int(alfred_h.get("blockers", 0) or 0):
        anomalies.append(issue("alfred_blockers", "error", "Alfred ha trovato blocker qualitativi.", alfred_h))
    if int(alfred_h.get("needs_revision", 0) or 0):
        anomalies.append(issue("alfred_revision", "warning", "Alfred ha mandato articoli in revisione.", alfred_h))

    publisher_h = publisher.get("handoff", {}) if isinstance(publisher.get("handoff"), dict) else {}
    if int(publisher_h.get("errors", 0) or 0):
        anomalies.append(issue("publisher_errors", "error", "Publisher ha avuto errori WordPress.", publisher_h))
    if int(publisher_h.get("wp_not_ready", 0) or 0):
        anomalies.append(issue("wp_not_ready", "error", "WordPress non era pronto/raggiungibile.", publisher_h))

    approved = int(alfred_h.get("approved", 0) or 0)
    completed = int(publisher_h.get("published", 0) or 0) + int(publisher_h.get("already_published", 0) or 0) + int(publisher_h.get("dry_run", 0) or 0) + int(publisher_h.get("wp_not_ready", 0) or 0)
    if approved and completed < approved:
        anomalies.append(issue("approval_publish_mismatch", "warning", "Non tutti gli articoli approvati risultano gestiti dal Publisher.", {"approved": approved, "publisher_completed": completed}))

    for d in dossiers:
        if d["bob"].get("present") and d["bob"].get("status") != "ready_for_alfred":
            anomalies.append(issue("article_bob_not_ready", "warning", "Articolo non pronto in Bob.", {"source_url": d.get("source_url"), "status": d["bob"].get("status")}))
        if d["alfred"].get("present") and d["alfred"].get("decision") == "needs_revision":
            anomalies.append(issue("article_needs_revision", "warning", "Articolo fermato da Alfred.", {"source_url": d.get("source_url"), "issues": d["alfred"].get("issues")}))
        if d["publisher"].get("present") and d["publisher"].get("status") == "publish_error":
            anomalies.append(issue("article_publish_error", "error", "Articolo non pubblicato per errore WordPress.", {"source_url": d.get("source_url"), "error": d["publisher"].get("error")}))

    return anomalies


def update_ledger(run_record: dict[str, Any]) -> list[dict[str, Any]]:
    ledger = load_json(ARCHIVISTA_LEDGER_FILE, [])
    if not isinstance(ledger, list):
        ledger = []
    ledger.append(run_record)
    cutoff = utc_now_dt() - timedelta(hours=LEDGER_HOURS)
    recent: list[dict[str, Any]] = []
    for item in ledger:
        ts = parse_dt(item.get("generated_at") or item.get("started_at")) if isinstance(item, dict) else None
        if ts is None or ts >= cutoff:
            recent.append(item)
    write_json(ARCHIVISTA_LEDGER_FILE, recent)
    return recent


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Archivista report - {report.get('generated_at')}")
    lines.append("")
    lines.append(f"Status: **{report.get('overall_status')}**")
    summary = report.get("summary", {})
    lines.append(f"Runs in ledger 48h: {summary.get('runs_48h')} | Published current run: {summary.get('published_current_run')} | Anomalies: {summary.get('anomalies')}")
    lines.append("")
    lines.append("## Agent handoff")
    for name, handoff in (report.get("agent_handoffs") or {}).items():
        lines.append(f"- {name}: `{json.dumps(handoff, ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Anomalies")
    anomalies = report.get("anomalies") or []
    if not anomalies:
        lines.append("- Nessuna anomalia rilevata.")
    else:
        for a in anomalies:
            lines.append(f"- **{a.get('severity')}** `{a.get('code')}`: {a.get('message')}")
    lines.append("")
    lines.append("## Articles")
    for d in report.get("article_dossiers", []):
        lines.append(f"### {d.get('title_it') or d.get('source_url')}")
        lines.append(f"- URL: {d.get('source_url')}")
        lines.append(f"- Bob: {d.get('bob', {}).get('status')} | Alfred: {d.get('alfred', {}).get('decision')} | Publisher: {d.get('publisher', {}).get('status')}")
        if d.get("publisher", {}).get("wp_link"):
            lines.append(f"- WP: {d.get('publisher', {}).get('wp_link')}")
    lines.append("")
    return "\n".join(lines)


def run_archivista(
    *,
    timeline: list[dict[str, Any]] | None = None,
    run_summary: dict[str, Any] | None = None,
    massy: dict[str, Any] | None = None,
    simone: dict[str, Any] | None = None,
    menzo: dict[str, Any] | None = None,
    bob: dict[str, Any] | None = None,
    alfred: dict[str, Any] | None = None,
    publisher: dict[str, Any] | None = None,
) -> dict[str, Any]:
    print("[ARCHIVISTA v93.7] Avvio audit redazionale", flush=True)
    inputs = {
        "massy": massy if isinstance(massy, dict) else load_json(ARTIFACT_DIR / "massy_board.json", {}),
        "simone": simone if isinstance(simone, dict) else load_json(ARTIFACT_DIR / "simone_reports.json", {}),
        "menzo": menzo if isinstance(menzo, dict) else load_json(ARTIFACT_DIR / "menzo_decisions.json", {}),
        "bob": bob if isinstance(bob, dict) else load_json(ARTIFACT_DIR / "bob_articles.json", {}),
        "alfred": alfred if isinstance(alfred, dict) else load_json(ARTIFACT_DIR / "alfred_review.json", {}),
        "publisher": publisher if isinstance(publisher, dict) else load_json(ARTIFACT_DIR / "publisher_result.json", {}),
    }
    dossiers = make_article_dossiers(inputs)
    anomalies = detect_anomalies(inputs, dossiers)
    has_error = any(a.get("severity") == "error" for a in anomalies)
    has_warning = any(a.get("severity") == "warning" for a in anomalies)
    overall = "error" if has_error else ("warning" if has_warning else "ok")

    handoffs = {
        "massy": (inputs["massy"].get("handoff", {}) if isinstance(inputs["massy"], dict) else {}),
        "simone": (inputs["simone"].get("handoff", {}) if isinstance(inputs["simone"], dict) else {}),
        "menzo": (inputs["menzo"].get("handoff", {}) if isinstance(inputs["menzo"], dict) else {}),
        "bob": (inputs["bob"].get("handoff", {}) if isinstance(inputs["bob"], dict) else {}),
        "alfred": (inputs["alfred"].get("handoff", {}) if isinstance(inputs["alfred"], dict) else {}),
        "publisher": (inputs["publisher"].get("handoff", {}) if isinstance(inputs["publisher"], dict) else {}),
    }
    run_record = {
        "generated_at": utc_now(),
        "overall_status": overall,
        "agent_handoffs": handoffs,
        "published": handoffs.get("publisher", {}).get("published", 0),
        "already_published": handoffs.get("publisher", {}).get("already_published", 0),
        "errors": len([a for a in anomalies if a.get("severity") == "error"]),
        "warnings": len([a for a in anomalies if a.get("severity") == "warning"]),
        "article_count": len(dossiers),
    }
    ledger = update_ledger(run_record)
    published_48h = sum(int(item.get("published", 0) or 0) for item in ledger if isinstance(item, dict))
    errors_48h = sum(int(item.get("errors", 0) or 0) for item in ledger if isinstance(item, dict))

    report = {
        "agent": "Archivista",
        "version": ARCHIVISTA_VERSION,
        "generated_at": run_record["generated_at"],
        "overall_status": overall,
        "summary": {
            "runs_48h": len(ledger),
            "published_current_run": run_record["published"],
            "published_48h": published_48h,
            "errors_48h": errors_48h,
            "anomalies": len(anomalies),
            "article_dossiers": len(dossiers),
        },
        "agent_handoffs": handoffs,
        "anomalies": anomalies,
        "timeline": timeline or [],
        "article_dossiers": dossiers,
        "ledger_48h": ledger,
        "run_summary_input": run_summary or {},
        "how_to_read": {
            "translation_prompt_preview": "testo pulito dato a Gemini da Bob",
            "bob_body_html_preview": "HTML prodotto da Bob prima di Alfred",
            "alfred_final_html_preview": "HTML dopo revisione/normalizzazioni di Alfred",
            "publisher_review_html_preview": "HTML finale preparato per WordPress con fonte in coda",
            "published_html_preview": "HTML salvato dopo pubblicazione",
        },
    }

    write_json(ARCHIVISTA_REPORT_FILE, report)
    write_json(ARTIFACT_ARCHIVISTA_FILE, report)
    write_text(ARTIFACT_ARCHIVISTA_MD, render_markdown(report))
    print(
        "[ARCHIVISTA v93.7] Audit pronto | "
        f"status={overall} runs48h={len(ledger)} published48h={published_48h} anomalies={len(anomalies)}",
        flush=True,
    )
    return report


if __name__ == "__main__":
    out = run_archivista()
    print(json.dumps({"overall_status": out.get("overall_status"), "summary": out.get("summary")}, ensure_ascii=False, indent=2))
