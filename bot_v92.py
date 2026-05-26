from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import feedparser
import requests

BOT_VERSION = "v92_0_clean_split_pipeline_bootstrap"
TZ_LABEL = "Europe/Rome"
ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
CONFIG_DIR = ROOT / "config"

REPORTS_CONFIG = CONFIG_DIR / "reports_v92.json"
FEEDS_CONFIG = CONFIG_DIR / "feeds_v92.json"
CATEGORIES_CONFIG = CONFIG_DIR / "categories_v92.json"
REPORT_STATUS_FILE = STATE_DIR / "report_status.json"
PENDING_REPORTS_FILE = STATE_DIR / "pending_reports.json"
PENDING_NEWS_FILE = STATE_DIR / "pending_news.json"
MASTER_LOG = LOG_DIR / "master_log.log"
BOT_EXIT_CODE = ROOT / ".bot_exit_code"

MAX_REPORTS_PER_RUN = int(os.getenv("V92_MAX_REPORTS_PER_RUN", "1"))
MAX_NEWS_PER_RUN = int(os.getenv("V92_MAX_NEWS_PER_RUN", "3"))
REQUEST_TIMEOUT = int(os.getenv("V92_REQUEST_TIMEOUT", "10"))


def utcnow() -> datetime:
    return datetime.utcnow()


def now_local_naive() -> datetime:
    # GitHub Actions runs UTC. Europe/Rome DST is +2 on May; for this bootstrap we use +2.
    # Later this should use zoneinfo Europe/Rome.
    return utcnow() + timedelta(hours=2)


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    ensure_dirs()
    line = message.rstrip()
    print(line, flush=True)
    with MASTER_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"[V92 STATE] Warning: impossibile leggere {path}: {exc}")
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def wp_health_check() -> Tuple[bool, str]:
    wp_url = os.getenv("WP_URL", "").rstrip("/")
    if not wp_url:
        return False, "missing_wp_url"
    endpoint = f"{wp_url}/wp-json/wp/v2/posts?per_page=1"
    for attempt in range(1, 4):
        try:
            r = requests.get(endpoint, timeout=6)
            if r.status_code in (200, 401, 403):
                log(f"[WP v92] Health check API OK: status {r.status_code} | tentativo {attempt}/3")
                return True, f"status_{r.status_code}"
            log(f"[WP v92] Health check risposta inattesa: status {r.status_code} | tentativo {attempt}/3")
        except Exception as exc:
            log(f"[WP v92] Health check timeout/errore | tentativo {attempt}/3: {exc}")
    return False, "wp_unavailable"


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    s = normalize_text(text).replace(" ", "-")
    return s[:120] or "item"


def parse_hhmm(value: str) -> Tuple[int, int]:
    h, m = (value or "00:00").split(":", 1)
    return int(h), int(m)


def report_due_today(report: Dict[str, Any], now: datetime) -> bool:
    if not report.get("enabled", True):
        return False
    publish_after = report.get("publish_after", "06:30")
    h, m = parse_hhmm(publish_after)
    return now.time() >= now.replace(hour=h, minute=m, second=0, microsecond=0).time()


def report_date_key(report: Dict[str, Any], now: datetime) -> Tuple[str, str]:
    # For weekly shows we use previous day as show date after midnight/morning.
    show_date = now.date() - timedelta(days=int(report.get("show_date_offset_days", 1)))
    date_iso = show_date.isoformat()
    key = f"{report['id']}_{date_iso.replace('-', '_')}"
    return key, date_iso


def date_it(date_iso: str) -> str:
    months = [
        "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ]
    y, m, d = [int(x) for x in date_iso.split("-")]
    return f"{d} {months[m-1]} {y}"


def build_report_title(report: Dict[str, Any], date_iso: str) -> str:
    template = report.get("title_template") or "{show_name} del {date_it} - risultati e momenti salienti"
    return template.format(
        show_name=report.get("show_name", report.get("id", "Report")),
        date_iso=date_iso,
        date_it=date_it(date_iso),
        year=date_iso[:4],
    )


def feed_entries(feeds: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for feed in feeds:
        url = feed.get("url")
        source = feed.get("id") or feed.get("name") or url
        if not url:
            continue
        log(f"[FEED v92] Scansione feed: {url}")
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries:
                out.append({
                    "source": source,
                    "feed_url": url,
                    "title": getattr(e, "title", "") or "",
                    "url": getattr(e, "link", "") or "",
                    "published": getattr(e, "published", "") or getattr(e, "updated", "") or "",
                    "summary": getattr(e, "summary", "") or "",
                })
        except Exception as exc:
            log(f"[FEED v92] Errore feed {url}: {exc}")
    return out


def source_rank(source: str, report: Dict[str, Any]) -> int:
    if source == report.get("preferred_source"):
        return 0
    if source == report.get("fallback_source"):
        return 1
    return 9


def report_keywords(report: Dict[str, Any]) -> List[str]:
    return [normalize_text(x) for x in report.get("match_keywords", []) if x]


def is_report_candidate(entry: Dict[str, Any], report: Dict[str, Any]) -> bool:
    title = normalize_text(entry.get("title", ""))
    url = normalize_text(entry.get("url", ""))
    blob = f"{title} {url}"
    if "results" not in blob and "risultati" not in blob:
        return False
    kws = report_keywords(report)
    return any(kw and kw in blob for kw in kws)


def choose_report_source(report: Dict[str, Any], entries: List[Dict[str, Any]], now: datetime) -> Tuple[Optional[Dict[str, Any]], str]:
    candidates = [e for e in entries if is_report_candidate(e, report)]
    if not candidates:
        return None, "no_candidate"

    candidates.sort(key=lambda e: (source_rank(e.get("source", ""), report), e.get("published", "")), reverse=False)
    preferred = [e for e in candidates if e.get("source") == report.get("preferred_source")]
    if preferred:
        return preferred[0], "preferred_source"

    wait_until = report.get("wait_for_preferred_until")
    if wait_until:
        h, m = parse_hhmm(wait_until)
        if now.time() < now.replace(hour=h, minute=m, second=0, microsecond=0).time():
            return None, "waiting_for_preferred_source"

    fallback = [e for e in candidates if e.get("source") == report.get("fallback_source")]
    if fallback:
        return fallback[0], "fallback_source"
    return candidates[0], "other_source"


def categories_for_report(report: Dict[str, Any], categories_cfg: Dict[str, Any]) -> List[str]:
    names = []
    editorial = report.get("editorial_category", "Editoriali")
    company = report.get("category")
    if editorial:
        names.append(editorial)
    if company and company not in names:
        names.append(company)
    return names


def run_report_pipeline(wp_ok: bool, now: datetime) -> int:
    reports_cfg = load_json(REPORTS_CONFIG, {"reports": []})
    feeds_cfg = load_json(FEEDS_CONFIG, {"feeds": []})
    categories_cfg = load_json(CATEGORIES_CONFIG, {})
    status = load_json(REPORT_STATUS_FILE, {})
    pending = load_json(PENDING_REPORTS_FILE, [])

    entries = feed_entries(feeds_cfg.get("feeds", []))
    published = 0

    for report in reports_cfg.get("reports", []):
        if published >= MAX_REPORTS_PER_RUN:
            break
        if not report_due_today(report, now):
            continue
        report_key, date_iso = report_date_key(report, now)
        current = status.get(report_key, {})
        if current.get("status") == "published":
            log(f"[REPORT v92] Gia pubblicato: {report_key}")
            continue

        chosen, reason = choose_report_source(report, entries, now)
        title = build_report_title(report, date_iso)
        categories = categories_for_report(report, categories_cfg)

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
        }
        log(f"[REPORT v92] Pronto: {report_key} source={job['source']} url={job['source_url']}")
        log(f"[REPORT v92] Titolo deterministico: {title}")
        log(f"[REPORT v92] Categorie: {', '.join(categories)}")

        # v92 bootstrap: do not publish until article_workshop is ported.
        # Keep the job deterministic and visible in pending_reports.json.
        pending = [p for p in pending if p.get("report_key") != report_key]
        pending.append(job)
        status[report_key] = {
            "status": job["status"],
            "source": job["source"],
            "source_url": job["source_url"],
            "title": title,
            "categories": categories,
            "updated_at": utcnow().isoformat(),
        }

    save_json(REPORT_STATUS_FILE, status)
    save_json(PENDING_REPORTS_FILE, pending)
    return published


def run_news_pipeline(wp_ok: bool, now: datetime) -> int:
    # v92 bootstrap: intentionally disabled until report pipeline and article_workshop are stable.
    save_json(PENDING_NEWS_FILE, [])
    log(f"[NEWS v92] Pipeline news non ancora attiva. max_news_per_run={MAX_NEWS_PER_RUN}")
    return 0


def main() -> int:
    ensure_dirs()
    now = now_local_naive()
    log(f"===== RUN START [{now.isoformat(timespec='seconds')}] VERSION [{BOT_VERSION}] =====")
    wp_ok, wp_status = wp_health_check()
    log(f"[RUN v92] wp_ok={wp_ok} wp_status={wp_status}")
    reports = run_report_pipeline(wp_ok, now)
    news = run_news_pipeline(wp_ok, now)
    log(f"[RUN v92] totale pubblicazioni={reports + news} (report={reports}, news={news})")
    log(f"===== RUN END [{now.isoformat(timespec='seconds')}] VERSION [{BOT_VERSION}] =====")
    BOT_EXIT_CODE.write_text("0", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
