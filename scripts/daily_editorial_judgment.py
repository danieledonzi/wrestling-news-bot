from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
STATE_REPORTS_DIR = ROOT / "state" / "reports"
DEFAULT_ARTIFACTS = {
    "menzo_latest": ROOT / "state" / "newsroom" / "menzo_decisions_latest.json",
    "menzo_artifact": ROOT / "artifacts" / "newsroom" / "menzo_decisions.json",
    "master_log": ROOT / "artifacts" / "newsroom" / "master_log_latest.json",
    "editorial_audit": ROOT / "reports" / "editorial_audit_v1_1_latest.json",
    "story_cluster_audit": ROOT / "reports" / "story_cluster_audit_latest.json",
    "gemini_summary": ROOT / "reports" / "gemini_diagnostics_summary_latest.json",
}
HARD_TYPES = {"hard_news", "news_risultato", "news_evento", "report_show", "injury", "contract", "roster", "title_change", "business"}
SOFT_TYPES = {"soft_news", "news_generica", "intervista", "rumor", "social", "curiosita"}
MAJOR_TERMS = ("wwe", "aew", "title", "champion", "injury", "contract", "roster", "release", "business", "raw", "smackdown", "dynamite")


def _load(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def resolve_artifact_paths(paths: dict[str, Path] | None = None) -> dict[str, Path]:
    selected = dict(DEFAULT_ARTIFACTS)
    if paths:
        selected.update(paths)
    return selected


def load_inputs(paths: dict[str, Path] | None = None) -> dict[str, Any]:
    return {name: _load(path) for name, path in resolve_artifact_paths(paths).items()}


def artifact_presence(paths: dict[str, Path] | None = None) -> tuple[list[str], list[str]]:
    used: list[str] = []
    missing: list[str] = []
    for name, path in resolve_artifact_paths(paths).items():
        if path.exists():
            used.append(str(path.relative_to(ROOT) if path.is_absolute() and path.is_relative_to(ROOT) else path))
        else:
            missing.append(str(path.relative_to(ROOT) if path.is_absolute() and path.is_relative_to(ROOT) else path))
    return used, missing


def _items(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = data.get(key)
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _title(item: dict[str, Any]) -> str:
    return str(item.get("title") or item.get("title_it") or item.get("headline") or "Senza titolo").strip()


def _url(item: dict[str, Any]) -> str:
    return str(item.get("url") or item.get("source_url") or item.get("link") or "").strip()


def _score(item: dict[str, Any]) -> int:
    for key in ("native_score", "score", "final_score", "priority_score"):
        try:
            return int(float(item.get(key)))
        except Exception:
            continue
    return 0


def _article_type(item: dict[str, Any]) -> str:
    return str(item.get("article_type") or item.get("type") or item.get("category") or "unknown").strip().lower()


def is_hard(item: dict[str, Any]) -> bool:
    at = _article_type(item)
    pr = str(item.get("priority") or "").lower()
    blob = f"{at} {pr} {_title(item)} {_url(item)}".lower()
    return at in HARD_TYPES or pr in {"hard", "high", "major"} or any(t in blob for t in ("injury", "contract", "roster", "release", "title change", "business"))


def is_soft(item: dict[str, Any]) -> bool:
    at = _article_type(item)
    return at in SOFT_TYPES or str(item.get("priority") or "").lower() in {"soft", "low", "medium"}


def collect_menzo(data: dict[str, Any]) -> dict[str, Any]:
    menzo = data.get("menzo_latest") or data.get("menzo_artifact") or {}
    if not menzo and isinstance(_nested(data.get("master_log", {}), "menzo"), dict):
        menzo = _nested(data.get("master_log", {}), "menzo")
    return menzo if isinstance(menzo, dict) else {}


def collect_published(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    master = data.get("master_log", {})
    news = _items(_nested(master, "publisher") or {}, "published") + [r for r in _items(_nested(master, "publisher") or {}, "results") if str(r.get("status")) == "published"]
    reports = _items(_nested(master, "simone") or {}, "published_reports")
    return news, reports


def day_type(news_count: int, report_count: int, hard_count: int, story_reviews: int = 0) -> str:
    if report_count > 0:
        return "post-show"
    if news_count >= 18 or hard_count >= 10 or story_reviews >= 5:
        return "intensa"
    if news_count <= 3 and hard_count <= 1:
        return "scarica"
    return "normale"


def top_discarded(menzo: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
    candidates = []
    for decision in ("skipped", "pending", "skipped_sample"):
        for item in _items(menzo, decision):
            blob = f"{_title(item)} {_url(item)} {item.get('source','')}".lower()
            rank = _score(item) + (25 if is_hard(item) else 0) + (15 if any(t in blob for t in MAJOR_TERMS) else 0)
            if decision == "pending":
                rank += 10
            candidates.append((rank, decision, item))
    seen = set()
    out = []
    for _rank, decision, item in sorted(candidates, key=lambda x: x[0], reverse=True):
        key = _url(item) or _title(item).lower()
        if key in seen:
            continue
        seen.add(key)
        clone = dict(item)
        clone["_decision_bucket"] = decision
        out.append(clone)
        if len(out) >= limit:
            break
    return out


def _auto_judgment(item: dict[str, Any]) -> str:
    if is_hard(item) and _score(item) >= 75:
        return "possibile buco editoriale"
    if _score(item) >= 60 or str(item.get("_decision_bucket")) == "pending":
        return "scarto dubbio"
    return "scarto probabilmente corretto"


def build_report(data: dict[str, Any], *, generated_at: datetime | None = None, source_artifacts_used: list[str] | None = None, missing_artifacts: list[str] | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    menzo = collect_menzo(data)
    news, reports = collect_published(data)
    selected, pending, skipped = _items(menzo, "selected"), _items(menzo, "pending"), _items(menzo, "skipped") or _items(menzo, "skipped_sample")
    hard_count = sum(1 for x in selected + news if is_hard(x))
    soft_count = sum(1 for x in selected + news if is_soft(x))
    story_audit = data.get("story_cluster_audit", {})
    story_reviews = _items(story_audit, "story_review") or _items(story_audit, "story_reviews")
    clusters = _items(story_audit, "same_story_clusters") or _items(story_audit, "suspicious_story_clusters")
    duplicate_candidates = len(_items(story_audit, "duplicate_candidates"))
    dtype = day_type(len(news), len(reports), hard_count, len(story_reviews))
    softpool = _nested(menzo, "softpool", "injected_candidates") or _nested(menzo, "daily_policy", "softpool_used") or any(x.get("from_softpool") for x in selected + pending + skipped)
    warnings = _nested(data.get("master_log", {}), "alfred", "handoff", "warnings") or _nested(data.get("master_log", {}), "alfred", "postprocess", "warnings") or 0
    blockers = _nested(data.get("master_log", {}), "alfred", "handoff", "blockers") or 0
    gemini_called = _nested(data.get("gemini_summary", {}), "models", "gemini-3.5", "called") or _nested(data.get("gemini_summary", {}), "gemini_3_5_called_total") or "n/d"
    article_types = Counter(_article_type(x) for x in selected + news if _article_type(x) != "unknown")
    judgment = "OTTIMO" if hard_count >= 8 and len(top_discarded(menzo, 1)) == 0 else "BUONO" if len(news) + len(reports) >= 8 else "DISCRETO" if len(news) + len(reports) >= 3 else "DEBOLE"
    top = top_discarded(menzo)
    borderline = [x for x in selected + news if is_soft(x) or _score(x) < 65][:3]
    summary = f"Giornata {dtype} con {len(news)} news e {len(reports)} report show pubblicati. La copertura hard news è stimata a {hard_count} elementi e quella soft a {soft_count}; {'softpool usato' if softpool else 'softpool non usato'}."
    if top:
        summary += " Il principale controllo umano riguarda: " + _title(top[0]) + "."
    else:
        summary += " Non emergono forti candidati scartati da recuperare."
    return {"generated_at": generated_at, "source_artifacts_used": source_artifacts_used or [], "missing_artifacts": missing_artifacts or [], "menzo": menzo, "news": news, "reports": reports, "selected": selected, "pending": pending, "skipped": skipped, "hard_count": hard_count, "soft_count": soft_count, "story_reviews": story_reviews, "clusters": clusters, "duplicate_candidates": duplicate_candidates, "day_type": dtype, "softpool": bool(softpool), "warnings": warnings, "blockers": blockers, "gemini_called": gemini_called, "article_types": article_types, "judgment": judgment, "top_discarded": top, "borderline": borderline, "summary": summary}


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# OWTV Daily Editorial Judgment 24h", "", "## Daily Editorial Judgment", "", f"- Judgment: {report['judgment']}", f"- Day type: {report['day_type']}", "", report["summary"], "", "## Daily numbers", "", f"- runs completed: {1 if (report['news'] or report['reports'] or report['selected']) else 0}", f"- news published: {len(report['news'])}", f"- reports published: {len(report['reports'])}", f"- article types: {dict(report['article_types']) or 'n/d'}", f"- Menzo first decision selected/pending/skipped: {len(report['selected'])}/{len(report['pending'])}/{len(report['skipped'])}", f"- final selected/pending/skipped: {len(report['selected'])}/{len(report['pending'])}/{len(report['skipped'])}", f"- hard news count: {report['hard_count']} (stima)", f"- soft news count: {report['soft_count']} (stima)", f"- softpool used: {'yes' if report['softpool'] else 'no'}", f"- Alfred warnings/blockers: {report['warnings']}/{report['blockers']}", f"- duplicate candidates / same story clusters / story reviews: {report['duplicate_candidates']} / {len(report['clusters'])} / {len(report['story_reviews'])}", f"- Gemini 3.5 called total: {report['gemini_called']}", "", "## Hard vs soft editorial balance", "", f"Stima: {report['hard_count']} hard news e {report['soft_count']} soft news. " + ("Il ricorso al softpool sembra giustificato solo se le hard news erano limitate." if report['softpool'] else "Softpool non usato: scelta coerente se la giornata aveva sufficiente materiale hard o nessun soft recuperabile."), "", "## Top 3 discarded URLs for human control", ""]
    if not report["top_discarded"]:
        lines.append("Nessun forte candidato scartato/pending emerso dagli artefatti disponibili.")
    for item in report["top_discarded"]:
        lines += [f"### {_title(item)}", f"- source: {item.get('source') or 'n/d'}", f"- url: {_url(item) or 'n/d'}", f"- score: {_score(item) or 'n/d'}", f"- article_type: {_article_type(item)}", f"- priority: {item.get('priority') or 'n/d'}", f"- Menzo decision/reason: {item.get('_decision_bucket')} / {item.get('reason') or 'n/d'}", "- why it is worth checking: punteggio/priorità o rilevanza potenziale per il pubblico OWTV.", f"- automatic judgment: {_auto_judgment(item)}", ""]
    lines += ["## Published borderline/soft picks", ""]
    if not report["borderline"]:
        lines.append("Nessun pick pubblicato chiaramente borderline/soft dagli artefatti disponibili.")
    for item in report["borderline"]:
        lines += [f"- {_title(item)} — type={_article_type(item)}, score={_score(item) or 'n/d'}, valutazione: accettabile se utile al mix quotidiano; da monitorare se sostituisce hard news."]
    lines += ["", "## Redundancy and show-report integration", "", f"Duplicate risk: {'high' if len(report['clusters']) > 3 else 'medium' if report['clusters'] else 'low'}. Same-story clusters: {len(report['clusters'])}. Story_review items: {len(report['story_reviews'])}. Le news risultato/evento vanno controllate rispetto ai report show quando presenti; pubblicazione post-show {'presente' if report['reports'] else 'non presente'}.", ""]
    if report["story_reviews"]:
        lines.append("Story_review inclusi: " + "; ".join(_title(x) for x in report["story_reviews"][:5]))
    lines += ["", "## Editorial risks and patterns of the day", "", "- " + ("news_generica/soft da monitorare." if report['soft_count'] > report['hard_count'] else "no major issue found nella stima hard/soft."), "- controllare eventuali sovrapposizioni tra news evento/risultato e report show.", "", "## Recommended actions", "", "1. Rivedere il primo URL scartato/pending se presente.", "2. Monitorare il rapporto hard/soft nel prossimo ciclo.", "3. Rafforzare il controllo post-show se emergono duplicazioni con report.", ""]
    return "\n".join(lines)


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _title(item),
        "source": item.get("source") or "",
        "url": _url(item),
        "score": _score(item) or None,
        "article_type": _article_type(item),
        "priority": item.get("priority") or "",
        "menzo_decision": item.get("_decision_bucket") or item.get("decision") or "",
        "menzo_reason": item.get("reason") or "",
        "automatic_judgment": _auto_judgment(item) if item.get("_decision_bucket") else "",
    }


def structured_json(report: dict[str, Any]) -> dict[str, Any]:
    daily_numbers = {
        "runs_completed": 1 if (report["news"] or report["reports"] or report["selected"]) else 0,
        "news_published": len(report["news"]),
        "reports_published": len(report["reports"]),
        "article_types": dict(report["article_types"]),
        "menzo_first_decision": {"selected": len(report["selected"]), "pending": len(report["pending"]), "skipped": len(report["skipped"])},
        "final_decision": {"selected": len(report["selected"]), "pending": len(report["pending"]), "skipped": len(report["skipped"])},
        "hard_news_count": report["hard_count"],
        "soft_news_count": report["soft_count"],
        "softpool_used": report["softpool"],
        "alfred": {"warnings": report["warnings"], "blockers": report["blockers"]},
        "duplicate_candidates": report["duplicate_candidates"],
        "same_story_clusters": len(report["clusters"]),
        "story_reviews": len(report["story_reviews"]),
        "gemini_3_5_called_total": report["gemini_called"],
    }
    hard_soft_balance = {
        "hard_news_count": report["hard_count"],
        "soft_news_count": report["soft_count"],
        "softpool_used": report["softpool"],
        "is_estimate": True,
        "explanation": "Stima deterministica da priority, article_type, score e decisioni Menzo disponibili.",
    }
    redundancy_risks = {
        "duplicate_risk": "high" if len(report["clusters"]) > 3 else "medium" if report["clusters"] else "low",
        "same_story_clusters": len(report["clusters"]),
        "story_review_items": [_compact_item(x) for x in report["story_reviews"][:10]],
        "show_report_integration": "post-show presente" if report["reports"] else "nessun report show pubblicato negli artefatti disponibili",
    }
    recommended_actions = [
        "Rivedere il primo URL scartato/pending se presente.",
        "Monitorare il rapporto hard/soft nel prossimo ciclo.",
        "Rafforzare il controllo post-show se emergono duplicazioni con report.",
    ]
    return {
        "judgment": report["judgment"],
        "day_type": report["day_type"],
        "summary": report["summary"],
        "daily_numbers": daily_numbers,
        "hard_soft_balance": hard_soft_balance,
        "top_discarded_candidates": [_compact_item(x) for x in report["top_discarded"]],
        "borderline_published": [_compact_item(x) for x in report["borderline"]],
        "redundancy_risks": redundancy_risks,
        "recommended_actions": recommended_actions,
        "generated_at": report["generated_at"].isoformat(),
        "source_artifacts_used": report["source_artifacts_used"],
        "missing_artifacts": report["missing_artifacts"],
    }


def email_summary(report: dict[str, Any]) -> str:
    top = report["top_discarded"][0] if report["top_discarded"] else None
    return "\n".join(["Daily Editorial Judgment:", f"- Judgment: {report['judgment']}", f"- Day type: {report['day_type']}", f"- Published: {len(report['news'])} news / {len(report['reports'])} report", f"- Hard/soft balance: {report['hard_count']} hard vs {report['soft_count']} soft (stima)", f"- Top concern: {'controllare scarti/pending ad alta rilevanza' if top else 'nessun forte candidato scartato emerso'}", f"- Top discarded URL: {_url(top) if top else 'n/d'}"])


def generate_daily_editorial_judgment_outputs(paths: dict[str, Path] | None = None, output_dir: Path = REPORTS_DIR, state_dir: Path = STATE_REPORTS_DIR, now: datetime | None = None) -> dict[str, Path]:
    used, missing = artifact_presence(paths)
    report = build_report(load_inputs(paths), generated_at=now, source_artifacts_used=used, missing_artifacts=missing)
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    ts = (now or report["generated_at"]).strftime("%Y%m%d_%H%M%S")
    markdown_path = output_dir / f"owtv_daily_editorial_judgment_24h_{ts}.md"
    json_path = output_dir / f"owtv_daily_editorial_judgment_24h_{ts}.json"
    latest_json_path = state_dir / "owtv_daily_editorial_judgment_latest.json"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    payload = structured_json(report)
    json_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    return {"markdown": markdown_path, "json": json_path, "latest_json": latest_json_path}


def generate_daily_editorial_judgment_report(paths: dict[str, Path] | None = None, output_dir: Path = REPORTS_DIR, now: datetime | None = None) -> Path:
    state_dir = STATE_REPORTS_DIR if output_dir == REPORTS_DIR else output_dir / "state_reports"
    return generate_daily_editorial_judgment_outputs(paths=paths, output_dir=output_dir, state_dir=state_dir, now=now)["markdown"]


if __name__ == "__main__":
    path = generate_daily_editorial_judgment_report()
    print(path)
