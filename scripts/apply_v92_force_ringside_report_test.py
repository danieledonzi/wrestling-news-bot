from __future__ import annotations

import json
import os
from pathlib import Path

ACTIVE = os.getenv("V92_FORCE_RINGSIDE_REPORT_TEST", "1").lower() in {"1", "true", "yes", "on"}
CONFIG = Path("config/reports_v92.json")
REPORT_ID = os.getenv("V92_FORCE_REPORT_ID", "wwe_raw")

if not ACTIVE:
    print("[V92 RINGSIDE TEST] Non attivo")
    raise SystemExit(0)

if not CONFIG.exists():
    raise SystemExit(f"[V92 RINGSIDE TEST] Config mancante: {CONFIG}")

data = json.loads(CONFIG.read_text(encoding="utf-8"))
changed = False
for report in data.get("reports", []):
    if report.get("id") != REPORT_ID:
        continue
    report["preferred_source"] = "ringsidenews"
    report["fallback_source"] = "ringsidenews"
    report["wait_for_preferred_until"] = "00:00"
    report["force_source_test"] = "ringsidenews"
    changed = True
    print(f"[V92 RINGSIDE TEST] Forzo {REPORT_ID}: preferred=fallback=ringsidenews")

if not changed:
    raise SystemExit(f"[V92 RINGSIDE TEST] Report non trovato: {REPORT_ID}")

CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
