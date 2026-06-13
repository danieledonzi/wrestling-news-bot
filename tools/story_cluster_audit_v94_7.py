#!/usr/bin/env python3
"""OpenWrestlingTV v94.7 - diagnostic story cluster audit.

This tool is intentionally read-only. It does not affect Menzo decisions,
Publisher output, WordPress posts, or any runtime state.

It inspects locally generated final review artifacts, compares published items
inside a time window, and writes a Markdown/JSON report with suspected editorial
clusters. The purpose is to understand why strict story fingerprint/footprint
counters can stay at zero while the home page still feels dominated by related
storylines.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLISHED_DIR = ROOT / "published_html_review"
DEFAULT_REPORT_DIR = ROOT / "reports"

try:
    from agents.story_dedupe_v93_32 import build_generalized_fingerprint, fingerprint_similarity
except Exception:  # pragma: no cover - diagnostic fallback
    build_generalized_fingerprint = None
    fingerprint_similarity = None

TAG_RE = re.compile(r"<[^>]+>")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "after", "before", "during",
    "report", "reports", "news", "update", "updates", "spoiler", "rumor", "rumors",
    "wwe", "aew", "tna", "nxt", "roh", "aaa", "cmll", "njpw", "stardom",
    "del", "della", "dello", "delle", "degli", "dei", "dal", "dalla", "allo", "alla",
    "con", "per", "tra", "sul", "sulla", "sullo", "sulle", "sugli", "gli", "nel",
    "nella", "nelle", "dopo", "prima", "durante", "questa", "questo", "quella", "quello",
    "una", "uno", "dei", "gli", "alle", "dagli", "dagli", "come", "piu", "più",
    "match", "titolo", "title", "show", "evento", "event", "sera", "questa", "questa sera",
}

EVENT_TERMS = {
    "raw", "smackdown", "dynamite", "collision", "impact", "summerslam", "slammiversary",
    "forbidden", "door", "nxt", "aaa", "king", "queen", "ring", "owen", "hart", "cup",
    "night", "champions", "money", "bank", "all", "redemption", "lockdown", "bound", "glory",
}

ACTION_KEYWORDS = {
    "injury": {"infortunio", "infortunato", "infortunata", "ginocchio", "collo", "recupero", "chirurgico", "intervento", "ritiro", "ritirato", "sareee"},
    "return": {"ritorno", "rientro", "torna", "tornare", "back", "return", "returns"},
    "contract": {"contratto", "rinnovare", "firmare", "scadenza", "addio", "release", "released"},
    "legal": {"legale", "avvocato", "causa", "aggressione", "vittima", "giustizia", "arbitrato", "lawsuit", "court"},
    "result": {"vince", "sconfigge", "mantiene", "batte", "avanza", "vittoria", "risultati"},
    "booking": {"annunciati", "annunciato", "svelato", "previsto", "piani", "discussioni", "scelto", "sceglie", "card"},
    "reaction": {"commenta", "risponde", "spiega", "rivela", "chiarisce", "furiosi", "preoccupazioni"},
    "business": {"fusione", "accordo", "partnership", "televisivo", "diritti", "distribuzione"},
}


@dataclass
class Article:
    id: str
    path: str
    title: str
    kind: str
    mtime_utc: str
    tokens: list[str]
    entities: list[str]
    actions: list[str]
    events: list[str]
    fingerprint: dict[str, Any]


@dataclass
class Pair:
    a: str
    b: str
    title_a: str
    title_b: str
    score: float
    fingerprint_score: float
    token_score: float
    entity_score: float
    action_score: float
    event_score: float
    cluster_type: str
    reason: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OWTV v94.7 diagnostic story cluster audit")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    parser.add_argument("--since", default="", help="Optional ISO UTC lower bound, e.g. 2026-06-12T10:00:01")
    parser.add_argument("--until", default="", help="Optional ISO UTC upper bound, e.g. 2026-06-13T10:00:01")
    parser.add_argument("--published-dir", default=str(DEFAULT_PUBLISHED_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--min-score", type=float, default=0.45, help="Minimum pair score to include")
    parser.add_argument("--cluster-score", type=float, default=0.58, help="Minimum pair score to connect cluster")
    parser.add_argument("--top-pairs", type=int, default=80)
    return parser.parse_args()


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def strip_tags(value: str) -> str:
    text = TAG_RE.sub(" ", str(value or ""))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def title_from_html(text: str, fallback: str) -> str:
    for rx in (H1_RE, TITLE_RE):
        m = rx.search(text or "")
        if m:
            title = strip_tags(m.group(1))
            title = re.sub(r"\s+[-|].*$", "", title).strip()
            if title:
                return title
    return fallback


def title_from_path(path: Path) -> str:
    stem = path.stem
    for prefix in ("v93_publisher_", "v93-news-", "v93_news_", "v93-publisher-"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
    stem = stem.replace("_", "-")
    return " ".join(w.capitalize() if w not in {"wwe", "aew", "tna", "nxt", "aaa", "cm", "mjf"} else w.upper() for w in stem.split("-"))


def normalize(value: str) -> str:
    text = html.unescape(str(value or "")).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens_for(title: str) -> list[str]:
    words = []
    for w in normalize(title).split():
        if len(w) < 3:
            continue
        if w in STOPWORDS:
            continue
        if w not in words:
            words.append(w)
    return words


def action_tags(tokens: list[str]) -> list[str]:
    s = set(tokens)
    out = [name for name, keys in ACTION_KEYWORDS.items() if s & keys]
    return out or ["general"]


def event_tags(tokens: list[str]) -> list[str]:
    s = set(tokens)
    return sorted(s & EVENT_TERMS)


def entity_terms(tokens: list[str]) -> list[str]:
    # For this diagnostic, use distinctive title tokens as entity candidates.
    # This intentionally catches names missing from the older static ENTITY_HINTS list.
    actions = set().union(*ACTION_KEYWORDS.values())
    ents = [w for w in tokens if w not in actions and w not in EVENT_TERMS and w not in STOPWORDS]
    return ents[:10]


def overlap(a: list[str], b: list[str], *, min_denominator: bool = True) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    denom = min(len(sa), len(sb)) if min_denominator else len(sa | sb)
    return len(sa & sb) / max(1, denom)


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def load_articles(published_dir: Path, since: datetime, until: datetime) -> list[Article]:
    articles: list[Article] = []
    if not published_dir.exists():
        return articles
    for path in sorted(published_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".html", ".json"}:
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < since or mtime > until:
            continue
        fallback = title_from_path(path)
        raw = safe_read(path)
        kind = "report_show" if path.suffix.lower() == ".json" and not path.name.startswith("v93_publisher") else "news"
        title = fallback
        body = raw
        if path.suffix.lower() == ".html":
            title = title_from_html(raw, fallback)
            body = strip_tags(raw)[:8000]
        elif path.suffix.lower() == ".json":
            try:
                data = json.loads(raw)
                for key in ("title", "headline", "post_title", "slug"):
                    if isinstance(data, dict) and data.get(key):
                        title = str(data.get(key))
                        break
                body = json.dumps(data, ensure_ascii=False)[:8000]
            except Exception:
                pass
        toks = tokens_for(title)
        item = {"title": title, "source_title": title, "body_html": body, "url": str(path), "source": "published_html_review"}
        fp = build_generalized_fingerprint(item) if build_generalized_fingerprint else {}
        articles.append(Article(
            id=path.name,
            path=str(path),
            title=title,
            kind=kind,
            mtime_utc=mtime.isoformat(),
            tokens=toks,
            entities=entity_terms(toks),
            actions=action_tags(toks),
            events=event_tags(toks),
            fingerprint=fp,
        ))
    return articles


def classify(score: float, entity_score: float, action_score: float, event_score: float) -> str:
    if score >= 0.82 and entity_score >= 0.50:
        return "duplicate_candidate"
    if score >= 0.66 and entity_score >= 0.35:
        return "same_story_cluster"
    if score >= 0.56 and event_score >= 0.50:
        return "same_event_cluster"
    if score >= 0.45:
        return "weak_relation"
    return "no_relation"


def reason_for(pair_type: str, a: Article, b: Article) -> str:
    shared_entities = sorted(set(a.entities) & set(b.entities))
    shared_actions = sorted(set(a.actions) & set(b.actions))
    shared_events = sorted(set(a.events) & set(b.events))
    parts = []
    if shared_entities:
        parts.append("soggetti=" + ", ".join(shared_entities[:6]))
    if shared_actions:
        parts.append("azioni=" + ", ".join(shared_actions[:4]))
    if shared_events:
        parts.append("eventi=" + ", ".join(shared_events[:6]))
    if pair_type == "duplicate_candidate":
        parts.append("possibile stesso fatto centrale")
    elif pair_type == "same_story_cluster":
        parts.append("stesso filone, verificare novelty")
    elif pair_type == "same_event_cluster":
        parts.append("stesso evento/show, verificare overlap con report")
    return "; ".join(parts) or "relazione lessicale debole"


def pair_score(a: Article, b: Article) -> Pair:
    token_score = overlap(a.tokens, b.tokens, min_denominator=False)
    entity_score = overlap(a.entities, b.entities, min_denominator=True)
    action_score = overlap(a.actions, b.actions, min_denominator=True)
    event_score = overlap(a.events, b.events, min_denominator=True)
    fp_score = 0.0
    if fingerprint_similarity and a.fingerprint and b.fingerprint:
        try:
            fp_score = float(fingerprint_similarity(a.fingerprint, b.fingerprint))
        except Exception:
            fp_score = 0.0
    # Diagnostic blend: keep strict fingerprint visible, but do not depend on it.
    score = (
        entity_score * 0.30
        + token_score * 0.25
        + action_score * 0.18
        + event_score * 0.17
        + fp_score * 0.10
    )
    # Boost strong named-subject matches such as Ludwig Kaiser / Kota Ibushi / Piper Niven.
    if entity_score >= 0.5 and action_score >= 0.5:
        score += 0.08
    if event_score >= 0.75 and action_score >= 0.5:
        score += 0.05
    score = min(1.0, round(score, 4))
    ctype = classify(score, entity_score, action_score, event_score)
    return Pair(
        a=a.id,
        b=b.id,
        title_a=a.title,
        title_b=b.title,
        score=score,
        fingerprint_score=round(fp_score, 4),
        token_score=round(token_score, 4),
        entity_score=round(entity_score, 4),
        action_score=round(action_score, 4),
        event_score=round(event_score, 4),
        cluster_type=ctype,
        reason="",
    )


def union_find_clusters(articles: list[Article], pairs: list[Pair], min_score: float) -> list[list[Article]]:
    parent = {a.id: a.id for a in articles}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for p in pairs:
        if p.score >= min_score or p.cluster_type == "duplicate_candidate":
            union(p.a, p.b)
    groups: dict[str, list[Article]] = {}
    by_id = {a.id: a for a in articles}
    for aid in parent:
        groups.setdefault(find(aid), []).append(by_id[aid])
    clusters = [sorted(v, key=lambda x: x.mtime_utc) for v in groups.values() if len(v) >= 2]
    return sorted(clusters, key=lambda g: (-len(g), g[0].mtime_utc))


def write_reports(articles: list[Article], pairs: list[Pair], clusters: list[list[Article]], args: argparse.Namespace, since: datetime, until: datetime) -> tuple[Path, Path]:
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y-%m-%d_%H-%M")
    json_path = report_dir / f"story_cluster_audit_v94_7_{stamp}.json"
    md_path = report_dir / f"story_cluster_audit_v94_7_{stamp}.md"

    payload = {
        "version": "v94.7_story_cluster_audit_diagnostic",
        "generated_at_utc": utc_now().isoformat(),
        "window": {"since_utc": since.isoformat(), "until_utc": until.isoformat(), "hours": args.hours},
        "counts": {
            "articles": len(articles),
            "pairs_above_threshold": len(pairs),
            "clusters": len(clusters),
            "duplicate_candidates": sum(1 for p in pairs if p.cluster_type == "duplicate_candidate"),
            "same_story_clusters": sum(1 for p in pairs if p.cluster_type == "same_story_cluster"),
            "same_event_clusters": sum(1 for p in pairs if p.cluster_type == "same_event_cluster"),
        },
        "articles": [asdict(a) for a in articles],
        "pairs": [asdict(p) for p in pairs],
        "clusters": [[a.id for a in group] for group in clusters],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines: list[str] = []
    lines.append("# OpenWrestlingTV - Story Cluster Audit v94.7")
    lines.append("")
    lines.append(f"Generated UTC: {payload['generated_at_utc']}")
    lines.append(f"Window UTC: {since.isoformat()} -> {until.isoformat()}")
    lines.append("")
    lines.append("## Sintesi")
    lines.append(f"- Articoli locali analizzati: {len(articles)}")
    lines.append(f"- Coppie sopra soglia diagnostica: {len(pairs)}")
    lines.append(f"- Cluster rilevati: {len(clusters)}")
    lines.append(f"- Duplicate candidate: {payload['counts']['duplicate_candidates']}")
    lines.append(f"- Same story cluster: {payload['counts']['same_story_clusters']}")
    lines.append(f"- Same event cluster: {payload['counts']['same_event_clusters']}")
    lines.append("")
    lines.append("Nota: questo audit non blocca nulla e non modifica Menzo. Serve solo a rendere visibili i filoni editoriali.")
    lines.append("")

    lines.append("## Cluster principali")
    if not clusters:
        lines.append("- Nessun cluster sopra soglia.")
    for idx, group in enumerate(clusters[:20], start=1):
        group_pairs = [p for p in pairs if p.a in {x.id for x in group} and p.b in {x.id for x in group}]
        max_score = max([p.score for p in group_pairs], default=0.0)
        labels = sorted(set(p.cluster_type for p in group_pairs))
        lines.append(f"### Cluster {idx} - items={len(group)} - max_score={max_score:.2f} - types={', '.join(labels)}")
        for a in group:
            lines.append(f"- {a.mtime_utc} | {a.kind} | {a.title}")
        lines.append("")

    lines.append("## Coppie sospette")
    if not pairs:
        lines.append("- Nessuna coppia sopra soglia.")
    for p in pairs[: args.top_pairs]:
        lines.append(f"### {p.cluster_type} | score={p.score:.2f} | fp={p.fingerprint_score:.2f}")
        lines.append(f"- A: {p.title_a}")
        lines.append(f"- B: {p.title_b}")
        lines.append(f"- metriche: entity={p.entity_score:.2f}, action={p.action_score:.2f}, event={p.event_score:.2f}, token={p.token_score:.2f}")
        lines.append(f"- motivo: {p.reason}")
        lines.append("")

    lines.append("## Articoli analizzati")
    for a in sorted(articles, key=lambda x: x.mtime_utc, reverse=True):
        lines.append(f"- {a.mtime_utc} | {a.kind} | {a.title}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    args = parse_args()
    until = parse_iso(args.until) or utc_now()
    since = parse_iso(args.since) or (until - timedelta(hours=args.hours))
    articles = load_articles(Path(args.published_dir), since, until)
    raw_pairs: list[Pair] = []
    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            p = pair_score(articles[i], articles[j])
            if p.score >= args.min_score:
                # Attach reason after type is known.
                a, b = articles[i], articles[j]
                p.reason = reason_for(p.cluster_type, a, b)
                raw_pairs.append(p)
    pairs = sorted(raw_pairs, key=lambda p: (p.score, p.fingerprint_score), reverse=True)
    clusters = union_find_clusters(articles, pairs, args.cluster_score)
    json_path, md_path = write_reports(articles, pairs, clusters, args, since, until)
    print(f"[STORY CLUSTER v94.7] articles={len(articles)} pairs={len(pairs)} clusters={len(clusters)}")
    print(f"[STORY CLUSTER v94.7] json={json_path}")
    print(f"[STORY CLUSTER v94.7] report={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
