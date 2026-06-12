#!/usr/bin/env python3
"""OpenWrestlingTV v94.1 - Special Events Registry refresh proposal generator.

This script is intentionally conservative:
- it reads config/special_events.json as the editorial source of truth;
- it reads config/special_event_sources.json as the list of sources to inspect;
- it fetches source pages without using AI;
- it does not modify the registry;
- it writes a JSON proposal file and a Markdown report for human review.

The first implementation is a safe scanner: it checks whether known event aliases appear
in configured source pages and extracts nearby date-like snippets. Human approval remains
required before any proposal becomes part of config/special_events.json.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = DEFAULT_REPO_DIR / "reports"

DATE_PATTERNS = [
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+\d{4}",
    r"\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}",
    r"\d{4}-\d{2}-\d{2}",
    r"\d{1,2}/\d{1,2}/\d{4}",
]
DATE_RE = re.compile("|".join(f"({p})" for p in DATE_PATTERNS), re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")

@dataclass
class FetchResult:
    ok: bool
    url: str
    status: str
    text: str = ""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(raw: str) -> str:
    raw = html.unescape(raw)
    raw = TAG_RE.sub(" ", raw)
    raw = SPACE_RE.sub(" ", raw)
    return raw.strip()


def fetch_url(url: str, timeout: int = 15) -> FetchResult:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OpenWrestlingTV-SpecialEventsRefresh/1.0 (+https://news.openwrestlingtv.com)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = getattr(resp, "status", "?")
            content_type = resp.headers.get("content-type", "")
            body = resp.read(750000)
            charset = "utf-8"
            m = re.search(r"charset=([^;]+)", content_type, re.I)
            if m:
                charset = m.group(1).strip()
            text = body.decode(charset, errors="replace")
            return FetchResult(True, url, f"http_{status_code}", normalize_text(text))
    except Exception as exc:  # noqa: BLE001 - report all fetch failures without crashing
        return FetchResult(False, url, f"fetch_error:{type(exc).__name__}:{exc}")


def event_aliases(event: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for value in [event.get("event_name"), *(event.get("aliases") or [])]:
        if isinstance(value, str) and value.strip():
            aliases.append(value.strip())
    # longer aliases first to reduce noisy matches
    return sorted(set(aliases), key=len, reverse=True)


def find_alias_context(text: str, alias: str, radius: int = 260) -> list[str]:
    contexts: list[str] = []
    pattern = re.compile(re.escape(alias), re.IGNORECASE)
    for match in pattern.finditer(text):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        snippet = text[start:end].strip()
        snippet = SPACE_RE.sub(" ", snippet)
        contexts.append(snippet)
        if len(contexts) >= 3:
            break
    return contexts


def extract_dates(snippet: str) -> list[str]:
    dates = []
    for match in DATE_RE.finditer(snippet):
        value = match.group(0)
        if value and value not in dates:
            dates.append(value)
    return dates[:5]


def build_proposals(registry: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
    generated_at = now_utc()
    enabled_sources = [s for s in sources.get("sources", []) if s.get("enabled")]
    source_results: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []

    fetched: dict[str, FetchResult] = {}
    for source in enabled_sources:
        url = source.get("url")
        if not url:
            continue
        result = fetch_url(url)
        fetched[source["key"]] = result
        source_results.append(
            {
                "source_key": source.get("key"),
                "promotion": source.get("promotion"),
                "url": url,
                "ok": result.ok,
                "status": result.status,
                "chars": len(result.text),
            }
        )

    events = registry.get("events", [])
    for event in events:
        event_status = event.get("status")
        aliases = event_aliases(event)
        if not aliases:
            continue

        matched_sources = []
        for source in enabled_sources:
            if event.get("promotion") and source.get("promotion") and event.get("promotion") != source.get("promotion"):
                # WWE source also covers NXT because promotion remains WWE.
                continue
            result = fetched.get(source["key"])
            if not result or not result.ok or not result.text:
                continue

            for alias in aliases:
                contexts = find_alias_context(result.text, alias)
                if not contexts:
                    continue
                dates = []
                for ctx in contexts:
                    for d in extract_dates(ctx):
                        if d not in dates:
                            dates.append(d)
                matched_sources.append(
                    {
                        "source_key": source.get("key"),
                        "source_url": source.get("url"),
                        "matched_alias": alias,
                        "dates_found_near_alias": dates,
                        "context_samples": contexts[:2],
                    }
                )
                break

        if not matched_sources:
            continue

        existing_nights = event.get("nights") or []
        proposal_type = "review_existing_event"
        confidence = "medium"
        reason = "Known event alias found in official/curated source page."

        if event_status in {"expected", "proposed"} and not existing_nights:
            proposal_type = "possible_date_confirmation"
            confidence = "medium"
            reason = "Expected event appears in a source page; check whether date/night should be added."
        elif event_status == "confirmed":
            proposal_type = "confirmed_event_seen_in_source"
            confidence = "low"
            reason = "Confirmed event appears in a source page; verify date consistency manually if needed."

        proposals.append(
            {
                "proposal_id": f"{event.get('key')}:review",
                "proposal_type": proposal_type,
                "confidence": confidence,
                "event_key": event.get("key"),
                "promotion": event.get("promotion"),
                "brand": event.get("brand"),
                "event_name": event.get("event_name"),
                "current_status": event_status,
                "existing_nights": existing_nights,
                "reason": reason,
                "matched_sources": matched_sources[:5],
                "recommended_action": "manual_review",
            }
        )

    return {
        "schema_version": "v94_special_event_proposals_1",
        "generated_at_utc": generated_at,
        "registry_schema_version": registry.get("schema_version"),
        "source_schema_version": sources.get("schema_version"),
        "policy": {
            "auto_apply": False,
            "human_approval_required": True,
            "safe_behavior": "This file is informational. It does not change config/special_events.json.",
        },
        "source_results": source_results,
        "proposals": proposals,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# OpenWrestlingTV - Special Events Registry Refresh")
    lines.append("")
    lines.append(f"Generated UTC: {payload.get('generated_at_utc')}")
    lines.append("")
    lines.append("## Source check")
    for src in payload.get("source_results", []):
        status = "OK" if src.get("ok") else "FAIL"
        lines.append(f"- {status} | {src.get('source_key')} | {src.get('promotion')} | {src.get('status')} | chars={src.get('chars')} | {src.get('url')}")
    lines.append("")

    proposals = payload.get("proposals", [])
    lines.append("## Proposals")
    lines.append(f"Total proposals: {len(proposals)}")
    lines.append("")
    if not proposals:
        lines.append("No event proposal generated. This can be normal if source pages are dynamic or no known aliases were found.")
        lines.append("")
    for idx, prop in enumerate(proposals, 1):
        lines.append(f"### [{idx}] {prop.get('promotion')} - {prop.get('event_name')}")
        lines.append(f"- event_key: `{prop.get('event_key')}`")
        lines.append(f"- type: {prop.get('proposal_type')}")
        lines.append(f"- current_status: {prop.get('current_status')}")
        lines.append(f"- confidence: {prop.get('confidence')}")
        lines.append(f"- recommended_action: {prop.get('recommended_action')}")
        if prop.get("existing_nights"):
            lines.append("- existing_nights:")
            for n in prop.get("existing_nights", []):
                lines.append(f"  - {n.get('label')} | {n.get('date_local')} | {n.get('night_key')}")
        lines.append("- matched_sources:")
        for ms in prop.get("matched_sources", []):
            dates = ", ".join(ms.get("dates_found_near_alias") or []) or "no date extracted"
            lines.append(f"  - {ms.get('source_key')} | alias='{ms.get('matched_alias')}' | dates: {dates}")
        lines.append("")

    lines.append("## Approval policy")
    lines.append("- This report does not update the registry automatically.")
    lines.append("- To approve proposals, update `config/special_events.json` via GitHub/Codex/manual commit.")
    lines.append("- The VPS should remain a runtime machine unless a later PR-based approval flow is explicitly enabled.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-dir", default=str(DEFAULT_REPO_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--registry", default="config/special_events.json")
    parser.add_argument("--sources", default="config/special_event_sources.json")
    args = parser.parse_args(argv)

    repo_dir = Path(args.repo_dir).resolve()
    report_dir = Path(args.report_dir).resolve()
    registry_path = repo_dir / args.registry
    sources_path = repo_dir / args.sources

    registry = load_json(registry_path)
    sources = load_json(sources_path)
    payload = build_proposals(registry, sources)

    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    json_path = report_dir / f"special_events_proposals_{stamp}.json"
    md_path = report_dir / f"special_events_refresh_{stamp}.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(payload), encoding="utf-8")

    print(f"[SPECIAL EVENTS] proposals={len(payload.get('proposals', []))}")
    print(f"[SPECIAL EVENTS] json={json_path}")
    print(f"[SPECIAL EVENTS] report={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
