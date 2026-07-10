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
    "master_log": ("state/newsroom/master_log.jsonl", "artifacts/newsroom/master_log_tail.jsonl", "logs/newsroom_master.log", "artifacts/newsroom/master_log_latest.json"),
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
    if (
        (not paths or "master_log" not in paths)
        and isinstance(data.get("master_log"), dict)
        and data["master_log"].get("_schema_warning")
        and (ROOT / "artifacts/newsroom/master_log_tail.jsonl").exists()
    ):
        tail = ROOT / "artifacts/newsroom/master_log_tail.jsonl"
        data["master_log"] = _load(tail)
        used = [u for u in used if "master_log" not in u] + [_rel(tail, "master_log")]
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


def _wp_link(item: dict[str, Any]) -> str:
    return str(item.get("wp_link") or item.get("wordpress_url") or item.get("published_url") or "").strip()


def _dedupe_key(item: dict[str, Any]) -> str:
    source_url = str(item.get("source_url") or item.get("url") or item.get("link") or "").strip().lower()
    if source_url:
        return "source_url:" + source_url
    wp_link = _wp_link(item).lower()
    if wp_link:
        return "wp_link:" + wp_link
    title = re.sub(r"\s+", " ", _title(item).lower()).strip()
    return "title:" + title


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for record in records:
        key = _dedupe_key(record)
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def _editorial_aggregation_key(item: dict[str, Any]) -> str:
    source_url = str(item.get("source_url") or "").strip().lower()
    if source_url:
        return "source_url:" + source_url
    url = str(item.get("url") or item.get("link") or "").strip().lower()
    if url:
        return "url:" + url
    wp_link = _wp_link(item).lower()
    if wp_link:
        return "wp_link:" + wp_link
    title = re.sub(r"\s+", " ", _title(item).lower()).strip()
    return "title:" + title


def _editorial_record_richness(item: dict[str, Any]) -> int:
    return sum(
        1
        for value in (
            _numeric_score(item),
            item.get("priority"),
            item.get("article_type"),
            item.get("decision"),
            item.get("reason") or item.get("menzo_reason"),
            item.get("source"),
            _wp_link(item),
        )
        if value
    )


def _dedupe_editorial_aggregation_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _editorial_aggregation_key(record)
        current = by_key.get(key)
        if current is None or _editorial_record_richness(record) > _editorial_record_richness(current):
            by_key[key] = record
    return list(by_key.values())


def _numeric_score(item: dict[str, Any]) -> int | None:
    for key in ("native_score", "score", "deterministic_score", "final_score", "priority_score"):
        try:
            value = item.get(key)
            if value is None or value == "":
                continue
            return int(float(value))
        except Exception:
            continue
    return None


def _score(item: dict[str, Any]) -> int:
    return _numeric_score(item) or 0


def _article_type(item: dict[str, Any]) -> str:
    return str(item.get("article_type") or item.get("type") or item.get("category") or item.get("cluster_type") or "unknown").strip().lower()


def _to_int_if_numeric(value: Any) -> Any:
    try:
        if value is None or value == "":
            return value
        numeric = float(value)
        if numeric.is_integer():
            return int(numeric)
    except Exception:
        return value
    return value


def is_hard(item: dict[str, Any]) -> bool:
    at = _article_type(item)
    pr = str(item.get("priority") or "").lower()
    blob = f"{at} {pr} {_title(item)} {_url(item)}".lower()
    return at in HARD_TYPES or pr in {"hard", "high", "major"} or any(t in blob for t in ("injury", "contract", "roster", "release", "title change", "business"))


def is_soft(item: dict[str, Any]) -> bool:
    at = _article_type(item)
    return at in SOFT_TYPES or str(item.get("priority") or "").lower() in {"soft", "low", "medium"}


def _is_count_placeholder(item: dict[str, Any]) -> bool:
    if item.get("_placeholder_from_markdown") is True:
        return True
    has_identity = bool(_title(item) != "Senza titolo" or _url(item) or str(item.get("source") or "").strip())
    return not has_identity and set(item).issubset({"count", "published_count", "_count_only", "_placeholder_from_markdown"})


def collect_menzo(data: dict[str, Any]) -> dict[str, Any]:
    menzo = data.get("menzo_latest") or {}
    if not menzo and isinstance(_nested(data.get("master_log", {}), "latest", "menzo"), dict):
        menzo = _nested(data.get("master_log", {}), "latest", "menzo")
    if not menzo and isinstance(_nested(data.get("master_log", {}), "menzo"), dict):
        menzo = _nested(data.get("master_log", {}), "menzo")
    return menzo if isinstance(menzo, dict) else {}


def _menzo_selected_map(data: dict[str, Any], menzo: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    if isinstance(menzo, dict):
        selected.extend(_items(menzo, "selected"))
    for master in _master_records_in_window(data):
        selected.extend(_items(_nested(master, "menzo") or {}, "selected"))
        selected.extend(_items(_nested(master, "menzo", "first_decision") or {}, "selected"))
        selected.extend(_items(_nested(master, "menzo", "decisions") or {}, "selected"))
    out: dict[str, dict[str, Any]] = {}
    for item in selected:
        url = str(item.get("source_url") or item.get("url") or item.get("link") or "").strip()
        if url:
            out[url] = item
    return out


def _enrich_published_with_menzo(record: dict[str, Any], selected_by_url: dict[str, dict[str, Any]]) -> dict[str, Any]:
    url = str(record.get("source_url") or record.get("url") or record.get("link") or "").strip()
    selected = selected_by_url.get(url)
    if not selected:
        return record
    enriched = dict(record)
    for key in ("score", "deterministic_score", "priority", "article_type", "decision", "source", "category_hint", "ai_priority_label"):
        if selected.get(key) is not None:
            enriched[key] = selected.get(key)
    if selected.get("reason") is not None:
        enriched["reason"] = selected.get("reason")
        enriched["menzo_reason"] = selected.get("reason")
    if selected.get("source_url") is not None:
        enriched["source_url"] = selected.get("source_url")
    return enriched


def _master(data: dict[str, Any]) -> dict[str, Any]:
    master = data.get("master_log", {})
    if isinstance(master.get("latest"), dict):
        return master["latest"]
    return master if isinstance(master, dict) else {}


def _master_log_source(data: dict[str, Any]) -> str:
    for item in (data.get("__artifact_status__", {}) or {}).get("used", []):
        if str(item).endswith("state/newsroom/master_log.jsonl"):
            return "master_log"
        if "master_log_tail.jsonl" in str(item):
            return "master_log_tail_partial"
    master = data.get("master_log", {})
    if isinstance(master, dict) and master.get("_format") == "jsonl":
        return "master_log"
    return "inline_or_latest"


def _record_timestamp(record: dict[str, Any]) -> datetime | None:
    return (
        _parse_dt(record.get("recorded_at"))
        or _parse_dt(_nested(record, "run", "ended_at"))
        or _parse_dt(_nested(record, "run", "started_at"))
    )


def _master_records_in_window(data: dict[str, Any]) -> list[dict[str, Any]]:
    master = data.get("master_log", {})
    if not isinstance(master, dict) or not isinstance(master.get("records"), list):
        latest = _master(data)
        return [latest] if latest else []
    window = data.get("__window__", {}) if isinstance(data.get("__window__"), dict) else {}
    now = _parse_dt(window.get("now")) if window else None
    try:
        hours = int(window.get("hours") or 24)
    except Exception:
        hours = 24
    until_ts = now.timestamp() if now else None
    since_ts = (until_ts - (hours * 3600)) if until_ts is not None else None
    selected: list[dict[str, Any]] = []
    for record in master["records"]:
        if not isinstance(record, dict):
            continue
        stamp = _record_timestamp(record)
        if since_ts is not None and stamp is not None and stamp.timestamp() < since_ts:
            continue
        if until_ts is not None and stamp is not None and stamp.timestamp() > until_ts:
            continue
        selected.append(record)
    return selected


def collect_published(data: dict[str, Any], menzo: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    records = _master_records_in_window(data)
    selected_by_url = _menzo_selected_map(data, menzo)
    include_already_published_reports = _master_log_source(data) in {"master_log", "master_log_tail_partial"}
    news: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    all_reports: list[dict[str, Any]] = []
    news_stream_available = False
    report_stream_available = False
    for master in records:
        publisher = _nested(master, "publisher") or {}
        publisher_published = _items(publisher, "published")
        publisher_results = _items(publisher, "results")
        if isinstance(publisher, dict) and ("published" in publisher or "results" in publisher):
            news_stream_available = True
        news.extend(_enrich_published_with_menzo(r, selected_by_url) for r in publisher_published)
        news.extend(_enrich_published_with_menzo(r, selected_by_url) for r in publisher_results if str(r.get("status")).lower() == "published")
        simone = _nested(master, "simone") or {}
        run_reports = _items(simone, "published_reports")
        if isinstance(simone, dict) and "published_reports" in simone:
            report_stream_available = True
        all_reports.extend(run_reports)
        reports.extend(
            r
            for r in run_reports
            if str(r.get("status") or "").lower() == "published"
            or (include_already_published_reports and str(r.get("status") or "").lower() == "already_published")
        )
    news = _dedupe_records(news)
    reports = _dedupe_records(reports)
    report_status_counts = Counter(str(r.get("status") or "unknown").lower() for r in all_reports)
    return news, reports, {
        "available": bool(records),
        "news_stream_available": news_stream_available,
        "report_stream_available": report_stream_available,
        "report_status_counts": dict(report_status_counts),
        "published_records_source": _master_log_source(data),
    }


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


def _has_meaningful_editorial_metadata(item: dict[str, Any]) -> bool:
    return (
        _numeric_score(item) is not None
        or bool(str(item.get("priority") or "").strip())
        or _article_type(item) != "unknown"
        or bool(str(item.get("reason") or item.get("menzo_reason") or item.get("decision") or "").strip())
    )


def _is_borderline_published(item: dict[str, Any]) -> bool:
    if not _has_meaningful_editorial_metadata(item):
        return False
    score = _numeric_score(item)
    priority = str(item.get("priority") or "").strip().lower()
    article_type = _article_type(item)
    if score is not None and score < 65:
        return True
    if priority in {"soft", "skip", "low"}:
        return True
    return article_type in SOFT_TYPES or article_type in {"strategic_discussion", "low_value", "news_generica"}


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


def _parse_markdown_report_text(text: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    runs = _md_int(text, (r"^\s*-?\s*Run completate\s*:\s*(\d+)\s*$", r"runs completed\D+(\d+)"))
    if runs is not None:
        parsed["runs_completed"] = runs
    news_count = _md_int(text, (r"^\s*-?\s*Articoli/news pubblicati da Publisher\s*:\s*(\d+)\s*$", r"news published\D+(\d+)", r"news_published\D+(\d+)"))
    reports_count = _md_int(text, (r"^\s*-?\s*Report pubblicati da Simone\s*:\s*(\d+)\s*$", r"reports? show published\D+(\d+)", r"reports? published\D+(\d+)", r"reports_published\D+(\d+)"))
    if news_count is not None:
        parsed["news_count"] = news_count
        parsed["news"] = [{"_placeholder_from_markdown": True} for _ in range(news_count)]
    if reports_count is not None:
        parsed["reports_count"] = reports_count
        parsed["reports"] = [{"_placeholder_from_markdown": True} for _ in range(reports_count)]
    decision = re.search(r"Menzo first decision selected/pending/skipped\D+(\d+)\D+(\d+)\D+(\d+)", text, re.I)
    if decision:
        parsed["menzo"] = {
            "selected": [{"_placeholder_from_markdown": True} for _ in range(int(decision.group(1)))],
            "pending": [{"_placeholder_from_markdown": True} for _ in range(int(decision.group(2)))],
            "skipped": [{"_placeholder_from_markdown": True} for _ in range(int(decision.group(3)))],
        }
    types: Counter[str] = Counter()
    section = re.search(r"^##\s*3\.\s*Tipologia contenuti pubblicati/rilevati\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.I | re.M)
    if section:
        for name, value in re.findall(r"^\s*-\s*([^:\n]+?)\s*:\s*(\d+)\s*$", section.group(1), re.M):
            key = name.strip()
            if key.lower().startswith(("alfred", "blocker alfred")):
                continue
            types[key] += int(value)
    type_match = re.search(r"article types?\s*[:=]\s*(\{[^\n]+\}|[^\n]+)", text, re.I)
    if type_match and not types:
        raw = type_match.group(1).strip()
        try:
            parsed_obj = json.loads(raw.replace("'", '"'))
            if isinstance(parsed_obj, dict):
                types.update({str(k): int(v) for k, v in parsed_obj.items()})
        except Exception:
            for name, value in re.findall(r"([a-zA-Z_/]+)\D+(\d+)", raw):
                types[name.lower()] += int(value)
    if types:
        parsed["article_types"] = types
    alfred_pair = re.search(r"Alfred warnings/blockers\D+(\d+|n\.d\.)\D+(\d+|n\.d\.)", text, re.I)
    if alfred_pair:
        parsed["warnings"], parsed["blockers"] = _to_int_if_numeric(alfred_pair.group(1)), _to_int_if_numeric(alfred_pair.group(2))
    warnings = _md_int(text, (r"^\s*-?\s*Alfred warnings\s*:\s*(\d+)\s*$",))
    blockers = _md_int(text, (r"^\s*-?\s*Alfred blockers\s*:\s*(\d+)\s*$", r"^\s*-?\s*Blocker Alfred\s*:\s*(\d+)\s*$"))
    if warnings is not None:
        parsed["warnings"] = warnings
    if blockers is not None:
        parsed["blockers"] = blockers
    pub_errors = _md_int(text, (r"Publisher errors\D+(\d+)",))
    andrea_blocked = _md_int(text, (r"Andrea blocked\D+(\d+)",))
    if pub_errors is not None:
        parsed["publisher_errors"] = pub_errors
    if andrea_blocked is not None:
        parsed["andrea_blocked"] = andrea_blocked
    gemini = _md_int(text, (r"Gemini(?:\s+3\.5)? called total\D+(\d+)", r"gemini[_\s-]*3[_\s.-]*5[_\s-]*called[_\s-]*total\D+(\d+)"))
    if gemini is not None:
        parsed["gemini_3_5_called_total"] = gemini
    return parsed


def parse_daily_markdown_inputs(data: dict[str, Any]) -> dict[str, Any]:
    """Parse real 24h markdown reports without inventing zeroes on mismatch."""
    operational = str((data.get("operational_report") or {}).get("_markdown") or "")
    editorial = str((data.get("editorial_audit") or {}).get("_markdown") or "")
    if not (operational.strip() or editorial.strip()):
        return {}
    op = _parse_markdown_report_text(operational)
    audit = _parse_markdown_report_text(editorial)
    parsed = dict(audit)
    # Operational report is authoritative for run/publication/Alfred counters.
    for key in ("runs_completed", "news_count", "news", "reports_count", "reports", "warnings", "blockers", "publisher_errors", "andrea_blocked", "gemini_3_5_called_total"):
        if key in op:
            parsed[key] = op[key]
    if "menzo" in op:
        parsed["menzo"] = op["menzo"]
    # Editorial audit section is authoritative for content taxonomy.
    if isinstance(audit.get("article_types"), Counter):
        parsed["article_types"] = audit["article_types"]
    elif isinstance(op.get("article_types"), Counter):
        parsed["article_types"] = op["article_types"]
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
    news, reports, published_meta = collect_published(data, menzo)
    markdown_news_available = "news_count" in parsed_md
    markdown_reports_available = "reports_count" in parsed_md
    concrete_news_records = [x for x in news if not x.get("_placeholder_from_markdown")]
    concrete_report_records = [x for x in reports if not x.get("_placeholder_from_markdown")]
    news_stream_available = bool(published_meta.get("news_stream_available"))
    report_stream_available = bool(published_meta.get("report_stream_available"))
    news_records_available = bool(concrete_news_records)
    report_records_available = bool(concrete_report_records)
    if not news_records_available and markdown_news_available:
        news = parsed_md.get("news", news)
    if not report_records_available and markdown_reports_available:
        reports = parsed_md.get("reports", reports)
    news_count_available = news_records_available or markdown_news_available or news_stream_available
    reports_count_available = report_records_available or markdown_reports_available or report_stream_available
    if not (news_count_available or reports_count_available):
        schema_warnings.append("published_counts_not_available")
    if not news_count_available:
        schema_warnings.append("news_published_count_not_available")
    if not reports_count_available:
        schema_warnings.append("reports_published_count_not_available")
    selected, pending, skipped = _items(menzo, "selected"), _items(menzo, "pending"), _items(menzo, "skipped") or _items(menzo, "skipped_sample")
    concrete_selected = [x for x in selected if not x.get("_placeholder_from_markdown")]
    concrete_news = [x for x in news if not x.get("_placeholder_from_markdown")]
    concrete_reports = [x for x in reports if not x.get("_placeholder_from_markdown")]
    aggregate_items = _dedupe_editorial_aggregation_items(concrete_selected + concrete_news)
    article_types = Counter(_article_type(x) for x in aggregate_items if _article_type(x) != "unknown")
    if isinstance(parsed_md.get("article_types"), Counter):
        article_types = parsed_md["article_types"]
    hard_soft_source = None if isinstance(parsed_md.get("article_types"), Counter) else ("records" if (concrete_selected or concrete_news) else None)
    hard_count = sum(1 for x in aggregate_items if is_hard(x)) if hard_soft_source == "records" else None
    soft_count = sum(1 for x in aggregate_items if is_soft(x)) if hard_soft_source == "records" else None
    if hard_soft_source is None and article_types:
        hard_count, soft_count = _article_type_hard_soft_counts(article_types)
        hard_soft_source = "article_types_markdown"
    story = parse_story_cluster_audit(data.get("story_cluster_audit", {}))
    schema_warnings.extend(story["schema_warnings"])
    official_counts_authoritative = published_meta.get("published_records_source") in {"master_log", "master_log_tail_partial"}
    news_published_count = (parsed_md.get("news_count") if markdown_news_available and official_counts_authoritative else (len(concrete_news) if concrete_news else (parsed_md.get("news_count") if markdown_news_available else (0 if news_stream_available else None))))
    reports_published_count = (parsed_md.get("reports_count") if markdown_reports_available and official_counts_authoritative else (len(concrete_reports) if concrete_reports else (parsed_md.get("reports_count") if markdown_reports_available else (0 if report_stream_available else None))))
    dtype = day_type(news_published_count, reports_published_count, hard_count, story["story_reviews"])
    softpool = _nested(menzo, "softpool", "injected_candidates") or _nested(menzo, "daily_policy", "softpool_used") or any(x.get("from_softpool") for x in selected + pending + skipped)
    warnings = parsed_md.get("warnings")
    blockers = parsed_md.get("blockers")
    if warnings is None:
        warnings = _nested(_master(data), "alfred", "handoff", "warnings") or _nested(_master(data), "alfred", "postprocess", "warnings") or "n.d."
    if blockers is None:
        blockers = _nested(_master(data), "alfred", "handoff", "blockers") or "n.d."
    warnings = _to_int_if_numeric(warnings)
    blockers = _to_int_if_numeric(blockers)
    gemini_called = _gemini_35_calls(data)
    runs_completed = parsed_md.get("runs_completed")
    news_published_count = (parsed_md.get("news_count") if markdown_news_available and official_counts_authoritative else (len(concrete_news) if concrete_news else (parsed_md.get("news_count") if markdown_news_available else (0 if news_stream_available else None))))
    reports_published_count = (parsed_md.get("reports_count") if markdown_reports_available and official_counts_authoritative else (len(concrete_reports) if concrete_reports else (parsed_md.get("reports_count") if markdown_reports_available else (0 if report_stream_available else None))))
    if markdown_news_available and concrete_news and len(concrete_news) != parsed_md.get("news_count") and official_counts_authoritative:
        schema_warnings.append("published_record_count_differs_from_official_count")
    if markdown_reports_available and concrete_reports and len(concrete_reports) != parsed_md.get("reports_count") and official_counts_authoritative:
        schema_warnings.append("published_record_count_differs_from_official_count")
    published_total = (news_published_count or 0) + (reports_published_count or 0) if (news_published_count is not None or reports_published_count is not None) else None
    judgment = "OTTIMO" if (hard_count or 0) >= 8 and len(top_discarded(menzo, 1)) == 0 else "BUONO" if (published_total or 0) >= 8 else "DISCRETO" if (published_total or 0) >= 3 else "DEBOLE"
    top = top_discarded(menzo)
    published_items_for_review = _dedupe_editorial_aggregation_items([x for x in concrete_news if not _is_count_placeholder(x)])
    borderline = [x for x in published_items_for_review if _is_borderline_published(x)][:3]
    news_label = str(news_published_count) if news_published_count is not None else "n.d."
    reports_label = str(reports_published_count) if reports_published_count is not None else "n.d."
    summary = f"Giornata {dtype} con {news_label} news e {reports_label} report show pubblicati. La copertura hard news è stimata a {hard_count if hard_count is not None else 'n.d.'} elementi e quella soft a {soft_count if soft_count is not None else 'n.d.'}; {'softpool usato' if softpool else 'softpool non usato'}."
    if top:
        summary += " Il principale controllo umano riguarda: " + _title(top[0]) + "."
    else:
        summary += " Non emergono forti candidati scartati da recuperare."
    return {"generated_at": generated_at, "source_artifacts_used": used, "missing_artifacts": missing, "schema_warnings": list(dict.fromkeys(schema_warnings)), "published_available": news_count_available or reports_count_available, "report_status_counts": published_meta["report_status_counts"], "published_records_source": published_meta.get("published_records_source"), "official_news_published_count": parsed_md.get("news_count") if markdown_news_available else None, "concrete_news_record_count": len(concrete_news), "menzo": menzo, "news": news, "reports": reports, "news_records": concrete_news, "report_records": concrete_reports, "selected": selected, "pending": pending, "skipped": skipped, "runs_completed": runs_completed, "news_published_count": news_published_count, "reports_published_count": reports_published_count, "news_count_available": news_count_available, "reports_count_available": reports_count_available, "hard_count": hard_count, "soft_count": soft_count, "hard_soft_source": hard_soft_source, "story": story, "day_type": dtype, "softpool": bool(softpool), "warnings": warnings, "blockers": blockers, "gemini_called": gemini_called, "article_types": article_types, "judgment": judgment, "top_discarded": top, "borderline": borderline, "summary": summary}


def _num(value: Any) -> str:
    return str(value) if value is not None else "n.d."


def render_markdown(report: dict[str, Any]) -> str:
    story = report["story"]
    lines = ["# OWTV Daily Editorial Judgment 24h", "", "## Daily Editorial Judgment", "", f"- Judgment: {report['judgment']}", f"- Day type: {report['day_type']}", "", report["summary"], "", "## Daily numbers", "", f"- runs completed: {_num(report.get('runs_completed'))}", f"- news published: {_num(report.get('news_published_count'))}", f"- reports published: {_num(report.get('reports_published_count'))}", f"- article types: {dict(report['article_types']) or 'n.d.'}", f"- Menzo first decision selected/pending/skipped: {len(report['selected'])}/{len(report['pending'])}/{len(report['skipped'])}", f"- final selected/pending/skipped: {len(report['selected'])}/{len(report['pending'])}/{len(report['skipped'])}", f"- hard news count: {_num(report['hard_count'])} (stima)", f"- soft news count: {_num(report['soft_count'])} (stima)", f"- softpool used: {'yes' if report['softpool'] else 'no'}", f"- Alfred warnings/blockers: {report['warnings']}/{report['blockers']}", f"- duplicate candidates / same story clusters / same event clusters / story reviews: {_num(story['duplicate_candidates'])} / {_num(story['same_story_clusters'])} / {_num(story['same_event_clusters'])} / {_num(story['story_reviews'])}", f"- suspicious pairs above threshold: {_num(story['pairs_above_threshold'])}", f"- Gemini 3.5 called total: {report['gemini_called']}", "", "## Hard vs soft editorial balance", "", f"Stima: {_num(report['hard_count'])} hard news e {_num(report['soft_count'])} soft news. " + ("Il ricorso al softpool sembra giustificato solo se le hard news erano limitate." if report['softpool'] else "Softpool non usato: scelta coerente se la giornata aveva sufficiente materiale hard o nessun soft recuperabile."), "", "## Top 3 discarded URLs for human control", ""]
    if not report["top_discarded"]:
        lines.append("Nessun forte candidato scartato/pending emerso dagli artefatti disponibili.")
    for item in report["top_discarded"]:
        lines += [f"### {_title(item)}", f"- source: {item.get('source') or 'n.d.'}", f"- url: {_url(item) or 'n.d.'}", f"- score: {_score(item) or 'n.d.'}", f"- article_type: {_article_type(item)}", f"- priority: {item.get('priority') or 'n.d.'}", f"- Menzo decision/reason: {item.get('_decision_bucket')} / {item.get('reason') or 'n.d.'}", "- why it is worth checking: punteggio/priorità o rilevanza potenziale per il pubblico OWTV.", f"- automatic judgment: {_auto_judgment(item)}", ""]
    lines += ["## Published borderline/soft picks", ""]
    if not report["borderline"]:
        if (report.get("news_published_count") is not None or report.get("reports_published_count") is not None) and not (report.get("news_records") or report.get("report_records")):
            lines.append("Nessun articolo pubblicato borderline valutabile perché sono disponibili solo conteggi aggregati.")
        else:
            lines.append("Nessun pick pubblicato chiaramente borderline/soft dagli artefatti disponibili.")
    for item in report["borderline"]:
        lines += [f"- {_title(item)} — type={_article_type(item)}, score={_score(item) or 'n.d.'}, valutazione: accettabile se utile al mix quotidiano; da monitorare se sostituisce hard news."]
    lines += ["", "## Redundancy and show-report integration", "", f"Duplicate risk: {'high' if (story['same_story_clusters'] or 0) > 3 else 'medium' if (story['same_story_clusters'] or story['duplicate_candidates'] or story['same_event_clusters']) else 'low'}. Same-story clusters: {_num(story['same_story_clusters'])}. Story_review items: {_num(story['story_reviews'])}. Le news risultato/evento vanno controllate rispetto ai report show quando presenti; pubblicazione post-show {'presente' if (report.get('reports_published_count') or 0) > 0 else 'non presente'}.", ""]
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
    compact = {"title": _title(item), "source": item.get("source") or "", "url": _url(item), "score": _numeric_score(item), "article_type": _article_type(item), "priority": item.get("priority") or "", "menzo_decision": item.get("_decision_bucket") or item.get("decision") or "", "menzo_reason": item.get("menzo_reason") or item.get("reason") or "", "automatic_judgment": _auto_judgment(item) if item.get("_decision_bucket") else ""}
    if item.get("source_url"):
        compact["source_url"] = item.get("source_url")
    if _wp_link(item):
        compact["wp_link"] = _wp_link(item)
    return compact


def _compact_pair(item: dict[str, Any]) -> dict[str, Any]:
    return {"title_a": item.get("title_a") or "", "title_b": item.get("title_b") or "", "score": item.get("score"), "cluster_type": item.get("cluster_type") or "", "reason": item.get("reason") or ""}


def structured_json(report: dict[str, Any]) -> dict[str, Any]:
    story = report["story"]
    daily_numbers = {"runs_completed": report.get("runs_completed"), "news_published": report.get("news_published_count"), "reports_published": report.get("reports_published_count"), "news_published_count": report.get("news_published_count"), "reports_published_count": report.get("reports_published_count"), "official_news_published_count": report.get("official_news_published_count"), "concrete_news_record_count": report.get("concrete_news_record_count"), "published_records_source": report.get("published_records_source"), "news_records": [_compact_item(x) for x in report.get("news_records", [])], "report_records": [_compact_item(x) for x in report.get("report_records", [])], "report_status_counts": report["report_status_counts"], "article_types": dict(report["article_types"]), "menzo_first_decision": {"selected": len(report["selected"]), "pending": len(report["pending"]), "skipped": len(report["skipped"])}, "final_decision": {"selected": len(report["selected"]), "pending": len(report["pending"]), "skipped": len(report["skipped"])}, "hard_news_count": report["hard_count"], "soft_news_count": report["soft_count"], "softpool_used": report["softpool"], "alfred": {"warnings": report["warnings"], "blockers": report["blockers"]}, "duplicate_candidates": story["duplicate_candidates"], "same_story_clusters": story["same_story_clusters"], "same_event_clusters": story["same_event_clusters"], "story_reviews": story["story_reviews"], "pairs_above_threshold": story["pairs_above_threshold"], "gemini_3_5_called_total": report["gemini_called"]}
    hard_soft_balance = {"hard_news_count": report["hard_count"], "soft_news_count": report["soft_count"], "softpool_used": report["softpool"], "is_estimate": True, "source": report.get("hard_soft_source") or "n.d.", "explanation": "Stima deterministica da priority, article_type, score e decisioni Menzo disponibili; source=article_types_markdown quando derivata solo dai tipi articolo del markdown; n.d. se mancano gli artefatti affidabili."}
    redundancy_risks = {"duplicate_risk": "high" if (story["same_story_clusters"] or 0) > 3 else "medium" if (story["same_story_clusters"] or story["duplicate_candidates"] or story["same_event_clusters"]) else "low", "duplicate_candidate_count": story["duplicate_candidates"], "same_story_cluster_count": story["same_story_clusters"], "same_event_cluster_count": story["same_event_clusters"], "story_review_count": story["story_reviews"], "pairs_above_threshold": story["pairs_above_threshold"], "top_suspicious_pairs": [_compact_pair(x) for x in story["suspicious_pairs"]], "story_review_items": [_compact_pair(x) if x.get("title_a") else _compact_item(x) for x in story["story_review_items"][:10]], "show_report_integration": "post-show presente" if (report.get("reports_published_count") or 0) > 0 else "nessun report show pubblicato negli artefatti disponibili"}
    return {"judgment": report["judgment"], "day_type": report["day_type"], "summary": report["summary"], "daily_numbers": daily_numbers, "hard_soft_balance": hard_soft_balance, "top_discarded_candidates": [_compact_item(x) for x in report["top_discarded"]], "borderline_published": [_compact_item(x) for x in report["borderline"]], "redundancy_risks": redundancy_risks, "recommended_actions": ["Rivedere il primo URL scartato/pending se presente.", "Monitorare il rapporto hard/soft nel prossimo ciclo.", "Rafforzare il controllo post-show se emergono duplicazioni con report."], "generated_at": report["generated_at"].isoformat(), "source_artifacts_used": report["source_artifacts_used"], "missing_artifacts": report["missing_artifacts"], "schema_warnings": report["schema_warnings"]}


def email_summary(report: dict[str, Any]) -> str:
    top = report["top_discarded"][0] if report["top_discarded"] else None
    news_count = _num(report.get("news_published_count"))
    reports_count = _num(report.get("reports_published_count"))
    return "\n".join(["Daily Editorial Judgment:", f"- Judgment: {report['judgment']}", f"- Day type: {report['day_type']}", f"- Published: {news_count} news / {reports_count} report", f"- Hard/soft balance: {_num(report['hard_count'])} hard vs {_num(report['soft_count'])} soft (stima)", f"- Top concern: {'controllare scarti/pending ad alta rilevanza' if top else 'nessun forte candidato scartato emerso'}", f"- Top discarded URL: {_url(top) if top else 'n.d.'}"])


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
