#!/usr/bin/env python3
from __future__ import annotations

import argparse, html, json, re, urllib.parse, urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_DIR / "reports"
SOURCES = [
    {"key":"wwe_nxt_wikipedia_schedule","promotion":"WWE","brand":"WWE","page":"List_of_WWE_pay-per-view_and_livestreaming_supercards","sections":["Upcoming event schedule","Upcoming events"]},
    {"key":"aew_wikipedia_schedule","promotion":"AEW","brand":"AEW","page":"List_of_All_Elite_Wrestling_pay-per-view_events","sections":["Upcoming events"]},
    {"key":"tna_wikipedia_schedule","promotion":"TNA","brand":"TNA","page":"List_of_TNA_pay-per-view_and_livestreaming_events","sections":["Upcoming events"]},
    {"key":"roh_wikipedia_schedule","promotion":"ROH","brand":"ROH","page":"List_of_Ring_of_Honor_pay-per-view_and_livestreaming_events","sections":["Upcoming","Upcoming events","Upcoming event schedule"]},
    {"key":"aaa_wikipedia_schedule","promotion":"AAA","brand":"AAA","page":"List_of_major_Lucha_Libre_AAA_Worldwide_events","sections":["Upcoming event schedule","Upcoming events","Upcoming"]},
]
MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12,"jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,"sep":9,"sept":9,"oct":10,"nov":11,"dec":12}
SPACE_RE = re.compile(r"\s+")
HEADING_RE = re.compile(r"^(=+)\s*(.*?)\s*\1\s*$", re.M)
MDAY_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?", re.I)
MRANGE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?\s*[--]\s*(\d{1,2})(?:st|nd|rd|th)?", re.I)
ATTR_RE = re.compile(r"(^|\s)(style|class|rowspan|colspan|scope|align|width)\s*=", re.I)


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
    req = urllib.request.Request(url, headers={"User-Agent":"OpenWrestlingTV-WikiScheduleRaw/1.3"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"ok": True, "status": f"http_{getattr(r,'status','?')}", "url": url, "text": r.read(1800000).decode("utf-8", errors="replace")}
    except Exception as e:
        return {"ok": False, "status": f"fetch_error:{type(e).__name__}:{e}", "url": url, "text": ""}


def find_section(text: str, names: list[str]) -> str:
    headings = list(HEADING_RE.finditer(text)); wanted={n.lower() for n in names}
    for i,h in enumerate(headings):
        level=len(h.group(1)); title=clean(h.group(2)).lower()
        if title not in wanted: continue
        start=h.end(); end=len(text)
        for nxt in headings[i+1:]:
            if len(nxt.group(1)) <= level:
                end=nxt.start(); break
        return text[start:end]
    return ""


def extract_tables(section: str) -> list[str]:
    out=[]; pos=0
    while True:
        start=section.find("{|", pos)
        if start < 0: break
        end=section.find("|}", start)
        if end < 0: break
        table=section[start:end+2]
        if "wikitable" in table.lower(): out.append(table)
        pos=end+2
    return out


def split_rows(table: str) -> list[str]:
    return re.split(r"\n\|-.*", table)[1:] if "\n|-" in table else []


def split_cells(row: str) -> list[str]:
    cells=[]; cur=[]
    for raw in row.splitlines():
        line=raw.strip()
        if not line: continue
        if line.startswith("|") or line.startswith("!"):
            marker=line[0]; content=line[1:].strip(); sep="!!" if marker=="!" else "||"
            if sep in content:
                if cur: cells.append("\n".join(cur)); cur=[]
                cells.extend(part.strip() for part in content.split(sep)); continue
            if cur: cells.append("\n".join(cur))
            cur=[content]
        elif cur:
            cur.append(line)
    if cur: cells.append("\n".join(cur))
    out=[]
    for c in cells:
        if "|" in c and ATTR_RE.search(c): c=c.split("|",1)[1]
        out.append(clean(c))
    return out


def parse_headers(table: str) -> list[str]:
    blocks=[]
    if "\n|-" in table: blocks.append(table.split("\n|-",1)[0])
    blocks.extend(split_rows(table))
    for row in blocks:
        if row.strip().startswith("!") or "\n!" in row:
            headers=[c.lower() for c in split_cells(row)]
            if "event" in headers and "date" in headers: return headers
    return []


def safe_iso(y:int,m:int,d:int) -> str | None:
    try: return date(y,m,d).isoformat()
    except ValueError: return None


def parse_date_cell(text: str, year: int) -> list[str]:
    text=clean(text).replace(","," | ")
    out=[]
    for m in MRANGE_RE.finditer(text):
        mm=MONTHS[m.group(1).lower()]
        for day in (int(m.group(2)), int(m.group(3))):
            iso=safe_iso(year,mm,day)
            if iso: out.append(iso)
    for m in MDAY_RE.finditer(text):
        iso=safe_iso(year, MONTHS[m.group(1).lower()], int(m.group(2)))
        if iso: out.append(iso)
    return sorted(set(out))


def year_row(cells:list[str]) -> int | None:
    return int(cells[0]) if len(cells)==1 and re.fullmatch(r"20\d{2}", cells[0]) else None


def infer_brand(source_key: str, default: str, event_name: str, row_text: str) -> str:
    if source_key != "wwe_nxt_wikipedia_schedule": return default
    low=(event_name+" "+row_text).lower()
    nxt={"the great american bash","heatwave","no mercy","halloween havoc","deadline","stand & deliver","stand and deliver"}
    return "NXT" if event_name.lower() in nxt or "nxt-branded" in low or "nxt " in low else default


def aggregate(events:list[dict[str,Any]]) -> list[dict[str,Any]]:
    merged={}
    for ev in events:
        key=(ev["source_key"],ev["promotion"],ev["brand"],ev["event_name"],ev.get("venue",""),ev.get("location",""))
        if key not in merged: merged[key]=ev
        else:
            merged[key]["dates"]=sorted(set(merged[key]["dates"])|set(ev["dates"]))
            if ev.get("notes") and ev["notes"] not in merged[key].get("notes",""):
                merged[key]["notes"]=(merged[key].get("notes","")+" | "+ev["notes"]).strip(" |")
    return list(merged.values())


def parse_table(table: str, source: dict[str, Any]) -> list[dict[str,Any]]:
    headers=parse_headers(table)
    if not headers:
        if source["key"]=="tna_wikipedia_schedule": headers=["date","event","venue","location","main event","notes"]
        elif source["key"]=="aew_wikipedia_schedule": headers=["event","date","location","venue","main event","notes"]
        elif source["key"]=="roh_wikipedia_schedule": headers=["date","event","venue","location","main event","notes","ref"]
        else: return []
    idx={h:i for i,h in enumerate(headers)}; current_year=datetime.now(timezone.utc).year
    raw=[]; last=None
    for row in split_rows(table):
        cells=split_cells(row)
        if not cells: continue
        y=year_row(cells)
        if y: current_year=y; continue
        di=idx.get("date"); ei=idx.get("event")
        if di is None or ei is None: continue
        date_cell=cells[di] if di < len(cells) else ""; event_cell=cells[ei] if ei < len(cells) else ""
        dates=parse_date_cell(date_cell,current_year)
        if not dates: continue
        if event_cell:
            name=clean(event_cell)
            venue=cells[idx["venue"]] if "venue" in idx and idx["venue"] < len(cells) else ""
            location=cells[idx["location"]] if "location" in idx and idx["location"] < len(cells) else ""
            notes=cells[idx["notes"]] if "notes" in idx and idx["notes"] < len(cells) else ""
            last={"event_name":name,"venue":venue,"location":location,"notes":notes}
        elif last:
            name=last["event_name"]; venue=last.get("venue",""); location=last.get("location",""); notes=last.get("notes","")
        else: continue
        low=name.lower()
        if source["key"]=="aaa_wikipedia_schedule":
            if "," in name and not any(x in low for x in ["triplemania","triplemania","verano","guerra","rey de reyes"]): continue
            if name == location: continue
        brand=infer_brand(source["key"], source["brand"], name, " ".join(cells))
        raw.append({"source_key":source["key"],"source_url":source["url"],"promotion":source["promotion"],"brand":brand,"event_name":name,"dates":dates,"venue":venue,"location":location,"notes":notes,"raw_date":date_cell})
    return aggregate(raw)


def score(ev:dict[str,Any], reg:dict[str,Any]) -> int:
    s=ev["event_name"].lower(); r=str(reg.get("event_name","")).lower(); aliases=[str(a).lower() for a in reg.get("aliases",[])]
    val=100 if s==r or s in aliases else 60 if s in r or r in s or any(s in a or a in s for a in aliases) else 0
    if ev["promotion"]==reg.get("promotion"): val+=20
    if ev["brand"] in {reg.get("brand"), reg.get("category_hint")}: val+=10
    return val


def compare(ev:dict[str,Any], registry:dict[str,Any]) -> dict[str,Any]:
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


def build(registry:dict[str,Any]) -> dict[str,Any]:
    source_results=[]; events=[]
    for source in SOURCES:
        page=source["page"]; source["url"]="https://en.wikipedia.org/wiki/"+page
        fetched=fetch_raw(page)
        source_results.append({"source_key":source["key"],"promotion":source["promotion"],"ok":fetched["ok"],"status":fetched["status"],"chars":len(fetched.get("text","")),"url":source["url"],"sections":source["sections"]})
        if not fetched["ok"]: continue
        section=find_section(fetched["text"], source["sections"])
        if not section: continue
        for table in extract_tables(section):
            for ev in parse_table(table, source):
                ev["registry_comparison"]=compare(ev,registry); events.append(ev)
    return {"schema_version":"v94_wikipedia_schedule_layer_2_3","generated_at_utc":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"source_results":source_results,"events":events}


def render(payload:dict[str,Any]) -> str:
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
    payload=build(registry); out.mkdir(parents=True,exist_ok=True); stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    jp=out/f"special_events_wikipedia_schedule_layer_{stamp}.json"; mp=out/f"special_events_wikipedia_schedule_layer_{stamp}.md"
    jp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); mp.write_text(render(payload),encoding="utf-8")
    print(f"[WIKI SCHEDULE] events={len(payload['events'])}"); print(f"[WIKI SCHEDULE] json={jp}"); print(f"[WIKI SCHEDULE] report={mp}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
