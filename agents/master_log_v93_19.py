from __future__ import annotations

import json
import os
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "newsroom"
LOG_DIR = ROOT / "logs"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"

MASTER_JSONL = STATE_DIR / "master_log.jsonl"
MASTER_HUMAN = LOG_DIR / "newsroom_master.log"
ARTIFACT_MASTER_JSONL = ARTIFACT_DIR / "master_log_tail.jsonl"
ARTIFACT_MASTER_HUMAN = ARTIFACT_DIR / "newsroom_master.log"

VERSION = "v93_19_newsroom_master_log"
MAX_RUNS = int(os.getenv("V93_MASTER_LOG_MAX_RUNS", "300"))
TAIL_RUNS = int(os.getenv("V93_MASTER_LOG_ARTIFACT_TAIL", "40"))

DUPLICATE_ARBITRATION_COUNTER_KEYS = (
    "menzo_same_run_batch_calls",
    "menzo_same_run_batch_repairs",
    "menzo_same_run_micro_fallback_calls",
    "menzo_same_run_duplicate_groups",
    "menzo_same_run_duplicates_blocked",
    "menzo_recent_history_batch_calls",
    "menzo_recent_history_batch_repairs",
    "menzo_recent_history_micro_fallback_calls",
    "menzo_recent_history_duplicates_blocked",
    "menzo_recent_history_material_updates",
    "menzo_duplicate_arbitration_fail_closed",
    "gemini_calls_used_for_duplicate_arbitration",
)


def compact_duplicate_arbitration(postprocess: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(postprocess, dict):
        return {}
    return {key: postprocess[key] for key in DUPLICATE_ARBITRATION_COUNTER_KEYS if isinstance(postprocess.get(key), int)}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_handoff(data: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(data, dict) and isinstance(data.get("handoff"), dict):
        return dict(data.get("handoff") or {})
    return {}


def scalar(value: Any, default: Any = None) -> Any:
    return value if value not in (None, "") else default


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def canonical_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parsed.scheme.lower() or "https", parsed.netloc.lower().removeprefix("www."),
                       parsed.path.rstrip("/"), urlencode(query), ""))


def actionable_identity_key(item: dict[str, Any]) -> str:
    for field in ("source_url", "url", "original_url"):
        value = canonical_url(item.get(field))
        if value:
            return "source:" + value
    for field in ("wp_link", "wordpress_url", "published_url", "final_url", "link"):
        value = canonical_url(item.get(field))
        if value:
            return "wp:" + value
    title = re.sub(r"[^a-z0-9]+", " ", str(item.get("title") or item.get("title_it") or item.get("source_title") or "").lower()).strip()
    if title:
        return "title:" + title
    payload = json.dumps(item, sort_keys=True, default=str, ensure_ascii=True).encode()
    return "unknown:" + hashlib.sha1(payload).hexdigest()[:12]


def compact_item(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else {}
    brief = item.get("bob_brief") if isinstance(item.get("bob_brief"), dict) else {}
    return {
        "title": scalar(item.get("title") or item.get("title_it") or item.get("source_title"), ""),
        "source_url": scalar(item.get("url") or item.get("source_url"), ""),
        "source": scalar(item.get("source"), ""),
        "category_hint": scalar(item.get("category_hint"), ""),
        "article_type": scalar(item.get("article_type"), ""),
        "score": item.get("score"),
        "deterministic_score": item.get("deterministic_score"),
        "ai_priority_label": scalar(item.get("ai_priority_label"), ""),
        "decision": scalar(item.get("decision"), ""),
        "priority": scalar(item.get("priority"), ""),
        "reason": scalar(item.get("reason"), ""),
        "event_key": scalar(review.get("event_key"), ""),
        "duplicate_of": scalar(item.get("duplicate_of") or review.get("duplicate_of"), ""),
        "expected_embeds": brief.get("expected_embeds", []) if isinstance(brief.get("expected_embeds"), list) else [],
        "expected_tables": brief.get("expected_tables") if "expected_tables" in brief else None,
        "published": scalar(item.get("published"), ""),
    }


def compact_published(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "title": scalar(item.get("title") or item.get("title_it"), ""),
        "source_url": scalar(item.get("source_url") or item.get("url"), ""),
        "wp_link": scalar(item.get("wp_link") or item.get("link"), ""),
        "wp_post_id": item.get("wp_post_id") or item.get("post_id"),
        "status": scalar(item.get("status"), ""),
        "categories": item.get("categories") or item.get("category_names_priority") or item.get("publisher_category_names") or [],
        "category_hint": scalar(item.get("category_hint"), ""),
    }


def compact_warning(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "code": scalar(value.get("code"), "warning"),
            "severity": scalar(value.get("severity"), "warning"),
            "message": scalar(value.get("message"), ""),
            "evidence": scalar(value.get("evidence"), ""),
            "expected_embeds": value.get("expected_embeds", []),
        }
    return {"code": "warning", "severity": "warning", "message": str(value)}


def compact_article_diagnostics(article: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(article, dict):
        return {}
    diagnostics = article.get("extraction_diagnostics") if isinstance(article.get("extraction_diagnostics"), dict) else {}
    return {
        "title": scalar(article.get("title_it") or article.get("source_title"), ""),
        "source_url": scalar(article.get("source_url"), ""),
        "status": scalar(article.get("status"), ""),
        "element_counts": article.get("element_counts", {}),
        "translation_model": scalar(article.get("translation_model"), ""),
        "translation_used": bool(article.get("translation_used")),
        "warnings": [compact_warning(x) for x in article.get("diagnostic_warnings", []) if x][:8] if isinstance(article.get("diagnostic_warnings"), list) else [],
        "editorial_changes": [compact_warning(x) for x in article.get("editorial_changes", []) if x][:8] if isinstance(article.get("editorial_changes"), list) else [],
        "source_html_contains_embed_hint": article.get("source_html_contains_embed_hint"),
        "table_count": diagnostics.get("table_count"),
        "embed_count": diagnostics.get("embed_count"),
        "quote_count": diagnostics.get("quote_count"),
    }


def compact_alfred_review(review: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(review, dict):
        return {}
    blockers = review.get("blockers", []) if isinstance(review.get("blockers"), list) else []
    if not blockers and isinstance(review.get("issues"), list):
        blockers = [x for x in review.get("issues", []) if isinstance(x, dict) and str(x.get("severity") or "").lower() == "blocker"]
    warnings = [x for x in review.get("warnings", []) if x] if isinstance(review.get("warnings"), list) else []
    return {
        "title": scalar(review.get("title") or review.get("title_it"), ""),
        "source_url": scalar(review.get("source_url"), ""),
        "status": scalar(review.get("status") or review.get("decision"), ""),
        "quality_score": review.get("quality_score"),
        "warnings": [compact_warning(x) for x in warnings[:10]],
        "warning_occurrences_total": len(warnings),
        "warnings_truncated": len(warnings) > 10,
        "blockers": [compact_warning(x) for x in blockers if x][:10],
        "changes": [compact_warning(x) for x in review.get("editorial_changes", []) if x][:10] if isinstance(review.get("editorial_changes"), list) else [],
    }


def top_skips(items: list[Any], limit: int = 12) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            out.append(compact_item(item))
        if len(out) >= limit:
            break
    return out


def build_master_record(
    *,
    run_summary: dict[str, Any],
    timeline: list[dict[str, Any]],
    massy: dict[str, Any],
    simone: dict[str, Any],
    simone_publish: dict[str, Any],
    menzo: dict[str, Any],
    bob: dict[str, Any],
    alfred: dict[str, Any],
    publisher: dict[str, Any],
    archivista: dict[str, Any],
) -> dict[str, Any]:
    massy_h = safe_handoff(massy)
    simone_h = safe_handoff(simone)
    simone_pub_h = safe_handoff(simone_publish)
    menzo_h = safe_handoff(menzo)
    andrea_h = dict(run_summary.get("andrea_handoff") or {}) if isinstance(run_summary.get("andrea_handoff"), dict) else {}
    bob_h = safe_handoff(bob)
    alfred_h = safe_handoff(alfred)
    publisher_h = safe_handoff(publisher)
    archivista_summary = archivista.get("summary", {}) if isinstance(archivista.get("summary"), dict) else {}

    selected_items = [x for x in menzo.get("selected", []) if isinstance(x, dict)] if isinstance(menzo.get("selected"), list) else []
    pending_items = [x for x in menzo.get("pending", []) if isinstance(x, dict)] if isinstance(menzo.get("pending"), list) else []
    selected = [compact_item(x) for x in selected_items]
    pending = [compact_item(x) for x in pending_items[:20]]
    actionable_identity_keys = sorted({actionable_identity_key(x) for x in selected_items + pending_items})
    skipped = top_skips(menzo.get("skipped", []) if isinstance(menzo.get("skipped"), list) else [], 12)
    duplicate_arbitration = compact_duplicate_arbitration(menzo.get("postprocess") if isinstance(menzo.get("postprocess"), dict) else {})

    bob_articles = [compact_article_diagnostics(x) for x in bob.get("articles", []) if isinstance(x, dict)] if isinstance(bob.get("articles"), list) else []
    alfred_reviews = [compact_alfred_review(x) for x in alfred.get("reviews", []) if isinstance(x, dict)] if isinstance(alfred.get("reviews"), list) else []
    pub_results = [compact_published(x) for x in publisher.get("results", []) if isinstance(x, dict)] if isinstance(publisher.get("results"), list) else []
    report_results = [compact_published(x) for x in simone_publish.get("results", []) if isinstance(x, dict)] if isinstance(simone_publish.get("results"), list) else []

    return {
        "schema_version": VERSION,
        "recorded_at": utc_now(),
        "run": {
            "started_at": run_summary.get("started_at"),
            "ended_at": run_summary.get("ended_at"),
            "newsroom_version": run_summary.get("version"),
            "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
            "github_run_number": os.getenv("GITHUB_RUN_NUMBER", ""),
            "github_sha": os.getenv("GITHUB_SHA", ""),
            "github_ref_name": os.getenv("GITHUB_REF_NAME", ""),
            "github_event_name": os.getenv("GITHUB_EVENT_NAME", ""),
            "engine": run_summary.get("engine"),
            "runtime_delegations": run_summary.get("runtime_delegations"),
            "runtime_exit_code": run_summary.get("runtime_exit_code"),
        },
        "agents": run_summary.get("agents", {}),
        "massy": {
            "version": massy.get("version"),
            "handoff": massy_h,
            "found": massy.get("found_count") or massy.get("input", {}).get("found") if isinstance(massy.get("input"), dict) else None,
            "to_simone": massy_h.get("to_simone"),
            "to_menzo": massy_h.get("to_menzo"),
            "hard_skipped": massy_h.get("hard_skipped"),
            "published_skip": massy_h.get("published_skip"),
            "menzo_memory_hard_skipped": massy_h.get("menzo_memory_hard_skipped"),
            "old_news_hard_skipped": massy_h.get("old_news_hard_skipped"),
            "known_menzo_hard_skip_urls": massy.get("known_menzo_hard_skip_urls"),
        },
        "simone": {
            "version": simone.get("version"),
            "handoff": simone_h,
            "ready_reports": [compact_item(x) for x in simone.get("ready_reports", []) if isinstance(x, dict)] if isinstance(simone.get("ready_reports"), list) else [],
            "waiting_reports": [compact_item(x) for x in simone.get("waiting_reports", []) if isinstance(x, dict)][:10] if isinstance(simone.get("waiting_reports"), list) else [],
            "publish_version": simone_publish.get("version"),
            "publish_handoff": simone_pub_h,
            "published_reports": report_results,
        },
        "menzo": {
            "version": menzo.get("version"),
            "mode": menzo.get("mode"),
            "handoff": menzo_h,
            "ai_used": (menzo.get("menzo_ai") or {}).get("used") if isinstance(menzo.get("menzo_ai"), dict) else None,
            "ai_model": (menzo.get("menzo_ai") or {}).get("model") if isinstance(menzo.get("menzo_ai"), dict) else None,
            "policy": menzo.get("policy", {}),
            "selected": selected,
            "pending": pending,
            "actionable_identity_keys": actionable_identity_keys,
            "selected_total": len(selected_items),
            "pending_total": len(pending_items),
            "pending_sample_size": len(pending),
            "pending_sample_truncated": len(pending_items) > len(pending),
            "skipped_sample": skipped,
            "duplicate_arbitration": duplicate_arbitration,
        },
        "andrea": {
            "handoff": andrea_h,
        },
        "bob": {
            "version": bob.get("version"),
            "mode": bob.get("mode"),
            "handoff": bob_h,
            "policy": bob.get("policy", {}),
            "postprocess": bob.get("postprocess", {}),
            "articles": bob_articles,
        },
        "alfred": {
            "version": alfred.get("version"),
            "handoff": alfred_h,
            "policy": alfred.get("policy", {}),
            "postprocess": alfred.get("postprocess", {}),
            "reviews": alfred_reviews,
        },
        "publisher": {
            "version": publisher.get("version"),
            "handoff": publisher_h,
            "policy": publisher.get("policy", {}),
            "published": [x for x in pub_results if x.get("status") == "published"],
            "results": pub_results,
        },
        "archivista": {
            "version": archivista.get("version"),
            "overall_status": archivista.get("overall_status"),
            "summary": archivista_summary,
            "anomalies": archivista.get("anomalies", []) if isinstance(archivista.get("anomalies"), list) else [],
        },
        "timeline": timeline[-80:] if isinstance(timeline, list) else [],
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                out.append(item)
        except Exception:
            continue
    return out


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in records), encoding="utf-8")
    tmp.replace(path)


def human_line(record: dict[str, Any]) -> str:
    run = record.get("run", {})
    massy = record.get("massy", {})
    simone = record.get("simone", {})
    menzo = record.get("menzo", {})
    bob = record.get("bob", {})
    alfred = record.get("alfred", {})
    publisher = record.get("publisher", {})
    archivista = record.get("archivista", {})
    selected_titles = [x.get("title", "") for x in menzo.get("selected", [])][:6]
    published_titles = [x.get("title", "") for x in publisher.get("published", [])][:8]
    report_titles = [x.get("title", "") for x in simone.get("published_reports", []) if x.get("status") == "published"][:4]
    return (
        f"\n===== NEWSROOM MASTER RUN {run.get('started_at')} | {run.get('newsroom_version')} | run_id={run.get('github_run_id')} =====\n"
        f"Massy: to_simone={massy.get('to_simone')} to_menzo={massy.get('to_menzo')} hard_skip={massy.get('hard_skipped')} menzo_skip={massy.get('menzo_memory_hard_skipped')} old_skip={massy.get('old_news_hard_skipped')}\n"
        f"Simone: ready={simone.get('handoff', {}).get('ready')} reports_published={simone.get('publish_handoff', {}).get('published')} wp_not_ready={simone.get('publish_handoff', {}).get('wp_not_ready')}\n"
        f"Menzo: selected={menzo.get('handoff', {}).get('to_bob_or_v92')} pending={menzo.get('handoff', {}).get('pending')} skipped={menzo.get('handoff', {}).get('skipped')} ai={menzo.get('ai_used')} model={menzo.get('ai_model')}\n"
        f"Bob: ready={bob.get('handoff', {}).get('ready_for_alfred')} errors={bob.get('handoff', {}).get('errors')} changes={bob.get('postprocess', {})}\n"
        f"Alfred: approved={alfred.get('handoff', {}).get('approved')} warnings={alfred.get('handoff', {}).get('warnings')} blockers={alfred.get('handoff', {}).get('blockers')}\n"
        f"Publisher: published={publisher.get('handoff', {}).get('published')} wp_not_ready={publisher.get('handoff', {}).get('wp_not_ready')} errors={publisher.get('handoff', {}).get('errors')}\n"
        f"Archivista: status={archivista.get('overall_status')} anomalies={archivista.get('summary', {}).get('anomalies')}\n"
        f"Selected: {', '.join(t for t in selected_titles if t) or '-'}\n"
        f"Published news: {', '.join(t for t in published_titles if t) or '-'}\n"
        f"Published reports: {', '.join(t for t in report_titles if t) or '-'}\n"
    )


def write_human_log(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tail = records[-MAX_RUNS:]
    content = "".join(human_line(r) for r in tail)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def write_master_log(
    *,
    run_summary: dict[str, Any],
    timeline: list[dict[str, Any]],
    massy: dict[str, Any],
    simone: dict[str, Any],
    simone_publish: dict[str, Any],
    menzo: dict[str, Any],
    bob: dict[str, Any],
    alfred: dict[str, Any],
    publisher: dict[str, Any],
    archivista: dict[str, Any],
) -> dict[str, Any]:
    record = build_master_record(run_summary=run_summary, timeline=timeline, massy=massy, simone=simone, simone_publish=simone_publish, menzo=menzo, bob=bob, alfred=alfred, publisher=publisher, archivista=archivista)
    records = read_jsonl(MASTER_JSONL)
    records.append(record)
    records = records[-MAX_RUNS:]
    write_jsonl(MASTER_JSONL, records)
    write_jsonl(ARTIFACT_MASTER_JSONL, records[-TAIL_RUNS:])
    write_human_log(MASTER_HUMAN, records)
    write_human_log(ARTIFACT_MASTER_HUMAN, records[-TAIL_RUNS:])
    print(f"[MASTERLOG v93.19] saved runs={len(records)} tail={min(len(records), TAIL_RUNS)}", flush=True)
    return {"version": VERSION, "records": len(records), "latest_run_id": record.get("run", {}).get("github_run_id"), "jsonl": str(MASTER_JSONL), "human": str(MASTER_HUMAN)}
