#!/usr/bin/env python3
"""Validate P1.2 manifest structure, identity, and immutable bytes (stdlib only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.canonical_artifact_index import artifact_id, validate_manifest_entry
from agents.canonical_event_ledger import correlation_id

DEFAULT_PATH = Path("state/newsroom/canonical_artifact_index.jsonl")


def validate_index(path: str | Path, repository_root: str | Path = ROOT) -> tuple[dict[str, Any], int]:
    index = Path(path)
    root = Path(repository_root)
    summary: dict[str, Any] = {
        "rows": 0, "valid_rows": 0, "invalid_rows": 0, "malformed_json_rows": 0,
        "distinct_artifact_ids": 0, "distinct_run_ids": 0, "distinct_content_ids": 0,
        "by_semantic_role": {}, "by_producer_agent": {}, "by_producer_stage": {}, "by_format": {},
        "integrity_errors": 0, "identity_errors": 0, "missing_artifact_files": 0,
        "duplicate_artifact_ids": 0,
    }
    ids: set[str] = set()
    runs: set[str] = set()
    contents: set[str] = set()
    counts = {key: Counter() for key in ("semantic_role", "producer_agent", "producer_stage", "format")}
    # Coverage is per P1.1 run/content correlation, never a cross-run content union.
    coverage: dict[str, set[str]] = defaultdict(set)
    try:
        lines = index.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        summary["invalid_rows"] = 1
        return summary, 1
    for line in lines:
        summary["rows"] += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            summary["malformed_json_rows"] += 1
            summary["invalid_rows"] += 1
            continue
        errors = validate_manifest_entry(row)
        if not isinstance(row, dict):
            summary["invalid_rows"] += 1
            continue
        aid = row.get("artifact_id")
        if aid in ids:
            summary["duplicate_artifact_ids"] += 1
            errors.append("duplicate artifact_id")
        if isinstance(aid, str):
            ids.add(aid)
        run_id, cid, corr = (row.get(key) for key in ("run_id", "content_id", "correlation_id"))
        if not all(isinstance(value, str) and value for value in (run_id, cid, corr)):
            summary["identity_errors"] += 1
            errors.append("content-linked artifact requires run_id/content_id/correlation_id")
        elif corr != correlation_id(run_id, cid):
            summary["identity_errors"] += 1
            errors.append("wrong correlation_id")
        else:
            runs.add(run_id)
            contents.add(cid)
        roles = row.get("semantic_roles", []) if isinstance(row.get("semantic_roles"), list) else []
        coverage_markers: set[str] = set()
        for role in roles:
            counts["semantic_role"][role] += 1
            coverage_markers.add(role)
        if "translated_candidate" in roles and row.get("producer_agent") == "Bob":
            coverage_markers.add("bob_candidate")
        if "quality_review" in roles and "translated_candidate" in roles:
            coverage_markers.add("alfred_approved_body")
        elif "quality_review" in roles:
            coverage_markers.add("alfred_review")
        for field in ("producer_agent", "producer_stage", "format"):
            if isinstance(row.get(field), str):
                counts[field][row[field]] += 1
        if row.get("persistence_class") == "immutable_archive" and "sha256" in row and "size_bytes" in row:
            artifact_path = root / row.get("path", "")
            if not artifact_path.is_file():
                summary["missing_artifact_files"] += 1
                summary["integrity_errors"] += 1
                errors.append("missing artifact file")
            else:
                try:
                    data = artifact_path.read_bytes()
                    if len(data) != row["size_bytes"]:
                        summary["integrity_errors"] += 1
                        errors.append("size mismatch")
                    if hashlib.sha256(data).hexdigest() != row["sha256"]:
                        summary["integrity_errors"] += 1
                        errors.append("SHA mismatch")
                    if all(isinstance(row.get(key), str) for key in
                           ("run_id", "content_id", "producer_stage")) and isinstance(row.get("semantic_roles"), list):
                        expected_id = artifact_id(row["run_id"], row["content_id"], row["producer_stage"],
                                                  "+".join(row["semantic_roles"]), data)
                        if row.get("artifact_id") != expected_id:
                            summary["identity_errors"] += 1
                            errors.append("wrong deterministic artifact_id")
                except OSError:
                    summary["integrity_errors"] += 1
                    errors.append("artifact read error")
        if errors:
            summary["invalid_rows"] += 1
        else:
            summary["valid_rows"] += 1
            coverage[corr].update(coverage_markers)
    summary.update(distinct_artifact_ids=len(ids), distinct_run_ids=len(runs), distinct_content_ids=len(contents))
    for key, counter in counts.items():
        summary["by_" + key] = dict(sorted(counter.items()))
    has_source = {cid for cid, roles in coverage.items() if "source_material" in roles}
    has_bob = {cid for cid, roles in coverage.items() if "bob_candidate" in roles}
    has_review = {cid for cid, roles in coverage.items() if "alfred_review" in roles}
    has_body = {cid for cid, roles in coverage.items() if "alfred_approved_body" in roles}
    has_final = {cid for cid, roles in coverage.items() if "final_published_material" in roles}
    summary["material_chain_coverage"] = {
        "contents_with_source": len(has_source), "contents_with_bob_candidate": len(has_bob),
        "contents_with_alfred_review": len(has_review), "contents_with_alfred_approved_body": len(has_body),
        "contents_with_final_material": len(has_final), "contents_with_source_and_bob": len(has_source & has_bob),
        "contents_with_source_bob_alfred": len(has_source & has_bob & has_review),
        "contents_with_source_bob_alfred_final": len(has_source & has_bob & has_review & has_final),
    }
    return summary, int(bool(summary["invalid_rows"] or summary["integrity_errors"] or summary["identity_errors"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH))
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    summary, exit_code = validate_index(args.path, args.root)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
