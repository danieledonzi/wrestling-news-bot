from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_FILE = ROOT / "state" / "newsroom" / "gemini_call_ledger.jsonl"
MENZO_CACHE_FILE = ROOT / "state" / "newsroom" / "menzo_duplicate_arbitration_cache.json"

REASON_FIELDS = ("reason", "purpose", "phase", "task", "selected_model_chain_reason")
MODEL_FIELDS = ("model", "actual_model", "selected_model", "translation_model")
AGENT_FIELDS = ("agent", "stage", "caller")


def _first(record: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = record.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "unknown"


def reason_or_purpose(record: dict[str, Any]) -> str:
    return _first(record, REASON_FIELDS)


def model_name(record: dict[str, Any]) -> str:
    return _first(record, MODEL_FIELDS)


def agent_name(record: dict[str, Any]) -> str:
    return _first(record, AGENT_FIELDS)


def status_name(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "").strip().lower()
    if status in {"called", "avoided", "failed"}:
        return status
    if record.get("saved_gemini_call") is True:
        return "avoided"
    return "unknown"


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def load_ledger(path: Path = LEDGER_FILE, *, hours: int = 24, now: datetime | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    if not path.exists():
        return [], [f"ledger file missing: {path}"]
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=hours)
    records: list[dict[str, Any]] = []
    try:
        for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except Exception as exc:
                warnings.append(f"invalid ledger JSON line {idx}: {exc}")
                continue
            if not isinstance(data, dict):
                continue
            ts = parse_dt(data.get("timestamp") or data.get("generated_at") or data.get("started_at"))
            if ts is None or ts >= cutoff:
                records.append(data)
    except Exception as exc:
        return [], [f"ledger read failed: {exc}"]
    return records, warnings


def normalize_title(title: Any) -> str:
    text = re.sub(r"\s+", " ", str(title or "").strip().lower())
    text = re.sub(r"[^a-z0-9à-ÿ ]+", "", text)
    return text or "unknown"


def _counter(records: list[dict[str, Any]], *parts: str) -> Counter[str]:
    c: Counter[str] = Counter()
    for r in records:
        vals = []
        for part in parts:
            vals.append({"model": model_name, "agent": agent_name, "reason": reason_or_purpose, "status": status_name}[part](r))
        c[" × ".join(vals)] += 1
    return c


def _top_titles(records: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        grouped[normalize_title(r.get("title") or r.get("candidate_title"))].append(r)
    rows = []
    for key, items in grouped.items():
        times = [str(i.get("timestamp") or "") for i in items if i.get("timestamp")]
        rows.append({
            "title": key[:120],
            "called_count": len(items),
            "models": sorted({model_name(i) for i in items}),
            "agents": sorted({agent_name(i) for i in items}),
            "reasons": sorted({reason_or_purpose(i) for i in items}),
            "first_timestamp": min(times) if times else "",
            "last_timestamp": max(times) if times else "",
        })
    return sorted(rows, key=lambda x: (-int(x["called_count"]), str(x["title"])))[:limit]


def load_menzo_cache(path: Path = MENZO_CACHE_FILE, *, now: datetime | None = None) -> dict[str, Any]:
    out = {"present": path.exists(), "warnings": [], "entries_total": 0, "entries_expired": 0, "entries_valid": 0, "newest": []}
    if not path.exists():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        out["warnings"].append(f"cache read/parse warning: {exc}")
        return out
    entries = data.values() if isinstance(data, dict) else data if isinstance(data, list) else []
    rows = [e for e in entries if isinstance(e, dict)]
    out["entries_total"] = len(rows)
    now_dt = now or datetime.now(timezone.utc)
    for e in rows:
        exp = parse_dt(e.get("expires_at") or e.get("expire_at"))
        if exp and exp < now_dt:
            out["entries_expired"] += 1
        else:
            out["entries_valid"] += 1
    rows.sort(key=lambda e: str(e.get("created_at") or e.get("timestamp") or ""), reverse=True)
    out["newest"] = [{k: str(e.get(k) or "")[:120] for k in ("created_at", "model_used", "decision", "candidate_title_normalized")} for e in rows[:5]]
    return out


def build_gemini_diagnostics(records: list[dict[str, Any]], cache_path: Path = MENZO_CACHE_FILE) -> dict[str, Any]:
    called = [r for r in records if status_name(r) == "called"]
    avoided = [r for r in records if status_name(r) == "avoided"]
    failed = [r for r in records if status_name(r) == "failed"]
    called35 = [r for r in called if "3.5" in model_name(r)]
    avoided35 = [r for r in avoided if "3.5" in model_name(r)]
    return {
        "called_total": len(called), "avoided_total": len(avoided), "failed_total": len(failed),
        "called_by_model_agent": dict(_counter(called, "model", "agent")),
        "called_by_model_agent_reason": dict(_counter(called, "model", "agent", "reason")),
        "called_by_agent_reason": dict(_counter(called, "agent", "reason")),
        "called_35_total": len(called35),
        "called_35_rows": [{"timestamp": str(r.get("timestamp") or ""), "agent": agent_name(r), "reason_or_purpose": reason_or_purpose(r), "title": str(r.get("title") or "")[:120], "url": str(r.get("url") or "")[:180], "run_id": str(r.get("run_id") or "")} for r in called35[:50]],
        "called_35_by_agent": dict(_counter(called35, "agent")),
        "called_35_by_reason": dict(_counter(called35, "reason")),
        "avoided_35_total": len(avoided35),
        "avoided_35_by_reason": dict(_counter(avoided35, "reason")),
        "avoided_by_agent": dict(_counter(avoided, "agent")),
        "avoided_by_agent_reason": dict(_counter(avoided, "agent", "reason")),
        "duplicate_arbitration_cache_hit": sum(1 for r in avoided if reason_or_purpose(r) == "duplicate_arbitration_cache_hit"),
        "purpose_gate_not_met": sum(1 for r in avoided if reason_or_purpose(r) == "purpose_gate_not_met"),
        "deterministic_novelty_allow": sum(1 for r in avoided if reason_or_purpose(r) == "deterministic_novelty_allow"),
        "high_ambiguity_gate_not_met": sum(1 for r in avoided if reason_or_purpose(r) == "high_ambiguity_gate_not_met"),
        "menzo_cache_miss": sum(1 for r in records if reason_or_purpose(r) == "duplicate_arbitration_cache_miss"),
        "menzo_cache_expired": sum(1 for r in records if reason_or_purpose(r) == "duplicate_arbitration_cache_expired"),
        "menzo_cache": load_menzo_cache(cache_path),
        "top_repeated_titles": _top_titles(called),
        "top_repeated_35_titles": _top_titles(called35),
    }


def _fmt_counter(counter: dict[str, int], limit: int = 30) -> list[str]:
    if not counter:
        return ["- none"]
    return [f"- {k}: {v}" for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def render_gemini_diagnostics_markdown(diag: dict[str, Any]) -> str:
    lines = ["## Gemini / AI Detailed Ledger 24h", "", "### Gemini called by model × agent"]
    lines += _fmt_counter(diag.get("called_by_model_agent", {}))
    lines += ["", "### Gemini called by model × agent × reason_or_purpose"] + _fmt_counter(diag.get("called_by_model_agent_reason", {}))
    lines += ["", "### Gemini called by agent × reason_or_purpose"] + _fmt_counter(diag.get("called_by_agent_reason", {}))
    lines += ["", "### Gemini 3.5 Flash called", f"- 3.5 called total: {diag.get('called_35_total', 0)}"]
    lines += ["- 3.5 called by agent:"] + ["  " + x for x in _fmt_counter(diag.get("called_35_by_agent", {}))]
    lines += ["- 3.5 called by reason_or_purpose:"] + ["  " + x for x in _fmt_counter(diag.get("called_35_by_reason", {}))]
    lines += [f"- 3.5 avoided total: {diag.get('avoided_35_total', 0)}", "- 3.5 avoided by reason_or_purpose:"] + ["  " + x for x in _fmt_counter(diag.get("avoided_35_by_reason", {}))]
    for r in diag.get("called_35_rows", []):
        lines.append(f"- {r['timestamp']} | {r['agent']} | {r['reason_or_purpose']} | {r['title']} | {r['url']} | run_id={r['run_id']}")
    lines += ["", "### Gemini avoided calls", f"- avoided total: {diag.get('avoided_total', 0)}", "- avoided by agent:"] + ["  " + x for x in _fmt_counter(diag.get("avoided_by_agent", {}))]
    lines += ["- avoided by agent × reason_or_purpose:"] + ["  " + x for x in _fmt_counter(diag.get("avoided_by_agent_reason", {}))]
    for key in ("duplicate_arbitration_cache_hit", "purpose_gate_not_met", "deterministic_novelty_allow", "high_ambiguity_gate_not_met"):
        lines.append(f"- {key}: {diag.get(key, 0)}")
    cache = diag.get("menzo_cache", {}) or {}
    lines += ["", "### Menzo duplicate arbitration cache", f"- cache file present: {'yes' if cache.get('present') else 'no'}", f"- cache entries total: {cache.get('entries_total', 0)}", f"- cache entries expired: {cache.get('entries_expired', 0)}", f"- cache entries valid: {cache.get('entries_valid', 0)}", f"- duplicate_arbitration_cache_hit: {diag.get('duplicate_arbitration_cache_hit', 0)}", f"- duplicate_arbitration_cache_miss: {diag.get('menzo_cache_miss', 0)}", f"- duplicate_arbitration_cache_expired: {diag.get('menzo_cache_expired', 0)}", f"- gemini_calls_avoided_by_duplicate_arbitration_cache: {diag.get('duplicate_arbitration_cache_hit', 0)}"]
    for e in cache.get("newest", []):
        lines.append(f"- newest: {e.get('created_at')} | {e.get('model_used')} | {e.get('decision')} | {e.get('candidate_title_normalized')}")
    for w in cache.get("warnings", []):
        lines.append(f"- warning: {w}")
    lines += ["", "### Top repeated Gemini titles"]
    for label, rows in (("called", diag.get("top_repeated_titles", [])), ("3.5 called", diag.get("top_repeated_35_titles", []))):
        lines.append(f"- {label}:")
        for r in rows:
            lines.append(f"  - {r['called_count']} | {r['title']} | models={','.join(r['models'])} | agents={','.join(r['agents'])} | reasons={','.join(r['reasons'])} | first={r['first_timestamp']} | last={r['last_timestamp']}")
    return "\n".join(lines) + "\n"


def build_email_gemini_summary(diag: dict[str, Any]) -> str:
    top_agent = next(iter(sorted((diag.get("called_35_by_agent") or {}).items(), key=lambda kv: (-kv[1], kv[0]))), ("none", 0))
    top_reason = next(iter(sorted((diag.get("called_35_by_reason") or {}).items(), key=lambda kv: (-kv[1], kv[0]))), ("none", 0))
    top_title = (diag.get("top_repeated_35_titles") or [{}])[0]
    lines = ["Gemini summary:", f"- Gemini calls total: {diag.get('called_total', 0)}", f"- Gemini 3.5 called total: {diag.get('called_35_total', 0)}", f"- Gemini 3.5 top agent/purpose: {top_agent[0]} ({top_agent[1]}) / {top_reason[0]} ({top_reason[1]})", f"- Gemini avoided total: {diag.get('avoided_total', 0)}", f"- Menzo duplicate arbitration cache hits / avoided: {diag.get('duplicate_arbitration_cache_hit', 0)} / {diag.get('duplicate_arbitration_cache_hit', 0)}"]
    if top_title:
        lines.append(f"- Top repeated 3.5 title: {top_title.get('title')} ({top_title.get('called_count', 0)} calls)")
    return "\n".join(lines)
