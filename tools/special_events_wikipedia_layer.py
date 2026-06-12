#!/usr/bin/env python3
"""OpenWrestlingTV v94.3 - Wikipedia detail layer for special events.

This is a separate, read-only helper.
It reads config/special_events.json, checks likely Wikipedia pages for the events
already present in the registry, extracts future dates, and writes a Markdown/JSON
report. It does not change the registry.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_DIR / "reports"

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
DATE_RE = re.compile(
    r"(?:\d{4}-\d{2}-\d{2})|"
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})|"
    r"(?:\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4})",
    re.I,
)
RANGE_RE = re.compile(
    r"(?P<m1>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
    r"(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s*[–-]\s*(?:(?P<m2>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+)?"
    r"(?P<d2>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})",
    re.I,
)


def clean_text(raw: str) -> str:
    raw = html.unescape(raw or "")
    raw = TAG_RE.sub(" ", raw)
    return SPACE_RE.sub(" ", raw).strip()


def page_title(raw: str) -> str:
    m = TITLE_RE.search(raw or "")
    return clean_text(m.group(1)).replace(" - Wikipedia", "").strip() if m else ""


def fetch(url: str, timeout: int = 15) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenWrestlingTV-WikipediaLayer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(1200000)
            raw = body.decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status": f"http_{getattr(resp, 'status', '?')}",
                "url": url,
                "final_url": getattr(resp, "url", url),
                "title": page_title(raw),
                "text": clean_text(raw),
            }
    except Exception as exc:
        return {"ok": False, "status": f"fetch_error:{type(exc).__name__}:{exc}", "url": url}


def parse_one_date(raw: str) -> str | None:
    raw = raw.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return m.group(1)
    clean = raw.replace(",", " ")
    clean = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", clean, flags=re.I)
    parts = SPACE_RE.sub(" ", clean).strip().split(" ")
    try:
        if len(parts) >= 3 and parts[0].lower() in MONTHS:
            return date(int(parts[2]), MONTHS[parts[0].lower()], int(parts[1])).isoformat()
        if len(parts) >= 3 and parts[1].lower() in MONTHS:
            return date(int(parts[2]), MONTHS[parts[1].lower()], int(parts[0])).isoformat()
    except Exception:
        return None
    return None


def extract_dates(text: str) -> list[dict[str, str]]:
    today = datetime.now(timezone.utc).date()
    out: list[dict[str, str]] = []
    seen = set()

    for m in RANGE_RE.finditer(text):
        try:
            y = int(m.group("y"))
            m1 = MONTHS[m.group("m1").lower()]
            m2 = MONTHS[(m.group("m2") or m.group("m1")).lower()]
            for mm, dd in [(m1, int(m.group("d1"))), (m2, int(m.group("d2")) )]:
                iso = date(y, mm, dd).isoformat()
                if datetime.strptime(iso, "%Y-%m-%d").date() < today:
                    continue
                key = (m.group(0), iso)
                if key not in seen:
                    seen.add(key)
                    out.append({"raw": m.group(0), "iso": iso})
        except Exception:
            pass

    for m in DATE_RE.finditer(text):
        iso = parse_one_date(m.group(0))
        if not iso:
            continue
        if datetime.strptime(iso, "%Y-%m-%d").date() < today:
            continue
        key = (m.group(0), iso)
        if key not in seen:
            seen.add(key)
            out.append({"raw": m.group(0), "iso": iso})
    return out[:10]


def wiki_title_candidates(event: dict[str, Any]) -> list[str]:
    name = str(event.get("event_name") or "").strip()
    if not name:
        return []
    years: list[int] = []
    for n in event.get("nights") or []:
        d = str(n.get("date_local") or "")
        if re.match(r"^\d{4}-", d):
            years.append(int(d[:4]))
    if not years:
        years = [datetime.now(timezone.utc).year, datetime.now(timezone.utc).year + 1]
    titles: list[str] = []
    for year in sorted(set(years)):
        for t in [f"{name} ({year})", f"{year} {name}", name]:
            if t not in titles:
                titles.append(t)
    return titles


def wiki_url(title: str) -> str:
    safe = urllib.parse.quote(title.replace(" ", "_"), safe="_()'-.!")
    return f"https://en.wikipedia.org/wiki/{safe}"


def valid_wiki_page(result: dict[str, Any], title: str, event_name: str) -> bool:
    if not result.get("ok"):
        return False
    text = str(result.get("text") or "")
    low = text[:6000].lower()
    if "wikipedia does not have an article with this exact name" in low:
        return False
    if "may refer to:" in low[:1200]:
        return False
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", event_name) if len(w) > 2]
    return any(w in low for w in words)


def existing_dates(event: dict[str, Any]) -> list[str]:
    return [str(n.get("date_local")) for n in event.get("nights") or [] if n.get("date_local")]


def inspect_event(event: dict[str, Any]) -> dict[str, Any]:
    tried = []
    found = None
    for title in wiki_title_candidates(event):
        url = wiki_url(title)
        res = fetch(url)
        tried.append({"title": title, "url": url, "status": res.get("status"), "page_title": res.get("title")})
        if not valid_wiki_page(res, title, str(event.get("event_name") or "")):
            continue
        dates = extract_dates(str(res.get("text") or "")[:20000])
        if dates:
            found = {"title": title, "url": url, "page_title": res.get("title"), "dates": dates}
            break

    reg_dates = existing_dates(event)
    wiki_dates = sorted({d["iso"] for d in (found or {}).get("dates", [])})
    return {
        "event_key": event.get("key"),
        "promotion": event.get("promotion"),
        "brand": event.get("brand"),
        "event_name": event.get("event_name"),
        "status": event.get("status"),
        "registry_dates": reg_dates,
        "wikipedia_found": bool(found),
        "wikipedia_page": found,
        "wikipedia_dates": wiki_dates,
        "matching_dates": sorted(set(reg_dates) & set(wiki_dates)),
        "new_candidate_dates": sorted(set(wiki_dates) - set(reg_dates)),
        "tried": tried[:6],
    }


def render(items: list[dict[str, Any]], generated_at: str) -> str:
    lines = ["# OpenWrestlingTV - Wikipedia special events layer", "", f"Generated UTC: {generated_at}", ""]
    lines.append("## Summary")
    lines.append(f"- Events checked: {len(items)}")
    lines.append(f"- Wikipedia pages with dates: {sum(1 for x in items if x['wikipedia_found'])}")
    lines.append(f"- Registry/date matches: {sum(1 for x in items if x['matching_dates'])}")
    lines.append(f"- New candidate dates: {sum(1 for x in items if x['new_candidate_dates'])}")
    lines.append("")
    lines.append("## Details")
    for x in items:
        lines.append(f"### {x['promotion']} - {x['event_name']}")
        lines.append(f"- event_key: `{x['event_key']}`")
        lines.append(f"- status: {x['status']}")
        lines.append(f"- registry_dates: {', '.join(x['registry_dates']) or 'none'}")
        lines.append(f"- wikipedia_found: {x['wikipedia_found']}")
        lines.append(f"- wikipedia_dates: {', '.join(x['wikipedia_dates']) or 'none'}")
        lines.append(f"- matching_dates: {', '.join(x['matching_dates']) or 'none'}")
        lines.append(f"- new_candidate_dates: {', '.join(x['new_candidate_dates']) or 'none'}")
        if x.get("wikipedia_page"):
            p = x["wikipedia_page"]
            lines.append(f"- page: {p.get('page_title')} | {p.get('url')}")
        else:
            tried = "; ".join(t.get("title", "") for t in x.get("tried", [])[:3])
            lines.append(f"- tried: {tried}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir", default=str(REPO_DIR))
    ap.add_argument("--report-dir", default=str(REPORT_DIR))
    args = ap.parse_args()
    repo_dir = Path(args.repo_dir).resolve()
    report_dir = Path(args.report_dir).resolve()
    registry = json.loads((repo_dir / "config/special_events.json").read_text(encoding="utf-8"))
    items = [inspect_event(e) for e in registry.get("events", [])]
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    json_path = report_dir / f"special_events_wikipedia_layer_{stamp}.json"
    md_path = report_dir / f"special_events_wikipedia_layer_{stamp}.md"
    payload = {"schema_version": "v94_wikipedia_layer_1", "generated_at_utc": generated_at, "items": items}
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render(items, generated_at), encoding="utf-8")
    print(f"[WIKI LAYER] checked={len(items)}")
    print(f"[WIKI LAYER] with_dates={sum(1 for x in items if x['wikipedia_found'])}")
    print(f"[WIKI LAYER] json={json_path}")
    print(f"[WIKI LAYER] report={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
