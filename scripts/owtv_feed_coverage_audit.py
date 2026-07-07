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
ARTIFACT_PREFIX_RE = re.compile(r"^(?:v\d+[_-])?(?:news|publisher)[_-]", re.I)
PREPUBLISH_RE = re.compile(r"\.prepublish(?:\.[^.]+)?$", re.I)
SHOW_MARKER_RE = re.compile(r"\b(raw|smackdown|nxt|dynamite|collision|rampage|impact|roh|results?|recap|live coverage|title match|main event|championship|champion|segment|july\s+\d{1,2}|\d{1,2}/\d{1,2})\b", re.I)
PUBLISHED_STATUSES = {"published", "already_published", "published_file", "published_trace"}
UNPUBLISHED_STATUSES = {"skipped_approved_articles", "wp_not_ready", "publish_error", "skipped_capacity", "skipped", "error"}
DUPLICATE_LOSER_RE = re.compile(r"(ai_cross_source_duplicate_arbitration_loser|duplicate_arbitration_loser|duplicate loser)", re.I)
GENERIC_RECAP_DUPLICATE_RE = re.compile(
    r"\b("
    r"live\s+results?|full\s+results?|complete\s+results?|results?|risultati|"
    r"recap|highlights?|momenti\s+salienti|moments?|what\s+happened|"
    r"live\s+coverage|live\s+blog|play[-\s]+by[-\s]+play|"
    r"live\s+updates?|ongoing\s+coverage|"
    r"reports?|show\s+review|things\s+(?:we\s+)?(?:loved|hated)|"
    r"\d+\s+things|full\s+show\s+coverage"
    r")\b",
    re.I,
)
REPORT_PUBLICATION_RE = re.compile(r"\b(simone|report[_ -]?show|show[_ -]?report|report publication|simone report|reporto|risultati|results)\b", re.I)
ITALIAN_MONTHS = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}

@dataclass
class Trace:
    url: str
    source: str = ""
    title: str = ""
    published_at: str = ""
    massy_decision: str = ""
    massy_reason: str = ""
    kind_hint: str = ""
    score_hint: str = ""
    menzo_decision: str = ""
    menzo_reason: str = ""
    score: int | None = None
    priority_label: str = ""
    article_type: str = ""
    duplicate_reason: str = ""
    andrea_outcome: str = ""
    andrea_reason: str = ""
    andrea_blocked_before_bob: bool = False
    bob_outcome: str = ""
    alfred_outcome: str = ""
    publisher_outcome: str = ""
    final_title: str = ""
    final_url: str = ""
    trace_status: str = "unknown"
    recall_class: str = "unknown"
    comparison_class: str = "unknown_needs_trace"
    published_match_method: str = ""
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

def canonical_slug(value: Any) -> str:
    """Collapse local pipeline artifact variants to one story-level slug."""
    raw = Path(str(value or "")).name
    raw = PREPUBLISH_RE.sub("", raw)
    raw = re.sub(r"\.(?:html|json|md|txt)$", "", raw, flags=re.I)
    previous = None
    while raw != previous:
        previous = raw
        raw = ARTIFACT_PREFIX_RE.sub("", raw)
    raw = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return raw

def record_slug(item: dict[str, Any]) -> str:
    for key in ("slug", "artifact_slug", "path", "file", "filename"):
        v = item.get(key)
        if v:
            slug = canonical_slug(v)
            if slug:
                return slug
    title = first(item, "title_it", "title", "source_title")
    slug = canonical_slug(title)
    if slug:
        return slug
    for key in ("final_url", "wp_link", "published_url", "url"):
        v = item.get(key)
        if v:
            slug = canonical_slug(v)
            if slug:
                return slug
    return ""

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

def classify(t: Trace, published: bool, duplicate_survivor_found: bool = False) -> str:
    blob = f"{t.title} {t.menzo_reason} {t.article_type} {t.priority_label}".lower()
    if not published and DUPLICATE_LOSER_RE.search(f"{t.menzo_reason} {t.duplicate_reason}"):
        t.why.append("duplicate loser; verify survivor coverage")
        return "correctly_skipped_likely" if duplicate_survivor_found else "duplicate_loser_review"
    if not published and t.andrea_blocked_before_bob:
        t.why.append(f"andrea_blocked_before_bob:{t.andrea_reason or t.andrea_outcome}")
        if t.score is not None and t.score >= 80:
            t.why.append("needs_human_review_high_score_andrea_block")
        return "correctly_skipped_likely"
    if not published and t.trace_status in {"skipped", "already_seen", "already_worked", "report_candidate"}:
        massy_blob = f"{t.massy_decision} {t.massy_reason} {t.kind_hint}".lower()
        if re.search(r"hard_skip|already|report_candidate|simone|duplicate|low|expired|history|published", massy_blob):
            t.why.append(f"massy_disposition:{t.massy_decision or t.kind_hint}")
            return "correctly_skipped_likely"
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

def extract_published_traces(since: datetime, until: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = ARTIFACTS / "published_traces"
    if not base.exists():
        return rows
    for p in base.glob("*.published_trace.json"):
        if not p.is_file():
            continue
        try:
            item = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(item, dict) or item.get("artifact_marker") != "owtv_published_trace_v1":
            continue
        if is_report_publication_record(item, str(p)) and item.get("artifact_marker") != "owtv_report_trace_v1":
            continue
        check = dict(item)
        check.setdefault("published_at", datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat())
        if not in_window(check, since, until):
            continue
        check.setdefault("status", "published_trace")
        check.setdefault("path", str(p))
        check.setdefault("slug", canonical_slug(check.get("slug") or p.name))
        check["_pub_source"] = "published_trace"
        rows.append(check)
    return rows

def extract_published_from_files(since: datetime, until: datetime) -> list[dict[str, Any]]:
    rows=[]
    title_re=re.compile(r"<h1[^>]*>(.*?)</h1>|<title[^>]*>(.*?)</title>", re.I|re.S)
    trusted_dirs = [(ROOT/"published_html_review", "published_html_review"), (ROOT/"published", "published"), (ARTIFACTS/"published_html_review", "artifact_published_html_review"), (ARTIFACTS/"published", "artifact_published")]
    for base, source in trusted_dirs:
        if not base.exists(): continue
        iterator = base.rglob("*") if base.is_relative_to(ARTIFACTS) else base.iterdir()
        for p in iterator:
            if not p.is_file() or p.suffix.lower() not in {".html", ".json", ".md"}: continue
            if ".prepublish" in p.name.lower():
                continue
            mt=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            if mt < since or mt > until: continue
            text=p.read_text(encoding="utf-8", errors="ignore")[:5000]
            title=p.stem
            url=""
            if p.suffix.lower()==".json":
                try:
                    j=json.loads(text); title=str(first(j,"title_it","title","source_title") or title); url=first(j,"source_url","url")
                except Exception:
                    pass
            else:
                m=title_re.search(text); title=re.sub(r"<[^>]+>"," ",(m.group(1) or m.group(2)) if m else title).strip(); url=""
            rows.append({"source_url":url,"title_it":title,"status":"published_file","published_at":mt.isoformat(),"path":str(p), "_pub_source":source})
    # Generic artifacts are not publication directories. Only accept artifact JSON
    # that explicitly looks like a final publication record.
    if ARTIFACTS.exists():
        for p in ARTIFACTS.rglob("*.json"):
            if not p.is_file() or ".prepublish" in p.name.lower() or p.name.endswith(".published_trace.json"):
                continue
            mt=datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
            if mt < since or mt > until:
                continue
            try:
                item=json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if "simone_report_publish" in str(p).lower() or is_report_publication_record(item, str(p)):
                continue
            status=str(item.get("status") or "").lower()
            has_explicit_publication = (
                status in PUBLISHED_STATUSES
                or bool(first(item, "published_url", "wp_post_id", "final_url"))
                or (bool(first(item, "source_url", "url")) and bool(first(item, "final_title", "slug", "artifact_slug")))
            )
            if not has_explicit_publication or status in UNPUBLISHED_STATUSES:
                continue
            item=dict(item)
            item.setdefault("status", "published_file")
            item.setdefault("path", str(p))
            item.setdefault("published_at", mt.isoformat())
            item["_pub_source"]="artifact_metadata"
            rows.append(item)
    return rows

def record_priority(item: dict[str, Any]) -> int:
    source = str(item.get("_pub_source") or "")
    status = str(item.get("status") or "").lower()
    if source == "published_trace":
        return 4
    if source == "publisher" or (status in {"published", "already_published"} and first(item, "source_url", "wp_link", "published_url", "final_url")):
        return 3
    if source == "published_html_review":
        return 2
    if source == "published":
        return 1
    return 0

def merge_published_records(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if record_priority(incoming) > record_priority(current):
        winner, loser = dict(incoming), current
    else:
        winner, loser = dict(current), incoming
    for key, value in loser.items():
        if winner.get(key) in (None, "") and value not in (None, ""):
            winner[key] = value
    return winner

def dedupe_published_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    key_to_index: dict[str, int] = {}
    for item in records:
        if not is_published_record(item):
            continue
        keys = {f"url:{u}" for u in [norm_url(first(item, "source_url", "url"))] if u}
        slug = record_slug(item)
        if slug:
            keys.add(f"slug:{slug}")
        matched = sorted({key_to_index[k] for k in keys if k in key_to_index})
        if not matched:
            deduped.append(dict(item))
            index = len(deduped)-1
        else:
            index = matched[0]
            deduped[index] = merge_published_records(deduped[index], item)
            for duplicate_index in reversed(matched[1:]):
                deduped[index] = merge_published_records(deduped[index], deduped[duplicate_index])
                del deduped[duplicate_index]
                for key, old_index in list(key_to_index.items()):
                    if old_index == duplicate_index:
                        key_to_index[key] = index
                    elif old_index > duplicate_index:
                        key_to_index[key] = old_index - 1
        for key in keys:
            key_to_index[key] = index
    return deduped

def build_published_indexes(records: list[dict[str, Any]]) -> tuple[set[str], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    urls: set[str] = set()
    by_url: dict[str, dict[str, Any]] = {}
    by_slug: dict[str, dict[str, Any]] = {}
    for item in records:
        for key in ("source_url", "url"):
            u = norm_url(item.get(key))
            if u:
                urls.add(u); by_url[u] = item
        slug = record_slug(item)
        if slug:
            by_slug[slug] = item
    return urls, by_url, by_slug

def source_is_monitored(value: Any) -> bool:
    s = str(value or "").lower().replace(" ", "")
    return "wrestlinginc" in s or "ringsidenews" in s or "ringside-news" in s

def url_is_monitored(value: Any) -> bool:
    host = urlsplit(str(value or "")).netloc.lower().replace("www.", "")
    return host.endswith("wrestlinginc.com") or host.endswith("ringsidenews.com")

def published_recovery_method(item: dict[str, Any]) -> str:
    src = str(item.get("_pub_source") or "")
    if src == "published_trace" or item.get("artifact_marker") == "owtv_published_trace_v1":
        return "published_trace"
    if src == "publisher":
        return "publisher_record"
    if src.startswith("published") or src.startswith("artifact_published"):
        return "published_file"
    if record_slug(item):
        return "artifact_slug"
    return "unknown_source"

ENTITY_ONLY_TOKENS = {
    "wwe", "aew", "nxt", "tna", "roh", "john", "cena", "drew", "mcintyre",
    "punk", "sheamus", "cody", "rhodes", "roman", "reigns", "seth", "rollins",
    "becky", "lynch", "rhea", "ripley", "cm",
}
ACTION_GROUPS: dict[str, set[str]] = {
    "injury": {"injury", "injured", "health", "surgery", "medical", "backstage"},
    "contract": {"contract", "expires", "extension", "deal", "signed", "signs", "situation"},
    "return": {"return", "returns", "rumor", "rumour", "comeback", "back"},
    "legal": {"legal", "lawsuit", "arrest", "arrested", "charged", "charges", "court"},
    "title": {"title", "champion", "championship", "wins", "win", "won", "defeats", "beats", "crowns"},
    "ratings": {"ratings", "viewership", "demo", "audience"},
    "backstage": {"backstage", "creative", "plans", "development"},
    "reaction": {"reacts", "reaction", "fans", "social", "photo", "gym", "post"},
}
INCOMPATIBLE_ACTIONS = {
    frozenset(("injury", "contract")), frozenset(("return", "reaction")),
    frozenset(("title", "reaction")), frozenset(("ratings", "backstage")),
    frozenset(("legal", "return")), frozenset(("legal", "reaction")),
}

def title_similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))

def action_labels(title: str) -> set[str]:
    tt = tokens(title)
    return {label for label, words in ACTION_GROUPS.items() if tt & words}

def substantive_overlap(a: str, b: str) -> set[str]:
    return (tokens(a) & tokens(b)) - ENTITY_ONLY_TOKENS

def action_compatible(feed_title: str, pub_title: str) -> bool:
    feed_actions = action_labels(feed_title)
    pub_actions = action_labels(pub_title)
    if not feed_actions or not pub_actions:
        return False
    if any(frozenset((a, b)) in INCOMPATIBLE_ACTIONS for a in feed_actions for b in pub_actions):
        return False
    return bool(feed_actions & pub_actions)

def reliable_alternate_title_match(feed_title: str, pub_title: str) -> bool:
    shared_substantive = substantive_overlap(feed_title, pub_title)
    if not shared_substantive:
        return False
    if not action_compatible(feed_title, pub_title):
        return False
    # Require strong overlap after also confirming an event/action token. This
    # prevents entity-only matches such as "John Cena injury" vs "John Cena contract".
    sim = title_similarity(feed_title, pub_title)
    if sim >= 0.75:
        return True
    actions = action_labels(feed_title) & action_labels(pub_title)
    # Short hard-news titles often share one entity plus one decisive action
    # token (e.g. Sheamus + contract, CM Punk + title). Allow those only for
    # compatible hard-news action families, not reactions/social posts.
    return sim >= 0.66 and bool(actions & {"contract", "title", "injury", "legal", "return"})

def find_alternate_published_match(t: Trace, published_records: list[dict[str, Any]], published_by_slug: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    slug = canonical_slug(t.final_title or t.title)
    if slug and slug in published_by_slug:
        return published_by_slug[slug]
    best = None
    best_score = 0.0
    for p in published_records:
        pt = str(first(p, "title_it", "title", "source_title") or "")
        if not reliable_alternate_title_match(t.title, pt):
            continue
        sim = title_similarity(t.title, pt)
        if sim > best_score:
            best, best_score = p, sim
    return best

def is_low_value_or_report_candidate(t: Trace) -> bool:
    blob = f"{t.title} {t.massy_decision} {t.massy_reason} {t.kind_hint} {t.menzo_decision} {t.menzo_reason} {t.article_type} {t.priority_label}".lower()
    if "report_candidate" in blob or "simone" in blob:
        return True
    if GENERIC_RECAP_DUPLICATE_RE.search(blob):
        return True
    if re.search(r"low[-_ ]?value|low_score|soft reaction|reaction|listicle|source not preferred|hard_skip|hard skip memory|expired|promo|podcast|recap", blob):
        return True
    if SOFT_RE.search(blob) or str(t.article_type).lower() in SOFT_TYPES:
        return True
    return False

def is_already_published_trace(t: Trace) -> bool:
    return bool(re.search(r"url_already_published|already_published|already_worked|already_seen", f"{t.massy_decision} {t.massy_reason} {t.kind_hint} {t.menzo_reason}", re.I))

def is_relevant_unpublished_candidate(t: Trace) -> bool:
    blob = f"{t.title} {t.menzo_reason} {t.article_type} {t.priority_label}".lower()
    if t.score is not None and t.score >= 80:
        return True
    if str(t.priority_label).lower() in {"high", "critical", "hard"}:
        return True
    if str(t.article_type).lower() in HARD_TYPES:
        return True
    if HARD_RE.search(blob):
        return True
    return False

def classify_comparison(t: Trace, exact: bool, alternate: bool, duplicate_survivor_found: bool = False) -> str:
    if exact:
        return "published_exact_source_url"
    if is_already_published_trace(t):
        return "already_published_before_window_or_seen_again"
    if DUPLICATE_LOSER_RE.search(f"{t.menzo_reason} {t.duplicate_reason}") and duplicate_survivor_found:
        return "duplicate_loser_covered"
    if alternate:
        return "published_by_alternate_source_or_slug"
    if is_relevant_unpublished_candidate(t):
        return "candidate_not_published_review"
    if is_low_value_or_report_candidate(t):
        return "skipped_correctly_likely"
    if t.trace_status in {"skipped", "report_candidate", "already_seen"}:
        return "skipped_correctly_likely"
    return "unknown_needs_trace"

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

SHOW_FAMILIES = {
    "raw": re.compile(r"\b(wwe\s+raw|raw|monday\s+night\s+raw)\b", re.I),
    "smackdown": re.compile(r"\b(smackdown|friday\s+night\s+smackdown)\b", re.I),
    "nxt": re.compile(r"\bnxt\b", re.I),
    "dynamite": re.compile(r"\b(aew\s+dynamite|dynamite)\b", re.I),
    "collision": re.compile(r"\b(aew\s+collision|collision)\b", re.I),
    "impact": re.compile(r"\b(tna\s+impact|impact\s+wrestling|tna|impact)\b", re.I),
}
RAW_SPECIFIC_RE = re.compile(r"\b(wwe\s+raw|raw|monday\s+night\s+raw|raw\s+results?|results?\s+.*raw|title\s+(?:change|match)|main\s+event|new\s+champion|wins?\s+(?:the\s+)?title)\b", re.I)
GENERAL_NON_RAW_RE = re.compile(r"\b(aew|dynamite|collision|tko|business|earnings|contract|backstage|roster update|media rights)\b", re.I)

def show_family(text: str) -> str:
    for family, rx in SHOW_FAMILIES.items():
        if rx.search(text):
            return family
    return ""

def article_matches_report_family(report_text: str, article_text: str) -> bool:
    rfamily = show_family(report_text)
    afamily = show_family(article_text)
    if rfamily and afamily and rfamily != afamily:
        return False
    if rfamily == "raw":
        if re.search(r"\b(aew\s+dynamite|dynamite|aew)\b", article_text, re.I):
            return False
        if RAW_SPECIFIC_RE.search(article_text):
            return True
        return False if GENERAL_NON_RAW_RE.search(article_text) else False
    return bool(rfamily and afamily == rfamily)

def report_label(title: str) -> str:
    if GENERIC_RECAP_DUPLICATE_RE.search(title):
        return "duplicate_recap_risk"
    return ""

def report_show_date(text: str, row: dict[str, Any]) -> str:
    explicit = parse_dt(first(row, "show_date", "event_date", "episode_date"))
    if explicit:
        return explicit.date().isoformat()
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else (parse_dt(first(row, "published_at", "generated_at", "created_at")) or utc_now()).year
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day, tzinfo=timezone.utc).date().isoformat()
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})\s+(?:di\s+)?(" + "|".join(ITALIAN_MONTHS) + r")(?:\s+(\d{4}))?\b", text, re.I)
    if m:
        day, month = int(m.group(1)), ITALIAN_MONTHS[m.group(2).lower()]
        year = int(m.group(3)) if m.group(3) else (parse_dt(first(row, "published_at", "generated_at", "created_at")) or utc_now()).year
        try:
            return datetime(year, month, day, tzinfo=timezone.utc).date().isoformat()
        except ValueError:
            pass
    dt = parse_dt(first(row,"published_at","generated_at","created_at"))
    return dt.date().isoformat() if dt else ""

def report_thread_key(r: dict[str, Any]) -> str:
    text = str(first(r,"title","show","show_name") or "")
    fam = show_family(text)
    day = report_show_date(text, r)
    if fam and day:
        return f"{fam}:{day}"
    if fam:
        return f"{fam}:{re.sub(r'[^a-z0-9]+', '-', text.lower())[:40]}"
    return re.sub(r"[^a-z0-9]+", "-", text.lower())[:40]

def dedupe_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in reports:
        key = report_thread_key(r)
        current = out.get(key)
        is_pub = bool(first(r, "wp_link", "published_url", "final_url")) or str(first(r, "status", "outcome") or "").lower() in PUBLISHED_STATUSES
        cur_pub = bool(current and (first(current, "wp_link", "published_url", "final_url") or str(first(current, "status", "outcome") or "").lower() in PUBLISHED_STATUSES))
        if current is None or (is_pub and not cur_pub):
            out[key] = r
    return list(out.values())

def report_overlap(pubs: list[dict[str,Any]], reports: list[dict[str,Any]]) -> list[dict[str,Any]]:
    risks=[]
    for r in reports:
        rt=parse_dt(first(r,"published_at","generated_at","created_at")) or utc_now()
        rtitle=str(first(r,"title","show","show_name") or "report")
        rbody=str(first(r,"body","content","html","summary") or "")
        report_text = rtitle + " " + rbody
        for p in pubs:
            title=str(first(p,"title_it","title","source_title") or "")
            article_text = title + " " + str(first(p,"body","content","summary") or "")
            if not article_matches_report_family(report_text, article_text):
                continue
            if abs(((parse_dt(first(p,"published_at","created_at")) or rt)-rt).total_seconds()) <= 24*3600:
                cls=report_label(title)
                if cls:
                    risks.append({"report":rtitle,"title":title,"classification":cls})
    return risks


def is_report_publication_record(item: dict[str, Any], source_hint: str = "") -> bool:
    if first(item, "source_url", "url"):
        return False
    blob = " ".join(str(first(item, key) or item.get(key) or "") for key in ("type", "kind", "category", "article_type", "report_type", "status", "title", "title_it", "show", "show_name", "path", "file", "filename"))
    blob = f"{source_hint} {blob}"
    return bool(REPORT_PUBLICATION_RE.search(blob) and (show_family(blob) or "simone" in blob.lower() or "report" in blob.lower()))

def is_published_record(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").lower()
    if status in PUBLISHED_STATUSES:
        return True
    if status in UNPUBLISHED_STATUSES:
        return False
    return bool(first(item, "wp_link", "published_url", "final_url", "path") and status not in {"wp_not_ready", "publish_error", "skipped_capacity"})

def massy_status(decision: str, assigned: str, kind: str, reason: str) -> str:
    blob = f"{decision} {assigned} {kind} {reason}".lower()
    if "report_candidate" in blob or assigned.lower() == "simone":
        return "report_candidate"
    if "already_worked" in blob or "already_seen" in blob or "already_published" in blob:
        return "already_seen"
    if "hard_skip" in blob:
        return "skipped"
    return ""


ARTIFACT_TIMESTAMP_KEYS = (
    "generated_at", "timestamp", "created_at", "run_started_at",
    "run_finished_at", "started_at", "finished_at", "window_start",
    "window_end", "published_at", "run_at",
)

def embedded_dt(obj: Any) -> datetime | None:
    if not isinstance(obj, dict):
        return None
    return parse_dt(first(obj, *ARTIFACT_TIMESTAMP_KEYS))

def file_in_window(path: Path, obj: Any, since: datetime, until: datetime) -> tuple[bool, datetime | None, str]:
    dt = embedded_dt(obj)
    if dt is not None:
        return since <= dt <= until, dt, "embedded"
    try:
        mt = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except Exception:
        return False, None, "none"
    return since <= mt <= until, mt, "mtime"

def useful_stage_count(bundle: dict[str, Any]) -> int:
    return sum(len(v) for stage in bundle.values() for v in stage.values() if isinstance(v, list))

def row_with_parent_timestamp(item: dict[str, Any], parent_dt: datetime | None) -> dict[str, Any]:
    row = dict(item)
    if parent_dt is not None and embedded_dt(row) is None:
        row["generated_at"] = parent_dt.isoformat()
    return row

def merge_stage(dest: dict[str, Any], src: dict[str, Any], keys: list[str], parent_dt: datetime | None = None) -> int:
    added = 0
    for key in keys:
        val = src.get(key)
        if isinstance(val, list):
            rows = [row_with_parent_timestamp(x, parent_dt) for x in val if isinstance(x, dict)]
            if rows:
                dest.setdefault(key, []).extend(rows)
                added += len(rows)
    return added

def collect_window_artifacts(since: datetime, until: datetime, warnings: list[str]) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    """Aggregate historical per-run newsroom artifacts in the audit window.

    Returns a stage bundle plus whether any historical run artifact was found.
    """
    bundle: dict[str, Any] = {
        "massy": {}, "menzo": {}, "bob": {}, "andrea": {},
        "alfred": {}, "publisher": {}, "simone": {}, "simpub": {},
    }
    roots = [ARTIFACTS / "newsroom_runs", ARTIFACTS / "newsroom", NEWSROOM]
    latest_re = re.compile(r"_latest\.json$", re.I)
    found = False
    diag = {"historical_files_scanned": 0, "historical_files_inside_window": 0, "merged_by_stage": {k: 0 for k in bundle}}
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*.json"):
            diag["historical_files_scanned"] += 1
            if not path.is_file() or latest_re.search(path.name):
                continue
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                warnings.append(f"unreadable_historical_artifact: {path}: {exc}")
                continue
            if not isinstance(obj, dict):
                continue
            parent_ok, parent_dt, timestamp_source = file_in_window(path, obj, since, until)
            if not parent_ok:
                continue
            diag["historical_files_inside_window"] += 1
            if path.is_relative_to(ARTIFACTS / "newsroom") and timestamp_source != "embedded":
                # artifacts/newsroom also contains generic diagnostic snapshots;
                # require an embedded run timestamp there so mtime-only ad-hoc
                # snapshots are not mistaken for historical run coverage.
                continue
            name = path.name.lower()
            # Also recognize run bundles that carry multiple stage keys.
            run_obj = obj.get("newsroom") if isinstance(obj.get("newsroom"), dict) else obj
            before_count = useful_stage_count(bundle)
            if "massy" in name or any(k in run_obj for k in ["news_candidates_for_menzo", "report_candidates", "hard_skipped", "already_worked"]):
                if any(k in run_obj for k in ["news_candidates_for_menzo", "report_candidates", "hard_skipped", "already_worked", "items", "entries"]):
                    merge_stage(bundle["massy"], run_obj, ["news_candidates_for_menzo", "report_candidates", "hard_skipped", "already_worked", "items", "entries"], parent_dt)
                elif first(run_obj, "url", "source_url"):
                    bundle["massy"].setdefault("news_candidates_for_menzo", []).append(row_with_parent_timestamp(run_obj, parent_dt))
            if "menzo" in name or any(k in run_obj for k in ["selected", "pending", "skipped"]):
                merge_stage(bundle["menzo"], run_obj, ["selected", "pending", "skipped"], parent_dt)
            if "andrea" in name:
                merge_stage(bundle["andrea"], run_obj, ["blocked_items", "passed_items", "selected", "items", "results"], parent_dt)
            if "bob" in name or "articles" in run_obj:
                merge_stage(bundle["bob"], run_obj, ["articles"], parent_dt)
            if "alfred" in name or any(k in run_obj for k in ["reviews", "approved_articles"]):
                merge_stage(bundle["alfred"], run_obj, ["reviews", "approved_articles"], parent_dt)
            if "simone_report_publish" not in name and ("publisher" in name or any(k in run_obj for k in ["results", "skipped_approved_articles"])):
                if any(k in run_obj for k in ["results", "skipped_approved_articles"]):
                    if timestamp_source == "embedded":
                        merge_stage(bundle["publisher"], run_obj, ["results", "skipped_approved_articles"], parent_dt)
                    else:
                        for key in ["results", "skipped_approved_articles"]:
                            rows = [x for x in run_obj.get(key, []) if isinstance(x, dict) and embedded_dt(x) is not None]
                            if rows:
                                bundle["publisher"].setdefault(key, []).extend(rows)
                elif is_published_record(run_obj) or first(run_obj, "source_url", "url"):
                    if timestamp_source == "embedded" or embedded_dt(run_obj) is not None:
                        bundle["publisher"].setdefault("results", []).append(row_with_parent_timestamp(run_obj, parent_dt))
            if "simone_report_publish" in name:
                merge_stage(bundle["simpub"], run_obj, ["results", "published_reports", "reports"], parent_dt)
            elif "simone" in name or any(k in run_obj for k in ["reports", "report_candidates"]):
                merge_stage(bundle["simone"], run_obj, ["reports", "report_candidates"], parent_dt)
            after_count = useful_stage_count(bundle)
            if after_count > before_count:
                found = True
                for stage in bundle:
                    diag["merged_by_stage"][stage] = sum(len(v) for v in bundle[stage].values() if isinstance(v, list))
    return bundle, found, diag

def build_audit(hours: int, root: Path = ROOT) -> tuple[str, Path]:
    global ROOT, STATE, NEWSROOM, ARTIFACTS
    ROOT=root; STATE=root/"state"; NEWSROOM=STATE/"newsroom"; ARTIFACTS=root/"artifacts"
    until=utc_now(); since=until-timedelta(hours=hours); warnings=[]
    historical, has_historical, hist_diag = collect_window_artifacts(since, until, warnings)
    mode = "historical_window" if has_historical else "latest_snapshot_fallback"
    if has_historical:
        massy=historical["massy"]; menzo=historical["menzo"]; bob=historical["bob"]; andrea=historical["andrea"]
        alfred=historical["alfred"]; publisher=historical["publisher"]; simone=historical["simone"]; simpub=historical["simpub"]
    else:
        warnings.append("mode: latest_snapshot_fallback - published coverage may be incomplete because no historical per-run artifacts were found")
        massy=load_json(NEWSROOM/"massy_board_latest.json", warnings, {})
        menzo=load_json(NEWSROOM/"menzo_decisions_latest.json", warnings, {})
        bob=load_json(NEWSROOM/"bob_articles_latest.json", warnings, {})
        andrea=load_json(NEWSROOM/"andrea_pre_bob_latest.json", warnings, {})
        alfred=load_json(NEWSROOM/"alfred_review_latest.json", warnings, {})
        publisher=load_json(NEWSROOM/"publisher_status_latest.json", warnings, {})
        simone=load_json(NEWSROOM/"simone_reports_latest.json", warnings, {})
        simpub=load_json(NEWSROOM/"simone_report_publish_latest.json", warnings, {})
        simone_dt = embedded_dt(simone)
        simpub_dt = embedded_dt(simpub)
        if simone_dt:
            simone = {**simone, **{key: [row_with_parent_timestamp(x, simone_dt) for x in val] for key, val in simone.items() if isinstance(val, list)}}
        if simpub_dt:
            simpub = {**simpub, **{key: [row_with_parent_timestamp(x, simpub_dt) for x in val] for key, val in simpub.items() if isinstance(val, list)}}
    for extra in ["archivista_report_latest.json","gemini_call_ledger.jsonl","report_publication_registry.json"]:
        if not (NEWSROOM/extra).exists(): warnings.append(f"missing_input: state/newsroom/{extra}")
    for extra in ["manual_runs.json","report_status.json"]:
        if not (STATE/extra).exists(): warnings.append(f"missing_input: state/{extra}")
    for extra in ["skipped_history.json","history.txt"]:
        if not (root/extra).exists(): warnings.append(f"missing_optional_input: {extra}")

    feed_items=iter_items(massy,["news_candidates_for_menzo","report_candidates","hard_skipped","already_worked","items","entries"])
    monitored_feed_urls = {
        norm_url(first(it,"url","source_url","link"))
        for it in feed_items
        if url_is_monitored(first(it,"url","source_url","link"))
    }
    monitored_mode = bool(monitored_feed_urls)
    if monitored_mode:
        feed_items=[it for it in feed_items if norm_url(first(it,"url","source_url","link")) in monitored_feed_urls]
    traces: dict[str,Trace]={}
    for it in feed_items:
        if not in_window(it,since,until): continue
        u=norm_url(first(it,"url","source_url","link"));
        if not u: continue
        massy_decision=str(first(it,"decision","kind","kind_hint") or "")
        assigned=str(it.get("assigned_to") or "")
        traces[u]=Trace(url=u, source=str(first(it,"source","source_id","feed") or ""), title=str(first(it,"title","source_title") or ""), published_at=str(first(it,"published","published_at") or ""), massy_decision=massy_decision, massy_reason=str(first(it,"reason","original_report_reason","skip_reason") or ""), kind_hint=str(first(it,"kind_hint","kind","assigned_to") or ""), score_hint=str(first(it,"score","score_hint") or ""))
        status=massy_status(massy_decision, assigned, traces[u].kind_hint, traces[u].massy_reason)
        if status:
            traces[u].trace_status=status
    menzo_items=iter_items(menzo,["selected","pending","skipped"])
    for it in menzo_items:
        u=norm_url(first(it,"url","source_url"));
        if not u: continue
        if monitored_mode and u not in monitored_feed_urls: continue
        t=traces.setdefault(u, Trace(url=u, title=str(first(it,"title","source_title") or "")))
        t.menzo_decision=str(it.get("decision") or ("selected" if it in menzo.get("selected",[]) else "")); t.menzo_reason=str(first(it,"reason","editorial_reason","ai_editorial_reason") or "")
        try: t.score=int(first(it,"score","ai_priority","deterministic_score") or 0)
        except Exception: pass
        t.priority_label=str(first(it,"ai_priority_label","priority_label","priority") or ""); t.article_type=str(it.get("article_type") or ""); t.duplicate_reason=str(first(it,"duplicate_of","duplicate_reason","event_key") or "")
        if not t.title: t.title=str(first(it,"title","source_title") or "")
    for it in iter_items(andrea,["blocked_items","passed_items","selected","items","results"]):
        u=norm_url(first(it,"source_url","url"));
        if not u: continue
        if monitored_mode and u not in monitored_feed_urls: continue
        t=traces.setdefault(u, Trace(url=u, title=str(first(it,"title","source_title") or "")))
        raw_outcome=str(first(it,"andrea_outcome","status","decision","outcome") or "")
        blocked=bool(first(it,"andrea_blocked_before_bob","blocked_before_bob")) or raw_outcome.lower() in {"blocked","rejected","failed","blocked_before_bob"}
        t.andrea_blocked_before_bob=blocked
        t.andrea_outcome="blocked" if blocked else (raw_outcome or "passed")
        t.andrea_reason=str(first(it,"reason","andrea_reason","block_reason","guard_reason") or "")
    for it in iter_items(bob,["articles"]):
        u=norm_url(first(it,"source_url","url"));
        if u in traces: traces[u].bob_outcome=str(it.get("status") or "generated")
    for rev in iter_items(alfred,["reviews","approved_articles"]):
        art=rev.get("approved_article") if isinstance(rev.get("approved_article"),dict) else rev
        u=norm_url(first(art,"source_url","url"));
        if u in traces: traces[u].alfred_outcome=str(rev.get("decision") or "approved")
    publisher_records=[{**item, "_pub_source":"publisher"} for item in iter_items(publisher,["results","skipped_approved_articles"]) if not is_report_publication_record(item, "publisher")]
    trace_pubs=extract_published_traces(since,until)
    file_pubs=extract_published_from_files(since,until)
    file_pubs=[item for item in file_pubs if not is_report_publication_record(item, str(first(item, "_pub_source", "path")))]
    all_pub_candidates=trace_pubs+publisher_records+file_pubs
    publisher_before=sum(1 for item in publisher_records if is_published_record(item))
    publisher_after=len(dedupe_published_records(publisher_records))
    trace_before=sum(1 for item in trace_pubs if is_published_record(item))
    trace_with_source=sum(1 for item in trace_pubs if norm_url(first(item, "source_url", "url")))
    file_before=sum(1 for item in file_pubs if is_published_record(item))
    file_after=len(dedupe_published_records(file_pubs))
    published_records=dedupe_published_records(all_pub_candidates)
    published_urls, published_by_url, published_by_slug = build_published_indexes(published_records)
    for it in all_pub_candidates:
        u=norm_url(first(it,"source_url","url"));
        if u:
            if monitored_mode and u not in monitored_feed_urls: continue
            t=traces.setdefault(u, Trace(url=u, title=str(first(it,"title_it","title") or "")))
            t.publisher_outcome=str(it.get("status") or "published_file"); t.final_title=str(first(it,"title_it","title") or t.title); t.final_url=str(first(it,"wp_link","published_url","final_url","path") or "")
    for t in traces.values():
        matched_trace = published_by_url.get(t.url)
        exact_match = matched_trace is not None
        alternate_match = None
        if not matched_trace:
            alternate_match = find_alternate_published_match(t, published_records, published_by_slug)
            matched_trace = alternate_match
        published=t.publisher_outcome in {"published","already_published","published_file"} or bool(t.final_url and t.publisher_outcome not in {"wp_not_ready","publish_error","skipped_capacity","skipped"}) or exact_match or alternate_match is not None
        if published:
            if not t.publisher_outcome:
                t.publisher_outcome="published_trace"
            if matched_trace:
                t.final_title=t.final_title or str(first(matched_trace,"title_it","title","source_title") or "")
                t.final_url=t.final_url or str(first(matched_trace,"wp_link","published_url","final_url","path","url") or "")
            t.trace_status="published"
        elif t.andrea_blocked_before_bob: t.trace_status="blocked_by_andrea"
        elif t.menzo_decision=="skip": t.trace_status="skipped"
        elif t.menzo_decision=="pending": t.trace_status="pending"
        elif t.trace_status in {"report_candidate", "already_seen", "skipped"}: pass
        elif t.kind_hint=="report_candidate": t.trace_status="report_candidate"
        elif re.search("already", f"{t.kind_hint} {t.menzo_reason} {t.massy_decision} {t.massy_reason}", re.I): t.trace_status="already_seen"
        else: t.trace_status="unknown"
        survivor = False
        if DUPLICATE_LOSER_RE.search(f"{t.menzo_reason} {t.duplicate_reason}"):
            survivor = bool(t.duplicate_reason and (norm_url(t.duplicate_reason) in published_urls or canonical_slug(t.duplicate_reason) in published_by_slug))
            if not survivor:
                tt = tokens(t.title)
                survivor = any(len(tt & tokens(str(first(p,"title_it","title","source_title") or ""))) >= 2 for p in published_records)
        t.recall_class=classify(t,published,survivor)
        t.comparison_class=classify_comparison(t, exact_match, alternate_match is not None, survivor)
        if exact_match:
            t.published_match_method="source_url"
        elif alternate_match is not None:
            t.published_match_method="slug_or_title"
    if monitored_mode:
        traces={u: t for u, t in traces.items() if u in monitored_feed_urls}
    trace_list=sorted(traces.values(), key=lambda x:(x.trace_status,x.source,x.title))
    missed=[t for t in trace_list if t.trace_status!="published" and t.recall_class in {"must_publish_candidate","should_publish_candidate"}]
    soft=[t for t in trace_list if t.trace_status=="published" and t.recall_class=="optional_soft"]
    over=overcoverage(published_records)
    reports=dedupe_reports(iter_items(simone,["reports","report_candidates"])+iter_items(simpub,["results","published_reports","reports"]))
    overlaps=report_overlap(published_records,reports)
    def c(status): return sum(1 for t in trace_list if t.trace_status==status)
    def esc(s: Any) -> str:
        return str(s or "").replace("|","/").replace("\n", " ")[:220]
    missing_source_pubs = [p for p in published_records if not norm_url(first(p, "source_url", "url"))]
    exact_count = sum(1 for t in trace_list if t.comparison_class == "published_exact_source_url")
    alt_count = sum(1 for t in trace_list if t.comparison_class == "published_by_alternate_source_or_slug")
    skipped_count = sum(1 for t in trace_list if t.comparison_class in {"skipped_correctly_likely", "already_published_before_window_or_seen_again", "duplicate_loser_covered"})
    review = [t for t in trace_list if t.comparison_class == "candidate_not_published_review"]
    lines=[f"# OWTV Feed vs Published Comparison Audit v95.8.5", "", f"Artifact marker: `{MARKER}`", f"Window: {hours}h ({since.isoformat()} → {until.isoformat()} UTC)", f"mode: {mode}", "", "Diagnostic-only. This report compares the monitored feed inventory with published OWTV inventory; it does not change publishing behavior.", ""]

    lines += ["## 1. Feed inventory", "", "| source | source_title | source_url | feed_published_at | Massy disposition | Massy reason | Menzo decision if available | Menzo reason if available | score if available | priority if available | article_type if available | trace status |", "|---|---|---|---|---|---|---|---|---:|---|---|---|"]
    for t in trace_list:
        lines.append(f"| {esc(t.source)} | {esc(t.title)} | {esc(t.url)} | {esc(t.published_at)} | {esc(t.massy_decision or t.kind_hint)} | {esc(t.massy_reason)} | {esc(t.menzo_decision)} | {esc(t.menzo_reason)} | {t.score if t.score is not None else ''} | {esc(t.priority_label)} | {esc(t.article_type)} | {esc(t.trace_status)} |")

    lines += ["", "## 2. Published inventory", "", "| OWTV title | OWTV slug or URL if available | source | source_url if available | source_title if available | published_at if available | recovery method |", "|---|---|---|---|---|---|---|"]
    for p in published_records:
        src_url = norm_url(first(p, "source_url", "url"))
        slug_or_url = first(p, "wp_link", "published_url", "final_url") or record_slug(p) or first(p, "path", "file", "filename")
        lines.append(f"| {esc(first(p,'title_it','title','final_title') or record_slug(p))} | {esc(slug_or_url)} | {esc(first(p,'source','source_id','feed') or 'unknown')} | {esc(src_url or 'source_url_missing')} | {esc(first(p,'source_title','original_title'))} | {esc(first(p,'published_at','created_at','generated_at'))} | {published_recovery_method(p)} |")

    lines += ["", "## 3. Feed-to-published comparison", "", "| source | source_title | source_url | comparison classification | published match method | reason |", "|---|---|---|---|---|---|"]
    for t in trace_list:
        reason = ", ".join(t.why) or t.menzo_reason or t.massy_reason or t.trace_status
        lines.append(f"| {esc(t.source)} | {esc(t.title)} | {esc(t.url)} | {t.comparison_class} | {esc(t.published_match_method)} | {esc(reason)} |")

    lines += ["", "## 4. Editorial review list", "", "This is the short human list answering: **What might we have missed?**", ""]
    lines += ([f"- **{esc(t.title or t.url)}** ({esc(t.source)}) — {esc(t.url)} — {esc(', '.join(t.why) or t.menzo_reason or t.massy_reason or 'relevance signal with no published match')}" for t in review] or ["- None detected."])

    lines += ["", "## 5. Published without source attribution", "", "These are trace-quality issues, not editorial misses.", ""]
    lines += ([f"- **{esc(first(p,'title_it','title','final_title') or record_slug(p))}** — {esc(first(p,'wp_link','published_url','final_url') or record_slug(p) or first(p,'path','file','filename'))} — recovery_method={published_recovery_method(p)} — source_url_missing" for p in missing_source_pubs] or ["- None detected."])

    lines += ["", "## 6. Summary", "", f"- total feed URLs seen: {len(trace_list)}", f"- total published articles: {len(published_records)}", f"- published trace records found: {trace_before}", f"- published trace records with source_url: {trace_with_source}", f"- published file fallback records used: {file_before}", f"- feed URLs exactly matched to published: {exact_count}", f"- feed URLs covered by alternate/slug match: {alt_count}", f"- feed URLs skipped correctly: {skipped_count}", f"- feed URLs requiring human review: {len(review)}", f"- published articles missing source attribution: {len(missing_source_pubs)}", "", "### Legacy summary compatibility", "", f"- Feed URLs seen: {len(trace_list)}", f"- Feed URLs with Menzo decision: {sum(1 for t in trace_list if t.menzo_decision)}", f"- Feed URLs published: {c('published')}", f"- Feed URLs skipped: {c('skipped')}", f"- Feed URLs pending: {c('pending')}", f"- Feed URLs unknown/untracked: {c('unknown')}", f"- Potential must-publish missed: {sum(1 for t in missed if t.recall_class=='must_publish_candidate')}", f"- Potential should-publish missed: {sum(1 for t in missed if t.recall_class=='should_publish_candidate')}", f"- Potential overpublished soft items: {len(soft)}", f"- Potential story-thread overcoverage: {len(over)}", f"- Post-show duplicate recap risks: {len(overlaps)}", "", "## 7. Secondary diagnostics (demoted)", "", "### Coverage funnel", "", "| Stage | Count |", "|---|---:|", f"| Massy feed URLs | {len(trace_list)} |", f"| Menzo evaluated | {sum(1 for t in trace_list if t.menzo_decision)} |", f"| Final published | {len(published_records)} |", ""]
    lines += ["### Historical artifact discovery diagnostics", "", "| Diagnostic | Count |", "|---|---:|", f"| Historical files scanned | {hist_diag['historical_files_scanned']} |", f"| Historical files inside window | {hist_diag['historical_files_inside_window']} |"]
    for label, key in [("Massy", "massy"), ("Menzo", "menzo"), ("Andrea", "andrea"), ("Bob", "bob"), ("Alfred", "alfred"), ("Publisher", "publisher"), ("Simone", "simone"), ("Simone publish", "simpub")]:
        lines.append(f"| Useful {label} records merged | {hist_diag['merged_by_stage'].get(key, 0)} |")
    lines += [f"| Publisher published records before dedupe | {publisher_before} |", f"| Publisher published records after dedupe | {publisher_after} |", f"| Published trace records found | {trace_before} |", f"| Published trace records with source_url | {trace_with_source} |", f"| Published file artifacts before dedupe | {file_before} |", f"| Published file artifacts after dedupe | {file_after} |", "", "### Legacy recall classes", "", "| source | source_title | source_url | massy | andrea | trace_status | editorial_recall_class | comparison_class |", "|---|---|---|---|---|---|---|---|"]
    for t in trace_list:
        lines.append(f"| {esc(t.source)} | {esc(t.title)} | {esc(t.url)} | {esc('/'.join(x for x in [t.massy_decision or t.kind_hint, t.massy_reason, t.score_hint] if x))} | {esc('/'.join(x for x in [t.andrea_outcome, t.andrea_reason] if x))} | {esc(t.trace_status)} | {t.recall_class} | {t.comparison_class} |")
    dup_rows=[t for t in trace_list if DUPLICATE_LOSER_RE.search(f"{t.menzo_reason} {t.duplicate_reason}")]
    lines += ["", "### Duplicate loser review notes", ""] + ([f"- {t.comparison_class}: {t.title} — {t.url}; duplicate loser; verify survivor coverage" for t in dup_rows] or ["- None."])
    lines += ["", "### Potential missed stories (legacy)", ""] + ([f"- **{t.title or t.url}** ({t.source}) — {t.url} — potential_miss: {', '.join(t.why) or 'review signal'}; skipped/trace reason: {t.menzo_reason or t.trace_status}" for t in missed] or ["- None detected."])
    lines += ["", "## 6. Potential overpublished soft items", ""] + ([f"- **{t.final_title or t.title}** — possible_overpublished_soft_item: {', '.join(t.why)} — {t.url}" for t in soft] or ["- None detected."])
    lines += ["", "### Story thread overcoverage", ""] + ([f"- **{r['label']}** ({r['count']} published) — {r['reason']}; titles: " + "; ".join(str(first(i,'title_it','title','source_title')) for i in r['items']) for r in over] or ["- None detected by fallback grouping; latest story cluster audit, if present, should be reviewed separately."])
    lines += ["", "## 8. Post-show duplicate recap risks", ""] + ([f"- Report `{o['report']}` vs `{o['title']}` — {o['classification']}" for o in overlaps] or ["- None detected."])
    lines += ["", "### Source coverage", "", "| source | seen | published | skipped | pending | unknown | publish rate | possible missed high-value |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for src in sorted({t.source or 'unknown' for t in trace_list}):
        rows=[t for t in trace_list if (t.source or 'unknown')==src]; pub=sum(1 for t in rows if t.trace_status=='published')
        lines.append(f"| {src} | {len(rows)} | {pub} | {sum(1 for t in rows if t.trace_status=='skipped')} | {sum(1 for t in rows if t.trace_status=='pending')} | {sum(1 for t in rows if t.trace_status=='unknown')} | {pub/len(rows):.0%} | {sum(1 for t in rows if t in missed)} |")
    lines += ["", "### Category/type coverage", "", "| type/category | count |", "|---|---:|"]
    for typ in sorted({(t.article_type or ('report' if t.trace_status=='report_candidate' else 'unknown')) for t in trace_list}): lines.append(f"| {typ} | {sum(1 for t in trace_list if (t.article_type or ('report' if t.trace_status=='report_candidate' else 'unknown'))==typ)} |")
    lines += ["", "### Human review samples", "", "### Top skipped candidates to review"] + ([f"- {t.recall_class}: {t.title} — {t.url}" for t in missed[:5]] or ["- None."])
    published_samples = soft[:5] or [t for t in trace_list if t.trace_status=="published"][:5]
    lines += ["", "### Top published candidates to quality-check"] + ([f"- {t.recall_class}: {t.final_title or t.title} — {t.url or 'source_url_unavailable'}" for t in published_samples] or ["- None."])
    lines += ["", "### Top overcoverage candidates"] + ([f"- {r['label']} ({r['count']})" for r in over[:5]] or ["- None."])
    lines += ["", "### Top unknown/untracked URLs"] + ([f"- {t.title} — {t.url}" for t in trace_list if t.trace_status=='unknown'][:5] or ["- None."])
    lines += ["", "## Input warnings", ""] + ([f"- {w}" for w in warnings] or ["- None."])
    outdir=Path(os.getenv("OWTV_REPORTS_DIR") or DEFAULT_REPORTS_DIR); outdir.mkdir(parents=True, exist_ok=True)
    out=outdir/f"owtv_feed_coverage_audit_v95_8_{hours}h_{until.strftime('%Y%m%dT%H%M%SZ')}.md"
    text="\n".join(lines)+"\n"; out.write_text(text, encoding="utf-8")
    return text,out

def main() -> int:
    ap=argparse.ArgumentParser(description="OWTV v95.8 feed coverage editorial recall audit")
    ap.add_argument("hours", nargs="?", type=int, default=24, choices=[12,24,48,72,168])
    args=ap.parse_args(); _, out=build_audit(args.hours); print(out); return 0
if __name__ == "__main__": raise SystemExit(main())
