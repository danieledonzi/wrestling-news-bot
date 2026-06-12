#!/usr/bin/env python3
"""OpenWrestlingTV v94.5 - apply Wikipedia schedule proposals to registry.

Default mode is dry-run. Use --write to update config/special_events.json locally.
The tool trusts Wikipedia upcoming schedule for WWE, NXT, AEW, TNA and ROH.
AAA stays report-only by default and is not auto-applied.
"""
from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_DIR / "config" / "special_events.json"
REPORT_DIR = REPO_DIR / "reports"
AUTO_PROMOTIONS = {"WWE", "AEW", "TNA", "ROH"}
SKIP_PROMOTIONS = {"AAA"}


def slugify(text: str) -> str:
    text = text.lower().replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "event"


def event_key(promotion: str, name: str, year: str) -> str:
    return f"{promotion.lower()}_{slugify(name)}_{year}"


def main_night_key(key: str) -> str:
    return f"{key}_main"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_latest_report(report_dir: Path) -> Path:
    files = sorted(report_dir.glob("special_events_wikipedia_schedule_layer_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit(f"Nessun report Wikipedia schedule trovato in {report_dir}")
    return files[0]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def score_event(ev: dict[str, Any], reg: dict[str, Any]) -> int:
    s = norm(ev.get("event_name", ""))
    r = norm(reg.get("event_name", ""))
    aliases = [norm(a) for a in reg.get("aliases", [])]
    score = 0
    if s and (s == r or s in aliases):
        score = 100
    elif s and (s in r or r in s or any(s in a or a in s for a in aliases)):
        score = 70
    if ev.get("promotion") == reg.get("promotion"):
        score += 20
    if ev.get("brand") in {reg.get("brand"), reg.get("category_hint")}:
        score += 10
    return score


def find_match(ev: dict[str, Any], registry: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    ranked = sorted(((score_event(ev, reg), reg) for reg in registry.get("events", [])), key=lambda x: x[0], reverse=True)
    if not ranked or ranked[0][0] < 60:
        return 0, None
    return ranked[0]


def night_aliases(promotion: str, name: str, label: str) -> list[str]:
    base = [f"{name} results", f"{promotion} {name} results"]
    if label and label != "Main show":
        base.extend([f"{name} {label}", f"{promotion} {name} {label}", f"{name} {label} results"])
    return sorted(set(base))


def build_nights(key: str, dates: list[str], promotion: str, name: str) -> list[dict[str, Any]]:
    dates = sorted(set(dates))
    if len(dates) <= 1:
        label = "Main show"
        return [{"night_key": main_night_key(key), "label": label, "date_local": dates[0], "report_publish_after_local": "06:30", "enabled": True, "aliases": night_aliases(promotion, name, label)}]
    nights = []
    for i, d in enumerate(dates, 1):
        label = f"Night {i}"
        nights.append({"night_key": f"{key}_night_{i}", "label": label, "date_local": d, "report_publish_after_local": "06:30", "enabled": True, "aliases": night_aliases(promotion, name, label)})
    return nights


def priority_for(promotion: str, name: str) -> str:
    low = name.lower()
    if promotion in {"AEW", "TNA"}:
        return "major"
    if any(x in low for x in ["summerslam", "money in the bank", "night of champions", "survivor series"]):
        return "major"
    return "medium"


def event_type_for(promotion: str, brand: str, name: str) -> str:
    if brand == "NXT":
        return "NXT Special/PLE"
    if promotion == "WWE" and "night" in name.lower() and "main event" in name.lower():
        return "Special"
    if promotion in {"AEW", "TNA", "ROH"}:
        return "PPV"
    return "PLE"


def coverage_for(dates: list[str]) -> str:
    return "multi_night_report_and_post_event_freeze" if len(set(dates)) > 1 else "report_and_post_event_freeze"


def update_existing(reg: dict[str, Any], ev: dict[str, Any]) -> list[str]:
    changes = []
    dates = sorted(set(ev.get("dates") or []))
    old_dates = [n.get("date_local") for n in reg.get("nights", []) if n.get("date_local")]
    if reg.get("status") != "confirmed":
        changes.append(f"status {reg.get('status')} -> confirmed")
        reg["status"] = "confirmed"
    if reg.get("coverage_policy") == "await_manual_confirmation":
        reg["coverage_policy"] = coverage_for(dates)
        changes.append("coverage_policy -> report_and_post_event_freeze")
    if dates and sorted(old_dates) != dates:
        reg["nights"] = build_nights(reg["key"], dates, reg.get("promotion", ev["promotion"]), reg.get("event_name", ev["event_name"]))
        changes.append(f"nights {old_dates or 'none'} -> {dates}")
    aliases = set(reg.get("aliases", []))
    for a in [ev.get("event_name"), f"{ev.get('promotion')} {ev.get('event_name')}", f"{ev.get('event_name')} 2026"]:
        if a: aliases.add(a)
    reg["aliases"] = sorted(aliases)
    if ev.get("venue"):
        reg["venue"] = ev["venue"]
    if ev.get("location"):
        reg["location"] = ev["location"]
    reg["source"] = "wikipedia_schedule_auto_applied"
    reg["last_verified_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return changes or ["verified_no_date_change"]


def create_event(ev: dict[str, Any]) -> dict[str, Any]:
    dates = sorted(set(ev.get("dates") or []))
    year = dates[0].split("-", 1)[0] if dates else datetime.now(timezone.utc).strftime("%Y")
    key = event_key(ev["promotion"], ev["event_name"], year)
    promotion = ev["promotion"]
    brand = ev.get("brand") or promotion
    name = ev["event_name"]
    return {
        "key": key,
        "promotion": promotion,
        "brand": brand,
        "event_name": name,
        "event_type": event_type_for(promotion, brand, name),
        "priority": priority_for(promotion, name),
        "status": "confirmed",
        "coverage_policy": coverage_for(dates),
        "category_hint": brand if brand in {"NXT", "ROH"} else promotion,
        "aliases": sorted({name, f"{promotion} {name}", f"{name} {year}"}),
        "nights": build_nights(key, dates, promotion, name),
        "venue": ev.get("venue") or "",
        "location": ev.get("location") or "",
        "source": "wikipedia_schedule_auto_applied",
        "last_verified_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def apply_schedule(registry: dict[str, Any], schedule: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    out = deepcopy(registry)
    actions = []
    for ev in schedule.get("events", []):
        promotion = ev.get("promotion")
        name = ev.get("event_name")
        if promotion in SKIP_PROMOTIONS:
            actions.append(f"SKIP {promotion} - {name}: report_only")
            continue
        if promotion not in AUTO_PROMOTIONS:
            actions.append(f"SKIP {promotion} - {name}: unsupported_promotion")
            continue
        if not ev.get("dates"):
            actions.append(f"SKIP {promotion} - {name}: no_dates")
            continue
        score, match = find_match(ev, out)
        if match:
            changes = update_existing(match, ev)
            actions.append(f"UPDATE {match['key']} score={score}: {', '.join(changes)}")
        else:
            new_ev = create_event(ev)
            out.setdefault("events", []).append(new_ev)
            actions.append(f"ADD {new_ev['key']}: {promotion} - {name} dates={','.join(ev['dates'])}")
    out["generated_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out, actions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(REGISTRY_PATH))
    ap.add_argument("--schedule-json", default=None)
    ap.add_argument("--report-dir", default=str(REPORT_DIR))
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    registry_path = Path(args.registry).resolve()
    schedule_path = Path(args.schedule_json).resolve() if args.schedule_json else find_latest_report(Path(args.report_dir).resolve())
    registry = load_json(registry_path)
    schedule = load_json(schedule_path)
    updated, actions = apply_schedule(registry, schedule)
    mode = "WRITE" if args.write else "DRY-RUN"
    print(f"[REGISTRY APPLY] mode={mode}")
    print(f"[REGISTRY APPLY] registry={registry_path}")
    print(f"[REGISTRY APPLY] schedule={schedule_path}")
    for a in actions:
        print("- " + a)
    if args.write:
        registry_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("[REGISTRY APPLY] written")
    else:
        print("[REGISTRY APPLY] dry-run only, use --write to update registry")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
