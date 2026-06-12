#!/usr/bin/env python3
"""OpenWrestlingTV v94.4.2 - Wikipedia schedule table layer.

Read-only checker for curated Wikipedia upcoming-event tables.
It uses Wikipedia raw wikitext and reads only the configured upcoming section for
WWE/NXT, AEW, TNA, ROH and AAA, then compares extracted rows with
config/special_events.json. It never changes the registry.
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

SOURCES = [
    {"key":"wwe_nxt_wikipedia_schedule","promotion":"WWE","default_brand":"WWE","page":"List_of_WWE_pay-per-view_and_livestreaming_supercards","section_names":["Upcoming event schedule","Upcoming events"]},
    {"key":"aew_wikipedia_schedule","promotion":"AEW","default_brand":"AEW","page":"List_of_All_Elite_Wrestling_pay-per-view_events","section_names":["Upcoming events"]},
    {"key":"tna_wikipedia_schedule","promotion":"TNA","default_brand":"TNA","page":"List_of_TNA_pay-per-view_and_livestreaming_events","section_names":["Upcoming events"]},
    {"key":"roh_wikipedia_schedule","promotion":"ROH","default_brand":"ROH","page":"List_of_Ring_of_Honor_pay-per-view_and_livestreaming_events","section_names":["Upcoming","Upcoming events","Upcoming event schedule"]},
    {"key":"aaa_wikipedia_schedule","promotion":"AAA","default_brand":"AAA","page":"List_of_major_Lucha_Libre_AAA_Worldwide_events","section_names":["Upcoming event schedule","Upcoming events","Upcoming"]},
]

MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12,"jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,"sep":9,"sept":9,"oct":10,"nov":11,"dec":12}
SPACE_RE = re.compile(r"\s+")
HEADING_RE = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$", re.M)
MONTH_DAY_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?", re.I)
MONTH_RANGE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?\s*[–-]\s*(\d{1,2})(?:st|nd|rd|th)?", re.I)


def clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<ref[^>/]*/>", " ", text, flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", " | ", text, flags=re.I)
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"\[\[([^|\]]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[[^\] ]+\s+([^\]]+)\]", r"\1", text)
    text = re.sub(r"'''?", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[[0-9]+\]", "", text)
    return SPACE_RE.sub(" ", text).strip()


def fetch_raw(page: str) -> dict[str, Any]:
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page, safe="_()'-.!") + "?action=raw"
    req = urllib.request.Request(url, headers={"User-Agent":"OpenWrestlingTV-WikiScheduleRaw/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read(1800000).decode("utf-8", errors="replace")
            return {"ok": True, "status": f"http_{getattr(r,'status','?')}", "url": url, "text": text}
    except Exception as e:
        return {"ok": False, "status": f"fetch_error:{type(e).__name__}:{e}", "url": url, "text": ""}


def find_section(wikitext: str, names: list[str]) -> str:
    headings = list(HEADING_RE.finditer(wikitext))
    wanted = {n.lower() for n in names}
    for i, h in enumerate(headings):
        level = len(h.group(1)); title = clean(h.group(2)).lower()
        if title not in wanted:
            continue
        start = h.end(); end = len(wikitext)
        for nxt in headings[i+1:]:
            if len(nxt.group(1)) <= level:
                end = nxt.start(); break
        return wikitext[start:end]
    return ""


def extract_tables(section: str) -> list[str]:
    tables=[]; pos=0
    while True:
        start = section.find("{|", pos)
        if start < 0: break
        end = section.find("|}", start)
        if end < 0: break
        table = section[start:end+2]
        if "wikitable" in table.lower(): tables.append(table)
        pos = end + 2
    return tables


def split_rows(table: str) -> list[str]:
    if "\n|-" not in table: return []
    return re.split(r"\n\|-.*", table)[1:]


def split_cells(row: str) -> list[str]:
    cells=[]; current=[]
    for raw in row.splitlines():
        line = raw.strip()
        if not line: continue
        if line.startswith("|") or line.startswith("!"):
            marker=line[0]; content=line[1:].strip(); sep="!!" if marker=="!" else "||"
            if sep in content:
                if current: cells.append("\n".join(current)); current=[]
                cells.extend(part.strip() for part in content.split(sep)); continue
            if current: cells.append("\n".join(current))
            current=[content]
        elif current:
            current.append(line)
    if current: cells.append("\n".join(current))
    out=[]
    for c in cells:
        if "|" in c and re.search(r"(^|\s)(style|class|rowspan|colspan|scope|align)\s*=", c, re.I):
            c = c.split("|", 1)[1]
        out.append(clean(c))
    return out


def parse_headers(table: str) -> list[str]:
    for row in split_rows(table):
        if row.strip().startswith("!"):
            headers = [c.lower() for c in split_cells(row)]
            if "event" in headers and "date" in headers: return headers
    return []


def safe_iso(year: int, month: int, day: int) -> str | None:
    try: return date(year, month, day).isoformat()
    except ValueError: return None


def parse_date_cell(text: str, year: int) -> list[str]:
    text = clean(text).replace(",", " | ")
    out=[]
    for m in MONTH_RANGE_RE.finditer(text):
        month=MONTHS[m.group(1).lower()]
        for d in (int(m.group(2)), int(m.group(3))):
            iso=safe_iso(year, month, d)
            if iso: out.append(iso)
    for m in MONTH_DAY_RE.finditer(text):
        iso=safe_iso(year, MONTHS[m.group(1).lower()], int(m.group(2)))
        if iso: out.append(iso)
    return sorted(set(out))


def is_year_row(cells: list[str]) -> int | None:
    if len(cells)==1 and re.fullmatch(r"20\d{2}", cells[0]): return int(cells[0])
    return None


def infer_brand(source_key: str, default_brand: str, event_name: str, row_text: str) -> str:
    if source_key != "wwe_nxt_wikipedia_schedule": return default_brand
    low=(event_name+" "+row_text).lower()
    nxt_names={"the great american bash","heatwave","no mercy","halloween havoc","deadline","stand & deliver","stand and deliver"}
    return "NXT" if event_name.lower() in nxt_names or "nxt-branded" in low or "nxt " in low else default_brand


def aggregate(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged={}
    for ev in events:
        key=(ev["source_key"], ev["promotion"], ev["brand"], ev["event_name"], ev.get("venue",""), ev.get("location",""))
        if key not in merged:
            merged[key]=ev
        else:
            merged[key]["dates"] = sorted(set(merged[key]["dates"]) | set(ev["dates"]))
            if ev.get("notes") and ev["notes"] not in merged[key].get("notes",""):
                merged[key]["notes"] = (merged[key].get("notes","") + " | " + ev["notes"]).strip(" |")
    return list(merged.values())


def parse_table(table: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    headers=parse_headers(table)
    if not headers: return []
    idx={h:i for i,h in enumerate(headers)}; current_year=datetime.now(timezone.utc).year
    raw_events=[]; last_event=None
    for row in split_rows(table):
        cells=split_cells(row)
        if not cells: continue
        y=is_year_row(cells)
        if y: current_year=y; continue
        if len(cells) < 1: continue
        # Rows with fewer cells can happen because Wikipedia uses rowspan for multi-night events.
        date_i=idx.get("date"); event_i=idx.get("event")
        if date_i is None or event_i is None: continue
        date_cell = cells[date_i] if date_i < len(cells) else ""
        event_cell = cells[event_i] if event_i < len(cells) else ""
        dates=parse_date_cell(date_cell, current_year)
        if not dates: continue
        if event_cell:
            event_name=clean(event_cell)
            venue = cells[idx["venue"]] if "venue" in idx and idx["venue"] < len(cells) else ""
            location = cells[idx["location"]] if "location" in idx and idx["location"] < len(cells) else ""
            notes = cells[idx["notes"]] if "notes" in idx and idx["notes"] < len(cells) else ""
            last_event={"event_name":event_name,"venue":venue,"location":location,"notes":notes}
        elif last_event:
            event_name=last_event["event_name"]; venue=last_event.get("venue",""); location=last_event.get("location",""); notes=last_event.get("notes","")
        else:
            continue
        brand=infer_brand(source["key"], source["default_brand"], event_name, " ".join(cells))
        raw_events.append({"source_key":source["key"],"source_url":source["url"],"promotion":source["promotion"],"brand":brand,"event_name":event_name,"dates":dates,"venue":venue,"location":location,"notes":notes,"raw_date":date_cell})
    return aggregate(raw_events)


def score(ev: dict[str, Any], reg: dict[str, Any]) -> int:
    s=ev["event_name"].lower(); r=str(reg.get("event_name","")).lower(); aliases=[str(a).lower() for a in reg.get("aliases",[])]
    val = 100 if s==r or s in aliases else 60 if s in r or r in s or any(s in a or a in s for a in aliases) else 0
    if ev["promotion"] == reg.get("promotion"): val += 20
    if ev["brand"] in {reg.get("brand"), reg.get("category_hint")}: val += 10
    return val


def compare(ev: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    ranked=sorted(((score(ev,r),r) for r in registry.get("events",[])), key=lambda x:x[0], reverse=True)
    best_score,best=(ranked[0] if ranked else (0,{}))
    if best_score < 60: best={}
    reg_dates=[n.get("date_local") for n in best.get("nights",[]) if n.get("date_local")] if best else []
    matching=sorted(set(reg_dates)&set(ev["dates"])); new=sorted(set(ev["dates"])-set(reg_dates)); missing=sorted(set(reg_dates)-set(ev["dates"]))
    if not best: action="new_event_manual_review" if ev["promotion"]=="AAA" else "new_event_safe_to_review"
    elif matching and not new and not missing: action="no_action_if_dates_match"
    elif matching and missing and not new: action="partial_match_multi_night_review"
    elif best.get("status") in {"expected","proposed"} and ev["dates"]: action="safe_to_accept_after_review"
    else: action="manual_review_date_difference"
    return {"registry_event_key":best.get("key"),"registry_event_name":best.get("event_name"),"registry_status":best.get("status"),"match_score":best_score,"registry_dates":reg_dates,"schedule_dates":ev["dates"],"matching_dates":matching,"missing_registry_dates":missing,"new_candidate_dates":new,"recommended_action":action}


def build(registry: dict[str, Any]) -> dict[str, Any]:
    source_results=[]; events=[]
    for source in SOURCES:
        page=source["page"]; source["url"]="https://en.wikipedia.org/wiki/"+page
        fetched=fetch_raw(page)
        source_results.append({"source_key":source["key"],"promotion":source["promotion"],"ok":fetched["ok"],"status":fetched["status"],"chars":len(fetched.get("text","")),"url":source["url"],"sections":source["section_names"]})
        if not fetched["ok"]: continue
        section=find_section(fetched["text"], source["section_names"])
        if not section: continue
        for table in extract_tables(section):
            for ev in parse_table(table, source):
                ev["registry_comparison"]=compare(ev, registry); events.append(ev)
    return {"schema_version":"v94_wikipedia_schedule_layer_2_1","generated_at_utc":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"source_results":source_results,"events":events}


def render(payload: dict[str, Any]) -> str:
    lines=["# OpenWrestlingTV - Wikipedia schedule layer","",f"Generated UTC: {payload['generated_at_utc']}","","## Source check"]
    for s in payload["source_results"]:
        lines.append(f"- {'OK' if s['ok'] else 'FAIL'} | {s['source_key']} | {s['promotion']} | {s['status']} | chars={s['chars']} | sections={', '.join(s.get('sections') or [])} | {s['url']}")
    lines += ["","## Upcoming schedule extracted"]
    for ev in payload["events"]:
        c=ev["registry_comparison"]
        lines += [f"### {ev['promotion']} / {ev['brand']} - {ev['event_name']}",f"- source_dates: {', '.join(ev['dates'])}",f"- venue: {ev.get('venue') or '-'}",f"- location: {ev.get('location') or '-'}"]
        if ev.get("notes"): lines.append(f"- notes: {ev['notes']}")
        lines += [f"- registry_event: {c.get('registry_event_key') or 'not_found'}",f"- registry_status: {c.get('registry_status') or '-'}",f"- registry_dates: {', '.join(c.get('registry_dates') or []) or 'none'}",f"- matching_dates: {', '.join(c.get('matching_dates') or []) or 'none'}",f"- missing_registry_dates: {', '.join(c.get('missing_registry_dates') or []) or 'none'}",f"- new_candidate_dates: {', '.join(c.get('new_candidate_dates') or []) or 'none'}",f"- recommended_action: {c.get('recommended_action')}",""]
    return "\n".join(lines)


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--repo-dir",default=str(REPO_DIR)); ap.add_argument("--report-dir",default=str(REPORT_DIR)); args=ap.parse_args()
    repo=Path(args.repo_dir).resolve(); out=Path(args.report_dir).resolve(); registry=json.loads((repo/"config/special_events.json").read_text(encoding="utf-8"))
    payload=build(registry); out.mkdir(parents=True, exist_ok=True); stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    jp=out/f"special_events_wikipedia_schedule_layer_{stamp}.json"; mp=out/f"special_events_wikipedia_schedule_layer_{stamp}.md"
    jp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); mp.write_text(render(payload),encoding="utf-8")
    print(f"[WIKI SCHEDULE] events={len(payload['events'])}"); print(f"[WIKI SCHEDULE] json={jp}"); print(f"[WIKI SCHEDULE] report={mp}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
