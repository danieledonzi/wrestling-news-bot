#!/usr/bin/env python3
"""Validate an OWTV canonical JSONL ledger (Python 3.9 stdlib only)."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from agents.canonical_event_ledger import (DEFAULT_PATH, correlation_id,
                                           report_correlation_id, validate_event)


def validate_ledger(path: Path) -> tuple[int, dict[str, Any]]:
    summary: dict[str, Any] = {"rows": 0, "valid_rows": 0, "invalid_rows": 0,
                               "malformed_json_rows": 0, "first_timestamp": None,
                               "last_timestamp": None, "distinct_run_ids": 0,
                               "distinct_content_ids": 0, "distinct_correlation_ids": 0}
    events: Counter[str] = Counter()
    agents: Counter[str] = Counter()
    runs: set[str] = set(); contents: set[str] = set(); correlations: set[str] = set()
    run_content: dict[tuple[str, str], set[str]] = defaultdict(set)
    correlation_content: dict[str, set[str]] = defaultdict(set)
    identity_errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        summary["errors"] = [str(exc)]
        return 1, summary
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        summary["rows"] += 1
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            summary["malformed_json_rows"] += 1; summary["invalid_rows"] += 1
            continue
        problems = validate_event(row)
        if problems:
            summary["invalid_rows"] += 1
            identity_errors.append(f"row {number}: {'; '.join(problems)}")
            continue
        summary["valid_rows"] += 1
        timestamp = row["timestamp_utc"]
        summary["first_timestamp"] = min(filter(None, (summary["first_timestamp"], timestamp)), default=timestamp)
        summary["last_timestamp"] = max(filter(None, (summary["last_timestamp"], timestamp)), default=timestamp)
        runs.add(row["run_id"]); events[row["event_type"]] += 1; agents[row["agent"]] += 1
        cid, corr = row.get("content_id"), row.get("correlation_id")
        if cid: contents.add(cid)
        if corr: correlations.add(corr)
        if cid and corr:
            run_content[(row["run_id"], cid)].add(corr)
            correlation_content[corr].add(cid)
        if cid:
            expected = correlation_id(row["run_id"], cid)
            if not corr:
                identity_errors.append(f"row {number}: content_id requires correlation_id")
            elif corr != expected:
                identity_errors.append(f"row {number}: content correlation is not deterministic")
        elif row.get("report_key") and corr:
            expected = report_correlation_id(row["run_id"], row["report_key"])
            if corr != expected:
                identity_errors.append(f"row {number}: report-only correlation is not deterministic")
    for key, values in run_content.items():
        if len(values) > 1: identity_errors.append(f"run/content {key!r} maps to multiple correlations")
    for key, values in correlation_content.items():
        if len(values) > 1: identity_errors.append(f"correlation {key!r} maps to multiple content IDs")
    summary.update(distinct_run_ids=len(runs), distinct_content_ids=len(contents),
                   distinct_correlation_ids=len(correlations), event_type_counts=dict(sorted(events.items())),
                   agent_counts=dict(sorted(agents.items())), identity_errors=identity_errors)
    return (1 if summary["invalid_rows"] or identity_errors else 0), summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    code, result = validate_ledger(Path(args.path))
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
