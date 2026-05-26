from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

FORCE = os.getenv("V92_FORCE_REPORT_REPUBLISH", "0").lower() in {"1", "true", "yes", "on"}
STATE = Path("state/report_status.json")
REPORT_ID = os.getenv("V92_FORCE_REPORT_ID", "wwe_raw")
TZ = ZoneInfo("Europe/Rome")

if not FORCE:
    print("[V92 RESET] Force republish non attivo")
    raise SystemExit(0)

now = datetime.now(TZ).replace(tzinfo=None)
show_date = now.date() - timedelta(days=int(os.getenv("V92_FORCE_REPORT_OFFSET_DAYS", "1")))
key = f"{REPORT_ID}_{show_date.isoformat().replace('-', '_')}"

if not STATE.exists():
    print(f"[V92 RESET] Nessuno stato da resettare: {STATE}")
    raise SystemExit(0)

try:
    data = json.loads(STATE.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"[V92 RESET] Stato non leggibile: {exc}")
    raise SystemExit(0)

if key in data:
    old_status = data.get(key, {}).get("status")
    data.pop(key, None)
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[V92 RESET] Rimosso stato {key} old_status={old_status}")
else:
    print(f"[V92 RESET] Nessuno stato presente per {key}")
