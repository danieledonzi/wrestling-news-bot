from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ACTIVE = os.getenv("V92_FORCE_RINGSIDE_REPORT_TEST", "1").lower() in {"1", "true", "yes", "on"}
CONFIG = Path("config/reports_v92.json")
REPORT_ID = os.getenv("V92_FORCE_REPORT_ID", "wwe_raw")
ROME_TZ = ZoneInfo("Europe/Rome")
FORCE_DAY = os.getenv("V92_FORCE_REPORT_EXPECTED_DAY", datetime.now(ROME_TZ).strftime("%A"))
FORCE_OFFSET = int(os.getenv("V92_FORCE_REPORT_OFFSET_DAYS", "2"))

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
    report["expected_day_after"] = FORCE_DAY
    report["show_date_offset_days"] = FORCE_OFFSET
    report["force_source_test"] = "ringsidenews"
    changed = True
    print(
        f"[V92 RINGSIDE TEST] Forzo {REPORT_ID}: preferred=fallback=ringsidenews "
        f"expected_day_after={FORCE_DAY} offset_days={FORCE_OFFSET}"
    )

if not changed:
    raise SystemExit(f"[V92 RINGSIDE TEST] Report non trovato: {REPORT_ID}")

CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
