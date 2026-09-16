"""Persistent reuse of fully validated Active E04/E04C pair results."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CACHE_FILE = ROOT / "state/newsroom/menzo_active_duplicate_pair_cache_v1.json"
SCHEMA_VERSION = "owtv_active_duplicate_pair_cache_v1"
CONTRACT_VERSION = "ed-2.1.2-active-final-pair-result-v1"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def contract_fingerprint(*, policy_version: str, model: str, policy_path: Path,
                         gate_schema_path: Path, confirmation_schema_path: Path,
                         event_registry_path: Path) -> str:
    from agents.menzo_duplicate_scorer import SCORER_VERSION, effective_threshold
    try:
        event_registry = {"status": "available", "sha256": hashlib.sha256(
            event_registry_path.read_bytes()).hexdigest()}
    except (OSError, ValueError):
        # Cache lookup must fail open.  This stable marker cannot match an entry
        # created while the registry was readable; E04V remains authoritative.
        event_registry = {"status": "unavailable"}
    material = {
        "cache_contract_version": CONTRACT_VERSION,
        "cache_schema_version": SCHEMA_VERSION,
        "active_policy_version": policy_version,
        "active_policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "model": model,
        "duplicate_gate_schema_sha256": hashlib.sha256(gate_schema_path.read_bytes()).hexdigest(),
        "duplicate_confirmation_schema_sha256": hashlib.sha256(
            confirmation_schema_path.read_bytes()).hexdigest(),
        "event_registry": event_registry,
        "duplicate_scorer_version": SCORER_VERSION,
        "duplicate_effective_threshold": effective_threshold(),
    }
    return _hash(material)


def pair_material(relation: Mapping[str, Any], endpoints: Mapping[str, Mapping[str, Any]],
                  contract: str) -> dict[str, Any]:
    """Use exact provider rows, excluding only request-local aliases."""
    endpoint_material = {
        side: {key: copy.deepcopy(value) for key, value in endpoints[side].items() if key != "ref"}
        for side in ("left", "right")
    }
    scorer = {key: copy.deepcopy(relation.get(key))
              for key in ("scorer_version", "score", "threshold", "components")}
    identity = {"pair_id": relation.get("pair_id"), "scope": relation.get("scope")}
    return {"identity": identity, "endpoint_material_hash": _hash(endpoint_material),
            "relation_contract_hash": _hash(scorer), "contract_fingerprint": contract}


def empty(status: str = "missing") -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "load_status": status, "entries": {}}


def load(path: Path | None = None) -> dict[str, Any]:
    target = Path(path or CACHE_FILE)
    if not target.exists():
        return empty()
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or
                not isinstance(value.get("entries"), dict)):
            return empty("obsolete_schema")
        value["load_status"] = "loaded"
        return value
    except Exception:
        return empty("malformed")


def lookup(cache: Mapping[str, Any], material: Mapping[str, Any]) -> dict[str, Any] | None:
    key = str(material["identity"]["pair_id"])
    entry = cache.get("entries", {}).get(key)
    if not isinstance(entry, Mapping):
        return None
    if any(entry.get(field) != material.get(field) for field in
           ("identity", "endpoint_material_hash", "relation_contract_hash", "contract_fingerprint")):
        return None
    relation = entry.get("final_relation")
    if not isinstance(relation, Mapping) or relation.get("decision") not in {
            "NO_MATCH", "MATERIAL_UPDATE", "DUPLICATE"}:
        return None
    if relation.get("decision") == "DUPLICATE" and (
            relation.get("duplicate_confirmation", {}).get("decision") != "CONFIRM_DUPLICATE"):
        return None
    if relation.get("primary_decision") == "DUPLICATE" and relation.get("decision") == "NO_MATCH" and (
            relation.get("duplicate_confirmation", {}).get("decision") != "REJECT_DUPLICATE"):
        return None
    result = copy.deepcopy(dict(relation))
    result["duplicate_pair_cache"] = {
        "cache_hit": True, "contract_version": CONTRACT_VERSION,
        "contract_fingerprint": material["contract_fingerprint"],
        "stored_at": entry.get("stored_at"),
        "original_provenance": copy.deepcopy(entry.get("original_provenance", {})),
    }
    return result


def store(cache: dict[str, Any], rows: list[tuple[Mapping[str, Any], Mapping[str, Any]]],
          path: Path | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    entries = cache.setdefault("entries", {})
    for material, relation in rows:
        key = str(material["identity"]["pair_id"])
        entries[key] = {**copy.deepcopy(dict(material)), "stored_at": now,
                        "original_provenance": copy.deepcopy(relation.get("validated_provenance", {})),
                        "final_relation": copy.deepcopy(dict(relation))}
    payload = {"schema_version": SCHEMA_VERSION, "entries": entries}
    target = Path(path or CACHE_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_json(payload)); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return len(rows)
