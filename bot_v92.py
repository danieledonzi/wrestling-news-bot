from __future__ import annotations

import json
import os
import re
import socket
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests
from modules.news_workshop_v92 import analyze_news_editorial, run_news_workshop
from modules.report_workshop_v92 import run_report_workshop

BOT_VERSION = "v92_0_2_report_workshop_publish"
V92_STABILITY_PATCH_ACTIVE = True
V92_BUSINESS_PLE_CARD_PATCH_ACTIVE = True
V92_POSTRUN_GUARDRAILS_ACTIVE = True
V92_NEWS_QUALITY_GUARDRAILS_ACTIVE = True
V92_BUSINESS_BOUNDARY_PATCH_ACTIVE = True
V92_NEWS_DEDUPE_PLACEHOLDER_ACTIVE = True
V92_NEWS_CATEGORY_EVENT_FIX_ACTIVE = True
V92_NEWS_FINAL_CATEGORY_QUOTE_PATCH_ACTIVE = True
TZ_LABEL = "Europe/Rome"
ROME_TZ = ZoneInfo("Europe/Rome")
ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
CONFIG_DIR = ROOT / "config"
PUBLISHED_DIR = ROOT / "published"
REVIEW_DIR = ROOT / "published_html_review"
PUBLISHED_DIR = ROOT / "published"
REVIEW_DIR = ROOT / "published_html_review"

REPORTS_CONFIG = CONFIG_DIR / "reports_v92.json"
FEEDS_CONFIG = CONFIG_DIR / "feeds_v92.json"
CATEGORIES_CONFIG = CONFIG_DIR / "categories_v92.json"
REPORT_STATUS_FILE = STATE_DIR / "report_status.json"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
V93_SIMONE_REPORTS_FILE = NEWSROOM_STATE_DIR / "simone_reports_latest.json"
V93_SIMONE_GATE_ACTIVE = True
PENDING_REPORTS_FILE = STATE_DIR / "pending_reports.json"
PENDING_NEWS_FILE = STATE_DIR / "pending_news.json"
PUBLISHED_NEWS_FILE = STATE_DIR / "published_news.json"
NEWS_HARD_SKIPS_FILE = STATE_DIR / "news_hard_skips.json"
NEWS_SOFT_POOL_FILE = STATE_DIR / "news_soft_pool.json"
V93_MENZO_ALLOWED_NEWS_FILE = NEWSROOM_STATE_DIR / "v92_allowed_news_urls.json"
V93_MENZO_GATE_ACTIVE = True
V92_NEWS_PIPELINE_ACTIVE = True
V92_NEWS_SCORING_V2_ACTIVE = True
MASTER_LOG = LOG_DIR / "master_log.log"
BOT_EXIT_CODE = ROOT / ".bot_exit_code"

MAX_REPORTS_PER_RUN = int(os.getenv("V92_MAX_REPORTS_PER_RUN", "1"))
MAX_NEWS_PER_RUN = int(os.getenv("V92_MAX_NEWS_PER_RUN", "3"))
V92_MIN_SOFT_PUBLISH_SCORE = int(os.getenv("V92_MIN_SOFT_PUBLISH_SCORE", "70"))
V92_MIN_HARD_PUBLISH_SCORE = int(os.getenv("V92_MIN_HARD_PUBLISH_SCORE", "75"))
REQUEST_TIMEOUT = int(os.getenv("V92_REQUEST_TIMEOUT", "10"))


def utcnow() -> datetime:
    return datetime.utcnow()


def now_local_naive() -> datetime:
    return datetime.now(ROME_TZ).replace(tzinfo=None)


def ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)


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


def wp_root_from_env() -> str:
    raw = os.getenv("WP_URL", "").strip().rstrip("/")
    if not raw:
        return ""
    marker = "/wp-json"
    if marker in raw:
        return raw.split(marker, 1)[0].rstrip("/")
    return raw


def log_wp_dns_diagnostics(root: str) -> None:
    try:
        host = urlparse(root).netloc
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips: List[str] = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        log(f"[WP v92] BOT WP DIAG DNS {host}: {', '.join(ips) if ips else 'nessun IP'}")
    except Exception as exc:
        log(f"[WP v92] BOT WP DIAG DNS fallita: {exc}")


def wp_probe_endpoint(endpoint: str, timeout: int, use_auth: bool = False) -> Tuple[bool, str]:
    start_time = time.monotonic()
    try:
        kwargs: Dict[str, Any] = {"timeout": timeout}
        if use_auth:
            kwargs["auth"] = (os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", ""))
        r = requests.get(endpoint, **kwargs)
        elapsed = time.monotonic() - start_time
        log(f"[WP v92] BOT WP DIAG probe status={r.status_code} elapsed={elapsed:.2f}s endpoint={endpoint}")
        if r.status_code in (200, 401, 403):
            return True, f"status_{r.status_code}"
        return False, f"status_{r.status_code}"
    except Exception as exc:
        elapsed = time.monotonic() - start_time
        log(f"[WP v92] BOT WP DIAG probe timeout/errore elapsed={elapsed:.2f}s endpoint={endpoint}: {exc}")
        return False, "wp_error"


def wp_health_check() -> Tuple[bool, str]:
    root = wp_root_from_env()
    if not root:
        return False, "missing_wp_url"
    timeout = int(os.getenv("V92_WP_HEALTH_TIMEOUT", "10"))
    retries = int(os.getenv("V92_WP_HEALTH_RETRIES", "2"))
    log_wp_dns_diagnostics(root)
    endpoints = [
        (f"{root}/", False, "home"),
        (f"{root}/wp-json/", False, "rest_root"),
        (f"{root}/wp-json/wp/v2/posts?per_page=1", True, "posts_auth"),
    ]
    last_status = "wp_unavailable"
    for attempt in range(1, retries + 1):
        log(f"[WP v92] BOT WP DIAG health attempt {attempt}/{retries} timeout={timeout}s")
        for endpoint, use_auth, label in endpoints:
            ok, status = wp_probe_endpoint(endpoint, timeout=timeout, use_auth=use_auth)
            last_status = status
            if ok and label in {"rest_root", "posts_auth"}:
                log(f"[WP v92] Health check API OK: {status} label={label} | tentativo {attempt}/{retries}")
                return True, status
    return False, last_status


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
    expected_day = str(report.get("expected_day_after") or "").strip().lower()
    if expected_day and now.strftime("%A").lower() != expected_day:
        return False
    publish_after = report.get("publish_after", "06:30")
    h, m = parse_hhmm(publish_after)
    return now.time() >= now.replace(hour=h, minute=m, second=0, microsecond=0).time()


def report_date_key(report: Dict[str, Any], now: datetime) -> Tuple[str, str]:
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


def date_tokens(date_iso: str) -> List[str]:
    y, m, d = [int(x) for x in date_iso.split("-")]
    month_names = [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ]
    month = month_names[m - 1]
    return [
        f"{m}/{d}", f"{m:02d}/{d:02d}", f"{m}-{d}", f"{m:02d}-{d:02d}",
        f"{month} {d}", f"{month}-{d}", f"{month} {d} {y}", f"{month}-{d}-{y}",
        f"{y}-{m:02d}-{d:02d}",
    ]


def entry_mentions_report_date(entry: Dict[str, Any], date_iso: str) -> bool:
    raw = f"{entry.get('title', '')} {entry.get('url', '')}".lower()
    normalized = normalize_text(raw)
    for token in date_tokens(date_iso):
        if token.lower() in raw or normalize_text(token) in normalized:
            return True
    return False


def entry_published_near_report(entry: Dict[str, Any], date_iso: str) -> bool:
    published = entry.get("published") or ""
    if not published:
        return False
    try:
        dt = parsedate_to_datetime(published)
        if dt.tzinfo is not None:
            dt = dt.astimezone(ROME_TZ).replace(tzinfo=None)
        expected = datetime.fromisoformat(date_iso)
        return expected.date() <= dt.date() <= (expected + timedelta(days=2)).date()
    except Exception:
        return False


def is_combined_aew_dynamite_collision_report(entry: Dict[str, Any], report: Dict[str, Any], date_iso: str) -> bool:
    if str(report.get("id") or "") != "aew_dynamite":
        return False
    raw = f"{entry.get('title', '')} {entry.get('url', '')}".lower()
    blob = normalize_text(raw)
    combined_patterns = [
        "aew dynamite collision results",
        "aew dynamite and collision results",
        "aew dynamite collision highlights",
        "dynamite collision results",
        "dynamite and collision results",
    ]
    slash_or_amp = bool(re.search(r"aew\s+dynamite\s*(?:&|/|and)\s*collision\s+results", raw, re.I))
    if not slash_or_amp and not any(p in blob for p in combined_patterns):
        return False
    if not entry_mentions_report_date(entry, date_iso):
        log(f"[REPORT v92] Scarto AEW combined data non coerente: {entry.get('title')} | expected={date_iso}")
        return False
    if not entry_published_near_report(entry, date_iso):
        log(f"[REPORT v92] Scarto AEW combined pubblicazione non coerente: {entry.get('title')} | published={entry.get('published')} expected={date_iso}")
        return False
    log(f"[REPORT v92] Match report combinato AEW Dynamite/Collision: {entry.get('title')}")
    return True


def is_report_candidate(entry: Dict[str, Any], report: Dict[str, Any], date_iso: str) -> bool:
    if is_combined_aew_dynamite_collision_report(entry, report, date_iso):
        return True
    title = normalize_text(entry.get("title", ""))
    url = normalize_text(entry.get("url", ""))
    blob = f"{title} {url}"
    if "results" not in blob and "risultati" not in blob:
        return False
    kws = report_keywords(report)
    if not any(kw and kw in blob for kw in kws):
        return False
    if not entry_mentions_report_date(entry, date_iso):
        log(f"[REPORT v92] Scarto candidato data non coerente: {entry.get('title')} | expected={date_iso}")
        return False
    if not entry_published_near_report(entry, date_iso):
        log(f"[REPORT v92] Scarto candidato pubblicazione non coerente: {entry.get('title')} | published={entry.get('published')} expected={date_iso}")
        return False
    return True


def choose_report_source(report: Dict[str, Any], entries: List[Dict[str, Any]], now: datetime, date_iso: str) -> Tuple[Optional[Dict[str, Any]], str]:
    candidates = [e for e in entries if is_report_candidate(e, report, date_iso)]
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
    rules = categories_cfg.get("report_category_rules", {}) if isinstance(categories_cfg, dict) else {}
    category = report.get("category")
    if category in rules:
        return list(dict.fromkeys(rules[category]))
    names = []
    editorial = report.get("editorial_category", "Editoriali")
    if editorial:
        names.append(editorial)
    if category and category not in names:
        names.append(category)
    return names


def report_show_token(report: Dict[str, Any]) -> str:
    rid = str(report.get("id") or "")
    if rid == "wwe_raw":
        return "raw"
    if rid == "wwe_smackdown":
        return "smackdown"
    if rid == "wwe_nxt":
        return "nxt"
    if rid == "aew_dynamite":
        return "dynamite"
    if rid == "aew_collision":
        return "collision"
    return normalize_text(str(report.get("show_name") or rid)).split(" ")[-1]


def report_title_matches(title_text: str, report: Dict[str, Any], date_iso: str) -> bool:
    blob = normalize_text(title_text)
    show_token = report_show_token(report)
    date_token = normalize_text(date_it(date_iso))
    if not show_token or show_token not in blob:
        return False
    if date_token not in blob:
        return False
    if "risultati" not in blob and "momenti salienti" not in blob and "results" not in blob:
        return False
    return True


def manual_report_already_published(report: Dict[str, Any], date_iso: str, title: str) -> Optional[Dict[str, Any]]:
    manual_file = STATE_DIR / "manual_runs.json"
    data = load_json(manual_file, [])
    if not isinstance(data, list):
        return None
    for item in reversed(data):
        job = item.get("job", {}) if isinstance(item, dict) else {}
        job_title = str(job.get("title") or "")
        if not job_title:
            continue
        if report_title_matches(job_title, report, date_iso):
            return {
                "source": "manual_runs",
                "wp_post_id": item.get("wp_post_id"),
                "link": item.get("link"),
                "matched_title": job_title,
            }
    return None


def wp_report_already_published(report: Dict[str, Any], date_iso: str, title: str) -> Optional[Dict[str, Any]]:
    root = wp_root_from_env()
    if not root:
        return None
    search_terms = [title, f"{report.get('show_name', '')} {date_it(date_iso)}"]
    for term in search_terms:
        try:
            res = requests.get(
                f"{root}/wp-json/wp/v2/posts",
                params={"search": term, "per_page": 10, "status": "publish"},
                timeout=REQUEST_TIMEOUT,
                auth=(os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", "")),
            )
            if res.status_code != 200:
                continue
            for post in res.json():
                rendered = str((post.get("title") or {}).get("rendered") or "")
                if report_title_matches(rendered, report, date_iso):
                    return {
                        "source": "wordpress_search",
                        "wp_post_id": post.get("id"),
                        "link": post.get("link"),
                        "matched_title": rendered,
                    }
        except Exception as exc:
            log(f"[REPORT v92] Warning controllo duplicato WP fallito: {exc}")
            continue
    return None


def report_already_published_elsewhere(report: Dict[str, Any], date_iso: str, title: str, wp_ok: bool) -> Optional[Dict[str, Any]]:
    manual = manual_report_already_published(report, date_iso, title)
    if manual:
        return manual
    if wp_ok:
        return wp_report_already_published(report, date_iso, title)
    return None


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


def run_report_pipeline(wp_ok: bool, now: datetime) -> int:
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

    entries: Optional[List[Dict[str, Any]]] = None
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


def hydrate_soft_pool(soft_pool: Any, now: datetime) -> List[Dict[str, Any]]:
    if isinstance(soft_pool, list):
        return [item for item in soft_pool if isinstance(item, dict)]
    if isinstance(soft_pool, dict):
        items = soft_pool.get("items") or soft_pool.get("soft_items") or soft_pool.get("pool") or []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def is_report_like_news(entry: Dict[str, Any]) -> bool:
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('url', '')}")
    report_terms = ["results", "risultati", "recap", "live coverage", "coverage", "report"]
    show_terms = ["raw", "smackdown", "nxt", "dynamite", "collision", "impact", "aew", "wwe", "tna", "roh"]
    return any(term in blob for term in report_terms) and any(term in blob for term in show_terms)


def v93_gate_key(url: str) -> str:
    raw = str(url or "").strip().lower()
    if not raw:
        return ""
    raw = raw.split("#", 1)[0]
    raw = raw.split("?", 1)[0]
    return raw.rstrip("/")


def load_v93_menzo_allowed_urls() -> set[str]:
    data = load_json(V93_MENZO_ALLOWED_NEWS_FILE, {})
    urls = data.get("allowed_urls", []) if isinstance(data, dict) else []
    if not isinstance(urls, list):
        return set()
    return {v93_gate_key(str(url)) for url in urls if v93_gate_key(str(url))}


def v93_menzo_gate_enabled() -> bool:
    return str(os.getenv("V93_MENZO_GATE", "1")).strip().lower() not in {"0", "false", "no", "off"}


def v93_menzo_allows(entry: Dict[str, Any], allowed: set[str]) -> bool:
    if not allowed:
        return True
    url = v93_gate_key(str(entry.get("url") or entry.get("source_url") or ""))
    return bool(url and url in allowed)


def v93_filter_soft_pool_items(items: List[Dict[str, Any]], allowed: set[str]) -> List[Dict[str, Any]]:
    if not allowed:
        return items
    return [item for item in items if v93_menzo_allows(item, allowed)]


def run_news_pipeline(wp_ok: bool, now: datetime) -> int:
    if not wp_ok:
        log("[NEWS v92] WordPress non disponibile: skip news")
        return 0

    feeds_cfg = load_json(FEEDS_CONFIG, {"feeds": []})
    published_urls = load_json(PUBLISHED_NEWS_FILE, {})
    hard_skips = load_json(NEWS_HARD_SKIPS_FILE, {})
    soft_pool = load_json(NEWS_SOFT_POOL_FILE, {})
    pending: List[Dict[str, Any]] = []

    entries = feed_entries(feeds_cfg.get("feeds", []))
    allowed_urls = load_v93_menzo_allowed_urls() if v93_menzo_gate_enabled() else set()
    if allowed_urls:
        log(f"[NEWS v92] V93 Menzo gate attivo: allowed_urls={len(allowed_urls)}")
    else:
        log("[NEWS v92] V93 Menzo gate non vincolante: allowed_urls vuoto o gate disattivato")
    hard_items: List[Dict[str, Any]] = []
    hydrated_soft_items = hydrate_soft_pool(soft_pool, now)
    soft_items: List[Dict[str, Any]] = v93_filter_soft_pool_items(hydrated_soft_items, allowed_urls)
    if allowed_urls and len(soft_items) != len(hydrated_soft_items):
        log(f"[NEWS v92] V93 Menzo gate soft_pool filtrata: kept={len(soft_items)} original={len(hydrated_soft_items)}")
    seen: set[str] = set()

    for entry in entries:
        url = str(entry.get("url") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not url or not title:
            continue
        if url in seen:
            continue
        seen.add(url)
        if url in published_urls:
            continue
        if url in hard_skips:
            continue
        if not v93_menzo_allows(entry, allowed_urls):
            log(f"[NEWS v92] Skip V93 Menzo gate: {title}")
            continue

        if is_report_like_news(entry):
            log(f"[NEWS v92] Hard skip deterministic report-like: {title}")
            mark_hard_skip(hard_skips, entry, "report_like", "deterministic", 0)
            continue

        local = local_pre_score_news(entry)
        local_score = int(local.get("score") or 0)
        if local.get("lane") == "hard_skip":
            log(f"[NEWS v92] Hard skip Fase A ({local_score}/100): {title} | {local.get('reason')}")
            mark_hard_skip(hard_skips, entry, str(local.get("reason") or "local_hard_skip"), "phase_a", local_score)
            continue
        if local.get("lane") == "low_soft":
            log(f"[NEWS v92] Low-soft Fase A ({local_score}/100): {title} | non mando a Gemini")
            low_item = build_news_candidate(
                entry,
                {"article_type": "soft_news", "priority": "soft", "category": news_category_for_entry(entry)[0], "story_core": slugify(title), "freshness": "fresh", "editorial_notes": "low_soft_phase_a"},
                max(40, min(local_score + 15, 49)),
                "soft",
                local,
            )
            store_soft_candidate(soft_pool, low_item, now)
            continue

        try:
            analysis = analyze_news_editorial(
                str(entry.get("title") or ""),
                str(entry.get("summary") or ""),
                str(entry.get("source") or ""),
                url,
                local_score,
                str(local.get("reason") or ""),
            )
        except Exception as exc:
            log(f"[NEWS v92] Analisi editoriale fallita, uso fallback locale: {title} | {exc}")
            analysis = {
                "article_type": "standard_useful" if local_score >= 50 else "soft_news",
                "priority": "soft",
                "category": news_category_for_entry(entry)[0],
                "main_entities": [],
                "story_core": slugify(title),
                "news_action": "local_fallback",
                "freshness": "fresh",
                "editorial_notes": "fallback_local_analysis",
            }

        article_type = str(analysis.get("article_type") or "low_value")
        final_score = score_editorial_analysis(entry, analysis, local_score)
        priority = priority_from_score(final_score, article_type)
        candidate = build_news_candidate(entry, analysis, final_score, priority, local)

        existing_duplicate = already_published_semantic_duplicate(candidate, published_urls)
        if existing_duplicate:
            log(f"[NEWS v92] Hard skip duplicato semantico gia pubblicato: {title} ~= {existing_duplicate.get('source_title')}")
            mark_hard_skip(hard_skips, entry, "semantic_duplicate_published", "phase_b", final_score)
            continue

        if article_type == "event_outcome" and (event_outcome_has_published_report(entry, analysis) or should_skip_event_after_published_report_strict(entry, analysis)):
            log(f"[NEWS v92] Hard skip event_outcome post-report ({final_score}/100): {title}")
            mark_hard_skip(hard_skips, entry, "event_outcome_after_report", "phase_b", final_score)
            continue

        if priority == "skip":
            log(f"[NEWS v92] Hard skip Fase B ({final_score}/100 {article_type}): {title} | {analysis.get('editorial_notes')}")
            mark_hard_skip(hard_skips, entry, f"phase_b_{article_type}", "phase_b", final_score)
            continue
        if priority == "hard":
            log(f"[NEWS v92] Hard news Fase B ({final_score}/100 {article_type}): {title}")
            hard_items.append(candidate)
        else:
            log(f"[NEWS v92] Soft pool Fase B ({final_score}/100 {article_type}): {title}")
            soft_items.append(candidate)
            store_soft_candidate(soft_pool, candidate, now)

    chosen, remaining_soft = select_news_final(hard_items, soft_items, MAX_NEWS_PER_RUN)
    chosen_urls = {str(x.get("url") or x.get("source_url") or "") for x in chosen}
    for item in remaining_soft:
        store_soft_candidate(soft_pool, item, now)
    for url in list(soft_pool.keys()):
        if url in chosen_urls or url in published_urls:
            soft_pool.pop(url, None)

    published = 0
    for entry in chosen:
        url = str(entry.get("url") or entry.get("source_url") or "")
        if not url or url in published_urls:
            continue
        key = f"news:{slugify(url)}"
        categories = final_news_categories_for_publish(entry)
        job = {
            "kind": "news",
            "news_key": key,
            "source": entry.get("source"),
            "source_url": url,
            "source_title": entry.get("title"),
            "categories": categories,
            "score": entry.get("score"),
            "priority": entry.get("priority"),
            "article_type": entry.get("article_type"),
            "story_core": entry.get("story_core"),
            "created_at": utcnow().isoformat(),
        }
        try:
            log(f"[NEWS v92] Pubblico {job['priority']} score={job['score']}/100 type={job['article_type']} source={job['source']} title={job['source_title']}")
            post_id, post_json = run_news_workshop(job, PUBLISHED_DIR, REVIEW_DIR)
            published_urls[url] = {
                "status": "published",
                "wp_post_id": post_id,
                "source": job["source"],
                "source_title": job["source_title"],
                "categories": categories,
                "score": job["score"],
                "priority": job["priority"],
                "article_type": job["article_type"],
                "story_core": job["story_core"],
                "published_at": utcnow().isoformat(),
                "link": post_json.get("link"),
            }
            soft_pool.pop(url, None)
            published += 1
        except Exception as exc:
            log(f"[NEWS v92] Errore pubblicazione news: {job['source_title']} | {exc}")
            pending.append({**job, "status": "failed_technical", "error": str(exc)[:1000]})
            continue

    save_json(PUBLISHED_NEWS_FILE, published_urls)
    save_json(NEWS_HARD_SKIPS_FILE, hard_skips)
    save_json(NEWS_SOFT_POOL_FILE, soft_pool)
    save_json(PENDING_NEWS_FILE, pending)
    log(f"[NEWS v92] Pubblicate news={published}/{MAX_NEWS_PER_RUN} | hard_candidates={len(hard_items)} soft_candidates={len(soft_items)} soft_pool_saved={len(soft_pool)}")
    return published


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
