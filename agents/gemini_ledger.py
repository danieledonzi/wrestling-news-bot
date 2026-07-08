from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
LEDGER_FILE = STATE_DIR / "gemini_call_ledger.jsonl"
LATEST_FILE = ARTIFACT_DIR / "gemini_call_ledger_latest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_run_id() -> str | None:
    return os.getenv("NEWSROOM_RUN_ID", "").strip() or None


def _clean(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    return str(value)


def record_gemini_event(**kwargs: Any) -> None:
    """Best-effort append-only Gemini/cost observability ledger."""
    try:
        record: dict[str, Any] = {
            "timestamp": kwargs.pop("timestamp", None) or utc_now(),
            "run_id": kwargs.pop("run_id", None) or current_run_id(),
            "agent": kwargs.pop("agent", None),
            "phase": kwargs.pop("phase", None),
            "model": kwargs.pop("model", None),
            "url": kwargs.pop("url", None),
            "title": kwargs.pop("title", None),
            "candidate_id": kwargs.pop("candidate_id", None),
            "source_id": kwargs.pop("source_id", None),
            "reason": kwargs.pop("reason", None),
            "status": kwargs.pop("status", None),
            "result": kwargs.pop("result", None),
            "published": kwargs.pop("published", None),
            "blocked_by_andrea": kwargs.pop("blocked_by_andrea", None),
            "blocked_by_alfred": kwargs.pop("blocked_by_alfred", None),
            "saved_gemini_call": bool(kwargs.pop("saved_gemini_call", False)),
        }
        record.update({str(k): _clean(v) for k, v in kwargs.items()})
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        with LEDGER_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_clean(record), ensure_ascii=False, sort_keys=True) + "\n")
        write_latest_snapshot(run_id=record.get("run_id"))
    except Exception:
        return


def iter_records() -> list[dict[str, Any]]:
    try:
        if not LEDGER_FILE.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in LEDGER_FILE.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    out.append(data)
            except Exception:
                continue
        return out
    except Exception:
        return []


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [r for r in records if r.get("status") == "called"]
    avoided = [r for r in records if r.get("status") == "avoided"]
    failed = [r for r in records if r.get("status") == "failed"]
    by_agent = Counter(str(r.get("agent") or "unknown") for r in calls)
    premium_calls = [r for r in calls if r.get("selected_model_chain_kind") == "premium" or str(r.get("model") or "") == "gemini-3.5-flash"]
    standard_calls = [r for r in calls if r.get("selected_model_chain_kind") == "standard" or str(r.get("model") or "") != "gemini-3.5-flash"]
    return {
        "gemini_model_routing_v95_4": True,
        "gemini_calls_total": len(calls),
        "gemini_calls_by_agent": dict(sorted(by_agent.items())),
        "gemini_calls_avoided_total": len(avoided),
        "gemini_calls_avoided_by_andrea": sum(1 for r in avoided if str(r.get("agent") or "").lower() == "andrea"),
        "gemini_calls_failed": len(failed),
        "premium_model_calls": len(premium_calls),
        "standard_model_calls": len(standard_calls),
        "purpose_gate_avoided_calls": sum(1 for r in avoided if r.get("reason") in {"purpose_gate_not_met", "high_ambiguity_gate_not_met"}),
        "menzo_second_pass_35_avoided": sum(1 for r in avoided if r.get("agent") == "Menzo" and r.get("phase") == "duplicate_arbitration_second_pass"),
        "gemini_calls_avoided_by_duplicate_arbitration_cache": sum(1 for r in avoided if r.get("agent") == "Menzo" and r.get("reason") == "duplicate_arbitration_cache_hit"),
        "menzo_model_cooldown_avoided": sum(1 for r in avoided if r.get("reason") == "model_cooldown_after_failure"),
        "bob_premium_articles": sum(1 for r in calls if r.get("agent") == "Bob" and r.get("selected_model_chain_kind") == "premium"),
        "bob_standard_articles": sum(1 for r in calls if r.get("agent") == "Bob" and r.get("selected_model_chain_kind") == "standard"),
    }


def latest_for_run(run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or current_run_id()
    records = iter_records()
    if run_id:
        records = [r for r in records if r.get("run_id") == run_id]
    return {"generated_at": utc_now(), "run_id": run_id, "summary": summarize(records), "records": records}


def write_latest_snapshot(run_id: str | None = None) -> dict[str, Any]:
    data = latest_for_run(run_id)
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = LATEST_FILE.with_suffix(LATEST_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(LATEST_FILE)
    except Exception:
        pass
    return data


def record_andrea_avoided(candidate: dict[str, Any] | None = None, *, phase: str = "pre_bob_content_sufficiency_guard", reason: str | None = None) -> None:
    candidate = candidate or {}
    record_gemini_event(
        agent="Andrea",
        phase=phase,
        status="avoided",
        url=candidate.get("url") or candidate.get("source_url"),
        title=candidate.get("title") or candidate.get("source_title"),
        candidate_id=candidate.get("candidate_id") or candidate.get("id") or candidate.get("semantic_id"),
        source_id=candidate.get("source_id") or candidate.get("source"),
        reason=reason or candidate.get("andrea_reason") or candidate.get("reason") or "blocked_before_bob",
        blocked_by_andrea=True,
        saved_gemini_call=True,
        would_have_agent="Bob",
    )
