from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG = Path("config/reports_v92.json")
REPORT_ID = os.getenv("V92_FORCE_REPORT_ID", "wwe_raw")
PUBLISH_AFTER = os.getenv("V92_FORCE_REPORT_PUBLISH_AFTER", "00:00")

if not CONFIG.exists():
    print(f"[V92 TIME TEST] Config mancante: {CONFIG}")
    raise SystemExit(0)

data = json.loads(CONFIG.read_text(encoding="utf-8"))
changed = False
for report in data.get("reports", []):
    if report.get("id") == REPORT_ID:
        report["publish_after"] = PUBLISH_AFTER
        changed = True
        print(f"[V92 TIME TEST] Forzo publish_after={PUBLISH_AFTER} per {REPORT_ID}")

if changed:
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
else:
    print(f"[V92 TIME TEST] Report non trovato: {REPORT_ID}")
