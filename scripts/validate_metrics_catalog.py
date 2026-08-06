#!/usr/bin/env python3
"""Validate the A1 machine-readable canonical metrics contract."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, List

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "config" / "metrics_catalog_v1.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "runtime" / "OWTV_METRICS_CATALOG.md"
STATUSES = {"active", "alias", "ambiguous", "deprecated", "removed_candidate", "diagnostic_only", "planned"}
AVAILABILITIES = {"available", "partially_available", "unavailable", "source_dependent"}
REQUIRED_FIELDS = {
    "canonical_name", "description", "domain", "entity_counted", "unit", "cardinality",
    "authority_level", "source_primary", "source_secondary", "producer_paths", "consumer_paths",
    "formula", "aggregation", "identity_key", "time_window", "zero_semantics",
    "missing_semantics", "availability", "schema_version", "policy_version", "introduced_in",
    "status", "legacy_aliases", "replacement", "used_by_reports", "notes",
}
LIST_FIELDS = {"source_secondary", "producer_paths", "consumer_paths", "legacy_aliases", "used_by_reports"}
ACTIVE_TEXT_FIELDS = {"source_primary", "formula", "zero_semantics", "missing_semantics", "time_window"}


def _markdown_table(markdown: str, heading: str) -> List[List[str]]:
    """Return cells from the first deterministic pipe table under *heading*."""
    start = markdown.find(heading)
    if start < 0:
        return []
    end = markdown.find("\n## ", start + len(heading))
    section = markdown[start:end if end >= 0 else len(markdown)]
    rows: List[List[str]] = []
    for line in section.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0] not in {"Canonical name", "Name", "Observed alias"}:
            rows.append(cells)
    return rows


def _code_cell(cell: str) -> str:
    match = re.fullmatch(r"`([^`]+)`", cell)
    return match.group(1) if match else ""


def validate(catalog_path: Path = DEFAULT_CATALOG, markdown_path: Path = DEFAULT_MARKDOWN) -> List[str]:
    errors: List[str] = []
    try:
        payload: Any = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load catalog {catalog_path}: {exc}"]
    if not isinstance(payload, dict):
        return ["catalog root must be an object"]
    if payload.get("schema_version") != "owtv_metrics_catalog_v1":
        errors.append("schema_version must equal owtv_metrics_catalog_v1")
    if payload.get("policy_version") != "v95.22_a1":
        errors.append("policy_version must equal v95.22_a1")
    metrics = payload.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        return errors + ["metrics must be a non-empty array"]
    names = set()
    aliases = {}
    active_names = []
    planned_names = []
    deprecated_replacements = {}
    for index, metric in enumerate(metrics):
        label = f"metrics[{index}]"
        if not isinstance(metric, dict):
            errors.append(f"{label} must be an object")
            continue
        name = metric.get("canonical_name")
        if not isinstance(name, str) or not name or "." not in name:
            errors.append(f"{label}.canonical_name must be a non-empty domain.metric_name string")
            name = label
        elif name in names:
            errors.append(f"duplicate canonical_name: {name}")
        names.add(name)
        missing = sorted(REQUIRED_FIELDS - metric.keys())
        if missing:
            errors.append(f"{name}: missing required fields: {', '.join(missing)}")
        for field in LIST_FIELDS:
            if field in metric and not isinstance(metric[field], list):
                errors.append(f"{name}: {field} must be an array")
        status = metric.get("status")
        availability = metric.get("availability")
        if status not in STATUSES:
            errors.append(f"{name}: invalid status {status!r}")
        if availability not in AVAILABILITIES:
            errors.append(f"{name}: invalid availability {availability!r}")
        if isinstance(name, str) and isinstance(metric.get("domain"), str) and name.split(".", 1)[0] != metric["domain"]:
            errors.append(f"{name}: domain does not match canonical_name")
        if status in {"alias", "deprecated"} and not metric.get("replacement") and not str(metric.get("notes") or "").strip():
            errors.append(f"{name}: {status} metric requires replacement or an explicit notes rationale")
        if status == "active":
            active_names.append(name)
            for field in ACTIVE_TEXT_FIELDS:
                value = metric.get(field)
                if not isinstance(value, str) or not value.strip() or value == "not_available":
                    errors.append(f"{name}: active metric requires a real {field}")
            if metric.get("availability") != "available":
                errors.append(f"{name}: active metric must be available")
            if metric.get("zero_semantics") == metric.get("missing_semantics"):
                errors.append(f"{name}: zero_semantics must differ from missing_semantics")
        elif status == "planned":
            planned_names.append(name)
            if availability != "unavailable":
                errors.append(f"{name}: planned metric must be unavailable")
        elif status == "deprecated":
            deprecated_replacements[name] = metric.get("replacement")
        for alias in metric.get("legacy_aliases", []) if isinstance(metric.get("legacy_aliases"), list) else []:
            if not isinstance(alias, str) or not alias.strip():
                errors.append(f"{name}: legacy aliases must be non-empty strings")
            elif alias in aliases and aliases[alias] != name:
                errors.append(f"legacy alias {alias!r} points to both {aliases[alias]} and {name}")
            else:
                aliases[alias] = name
    for alias, target in aliases.items():
        if alias in names:
            errors.append(f"legacy alias {alias!r} for {target} collides with a canonical_name")
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot load Markdown catalog {markdown_path}: {exc}")
    else:
        active_rows = _markdown_table(markdown, "## 4. Active canonical metrics")
        planned_rows = _markdown_table(markdown, "## 6. Planned metrics")
        alias_rows = _markdown_table(markdown, "## 7. Legacy aliases")
        deprecated_rows = _markdown_table(markdown, "## 9. Deprecated metrics")
        markdown_active = {_code_cell(row[0]) for row in active_rows}
        markdown_planned = {_code_cell(row[0]) for row in planned_rows}
        if markdown_active != set(active_names):
            errors.append("Markdown active table does not match JSON active metrics")
        if markdown_planned != set(planned_names):
            errors.append("Markdown planned table does not match JSON planned metrics")
        markdown_deprecated = {
            _code_cell(row[0]): _code_cell(row[1])
            for row in deprecated_rows if len(row) >= 2
        }
        if markdown_deprecated != deprecated_replacements:
            errors.append("Markdown deprecated table/replacements do not match JSON")
        markdown_aliases = {}
        for row in alias_rows:
            if len(row) < 2:
                errors.append("Markdown legacy alias row must have a destination")
                continue
            alias, destination = _code_cell(row[0]), _code_cell(row[1])
            if alias in markdown_aliases and markdown_aliases[alias] != destination:
                errors.append(
                    f"Markdown legacy alias {alias!r} points to both "
                    f"{markdown_aliases[alias]} and {destination}"
                )
            markdown_aliases[alias] = destination
        if markdown_aliases != aliases:
            errors.append("Markdown legacy aliases do not match JSON legacy_aliases")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", nargs="?", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    errors = validate(args.catalog, args.markdown)
    if errors:
        print(f"metrics catalog invalid ({len(errors)} error(s)):", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    payload = json.loads(args.catalog.read_text(encoding="utf-8"))
    print(f"metrics catalog valid: {len(payload['metrics'])} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
