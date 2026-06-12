#!/usr/bin/env python3
"""OpenWrestlingTV v94.4 - Wikipedia schedule table layer.

Reads curated Wikipedia list pages for WWE/NXT, AEW, TNA, ROH and AAA.
Extracts upcoming/future event tables and compares them with config/special_events.json.
Read-only: it writes Markdown/JSON reports and never changes the registry.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_DIR / "reports"

SOURCES = [
    {
        "key": "wwe_nxt_wikipedia_schedule",
        "promotion": "WWE",
        "url": "https://en.wikipedia.org/wiki/List_of_WWE_pay-per-view_and_livestreaming_supercards",
        "section_markers": ["Upcoming event schedule", "Upcoming events"],
        "default_brand": "WWE",
    },
    {
        "key": "aew_wikipedia_schedule",
        "promotion": "AEW",
        "url": "https://en.wikipedia.org/wiki/List_of_All_Elite_Wrestling_pay-per-view_events",
        "section_markers": ["Upcoming events", "Upcoming event schedule"],
        "default_brand": "AEW",
    },
    {
        "key": "tna_wikipedia_schedule",
        "promotion": "TNA",
        "url": "https://en.wikipedia.org/wiki/List_of_TNA_pay-per-view_and_livestreaming_events",
        "section_markers": ["Upcoming events", "Upcoming event schedule"],
        "default_brand": "TNA",
    },
    {
        "key": "roh_wikipedia_schedule",
        "promotion": "ROH",
        "url": "https://en.wikipedia.org/wiki/List_of_Ring_of_Honor_pay-per-view_and_livestreaming_events",
        "section_markers": ["Upcoming events", "Upcoming event schedule"],
        "default_brand": "ROH",
    },
    {
        "key": "aaa_wikipedia_schedule",
        "promotion": "AAA",
        "url": "https://en.wikipedia.org/wiki/List_of_major_Lucha_Libre_AAA_Worldwide_events",
        "section_markers": ["Upcoming events", "Upcoming event schedule"],
        "default_brand": "AAA",
    },
]

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")


def clean_text(s: str) -> str:
    s = html.unescape(s or "")
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"\[[^\]]+\]", "", s)
    return SPACE_RE.sub(" ", s).strip()


def fetch(url: str, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenWrestlingTV-WikiScheduleLayer/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(1800000).decode("utf-8", errors="replace")
            return {"ok": True, "status": f"http_{getattr(resp, 'status', '?')}", "url": url, "raw": raw, "text": clean_text(raw)}
    except Exception as exc:
        return {"ok": False, "status": f"fetch_error:{type(exc).__name__}:{exc}", "url": url, "raw": "", "text": ""}


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.table_depth = 0
        self.current_row: list[dict[str, str]] = []
        self.rows: list[list[dict[str, str]]] = []
        self.cell_text: list[str] = []
        self.cell_attrs: dict[str, str] = {}
        self.cell_tag = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k: v or "" for k, v in attrs}
        if tag == "table":
            if not self.in_table:
                classes = d.get("class", "")
                if "wikitable" in classes:
                    self.in_table = True
                    self.table_depth = 1
            elif self.in_table:
                self.table_depth += 1
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
        elif self.in_table and self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.cell_tag = tag
            self.cell_attrs = d
            self.cell_text = []
        elif self.in_cell and tag == "br":
            self.cell_text.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if self.in_cell and tag in {"td", "th"}:
            txt = clean_text("".join(self.cell_text))
            self.current_row.append({"tag": self.cell_tag, "text": txt, "style": self.cell_attrs.get("style", ""), "class": self.cell_attrs.get("class", "")})
            self.in_cell = False
        elif self.in_table and tag == "tr":
            if self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False
        elif self.in_table and tag == "table":
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.in_table = False

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text.append(data)


def extract_relevant_html(raw: str, markers: list[str]) -> str:
    low = raw.lower()
    starts = [low.find(m.lower()) for m in markers]
    starts = [s for s in starts if s >= 0]
    if not starts:
        return raw
    start = min(starts)
    # stop near next major section after upcoming tables, but keep enough page if headings are complex
    return raw[start:start + 180000]


def parse_tables(raw: str, markers: list[str]) -> list[list[dict[str, str]]]:
    part = extract_relevant_html(raw, markers)
    p = TableParser()
    p.feed(part)
    return p.rows


def parse_date_cell(text: str, year: int) -> list[str]:
    text = clean_text(text)
    out: list[str] = []
    # examples: June 27, August 1 | August 2, July 26, August 30
    for piece in re.split(r"\||/|;", text):
        piece = piece.strip()
        m = re.match(r"^(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?$", piece, re.I)
        if m:
            out.append(date(year, MONTHS[m.group(1).lower()], int(m.group(2))).isoformat())
            continue
        m = re.match(r"^(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?\s*[–-]\s*(\d{1,2})(?:st|nd|rd|th)?$", piece, re.I)
        if m:
            month = MONTHS[m.group(1).lower()]
            out.append(date(year, month, int(m.group(2))).isoformat())
            out.append(date(year, month, int(m.group(3))).isoformat())
    return sorted(set(out))


def row_is_nxt(cells: list[dict[str, str]], source: dict[str, Any], event_name: str) -> bool:
    if source["key"] != "wwe_nxt_wikipedia_schedule":
        return False
    joined = " ".join((c.get("style", "") + " " + c.get("class", "") + " " + c.get("text", "")) for c in cells).lower()
    if "nxt" in joined or "background" in joined and ("ffff" in joined or "yellow" in joined):
        return True
    nxt_names = {"the great american bash", "heatwave", "no mercy", "halloween havoc", "deadline", "stand & deliver", "stand and deliver"}
    return event_name.lower() in nxt_names


def normalize_event_name(name: str) -> str:
    return clean_text(name).replace("TNA+", "TNA+").strip()


def parse_rows_for_source(source: dict[str, Any], rows: list[list[dict[str, str]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current_year = datetime.now().year
    headers: list[str] = []
    for row in rows:
        texts = [c["text"] for c in row]
        if len(texts) == 1 and re.fullmatch(r"20\d{2}", texts[0]):
            current_year = int(texts[0])
            continue
        if row and all(c.get("tag") == "th" for c in row):
            headers = [t.lower() for t in texts]
            continue
        if len(row) < 2:
            continue
        if not headers or len(headers) != len(row):
            # common defaults by source/table order
            if source["key"] == "aew_wikipedia_schedule":
                headers = ["event", "date", "location", "venue", "main event", "notes"][:len(row)]
            elif source["key"] == "tna_wikipedia_schedule":
                headers = ["date", "event", "venue", "location", "main event", "notes"][:len(row)]
            else:
                headers = ["date", "event", "venue", "location", "notes"][:len(row)]
        data = {headers[i]: row[i]["text"] for i in range(min(len(headers), len(row)))}
        date_text = data.get("date", "")
        event_name = normalize_event_name(data.get("event", ""))
        if not event_name or not date_text:
            continue
        dates = parse_date_cell(date_text, current_year)
        if not dates:
            continue
        brand = "NXT" if row_is_nxt(row, source, event_name) else source.get("default_brand", source["promotion"])
        events.append({
            "source_key": source["key"],
            "promotion": source["promotion"],
            "brand": brand,
            "event_name": event_name,
            "dates": dates,
            "venue": data.get("venue", ""),
            "location": data.get("location", ""),
            "notes": data.get("notes", ""),
            "raw_date": date_text,
            "source_url": source["url"],
        })
    return events


def registry_index(registry: dict[str, Any]) -> list[dict[str, Any]]:
    return registry.get("events", []) or []


def score_match(schedule_event: dict[str, Any], reg_event: dict[str, Any]) -> int:
    sname = schedule_event["event_name"].lower()
    rname = str(reg_event.get("event_name", "")).lower()
    aliases = [str(a).lower() for a in reg_event.get("aliases", [])]
    score = 0
    if sname == rname or sname in aliases:
        score += 100
    elif sname in rname or rname in sname or any(sname in a or a in sname for a in aliases):
        score += 60
    if schedule_event["promotion"] == reg_event.get("promotion"):
        score += 20
    if schedule_event["brand"] == reg_event.get("brand") or schedule_event["brand"] == reg_event.get("category_hint"):
        score += 10
    return score


def compare_with_registry(schedule_event: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    candidates = sorted(((score_match(schedule_event, e), e) for e in registry_index(registry)), key=lambda x: x[0], reverse=True)
    best_score, best = candidates[0] if candidates else (0, {})
    if best_score < 60:
        best = {}
    reg_dates = [n.get("date_local") for n in best.get("nights", []) if n.get("date_local")] if best else []
    schedule_dates = schedule_event["dates"]
    matching = sorted(set(reg_dates) & set(schedule_dates))
    new_dates = sorted(set(schedule_dates) - set(reg_dates))
    if not best:
        action = "new_event_manual_review" if schedule_event["promotion"] == "AAA" else "new_event_safe_to_review"
    elif matching and not new_dates:
        action = "no_action_if_dates_match"
    elif best.get("status") in {"expected", "proposed"} and schedule_dates:
        action = "safe_to_accept_after_review"
    else:
        action = "manual_review_date_difference"
    return {
        "registry_event_key": best.get("key"),
        "registry_event_name": best.get("event_name"),
        "registry_status": best.get("status"),
        "match_score": best_score,
        "registry_dates": reg_dates,
        "schedule_dates": schedule_dates,
        "matching_dates": matching,
        "new_candidate_dates": new_dates,
        "recommended_action": action,
    }


def build_report(registry: dict[str, Any]) -> dict[str, Any]:
    source_results = []
    rows = []
    for source in SOURCES:
        fetched = fetch(source["url"])
        source_results.append({"source_key": source["key"], "promotion": source["promotion"], "ok": fetched["ok"], "status": fetched["status"], "chars": len(fetched.get("text", "")), "url": source["url"]})
        if not fetched["ok"]:
            continue
        parsed_rows = parse_tables(fetched["raw"], source["section_markers"])
        for ev in parse_rows_for_source(source, parsed_rows):
            ev["registry_comparison"] = compare_with_registry(ev, registry)
            rows.append(ev)
    return {"schema_version": "v94_wikipedia_schedule_layer_1", "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "source_results": source_results, "events": rows}


def render(payload: dict[str, Any]) -> str:
    lines = ["# OpenWrestlingTV - Wikipedia schedule layer", "", f"Generated UTC: {payload['generated_at_utc']}", ""]
    lines.append("## Source check")
    for s in payload["source_results"]:
        lines.append(f"- {'OK' if s['ok'] else 'FAIL'} | {s['source_key']} | {s['promotion']} | {s['status']} | chars={s['chars']} | {s['url']}")
    lines.append("")
    lines.append("## Upcoming schedule extracted")
    for ev in payload["events"]:
        c = ev["registry_comparison"]
        lines.append(f"### {ev['promotion']} / {ev['brand']} - {ev['event_name']}")
        lines.append(f"- source_dates: {', '.join(ev['dates'])}")
        lines.append(f"- venue: {ev.get('venue') or '-'}")
        lines.append(f"- location: {ev.get('location') or '-'}")
        if ev.get("notes"):
            lines.append(f"- notes: {ev['notes']}")
        lines.append(f"- registry_event: {c.get('registry_event_key') or 'not_found'}")
        lines.append(f"- registry_status: {c.get('registry_status') or '-'}")
        lines.append(f"- registry_dates: {', '.join(c.get('registry_dates') or []) or 'none'}")
        lines.append(f"- matching_dates: {', '.join(c.get('matching_dates') or []) or 'none'}")
        lines.append(f"- new_candidate_dates: {', '.join(c.get('new_candidate_dates') or []) or 'none'}")
        lines.append(f"- recommended_action: {c.get('recommended_action')}")
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
    payload = build_report(registry)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    json_path = report_dir / f"special_events_wikipedia_schedule_layer_{stamp}.json"
    md_path = report_dir / f"special_events_wikipedia_schedule_layer_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render(payload), encoding="utf-8")
    print(f"[WIKI SCHEDULE] events={len(payload['events'])}")
    print(f"[WIKI SCHEDULE] json={json_path}")
    print(f"[WIKI SCHEDULE] report={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
