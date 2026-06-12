#!/usr/bin/env python3
"""OpenWrestlingTV v94.4.1 - Wikipedia schedule table layer.

Read-only checker for curated Wikipedia upcoming-event tables.
It extracts future event rows for WWE/NXT, AEW, TNA, ROH and AAA, then compares
those rows with config/special_events.json. It never changes the registry.
"""
from __future__ import annotations

import argparse, html, json, re, urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO_DIR / "reports"

SOURCES = [
    ("wwe_nxt_wikipedia_schedule", "WWE", "WWE", "https://en.wikipedia.org/wiki/List_of_WWE_pay-per-view_and_livestreaming_supercards"),
    ("aew_wikipedia_schedule", "AEW", "AEW", "https://en.wikipedia.org/wiki/List_of_All_Elite_Wrestling_pay-per-view_events"),
    ("tna_wikipedia_schedule", "TNA", "TNA", "https://en.wikipedia.org/wiki/List_of_TNA_pay-per-view_and_livestreaming_events"),
    ("roh_wikipedia_schedule", "ROH", "ROH", "https://en.wikipedia.org/wiki/List_of_Ring_of_Honor_pay-per-view_and_livestreaming_events"),
    ("aaa_wikipedia_schedule", "AAA", "AAA", "https://en.wikipedia.org/wiki/List_of_major_Lucha_Libre_AAA_Worldwide_events"),
]
MONTHS = {"january":1,"february":2,"march":3,"april":4,"may":5,"june":6,"july":7,"august":8,"september":9,"october":10,"november":11,"december":12,"jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,"sep":9,"sept":9,"oct":10,"nov":11,"dec":12}
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")


def clean(s: str) -> str:
    s = html.unescape(s or "")
    s = TAG_RE.sub(" ", s)
    s = re.sub(r"\[[^\]]+\]", "", s)
    return SPACE_RE.sub(" ", s).strip()


def fetch(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenWrestlingTV-WikiScheduleLayer/1.1"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(1800000).decode("utf-8", errors="replace")
            return {"ok": True, "status": f"http_{getattr(r,'status','?')}", "url": url, "raw": raw, "text": clean(raw)}
    except Exception as e:
        return {"ok": False, "status": f"fetch_error:{type(e).__name__}:{e}", "url": url, "raw": "", "text": ""}


class WikiTableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.in_table=False; self.depth=0; self.in_row=False; self.in_cell=False
        self.rows=[]; self.row=[]; self.buf=[]; self.tag=""; self.attrs={}
    def handle_starttag(self, tag, attrs):
        d={k:v or "" for k,v in attrs}
        if tag=="table":
            if not self.in_table and "wikitable" in d.get("class",""):
                self.in_table=True; self.depth=1
            elif self.in_table: self.depth+=1
        elif self.in_table and tag=="tr": self.in_row=True; self.row=[]
        elif self.in_table and self.in_row and tag in {"td","th"}:
            self.in_cell=True; self.tag=tag; self.attrs=d; self.buf=[]
        elif self.in_cell and tag=="br": self.buf.append(" | ")
    def handle_endtag(self, tag):
        if self.in_cell and tag in {"td","th"}:
            self.row.append({"tag":self.tag,"text":clean("".join(self.buf)),"style":self.attrs.get("style",""),"class":self.attrs.get("class","")}); self.in_cell=False
        elif self.in_table and tag=="tr":
            if self.row: self.rows.append(self.row)
            self.in_row=False
        elif self.in_table and tag=="table":
            self.depth-=1
            if self.depth<=0: self.in_table=False
    def handle_data(self, data):
        if self.in_cell: self.buf.append(data)


def relevant_html(raw: str) -> str:
    low = raw.lower(); spots=[low.find(x) for x in ["upcoming event schedule","upcoming events"]]; spots=[s for s in spots if s>=0]
    return raw[min(spots):min(spots)+180000] if spots else raw


def parse_tables(raw: str):
    p=WikiTableParser(); p.feed(relevant_html(raw)); return p.rows


def safe_iso(y:int, m:int, d:int) -> str | None:
    try: return date(y,m,d).isoformat()
    except ValueError: return None


def parse_date_cell(txt: str, year: int) -> list[str]:
    out=[]
    for piece in re.split(r"\||;", clean(txt)):
        piece=piece.strip()
        m=re.match(r"^(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?$", piece, re.I)
        if m:
            iso=safe_iso(year, MONTHS[m.group(1).lower()], int(m.group(2)))
            if iso: out.append(iso)
            continue
        m=re.match(r"^(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?\s*[–-]\s*(\d{1,2})(?:st|nd|rd|th)?$", piece, re.I)
        if m:
            month=MONTHS[m.group(1).lower()]
            for day in [int(m.group(2)), int(m.group(3))]:
                iso=safe_iso(year, month, day)
                if iso: out.append(iso)
    return sorted(set(out))


def row_is_nxt(row, source_key, event_name):
    if source_key != "wwe_nxt_wikipedia_schedule": return False
    j=" ".join((c.get("style","")+" "+c.get("class","")+" "+c.get("text","")) for c in row).lower()
    nxt_names={"the great american bash","heatwave","no mercy","halloween havoc","deadline","stand & deliver","stand and deliver"}
    return "nxt" in j or event_name.lower() in nxt_names


def rows_to_events(source_key, promotion, default_brand, url, rows):
    events=[]; current_year=datetime.now().year; headers=[]
    for row in rows:
        texts=[c["text"] for c in row]
        if len(texts)==1 and re.fullmatch(r"20\d{2}", texts[0]): current_year=int(texts[0]); continue
        if row and all(c.get("tag")=="th" for c in row): headers=[t.lower() for t in texts]; continue
        if len(row)<2: continue
        local_headers=headers if len(headers)==len(row) else None
        if not local_headers:
            if source_key=="aew_wikipedia_schedule": local_headers=["event","date","location","venue","main event","notes"][:len(row)]
            elif source_key=="tna_wikipedia_schedule": local_headers=["date","event","venue","location","main event","notes"][:len(row)]
            else: local_headers=["date","event","venue","location","notes"][:len(row)]
        data={local_headers[i]: row[i]["text"] for i in range(min(len(local_headers),len(row)))}
        name=clean(data.get("event","")).replace("TNA+","TNA+"); dates=parse_date_cell(data.get("date",""), current_year)
        if not name or not dates: continue
        brand="NXT" if row_is_nxt(row, source_key, name) else default_brand
        events.append({"source_key":source_key,"promotion":promotion,"brand":brand,"event_name":name,"dates":dates,"venue":data.get("venue",""),"location":data.get("location",""),"notes":data.get("notes",""),"raw_date":data.get("date",""),"source_url":url})
    return events


def score(ev, reg):
    s=ev["event_name"].lower(); r=str(reg.get("event_name","")).lower(); aliases=[str(a).lower() for a in reg.get("aliases",[])]
    v=100 if s==r or s in aliases else 60 if s in r or r in s or any(s in a or a in s for a in aliases) else 0
    if ev["promotion"]==reg.get("promotion"): v+=20
    if ev["brand"] in {reg.get("brand"), reg.get("category_hint")}: v+=10
    return v


def compare(ev, registry):
    matches=sorted(((score(ev,r),r) for r in registry.get("events",[])), key=lambda x:x[0], reverse=True)
    best_score,best=(matches[0] if matches else (0,{}))
    if best_score<60: best={}
    reg_dates=[n.get("date_local") for n in best.get("nights",[]) if n.get("date_local")] if best else []
    matching=sorted(set(reg_dates)&set(ev["dates"])); new=sorted(set(ev["dates"])-set(reg_dates))
    if not best: action="new_event_manual_review" if ev["promotion"]=="AAA" else "new_event_safe_to_review"
    elif matching and not new: action="no_action_if_dates_match"
    elif best.get("status") in {"expected","proposed"}: action="safe_to_accept_after_review"
    else: action="manual_review_date_difference"
    return {"registry_event_key":best.get("key"),"registry_status":best.get("status"),"match_score":best_score,"registry_dates":reg_dates,"matching_dates":matching,"new_candidate_dates":new,"recommended_action":action}


def build(registry):
    sources=[]; events=[]
    for key,promo,brand,url in SOURCES:
        got=fetch(url); sources.append({"source_key":key,"promotion":promo,"ok":got["ok"],"status":got["status"],"chars":len(got.get("text","")),"url":url})
        if got["ok"]:
            for ev in rows_to_events(key,promo,brand,url,parse_tables(got["raw"])):
                ev["registry_comparison"]=compare(ev,registry); events.append(ev)
    return {"schema_version":"v94_wikipedia_schedule_layer_1_1","generated_at_utc":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"source_results":sources,"events":events}


def render(payload):
    lines=["# OpenWrestlingTV - Wikipedia schedule layer","",f"Generated UTC: {payload['generated_at_utc']}","","## Source check"]
    for s in payload["source_results"]: lines.append(f"- {'OK' if s['ok'] else 'FAIL'} | {s['source_key']} | {s['promotion']} | {s['status']} | chars={s['chars']} | {s['url']}")
    lines += ["","## Upcoming schedule extracted"]
    for ev in payload["events"]:
        c=ev["registry_comparison"]
        lines += [f"### {ev['promotion']} / {ev['brand']} - {ev['event_name']}",f"- source_dates: {', '.join(ev['dates'])}",f"- venue: {ev.get('venue') or '-'}",f"- location: {ev.get('location') or '-'}"]
        if ev.get("notes"): lines.append(f"- notes: {ev['notes']}")
        lines += [f"- registry_event: {c.get('registry_event_key') or 'not_found'}",f"- registry_status: {c.get('registry_status') or '-'}",f"- registry_dates: {', '.join(c.get('registry_dates') or []) or 'none'}",f"- matching_dates: {', '.join(c.get('matching_dates') or []) or 'none'}",f"- new_candidate_dates: {', '.join(c.get('new_candidate_dates') or []) or 'none'}",f"- recommended_action: {c.get('recommended_action')}",""]
    return "\n".join(lines)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--repo-dir",default=str(REPO_DIR)); ap.add_argument("--report-dir",default=str(REPORT_DIR)); args=ap.parse_args()
    repo=Path(args.repo_dir).resolve(); out=Path(args.report_dir).resolve(); registry=json.loads((repo/"config/special_events.json").read_text(encoding="utf-8"))
    payload=build(registry); out.mkdir(parents=True,exist_ok=True); stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
    jp=out/f"special_events_wikipedia_schedule_layer_{stamp}.json"; mp=out/f"special_events_wikipedia_schedule_layer_{stamp}.md"
    jp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); mp.write_text(render(payload),encoding="utf-8")
    print(f"[WIKI SCHEDULE] events={len(payload['events'])}"); print(f"[WIKI SCHEDULE] json={jp}"); print(f"[WIKI SCHEDULE] report={mp}"); return 0

if __name__=="__main__": raise SystemExit(main())
