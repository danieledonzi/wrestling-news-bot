#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PUBLISHED_DIR = ROOT / "published_html_review"
DEFAULT_REPORT_DIR = ROOT / "reports"

try:
    from agents.story_dedupe_v93_32 import build_generalized_fingerprint, fingerprint_similarity
except Exception:
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
    "una", "uno", "alle", "dagli", "come", "piu", "più", "match", "titolo", "title",
    "show", "evento", "event", "sera", "un", "il", "lo", "la", "le", "i", "l",
    "di", "da", "a", "e", "o", "ha",
}

WEAK_ENTITY_TERMS = {
    "caso", "nomina", "presunta", "vittima", "giugno", "verso", "four", "way", "torneo",
    "importante", "diversi", "previsto", "svelato", "annunciati", "annunciato",
    "aggiornamento", "aggiornamenti", "possibile", "corso", "molto", "tempo", "ancora",
    "lunghi", "scelto", "sceglie", "speciale", "titolato", "arbitro", "providence", "mio", "non",
}

EVENT_TERMS = {
    "raw", "smackdown", "dynamite", "collision", "impact", "summerslam", "slammiversary",
    "forbidden", "door", "king", "queen", "ring", "owen", "hart", "cup",
    "night", "champions", "money", "bank", "redemption", "lockdown", "bound", "glory",
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
    diagnostic_warning: str = ""

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OWTV v94.7.1 diagnostic story cluster audit")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--since", default="")
    parser.add_argument("--until", default="")
    parser.add_argument("--published-dir", default=str(DEFAULT_PUBLISHED_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--min-score", type=float, default=0.45)
    parser.add_argument("--cluster-score", type=float, default=0.58)
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
    return " ".join(
        w.upper() if w in {"wwe", "aew", "tna", "nxt", "aaa", "cm", "mjf"}
        else w.capitalize()
        for w in stem.split("-")
    )

def normalize(value: str) -> str:
    text = html.unescape(str(value or "")).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def tokens_for(title: str) -> list[str]:
    out: list[str] = []
    for w in normalize(title).split():
        if len(w) < 3 or w in STOPWORDS:
            continue
        if w not in out:
            out.append(w)
    return out

def action_tags(tokens: list[str]) -> list[str]:
    s = set(tokens)
    out = [name for name, keys in ACTION_KEYWORDS.items() if s & keys]
    return out or ["general"]

def event_tags(tokens: list[str]) -> list[str]:
    return sorted(set(tokens) & EVENT_TERMS)

def entity_terms(tokens: list[str]) -> list[str]:
    action_words = set().union(*ACTION_KEYWORDS.values())
    entities: list[str] = []
    for w in tokens:
        if w in action_words or w in EVENT_TERMS or w in WEAK_ENTITY_TERMS or w in STOPWORDS:
            continue
        if w not in entities:
            entities.append(w)
    return entities[:12]

def overlap(a: list[str], b: list[str], *, min_denominator: bool = True) -> float:
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    denom = min(len(sa), len(sb)) if min_denominator else len(sa | sb)
    return len(sa & sb) / max(1, denom)

def shared_meaningful_entities(a: Article, b: Article) -> list[str]:
    return sorted((set(a.entities) & set(b.entities)) - WEAK_ENTITY_TERMS)

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
        if not path.is_file() or path.suffix.lower() not in {".html", ".json"}:
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime < since or mtime > until:
            continue
        raw = safe_read(path)
        fallback = title_from_path(path)
        kind = "report_show" if path.suffix.lower() == ".json" and not path.name.startswith("v93_publisher") else "news"
        title = fallback
        body = raw
        if path.suffix.lower() == ".html":
            title = title_from_html(raw, fallback)
            body = strip_tags(raw)[:8000]
        elif path.suffix.lower() == ".json":
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    for key in ("title", "headline", "post_title", "slug"):
                        if data.get(key):
                            title = str(data.get(key))
                            break
                body = json.dumps(data, ensure_ascii=False)[:8000]
            except Exception:
                pass
        toks = tokens_for(title)
        item = {"title": title, "source_title": title, "body_html": body, "url": str(path), "source": "published_html_review"}
        fp = build_generalized_fingerprint(item) if build_generalized_fingerprint else {}
        articles.append(Article(path.name, str(path), title, kind, mtime.isoformat(), toks, entity_terms(toks), action_tags(toks), event_tags(toks), fp))
    return articles

def classify(score: float, entity_score: float, action_score: float, event_score: float, token_score: float, shared_entities: list[str]) -> str:
    has_subject = bool(shared_entities)
    if has_subject and entity_score >= 0.80 and action_score >= 1.00 and token_score >= 0.50:
        return "duplicate_candidate"
    if has_subject and score >= 0.58 and action_score >= 0.50:
        return "same_story_cluster"
    if event_score >= 0.75 and action_score >= 0.50 and score >= 0.54:
        return "same_event_cluster"
    if has_subject and score >= 0.45:
        return "story_review"
    if score >= 0.45:
        return "weak_relation"
    return "no_relation"

def reason_for(pair_type: str, a: Article, b: Article) -> str:
    entities = shared_meaningful_entities(a, b)
    actions = sorted(set(a.actions) & set(b.actions))
    events = sorted(set(a.events) & set(b.events))
    parts: list[str] = []
    if entities:
        parts.append("soggetti=" + ", ".join(entities[:6]))
    if actions:
        parts.append("azioni=" + ", ".join(actions[:4]))
    if events:
        parts.append("eventi=" + ", ".join(events[:6]))
    if pair_type == "duplicate_candidate":
        parts.append("possibile stesso fatto centrale: controllare prima di pubblicare un secondo pezzo")
    elif pair_type == "same_story_cluster":
        parts.append("stesso filone: serve novelty esplicita")
    elif pair_type == "same_event_cluster":
        parts.append("stesso evento/show: verificare overlap con report o recap")
    elif pair_type == "story_review":
        parts.append("relazione di filone debole: monitorare")
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

    shared_entities = shared_meaningful_entities(a, b)

    score = (
        entity_score * 0.34
        + token_score * 0.24
        + action_score * 0.18
        + event_score * 0.14
        + fp_score * 0.10
    )

    if shared_entities and action_score >= 0.5:
        score += 0.07
    if event_score >= 0.75 and action_score >= 0.5:
        score += 0.04
    if not shared_entities and event_score < 0.75:
        score *= 0.60

    score = min(1.0, round(score, 4))
    ctype = classify(score, entity_score, action_score, event_score, token_score, shared_entities)
    warning = "legacy_fingerprint_zero_on_cluster" if fp_score == 0.0 and score >= 0.58 and ctype != "weak_relation" else ""

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
        reason=reason_for(ctype, a, b),
        diagnostic_warning=warning,
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
        if p.cluster_type == "duplicate_candidate" or p.score >= min_score:
            union(p.a, p.b)

    by_id = {a.id: a for a in articles}
    groups: dict[str, list[Article]] = {}
    for aid in parent:
        groups.setdefault(find(aid), []).append(by_id[aid])

    clusters = [sorted(v, key=lambda x: x.mtime_utc) for v in groups.values() if len(v) >= 2]
    return sorted(clusters, key=lambda g: (-len(g), g[0].mtime_utc))

def write_reports(articles: list[Article], pairs: list[Pair], clusters: list[list[Article]], args: argparse.Namespace, since: datetime, until: datetime) -> tuple[Path, Path]:
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().strftime("%Y-%m-%d_%H-%M")
    json_path = report_dir / f"story_cluster_audit_v94_7_1_{stamp}.json"
    md_path = report_dir / f"story_cluster_audit_v94_7_1_{stamp}.md"

    counts = {
        "articles": len(articles),
        "pairs_above_threshold": len(pairs),
        "clusters": len(clusters),
        "duplicate_candidates": sum(1 for p in pairs if p.cluster_type == "duplicate_candidate"),
        "same_story_clusters": sum(1 for p in pairs if p.cluster_type == "same_story_cluster"),
        "same_event_clusters": sum(1 for p in pairs if p.cluster_type == "same_event_cluster"),
        "story_reviews": sum(1 for p in pairs if p.cluster_type == "story_review"),
        "legacy_fp_zero_warnings": sum(1 for p in pairs if p.diagnostic_warning),
    }

    payload = {
        "version": "v94.7.1_story_cluster_audit_diagnostic",
        "generated_at_utc": utc_now().isoformat(),
        "window": {"since_utc": since.isoformat(), "until_utc": until.isoformat(), "hours": args.hours},
        "counts": counts,
        "articles": [asdict(a) for a in articles],
        "pairs": [asdict(p) for p in pairs],
        "clusters": [[a.id for a in g] for g in clusters],
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines: list[str] = [
        "# OpenWrestlingTV - Story Cluster Audit v94.7.1",
        "",
        f"Generated UTC: {payload['generated_at_utc']}",
        f"Window UTC: {since.isoformat()} -> {until.isoformat()}",
        "",
        "## Sintesi",
        f"- Articoli locali analizzati: {len(articles)}",
        f"- Coppie sopra soglia diagnostica: {len(pairs)}",
        f"- Cluster rilevati: {len(clusters)}",
        f"- Duplicate candidate: {counts['duplicate_candidates']}",
        f"- Same story cluster: {counts['same_story_clusters']}",
        f"- Same event cluster: {counts['same_event_clusters']}",
        f"- Story review: {counts['story_reviews']}",
        f"- Warning fp legacy a zero su cluster: {counts['legacy_fp_zero_warnings']}",
        "",
        "Nota: questo audit non blocca nulla e non modifica Menzo. Serve solo a rendere visibili i filoni editoriali.",
        "",
        "## Cluster principali",
    ]

    if not clusters:
        lines.append("- Nessun cluster sopra soglia.")

    for idx, group in enumerate(clusters[:20], start=1):
        ids = {a.id for a in group}
        group_pairs = [p for p in pairs if p.a in ids and p.b in ids]
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
        warn = f" | warning={p.diagnostic_warning}" if p.diagnostic_warning else ""
        lines.append(f"### {p.cluster_type} | score={p.score:.2f} | fp={p.fingerprint_score:.2f}{warn}")
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

    pairs: list[Pair] = []
    for i in range(len(articles)):
        for j in range(i + 1, len(articles)):
            p = pair_score(articles[i], articles[j])
            if p.score >= args.min_score:
                pairs.append(p)

    pairs = sorted(pairs, key=lambda p: (p.score, p.fingerprint_score), reverse=True)
    clusters = union_find_clusters(articles, pairs, args.cluster_score)
    json_path, md_path = write_reports(articles, pairs, clusters, args, since, until)

    print(f"[STORY CLUSTER v94.7.1] articles={len(articles)} pairs={len(pairs)} clusters={len(clusters)}")
    print(f"[STORY CLUSTER v94.7.1] json={json_path}")
    print(f"[STORY CLUSTER v94.7.1] report={md_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
