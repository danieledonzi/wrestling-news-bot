from pathlib import Path

p = Path("bot_v92.py")
text = p.read_text(encoding="utf-8")

if "V93_SIMONE_GATE_ACTIVE = True" in text:
    print("[V93 SIMONE GATE] gia applicato")
    raise SystemExit(0)

# Add state constants near report status files. Define NEWSROOM_STATE_DIR here
# regardless of whether another later patch will also need it.
needle = 'REPORT_STATUS_FILE = STATE_DIR / "report_status.json"\n'
if needle not in text:
    raise SystemExit("[V93 SIMONE GATE] REPORT_STATUS_FILE marker non trovato")
constants = (
    'NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"\n'
    'V93_SIMONE_REPORTS_FILE = NEWSROOM_STATE_DIR / "simone_reports_latest.json"\n'
    'V93_SIMONE_GATE_ACTIVE = True\n'
)
text = text.replace(needle, needle + constants, 1)

# Add helpers before run_report_pipeline.
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

start = text.find("def run_report_pipeline(wp_ok: bool, now: datetime) -> int:")
end = text.find("\n\ndef run_news_pipeline(wp_ok: bool, now: datetime) -> int:", start)
if start == -1 or end == -1:
    raise SystemExit("[V93 SIMONE GATE] impossibile delimitare run_report_pipeline")

run_func = r'''def run_report_pipeline(wp_ok: bool, now: datetime) -> int:
    reports_cfg = load_json(REPORTS_CONFIG, {"reports": []})
    feeds_cfg = load_json(FEEDS_CONFIG, {"feeds": []})
    categories_cfg = load_json(CATEGORIES_CONFIG, {})
    status = load_json(REPORT_STATUS_FILE, {})
    pending = load_json(PENDING_REPORTS_FILE, [])

    simone_reports = load_v93_simone_reports() if v93_simone_gate_enabled() else {}
    simone_gate_active = v93_simone_gate_enabled() and v93_simone_report_decisions_available(simone_reports)
    if simone_gate_active:
        handoff = simone_reports.get("handoff", {}) if isinstance(simone_reports, dict) else {}
        log(f"[REPORT v92] V93 Simone gate attivo: ready={handoff.get('ready', 0)} waiting={handoff.get('waiting', 0)} skipped={handoff.get('skipped', 0)}")
    else:
        log("[REPORT v92] V93 Simone gate non vincolante: decisioni assenti o gate disattivato")

    entries = feed_entries(feeds_cfg.get("feeds", []))
    published = 0

    for report in reports_cfg.get("reports", []):
        if published >= MAX_REPORTS_PER_RUN:
            break
        if not report_due_today(report, now):
            log(f"[REPORT v92] Non dovuto oggi: {report.get('id')} expected_day_after={report.get('expected_day_after')}")
            continue

        report_key, date_iso = report_date_key(report, now)
        current = status.get(report_key, {})
        if current.get("status") == "published":
            log(f"[REPORT v92] Gia pubblicato: {report_key}")
            continue

        title = build_report_title(report, date_iso)
        categories = categories_for_report(report, categories_cfg)

        if simone_gate_active:
            simone_decision = v93_simone_find_report(simone_reports, report_key)
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
            log(f"[REPORT v92] Non pronto: {report_key} reason={reason} title={title}")
            status[report_key] = {
                "status": reason,
                "title": title,
                "updated_at": utcnow().isoformat(),
                "categories": categories,
            }
            continue

        job = {
            "kind": "report",
            "report_key": report_key,
            "report_id": report.get("id"),
            "source": chosen.get("source"),
            "source_url": chosen.get("url"),
            "source_title": chosen.get("title"),
            "title": title,
            "date": date_iso,
            "categories": categories,
            "title_policy": "deterministic",
            "translation_mode": "report",
            "created_at": utcnow().isoformat(),
            "status": "ready_to_publish" if wp_ok else "ready_when_wp_returns",
            "gate": "simone" if simone_gate_active else "v92_fallback",
        }
        log(f"[REPORT v92] Pronto: {report_key} source={job['source']} url={job['source_url']}")
        log(f"[REPORT v92] Fonte title: {job['source_title']}")
        log(f"[REPORT v92] Titolo deterministico: {title}")
        log(f"[REPORT v92] Categorie: {', '.join(categories)}")

        if wp_ok:
            try:
                log(f"[REPORT v92] Avvio workshop pubblicazione: {report_key}")
                post_id, _post_json = run_report_workshop(job, PUBLISHED_DIR, REVIEW_DIR)
                status[report_key] = {
                    "status": "published",
                    "source": job["source"],
                    "source_url": job["source_url"],
                    "source_title": job["source_title"],
                    "title": title,
                    "categories": categories,
                    "wp_post_id": post_id,
                    "published_at": utcnow().isoformat(),
                    "updated_at": utcnow().isoformat(),
                    "gate": job["gate"],
                }
                pending = [p for p in pending if p.get("report_key") != report_key]
                published += 1
                continue
            except Exception as exc:
                log(f"[REPORT v92] Errore workshop report {report_key}: {exc}")
                job["status"] = "failed_technical"
                job["error"] = str(exc)[:1000]

        pending = [p for p in pending if p.get("report_key") != report_key]
        pending.append(job)
        status[report_key] = {
            "status": job["status"],
            "source": job["source"],
            "source_url": job["source_url"],
            "source_title": job["source_title"],
            "title": title,
            "categories": categories,
            "updated_at": utcnow().isoformat(),
            "error": job.get("error"),
            "gate": job["gate"],
        }

    save_json(REPORT_STATUS_FILE, status)
    save_json(PENDING_REPORTS_FILE, pending)
    return published
'''

text = text[:start] + run_func + text[end:]
p.write_text(text, encoding="utf-8")
print("[V93 SIMONE GATE] applicato")
