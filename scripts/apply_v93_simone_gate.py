from pathlib import Path

p = Path("bot_v92.py")
text = p.read_text(encoding="utf-8")

if "V93_SIMONE_GATE_ACTIVE = True" in text:
    print("[V93 SIMONE GATE] gia applicato")
    raise SystemExit(0)

# Add state constants near report status files.
needle = 'REPORT_STATUS_FILE = STATE_DIR / "report_status.json"\n'
if needle not in text:
    raise SystemExit("[V93 SIMONE GATE] REPORT_STATUS_FILE marker non trovato")
text = text.replace(
    needle,
    needle
    + 'NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"\n'
    + 'V93_SIMONE_REPORTS_FILE = NEWSROOM_STATE_DIR / "simone_reports_latest.json"\n'
    + 'V93_SIMONE_GATE_ACTIVE = True\n',
    1,
)

insert_before = '\n\ndef run_report_pipeline(wp_ok: bool, now: datetime) -> int:\n'
if insert_before not in text:
    raise SystemExit("[V93 SIMONE GATE] run_report_pipeline marker non trovato")

helpers = r'''

def v93_simone_gate_enabled() -> bool:
    return str(os.getenv("V93_SIMONE_REPORT_GATE", "1")).strip().lower() not in {"0", "false", "no", "off"}


def load_v93_simone_reports() -> Dict[str, Any]:
    data = load_json(V93_SIMONE_REPORTS_FILE, {})
    return data if isinstance(data, dict) else {}


def v93_simone_report_decisions_available(data: Dict[str, Any]) -> bool:
    return any(isinstance(data.get(key), list) for key in ["ready_reports", "waiting_reports", "skipped_reports"])


def v93_simone_find_report(data: Dict[str, Any], report_key: str) -> Optional[Dict[str, Any]]:
    for section in ["ready_reports", "waiting_reports", "skipped_reports"]:
        items = data.get(section, []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("report_key") == report_key:
                out = dict(item)
                out["simone_section"] = section
                return out
    return None


def v93_simone_chosen_entry(decision: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": decision.get("source"),
        "url": decision.get("source_url"),
        "title": decision.get("source_title"),
        "published": decision.get("published", ""),
        "summary": "",
    }
'''
text = text.replace(insert_before, helpers + insert_before, 1)

# Insert Simone gate setup after pending is loaded. This is more stable than
# matching the feed_entries block, because several v92 patches may alter the
# exact spacing/order of report scan code.
setup_anchor = '''    pending = load_json(PENDING_REPORTS_FILE, [])
'''
setup_code = '''    pending = load_json(PENDING_REPORTS_FILE, [])
    simone_reports = load_v93_simone_reports() if v93_simone_gate_enabled() else {}
    simone_gate_active = v93_simone_gate_enabled() and v93_simone_report_decisions_available(simone_reports)
    if simone_gate_active:
        handoff = simone_reports.get("handoff", {}) if isinstance(simone_reports, dict) else {}
        log(f"[REPORT v92] V93 Simone gate attivo: ready={handoff.get('ready', 0)} waiting={handoff.get('waiting', 0)} skipped={handoff.get('skipped', 0)}")
    else:
        log("[REPORT v92] V93 Simone gate non vincolante: decisioni assenti o gate disattivato")
'''
if setup_anchor not in text:
    raise SystemExit("[V93 SIMONE GATE] pending reports anchor non trovato")
text = text.replace(setup_anchor, setup_code, 1)

# Replace the point where v92 chooses the report source. Keep a fallback to the
# old v92 choice only if the Simone decision file is absent or the gate is disabled.
old = '''        chosen, reason = choose_report_source(report, entries, now, date_iso)
        title = build_report_title(report, date_iso)
        categories = categories_for_report(report, categories_cfg)

        if not chosen:
'''
new = '''        title = build_report_title(report, date_iso)
        categories = categories_for_report(report, categories_cfg)
        simone_decision = v93_simone_find_report(simone_reports, report_key) if simone_gate_active else None
        if simone_gate_active:
            if not simone_decision:
                log(f"[REPORT v92] Skip V93 Simone gate: nessuna decisione per {report_key}")
                status[report_key] = {
                    "status": "simone_no_decision",
                    "title": title,
                    "updated_at": utcnow().isoformat(),
                    "categories": categories,
                }
                continue
            if simone_decision.get("simone_section") != "ready_reports":
                reason = str(simone_decision.get("reason") or simone_decision.get("decision") or "not_ready")
                log(f"[REPORT v92] Skip V93 Simone gate: {report_key} section={simone_decision.get('simone_section')} reason={reason}")
                status[report_key] = {
                    "status": f"simone_{simone_decision.get('simone_section')}",
                    "title": title,
                    "updated_at": utcnow().isoformat(),
                    "categories": categories,
                    "reason": reason,
                }
                continue
            chosen = v93_simone_chosen_entry(simone_decision)
            reason = f"simone_{simone_decision.get('reason') or 'ready'}"
            log(f"[REPORT v92] V93 Simone gate autorizza: {report_key} source={chosen.get('source')} url={chosen.get('url')}")
        else:
            chosen, reason = choose_report_source(report, entries, now, date_iso)

        if not chosen:
'''
if old not in text:
    raise SystemExit("[V93 SIMONE GATE] blocco choose_report_source non trovato")
text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")
print("[V93 SIMONE GATE] applicato")
