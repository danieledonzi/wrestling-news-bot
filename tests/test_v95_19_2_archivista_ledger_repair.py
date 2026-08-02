from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.repair_archivista_ledger_v95_19_2 import deduplicate_legacy_pairs


def row(ts: str, published: int, *, status: str = "ok"):
    return {"generated_at": ts, "published": published, "overall_status": status}


def test_repair_collapses_only_nearby_exact_payload_pairs() -> None:
    rows = [
        row("2026-07-30T10:00:00+00:00", 1),
        row("2026-07-30T10:00:00.100000+00:00", 1),
        row("2026-07-30T10:30:00+00:00", 0),
        row("2026-07-30T10:30:00.100000+00:00", 2),
        row("2026-07-30T11:00:00+00:00", 1),
        row("2026-07-30T11:00:10+00:00", 1),
    ]

    repaired, removed = deduplicate_legacy_pairs(rows)

    assert removed == 1
    assert len(repaired) == 5
    assert repaired[0]["generated_at"] == "2026-07-30T10:00:00.100000+00:00"
