"""Content-addressed persistence for Menzo's batch duplicate arbitration.

This module deliberately knows nothing about duplicate editorial policy.  It
stores only already-validated outcomes, keyed by the effective prompt material
and the versioned arbitration contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CACHE_FILE = ROOT / "state" / "newsroom" / "menzo_duplicate_arbitration_cache_v2.json"
CACHE_SCHEMA_VERSION = "2"
MENZO_DUPLICATE_ARBITRATION_CONTRACT_VERSION = "v95.20-grounded-temporal-audit-4"
PROMPT_BUILDER_VERSION = "v95.20-temporal-basis-comparisons-4"
VALIDATOR_VERSION = "v95.20-grounded-temporal-validator-4"
MODEL_NAME = "gemini-3.1-flash-lite"
FAILURE_COOLDOWN_HOURS = float(os.getenv("MENZO_DUPLICATE_FAILURE_COOLDOWN_HOURS", "2"))
REQUIRED_DECISION_FIELDS = (
    "menzo_duplicate_checked", "menzo_duplicate_scope", "menzo_duplicate_decision",
    "menzo_authorized", "menzo_compared_with_url", "menzo_duplicate_reason",
    "menzo_new_fact", "menzo_winner_url", "menzo_duplicate_audit", "menzo_duplicate_comparisons",
)
REQUIRED_DISPOSITION_FIELDS = ("decision", "priority", "article_type", "reason")


def _normal(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {str(k): _normal(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple, set)):
        values = [_normal(v) for v in value]
        return sorted(values, key=lambda v: canonical_json(v))
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_normal(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def contract_fingerprint(contract_version: str | None = None, *, threshold: float | None = None) -> str:
    from agents.menzo_duplicate_scorer import SCORER_VERSION, effective_threshold
    return content_hash({
        "schema": CACHE_SCHEMA_VERSION,
        "contract": contract_version or MENZO_DUPLICATE_ARBITRATION_CONTRACT_VERSION,
        "model": MODEL_NAME,
        "prompt": PROMPT_BUILDER_VERSION,
        "validator": VALIDATOR_VERSION,
        "scorer": SCORER_VERSION,
        "threshold": effective_threshold() if threshold is None else float(threshold),
    })


def candidate_material_hash(compact_record: dict[str, Any]) -> str:
    # IDs are batch-local aliases. Scores and publication clocks do not inform
    # semantic duplicate policy and are intentionally absent from v95.17 keys.
    return content_hash({k: v for k, v in compact_record.items() if k not in {"id", "score", "published_at"}})


def actionable_snapshot_hash(pairs: list[tuple[str, str]]) -> str:
    return content_hash(sorted(f"{cid}\0{material}" for cid, material in pairs))


def comparison_hash(records: list[tuple[str, str]]) -> str:
    return content_hash(sorted(f"{identity}\0{material}" for identity, material in records))


def request_key(scope: str, candidates: list[tuple[str, str]], comparisons: str = "", *, contract_version: str | None = None) -> str:
    return content_hash({"scope": scope, "contract": contract_fingerprint(contract_version), "candidates": sorted(candidates), "comparisons": comparisons})


def empty_cache(status: str = "missing") -> dict[str, Any]:
    return {"schema_version": CACHE_SCHEMA_VERSION, "contract_fingerprint": contract_fingerprint(), "load_status": status,
            "entries": {}, "failures": {}, "last_snapshot": {}}


def load_cache(path: Path | None = None, warn: Callable[[str], None] = print) -> dict[str, Any]:
    target = Path(path or CACHE_FILE)
    if not target.exists():
        return empty_cache()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != CACHE_SCHEMA_VERSION:
            return empty_cache("obsolete_schema")
        for key in ("entries", "failures", "last_snapshot"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        data["load_status"] = "loaded"
        return data
    except Exception as exc:
        warn(f"WARNING: Menzo v2 duplicate cache ignored: {exc}")
        return empty_cache("malformed")


def atomic_write(cache: dict[str, Any], path: Path | None = None) -> None:
    target = Path(path or CACHE_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(cache); payload.pop("load_status", None)
    fd, name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush(); os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def valid_decisions(value: Any) -> bool:
    if not isinstance(value, dict): return False
    for decision in value.values():
        if not isinstance(decision, dict) or any(field not in decision for field in REQUIRED_DECISION_FIELDS):
            return False
        disposition = decision.get("disposition")
        if not isinstance(disposition, dict) or any(field not in disposition for field in REQUIRED_DISPOSITION_FIELDS):
            return False
    return True


def lookup(cache: dict[str, Any], key: str, *, candidates: list[tuple[str, str]] | None = None, comparisons: str | None = None) -> dict[str, Any] | None:
    entry = cache.get("entries", {}).get(key)
    if not isinstance(entry, dict) or entry.get("contract_fingerprint") != contract_fingerprint(): return None
    expected = sorted(candidates or [])
    stored = entry.get("candidate_material_hashes")
    if entry.get("evaluated_candidate_ids") != [x[0] for x in expected] or stored != {x[0]: x[1] for x in expected}: return None
    if comparisons is not None and entry.get("comparison_hash") != comparisons: return None
    if entry.get("outcome") not in {"validated_decisions", "validated_no_matches"}: return None
    decisions = entry.get("decisions")
    if not valid_decisions(decisions): return None
    if not decisions and entry.get("outcome") != "validated_no_matches": return None
    if decisions and entry.get("outcome") != "validated_decisions": return None
    outcomes=entry.get("candidate_outcomes")
    if not isinstance(outcomes,dict) or set(outcomes) != set(entry["evaluated_candidate_ids"]): return None
    if any(value not in {"validated_decision","validated_no_match"} for value in outcomes.values()): return None
    if {cid for cid,value in outcomes.items() if value=="validated_decision"} != set(decisions): return None
    if not isinstance(entry.get("actual_gemini_request_count"), int) or entry["actual_gemini_request_count"] < 0: return None
    return entry


def store(cache: dict[str, Any], key: str, scope: str, decisions: dict[str, dict[str, Any]], *, candidates: list[tuple[str, str]] | None = None, comparisons: str = "", actual_request_count: int = 0) -> bool:
    if not valid_decisions(decisions): return False
    pairs = sorted(candidates or [])
    if not pairs or len({x[0] for x in pairs}) != len(pairs): return False
    cache.setdefault("entries", {})[key] = {"scope": scope, "contract_fingerprint": contract_fingerprint(),
        "stored_at": datetime.now(timezone.utc).isoformat(), "outcome": "validated_decisions" if decisions else "validated_no_matches",
        "evaluated_candidate_ids": [x[0] for x in pairs], "candidate_material_hashes": {x[0]: x[1] for x in pairs},
        "comparison_hash": comparisons, "decisions": decisions, "actual_gemini_request_count": int(actual_request_count),
        "candidate_outcomes": {cid: ("validated_decision" if cid in decisions else "validated_no_match") for cid,_ in pairs},
        "candidates": pairs, "comparisons": comparisons}
    cache.setdefault("failures", {}).pop(key, None)
    return True


def record_failure(cache: dict[str, Any], key: str, failure_type: str) -> None:
    now = datetime.now(timezone.utc); old = cache.setdefault("failures", {}).get(key, {})
    cache["failures"][key] = {"failure_type": failure_type, "failed_at": now.isoformat(),
        "retry_after": (now + timedelta(hours=FAILURE_COOLDOWN_HOURS)).isoformat(), "attempt_count": int(old.get("attempt_count", 0)) + 1}


def failure_in_cooldown(cache: dict[str, Any], key: str) -> bool:
    try:
        return datetime.fromisoformat(cache.get("failures", {}).get(key, {}).get("retry_after", "")) > datetime.now(timezone.utc)
    except Exception:
        return False
