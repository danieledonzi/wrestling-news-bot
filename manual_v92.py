from __future__ import annotations

import json
import os
import re
import socket
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from modules.report_workshop_v92 import run_report_workshop

ROOT = Path(__file__).resolve().parent
PUBLISHED_DIR = ROOT / "published"
REVIEW_DIR = ROOT / "published_html_review"
LOG_DIR = ROOT / "logs"
STATE_DIR = ROOT / "state"
MASTER_LOG = LOG_DIR / "master_log.log"
BOT_EXIT_CODE = ROOT / ".bot_exit_code"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}


def ensure_dirs() -> None:
    for path in [PUBLISHED_DIR, REVIEW_DIR, LOG_DIR, STATE_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def log(message: str) -> None:
    ensure_dirs()
    print(message, flush=True)
    with MASTER_LOG.open("a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")


def wp_root_from_env() -> str:
    raw = os.getenv("WP_URL", "").strip().rstrip("/")
    if not raw:
        return ""
    if "/wp-json" in raw:
        raw = raw.split("/wp-json", 1)[0].rstrip("/")
    return raw


def log_dns_diagnostics(root: str) -> None:
    try:
        host = urlparse(root).netloc
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        log(f"[MANUAL v92] DNS {host}: {', '.join(ips) if ips else 'nessun IP'}")
    except Exception as exc:
        log(f"[MANUAL v92] DNS diagnostic fallita: {exc}")


def probe_endpoint(endpoint: str, timeout: int, use_auth: bool = False) -> Tuple[bool, str]:
    start = time.monotonic()
    try:
        kwargs = {"headers": HEADERS, "timeout": timeout}
        if use_auth:
            kwargs["auth"] = (os.getenv("WP_USER", ""), os.getenv("WP_PASSWORD", ""))
        res = requests.get(endpoint, **kwargs)
        elapsed = time.monotonic() - start
        log(f"[MANUAL v92] WP probe status={res.status_code} elapsed={elapsed:.2f}s endpoint={endpoint}")
        if res.status_code in {200, 401, 403}:
            return True, f"status_{res.status_code}"
        return False, f"status_{res.status_code}"
    except Exception as exc:
        elapsed = time.monotonic() - start
        log(f"[MANUAL v92] WP probe timeout/errore elapsed={elapsed:.2f}s endpoint={endpoint}: {exc}")
        return False, "wp_error"


def manual_wp_health_check() -> Tuple[bool, str]:
    root = wp_root_from_env()
    if not root:
        return False, "missing_wp_url"

    timeout = int(os.getenv("V92_WP_HEALTH_TIMEOUT", "10"))
    retries = int(os.getenv("V92_WP_HEALTH_RETRIES", "2"))
    log_dns_diagnostics(root)

    endpoints = [
        (f"{root}/", False, "home"),
        (f"{root}/wp-json/", False, "rest_root"),
        (f"{root}/wp-json/wp/v2/posts?per_page=1", True, "posts_auth"),
    ]

    last_status = "wp_unavailable"
    for attempt in range(1, retries + 1):
        log(f"[MANUAL v92] WP health check attempt {attempt}/{retries} timeout={timeout}s")
        for endpoint, use_auth, label in endpoints:
            ok, status = probe_endpoint(endpoint, timeout=timeout, use_auth=use_auth)
            last_status = status
            if ok and label in {"rest_root", "posts_auth"}:
                log(f"[MANUAL v92] WP health check OK label={label} status={status} | tentativo {attempt}/{retries}")
                return True, status
    return False, last_status


def slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:120] or "manual"


def domain_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "ringsidenews.com" in host:
        return "ringsidenews"
    if "wrestlinginc.com" in host:
        return "wrestlinginc"
    if "fightful.com" in host:
        return "fightful"
    return host.replace("www.", "") or "manual"


def fetch_source_title(url: str) -> str:
    try:
        res = requests.get(url, headers=HEADERS, timeout=12)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        for selector in ["meta[property='og:title']", "meta[name='twitter:title']"]:
            tag = soup.select_one(selector)
            if tag and tag.get("content"):
                return tag["content"].strip()
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(" ", strip=True)
    except Exception as exc:
        log(f"[MANUAL v92] Warning: impossibile leggere titolo sorgente: {exc}")
    return url


def parse_categories(raw: str, default: List[str]) -> List[str]:
    if not raw.strip():
        return default
    out = [x.strip() for x in raw.split(",") if x.strip()]
    return out or default


def read_manual_html() -> str:
    raw_path = os.getenv("V92_MANUAL_HTML_PATH", "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / raw_path
    if not path.exists():
        raise SystemExit(f"[MANUAL v92] V92_MANUAL_HTML_PATH non trovato: {path}")
    html = path.read_text(encoding="utf-8", errors="ignore")
    log(f"[MANUAL v92] HTML grezzo caricato: {path} chars={len(html)}")
    return html


def build_manual_report_job(url: str) -> Dict[str, object]:
    title = os.getenv("V92_MANUAL_TITLE", "").strip()
    source_title = fetch_source_title(url)
    source = domain_source(url)
    if not title:
        title = source_title
    categories = parse_categories(os.getenv("V92_MANUAL_CATEGORIES", ""), ["Editoriali"])
    now = datetime.utcnow().isoformat()
    job: Dict[str, object] = {
        "kind": "report",
        "report_key": f"manual_report_{slugify(title)}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        "report_id": "manual_report",
        "source": source,
        "source_url": url,
        "source_title": source_title,
        "title": title,
        "date": datetime.utcnow().date().isoformat(),
        "categories": categories,
        "title_policy": "manual" if os.getenv("V92_MANUAL_TITLE", "").strip() else "source_title",
        "translation_mode": "report",
        "created_at": now,
        "status": "manual_ready_to_publish",
    }
    source_html = read_manual_html()
    if source_html:
        job["source_html"] = source_html
        job["source_html_mode"] = "manual_raw_html"
    return job


def run_manual_report(url: str) -> int:
    wp_ok, wp_status = manual_wp_health_check()
    log(f"[MANUAL v92] wp_ok={wp_ok} wp_status={wp_status}")
    if not wp_ok:
        log("[MANUAL v92] WordPress non disponibile: interrompo prima di scrape/traduzione")
        return 0

    job = build_manual_report_job(url)
    log(f"[MANUAL v92] Avvio manual report url={url}")
    log(f"[MANUAL v92] source={job['source']} source_title={job['source_title']}")
    log(f"[MANUAL v92] title={job['title']}")
    log(f"[MANUAL v92] categories={', '.join(job['categories'])}")
    if job.get("source_html_mode"):
        log(f"[MANUAL v92] source_html_mode={job['source_html_mode']}")
    post_id, post_json = run_report_workshop(job, PUBLISHED_DIR, REVIEW_DIR)
    state_file = STATE_DIR / "manual_runs.json"
    try:
        data = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else []
    except Exception:
        data = []
    data.append({"job": {k: v for k, v in job.items() if k != "source_html"}, "wp_post_id": post_id, "link": post_json.get("link"), "created_at": datetime.utcnow().isoformat()})
    state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"[MANUAL v92] Pubblicato post_id={post_id} link={post_json.get('link')}")
    return 0


def main() -> int:
    ensure_dirs()
    url = os.getenv("V92_MANUAL_URL", "").strip()
    kind = os.getenv("V92_MANUAL_KIND", "").strip().lower()
    if not url:
        log("[MANUAL v92] Nessun V92_MANUAL_URL: skip")
        return 0
    if kind not in {"report", "news"}:
        raise SystemExit("V92_MANUAL_KIND deve essere 'report' oppure 'news'")
    if kind == "news":
        raise SystemExit("[MANUAL v92] manual news non ancora attivo: prima completiamo news_pipeline v92")
    return run_manual_report(url)


if __name__ == "__main__":
    code = main()
    BOT_EXIT_CODE.write_text(str(code), encoding="utf-8")
    raise SystemExit(code)
