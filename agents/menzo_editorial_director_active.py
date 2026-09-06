"""ED-2 Active Gemini Editorial Director authority and Menzo compatibility adapter."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from agents import menzo_editorial_director_shadow as shadow
from agents.canonical_event_ledger import OperationalAIRequest, active_event
from agents.gemini_ledger import record_gemini_attempt

ROOT = Path(__file__).resolve().parents[1]
MODEL = shadow.MODEL
SCHEMA_VERSION = "owtv_editorial_director_output_v3"
POLICY_VERSION = "owtv_editorial_director_policy_v3_active"
SCHEMA_PATH = ROOT / "config/editorial_director_output_schema_v3.json"
POLICY_PATH = ROOT / "docs/editorial-rules/OWTV_GEMINI_EDITORIAL_DIRECTOR_POLICY_V3_ACTIVE.md"


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    value = (environ or os.environ).get("OWTV_EDITORIAL_DIRECTOR_ACTIVE_ENABLED", "false")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def prepare_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Apply only frozen exact-duplicate authority and expose Bob's live capacity."""
    from agents.menzo_policy_v93_15 import canonical_richer_winner, hydrate_complete_article_bodies
    from agents.bob import dynamic_article_capacity

    relations_were_complete = bool(snapshot.get("authorized_relations_complete", True))
    candidates = list(snapshot.get("candidates", []))
    history = list(snapshot.get("publisher_history_12h", []))
    deterministic_skips: list[dict[str, Any]] = []

    # Published exact matches have no continuing eligibility.
    retained = []
    for candidate in candidates:
        exact_history = next((old for old in history
            if shadow.menzo_duplicate_scorer.score_pair(candidate, old)["exact_duplicate"]), None)
        if exact_history is None:
            retained.append(candidate)
        else:
            deterministic_skips.append({**copy.deepcopy(candidate), "exact_duplicate_scope": "recent_history",
                                        "exact_duplicate_of": exact_history.get("article_id")})

    # Resolve connected same-run exact components with the established richer-winner contract.
    parent = list(range(len(retained)))
    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]; index = parent[index]
        return index
    def union(left: int, right: int) -> None:
        a, b = find(left), find(right)
        if a != b: parent[b] = a
    for left in range(len(retained)):
        for right in range(left + 1, len(retained)):
            if shadow.menzo_duplicate_scorer.score_pair(retained[left], retained[right])["exact_duplicate"]:
                union(left, right)
    groups: dict[int, list[dict[str, Any]]] = {}
    for index, candidate in enumerate(retained): groups.setdefault(find(index), []).append(candidate)
    winners = []
    for group in groups.values():
        if len(group) > 1:
            local_group = copy.deepcopy(group)
            hydrate_complete_article_bodies(local_group)
            local_winner, _ = canonical_richer_winner(local_group)
            winner = next(item for item in group if item["candidate_id"] == local_winner["candidate_id"])
        else:
            winner = group[0]
        winners.append(winner)
        deterministic_skips.extend({**copy.deepcopy(item), "exact_duplicate_scope": "same_run",
                                    "exact_duplicate_of": winner["candidate_id"]}
                                   for item in group if item is not winner)
    snapshot["candidates"] = winners
    winner_ids = {item["candidate_id"] for item in winners}
    snapshot["authorized_relations"] = [relation for relation in snapshot.get("authorized_relations", [])
        if relation.get("left_id") in winner_ids and
        (relation.get("scope") != "same_run" or relation.get("right_id") in winner_ids)]
    if not relations_were_complete:
        rebuilt, complete = shadow.build_authorized_relations(winners, history)
        snapshot["authorized_relations"] = rebuilt
        snapshot["authorized_relations_complete"] = complete
    snapshot["deterministic_exact_skips"] = deterministic_skips
    capacity, reason = dynamic_article_capacity({"selected": winners}, winners)
    snapshot["downstream_capacity"] = max(0, capacity)
    snapshot["downstream_capacity_reason"] = reason
    _finalize_active_input(snapshot)
    return snapshot


def active_provider_input(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Single canonical ED-2 provider projection used by bounds, digest and prompt."""
    provider_data = shadow.provider_input(snapshot)
    provider_data["publication_context"].update(
        downstream_capacity_hint=snapshot.get("downstream_capacity"),
        downstream_capacity_hint_reason=snapshot.get("downstream_capacity_reason"),
        remaining_slots=snapshot.get("remaining_slots"))
    return provider_data


def _finalize_active_input(snapshot: dict[str, Any]) -> None:
    snapshot.setdefault("capture_input_digest", snapshot.get("input_digest"))
    serialized = json.dumps(active_provider_input(snapshot), ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")).encode("utf-8")
    snapshot["observed"] = {**(snapshot.get("observed") or {}),
        "candidate_count": len(snapshot.get("candidates", [])),
        "relation_count": len(snapshot.get("authorized_relations", [])),
        "serialized_input_bytes": len(serialized)}
    snapshot["input_digest"] = hashlib.sha256(serialized).hexdigest()
    ratio = max(len(snapshot.get("candidates", [])) / shadow.MAX_CANDIDATES,
                len(snapshot.get("authorized_relations", [])) / shadow.MAX_RELATIONS,
                len(serialized) / shadow.MAX_INPUT_BYTES)
    snapshot["limit_status"] = "exceeded" if ratio > 1 else ("approaching" if ratio >= shadow.APPROACH_RATIO else "within")


def _validate_active(value: Any, snapshot: Mapping[str, Any]):
    output, failures, telemetry = shadow.canonicalize_output(value, snapshot)
    if failures or output is None:
        return None, failures, telemetry
    raw_by_ref = {row.get("ref"): row for row in value.get("candidates", []) if isinstance(row, Mapping)}
    refs, relations = shadow.short_ref_maps(snapshot)
    actions: dict[str, str | None] = {}
    for ref, candidate in refs.items():
        raw = raw_by_ref.get(ref, {})
        action = raw.get("recommended_action")
        if action not in shadow.ACTIONS:
            failures.append({"family": "recommended_action", "ref": ref, "detail": "mandatory_active_field"})
        actions[candidate["candidate_id"]] = action
    selected = sum(action == "SELECT" for action in actions.values())
    if selected > int(snapshot.get("remaining_slots", 0)):
        failures.append({"family": "publication_capacity", "selected": selected,
                         "remaining_slots": int(snapshot.get("remaining_slots", 0))})
    selected_candidates = [refs[ref] for ref, raw in raw_by_ref.items()
                           if raw.get("recommended_action") == "SELECT" and ref in refs]
    from agents.bob import dynamic_article_capacity
    downstream_capacity, capacity_reason = dynamic_article_capacity({"selected": selected_candidates}, selected_candidates)
    if selected > downstream_capacity:
        failures.append({"family": "downstream_capacity", "selected": selected,
                         "capacity": downstream_capacity, "capacity_reason": capacity_reason})
    if any(row.get("detail") == "skip_invariant_overridden" for row in telemetry):
        failures.append({"family": "skip_action_invariant", "detail": "active_semantic_rewrite_forbidden"})
    for relation in output["relations"]:
        if relation["decision"] != "DUPLICATE":
            continue
        left_action = actions.get(relation["left_id"])
        right_action = actions.get(relation["right_id"])
        if relation["scope"] == "recent_history" and left_action != "SKIP":
            failures.append({"family": "recent_history_duplicate_action", "pair_id": relation["pair_id"]})
        if relation["scope"] == "same_run" and left_action != "SKIP" and right_action != "SKIP":
            failures.append({"family": "same_run_duplicate_action", "pair_id": relation["pair_id"]})
    if failures:
        return None, failures, telemetry
    output["schema_version"] = SCHEMA_VERSION
    output["policy_version"] = POLICY_VERSION
    return output, [], telemetry


def _prompt(snapshot: Mapping[str, Any], failures: list[dict[str, Any]] | None = None) -> str:
    policy = POLICY_PATH.read_text(encoding="utf-8")
    provider_data = active_provider_input(snapshot)
    prompt = (f"ACTIVE_POLICY_VERSION={POLICY_VERSION}\nACTIVE_POLICY_SHA256={hashlib.sha256(policy.encode()).hexdigest()}\n"
              f"<ACTIVE_POLICY>\n{policy}\n</ACTIVE_POLICY>\nReturn only JSON. Evaluate every candidate and authorized relation once. "
              "Candidate order expresses preference within class. INPUT=" +
              json.dumps(provider_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if failures is not None:
        prompt += "\nREPAIR ONLY THESE VALIDATION FAMILIES=" + json.dumps(failures[:20], separators=(",", ":"))
    return prompt


def evaluate(snapshot: Mapping[str, Any], *, provider: Callable[..., Any] | None = None,
             artifact_index: Any = None) -> dict[str, Any]:
    if isinstance(snapshot, dict):
        prepare_snapshot(snapshot)
    base = {"status": "failed", "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
            "observed": copy.deepcopy(snapshot.get("observed")), "limit_status": snapshot.get("limit_status"),
            "attempts": 0, "validation_attempts": []}
    if snapshot.get("limit_status") in {"projection_failed", "exceeded"}:
        status = "PROJECTION_FAILED" if snapshot.get("limit_status") == "projection_failed" else "OVERSIZE_NOT_EVALUATED"
        return {**base, "status": status, "fallback_reason": status}
    if not snapshot.get("candidates"):
        return {**base, "status": "VALIDATED", "attempts": 0,
                "output": {"schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
                           "candidates": [], "relations": []}, "validation_errors": []}
    request = OperationalAIRequest("Menzo", "editorial_director_active", reason_code="editorial_director_active")
    schema = json.loads(SCHEMA_PATH.read_text())
    digest = hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
    try:
        call = provider or shadow._default_provider_factory()
    except Exception as exc:
        request.initialization_failed(str(exc))
        return {**base, "status": "PROVIDER_UNAVAILABLE", "fallback_reason": type(exc).__name__}
    failures: list[dict[str, Any]] = []
    for index in range(2):
        repair = index == 1
        attempt = request.start(MODEL, repair=repair, reason_code="active_validation_failed" if repair else "")
        started = time.monotonic(); response = None
        try:
            response = call(_prompt(snapshot, failures if repair else None), schema, shadow.PROVIDER_TIMEOUT_SECONDS)
        except Exception as exc:
            record_gemini_attempt(response=response, model_requested=MODEL, operation_id=request.logical_request_id,
                attempt_index=index, repair=repair, fallback=False, agent="Menzo", workload="editorial_director_active",
                phase="editorial_director_active_repair" if repair else "editorial_director_active_primary", shadow=False,
                logical_request_id=request.logical_request_id, canonical_attempt_id=attempt["attempt_id"],
                candidate_count=len(snapshot["candidates"]), relation_count=len(snapshot["authorized_relations"]),
                input_digest=snapshot["input_digest"], policy_version=POLICY_VERSION, policy_digest=digest,
                status="failed", error_class=type(exc).__name__)
            request.failed(attempt, error_class="upstream", error_terminal=True,
                           latency_ms=int((time.monotonic() - started) * 1000))
            return {**base, "attempts": index + 1, "status": "PROVIDER_FAILED",
                    "fallback_reason": type(exc).__name__, "logical_request_id": request.logical_request_id}
        record_gemini_attempt(response=response, model_requested=MODEL, operation_id=request.logical_request_id,
            attempt_index=index, repair=repair, fallback=False, agent="Menzo", workload="editorial_director_active",
            phase="editorial_director_active_repair" if repair else "editorial_director_active_primary", shadow=False,
            logical_request_id=request.logical_request_id, canonical_attempt_id=attempt["attempt_id"],
            candidate_count=len(snapshot["candidates"]), relation_count=len(snapshot["authorized_relations"]),
            input_digest=snapshot["input_digest"], policy_version=POLICY_VERSION, policy_digest=digest, status="called")
        request.defer(attempt, int((time.monotonic() - started) * 1000))
        try:
            output, failures, canonicalized = _validate_active(shadow._decode(response), snapshot)
        except Exception as exc:
            output, failures, canonicalized = None, [{"family": "parse_json", "detail": type(exc).__name__}], []
        base["validation_attempts"].append({"attempt_index": index, "valid": not failures,
            "validation_families": failures, "canonicalizations": canonicalized})
        request.resolve_deferred(not failures, error_terminal=repair and bool(failures))
        if not failures:
            result = {**base, "status": "VALIDATED", "attempts": index + 1,
                      "logical_request_id": request.logical_request_id, "policy_digest": digest,
                      "input_digest": snapshot["input_digest"], "output": output, "validation_errors": []}
            active_event("stage_completed", "Menzo", "selection", "success",
                         result="editorial_director_active_authorized", reason_code="editorial_director_active")
            if artifact_index is not None:
                artifact_index.safely("observe_editorial_director_active", snapshot, output, result)
            return result
    return {**base, "attempts": 2, "logical_request_id": request.logical_request_id,
            "validation_errors": failures, "fallback_reason": failures[0]["family"] if failures else "validation_failed"}


def project(snapshot: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    """Mechanically project one wholly validated Active decision into Menzo's handoff."""
    originals = {row["candidate_id"]: row for row in snapshot.get("candidates", [])}
    sections = {"SELECT": "selected", "DEFER": "pending", "SKIP": "skipped"}
    projected: dict[str, Any] = {"selected": [], "pending": [], "skipped": [], "version": POLICY_VERSION,
        "policy_version": POLICY_VERSION, "mode": "editorial_director_active",
        "decision_authority": "editorial_director"}
    for decision in result["output"]["candidates"]:
        item = copy.deepcopy(originals[decision["candidate_id"]])
        item.pop("candidate_id", None)
        item["editorial_director"] = {"policy_version": POLICY_VERSION, **copy.deepcopy(decision),
                                      "decision_authority": "editorial_director"}
        item["decision_authority"] = "editorial_director"
        item["pipeline_version"] = POLICY_VERSION
        item["decision"] = decision["recommended_action"].lower()
        item["category_hint"] = decision["category"]
        item["priority"] = {"MUST_PUBLISH": "high", "SHOULD_PUBLISH": "high",
                            "PUBLISHABLE_SOFT": "medium", "SKIP": "skip"}[decision["editorial_class"]]
        projected[sections[decision["recommended_action"]]].append(item)
    for exact in snapshot.get("deterministic_exact_skips", []):
        item = copy.deepcopy(exact); item.pop("candidate_id", None)
        item.update(decision="skip", priority="skip", decision_authority="deterministic_exact_duplicate",
                    reason="exact_duplicate")
        projected["skipped"].append(item)
    projected["relations"] = copy.deepcopy(result["output"]["relations"])
    projected["handoff"] = {"to_bob_or_v92": len(projected["selected"]), "pending": len(projected["pending"]),
                             "skipped": len(projected["skipped"]), "decision_authority": "editorial_director"}
    projected["allowed_urls_for_v92"] = [str(item.get("url") or item.get("source_url"))
        for item in projected["selected"] if item.get("url") or item.get("source_url")]
    from agents.menzo_policy_v93_15 import (ARTIFACT_DECISIONS_FILE, MENZO_DECISIONS_FILE,
        V92_ALLOWED_URLS_FILE, save_hard_skips, save_softpool, utc_now, write_json)
    save_softpool(projected)
    save_hard_skips(projected)
    write_json(MENZO_DECISIONS_FILE, projected)
    write_json(ARTIFACT_DECISIONS_FILE, projected)
    write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": POLICY_VERSION,
                                      "decision_authority": "editorial_director",
                                      "allowed_urls": projected["allowed_urls_for_v92"]})
    return projected
