from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from modules.report_workshop_v92 import run_report_workshop

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED_DIR = ROOT / "published"
REVIEW_DIR = ROOT / "published_html_review"
STATE_DIR = ROOT / "state"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

SIMONE_REPORT_STATUS_FILE = NEWSROOM_STATE_DIR / "simone_report_publish_latest.json"
SIMONE_REPORT_HISTORY_FILE = NEWSROOM_STATE_DIR / "simone_report_history.json"
ARTIFACT_SIMONE_PUBLISH_FILE = ARTIFACT_DIR / "simone_report_publish.json"

VERSION = "v93_25_simone_skip_wp_probe_without_ready_reports"
HEADERS = {"User-Agent": "OpenWrestlingTV-v93-Simone-Reports/1.0"}
REQUEST_TIMEOUT = int(os.getenv("V93_SIMONE_REPORT_WP_TIMEOUT", "12"))
WP_RETRIES = int(os.getenv("V93_SIMONE_REPORT_WP_RETRIES", "2"))
MAX_REPORTS_PER_RUN = int(os.getenv("V93_SIMONE_MAX_REPORTS_PER_RUN", "1"))
DRY_RUN = str(os.getenv("V93_SIMONE_REPORT_DRY_RUN", "0")).strip().lower() in {"1", "true", "yes", "on"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def wp_root() -> str:
    raw = os.getenv("WP_URL", "").strip().rstrip("/")
    if "/wp-json" in raw:
        raw = raw.split("/wp-json", 1)[0].rstrip("/")
    return raw


def wp_auth() -> tuple[str, str]:
    return os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", "")


def log_dns_diagnostics(root: str) -> str:
    try:
        host = urlparse(root).netloc
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips: list[str] = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        return ", ".join(ips) if ips else "no_ip"
    except Exception as exc:
        return f"dns_error:{exc}"


def probe_endpoint(endpoint: str, *, use_auth: bool = False) -> tuple[bool, str]:
    try:
        kwargs: dict[str, Any] = {"headers": HEADERS, "timeout": REQUEST_TIMEOUT}
        if use_auth:
            kwargs["auth"] = wp_auth()
        res = requests.get(endpoint, **kwargs)
        if res.status_code in {200, 401, 403}:
            return True, f"status_{res.status_code}"
        return False, f"status_{res.status_code}"
    except Exception as exc:
        return False, f"wp_error:{exc}"


def wp_ready() -> tuple[bool, str, dict[str, Any]]:
    root = wp_root()
    if not root:
        return False, "missing_wp_url", {}
    if not all(wp_auth()):
        return False, "missing_wp_auth", {"root": root}
    diagnostics = {"root": root, "dns": log_dns_diagnostics(root), "attempts": []}
    endpoints = [(f"{root}/wp-json/", False, "rest_root"), (f"{root}/wp-json/wp/v2/posts?per_page=1", True, "posts_auth")]
    last = "wp_unavailable"
    for attempt in range(1, WP_RETRIES + 1):
        for endpoint, use_auth, label in endpoints:
            ok, status = probe_endpoint(endpoint, use_auth=use_auth)
            diagnostics["attempts"].append({"attempt": attempt, "label": label, "status": status})
            last = status
            if ok:
                return True, status, diagnostics
        if attempt < WP_RETRIES:
            time.sleep(3)
    return False, last, diagnostics


def report_key(report: dict[str, Any]) -> str:
    return str(report.get("report_key") or report.get("source_url") or "").strip()


def build_job(report: dict[str, Any]) -> dict[str, Any]:
    job = dict(report)
    job["kind"] = "report"
    job.setdefault("translation_mode", "report")
    job.setdefault("status", "simone_ready_to_publish")
    job.setdefault("title_policy", "simone_deterministic")
    job.setdefault("created_at", utc_now())
    job["counts_as_news"] = False
    categories = job.get("categories") if isinstance(job.get("categories"), list) else []
    if "Editoriali" not in categories:
        categories = ["Editoriali"] + categories
    job["categories"] = categories
    return job


def empty_result(decision: dict[str, Any], ready_count: int) -> dict[str, Any]:
    return {
        "agent": "Simone",
        "version": VERSION,
        "generated_at": utc_now(),
        "mode": "autonomous_report_publisher_v92_workshop",
        "input": {"simone_version": decision.get("version") if isinstance(decision, dict) else None, "ready_reports": ready_count},
        "wp": {"ready": None, "reason": "skipped_no_ready_reports", "dry_run": DRY_RUN, "diagnostics": {}},
        "results": [],
        "handoff": {"published": 0, "already_published": 0, "wp_not_ready": 0, "dry_run": 0, "errors": 0},
        "policy": {"simone_is_autonomous_for_reports": True, "uses_manual_report_workflow_engine": "modules.report_workshop_v92.run_report_workshop", "checks_wp_before_scrape_or_translation": True, "skips_wp_probe_when_no_ready_reports": True, "max_reports_per_run": MAX_REPORTS_PER_RUN, "reports_count_as_news": False},
    }


def run_simone_report_publisher(simone_decision: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = simone_decision if isinstance(simone_decision, dict) else load_json(NEWSROOM_STATE_DIR / "simone_reports_latest.json", {})
    ready_reports = decision.get("ready_reports", []) if isinstance(decision, dict) else []
    if not isinstance(ready_reports, list):
        ready_reports = []
    ready_reports = ready_reports[:MAX_REPORTS_PER_RUN]

    if not ready_reports:
        result = empty_result(decision if isinstance(decision, dict) else {}, 0)
        write_json(ARTIFACT_SIMONE_PUBLISH_FILE, result)
        write_json(SIMONE_REPORT_STATUS_FILE, result)
        print("[SIMONE v93.25] Nessun report pronto: salto WP probe", flush=True)
        return result

    history = load_json(SIMONE_REPORT_HISTORY_FILE, {})
    if not isinstance(history, dict):
        history = {}

    wp_ok, wp_status, wp_diagnostics = wp_ready()
    print(f"[SIMONE v93.25] Avvio publisher report | ready={len(ready_reports)} wp_ok={wp_ok} dry_run={DRY_RUN}", flush=True)
    results: list[dict[str, Any]] = []
    if not wp_ok:
        results = [{"report_key": report_key(report), "source_url": report.get("source_url"), "title": report.get("title"), "status": "wp_not_ready", "reason": wp_status} for report in ready_reports if isinstance(report, dict)]
    else:
        for report in ready_reports:
            if not isinstance(report, dict):
                continue
            key = report_key(report)
            if not key:
                results.append({"status": "skipped", "reason": "missing_report_key", "source_url": report.get("source_url")})
                continue
            if key in history:
                results.append({"report_key": key, "status": "already_published", "wp_post_id": history[key].get("wp_post_id"), "wp_link": history[key].get("wp_link"), "title": report.get("title")})
                continue
            job = build_job(report)
            if DRY_RUN:
                results.append({"report_key": key, "status": "dry_run", "title": job.get("title"), "source_url": job.get("source_url"), "categories": job.get("categories")})
                continue
            try:
                post_id, post_json = run_report_workshop(job, PUBLISHED_DIR, REVIEW_DIR)
                link = post_json.get("link") if isinstance(post_json, dict) else ""
                history[key] = {"report_key": key, "source_url": job.get("source_url"), "title": job.get("title"), "wp_post_id": post_id, "wp_link": link, "published_at": utc_now(), "categories": job.get("categories", [])}
                results.append({"report_key": key, "status": "published", "wp_post_id": post_id, "wp_link": link, "title": job.get("title"), "source_url": job.get("source_url"), "categories": job.get("categories", [])})
            except Exception as exc:
                results.append({"report_key": key, "status": "publish_error", "error": str(exc)[:1000], "title": job.get("title"), "source_url": job.get("source_url")})
    if not DRY_RUN and wp_ok:
        write_json(SIMONE_REPORT_HISTORY_FILE, history)

    result = {"agent": "Simone", "version": VERSION, "generated_at": utc_now(), "mode": "autonomous_report_publisher_v92_workshop", "input": {"simone_version": decision.get("version") if isinstance(decision, dict) else None, "ready_reports": len(ready_reports)}, "wp": {"ready": wp_ok, "reason": wp_status, "dry_run": DRY_RUN, "diagnostics": wp_diagnostics}, "results": results, "handoff": {"published": sum(1 for r in results if r.get("status") == "published"), "already_published": sum(1 for r in results if r.get("status") == "already_published"), "wp_not_ready": sum(1 for r in results if r.get("status") == "wp_not_ready"), "dry_run": sum(1 for r in results if r.get("status") == "dry_run"), "errors": sum(1 for r in results if r.get("status") == "publish_error")}, "policy": {"simone_is_autonomous_for_reports": True, "uses_manual_report_workflow_engine": "modules.report_workshop_v92.run_report_workshop", "checks_wp_before_scrape_or_translation": True, "skips_wp_probe_when_no_ready_reports": True, "max_reports_per_run": MAX_REPORTS_PER_RUN, "reports_count_as_news": False}}
    write_json(ARTIFACT_SIMONE_PUBLISH_FILE, result)
    write_json(SIMONE_REPORT_STATUS_FILE, result)
    print("[SIMONE v93.25] Report publisher completato | published={published} already={already} wp_not_ready={wp_not_ready} errors={errors}".format(published=result["handoff"]["published"], already=result["handoff"]["already_published"], wp_not_ready=result["handoff"]["wp_not_ready"], errors=result["handoff"]["errors"]), flush=True)
    return result


if __name__ == "__main__":
    print(json.dumps(run_simone_report_publisher().get("handoff", {}), ensure_ascii=False, indent=2))
