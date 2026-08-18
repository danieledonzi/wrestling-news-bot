"""Read-only P1.2 artifact-index resolver keyed exclusively by ``content_id``."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agents.canonical_artifact_index import validate_manifest_entry

INDEX_PATH = "state/newsroom/canonical_artifact_index.jsonl"
REPORT_SCOPE_REASON = "p1_2_report_material_retention_out_of_scope"


def _material_text(path: Path, row: dict[str, Any]) -> tuple[str | None, str | None]:
    try:
        payload = path.read_bytes()
    except OSError:
        return None, "indexed_path_unreadable"
    if row.get("sha256") and hashlib.sha256(payload).hexdigest() != row["sha256"]:
        return None, "indexed_content_sha256_mismatch"
    if row.get("size_bytes") is not None and len(payload) != row["size_bytes"]:
        return None, "indexed_content_size_mismatch"
    try:
        raw = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None, "indexed_content_not_utf8"
    if row.get("format") == "html":
        return raw, None
    if row.get("format") != "json":
        return None, "indexed_format_not_supported"
    try:
        value = json.loads(raw)
    except ValueError:
        return None, "indexed_json_invalid"
    roles = set(row.get("semantic_roles") or [])
    schema = (row.get("artifact_schema_version") or {}).get("version")
    if "source_material" in roles:
        text = value.get("cleaned_full_text") if isinstance(value, dict) else None
        if not isinstance(text, str):
            return None, "source_material_representation_invalid"
        return text, None
    if "final_published_material" in roles and schema == "owtv_p1_2_published_text_v1":
        text = value.get("text") if isinstance(value, dict) else None
        return (text, None) if isinstance(text, str) else (None, "final_material_representation_invalid")
    if "quality_review" in roles:
        return json.dumps(value, ensure_ascii=False, sort_keys=True), None
    return None, "indexed_json_role_representation_unsupported"


def read_artifact_index(root: Path, index_path: Path | None = None) -> dict[str, Any]:
    """Return validated rows grouped by content identity; malformed rows stay diagnostic."""
    path = index_path or root / INDEX_PATH
    if not path.exists():
        return {"available": False, "rows_by_content_id": {}, "diagnostic_mismatches": [],
                "reason": "canonical_artifact_index_unavailable", "source": INDEX_PATH}
    grouped: dict[str, list[dict[str, Any]]] = {}
    mismatches: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            mismatches.append(f"invalid_json:{number}")
            continue
        errors = validate_manifest_entry(row)
        cid = row.get("content_id") if isinstance(row, dict) else None
        if errors or not cid:
            mismatches.append(f"invalid_manifest:{number}:{'|'.join(errors) if errors else 'missing_content_id'}")
            continue
        grouped.setdefault(cid, []).append(row)
    return {"available": True, "rows_by_content_id": grouped,
            "diagnostic_mismatches": mismatches, "reason": None, "source": INDEX_PATH}


def resolve_material_chain(root: Path, content_id: str, *, content_kind: str = "news",
                           index: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve declared roles and authority claims without title/slug matching."""
    if content_kind == "report":
        return {"content_id": content_id, "available": False, "reason": REPORT_SCOPE_REASON,
                "roles": {}, "diagnostic_mismatches": []}
    index = index or read_artifact_index(root)
    if not index.get("available"):
        return {"content_id": content_id, "available": False, "reason": index.get("reason"),
                "roles": {}, "diagnostic_mismatches": index.get("diagnostic_mismatches", [])}
    rows = index["rows_by_content_id"].get(content_id, [])
    instances: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        correlation = str(row.get("correlation_id") or "")
        if correlation:
            instances.setdefault(correlation, []).append(row)
    def instance_rank(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, str, str]:
        correlation, values = item
        has_final = any("final_published_material" in (row.get("semantic_roles") or []) for row in values)
        newest = max((str(row.get("manifested_at_utc") or "") for row in values), default="")
        return (int(has_final), newest, correlation)
    selected_correlation, selected_rows = max(instances.items(), key=instance_rank) if instances else ("", [])
    wanted = ("source_material", "translated_candidate", "quality_review", "final_published_material")
    roles: dict[str, dict[str, Any]] = {}
    mismatches: list[str] = []
    for role in wanted:
        candidates = [row for row in selected_rows if role in (row.get("semantic_roles") or [])]
        if not candidates:
            roles[role] = {"available": False, "reason": f"canonical_role_not_indexed:{role}"}
            continue
        row = sorted(candidates, key=lambda x: (x.get("manifested_at_utc", ""), x.get("artifact_id", "")))[-1]
        text, reason = _material_text(root / row["path"], row)
        claims = [claim for claim in row.get("authority_claims", []) if isinstance(claim, dict)]
        roles[role] = {"available": text is not None, "reason": reason, "text": text,
                       "path": row["path"], "format": row["format"],
                       "semantic_roles": row["semantic_roles"], "authority_claims": claims,
                       "artifact_id": row["artifact_id"]}
        if reason:
            mismatches.append(f"{role}:{reason}")
    return {"content_id": content_id, "correlation_id": selected_correlation,
            "run_id": selected_rows[0].get("run_id") if selected_rows else None,
            "chain_instances": sorted(instances),
            "available": any(v["available"] for v in roles.values()),
            "reason": None if rows else "content_id_not_indexed", "roles": roles,
            "diagnostic_mismatches": mismatches}
