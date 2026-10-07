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

NEWSROOM_VERSION = "v95.25_ps1_pre_report_news_sequencing"
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


def import_andrea():
    try:
        from agents.andrea import run_andrea
        return run_andrea
    except Exception:
        from agents.andrea_policy_v94_15 import run_andrea
        return run_andrea


def andrea_output_for_bob(menzo: dict[str, Any], andrea: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(andrea, dict) or andrea.get("status") == "error":
        return menzo
    for key in ("menzo_decision", "filtered_menzo_decision", "decision", "output"):
        value = andrea.get(key)
        if isinstance(value, dict) and isinstance(value.get("selected"), list):
            return value
    if isinstance(andrea.get("selected"), list):
        merged = dict(menzo)
        merged["selected"] = andrea.get("selected") or []
        for key in ("pending", "skipped", "allowed_urls_for_v92", "handoff"):
            if key in andrea:
                merged[key] = andrea[key]
        return merged
    return menzo


def andrea_blocked_items(andrea: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(andrea, dict):
        return []
    for key in ("blocked_items", "andrea_blocked_items", "blocked_candidates", "blocked"):
        items = andrea.get(key)
        if isinstance(items, list):
            return [item if isinstance(item, dict) else {"title": str(item)} for item in items]
    nested = andrea.get("andrea") if isinstance(andrea.get("andrea"), dict) else {}
    # Current Andrea output keeps every real candidate in ``andrea.items``.
    # Preserve its source identity and select only the terminal pre-Bob blocks;
    # count-only legacy payloads deliberately continue to fall through.
    items = nested.get("items")
    if isinstance(items, list):
        return [item for item in items
                if isinstance(item, dict) and item.get("decision") == "blocked_before_bob"]
    for key in ("blocked_items", "blocked_candidates", "blocked"):
        items = nested.get(key)
        if isinstance(items, list):
            return [item if isinstance(item, dict) else {"title": str(item)} for item in items]
    return []


def andrea_blocked_count(andrea: dict[str, Any]) -> int:
    h = handoff(andrea)
    for key in ("andrea_blocked", "blocked", "blocked_by_andrea"):
        try:
            return int(h.get(key, andrea.get(key, 0)) or 0)
        except Exception:
            continue
    return len(andrea_blocked_items(andrea))


def record_andrea_avoids_from_result(andrea: dict[str, Any]) -> None:
    try:
        from agents.gemini_ledger import record_andrea_avoided
        items = andrea_blocked_items(andrea)
        blocked = andrea_blocked_count(andrea)
        if items:
            for item in items:
                record_andrea_avoided(item)
            return
        for idx in range(max(0, blocked)):
            record_andrea_avoided({"candidate_id": f"andrea_blocked_synthetic_{idx + 1}", "reason": "andrea_blocked_count_only"})
    except Exception:
        return


def gemini_ledger_summary() -> dict[str, Any]:
    try:
        from agents.gemini_ledger import write_latest_snapshot
        return write_latest_snapshot().get("summary", {})
    except Exception:
        return {"gemini_calls_total": 0, "gemini_calls_by_agent": {}, "gemini_calls_avoided_total": 0, "gemini_calls_avoided_by_andrea": 0, "gemini_calls_failed": 0}


def source_key(value: str) -> str:
    return str(value or "").split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


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


def safe_agent(
    *,
    timeline: list[dict[str, str]],
    agent: str,
    phase: str,
    import_fn: Callable[[], Callable[..., dict[str, Any]]],
    call_args: tuple[Any, ...] = (),
    call_kwargs: dict[str, Any] | None = None,
    artifact_name: str,
    default_handoff: dict[str, Any],
    note_fn: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    try:
        fn = import_fn()
    except Exception as exc:
        error = {"agent": agent, "version": NEWSROOM_VERSION, "generated_at": utc_now(), "status": "error", "error": f"import_failed: {exc}", "handoff": default_handoff}
        write_json(ARTIFACT_DIR / artifact_name, error)
        add_timeline(timeline, agent, "error", f"import_failed={exc}")
        return error
    try:
        result = fn(*call_args, **(call_kwargs or {}))
        add_timeline(timeline, agent, phase, note_fn(result if isinstance(result, dict) else {}))
        return result if isinstance(result, dict) else {"agent": agent, "status": "invalid_result", "handoff": default_handoff}
    except Exception as exc:
        error = {"agent": agent, "version": NEWSROOM_VERSION, "generated_at": utc_now(), "status": "error", "error": str(exc), "handoff": default_handoff}
        write_json(ARTIFACT_DIR / artifact_name, error)
        add_timeline(timeline, agent, "error", str(exc))
        return error


def import_massy():
    try:
        from agents.massy_policy_v93_16 import run_massy
        return run_massy
    except Exception:
        from agents.massy import run_massy
        return run_massy


def import_simone():
    from agents.simone import run_simone
    return run_simone


def import_simone_report_publisher():
    from agents.simone_publisher_v93_18 import run_simone_report_publisher
    return run_simone_report_publisher


def import_menzo():
    try:
        from agents.menzo_policy_v93_15 import run_menzo
        return run_menzo
    except Exception:
        from agents.menzo import run_menzo
        return run_menzo



def import_andrea():
    from agents.andrea_policy_v94_15 import run_andrea
    return run_andrea

def import_bob():
    try:
        from agents.bob_policy_v93_15 import run_bob
        return run_bob
    except Exception:
        from agents.bob import run_bob
        return run_bob


def import_alfred():
    try:
        from agents.alfred_policy_v93_20 import run_alfred
        return run_alfred
    except Exception:
        from agents.alfred import run_alfred
        return run_alfred


def import_publisher():
    try:
        from agents.publisher_policy_v93_20 import run_publisher
        return run_publisher
    except Exception:
        try:
            from agents.publisher_policy_v93_16 import run_publisher
            return run_publisher
        except Exception:
            from agents.publisher import run_publisher
            return run_publisher


def import_archivista():
    from agents.archivista import run_archivista
    return run_archivista


def write_master_log_safe(timeline: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
    try:
        from agents.master_log_v93_19 import write_master_log
        result = write_master_log(timeline=timeline, **kwargs)
        add_timeline(timeline, "MasterLog", "master_log_saved", f"records={result.get('records')}")
        return result
    except Exception as exc:
        error = {"version": NEWSROOM_VERSION, "status": "error", "error": str(exc), "generated_at": utc_now()}
        write_json(ARTIFACT_DIR / "master_log_error.json", error)
        add_timeline(timeline, "MasterLog", "error", str(exc))
        return error


class UnavailableCanonicalLedger:
    """No-op observer used when canonical telemetry cannot initialize."""

    def __init__(self, error: Exception):
        self._summary = {
            "enabled": False,
            "unavailable": True,
            "initialization_error": str(error),
        }

    def safely(self, _method: str, *_args: Any, **_kwargs: Any) -> None:
        return None

    def summary(self) -> dict[str, Any]:
        return dict(self._summary)


def canonical_ledger_factory(run_id: str) -> Any:
    from agents.canonical_event_ledger import CanonicalEventLedger
    return CanonicalEventLedger(run_id)


def initialize_canonical_ledger(run_id: str) -> Any:
    try:
        return canonical_ledger_factory(run_id)
    except Exception as exc:
        print(f"[CANONICAL LEDGER] initialization failed open: {exc}", flush=True)
        return UnavailableCanonicalLedger(exc)


def canonical_artifact_index_factory(run_id: str) -> Any:
    from agents.canonical_artifact_index import CanonicalArtifactIndex
    return CanonicalArtifactIndex(run_id)


class UnavailableCanonicalArtifactIndex:
    def __init__(self, error: Exception):
        self._summary = {
            "enabled": False, "index_path": os.getenv("OWTV_CANONICAL_ARTIFACT_INDEX_PATH", "state/newsroom/canonical_artifact_index.jsonl"),
            "material_root": os.getenv("OWTV_MATERIAL_CHAIN_ROOT", "state/newsroom/material_chain"),
            "artifacts_attempted": 0, "artifacts_archived": 0, "manifest_rows_written": 0,
            "artifacts_reused": 0, "artifacts_skipped": 0, "validation_errors": 0,
            "identity_unresolved": 0, "archive_write_errors": 0, "index_write_errors": 0,
            "initialization_error": str(error),
        }

    def safely(self, _method: str, *_args: Any, **_kwargs: Any) -> None:
        return None

    def summary(self) -> dict[str, Any]:
        return dict(self._summary)


def initialize_canonical_artifact_index(run_id: str) -> Any:
    try:
        return canonical_artifact_index_factory(run_id)
    except Exception as exc:
        print(f"[ARTIFACT INDEX] initialization failed open: {exc}", flush=True)
        return UnavailableCanonicalArtifactIndex(exc)


def weekly_report_keys_at(observation_timestamp: str) -> dict[str, str]:
    """Reuse Simone's dated discovery identity even after a report leaves ready."""
    from agents.simone import REPORTS_CONFIG, discovery_report_identity, load_json
    try:
        now = datetime.fromisoformat(observation_timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return {}
    config = load_json(REPORTS_CONFIG, {"reports": []})
    reports = config.get("reports", []) if isinstance(config, dict) else []
    return {str(row["id"]): discovery_report_identity(row, now)[0]
            for row in reports if isinstance(row, dict) and row.get("id") and row.get("enabled", True)}


def capture_editorial_director_opportunity(massy_board: dict[str, Any], *, run_id: str,
                                            observation_timestamp: str,
                                            preserve_active_metadata: bool = False,
                                            same_run_published_weekly_ids: set[str] | None = None,
                                            ready_weekly_report_keys: dict[str, str] | None = None) -> tuple[Any, Any, Any]:
    """Return snapshot, diagnostic result and the single Menzo preflight result."""
    from agents.menzo_editorial_director_shadow import (capture_opportunity, costly_work_eligibility,
                                                        softpool_augmented_board)
    preflight = costly_work_eligibility()
    if not preflight[0]:
        return None, {"status": "NOT_ELIGIBLE_WP_NOT_READY", "reason": preflight[1], "attempts": 0}, preflight
    from agents.menzo_policy_v93_15 import load_authoritative_publisher_history, load_json
    if preserve_active_metadata:
        from agents.menzo_soft_board import mark_rediscovered_pool_candidates
        # Active classifies only URLs present in the current feed board.
        # The persistent soft pool is a separate container and is never injected into Active candidates.
        augmented = mark_rediscovered_pool_candidates(massy_board)
    else:
        augmented = softpool_augmented_board(massy_board)
    from agents.menzo_policy_v93_15 import published_today_count
    published_weekly = augmented.get("published_due_reports", {})
    published_weekly_ids = set(published_weekly) if isinstance(published_weekly, dict) else set()
    from modules.simone_report_integrity import PENDING_REPORTS
    from agents.simone_publisher_v93_18 import SIMONE_REPORT_HISTORY_FILE
    special_rows = load_json(PENDING_REPORTS, {"reports": []}).get("reports", [])
    # Massy's weekly snapshot predates Simone in this run. Refresh only from
    # Simone publications produced by this run; persisted weekly rows are dated
    # occurrences and must not be collapsed to their stable report_id.
    published_weekly_ids.update(str(value) for value in (same_run_published_weekly_ids or set()) if value)
    special_history = load_json(SIMONE_REPORT_HISTORY_FILE, {})
    published_report_keys = set(special_history) if isinstance(special_history, dict) else set()
    published_report_keys.update(str(row.get("report_key")) for row in special_rows
                                 if isinstance(row, dict) and row.get("status") in {"published", "already_published"})
    weekly_keys = weekly_report_keys_at(observation_timestamp)
    for report_id, key in (ready_weekly_report_keys or {}).items():
        # A replayed older reservation must not replace the current occurrence.
        weekly_keys.setdefault(report_id, key)
    for candidate in augmented.get("news_candidates_for_menzo", []):
        if not isinstance(candidate, dict):
            continue
        special = candidate.get("special_event_match") if isinstance(candidate.get("special_event_match"), dict) else {}
        report_id = str(candidate.get("show_report_id") or "")
        report_key = str(special.get("report_key") or candidate.get("event_report_key") or
                         weekly_keys.get(report_id) or "")
        if report_key:
            candidate["event_report_key"] = report_key
        manual = published_weekly.get(report_id, {}) if isinstance(published_weekly, dict) else {}
        manual_key = str(manual.get("report_key") or "") if isinstance(manual, dict) else ""
        legacy_current_scope = not report_key or report_key == weekly_keys.get(report_id)
        candidate["corresponding_report_published"] = bool(
            (report_key and report_key in published_report_keys) or
            (report_id in published_weekly_ids and
             ((manual_key and manual_key == report_key) or (not manual_key and legacy_current_scope))))
    history = load_authoritative_publisher_history(12)
    if preserve_active_metadata:
        from agents.menzo_policy_v93_15 import load_soft_tombstone_duplicate_history
        tombstones = load_soft_tombstone_duplicate_history()
        published_urls = {str(row.get("source_url") or row.get("url") or "") for row in history if isinstance(row, dict)}
        history.extend(row for row in tombstones if str(row.get("source_url") or "") not in published_urls)
    snapshot = capture_opportunity(
        augmented, run_id=run_id, observation_timestamp=observation_timestamp,
        published_news_today_local=published_today_count(),
        history=history)
    snapshot["publisher_count_label"] = "published_news_today_local"
    if preserve_active_metadata:
        from agents.menzo_editorial_director_active import preserve_bob_capacity_metadata
        preserve_bob_capacity_metadata(snapshot, [item for item in augmented.get("news_candidates_for_menzo", [])
                                                   if isinstance(item, dict)])
    return snapshot, None, preflight


def persist_active_fallback(decision: dict[str, Any], reason: str) -> dict[str, Any]:
    """Attach and persist Active-fallback provenance before downstream readers run."""
    from agents.menzo_policy_v93_15 import (ARTIFACT_DECISIONS_FILE, MENZO_DECISIONS_FILE,
        V92_ALLOWED_URLS_FILE, utc_now, write_json)
    decision["decision_authority"] = "legacy_menzo_fallback"
    decision["fallback_reason"] = reason
    decision.setdefault("handoff", {})["decision_authority"] = "legacy_menzo_fallback"
    for section in ("selected", "pending", "skipped"):
        for item in decision.get(section, []) if isinstance(decision.get(section), list) else []:
            if isinstance(item, dict):
                item["decision_authority"] = "legacy_menzo_fallback"
                item["fallback_reason"] = reason
    write_json(MENZO_DECISIONS_FILE, decision)
    write_json(ARTIFACT_DECISIONS_FILE, decision)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": decision.get("version"),
        "decision_authority": "legacy_menzo_fallback", "fallback_reason": reason,
        "allowed_urls": decision.get("allowed_urls_for_v92", [])})
    return decision


def persist_active_fail_closed(snapshot: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    """ED-3 safety: Active failure never bypasses duplicate authority through legacy publication."""
    from agents.menzo_policy_v93_15 import (ARTIFACT_DECISIONS_FILE, MENZO_DECISIONS_FILE,
        V92_ALLOWED_URLS_FILE, utc_now, write_json)
    source = snapshot if isinstance(snapshot, dict) else {}
    skipped = []
    seen = set()
    for row in list(source.get("candidates", [])) + list(source.get("deterministic_exact_skips", [])) + list(source.get("semantic_duplicate_skips", [])):
        if not isinstance(row, dict):
            continue
        item = dict(row)
        item.pop("candidate_id", None)
        key = str(item.get("url") or item.get("source_url") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        if item.get("exact_duplicate_scope"):
            authority = "deterministic_exact_duplicate"
            why = "exact_duplicate"
        elif item.get("semantic_duplicate_scope"):
            authority = "semantic_duplicate_gate"
            why = "semantic_duplicate"
        else:
            authority = "editorial_director_fail_closed"
            why = "active_fail_closed:" + reason
        item.update(decision="skip", priority="skip", decision_authority=authority, reason=why)
        skipped.append(item)
    decision = {
        "version": "owtv_editorial_director_policy_v4_active",
        "policy_version": "owtv_editorial_director_policy_v4_active",
        "mode": "editorial_director_active_fail_closed",
        "decision_authority": "editorial_director_fail_closed",
        "fallback_reason": reason,
        "selected": [], "pending": [], "skipped": skipped,
        "allowed_urls_for_v92": [],
        "handoff": {"to_bob_or_v92": 0, "pending": 0, "skipped": len(skipped),
                    "decision_authority": "editorial_director_fail_closed"},
    }
    write_json(MENZO_DECISIONS_FILE, decision)
    write_json(ARTIFACT_DECISIONS_FILE, decision)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": decision["version"],
        "decision_authority": "editorial_director_fail_closed", "fallback_reason": reason,
        "allowed_urls": []})
    return decision


def active_fallback_reason(director_result: Any, exc: Exception) -> str:
    """Return the most specific structured Active failure provenance available."""
    result = director_result if isinstance(director_result, dict) else {}
    status = result.get("status")
    return str(result.get("fallback_reason") or result.get("reason") or
               (status if status and status != "VALIDATED" else None) or type(exc).__name__)


def observe_applied_active_authority(artifacts: Any, snapshot: dict[str, Any], result: dict[str, Any]) -> None:
    """Record authority only after projection commits; telemetry remains fail-open."""
    try:
        from agents.canonical_event_ledger import active_event
        active_event("stage_completed", "Menzo", "selection", "success",
                     result="editorial_director_active_authorized", reason_code="editorial_director_active")
    except Exception:
        pass
    try:
        artifacts.safely("observe_editorial_director_active", snapshot, result["output"], result)
    except Exception:
        pass


def publish_simone_reports(simone_decision: dict[str, Any], timeline: list[dict[str, str]], canonical: Any) -> dict[str, Any]:
    simone_publish = safe_agent(timeline=timeline, agent="Simone", phase="report_publication_ready", import_fn=import_simone_report_publisher, call_args=(simone_decision,), artifact_name="simone_report_publish.json", default_handoff={"published": 0, "already_published": 0, "wp_not_ready": 0, "dry_run": 0, "errors": 0}, note_fn=lambda r: "published={published} already={already_published} wp_not_ready={wp_not_ready} errors={errors}".format(**{**{"published": 0, "already_published": 0, "wp_not_ready": 0, "dry_run": 0, "errors": 0}, **handoff(r)}))
    simone_cycle_status = str(simone_publish.get("status") or "")
    if simone_cycle_status in {"error", "invalid_result"}:
        canonical.safely("event", "simone_publication_cycle", "Simone", "reporting", "failed",
                         "artifacts/newsroom/simone_report_publish.json",
                         reason_code="simone_publication_cycle_failed",
                         error_class="invariant", error_terminal=True,
                         result=simone_cycle_status)
    else:
        canonical.safely("event", "simone_publication_cycle", "Simone", "reporting", "success",
                         "artifacts/newsroom/simone_report_publish.json")
    canonical.safely("observe_simone", simone_decision, simone_publish)

    return simone_publish


def selected_news_precede_report(menzo: dict[str, Any], simone: dict[str, Any]) -> bool:
    """Sequence a selected show story before its ready report, never using title keywords."""
    ready = [row for row in simone.get("ready_reports", []) if isinstance(row, dict)]
    keys = {str(row["report_key"]) for row in ready if row.get("report_key")}
    weekly_ids = {str(row["report_id"]) for row in ready if row.get("report_id")}
    for item in menzo.get("selected", []):
        if not isinstance(item, dict) or item.get("corresponding_report_published"):
            continue
        special = item.get("special_event_match") if isinstance(item.get("special_event_match"), dict) else {}
        key = str(special.get("report_key") or item.get("event_report_key") or "")
        if (key and key in keys) or (not key and str(item.get("show_report_id") or "") in weekly_ids):
            return True
    return False


def main() -> int:
    from agents.news_scheduling import REPORT_PUBLICATION_PLANNED
    token = REPORT_PUBLICATION_PLANNED.set(False)
    try:
        return _run_newsroom()
    finally:
        REPORT_PUBLICATION_PLANNED.reset(token)



def _run_newsroom() -> int:
    ensure_artifacts()
    started_at = utc_now()
    os.environ["NEWSROOM_RUN_ID"] = os.getenv("NEWSROOM_RUN_ID", "").strip() or started_at
    canonical = initialize_canonical_ledger(os.environ["NEWSROOM_RUN_ID"])
    try:
        from agents.canonical_event_ledger import install_active_ledger
        install_active_ledger(canonical)
    except Exception:
        pass
    artifacts = initialize_canonical_artifact_index(os.environ["NEWSROOM_RUN_ID"])
    canonical.safely("event", "run_started", "Jarvis", "runtime", "started")
    timeline: list[dict[str, str]] = []
    print(f"===== NEWSROOM RUN START [{started_at}] VERSION [{NEWSROOM_VERSION}] =====", flush=True)
    print("[NEWSROOM v93] Avvio Virtual Newsroom", flush=True)
    print("[NEWSROOM v93] Massy, Simone, Menzo, Andrea, Bob, Alfred, Publisher and Archivista are real", flush=True)
    command = runtime_command()
    engine = command[1] if len(command) > 1 else "unknown"
    is_test_override = bool(os.getenv("NEWSROOM_ENGINE", "").strip())
    jarvis_status = {"version": NEWSROOM_VERSION, "created_at": utc_now(), "agent": "Jarvis", "mode": "v93_orchestrator", "engine": engine, "newsroom_engine_override": is_test_override, "wp_status_source": "v93_publisher", "can_pre_bob_guard": "v94_15_andrea", "can_translate": "v93_bob", "can_review": "v93_alfred", "can_publish": "v93_publisher", "can_audit": "v93_archivista", "can_publish_reports": "v93_simone_autonomous", "can_write_master_log": "v93_master_log"}
    write_json(ARTIFACT_DIR / "jarvis_status.json", jarvis_status)
    add_timeline(timeline, "Jarvis", "bootstrap_status_written", f"engine={engine}")

    massy_board = safe_agent(timeline=timeline, agent="Massy", phase="sentinel_board_ready", import_fn=import_massy, artifact_name="massy_board.json", default_handoff={"to_simone": 0, "to_menzo": 0, "hard_skipped": 0, "already_worked": 0}, note_fn=lambda r: "to_simone={to_simone} to_menzo={to_menzo} hard_skip={hard_skipped} already={already_worked}".format(**{**{"to_simone": 0, "to_menzo": 0, "hard_skipped": 0, "already_worked": 0}, **handoff(r)}))
    canonical.safely("observe_massy", massy_board)
    canonical.safely("observe_items", massy_board, ("report_candidates",), "report_candidate_seen", "Simone", "reporting", "success", "artifacts/newsroom/massy_board.json")
    add_timeline(timeline, "Massy", "forced_policy_active", f"version={massy_board.get('version')}")

    simone_decision = safe_agent(timeline=timeline, agent="Simone", phase="report_decision_ready", import_fn=import_simone, call_args=(massy_board,), artifact_name="simone_reports.json", default_handoff={"ready": 0, "waiting": 0, "skipped": 0}, note_fn=lambda r: "ready={ready} waiting={waiting} skipped={skipped}".format(**{**{"ready": 0, "waiting": 0, "skipped": 0}, **handoff(r)}))
    from agents.news_scheduling import REPORT_PUBLICATION_PLANNED
    REPORT_PUBLICATION_PLANNED.set(bool(simone_decision.get("ready_reports")))
    ready_weekly_report_keys = {
        str(row["report_id"]): str(row["report_key"])
        for row in simone_decision.get("ready_reports", [])
        if isinstance(row, dict) and row.get("report_id") and row.get("report_key")
    }

    # Active wins over Shadow. Capture includes the existing bounded softpool and duplicate gate.
    director_snapshot = None
    director_result = None
    menzo_preflight = None
    active_director = False
    try:
        from agents.menzo_editorial_director_active import enabled as active_enabled
        from agents.menzo_editorial_director_shadow import enabled as shadow_enabled
        active_director = active_enabled()
        if active_director or shadow_enabled():
            director_snapshot, director_result, menzo_preflight = capture_editorial_director_opportunity(
                massy_board, run_id=os.environ["NEWSROOM_RUN_ID"], observation_timestamp=utc_now(),
                preserve_active_metadata=active_director,
                ready_weekly_report_keys=ready_weekly_report_keys)
    except Exception as exc:
        director_result = {"status": "CAPTURE_FAILED", "fallback_reason": type(exc).__name__}
        add_timeline(timeline, "Menzo", "editorial_director_capture_failed_open", type(exc).__name__)

    if active_director:
        try:
            if director_snapshot is None or director_result is not None:
                raise RuntimeError(str((director_result or {}).get("fallback_reason") or
                                       (director_result or {}).get("status") or "capture_unavailable"))
            from agents.menzo_editorial_director_active import evaluate as evaluate_active, project as project_active
            director_result = evaluate_active(director_snapshot, artifact_index=artifacts)
            if director_result.get("status") == "VALIDATED":
                menzo_decision = project_active(director_snapshot, director_result)
                observe_applied_active_authority(artifacts, director_snapshot, director_result)
                add_timeline(timeline, "Menzo", "editorial_director_active_authoritative", "VALIDATED")
            else:
                raise RuntimeError(str(director_result.get("fallback_reason") or director_result.get("status")))
        except Exception as exc:
            reason = active_fallback_reason(director_result, exc)
            menzo_decision = persist_active_fail_closed(director_snapshot, reason)
            add_timeline(timeline, "Menzo", "editorial_director_active_fail_closed", reason)
    else:
        menzo_decision = safe_agent(timeline=timeline, agent="Menzo", phase="editorial_decision_ready", import_fn=import_menzo, call_args=(massy_board,), call_kwargs=({"costly_work_preflight": menzo_preflight} if menzo_preflight is not None else {}), artifact_name="menzo_decisions.json", default_handoff={"to_bob_or_v92": 0, "pending": 0, "skipped": 0}, note_fn=lambda r: "selected={to_bob_or_v92} pending={pending} skipped={skipped}".format(**{**{"to_bob_or_v92": 0, "pending": 0, "skipped": 0}, **handoff(r)}))
    canonical.safely("observe_menzo", menzo_decision)
    add_timeline(timeline, "Menzo", "forced_policy_active", f"version={menzo_decision.get('version')}")

    news_before_report = selected_news_precede_report(menzo_decision, simone_decision)
    add_timeline(timeline, "Jarvis", "news_report_sequence",
                 "selected_show_news_first" if news_before_report else "report_before_news_generation")
    if not news_before_report:
        simone_publish = publish_simone_reports(simone_decision, timeline, canonical)

    andrea_handoff = safe_agent(timeline=timeline, agent="Andrea", phase="pre_bob_content_sufficiency_ready", import_fn=import_andrea, call_args=(menzo_decision,), artifact_name="andrea_pre_bob_latest.json", default_handoff={"to_bob": 0, "blocked_before_bob": 0, "saved_gemini_calls": 0}, note_fn=lambda r: "to_bob={to_bob_or_v92} checked={andrea_checked} blocked={andrea_blocked} saved_gemini={andrea_saved_gemini_calls}".format(**{**{"to_bob_or_v92": 0, "andrea_checked": 0, "andrea_blocked": 0, "andrea_saved_gemini_calls": 0}, **handoff(r)}))
    record_andrea_avoids_from_result(andrea_handoff)
    canonical.safely("observe_andrea", andrea_handoff)
    canonical.safely("observe_bob_requested", andrea_handoff)

    bob_result = safe_agent(timeline=timeline, agent="Bob", phase="article_packages_ready", import_fn=import_bob, call_args=(andrea_handoff,), artifact_name="bob_articles.json", default_handoff={"ready_for_alfred": 0, "translation_pending": 0, "translation_validation_failed": 0, "errors": 0, "extraction_empty": 0}, note_fn=lambda r: "ready={ready_for_alfred} pending={translation_pending} validation_failed={translation_validation_failed} empty={extraction_empty} errors={errors}".format(**{**{"ready_for_alfred": 0, "translation_pending": 0, "translation_validation_failed": 0, "errors": 0, "extraction_empty": 0}, **handoff(r)}))
    bob_result = attach_bob_brief_warnings(bob_result, andrea_handoff)
    bob_cycle_status = str(bob_result.get("status") or "")
    if bob_cycle_status in {"error", "invalid_result"}:
        canonical.safely("event", "bob_generation_cycle", "Bob", "generation", "failed",
                         "artifacts/newsroom/bob_articles.json",
                         reason_code="bob_package_error",
                         error_class="invariant", error_terminal=True,
                         result=bob_cycle_status)
    else:
        canonical.safely("event", "bob_generation_cycle", "Bob", "generation", "success",
                         "artifacts/newsroom/bob_articles.json")
    canonical.safely("observe_bob_generated", bob_result)
    artifacts.safely("observe_bob", bob_result)
    write_json(ARTIFACT_DIR / "bob_articles.json", bob_result)
    add_timeline(timeline, "Bob", "bob_brief_guard_applied", f"warnings={bob_result.get('postprocess', {}).get('bob_brief_warnings_added', 0)}")

    alfred_result = safe_agent(timeline=timeline, agent="Alfred", phase="quality_review_ready", import_fn=import_alfred, call_args=(bob_result,), artifact_name="alfred_review.json", default_handoff={"approved": 0, "needs_revision": 0, "warnings": 0, "blockers": 0, "editorial_changes": 0}, note_fn=lambda r: "approved={approved} needs_revision={needs_revision} blockers={blockers} warnings={warnings} changes={editorial_changes}".format(**{**{"approved": 0, "needs_revision": 0, "warnings": 0, "blockers": 0, "editorial_changes": 0}, **handoff(r)}))
    alfred_result = surface_bob_warnings_in_alfred(alfred_result, bob_result)
    canonical.safely("observe_alfred", alfred_result)
    artifacts.safely("observe_alfred", alfred_result)
    write_json(ARTIFACT_DIR / "alfred_review.json", alfred_result)
    add_timeline(timeline, "Alfred", "bob_warning_guard_applied", f"surfaced={alfred_result.get('postprocess', {}).get('bob_warnings_surfaced', 0)}")

    publisher_result = safe_agent(timeline=timeline, agent="Publisher", phase="publication_ready", import_fn=import_publisher, call_args=(alfred_result,), artifact_name="publisher_result.json", default_handoff={"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}, note_fn=lambda r: "published={published} already={already_published} dry={dry_run} wp_not_ready={wp_not_ready} errors={errors}".format(**{**{"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}, **handoff(r)}))
    publisher_cycle_status = str(publisher_result.get("status") or "")
    if publisher_cycle_status in {"error", "invalid_result"}:
        canonical.safely("event", "publisher_observation_cycle", "Publisher", "publication", "failed",
                         "artifacts/newsroom/publisher_result.json",
                         reason_code="publisher_observation_cycle_failed",
                         error_class="invariant", error_terminal=True,
                         result=publisher_cycle_status)
    else:
        canonical.safely("event", "publisher_observation_cycle", "Publisher", "publication", "success",
                         "artifacts/newsroom/publisher_result.json")
    canonical.safely("observe_publisher", publisher_result)
    artifacts.safely("observe_publisher", publisher_result)

    # Always finish the ready report pass in this run, including news errors or
    # an empty downstream handoff. No waiting for more feed candidates or retries.
    if news_before_report:
        simone_publish = publish_simone_reports(simone_decision, timeline, canonical)

    # The observer runs only after Publisher and its value has no production consumer.
    if director_snapshot is not None and not active_director:
        try:
            from agents.menzo_editorial_director_shadow import evaluate
            director_result = evaluate(director_snapshot, menzo_decision, artifact_index=artifacts)
            add_timeline(timeline, "Menzo", "editorial_director_shadow_completed", str(director_result.get("status")))
        except Exception as exc:
            director_result = {"status": "failed_open", "error": type(exc).__name__}
            add_timeline(timeline, "Menzo", "editorial_director_shadow_failed_open", type(exc).__name__)

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
    run_summary = {"version": NEWSROOM_VERSION, "started_at": started_at, "ended_at": ended_at, "engine": engine, "newsroom_engine_override": is_test_override, "runtime_delegations": runtime_delegations, "runtime_exit_code": runtime_exit_code, "news_report_sequence": "selected_show_news_first" if news_before_report else "report_before_news_generation", "agents": {"jarvis": "real_orchestrator", "massy": "real_sentinel_control", "simone": "real_report_director_and_autonomous_report_publisher", "menzo": "real_editorial_director", "andrea": "real_pre_bob_content_sufficiency_guard", "bob": "real_article_writer", "alfred": "real_quality_editor", "publisher": "real_wordpress_publisher", "archivista": "real_audit_agent", "master_log": "real_structured_run_memory"}, "massy_handoff": handoff(massy_board), "simone_handoff": handoff(simone_decision), "simone_publish_handoff": handoff(simone_publish), "menzo_handoff": handoff(menzo_decision), "andrea_handoff": handoff(andrea_handoff), "bob_handoff": handoff(bob_result), "alfred_handoff": handoff(alfred_result), "publisher_handoff": handoff(publisher_result), "gemini_ledger_summary": gemini_ledger_summary()}
    if director_result is not None:
        run_summary["editorial_director_active" if active_director else "editorial_director_shadow"] = director_result

    archivista_result = safe_agent(
        timeline=timeline,
        agent="Archivista",
        phase="audit_ready",
        import_fn=import_archivista,
        call_kwargs={
            "timeline": timeline,
            "run_summary": run_summary,
            "massy": massy_board,
            "simone": simone_decision,
            "menzo": menzo_decision,
            "bob": bob_result,
            "alfred": alfred_result,
            "publisher": publisher_result,
        },
        artifact_name="archivista_report.json",
        default_handoff={"overall_status": "error"},
        note_fn=lambda r: "status={status} anomalies={anomalies}".format(
            status=r.get("overall_status", "unknown"),
            anomalies=(r.get("summary", {}) if isinstance(r.get("summary"), dict) else {}).get("anomalies", 0),
        ),
    )
    if isinstance(andrea_handoff, dict):
        ah = handoff(andrea_handoff)
        run_summary.update({
            "andrea_checked": ah.get("andrea_checked", 0),
            "andrea_passed": ah.get("andrea_passed", 0),
            "andrea_blocked": ah.get("andrea_blocked", 0),
            "andrea_saved_gemini_calls": ah.get("andrea_saved_gemini_calls", 0),
            "andrea_block_reasons": ah.get("andrea_block_reasons", []),
            "andrea_passed_with_exception": ah.get("andrea_passed_with_exception", 0),
        })
    run_summary["archivista_handoff"] = archivista_result.get("summary", {}) if isinstance(archivista_result, dict) else {}
    run_summary["archivista_status"] = archivista_result.get("overall_status") if isinstance(archivista_result, dict) else "error"
    if isinstance(archivista_result, dict) and archivista_result.get("status") != "error":
        canonical.safely("event", "audit_completed", "Archivista", "audit", "success", "artifacts/newsroom/archivista_report.json")
    if runtime_exit_code == 0:
        canonical.safely("event", "run_completed", "Jarvis", "runtime", "success")
    run_summary["canonical_event_ledger"] = canonical.summary()
    run_summary["canonical_artifact_index"] = artifacts.summary()

    master_log_result = write_master_log_safe(
        timeline,
        run_summary=run_summary,
        massy=massy_board,
        simone=simone_decision,
        simone_publish=simone_publish,
        menzo=menzo_decision,
        bob=bob_result,
        alfred=alfred_result,
        publisher=publisher_result,
        archivista=archivista_result,
    )
    run_summary["master_log"] = master_log_result

    write_json(ARTIFACT_DIR / "agent_timeline.json", timeline)
    write_json(ARTIFACT_DIR / "run_summary.json", run_summary)
    try:
        from agents.canonical_event_ledger import clear_active_ledger
        clear_active_ledger()
    except Exception:
        pass
    print(f"[ARCHIVISTA v93] Saved {ARTIFACT_DIR / 'run_summary.json'}", flush=True)
    print(f"===== NEWSROOM RUN END [{ended_at}] VERSION [{NEWSROOM_VERSION}] EXIT [{runtime_exit_code}] =====", flush=True)
    return runtime_exit_code




if __name__ == "__main__":
    raise SystemExit(main())
