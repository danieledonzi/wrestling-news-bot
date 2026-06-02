#!/usr/bin/env python3
"""OpenWrestlingTV v93 Virtual Newsroom runner.

Compatibility marker for workflow validation:
v93_0_virtual_newsroom_bootstrap

The runner does not import or execute bot_v92.py by default. NEWSROOM_ENGINE
remains available only as an explicit test override, and runtime_delegations is
kept in the summary for backward-compatible verification.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

NEWSROOM_VERSION = "v93_14_priority_label_bob_brief_guard"
ARTIFACT_DIR = Path("artifacts") / "newsroom"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_artifacts() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def add_timeline(timeline: list[dict[str, str]], agent: str, phase: str, note: str = "") -> None:
    item = {"timestamp": utc_now(), "agent": agent, "phase": phase}
    if note:
        item["note"] = note
    timeline.append(item)
    print(f"[{agent.upper()} v93] {phase}" + (f" - {note}" if note else ""), flush=True)


def runtime_command() -> list[str]:
    override = os.getenv("NEWSROOM_ENGINE", "").strip()
    if override:
        return [sys.executable, override]
    return [sys.executable, "bot_v92.py"]


def handoff(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("handoff", {}) if isinstance(data.get("handoff"), dict) else {}


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def priority_label_from_review(review: dict[str, Any]) -> str:
    label = str(review.get("priority_label") or "").strip().lower()
    if label in {"high", "medium", "low", "skip"}:
        return label
    try:
        numeric = int(review.get("priority", 0))
    except Exception:
        numeric = 0
    if numeric >= 80:
        return "high"
    if numeric >= 50:
        return "medium"
    if numeric > 0:
        # Backward compatibility for the first v93.13 prompt, where Gemini used 1/2.
        return "medium" if numeric >= 2 else "low"
    return "skip"


def priority_score(label: str) -> int:
    return {"high": 92, "medium": 72, "low": 48, "skip": 0}.get(label, 48)


def sort_item(item: dict[str, Any]) -> tuple[int, float, str]:
    age = item.get("age_hours")
    try:
        age_float = float(age)
    except Exception:
        age_float = 999999.0
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    return score, -age_float, str(item.get("published") or "")


def normalize_menzo_priority_labels(menzo: dict[str, Any]) -> dict[str, Any]:
    """Post-process Menzo v93.13 until the agent file itself fully owns v93.14.

    Converts numeric AI priority into priority_label, applies a conservative score blend,
    avoids duplicate_of=self, and caps selected data_report/rating articles to one per run.
    """
    if not isinstance(menzo, dict):
        return menzo
    reviews = ((menzo.get("menzo_ai") or {}).get("reviews") or []) if isinstance(menzo.get("menzo_ai"), dict) else []
    review_by_id = {str(r.get("id")): r for r in reviews if isinstance(r, dict) and r.get("id")}
    touched = 0
    for section in ["selected", "pending", "skipped"]:
        for item in menzo.get(section, []) if isinstance(menzo.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            review = item.get("menzo_ai_review") if isinstance(item.get("menzo_ai_review"), dict) else review_by_id.get(str(item.get("ai_id")), {})
            if not isinstance(review, dict) or not review:
                continue
            label = priority_label_from_review(review)
            review["priority_label"] = label
            item["menzo_ai_review"] = review
            item["ai_priority_label"] = label
            item["ai_priority"] = priority_score(label)
            det = int(item.get("deterministic_score", item.get("score", 0)) or 0)
            item["score"] = int(round(det * 0.55 + priority_score(label) * 0.45))
            duplicate_of = str(review.get("duplicate_of") or "").strip()
            if duplicate_of and duplicate_of == str(item.get("ai_id")):
                review["duplicate_of"] = ""
                item.pop("duplicate_of", None)
            touched += 1
    selected = [x for x in menzo.get("selected", []) if isinstance(x, dict)]
    pending = [x for x in menzo.get("pending", []) if isinstance(x, dict)]
    kept: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    max_data = int(os.getenv("V93_MENZO_MAX_DATA_REPORTS_PER_RUN", "1"))
    data_seen = 0
    for item in sorted(selected, key=sort_item, reverse=True):
        if str(item.get("article_type")) == "data_report":
            data_seen += 1
            if data_seen > max_data:
                item = dict(item)
                item["decision"] = "pending"
                item["priority"] = "soft"
                item["reason"] = f"data_report_cap:{max_data}; {item.get('reason', '')}"
                moved.append(item)
                continue
        kept.append(item)
    if moved:
        menzo["selected"] = kept
        menzo["pending"] = sorted(pending + moved, key=sort_item, reverse=True)
        menzo["allowed_urls_for_v92"] = [str(i.get("url") or i.get("source_url") or "") for i in kept if i.get("url") or i.get("source_url")]
        if isinstance(menzo.get("handoff"), dict):
            menzo["handoff"]["to_bob_or_v92"] = len(kept)
            menzo["handoff"]["pending"] = len(menzo["pending"])
    menzo.setdefault("policy", {})["priority_schema"] = "priority_label_high_medium_low_skip"
    menzo.setdefault("policy", {})["data_report_cap_enabled"] = True
    menzo["version"] = "v93_14_priority_label_bob_brief_guard"
    menzo["mode"] = "ai_editorial_review_priority_label_guard"
    menzo.setdefault("postprocess", {})["priority_label_normalized"] = touched
    return menzo


def attach_bob_brief_warnings(bob: dict[str, Any], menzo: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bob, dict) or not isinstance(menzo, dict):
        return bob
    selected_by_url = {
        source_key(item.get("url") or item.get("source_url") or ""): item
        for item in menzo.get("selected", []) if isinstance(item, dict)
    }
    warnings_added = 0
    for article in bob.get("articles", []) if isinstance(bob.get("articles"), list) else []:
        if not isinstance(article, dict):
            continue
        src = selected_by_url.get(source_key(article.get("source_url", "")))
        if not src:
            continue
        brief = src.get("bob_brief") if isinstance(src.get("bob_brief"), dict) else {}
        article["bob_brief"] = brief
        article["menzo_ai_review"] = src.get("menzo_ai_review")
        article["ai_editorial_reason"] = src.get("ai_editorial_reason")
        article["ai_priority_label"] = src.get("ai_priority_label")
        expected = brief.get("expected_embeds") if isinstance(brief, dict) else []
        if not isinstance(expected, list):
            expected = []
        expected = [str(x).strip() for x in expected if str(x).strip()]
        counts = article.get("element_counts") if isinstance(article.get("element_counts"), dict) else {}
        found = int(counts.get("embed", 0) or 0)
        if expected and found == 0:
            warn = {
                "code": "possible_missing_embed_from_menzo_brief",
                "severity": "warning",
                "message": "Menzo AI si aspettava embed/video/tweet, ma Bob non ne ha estratti.",
                "expected_embeds": expected,
                "source_specific_notes": brief.get("source_specific_notes", "") if isinstance(brief, dict) else "",
            }
            article.setdefault("diagnostic_warnings", []).append(warn)
            warnings_added += 1
    bob.setdefault("policy", {})["consume_menzo_bob_brief"] = True
    bob.setdefault("policy", {})["missing_expected_embed_warning"] = True
    bob.setdefault("postprocess", {})["bob_brief_warnings_added"] = warnings_added
    return bob


def surface_bob_warnings_in_alfred(alfred: dict[str, Any], bob: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(alfred, dict) or not isinstance(bob, dict):
        return alfred
    bob_warns = {
        source_key(a.get("source_url", "")): a.get("diagnostic_warnings", [])
        for a in bob.get("articles", []) if isinstance(a, dict) and isinstance(a.get("diagnostic_warnings"), list)
    }
    added = 0
    for review in alfred.get("reviews", []) if isinstance(alfred.get("reviews"), list) else []:
        if not isinstance(review, dict):
            continue
        warnings = bob_warns.get(source_key(review.get("source_url", "")), [])
        if not warnings:
            continue
        review.setdefault("warnings", [])
        for warning in warnings:
            review["warnings"].append(warning)
            added += 1
    if isinstance(alfred.get("handoff"), dict) and added:
        alfred["handoff"]["warnings"] = int(alfred["handoff"].get("warnings", 0) or 0) + added
    alfred.setdefault("policy", {})["consume_bob_diagnostic_warnings"] = True
    alfred.setdefault("postprocess", {})["bob_warnings_surfaced"] = added
    return alfred


def safe_agent(*, timeline: list[dict[str, str]], agent: str, phase: str, import_fn: Callable[[], Callable[..., dict[str, Any]]], call_args: tuple[Any, ...] = (), artifact_name: str, default_handoff: dict[str, Any], note_fn: Callable[[dict[str, Any]], str]) -> dict[str, Any]:
    try:
        fn = import_fn()
    except Exception as exc:
        error = {"agent": agent, "version": NEWSROOM_VERSION, "generated_at": utc_now(), "status": "error", "error": f"import_failed: {exc}", "handoff": default_handoff}
        write_json(ARTIFACT_DIR / artifact_name, error)
        add_timeline(timeline, agent, "error", f"import_failed={exc}")
        return error
    try:
        result = fn(*call_args)
        add_timeline(timeline, agent, phase, note_fn(result if isinstance(result, dict) else {}))
        return result if isinstance(result, dict) else {"agent": agent, "status": "invalid_result", "handoff": default_handoff}
    except Exception as exc:
        error = {"agent": agent, "version": NEWSROOM_VERSION, "generated_at": utc_now(), "status": "error", "error": str(exc), "handoff": default_handoff}
        write_json(ARTIFACT_DIR / artifact_name, error)
        add_timeline(timeline, agent, "error", str(exc))
        return error


def import_massy():
    from agents.massy import run_massy
    return run_massy


def import_simone():
    from agents.simone import run_simone
    return run_simone


def import_menzo():
    from agents.menzo import run_menzo
    return run_menzo


def import_bob():
    from agents.bob import run_bob
    return run_bob


def import_alfred():
    from agents.alfred import run_alfred
    return run_alfred


def import_publisher():
    from agents.publisher import run_publisher
    return run_publisher


def import_archivista():
    from agents.archivista import run_archivista
    return run_archivista


def main() -> int:
    ensure_artifacts()
    started_at = utc_now()
    timeline: list[dict[str, str]] = []
    print(f"===== NEWSROOM RUN START [{started_at}] VERSION [{NEWSROOM_VERSION}] =====", flush=True)
    print("[NEWSROOM v93] Avvio Virtual Newsroom", flush=True)
    print("[NEWSROOM v93] Massy, Simone, Menzo, Bob, Alfred, Publisher and Archivista are real", flush=True)
    command = runtime_command()
    engine = command[1] if len(command) > 1 else "unknown"
    is_test_override = bool(os.getenv("NEWSROOM_ENGINE", "").strip())
    jarvis_status = {"version": NEWSROOM_VERSION, "created_at": utc_now(), "agent": "Jarvis", "mode": "v93_orchestrator", "engine": engine, "newsroom_engine_override": is_test_override, "wp_status_source": "v93_publisher", "can_translate": "v93_bob", "can_review": "v93_alfred", "can_publish": "v93_publisher", "can_audit": "v93_archivista"}
    write_json(ARTIFACT_DIR / "jarvis_status.json", jarvis_status)
    add_timeline(timeline, "Jarvis", "bootstrap_status_written", f"engine={engine}")

    massy_board = safe_agent(timeline=timeline, agent="Massy", phase="sentinel_board_ready", import_fn=import_massy, artifact_name="massy_board.json", default_handoff={"to_simone": 0, "to_menzo": 0, "hard_skipped": 0, "already_worked": 0}, note_fn=lambda r: "to_simone={to_simone} to_menzo={to_menzo} hard_skip={hard_skipped} already={already_worked}".format(**{**{"to_simone": 0, "to_menzo": 0, "hard_skipped": 0, "already_worked": 0}, **handoff(r)}))
    simone_decision = safe_agent(timeline=timeline, agent="Simone", phase="report_decision_ready", import_fn=import_simone, call_args=(massy_board,), artifact_name="simone_reports.json", default_handoff={"ready": 0, "waiting": 0, "skipped": 0}, note_fn=lambda r: "ready={ready} waiting={waiting} skipped={skipped}".format(**{**{"ready": 0, "waiting": 0, "skipped": 0}, **handoff(r)}))
    menzo_decision = safe_agent(timeline=timeline, agent="Menzo", phase="editorial_decision_ready", import_fn=import_menzo, call_args=(massy_board,), artifact_name="menzo_decisions.json", default_handoff={"to_bob_or_v92": 0, "pending": 0, "skipped": 0}, note_fn=lambda r: "selected={to_bob_or_v92} pending={pending} skipped={skipped}".format(**{**{"to_bob_or_v92": 0, "pending": 0, "skipped": 0}, **handoff(r)}))
    menzo_decision = normalize_menzo_priority_labels(menzo_decision)
    write_json(ARTIFACT_DIR / "menzo_decisions.json", menzo_decision)
    add_timeline(timeline, "Menzo", "priority_label_guard_applied", f"selected={handoff(menzo_decision).get('to_bob_or_v92', 0)}")

    bob_result = safe_agent(timeline=timeline, agent="Bob", phase="article_packages_ready", import_fn=import_bob, call_args=(menzo_decision,), artifact_name="bob_articles.json", default_handoff={"ready_for_alfred": 0, "translation_pending": 0, "errors": 0, "extraction_empty": 0}, note_fn=lambda r: "ready={ready_for_alfred} pending={translation_pending} empty={extraction_empty} errors={errors}".format(**{**{"ready_for_alfred": 0, "translation_pending": 0, "errors": 0, "extraction_empty": 0}, **handoff(r)}))
    bob_result = attach_bob_brief_warnings(bob_result, menzo_decision)
    write_json(ARTIFACT_DIR / "bob_articles.json", bob_result)
    add_timeline(timeline, "Bob", "bob_brief_guard_applied", f"warnings={bob_result.get('postprocess', {}).get('bob_brief_warnings_added', 0)}")

    alfred_result = safe_agent(timeline=timeline, agent="Alfred", phase="quality_review_ready", import_fn=import_alfred, call_args=(bob_result,), artifact_name="alfred_review.json", default_handoff={"approved": 0, "needs_revision": 0, "warnings": 0, "blockers": 0, "editorial_changes": 0}, note_fn=lambda r: "approved={approved} needs_revision={needs_revision} blockers={blockers} warnings={warnings} changes={editorial_changes}".format(**{**{"approved": 0, "needs_revision": 0, "warnings": 0, "blockers": 0, "editorial_changes": 0}, **handoff(r)}))
    alfred_result = surface_bob_warnings_in_alfred(alfred_result, bob_result)
    write_json(ARTIFACT_DIR / "alfred_review.json", alfred_result)
    add_timeline(timeline, "Alfred", "bob_warning_guard_applied", f"surfaced={alfred_result.get('postprocess', {}).get('bob_warnings_surfaced', 0)}")

    publisher_result = safe_agent(timeline=timeline, agent="Publisher", phase="publication_ready", import_fn=import_publisher, call_args=(alfred_result,), artifact_name="publisher_result.json", default_handoff={"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}, note_fn=lambda r: "published={published} already={already_published} dry={dry_run} wp_not_ready={wp_not_ready} errors={errors}".format(**{**{"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}, **handoff(r)}))

    runtime_delegations = 0
    runtime_exit_code = 0
    skip_v92 = str(os.getenv("V93_SKIP_V92_AFTER_BOB", "1")).strip().lower() not in {"0", "false", "no", "off"}
    if skip_v92 and not is_test_override:
        add_timeline(timeline, "Jarvis", "runtime_skipped", "v93 Publisher completed; v92 fallback skipped")
        print("[NEWSROOM v93] v92 fallback skipped because V93_SKIP_V92_AFTER_BOB=1", flush=True)
    else:
        runtime_delegations = 1
        add_timeline(timeline, "Jarvis", "runtime_start", "delegating once via subprocess")
        print(f"[NEWSROOM v93] Runtime command: {' '.join(command)}", flush=True)
        result = subprocess.run(command, check=False)
        runtime_exit_code = int(result.returncode)
        add_timeline(timeline, "Publisher", "runtime_finished", f"exit_code={runtime_exit_code}")

    ended_at = utc_now()
    run_summary = {"version": NEWSROOM_VERSION, "started_at": started_at, "ended_at": ended_at, "engine": engine, "newsroom_engine_override": is_test_override, "runtime_delegations": runtime_delegations, "runtime_exit_code": runtime_exit_code, "agents": {"jarvis": "real_orchestrator", "massy": "real_sentinel_control", "simone": "real_report_director", "menzo": "real_editorial_director", "bob": "real_article_writer", "alfred": "real_quality_editor", "publisher": "real_wordpress_publisher", "archivista": "real_audit_agent"}, "massy_handoff": handoff(massy_board), "simone_handoff": handoff(simone_decision), "menzo_handoff": handoff(menzo_decision), "bob_handoff": handoff(bob_result), "alfred_handoff": handoff(alfred_result), "publisher_handoff": handoff(publisher_result)}
    archivista_result = safe_agent(timeline=timeline, agent="Archivista", phase="audit_ready", import_fn=import_archivista, call_args=(), artifact_name="archivista_report.json", default_handoff={"overall_status": "error"}, note_fn=lambda r: "status={status} anomalies={anomalies}".format(status=r.get("overall_status", "unknown"), anomalies=(r.get("summary", {}) if isinstance(r.get("summary"), dict) else {}).get("anomalies", 0)))
    if archivista_result.get("status") != "error":
        try:
            from agents.archivista import run_archivista
            archivista_result = run_archivista(timeline=timeline, run_summary=run_summary, massy=massy_board, simone=simone_decision, menzo=menzo_decision, bob=bob_result, alfred=alfred_result, publisher=publisher_result)
            add_timeline(timeline, "Archivista", "audit_context_refreshed", f"status={archivista_result.get('overall_status')}")
        except Exception as exc:
            add_timeline(timeline, "Archivista", "error", str(exc))
    run_summary["archivista_handoff"] = archivista_result.get("summary", {}) if isinstance(archivista_result, dict) else {}
    run_summary["archivista_status"] = archivista_result.get("overall_status") if isinstance(archivista_result, dict) else "error"
    write_json(ARTIFACT_DIR / "agent_timeline.json", timeline)
    write_json(ARTIFACT_DIR / "run_summary.json", run_summary)
    print(f"[ARCHIVISTA v93] Saved {ARTIFACT_DIR / 'run_summary.json'}", flush=True)
    print(f"===== NEWSROOM RUN END [{ended_at}] VERSION [{NEWSROOM_VERSION}] EXIT [{runtime_exit_code}] =====", flush=True)
    return runtime_exit_code


if __name__ == "__main__":
    raise SystemExit(main())
