#!/usr/bin/env python3
"""OpenWrestlingTV v94.2 - Special Events Registry refresh proposal generator.

Conservative refresh tool:
- reads config/special_events.json as the editorial source of truth;
- reads config/special_event_sources.json as official/curated sources;
- fetches source pages without AI;
- never modifies the registry;
- writes JSON and Markdown proposal reports for human review.

v94.2 improves date detection by keeping raw HTML, scanning wider alias contexts,
parsing ISO datetimes and English dates, extracting structured JSON-LD / embedded
JSON snippets, and comparing detected future dates with existing registry nights.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = DEFAULT_REPO_DIR / "reports"

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

DATE_PATTERNS = [
    r"\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?",
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}",
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}",
    r"\d{1,2}/\d{1,2}/\d{4}",
]
DATE_RE = re.compile("|".join(f"({p})" for p in DATE_PATTERNS), re.IGNORECASE)
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_JSON_RE = re.compile(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.I | re.S)
NEXT_DATA_RE = re.compile(r"<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>", re.I | re.S)


@dataclass
class FetchResult:
    ok: bool
    url: str
    status: str
    text: str = ""
    raw_html: str = ""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


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
            "User-Agent": "OpenWrestlingTV-SpecialEventsRefresh/1.1 (+https://news.openwrestlingtv.com)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status_code = getattr(resp, "status", "?")
            content_type = resp.headers.get("content-type", "")
            body = resp.read(1500000)
            charset = "utf-8"
            m = re.search(r"charset=([^;]+)", content_type, re.I)
            if m:
                charset = m.group(1).strip()
            raw = body.decode(charset, errors="replace")
            return FetchResult(True, url, f"http_{status_code}", normalize_text(raw), raw)
    except Exception as exc:
        return FetchResult(False, url, f"fetch_error:{type(exc).__name__}:{exc}")


def event_aliases(event: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for value in [event.get("event_name"), *(event.get("aliases") or [])]:
        if isinstance(value, str) and value.strip():
            aliases.append(value.strip())
    return sorted(set(aliases), key=len, reverse=True)


def parse_date(value: str) -> str | None:
    raw = value.strip()
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"

    clean = raw.replace(",", " ")
    clean = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", clean, flags=re.I)
    clean = SPACE_RE.sub(" ", clean).strip()
    parts = clean.split(" ")
    try:
        if len(parts) >= 3 and parts[0].lower() in MONTHS:
            return date(int(parts[2]), MONTHS[parts[0].lower()], int(parts[1])).isoformat()
        if len(parts) >= 3 and parts[1].lower() in MONTHS:
            return date(int(parts[2]), MONTHS[parts[1].lower()], int(parts[0])).isoformat()
    except Exception:
        return None

    for fmt in ("%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except Exception:
            pass
    return None


def extract_date_candidates(snippet: str, only_future: bool = True) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen = set()
    today = today_utc()
    for match in DATE_RE.finditer(snippet):
        raw = match.group(0).strip()
        iso = parse_date(raw)
        if not iso:
            continue
        try:
            parsed = datetime.strptime(iso, "%Y-%m-%d").date()
        except Exception:
            continue
        if only_future and parsed < today:
            continue
        key = (raw, iso)
        if key in seen:
            continue
        seen.add(key)
        out.append({"raw": raw, "iso": iso})
    return out[:12]


def find_alias_context(text: str, alias: str, radius: int = 1000) -> list[str]:
    contexts: list[str] = []
    pattern = re.compile(re.escape(alias), re.I)
    for match in pattern.finditer(text):
        start = max(0, match.start() - radius)
        end = min(len(text), match.end() + radius)
        contexts.append(SPACE_RE.sub(" ", text[start:end].strip()))
        if len(contexts) >= 4:
            break
    return contexts


def safe_json_loads(text: str) -> Any | None:
    try:
        return json.loads(html.unescape(text).strip())
    except Exception:
        return None


def walk_json_records(obj: Any, source: str = "json", limit: int = 800) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def walk(x: Any) -> None:
        if len(records) >= limit:
            return
        if isinstance(x, dict):
            name_bits, date_bits, url_bits = [], [], []
            for key, value in x.items():
                lk = str(key).lower()
                if isinstance(value, (str, int, float)):
                    sv = str(value)
                    if lk in {"name", "title", "headline", "eventname"}:
                        name_bits.append(sv)
                    if lk in {"startdate", "enddate", "date", "datetime", "eventdate"} or "date" in lk:
                        date_bits.append(sv)
                    if lk in {"url", "link"}:
                        url_bits.append(sv)
            if name_bits or date_bits:
                records.append({
                    "source": source,
                    "name": " | ".join(name_bits),
                    "date_values": date_bits,
                    "url_values": url_bits,
                    "text": " ".join(name_bits + date_bits + url_bits),
                })
            for value in x.values():
                walk(value)
        elif isinstance(x, list):
            for value in x:
                walk(value)

    walk(obj)
    return records


def extract_structured_records(raw_html: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for match in SCRIPT_JSON_RE.finditer(raw_html):
        parsed = safe_json_loads(match.group(1))
        if parsed is not None:
            records.extend(walk_json_records(parsed, source="json_ld"))

    next_match = NEXT_DATA_RE.search(raw_html)
    if next_match:
        parsed = safe_json_loads(next_match.group(1))
        if parsed is not None:
            records.extend(walk_json_records(parsed, source="next_data", limit=1400))

    for match in re.finditer(r'"(?:name|title|headline)"\s*:\s*"([^"]{3,180})"', raw_html, re.I):
        start = max(0, match.start() - 900)
        end = min(len(raw_html), match.end() + 1100)
        snippet = html.unescape(raw_html[start:end])
        dates = extract_date_candidates(snippet, only_future=True)
        if dates:
            records.append({
                "source": "embedded_json_snippet",
                "name": match.group(1),
                "date_values": [d["raw"] for d in dates],
                "url_values": [],
                "text": normalize_text(snippet),
            })
        if len(records) >= 1200:
            break
    return records[:1200]


def source_matches_event(source: dict[str, Any], event: dict[str, Any]) -> bool:
    src = str(source.get("promotion") or "").strip()
    promo = str(event.get("promotion") or "").strip()
    if not src or src in {"*", "ALL", "ANY"}:
        return True
    if not promo:
        return True
    return src == promo


def collect_source_match(source: dict[str, Any], result: FetchResult, aliases: list[str]) -> dict[str, Any] | None:
    records = extract_structured_records(result.raw_html)
    structured_hits: list[dict[str, Any]] = []
    text_hits: list[dict[str, Any]] = []

    for alias in aliases:
        alias_re = re.compile(re.escape(alias), re.I)
        for record in records:
            hay = " ".join([
                str(record.get("name") or ""),
                str(record.get("text") or ""),
                " ".join(str(x) for x in record.get("date_values") or []),
                " ".join(str(x) for x in record.get("url_values") or []),
            ])
            if not alias_re.search(hay):
                continue
            dates = extract_date_candidates(" ".join(str(x) for x in record.get("date_values") or []) + " " + hay)
            structured_hits.append({
                "matched_alias": alias,
                "record_source": record.get("source"),
                "record_name": record.get("name"),
                "date_candidates": dates,
                "url_values": record.get("url_values") or [],
            })
            if len(structured_hits) >= 4:
                break
        if structured_hits:
            break

    for alias in aliases:
        contexts = find_alias_context(result.text, alias)
        if not contexts:
            continue
        dates: list[dict[str, str]] = []
        for ctx in contexts:
            for d in extract_date_candidates(ctx):
                if d not in dates:
                    dates.append(d)
        text_hits.append({"matched_alias": alias, "date_candidates": dates, "context_samples": contexts[:2]})
        break

    if not structured_hits and not text_hits:
        return None

    all_dates: list[dict[str, str]] = []
    for hit in structured_hits + text_hits:
        for d in hit.get("date_candidates") or []:
            if d not in all_dates:
                all_dates.append(d)

    return {
        "source_key": source.get("key"),
        "source_url": source.get("url"),
        "trust_level": source.get("trust_level"),
        "structured_hits": structured_hits[:4],
        "text_hits": text_hits[:2],
        "date_candidates": all_dates[:12],
    }


def existing_night_dates(event: dict[str, Any]) -> list[str]:
    dates = []
    for night in event.get("nights") or []:
        value = night.get("date_local")
        if isinstance(value, str) and value:
            dates.append(value)
    return dates


def compare_detected_dates(existing: list[str], candidates: list[dict[str, str]]) -> dict[str, Any]:
    detected = sorted({d["iso"] for d in candidates if d.get("iso")})
    existing_set = set(existing)
    detected_set = set(detected)
    return {
        "existing_dates": existing,
        "detected_dates": detected,
        "matching_dates": sorted(existing_set & detected_set),
        "new_candidate_dates": sorted(detected_set - existing_set),
        "missing_existing_dates_in_sources": sorted(existing_set - detected_set) if detected else [],
    }


def build_proposals(registry: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
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
        source_results.append({
            "source_key": source.get("key"),
            "promotion": source.get("promotion"),
            "trust_level": source.get("trust_level"),
            "url": url,
            "ok": result.ok,
            "status": result.status,
            "chars": len(result.text),
        })

    for event in registry.get("events", []):
        aliases = event_aliases(event)
        if not aliases:
            continue
        matched_sources = []
        for source in enabled_sources:
            if not source_matches_event(source, event):
                continue
            result = fetched.get(source["key"])
            if not result or not result.ok or not result.text:
                continue
            match = collect_source_match(source, result, aliases)
            if match:
                matched_sources.append(match)
        if not matched_sources:
            continue

        existing_nights = event.get("nights") or []
        existing_dates = existing_night_dates(event)
        all_candidates: list[dict[str, str]] = []
        for match in matched_sources:
            for d in match.get("date_candidates") or []:
                if d not in all_candidates:
                    all_candidates.append(d)
        comparison = compare_detected_dates(existing_dates, all_candidates)

        status = event.get("status")
        high_trust_match = any(m.get("trust_level") == "high" for m in matched_sources) and bool(comparison["matching_dates"])
        high_trust_new = any(m.get("trust_level") == "high" for m in matched_sources) and bool(comparison["new_candidate_dates"])

        if status in {"expected", "proposed"} and not existing_nights:
            proposal_type = "possible_date_confirmation"
            confidence = "high" if high_trust_new else "medium"
            action = "approve_after_human_date_check"
            reason = "Expected event appears in a source page; check whether date/night should be added."
        elif status == "confirmed":
            proposal_type = "confirmed_event_seen_in_source"
            confidence = "high" if high_trust_match else "medium"
            action = "no_action_if_dates_match" if high_trust_match and not comparison["new_candidate_dates"] else "manual_review"
            reason = "Confirmed event appears in source page; verify date consistency if candidates differ."
        else:
            proposal_type = "review_existing_event"
            confidence = "medium"
            action = "manual_review"
            reason = "Known event alias found in official/curated source page."

        proposals.append({
            "proposal_id": f"{event.get('key')}:review",
            "proposal_type": proposal_type,
            "confidence": confidence,
            "event_key": event.get("key"),
            "promotion": event.get("promotion"),
            "brand": event.get("brand"),
            "event_name": event.get("event_name"),
            "current_status": status,
            "existing_nights": existing_nights,
            "date_comparison": comparison,
            "reason": reason,
            "matched_sources": matched_sources[:6],
            "recommended_action": action,
        })

    return {
        "schema_version": "v94_special_event_proposals_2",
        "generated_at_utc": now_utc(),
        "registry_schema_version": registry.get("schema_version"),
        "source_schema_version": sources.get("schema_version"),
        "policy": {
            "auto_apply": False,
            "human_approval_required": True,
            "safe_behavior": "This file is informational. It does not change config/special_events.json.",
            "auto_approval_threshold_future": "Only consider after repeated high-trust official/Wikipedia date agreement.",
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
        lines.append(f"- {status} | {src.get('source_key')} | {src.get('promotion')} | trust={src.get('trust_level')} | {src.get('status')} | chars={src.get('chars')} | {src.get('url')}")
    lines.append("")

    proposals = payload.get("proposals", [])
    lines.append("## Proposals")
    lines.append(f"Total proposals: {len(proposals)}")
    lines.append("")
    if not proposals:
        lines.append("No event proposal generated. This can be normal if source pages are dynamic or no known aliases were found.")
        lines.append("")
    for idx, prop in enumerate(proposals, 1):
        comp = prop.get("date_comparison") or {}
        lines.append(f"### [{idx}] {prop.get('promotion')} - {prop.get('event_name')}")
        lines.append(f"- event_key: `{prop.get('event_key')}`")
        lines.append(f"- type: {prop.get('proposal_type')}")
        lines.append(f"- current_status: {prop.get('current_status')}")
        lines.append(f"- confidence: {prop.get('confidence')}")
        lines.append(f"- recommended_action: {prop.get('recommended_action')}")
        lines.append(f"- existing_dates: {', '.join(comp.get('existing_dates') or []) or 'none'}")
        lines.append(f"- detected_dates: {', '.join(comp.get('detected_dates') or []) or 'none'}")
        lines.append(f"- matching_dates: {', '.join(comp.get('matching_dates') or []) or 'none'}")
        lines.append(f"- new_candidate_dates: {', '.join(comp.get('new_candidate_dates') or []) or 'none'}")
        if prop.get("existing_nights"):
            lines.append("- existing_nights:")
            for n in prop.get("existing_nights", []):
                lines.append(f"  - {n.get('label')} | {n.get('date_local')} | {n.get('night_key')}")
        lines.append("- matched_sources:")
        for ms in prop.get("matched_sources", []):
            source_dates = ", ".join(d.get("iso") for d in (ms.get("date_candidates") or []) if d.get("iso")) or "no date extracted"
            lines.append(f"  - {ms.get('source_key')} | trust={ms.get('trust_level')} | dates: {source_dates}")
            for hit in ms.get("structured_hits") or []:
                hit_dates = ", ".join(d.get("iso") for d in (hit.get("date_candidates") or []) if d.get("iso")) or "no date"
                name = (hit.get("record_name") or "").strip()
                if len(name) > 120:
                    name = name[:117] + "..."
                lines.append(f"    - structured:{hit.get('record_source')} | alias='{hit.get('matched_alias')}' | dates: {hit_dates} | name='{name}'")
            for hit in ms.get("text_hits") or []:
                hit_dates = ", ".join(d.get("iso") for d in (hit.get("date_candidates") or []) if d.get("iso")) or "no date"
                lines.append(f"    - text | alias='{hit.get('matched_alias')}' | dates: {hit_dates}")
        lines.append("")

    lines.append("## Approval policy")
    lines.append("- This report does not update the registry automatically.")
    lines.append("- Dates detected from high-trust official sources or curated Wikipedia pages can be considered near-approvable after human review.")
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
    registry = load_json(repo_dir / args.registry)
    sources = load_json(repo_dir / args.sources)
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
