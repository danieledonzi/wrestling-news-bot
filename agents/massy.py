from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    import feedparser  # type: ignore
except Exception:  # pragma: no cover - workflow installs feedparser
    feedparser = None

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
STATE_DIR = ROOT / "state"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"
FEEDS_CONFIG = CONFIG_DIR / "feeds_v92.json"

MASSY_VERSION = "v93_9_massy_published_hard_skip"

TRACKED_STATE_FILES = [
    STATE_DIR / "report_status.json",
    STATE_DIR / "manual_runs.json",
    STATE_DIR / "pending_reports.json",
    STATE_DIR / "pending_news.json",
]
PUBLISHED_HISTORY_FILES = [
    NEWSROOM_STATE_DIR / "publisher_history.json",
    NEWSROOM_STATE_DIR / "publisher_status_latest.json",
]

LOW_VALUE_PATTERNS = [
    (re.compile(r"\b\d+\s+things\s+(we\s+)?(hated|loved|learned)\b", re.I), "listicle_things_we_loved_hated"),
    (re.compile(r"\b(things\s+we\s+hated|things\s+we\s+loved)\b", re.I), "listicle_things_we_loved_hated"),
    (re.compile(r"\b(draws\s*(?:and|&)\s*duds|duds\s*(?:and|&)\s*draws)\b", re.I), "draws_and_duds_listicle"),
    (re.compile(r"\bpreview\b.*\b(start\s*time|how\s+to\s+watch|confirmed\s+matches)\b", re.I), "generic_show_preview"),
    (re.compile(r"\b(start\s*time|how\s+to\s+watch)\b.*\bpreview\b", re.I), "generic_show_preview"),
]

REPORT_SHOW_PATTERNS = [
    (re.compile(r"\bwwe\s+raw\b|\braw\b", re.I), "WWE Raw"),
    (re.compile(r"\bwwe\s+nxt\b|\bnxt\b", re.I), "WWE NXT"),
    (re.compile(r"\bsmackdown\b|\bsmack\s*down\b", re.I), "WWE SmackDown"),
    (re.compile(r"\baew\s+dynamite\b|\bdynamite\b", re.I), "AEW Dynamite"),
    (re.compile(r"\baew\s+collision\b|\bcollision\b", re.I), "AEW Collision"),
    (re.compile(r"\btna\s+impact\b|\bimpact\b", re.I), "TNA Impact"),
]

SPECIAL_EVENT_PATTERNS = [
    (re.compile(r"\bwrestlemania\b|\broyal\s+rumble\b|\bsummerslam\b|\bsurvivor\s+series\b|\bmoney\s+in\s+the\s+bank\b|\bnight\s+of\s+champions\b|\bclash\b", re.I), "WWE PLE"),
    (re.compile(r"\bdouble\s+or\s+nothing\b|\ball\s+out\b|\bfull\s+gear\b|\brevolution\b|\bforbidden\s+door\b|\bwrestledream\b|\bworlds\s+end\b", re.I), "AEW PPV"),
    (re.compile(r"\broh\b.*\b(final\s+battle|death\s+before\s+dishonor|supercard\s+of\s+honor)\b|\b(final\s+battle|death\s+before\s+dishonor|supercard\s+of\s+honor)\b", re.I), "ROH PPV"),
]


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


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        path = re.sub(r"/+$", "", parts.path or "/")
        query_items = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
        return urlunsplit((scheme, netloc, path, urlencode(query_items, doseq=True), ""))
    except Exception:
        return raw.rstrip("/")


def normalize_text(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_entry(entry: dict[str, Any], decision: str, reason: str, **extra: Any) -> dict[str, Any]:
    data = {
        "decision": decision,
        "reason": reason,
        "source": entry.get("source", ""),
        "feed_url": entry.get("feed_url", ""),
        "title": entry.get("title", ""),
        "url": entry.get("url", ""),
        "normalized_url": entry.get("normalized_url", ""),
        "published": entry.get("published", ""),
        "summary": entry.get("summary", ""),
    }
    data.update(extra)
    return data


def collect_urls(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and "url" in str(key).lower():
                normalized = normalize_url(item)
                if normalized:
                    found.add(normalized)
            collect_urls(item, found)
    elif isinstance(value, list):
        for item in value:
            collect_urls(item, found)


def worked_urls() -> set[str]:
    found: set[str] = set()
    for path in TRACKED_STATE_FILES:
        collect_urls(load_json(path, {}), found)
    return found


def published_urls() -> set[str]:
    found: set[str] = set()
    for path in PUBLISHED_HISTORY_FILES:
        collect_urls(load_json(path, {}), found)
    return found


def read_feeds_config() -> list[dict[str, Any]]:
    cfg = load_json(FEEDS_CONFIG, {"feeds": []})
    feeds = cfg.get("feeds", []) if isinstance(cfg, dict) else []
    return [feed for feed in feeds if isinstance(feed, dict) and feed.get("url")]


def read_feed_entries(feeds: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if feedparser is None:
        return entries, [{"error": "feedparser_not_available"}]
    for feed in feeds:
        feed_url = str(feed.get("url") or "")
        source = str(feed.get("id") or feed.get("name") or feed_url)
        try:
            parsed = feedparser.parse(feed_url)
            for raw in parsed.entries:
                url = getattr(raw, "link", "") or ""
                entries.append({
                    "source": source,
                    "feed_url": feed_url,
                    "title": getattr(raw, "title", "") or "",
                    "url": url,
                    "normalized_url": normalize_url(url),
                    "published": getattr(raw, "published", "") or getattr(raw, "updated", "") or "",
                    "summary": getattr(raw, "summary", "") or "",
                })
        except Exception as exc:
            errors.append({"feed_url": feed_url, "source": source, "error": str(exc)})
    return entries, errors


def low_value_reason(entry: dict[str, Any]) -> str | None:
    title = entry.get("title", "") or ""
    for pattern, reason in LOW_VALUE_PATTERNS:
        if pattern.search(title):
            return reason
    return None


def report_hint(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    blob = f"{entry.get('title', '')} {entry.get('url', '')}"
    normalized = normalize_text(blob)
    if not ("results" in normalized or "risultati" in normalized or "highlights" in normalized):
        return None, None
    for pattern, show_name in REPORT_SHOW_PATTERNS:
        if pattern.search(blob):
            return show_name, "weekly_show_results"
    for pattern, event_name in SPECIAL_EVENT_PATTERNS:
        if pattern.search(blob):
            return event_name, "special_event_results"
    return None, None


def classify_entries(entries: list[dict[str, Any]], already_worked_urls: set[str], already_published_urls: set[str]) -> dict[str, Any]:
    seen_scan: set[str] = set()
    already_worked: list[dict[str, Any]] = []
    hard_skipped: list[dict[str, Any]] = []
    report_candidates: list[dict[str, Any]] = []
    news_candidates: list[dict[str, Any]] = []

    for entry in entries:
        normalized = entry.get("normalized_url") or normalize_url(entry.get("url", ""))
        entry["normalized_url"] = normalized
        if not normalized:
            hard_skipped.append(compact_entry(entry, "hard_skip", "missing_url"))
            continue
        if normalized in seen_scan:
            hard_skipped.append(compact_entry(entry, "hard_skip", "duplicate_in_feed_scan"))
            continue
        seen_scan.add(normalized)
        if normalized in already_published_urls:
            hard_skipped.append(compact_entry(entry, "hard_skip", "url_already_published", published_guard="publisher_history"))
            continue
        if normalized in already_worked_urls:
            already_worked.append(compact_entry(entry, "already_worked", "url_present_in_state"))
            continue
        lv_reason = low_value_reason(entry)
        if lv_reason:
            hard_skipped.append(compact_entry(entry, "hard_skip", lv_reason))
            continue
        show_hint, report_reason = report_hint(entry)
        if show_hint:
            report_candidates.append(compact_entry(entry, "report_candidate", report_reason or "report_like_title", assigned_to="Simone", show_hint=show_hint))
            continue
        news_candidates.append(compact_entry(entry, "news_candidate", "requires_menzo_classification", assigned_to="Menzo"))

    return {"already_worked": already_worked, "hard_skipped": hard_skipped, "report_candidates": report_candidates, "news_candidates_for_menzo": news_candidates}


def run_massy() -> dict[str, Any]:
    feeds = read_feeds_config()
    print(f"[MASSY v93.9] Avvio sentinella feed | feeds={len(feeds)}", flush=True)
    entries, feed_errors = read_feed_entries(feeds)
    known_urls = worked_urls()
    published = published_urls()
    classified = classify_entries(entries, known_urls, published)
    board = {
        "agent": "Massy",
        "version": MASSY_VERSION,
        "generated_at": utc_now(),
        "mode": "sentinel_control_board",
        "binding": {
            "hard_skips_are_binding_for_newsroom": True,
            "published_urls_are_hard_skips": True,
            "bot_v92_runtime_still_delegated_until_menzo_simone_takeover": False,
        },
        "feeds": feeds,
        "feed_errors": feed_errors,
        "found_urls": len(entries),
        "known_state_urls": len(known_urls),
        "known_published_urls": len(published),
        **classified,
        "handoff": {
            "to_simone": len(classified["report_candidates"]),
            "to_menzo": len(classified["news_candidates_for_menzo"]),
            "already_worked": len(classified["already_worked"]),
            "hard_skipped": len(classified["hard_skipped"]),
            "already_published_hard_skipped": sum(1 for x in classified["hard_skipped"] if x.get("reason") == "url_already_published"),
        },
    }
    write_json(ARTIFACT_DIR / "massy_board.json", board)
    write_json(NEWSROOM_STATE_DIR / "massy_board_latest.json", board)
    print(
        "[MASSY v93.9] Board pronta | "
        f"found={board['found_urls']} to_simone={board['handoff']['to_simone']} "
        f"to_menzo={board['handoff']['to_menzo']} hard_skip={board['handoff']['hard_skipped']} "
        f"published_skip={board['handoff']['already_published_hard_skipped']} already={board['handoff']['already_worked']}",
        flush=True,
    )
    return board


if __name__ == "__main__":
    result = run_massy()
    print(json.dumps(result.get("handoff", {}), ensure_ascii=False, indent=2))
