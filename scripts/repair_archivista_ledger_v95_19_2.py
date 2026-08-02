#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_LEDGER = Path("state/newsroom/archivista_ledger.json")
MAX_DUPLICATE_GAP_SECONDS = 5.0
IGNORED_KEYS = {"generated_at", "started_at", "run_id"}


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def payload_without_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in IGNORED_KEYS}


def deduplicate_legacy_pairs(rows: list[Any]) -> tuple[list[Any], int]:
    repaired: list[Any] = []
    removed = 0

    for row in rows:
        if not isinstance(row, dict) or not repaired or not isinstance(repaired[-1], dict):
            repaired.append(row)
            continue

        previous = repaired[-1]
        previous_dt = parse_dt(previous.get("generated_at") or previous.get("started_at"))
        current_dt = parse_dt(row.get("generated_at") or row.get("started_at"))
        same_payload = payload_without_identity(previous) == payload_without_identity(row)
        gap = (current_dt - previous_dt).total_seconds() if previous_dt and current_dt else None

        if same_payload and gap is not None and 0 <= gap <= MAX_DUPLICATE_GAP_SECONDS:
            repaired[-1] = row
            removed += 1
        else:
            repaired.append(row)

    return repaired, removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair exact legacy Archivista duplicate pairs.")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.ledger.exists():
        print(f"ledger_missing={args.ledger}")
        return 1

    rows = json.loads(args.ledger.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        print("ledger_invalid_type")
        return 1

    repaired, removed = deduplicate_legacy_pairs(rows)
    print(f"ledger={args.ledger}")
    print(f"records_before={len(rows)}")
    print(f"exact_duplicate_pairs_removed={removed}")
    print(f"records_after={len(repaired)}")

    if not args.apply:
        print("mode=dry_run")
        return 0

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = args.ledger.with_name(f"{args.ledger.name}.pre_v95_19_2_{stamp}")
    shutil.copy2(args.ledger, backup)
    tmp = args.ledger.with_suffix(args.ledger.suffix + ".tmp")
    tmp.write_text(json.dumps(repaired, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(args.ledger)
    print(f"backup={backup}")
    print("mode=applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
