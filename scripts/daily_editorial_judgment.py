from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "reports"
VPS_REPORTS_DIR = Path("/opt/owtv/reports")
STATE_REPORTS_DIR = ROOT / "state" / "reports"
DEFAULT_ARTIFACT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "operational_report": ("reports/owtv_operational_report_24h_*.md",),
    "menzo_latest": ("state/newsroom/menzo_decisions_latest.json", "artifacts/newsroom/menzo_decisions.json"),
    "master_log": ("artifacts/newsroom/master_log_tail.jsonl", "logs/newsroom_master.log", "artifacts/newsroom/master_log_latest.json"),
    "editorial_audit": ("reports/owtv_editorial_audit_v1_1_24h_*.json", "reports/owtv_editorial_audit_v1_1_24h_*.md", "reports/editorial_audit_v1_1_latest.json"),
    "story_cluster_audit": ("reports/story_cluster_audit_v94_7_1_*.json", "reports/story_cluster_audit_v94_7_1_*.md", "reports/story_cluster_audit_latest.json"),
    "gemini_ledger": ("state/newsroom/gemini_call_ledger.jsonl", "reports/gemini_diagnostics_summary_latest.json"),
}
HARD_TYPES = {"hard_news", "news_risultato", "news_evento", "report_show", "injury", "contract", "roster", "title_change", "business"}
SOFT_TYPES = {"soft_news", "news_generica", "intervista", "rumor", "social", "curiosita"}
MAJOR_TERMS = ("wwe", "aew", "title", "champion", "injury", "contract", "roster", "release", "business", "raw", "smackdown", "dynamite")
COUNT_PATTERNS = {
    "duplicate_candidates": r"Duplicate candidate:\s*(\d+)",
    "same_story_clusters": r"Same story cluster:\s*(\d+)",
    "same_event_clusters": r"Same event cluster:\s*(\d+)",
    "story_reviews": r"Story review:\s*(\d+)",
    "pairs_above_threshold": r"Coppie sopra soglia diagnostica:\s*(\d+)",
}


def _latest_glob(pattern: str, *, base: Path | None = None) -> Path | None:
    root = base or ROOT
    matches = [p for p in root.glob(pattern) if p.is_file()]
    return max(matches, key=lambda p: (p.name, p.stat().st_mtime)) if matches else None


def _report_input_dirs() -> list[Path]:
    # Prefer the VPS-level operational report directory; the repo reports directory
    # remains the default output location and a fallback input source for dev/test.
    dirs = [VPS_REPORTS_DIR, ROOT / "reports"]
    out: list[Path] = []
    for d in dirs:
        if d not in out:
            out.append(d)
    return out


def _latest_report_artifact(pattern: str) -> Path | None:
    bare = pattern.removeprefix("reports/")
    for directory in _report_input_dirs():
        found = _latest_glob(bare, base=directory)
        if found:
            return found
    return _latest_glob(pattern)


def resolve_artifact_paths(paths: dict[str, Path] | None = None) -> dict[str, Path | None]:
    resolved: dict[str, Path | None] = {}
    for name, candidates in DEFAULT_ARTIFACT_CANDIDATES.items():
        found: Path | None = None
        for candidate in candidates:
            path = _latest_report_artifact(candidate) if candidate.startswith("reports/") and "*" in candidate else (_latest_glob(candidate) if "*" in candidate else ROOT / candidate)
            if path and path.exists():
                found = path
                break
        resolved[name] = found
    if paths:
        resolved.update(paths)
    return resolved


def _rel(path: Path | None, fallback: str) -> str:
    if path is None:
        return fallback
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def _load_jsonl(path: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            records.append(item)
    return {"_format": "jsonl", "records": records, "latest": records[-1] if records else {}}


def _load(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        if suffix == ".jsonl" or path.name.endswith(".log"):
            return _load_jsonl(path)
        if suffix == ".md":
            return {"_format": "markdown", "_markdown": path.read_text(encoding="utf-8", errors="ignore")}
    except Exception as exc:
        return {"_schema_warning": f"read_failed:{exc}"}
    return {}


def artifact_presence(paths: dict[str, Path] | None = None) -> tuple[list[str], list[str]]:
    used: list[str] = []
    missing: list[str] = []
    for name, path in resolve_artifact_paths(paths).items():
        if path and path.exists():
            used.append(_rel(path, name))
        else:
            missing.append(name)
    return used, missing


def load_inputs(paths: dict[str, Path] | None = None, *, hours: int = 24, now: datetime | None = None) -> dict[str, Any]:
    resolved = resolve_artifact_paths(paths)
    used, missing = artifact_presence(paths)
    data = {name: _load(path) for name, path in resolved.items()}
    data["__artifact_status__"] = {"used": used, "missing": missing}
    data["__window__"] = {"hours": hours, "now": (now or datetime.now(timezone.utc)).isoformat()}
    return data


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
    return str(item.get("title") or item.get("title_it") or item.get("headline") or item.get("title_a") or "Senza titolo").strip()


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
    return str(item.get("article_type") or item.get("type") or item.get("category") or item.get("cluster_type") or "unknown").strip().lower()


def is_hard(item: dict[str, Any]) -> bool:
    at = _article_type(item)
    pr = str(item.get("priority") or "").lower()
    blob = f"{at} {pr} {_title(item)} {_url(item)}".lower()
    return at in HARD_TYPES or pr in {"hard", "high", "major"} or any(t in blob for t in ("injury", "contract", "roster", "release", "title change", "business"))


def is_soft(item: dict[str, Any]) -> bool:
    at = _article_type(item)
    return at in SOFT_TYPES or str(item.get("priority") or "").lower() in {"soft", "low", "medium"}


def collect_menzo(data: dict[str, Any]) -> dict[str, Any]:
    menzo = data.get("menzo_latest") or {}
    if not menzo and isinstance(_nested(data.get("master_log", {}), "latest", "menzo"), dict):
        menzo = _nested(data.get("master_log", {}), "latest", "menzo")
    if not menzo and isinstance(_nested(data.get("master_log", {}), "menzo"), dict):
        menzo = _nested(data.get("master_log", {}), "menzo")
    return menzo if isinstance(menzo, dict) else {}


def _master(data: dict[str, Any]) -> dict[str, Any]:
    master = data.get("master_log", {})
    if isinstance(master.get("latest"), dict):
        return master["latest"]
    return master if isinstance(master, dict) else {}


def collect_published(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    master = _master(data)
    publisher = _nested(master, "publisher") or {}
    news = _items(publisher, "published") + [r for r in _items(publisher, "results") if str(r.get("status")) == "published"]
    simone = _nested(master, "simone") or {}
    all_reports = _items(simone, "published_reports")
    reports = [r for r in all_reports if str(r.get("status") or "").lower() == "published"]
    report_status_counts = Counter(str(r.get("status") or "unknown").lower() for r in all_reports)
    return news, reports, {"available": bool(master), "report_status_counts": dict(report_status_counts)}


def day_type(news_count: int | None, report_count: int | None, hard_count: int | None, story_reviews: int | None = 0) -> str:
    news_count = news_count or 0
    report_count = report_count or 0
    hard_count = hard_count or 0
    story_reviews = story_reviews or 0
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


def _count_from_markdown(text: str, key: str) -> int | None:
    pattern = COUNT_PATTERNS.get(key)
    if not pattern:
        return None
    match = re.search(pattern, text, re.I)
    return int(match.group(1)) if match else None


def _md_int(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return int(match.group(1))
    return None


def _md_list_count(text: str, patterns: tuple[str, ...]) -> list[dict[str, Any]]:
    count = _md_int(text, patterns)
    return [{"_placeholder_from_markdown": True} for _ in range(count or 0)]


def parse_daily_markdown_inputs(data: dict[str, Any]) -> dict[str, Any]:
    """Parse real 24h markdown reports without inventing zeroes on mismatch."""
    texts = "\n".join(str((data.get(k) or {}).get("_markdown") or "") for k in ("operational_report", "editorial_audit"))
    if not texts.strip():
        return {}
    parsed: dict[str, Any] = {}
    runs = _md_int(texts, (r"runs completed\D+(\d+)",))
    if runs is not None:
        parsed["runs_completed"] = runs if isinstance(runs, int) else 1
    elif re.search(r"EXIT\s+0", texts, re.I):
        parsed["runs_completed"] = 1
    news_count = _md_int(texts, (r"news published\D+(\d+)", r"news_published\D+(\d+)"))
    reports_count = _md_int(texts, (r"reports? show published\D+(\d+)", r"reports? published\D+(\d+)", r"reports_published\D+(\d+)"))
    if news_count is not None:
        parsed["news"] = _md_list_count(texts, (r"news published\D+(\d+)", r"news_published\D+(\d+)"))
    if reports_count is not None:
        parsed["reports"] = _md_list_count(texts, (r"reports? show published\D+(\d+)", r"reports? published\D+(\d+)", r"reports_published\D+(\d+)"))
    decision = re.search(r"Menzo first decision selected/pending/skipped\D+(\d+)\D+(\d+)\D+(\d+)", texts, re.I)
    if decision:
        parsed["menzo"] = {
            "selected": [{"_placeholder_from_markdown": True} for _ in range(int(decision.group(1)))],
            "pending": [{"_placeholder_from_markdown": True} for _ in range(int(decision.group(2)))],
            "skipped": [{"_placeholder_from_markdown": True} for _ in range(int(decision.group(3)))],
        }
    types: Counter[str] = Counter()
    type_match = re.search(r"article types?\s*[:=]\s*(\{[^\n]+\}|[^\n]+)", texts, re.I)
    if type_match:
        raw = type_match.group(1).strip()
        try:
            parsed_obj = json.loads(raw.replace("'", '"'))
            if isinstance(parsed_obj, dict):
                types.update({str(k): int(v) for k, v in parsed_obj.items()})
        except Exception:
            for name, value in re.findall(r"([a-zA-Z_]+)\D+(\d+)", raw):
                types[name.lower()] += int(value)
    if types:
        parsed["article_types"] = types
    alfred = re.search(r"Alfred warnings/blockers\D+(\d+|n\.d\.)\D+(\d+|n\.d\.)", texts, re.I)
    if alfred:
        parsed["warnings"], parsed["blockers"] = alfred.group(1), alfred.group(2)
    pub_errors = _md_int(texts, (r"Publisher errors\D+(\d+)",))
    andrea_blocked = _md_int(texts, (r"Andrea blocked\D+(\d+)",))
    if pub_errors is not None:
        parsed["publisher_errors"] = pub_errors
    if andrea_blocked is not None:
        parsed["andrea_blocked"] = andrea_blocked
    gemini = _md_int(texts, (r"Gemini(?:\s+3\.5)? called total\D+(\d+)", r"gemini[_\s-]*3[_\s.-]*5[_\s-]*called[_\s-]*total\D+(\d+)"))
    if gemini is not None:
        parsed["gemini_3_5_called_total"] = gemini
    return parsed


def _article_type_hard_soft_counts(article_types: Counter[str]) -> tuple[int, int]:
    hard_aliases = {
        "hard_news",
        "contratto",
        "contratti",
        "contract",
        "roster",
        "infortunio",
        "salute",
        "injury",
        "risultato_match",
        "risultato",
        "news_risultato",
        "evento",
        "news_evento",
        "business",
        "ascolti",
        "title_change",
    }
    soft_aliases = {
        "soft_news",
        "news_generica",
        "generica",
        "dichiarazione",
        "reazione",
        "intervista",
        "social",
        "curiosita",
        "backstage",
        "creative",
    }
    hard = 0
    soft = 0
    for raw_type, count in article_types.items():
        article_type = str(raw_type).strip().lower()
        if article_type in hard_aliases or article_type in HARD_TYPES:
            hard += int(count)
        elif article_type in soft_aliases or article_type in SOFT_TYPES:
            soft += int(count)
        elif any(token in article_type for token in ("contratt", "roster", "infortun", "salute", "risultato", "evento", "business", "ascolt")):
            hard += int(count)
        elif any(token in article_type for token in ("generic", "dichiar", "reazion", "backstage", "creative", "social")):
            soft += int(count)
    return hard, soft


def parse_story_cluster_audit(data: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    counts = data.get("counts") if isinstance(data.get("counts"), dict) else {}
    markdown = str(data.get("_markdown") or "")
    def count(name: str, legacy_list: str) -> int | None:
        aliases = {
            "duplicate_candidates": ("duplicate_candidates", "duplicate_candidate"),
            "same_story_clusters": ("same_story_clusters", "same_story_cluster"),
            "same_event_clusters": ("same_event_clusters", "same_event_cluster"),
            "story_reviews": ("story_reviews", "story_review"),
            "pairs_above_threshold": ("pairs_above_threshold", "pairs_above_threshold_count"),
        }.get(name, (name,))
        for alias in aliases:
            if alias not in counts:
                continue
            try:
                return int(counts[alias])
            except Exception:
                warnings.append(f"story_cluster_count_invalid:{alias}")
        if isinstance(data.get(legacy_list), list):
            return len(data[legacy_list])
        if legacy_list == "story_review" and isinstance(data.get("story_reviews"), list):
            return len(data["story_reviews"])
        return _count_from_markdown(markdown, name)
    pairs = _items(data, "pairs")
    suspicious_pairs = [p for p in pairs if _article_type(p) in {"duplicate_candidate", "same_story_cluster", "same_event_cluster", "story_review"}]
    if not counts and not markdown and not pairs and data:
        warnings.append("story_cluster_schema_unrecognized")
    return {
        "duplicate_candidates": count("duplicate_candidates", "duplicate_candidates"),
        "same_story_clusters": count("same_story_clusters", "same_story_clusters"),
        "same_event_clusters": count("same_event_clusters", "same_event_clusters"),
        "story_reviews": count("story_reviews", "story_review"),
        "pairs_above_threshold": count("pairs_above_threshold", "pairs") if count("pairs_above_threshold", "pairs") is not None else (len(pairs) if pairs else None),
        "clusters": data.get("clusters") if isinstance(data.get("clusters"), list) else [],
        "story_review_items": _items(data, "story_review") or _items(data, "story_reviews") or [p for p in pairs if _article_type(p) == "story_review"],
        "suspicious_pairs": sorted(suspicious_pairs, key=lambda p: float(p.get("score") or 0), reverse=True)[:5],
        "schema_warnings": warnings,
    }


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _gemini_35_calls(data: dict[str, Any]) -> int | str:
    parsed = parse_daily_markdown_inputs(data)
    if parsed.get("gemini_3_5_called_total") is not None:
        return parsed["gemini_3_5_called_total"]
    window = data.get("__window__", {}) if isinstance(data.get("__window__"), dict) else {}
    try:
        hours = int(window.get("hours") or 24)
    except Exception:
        hours = 24
    now = _parse_dt(window.get("now")) or datetime.now(timezone.utc)
    since_ts = now.timestamp() - (hours * 3600)
    ledger = data.get("gemini_ledger", {})
    if isinstance(ledger.get("records"), list):
        total = 0
        for record in ledger["records"]:
            stamp = _parse_dt(record.get("timestamp") or record.get("ts") or record.get("created_at"))
            if stamp and stamp.timestamp() < since_ts:
                continue
            model = str(record.get("model") or record.get("actual_model") or record.get("selected_model") or "").lower()
            status = str(record.get("status") or "called").lower()
            if "3.5" in model and status != "avoided":
                total += 1
        return total
    return _nested(ledger, "models", "gemini-3.5", "called") or _nested(ledger, "gemini_3_5_called_total") or "n.d."


def build_report(data: dict[str, Any], *, generated_at: datetime | None = None, source_artifacts_used: list[str] | None = None, missing_artifacts: list[str] | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    status = data.get("__artifact_status__", {}) if isinstance(data.get("__artifact_status__"), dict) else {}
    used = source_artifacts_used if source_artifacts_used is not None else list(status.get("used") or [])
    missing = missing_artifacts if missing_artifacts is not None else list(status.get("missing") or [])
    schema_warnings: list[str] = []
    parsed_md = parse_daily_markdown_inputs(data)
    menzo = collect_menzo(data)
    if not menzo and isinstance(parsed_md.get("menzo"), dict):
        menzo = parsed_md["menzo"]
    news, reports, published_meta = collect_published(data)
    if not published_meta["available"] and ("news" in parsed_md or "reports" in parsed_md):
        news = parsed_md.get("news", news)
        reports = parsed_md.get("reports", reports)
        published_meta = {"available": True, "report_status_counts": {}}
    if not published_meta["available"]:
        schema_warnings.append("published_counts_not_available")
    selected, pending, skipped = _items(menzo, "selected"), _items(menzo, "pending"), _items(menzo, "skipped") or _items(menzo, "skipped_sample")
    article_types = Counter(_article_type(x) for x in selected + news if _article_type(x) != "unknown")
    if not article_types and isinstance(parsed_md.get("article_types"), Counter):
        article_types = parsed_md["article_types"]
    concrete_selected = [x for x in selected if not x.get("_placeholder_from_markdown")]
    concrete_news = [x for x in news if not x.get("_placeholder_from_markdown")]
    hard_soft_source = "records" if (concrete_selected or concrete_news) else None
    hard_count = sum(1 for x in concrete_selected + concrete_news if is_hard(x)) if hard_soft_source == "records" else None
    soft_count = sum(1 for x in concrete_selected + concrete_news if is_soft(x)) if hard_soft_source == "records" else None
    if hard_soft_source is None and article_types:
        hard_count, soft_count = _article_type_hard_soft_counts(article_types)
        hard_soft_source = "article_types_markdown"
    story = parse_story_cluster_audit(data.get("story_cluster_audit", {}))
    schema_warnings.extend(story["schema_warnings"])
    dtype = day_type(len(news) if published_meta["available"] else None, len(reports), hard_count, story["story_reviews"])
    softpool = _nested(menzo, "softpool", "injected_candidates") or _nested(menzo, "daily_policy", "softpool_used") or any(x.get("from_softpool") for x in selected + pending + skipped)
    warnings = _nested(_master(data), "alfred", "handoff", "warnings") or _nested(_master(data), "alfred", "postprocess", "warnings") or "n.d."
    blockers = _nested(_master(data), "alfred", "handoff", "blockers") or "n.d."
    if warnings == "n.d." and parsed_md.get("warnings") is not None:
        warnings = parsed_md["warnings"]
    if blockers == "n.d." and parsed_md.get("blockers") is not None:
        blockers = parsed_md["blockers"]
    gemini_called = _gemini_35_calls(data)
    runs_completed = parsed_md.get("runs_completed")
    published_total = len(news) + len(reports) if published_meta["available"] else None
    judgment = "OTTIMO" if (hard_count or 0) >= 8 and len(top_discarded(menzo, 1)) == 0 else "BUONO" if (published_total or 0) >= 8 else "DISCRETO" if (published_total or 0) >= 3 else "DEBOLE"
    top = top_discarded(menzo)
    borderline = [x for x in selected + news if is_soft(x) or _score(x) < 65][:3]
    news_label = str(len(news)) if published_meta["available"] else "n.d."
    summary = f"Giornata {dtype} con {news_label} news e {len(reports)} report show pubblicati. La copertura hard news è stimata a {hard_count if hard_count is not None else 'n.d.'} elementi e quella soft a {soft_count if soft_count is not None else 'n.d.'}; {'softpool usato' if softpool else 'softpool non usato'}."
    if top:
        summary += " Il principale controllo umano riguarda: " + _title(top[0]) + "."
    else:
        summary += " Non emergono forti candidati scartati da recuperare."
    return {"generated_at": generated_at, "source_artifacts_used": used, "missing_artifacts": missing, "schema_warnings": schema_warnings, "published_available": published_meta["available"], "report_status_counts": published_meta["report_status_counts"], "menzo": menzo, "news": news, "reports": reports, "selected": selected, "pending": pending, "skipped": skipped, "runs_completed": runs_completed, "hard_count": hard_count, "soft_count": soft_count, "hard_soft_source": hard_soft_source, "story": story, "day_type": dtype, "softpool": bool(softpool), "warnings": warnings, "blockers": blockers, "gemini_called": gemini_called, "article_types": article_types, "judgment": judgment, "top_discarded": top, "borderline": borderline, "summary": summary}


def _num(value: Any) -> str:
    return str(value) if value is not None else "n.d."


def render_markdown(report: dict[str, Any]) -> str:
    story = report["story"]
    lines = ["# OWTV Daily Editorial Judgment 24h", "", "## Daily Editorial Judgment", "", f"- Judgment: {report['judgment']}", f"- Day type: {report['day_type']}", "", report["summary"], "", "## Daily numbers", "", f"- runs completed: {_num(report.get('runs_completed'))}", f"- news published: {len(report['news']) if report['published_available'] else 'n.d.'}", f"- reports published: {len(report['reports'])}", f"- article types: {dict(report['article_types']) or 'n.d.'}", f"- Menzo first decision selected/pending/skipped: {len(report['selected'])}/{len(report['pending'])}/{len(report['skipped'])}", f"- final selected/pending/skipped: {len(report['selected'])}/{len(report['pending'])}/{len(report['skipped'])}", f"- hard news count: {_num(report['hard_count'])} (stima)", f"- soft news count: {_num(report['soft_count'])} (stima)", f"- softpool used: {'yes' if report['softpool'] else 'no'}", f"- Alfred warnings/blockers: {report['warnings']}/{report['blockers']}", f"- duplicate candidates / same story clusters / same event clusters / story reviews: {_num(story['duplicate_candidates'])} / {_num(story['same_story_clusters'])} / {_num(story['same_event_clusters'])} / {_num(story['story_reviews'])}", f"- suspicious pairs above threshold: {_num(story['pairs_above_threshold'])}", f"- Gemini 3.5 called total: {report['gemini_called']}", "", "## Hard vs soft editorial balance", "", f"Stima: {_num(report['hard_count'])} hard news e {_num(report['soft_count'])} soft news. " + ("Il ricorso al softpool sembra giustificato solo se le hard news erano limitate." if report['softpool'] else "Softpool non usato: scelta coerente se la giornata aveva sufficiente materiale hard o nessun soft recuperabile."), "", "## Top 3 discarded URLs for human control", ""]
    if not report["top_discarded"]:
        lines.append("Nessun forte candidato scartato/pending emerso dagli artefatti disponibili.")
    for item in report["top_discarded"]:
        lines += [f"### {_title(item)}", f"- source: {item.get('source') or 'n.d.'}", f"- url: {_url(item) or 'n.d.'}", f"- score: {_score(item) or 'n.d.'}", f"- article_type: {_article_type(item)}", f"- priority: {item.get('priority') or 'n.d.'}", f"- Menzo decision/reason: {item.get('_decision_bucket')} / {item.get('reason') or 'n.d.'}", "- why it is worth checking: punteggio/priorità o rilevanza potenziale per il pubblico OWTV.", f"- automatic judgment: {_auto_judgment(item)}", ""]
    lines += ["## Published borderline/soft picks", ""]
    if not report["borderline"]:
        lines.append("Nessun pick pubblicato chiaramente borderline/soft dagli artefatti disponibili.")
    for item in report["borderline"]:
        lines += [f"- {_title(item)} — type={_article_type(item)}, score={_score(item) or 'n.d.'}, valutazione: accettabile se utile al mix quotidiano; da monitorare se sostituisce hard news."]
    lines += ["", "## Redundancy and show-report integration", "", f"Duplicate risk: {'high' if (story['same_story_clusters'] or 0) > 3 else 'medium' if (story['same_story_clusters'] or story['duplicate_candidates'] or story['same_event_clusters']) else 'low'}. Same-story clusters: {_num(story['same_story_clusters'])}. Story_review items: {_num(story['story_reviews'])}. Le news risultato/evento vanno controllate rispetto ai report show quando presenti; pubblicazione post-show {'presente' if report['reports'] else 'non presente'}.", ""]
    if story["suspicious_pairs"]:
        lines.append("Top suspicious pairs:")
        for pair in story["suspicious_pairs"][:3]:
            lines.append(f"- {_article_type(pair)} score={pair.get('score')}: {pair.get('title_a')} / {pair.get('title_b')}")
    if story["story_review_items"]:
        lines.append("Story_review inclusi: " + "; ".join(_title(x) for x in story["story_review_items"][:5]))
    if report["schema_warnings"]:
        lines += ["", "Schema warnings:"] + [f"- {w}" for w in report["schema_warnings"]]
    lines += ["", "## Editorial risks and patterns of the day", "", "- " + ("news_generica/soft da monitorare." if (report['soft_count'] or 0) > (report['hard_count'] or 0) else "no major issue found nella stima hard/soft."), "- controllare eventuali sovrapposizioni tra news evento/risultato e report show.", "", "## Recommended actions", "", "1. Rivedere il primo URL scartato/pending se presente.", "2. Monitorare il rapporto hard/soft nel prossimo ciclo.", "3. Rafforzare il controllo post-show se emergono duplicazioni con report.", ""]
    return "\n".join(lines)


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    return {"title": _title(item), "source": item.get("source") or "", "url": _url(item), "score": _score(item) or None, "article_type": _article_type(item), "priority": item.get("priority") or "", "menzo_decision": item.get("_decision_bucket") or item.get("decision") or "", "menzo_reason": item.get("reason") or "", "automatic_judgment": _auto_judgment(item) if item.get("_decision_bucket") else ""}


def _compact_pair(item: dict[str, Any]) -> dict[str, Any]:
    return {"title_a": item.get("title_a") or "", "title_b": item.get("title_b") or "", "score": item.get("score"), "cluster_type": item.get("cluster_type") or "", "reason": item.get("reason") or ""}


def structured_json(report: dict[str, Any]) -> dict[str, Any]:
    story = report["story"]
    daily_numbers = {"runs_completed": report.get("runs_completed"), "news_published": len(report["news"]) if report["published_available"] else None, "reports_published": len(report["reports"]), "report_status_counts": report["report_status_counts"], "article_types": dict(report["article_types"]), "menzo_first_decision": {"selected": len(report["selected"]), "pending": len(report["pending"]), "skipped": len(report["skipped"])}, "final_decision": {"selected": len(report["selected"]), "pending": len(report["pending"]), "skipped": len(report["skipped"])}, "hard_news_count": report["hard_count"], "soft_news_count": report["soft_count"], "softpool_used": report["softpool"], "alfred": {"warnings": report["warnings"], "blockers": report["blockers"]}, "duplicate_candidates": story["duplicate_candidates"], "same_story_clusters": story["same_story_clusters"], "same_event_clusters": story["same_event_clusters"], "story_reviews": story["story_reviews"], "pairs_above_threshold": story["pairs_above_threshold"], "gemini_3_5_called_total": report["gemini_called"]}
    hard_soft_balance = {"hard_news_count": report["hard_count"], "soft_news_count": report["soft_count"], "softpool_used": report["softpool"], "is_estimate": True, "source": report.get("hard_soft_source") or "n.d.", "explanation": "Stima deterministica da priority, article_type, score e decisioni Menzo disponibili; source=article_types_markdown quando derivata solo dai tipi articolo del markdown; n.d. se mancano gli artefatti affidabili."}
    redundancy_risks = {"duplicate_risk": "high" if (story["same_story_clusters"] or 0) > 3 else "medium" if (story["same_story_clusters"] or story["duplicate_candidates"] or story["same_event_clusters"]) else "low", "duplicate_candidate_count": story["duplicate_candidates"], "same_story_cluster_count": story["same_story_clusters"], "same_event_cluster_count": story["same_event_clusters"], "story_review_count": story["story_reviews"], "pairs_above_threshold": story["pairs_above_threshold"], "top_suspicious_pairs": [_compact_pair(x) for x in story["suspicious_pairs"]], "story_review_items": [_compact_pair(x) if x.get("title_a") else _compact_item(x) for x in story["story_review_items"][:10]], "show_report_integration": "post-show presente" if report["reports"] else "nessun report show pubblicato negli artefatti disponibili"}
    return {"judgment": report["judgment"], "day_type": report["day_type"], "summary": report["summary"], "daily_numbers": daily_numbers, "hard_soft_balance": hard_soft_balance, "top_discarded_candidates": [_compact_item(x) for x in report["top_discarded"]], "borderline_published": [_compact_item(x) for x in report["borderline"]], "redundancy_risks": redundancy_risks, "recommended_actions": ["Rivedere il primo URL scartato/pending se presente.", "Monitorare il rapporto hard/soft nel prossimo ciclo.", "Rafforzare il controllo post-show se emergono duplicazioni con report."], "generated_at": report["generated_at"].isoformat(), "source_artifacts_used": report["source_artifacts_used"], "missing_artifacts": report["missing_artifacts"], "schema_warnings": report["schema_warnings"]}


def email_summary(report: dict[str, Any]) -> str:
    top = report["top_discarded"][0] if report["top_discarded"] else None
    news_count = len(report["news"]) if report["published_available"] else "n.d."
    return "\n".join(["Daily Editorial Judgment:", f"- Judgment: {report['judgment']}", f"- Day type: {report['day_type']}", f"- Published: {news_count} news / {len(report['reports'])} report", f"- Hard/soft balance: {_num(report['hard_count'])} hard vs {_num(report['soft_count'])} soft (stima)", f"- Top concern: {'controllare scarti/pending ad alta rilevanza' if top else 'nessun forte candidato scartato emerso'}", f"- Top discarded URL: {_url(top) if top else 'n.d.'}"])


def generate_daily_editorial_judgment_outputs(paths: dict[str, Path] | None = None, output_dir: Path = REPORTS_DIR, state_dir: Path = STATE_REPORTS_DIR, now: datetime | None = None, hours: int = 24) -> dict[str, Path]:
    data = load_inputs(paths, hours=hours, now=now)
    status = data.get("__artifact_status__", {})
    report = build_report(data, generated_at=now, source_artifacts_used=list(status.get("used") or []), missing_artifacts=list(status.get("missing") or []))
    output_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    ts = (now or report["generated_at"]).strftime("%Y%m%d_%H%M%S")
    markdown_path = output_dir / f"owtv_daily_editorial_judgment_24h_{ts}.md"
    json_path = output_dir / f"owtv_daily_editorial_judgment_24h_{ts}.json"
    latest_json_path = state_dir / "owtv_daily_editorial_judgment_latest.json"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    json_text = json.dumps(structured_json(report), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    latest_json_path.write_text(json_text, encoding="utf-8")
    return {"markdown": markdown_path, "json": json_path, "latest_json": latest_json_path}


def generate_daily_editorial_judgment_report(paths: dict[str, Path] | None = None, output_dir: Path = REPORTS_DIR, now: datetime | None = None, hours: int = 24) -> Path:
    state_dir = STATE_REPORTS_DIR if output_dir == REPORTS_DIR else output_dir / "state_reports"
    return generate_daily_editorial_judgment_outputs(paths=paths, output_dir=output_dir, state_dir=state_dir, now=now, hours=hours)["markdown"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the report-only OWTV daily editorial judgment.")
    parser.add_argument("--hours", type=int, default=24, help="Report/Gemini ledger window in hours (default: 24).")
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR, help="Output directory for judgment markdown/json.")
    args = parser.parse_args()
    print(generate_daily_editorial_judgment_report(output_dir=args.output_dir, hours=args.hours))
