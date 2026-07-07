#!/usr/bin/env python3
"""OpenWrestlingTV v95.8 feed coverage editorial recall audit.

Diagnostic-only, deterministic, cost-free report. It reads local newsroom state
and artifacts, never calls Gemini, and never changes publishing behavior.
Artifact marker: v95_8_feed_coverage_editorial_recall_audit
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
NEWSROOM = STATE / "newsroom"
ARTIFACTS = ROOT / "artifacts"
DEFAULT_REPORTS_DIR = Path(os.getenv("OWTV_REPORTS_DIR") or ("/opt/owtv/reports" if Path("/opt/owtv").exists() else str(ROOT / "reports")))
MARKER = "v95_8_feed_coverage_editorial_recall_audit"

HARD_TYPES = {"hard_news", "business_legal", "legal", "injury", "roster", "title", "result", "result_event", "business", "data_report"}
SOFT_TYPES = {"soft_news", "low_value", "opinion", "commentary", "podcast", "reaction", "listicle"}
HARD_RE = re.compile(r"\b(death|dies|passed away|arrested|lawsuit|legal|charged|sentenced|serious injury|injury|surgery|released|contract expires|signs|signed|debut|return|returns|title change|wins title|new champion|media rights|tv deal|acquisition|fired|departs)\b", re.I)
SHOULD_RE = re.compile(r"\b(backstage|reportedly|update|follow-up|major|plans|creative|lineup|bracket|ratings|viewership|result|results)\b", re.I)
SOFT_RE = re.compile(r"\b(opinion|commentary|podcast|reacts?|reaction|interview|recalls|nostalgia|social media|photo|listicle|things we|quote|jokes|explains why|addresses)\b", re.I)
REPORT_RE = re.compile(r"\b(report|risultati|results|recap|live coverage|raw|smackdown|dynamite|collision|nxt|impact|payback|summerslam|wrestlemania|aew|wwe)\b", re.I)
STOP = {"the","and","for","with","from","this","that","after","before","wwe","aew","nxt","tna","roh","news","report","reports","update","results","result","wrestling","title","match","follow","up","followup"}

@dataclass
class Trace:
    url: str
    source: str = ""
    title: str = ""
    published_at: str = ""
    kind_hint: str = ""
    score_hint: str = ""
    menzo_decision: str = ""
    menzo_reason: str = ""
    score: int | None = None
    priority_label: str = ""
    article_type: str = ""
    duplicate_reason: str = ""
    andrea_outcome: str = ""
    bob_outcome: str = ""
    alfred_outcome: str = ""
    publisher_outcome: str = ""
    final_title: str = ""
    final_url: str = ""
    trace_status: str = "unknown"
    recall_class: str = "unknown"
    why: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def parse_dt(v: Any) -> datetime | None:
    if not v: return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(str(v))
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

def load_json(path: Path, warnings: list[str], default: Any) -> Any:
    try:
        if not path.exists():
            warnings.append(f"missing_input: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"unreadable_input: {path}: {exc}")
        return default

def norm_url(u: Any) -> str:
    raw = html.unescape(str(u or "").strip())
    if not raw: return ""
    p = urlsplit(raw)
    return urlunsplit((p.scheme.lower(), p.netloc.lower().replace("www.", ""), p.path.rstrip("/"), "", ""))

def first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if d.get(k) not in (None, ""):
            return d.get(k)
    return ""

def iter_items(obj: Any, keys: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if not isinstance(obj, dict): return out
    for k in keys:
        v = obj.get(k)
        if isinstance(v, list): out.extend([x for x in v if isinstance(x, dict)])
    return out

def in_window(item: dict[str, Any], since: datetime, until: datetime) -> bool:
    dt = parse_dt(first(item, "published", "published_at", "created_at", "generated_at", "mtime_utc"))
    return True if dt is None else since <= dt <= until

def classify(t: Trace, published: bool) -> str:
    blob = f"{t.title} {t.menzo_reason} {t.article_type} {t.priority_label}".lower()
    strong = []
    if t.score is not None and t.score >= 80: strong.append("score>=80")
    if str(t.priority_label).lower() in {"high", "critical", "hard"}: strong.append("high_priority")
    if HARD_RE.search(blob): strong.append("hard_news_keyword")
    if str(t.article_type).lower() in HARD_TYPES: strong.append("hard_article_type")
    if not published and strong:
        t.why.extend(strong); return "must_publish_candidate"
    if not published and ((t.score is not None and 65 <= t.score <= 79) or SHOULD_RE.search(blob)):
        t.why.append("medium_score_or_concrete_news_signal"); return "should_publish_candidate"
    if SOFT_RE.search(blob) or str(t.article_type).lower() in SOFT_TYPES:
        t.why.append("soft_optional_signal"); return "optional_soft" if published else "correctly_skipped_likely"
    if not published and re.search(r"duplicate|low|expired|already|history|no extraction|promo", blob):
        t.why.append("skip_reason_looks_expected"); return "correctly_skipped_likely"
    return "unknown"

def extract_published_from_files(since: datetime, until: datetime) -> list[dict[str, Any]]:
    rows=[]
    title_re=re.compile(r"<h1[^>]*>(.*?)</h1>|<title[^>]*>(.*?)</title>", re.I|re.S)
    for base in [ROOT/"published_html_review", ROOT/"published"]:
        if not base.exists(): continue
        for p in base.iterdir():
            if not p.is_file() or p.suffix.lower() not in {".html", ".json", ".md"}: continue
            mt=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            if mt < since or mt > until: continue
            text=p.read_text(encoding="utf-8", errors="ignore")[:5000]
            title=p.stem
            if p.suffix.lower()==".json":
                try:
                    j=json.loads(text); title=str(first(j,"title_it","title","source_title") or title); url=first(j,"source_url","url")
                except Exception: url=""
            else:
                m=title_re.search(text); title=re.sub(r"<[^>]+>"," ",(m.group(1) or m.group(2)) if m else title).strip(); url=""
            rows.append({"source_url":url,"title_it":title,"status":"published_file","published_at":mt.isoformat(),"path":str(p)})
    return rows

def tokens(title: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9]+"," ",title.lower()).split() if len(w)>3 and w not in STOP}

def action(title: str) -> str:
    s=title.lower()
    for name, rx in {"injury":r"injur|surgery", "return":r"return|back", "legal":r"lawsuit|legal|arrest|charged", "title":r"title|champion", "result":r"defeat|beats|wins|results", "business":r"media rights|tv deal|acquisition"}.items():
        if re.search(rx,s): return name
    return "general"

def overcoverage(pubs: list[dict[str,Any]]) -> list[dict[str,Any]]:
    groups: dict[str,list[dict[str,Any]]] = {}
    for p in pubs:
        title=str(first(p,"title_it","title","source_title") or "")
        key_terms=sorted(tokens(title))[:4]
        if not key_terms: continue
        key=f"{action(title)}:{' '.join(key_terms[:3])}"
        groups.setdefault(key,[]).append(p)
    risks=[]
    for key, items in groups.items():
        if len(items)>=2:
            risks.append({"label":key,"count":len(items),"items":items,"reason":"possible_overcoverage: story_thread_saturation"})
    return sorted(risks, key=lambda r: r["count"], reverse=True)

def report_overlap(pubs: list[dict[str,Any]], reports: list[dict[str,Any]]) -> list[dict[str,Any]]:
    risks=[]
    for r in reports:
        rt=parse_dt(first(r,"published_at","generated_at","created_at")) or utc_now()
        rtitle=str(first(r,"title","show","show_name") or "report")
        for p in pubs:
            title=str(first(p,"title_it","title","source_title") or "")
            if REPORT_RE.search(title) and abs(((parse_dt(first(p,"published_at","created_at")) or rt)-rt).total_seconds()) <= 24*3600:
                cls="likely_valid_major_angle" if HARD_RE.search(title) else "possible_report_duplicate"
                risks.append({"report":rtitle,"title":title,"classification":cls})
    return risks

def build_audit(hours: int, root: Path = ROOT) -> tuple[str, Path]:
    global ROOT, STATE, NEWSROOM, ARTIFACTS
    ROOT=root; STATE=root/"state"; NEWSROOM=STATE/"newsroom"; ARTIFACTS=root/"artifacts"
    until=utc_now(); since=until-timedelta(hours=hours); warnings=[]
    massy=load_json(NEWSROOM/"massy_board_latest.json", warnings, {})
    menzo=load_json(NEWSROOM/"menzo_decisions_latest.json", warnings, {})
    bob=load_json(NEWSROOM/"bob_articles_latest.json", warnings, {})
    alfred=load_json(NEWSROOM/"alfred_review_latest.json", warnings, {})
    publisher=load_json(NEWSROOM/"publisher_status_latest.json", warnings, {})
    simone=load_json(NEWSROOM/"simone_reports_latest.json", warnings, {})
    simpub=load_json(NEWSROOM/"simone_report_publish_latest.json", warnings, {})
    for extra in ["archivista_report_latest.json","gemini_call_ledger.jsonl","report_publication_registry.json"]:
        if not (NEWSROOM/extra).exists(): warnings.append(f"missing_input: state/newsroom/{extra}")
    for extra in ["manual_runs.json","report_status.json"]:
        if not (STATE/extra).exists(): warnings.append(f"missing_input: state/{extra}")
    for extra in ["skipped_history.json","history.txt"]:
        if not (root/extra).exists(): warnings.append(f"missing_optional_input: {extra}")

    feed_items=iter_items(massy,["news_candidates_for_menzo","report_candidates","hard_skipped","already_worked","items","entries"])
    traces: dict[str,Trace]={}
    for it in feed_items:
        if not in_window(it,since,until): continue
        u=norm_url(first(it,"url","source_url","link"));
        if not u: continue
        traces[u]=Trace(url=u, source=str(first(it,"source","source_id","feed") or ""), title=str(first(it,"title","source_title") or ""), published_at=str(first(it,"published","published_at") or ""), kind_hint=str(first(it,"kind","kind_hint","assigned_to") or ""), score_hint=str(first(it,"score","score_hint") or ""))
    menzo_items=iter_items(menzo,["selected","pending","skipped"])
    for it in menzo_items:
        u=norm_url(first(it,"url","source_url"));
        if not u: continue
        t=traces.setdefault(u, Trace(url=u, title=str(first(it,"title","source_title") or "")))
        t.menzo_decision=str(it.get("decision") or ("selected" if it in menzo.get("selected",[]) else "")); t.menzo_reason=str(first(it,"reason","editorial_reason","ai_editorial_reason") or "")
        try: t.score=int(first(it,"score","ai_priority","deterministic_score") or 0)
        except Exception: pass
        t.priority_label=str(first(it,"ai_priority_label","priority_label","priority") or ""); t.article_type=str(it.get("article_type") or ""); t.duplicate_reason=str(first(it,"duplicate_of","duplicate_reason","event_key") or "")
        if not t.title: t.title=str(first(it,"title","source_title") or "")
    for it in iter_items(bob,["articles"]):
        u=norm_url(first(it,"source_url","url"));
        if u in traces: traces[u].bob_outcome=str(it.get("status") or "generated")
    for rev in iter_items(alfred,["reviews","approved_articles"]):
        art=rev.get("approved_article") if isinstance(rev.get("approved_article"),dict) else rev
        u=norm_url(first(art,"source_url","url"));
        if u in traces: traces[u].alfred_outcome=str(rev.get("decision") or "approved")
    pubs=iter_items(publisher,["results","skipped_approved_articles"])+extract_published_from_files(since,until)
    for it in pubs:
        u=norm_url(first(it,"source_url","url"));
        if u:
            t=traces.setdefault(u, Trace(url=u, title=str(first(it,"title_it","title") or "")))
            t.publisher_outcome=str(it.get("status") or ""); t.final_title=str(first(it,"title_it","title") or t.title); t.final_url=str(first(it,"wp_link","url","path") or "")
    for t in traces.values():
        published=t.publisher_outcome in {"published","already_published","dry_run","published_file"} or bool(t.final_url and t.publisher_outcome)
        if published: t.trace_status="published"
        elif t.menzo_decision=="skip": t.trace_status="skipped"
        elif t.menzo_decision=="pending": t.trace_status="pending"
        elif t.kind_hint=="report_candidate": t.trace_status="report_candidate"
        elif re.search("already", f"{t.kind_hint} {t.menzo_reason}", re.I): t.trace_status="already_seen"
        else: t.trace_status="unknown"
        t.recall_class=classify(t,published)
    trace_list=sorted(traces.values(), key=lambda x:(x.trace_status,x.source,x.title))
    missed=[t for t in trace_list if t.trace_status!="published" and t.recall_class in {"must_publish_candidate","should_publish_candidate"}]
    soft=[t for t in trace_list if t.trace_status=="published" and t.recall_class=="optional_soft"]
    over=overcoverage([p for p in pubs if str(p.get("status")) in {"published","already_published","dry_run","published_file"}])
    reports=iter_items(simone,["reports","report_candidates"])+iter_items(simpub,["results","published_reports","reports"])
    overlaps=report_overlap(pubs,reports)
    def c(status): return sum(1 for t in trace_list if t.trace_status==status)
    lines=[f"# OWTV Feed Coverage Editorial Recall Audit v95.8", "", f"Artifact marker: `{MARKER}`", f"Window: {hours}h ({since.isoformat()} → {until.isoformat()} UTC)", "", "## 1. Executive summary", "", f"- Feed URLs seen: {len(trace_list)}", f"- Feed URLs with Menzo decision: {sum(1 for t in trace_list if t.menzo_decision)}", f"- Feed URLs published: {c('published')}", f"- Feed URLs skipped: {c('skipped')}", f"- Feed URLs pending: {c('pending')}", f"- Feed URLs unknown/untracked: {c('unknown')}", f"- Potential must-publish missed: {sum(1 for t in missed if t.recall_class=='must_publish_candidate')}", f"- Potential should-publish missed: {sum(1 for t in missed if t.recall_class=='should_publish_candidate')}", f"- Potential overpublished soft items: {len(soft)}", f"- Potential story-thread overcoverage: {len(over)}", f"- Post-show/report overlap risks: {len(overlaps)}", "", "## 2. Coverage funnel", "", "| Stage | Count |", "|---|---:|", f"| Massy feed URLs | {len(trace_list)} |", f"| Menzo evaluated | {sum(1 for t in trace_list if t.menzo_decision)} |", f"| Menzo selected | {sum(1 for t in trace_list if t.menzo_decision=='selected')} |", f"| Menzo pending | {sum(1 for t in trace_list if t.menzo_decision=='pending')} |", f"| Menzo skipped | {sum(1 for t in trace_list if t.menzo_decision=='skip')} |", f"| Andrea checked/passed/blocked | n/a / {sum(1 for t in trace_list if t.andrea_outcome=='passed')} / {sum(1 for t in trace_list if t.andrea_outcome=='blocked')} |", f"| Bob generated | {sum(1 for t in trace_list if t.bob_outcome)} |", f"| Alfred approved/warnings/blockers | {sum(1 for t in trace_list if t.alfred_outcome=='approved')} / n/a / n/a |", f"| Publisher published/already/errors | {sum(1 for t in trace_list if t.publisher_outcome=='published')} / {sum(1 for t in trace_list if t.publisher_outcome=='already_published')} / {sum(1 for t in trace_list if 'error' in t.publisher_outcome)} |", f"| Final published | {c('published')} |", ""]
    lines += ["## 3. Feed URL trace table", "", "| source | source_title | source_url | feed published_at | Massy kind/score | Menzo decision | Menzo reason | score | priority | article_type | duplicate/story | Andrea | Bob | Alfred | Publisher | final title/url | trace_status | editorial_recall_class |", "|---|---|---|---|---|---|---|---:|---|---|---|---|---|---|---|---|---|---|"]
    for t in trace_list:
        esc=lambda s: str(s or "").replace("|","/")[:180]
        lines.append(f"| {esc(t.source)} | {esc(t.title)} | {esc(t.url)} | {esc(t.published_at)} | {esc(t.kind_hint+'/'+t.score_hint)} | {esc(t.menzo_decision)} | {esc(t.menzo_reason)} | {t.score if t.score is not None else ''} | {esc(t.priority_label)} | {esc(t.article_type)} | {esc(t.duplicate_reason)} | {esc(t.andrea_outcome)} | {esc(t.bob_outcome)} | {esc(t.alfred_outcome)} | {esc(t.publisher_outcome)} | {esc(t.final_title or t.final_url)} | {t.trace_status} | {t.recall_class} |")
    lines += ["", "## 4. Potential missed stories", ""] + ([f"- **{t.title or t.url}** ({t.source}) — {t.url} — potential_miss: {', '.join(t.why) or 'review signal'}; skipped/trace reason: {t.menzo_reason or t.trace_status}; suggested human action: {'check_policy' if 'duplicate' in t.menzo_reason else 'review'}" for t in missed] or ["- None detected."])
    lines += ["", "## 5. Potential overpublished soft items", ""] + ([f"- **{t.final_title or t.title}** — possible_overpublished_soft_item: {', '.join(t.why)} — {t.url}" for t in soft] or ["- None detected."])
    lines += ["", "## 6. Story thread overcoverage", ""] + ([f"- **{r['label']}** ({r['count']} published) — {r['reason']}; titles: " + "; ".join(str(first(i,'title_it','title','source_title')) for i in r['items']) for r in over] or ["- None detected by fallback grouping; latest story cluster audit, if present, should be reviewed separately."])
    lines += ["", "## 7. Report/post-show overlap", ""] + ([f"- Report `{o['report']}` vs `{o['title']}` — {o['classification']}" for o in overlaps] or ["- None detected."])
    lines += ["", "## 8. Source coverage", "", "| source | seen | published | skipped | pending | unknown | publish rate | possible missed high-value |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for src in sorted({t.source or 'unknown' for t in trace_list}):
        rows=[t for t in trace_list if (t.source or 'unknown')==src]; pub=sum(1 for t in rows if t.trace_status=='published')
        lines.append(f"| {src} | {len(rows)} | {pub} | {sum(1 for t in rows if t.trace_status=='skipped')} | {sum(1 for t in rows if t.trace_status=='pending')} | {sum(1 for t in rows if t.trace_status=='unknown')} | {pub/len(rows):.0%} | {sum(1 for t in rows if t in missed)} |")
    lines += ["", "## 9. Category/type coverage", "", "| type/category | count |", "|---|---:|"]
    for typ in sorted({(t.article_type or ('report' if t.trace_status=='report_candidate' else 'unknown')) for t in trace_list}): lines.append(f"| {typ} | {sum(1 for t in trace_list if (t.article_type or ('report' if t.trace_status=='report_candidate' else 'unknown'))==typ)} |")
    lines += ["", "## 10. Human review samples", "", "### Top skipped candidates to review"] + ([f"- {t.recall_class}: {t.title} — {t.url}" for t in missed[:5]] or ["- None."])
    lines += ["", "### Top published candidates to quality-check"] + ([f"- optional_soft: {t.final_title or t.title} — {t.url}" for t in soft[:5]] or ["- None."])
    lines += ["", "### Top overcoverage candidates"] + ([f"- {r['label']} ({r['count']})" for r in over[:5]] or ["- None."])
    lines += ["", "### Top unknown/untracked URLs"] + ([f"- {t.title} — {t.url}" for t in trace_list if t.trace_status=='unknown'][:5] or ["- None."])
    lines += ["", "## Input warnings", ""] + ([f"- {w}" for w in warnings] or ["- None."])
    outdir=Path(os.getenv("OWTV_REPORTS_DIR") or DEFAULT_REPORTS_DIR); outdir.mkdir(parents=True, exist_ok=True)
    out=outdir/f"owtv_feed_coverage_audit_v95_8_{hours}h_{until.strftime('%Y%m%dT%H%M%SZ')}.md"
    text="\n".join(lines)+"\n"; out.write_text(text, encoding="utf-8")
    return text,out

def main() -> int:
    ap=argparse.ArgumentParser(description="OWTV v95.8 feed coverage editorial recall audit")
    ap.add_argument("hours", nargs="?", type=int, default=24, choices=[12,24,48])
    args=ap.parse_args(); _, out=build_audit(args.hours); print(out); return 0
if __name__ == "__main__": raise SystemExit(main())
