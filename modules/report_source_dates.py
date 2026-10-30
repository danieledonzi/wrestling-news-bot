"""Bound undated weekly fallback reports to retained evidence from their article."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from modules.simone_report_integrity import (
    candidate_date_evidence, is_canonical_report_source, normalize_url,
    report_source_name, FALLBACK_REPORT_SOURCE,
)

CACHE_DIR = Path(__file__).resolve().parents[1] / "state/newsroom/report_source_dates_v1"
VERSION = "article-show-date-v1"
RETRY_SECONDS = 600
MAX_PAGE_BYTES = 2_000_000
NOISE = "aside,nav,footer,.related,.related-posts,.td_block_related_posts,.comments-area,.wp-block-query,blockquote.twitter-tweet"
PREVIEW = re.compile(r"\b(next week|last week|previous|preview|prediction|will face|will air|upcoming|returns? on)\b", re.I)


def _show_label(text: str, report: dict[str, Any]) -> bool:
    name = re.sub(r"[^a-z0-9]+", " ", str(report.get("show_name") or "").lower()).strip()
    label = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return bool(name and re.search(r"\b" + re.escape(name) + r"\b", label))


def page_date_evidence(page: str, report: dict[str, Any], date_iso: str) -> dict[str, Any]:
    """Only article report labels or two distinct, concordant dated show videos."""
    soup = BeautifulSoup(page, "html.parser")
    content = soup.select_one("article .entry-content, .entry-content, article .article-content")
    if content is None:
        return {"matches": False, "reason": "source_show_date_unverified", "observations": []}
    for node in list(content.select(NOISE)):
        node.decompose()
    observations = []
    headers = []
    for node in content.find_all(["h1", "h2", "h3", "p"], limit=8):
        text = node.get_text(" ", strip=True)
        if len(text) > 220 or PREVIEW.search(text) or not _show_label(text, report):
            continue
        # A label begins with the show identity; an arbitrary dated sentence does not.
        normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        name = re.sub(r"[^a-z0-9]+", " ", str(report.get("show_name") or "").lower()).strip()
        if not normalized.startswith(name + " "):
            continue
        dates = candidate_date_evidence({"source_title": text}, date_iso)["explicit_content_dates"]
        if dates:
            headers.append(set(dates))
            observations.append({"kind": "article_report_label", "text": text, "dates": sorted(dates)})
    if headers:
        dates = set().union(*headers)
        return {"matches": dates == {date_iso},
                "reason": "source_show_date_verified" if dates == {date_iso} else "source_show_date_conflict",
                "observations": observations}
    videos = {}
    for node in content.select("iframe[src][title]"):
        video = urlsplit(str(node.get("src")))
        if video.hostname not in {"youtube.com", "www.youtube.com", "www.youtube-nocookie.com"}:
            continue
        if not re.fullmatch(r"/embed/[A-Za-z0-9_-]+", video.path):
            continue
        text = str(node.get("title") or "")
        if PREVIEW.search(text) or not _show_label(text, report):
            continue
        dates = candidate_date_evidence({"source_title": text}, date_iso)["explicit_content_dates"]
        if dates:
            dates = set(dates) | set(videos.get(video.path, {}).get("dates", []))
            videos[video.path] = {"kind": "article_show_video", "text": text, "dates": sorted(dates), "video": video.path}
    observations.extend(videos.values())
    dates = {date for row in videos.values() for date in row["dates"]}
    matched = len(videos) >= 2 and dates == {date_iso}
    conflict = bool(dates and dates != {date_iso})
    return {"matches": matched,
            "reason": "source_show_date_verified" if matched else "source_show_date_conflict" if conflict else "source_show_date_unverified",
            "observations": observations}


def report_page_date(candidate: dict[str, Any], report: dict[str, Any], date_iso: str,
                     *, allow_fetch: bool = False) -> dict[str, Any]:
    """Persistent URL/show/date-bound snapshots; no provider calls, no feed-date inference."""
    missing = {"matches": False, "reason": "source_show_date_unverified", "observations": []}
    if (report_source_name(candidate) != FALLBACK_REPORT_SOURCE
            or not is_canonical_report_source(candidate) or not report.get("show_name")):
        return missing
    explicit = candidate_date_evidence(candidate, date_iso)["explicit_content_dates"]
    if explicit:  # Never repair a conflicting explicit source date with page material.
        return missing
    url = normalize_url(str(candidate.get("url") or candidate.get("source_url") or ""))
    binding = {"url": url, "show": report["show_name"], "date": date_iso, "version": VERSION}
    key = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    record_path = CACHE_DIR / (key + ".json")
    now = datetime.now(timezone.utc).timestamp()
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("binding") == binding:
            digest = str(record.get("content_sha256") or "")
            if record.get("matches") and re.fullmatch(r"[0-9a-f]{64}", digest):
                page = (CACHE_DIR / (digest + ".html")).read_bytes().decode("utf-8")
                if hashlib.sha256(page.encode()).hexdigest() == digest:
                    return {**page_date_evidence(page, report, date_iso), **binding, "content_sha256": digest}
            if not record.get("matches") and 0 <= now - float(record.get("checked_at", 0)) < RETRY_SECONDS:
                return {**missing, "reason": record.get("reason", missing["reason"])}
    except (OSError, ValueError, TypeError):
        pass
    if not allow_fetch:
        return missing
    response = None
    try:
        fetch_url = str(candidate.get("url") or candidate.get("source_url") or "")
        for _redirect in range(3):
            response = requests.get(fetch_url, timeout=8, stream=True, allow_redirects=False,
                                    headers={"User-Agent": "OpenWrestlingTV-report-date/1.0"})
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            target = urljoin(fetch_url, response.headers.get("Location", ""))
            # Only canonical spelling redirects (for example the final slash),
            # never a different article, host or a downgrade.
            if urlsplit(target).scheme != "https" or normalize_url(target) != url:
                raise ValueError("source_redirect_changed_identity")
            response.close()
            fetch_url = target
        if response.status_code != 200:
            raise ValueError("source_http_status")
        chunks = []
        size = 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_PAGE_BYTES:
                raise ValueError("source_page_too_large")
            chunks.append(chunk)
        page = b"".join(chunks).decode("utf-8", errors="replace")
        digest = hashlib.sha256(page.encode()).hexdigest()
        evidence = page_date_evidence(page, report, date_iso)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        snapshot = CACHE_DIR / (digest + ".html")
        if not snapshot.exists():
            snapshot.write_bytes(page.encode("utf-8"))
        evidence = {**evidence, **binding, "content_sha256": digest}
        record = {**evidence, "binding": binding, "checked_at": now}
    except (requests.RequestException, OSError, ValueError):
        record = {**missing, "reason": "source_show_date_fetch_failed", "binding": binding, "checked_at": now}
        evidence = {**missing, "reason": record["reason"]}
    finally:
        if response is not None:
            response.close()
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        temp = record_path.with_suffix(".tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temp.replace(record_path)
    except OSError:
        # A reservation cannot rely on proof that will be lost on the next run.
        return {**missing, "reason": "source_show_date_persistence_failed"}
    return evidence
