"""ED-2 Active Gemini Editorial Director authority and Menzo compatibility adapter."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Mapping

from agents import menzo_editorial_director_shadow as shadow
from agents.canonical_event_ledger import OperationalAIRequest
from agents.gemini_ledger import record_gemini_attempt

ROOT = Path(__file__).resolve().parents[1]
MODEL = shadow.MODEL
SCHEMA_VERSION = "owtv_editorial_director_output_v3"
POLICY_VERSION = "owtv_editorial_director_policy_v3_active"
SCHEMA_PATH = ROOT / "config/editorial_director_output_schema_v3.json"
POLICY_PATH = ROOT / "docs/editorial-rules/OWTV_GEMINI_EDITORIAL_DIRECTOR_POLICY_V3_ACTIVE.md"
RELATION_SCHEMA_PATH = ROOT / "config/editorial_director_duplicate_gate_schema_v3.json"
BOB_CAPACITY_FIELDS = ("article_type", "source_title", "category_hint", "reason",
                       "ai_editorial_reason", "event_key")
DUPLICATE_EVIDENCE_FIELDS = ("left_evidence", "right_evidence")
DUPLICATE_CENTRALITY_FIELDS = ("left_central_development", "right_central_development",
                               "centrality_basis")
DUPLICATE_RELATION_FIELDS = {"ref", "decision", "shared_fact", "new_fact", "temporal_basis",
                             *DUPLICATE_EVIDENCE_FIELDS, *DUPLICATE_CENTRALITY_FIELDS}
GROUNDING_SOURCE_FIELDS = ("title", "source_title", "title_it", "summary", "retained_body")
ANCHOR_SOURCE_FIELDS = ("title", "source_title", "title_it")
MAX_DUPLICATE_SEMANTIC_FIELD_LENGTH = 500
MIN_DUPLICATE_EVIDENCE_TOKENS = 2
MIN_DUPLICATE_EVIDENCE_ALNUM_CHARS = 8


def enabled(environ: Mapping[str, str] | None = None) -> bool:
    value = (environ or os.environ).get("OWTV_EDITORIAL_DIRECTOR_ACTIVE_ENABLED", "false")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def preserve_bob_capacity_metadata(snapshot: dict[str, Any], candidates: list[Mapping[str, Any]]) -> None:
    """Attach an Active-local sidecar which is never part of provider projection."""
    from agents.duplicate_pair_identity import article_id
    known = {row.get("candidate_id") for row in snapshot.get("candidates", [])}
    sidecar = {}
    for item in candidates:
        candidate_id = article_id(item)
        if candidate_id in known:
            metadata = {field: copy.deepcopy(item[field]) for field in BOB_CAPACITY_FIELDS if field in item}
            if metadata:
                sidecar[candidate_id] = metadata
    snapshot["_active_bob_capacity_metadata"] = sidecar


def _capacity_candidate(snapshot: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    sidecar = snapshot.get("_active_bob_capacity_metadata", {})
    metadata = sidecar.get(candidate.get("candidate_id"), {}) if isinstance(sidecar, Mapping) else {}
    return {**copy.deepcopy(dict(candidate)), **copy.deepcopy(dict(metadata))}


def _refresh_capacity_hint(snapshot: dict[str, Any]) -> None:
    """Advertise only ordinary capacity guaranteed before classes/actions exist."""
    from agents.bob import dynamic_article_capacity
    base_capacity, reason = dynamic_article_capacity({"selected": []}, [])
    remaining_slots = max(0, int(snapshot.get("remaining_slots", 0)))
    snapshot["downstream_capacity"] = min(remaining_slots, max(0, base_capacity))
    snapshot["downstream_capacity_reason"] = reason


def prepare_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Apply only frozen exact-duplicate authority and expose Bob's live capacity."""
    from agents.menzo_policy_v93_15 import canonical_richer_winner, hydrate_complete_article_bodies

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
    # This pre-provider value remains only the existing compact-pool hint. The
    # authoritative capacity is recomputed from sidecar-restored SELECT rows.
    _refresh_capacity_hint(snapshot)
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
    refs, relations = shadow.short_ref_maps(snapshot)
    canonical_by_id = {row["candidate_id"]: row for row in output["candidates"]}
    actions: dict[str, str | None] = {}
    classes: dict[str, str | None] = {}
    for ref, candidate in refs.items():
        canonical = canonical_by_id.get(candidate["candidate_id"], {})
        action = canonical.get("recommended_action")
        if action not in shadow.ACTIONS:
            failures.append({"family": "recommended_action", "ref": ref, "detail": "mandatory_active_field"})
        actions[candidate["candidate_id"]] = action
        classes[candidate["candidate_id"]] = canonical.get("editorial_class")
        allowed = {"MUST_PUBLISH": {"SELECT"}, "SHOULD_PUBLISH": {"SELECT", "DEFER"},
                   "PUBLISHABLE_SOFT": {"SELECT", "DEFER"}, "SKIP": {"SKIP"}}
        if canonical.get("editorial_class") in allowed and action not in allowed[canonical["editorial_class"]]:
            failures.append({"family": "class_action_incompatibility", "ref": ref,
                             "editorial_class": canonical.get("editorial_class"), "recommended_action": action})
    selected = sum(action == "SELECT" for action in actions.values())
    must_selected = sum(actions[cid] == "SELECT" and classes[cid] == "MUST_PUBLISH" for cid in actions)
    ordinary_selected = selected - must_selected
    if ordinary_selected > int(snapshot.get("remaining_slots", 0)):
        failures.append({"family": "publication_capacity", "selected_ordinary": ordinary_selected,
                         "remaining_slots": int(snapshot.get("remaining_slots", 0))})
    ordinary_candidates = [_capacity_candidate(snapshot, candidate) for candidate in refs.values()
                           if actions.get(candidate["candidate_id"]) == "SELECT" and
                           classes.get(candidate["candidate_id"]) != "MUST_PUBLISH"]
    from agents.bob import dynamic_article_capacity
    ordinary_capacity, capacity_reason = dynamic_article_capacity(
        {"selected": ordinary_candidates}, ordinary_candidates)
    if ordinary_selected > ordinary_capacity:
        failures.append({"family": "downstream_capacity", "ordinary_selected": ordinary_selected,
                         "ordinary_capacity": ordinary_capacity, "must_selected": must_selected,
                         "capacity_reason": capacity_reason})
    if any(row.get("detail") == "skip_invariant_overridden" for row in telemetry):
        failures.append({"family": "skip_action_invariant", "detail": "active_semantic_rewrite_forbidden"})
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


def _normalize_grounding_text(value: str) -> str:
    """Normalize formatting only; this deliberately performs no semantic matching."""
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'",
                                           "“": '"', "”": '"', "„": '"', "‟": '"',
                                           "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-"}))
    return re.sub(r"\s+", " ", value).strip()


def _duplicate_gate_endpoint_maps(snapshot: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]],
                                                                          dict[str, Mapping[str, Any]]]:
    """Resolve each request-local relation ref to its exact provider-visible endpoints."""
    provider_data = active_provider_input(snapshot)
    endpoints = {str(row.get("ref")): row for table in ("candidates", "history")
                 for row in provider_data.get(table, []) if isinstance(row, Mapping)}
    relations = {}
    for relation in provider_data.get("authorized_relations", []):
        if not isinstance(relation, Mapping):
            continue
        left, right = endpoints.get(str(relation.get("left_ref"))), endpoints.get(str(relation.get("right_ref")))
        if left is not None and right is not None:
            relations[str(relation.get("ref"))] = {"left": left, "right": right}
    return endpoints, relations


def _grounded_evidence(value: Any, endpoint: Mapping[str, Any]) -> tuple[bool, str]:
    if not isinstance(value, str) or not value.strip():
        return False, "missing_or_empty"
    if len(value) > MAX_DUPLICATE_SEMANTIC_FIELD_LENGTH:
        return False, "too_long"
    evidence = _normalize_grounding_text(value)
    if not evidence:
        return False, "missing_or_empty"
    tokens = re.findall(r"[^\W_]+", evidence, flags=re.UNICODE)
    if (len(tokens) < MIN_DUPLICATE_EVIDENCE_TOKENS or
            sum(len(token) for token in tokens) < MIN_DUPLICATE_EVIDENCE_ALNUM_CHARS):
        return False, "insufficient_meaningful_span"
    first_alnum = next(index for index, character in enumerate(evidence) if character.isalnum())
    last_alnum = max(index for index, character in enumerate(evidence) if character.isalnum())
    contained_without_boundary = False
    for field in GROUNDING_SOURCE_FIELDS:
        source = endpoint.get(field)
        if not isinstance(source, str):
            continue
        normalized_source = _normalize_grounding_text(source)
        for match in re.finditer(re.escape(evidence), normalized_source):
            contained_without_boundary = True
            start, end = match.start() + first_alnum, match.start() + last_alnum + 1
            if ((start == 0 or not normalized_source[start - 1].isalnum()) and
                    (end == len(normalized_source) or not normalized_source[end].isalnum())):
                return True, field
    if contained_without_boundary:
        return False, "not_token_boundary_aligned"
    return False, "not_contained_in_exact_endpoint"


def _bounded_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_DUPLICATE_SEMANTIC_FIELD_LENGTH


def _lexical_tokens(value: str) -> list[str]:
    return re.findall(r"[^\W_]+", _normalize_grounding_text(value), flags=re.UNICODE)


def _contains_aligned_anchor(value: Any, anchor: str) -> bool:
    if not isinstance(value, str):
        return False
    tokens = _lexical_tokens(value)
    anchor_tokens = _lexical_tokens(anchor)
    width = len(anchor_tokens)
    return bool(width and any(tokens[index:index + width] == anchor_tokens
                              for index in range(len(tokens) - width + 1)))


def _non_anchor_lexical_overlap(left: str, right: str, anchor: str) -> int:
    anchor_tokens = set(_lexical_tokens(anchor))
    return len((set(_lexical_tokens(left)) - anchor_tokens) &
               (set(_lexical_tokens(right)) - anchor_tokens))


def _explicit_endpoint_subjects(endpoint: Mapping[str, Any]) -> set[str]:
    return set().union(*(shadow.menzo_duplicate_scorer.explicit_named_subjects(value)
                         for field in ANCHOR_SOURCE_FIELDS
                         if isinstance((value := endpoint.get(field)), str)))


def _validate_duplicate_anchor_contract(ref: Any, duplicate_values: Mapping[str, Any],
                                        shared_fact: Any, endpoints: Mapping[str, Mapping[str, Any]],
                                        failures: list[dict[str, Any]]) -> None:
    """Bind grounded claims to one shared explicit subject without judging semantics."""
    shared_anchors = (_explicit_endpoint_subjects(endpoints.get("left", {})) &
                      _explicit_endpoint_subjects(endpoints.get("right", {})))
    if not shared_anchors:
        failures.append({"family": "duplicate_relation_anchor_grounding", "ref": ref,
                         "detail": "no_shared_explicit_subject"})
        return
    ordered = sorted(shared_anchors, key=lambda anchor: (-len(_lexical_tokens(anchor)), -len(anchor), anchor))
    left_evidence, right_evidence = duplicate_values["left_evidence"], duplicate_values["right_evidence"]
    left_anchors = {anchor for anchor in ordered if _contains_aligned_anchor(left_evidence, anchor)}
    right_anchors = {anchor for anchor in ordered if _contains_aligned_anchor(right_evidence, anchor)}
    evidence_anchors = left_anchors & right_anchors
    if not evidence_anchors:
        if not left_anchors or right_anchors:
            failures.append({"family": "duplicate_left_evidence_grounding", "ref": ref,
                             "detail": "missing_shared_subject_anchor"})
        if not right_anchors or left_anchors:
            failures.append({"family": "duplicate_right_evidence_grounding", "ref": ref,
                             "detail": "missing_shared_subject_anchor"})
        return
    claims = {"shared_fact": shared_fact,
              "left_central_development": duplicate_values["left_central_development"],
              "right_central_development": duplicate_values["right_central_development"]}
    fully_linked = [anchor for anchor in ordered if anchor in evidence_anchors and
                    all(_contains_aligned_anchor(value, anchor) for value in claims.values())]
    selected = fully_linked[0] if fully_linked else next(anchor for anchor in ordered if anchor in evidence_anchors)
    if not _contains_aligned_anchor(shared_fact, selected):
        failures.append({"family": "duplicate_claim_anchor_grounding", "ref": ref,
                         "detail": "missing_shared_subject_anchor"})
    for side in ("left", "right"):
        central = duplicate_values[f"{side}_central_development"]
        evidence = duplicate_values[f"{side}_evidence"]
        details = []
        if not _contains_aligned_anchor(central, selected):
            details.append("missing_shared_subject_anchor")
        if isinstance(central, str) and isinstance(evidence, str):
            if _non_anchor_lexical_overlap(central, evidence, selected) < 2:
                details.append("insufficient_evidence_factual_linkage")
        if details:
            failures.append({"family": "duplicate_centrality_contract", "ref": ref,
                             "field": f"{side}_central_development", "details": details})
    if isinstance(shared_fact, str):
        for side in ("left", "right"):
            evidence = duplicate_values[f"{side}_evidence"]
            if isinstance(evidence, str) and _non_anchor_lexical_overlap(
                    shared_fact, evidence, selected) < 2:
                failures.append({"family": "duplicate_claim_anchor_grounding", "ref": ref,
                                 "detail": f"insufficient_{side}_evidence_factual_linkage"})


def _validate_duplicate_gate(value: Any, snapshot: Mapping[str, Any]):
    """Active-local E04V: validate complete relation semantics and exact endpoint evidence."""
    failures: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    if not isinstance(value, Mapping):
        return None, [{"family": "parse_json", "detail": "output_not_object"}], telemetry
    for field in set(value) - {"relations"}:
        telemetry.append({"family": "locally_canonicalized_extra_field", "field": field})
    rows = value.get("relations")
    if not isinstance(rows, list):
        return None, [{"family": "other", "detail": "relations_array_required"}], telemetry
    _, relation_map = shadow.short_ref_maps(snapshot)
    _, endpoints_by_relation = _duplicate_gate_endpoint_maps(snapshot)
    seen: set[str] = set()
    canonical = []
    for row in rows:
        if not isinstance(row, Mapping):
            failures.append({"family": "relation_ref", "detail": "row_not_object"}); continue
        ref = row.get("ref")
        for field in set(row) - DUPLICATE_RELATION_FIELDS:
            telemetry.append({"family": "locally_canonicalized_extra_field", "ref": ref, "field": field})
        if ref not in relation_map:
            telemetry.append({"family": "relation_ref", "ref": ref, "detail": "unauthorized_dropped"}); continue
        if ref in seen:
            failures.append({"family": "relation_ref", "ref": ref, "detail": "duplicate"}); continue
        seen.add(ref)
        supplied = relation_map[ref]
        decision = shadow._enum(row.get("decision"), shadow.DECISIONS, "relation_decision", telemetry, ref)
        if decision is None:
            failures.append({"family": "relation_decision", "ref": ref}); continue
        shared, new, temporal = row.get("shared_fact"), row.get("new_fact"), row.get("temporal_basis")
        duplicate_values = {field: row.get(field) for field in
                            (*DUPLICATE_EVIDENCE_FIELDS, *DUPLICATE_CENTRALITY_FIELDS)}
        if decision == "DUPLICATE":
            if not _bounded_text(shared):
                failures.append({"family": "duplicate_shared_fact", "ref": ref})
            endpoints = endpoints_by_relation.get(str(ref), {})
            for side in ("left", "right"):
                valid, detail = _grounded_evidence(duplicate_values[f"{side}_evidence"], endpoints.get(side, {}))
                if not valid:
                    failures.append({"family": f"duplicate_{side}_evidence_grounding", "ref": ref,
                                     "detail": detail})
                else:
                    telemetry.append({"family": f"duplicate_{side}_evidence_grounded", "ref": ref,
                                      "source_field": detail})
            invalid_centrality = [field for field in DUPLICATE_CENTRALITY_FIELDS
                                  if not _bounded_text(duplicate_values[field])]
            if invalid_centrality:
                failures.append({"family": "duplicate_centrality_contract", "ref": ref,
                                 "fields": invalid_centrality})
            if _bounded_text(shared) and not invalid_centrality:
                _validate_duplicate_anchor_contract(ref, duplicate_values, shared, endpoints, failures)
        if decision == "MATERIAL_UPDATE":
            if supplied.get("scope") != "recent_history":
                failures.append({"family": "material_update_scope", "ref": ref})
            if not isinstance(new, str) or not new.strip():
                failures.append({"family": "material_update_new_fact", "ref": ref})
            if not isinstance(temporal, str) or not temporal.strip():
                failures.append({"family": "material_update_temporal_basis", "ref": ref})
        duplicate_extras = decision != "DUPLICATE" and any(
            value is not None for value in duplicate_values.values())
        semantic_extras = ((decision != "DUPLICATE" and shared is not None) or
                           (decision != "MATERIAL_UPDATE" and (new is not None or temporal is not None)) or
                           (decision == "MATERIAL_UPDATE" and shared is not None) or
                           duplicate_extras)
        if semantic_extras:
            failures.append({"family": "material_update_grounding", "ref": ref,
                             "detail": "conditional_semantic_fields_contradict_decision"})
        canonical.append({"pair_id": supplied["pair_id"], "scope": supplied["scope"],
            "left_id": supplied["left_id"], "right_id": supplied["right_id"], "decision": decision,
            "shared_fact": shared.strip() if isinstance(shared, str) and shared.strip() else None,
            "new_fact": new.strip() if isinstance(new, str) and new.strip() else None,
            "temporal_basis": temporal.strip() if isinstance(temporal, str) and temporal.strip() else None,
            **{field: (value.strip() if isinstance(value, str) and value.strip() else None)
               for field, value in duplicate_values.items()},
            "scorer": {key: copy.deepcopy(supplied.get(key))
                       for key in ("scorer_version", "score", "threshold", "components")}})
    missing = sorted(set(relation_map) - seen)
    if missing:
        failures.append({"family": "relation_coverage", "missing_refs": missing})
    return (None if failures else canonical), failures, telemetry


def _duplicate_prompt(snapshot: Mapping[str, Any], failures: list[dict[str, Any]] | None = None) -> str:
    policy = POLICY_PATH.read_text(encoding="utf-8")
    data = active_provider_input(snapshot)
    prompt = (f"ACTIVE_POLICY_VERSION={POLICY_VERSION}\n<ACTIVE_POLICY>\n{policy}\n</ACTIVE_POLICY>\n"
              "DUPLICATE GATE PHASE ONLY. Return only JSON with relations. Do not classify candidates. "
              "Evaluate every authorized relation once. INPUT=" +
              json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if failures is not None:
        prompt += "\nREPAIR ONLY THESE VALIDATION FAMILIES=" + json.dumps(failures[:20], separators=(",", ":"))
    return prompt


def _apply_duplicate_gate(snapshot: dict[str, Any], relations: list[dict[str, Any]]) -> None:
    """Remove semantic duplicates before any survivor receives an editorial class."""
    from agents.menzo_policy_v93_15 import canonical_richer_winner, hydrate_complete_article_bodies
    by_id = {row["candidate_id"]: row for row in snapshot.get("candidates", [])}
    parent = {candidate_id: candidate_id for candidate_id in by_id}
    def find(candidate_id: str) -> str:
        while parent[candidate_id] != candidate_id:
            parent[candidate_id] = parent[parent[candidate_id]]
            candidate_id = parent[candidate_id]
        return candidate_id
    for relation in relations:
        if relation["decision"] == "DUPLICATE" and relation["scope"] == "same_run":
            left, right = relation["left_id"], relation["right_id"]
            if left in parent and right in parent:
                parent[find(right)] = find(left)
    groups: dict[str, list[dict[str, Any]]] = {}
    for candidate_id, candidate in by_id.items():
        groups.setdefault(find(candidate_id), []).append(candidate)
    eliminated: dict[str, dict[str, Any]] = {}
    representative_by_member: dict[str, str] = {}
    component_members: dict[str, set[str]] = {}
    for group in groups.values():
        if len(group) > 1:
            hydrated = copy.deepcopy(group)
            hydrate_complete_article_bodies(hydrated)
            winner, _ = canonical_richer_winner(hydrated)
        else:
            winner = group[0]
        representative_id = winner["candidate_id"]
        member_ids = {candidate["candidate_id"] for candidate in group}
        component_members[representative_id] = member_ids
        same_run_evidence = [relation["pair_id"] for relation in relations
            if relation["decision"] == "DUPLICATE" and relation["scope"] == "same_run" and
            relation["left_id"] in member_ids and relation["right_id"] in member_ids]
        for candidate in group:
            representative_by_member[candidate["candidate_id"]] = representative_id
            if candidate["candidate_id"] != representative_id:
                eliminated[candidate["candidate_id"]] = {**copy.deepcopy(candidate),
                    "semantic_duplicate_scope": "same_run", "semantic_duplicate_of": representative_id,
                    "semantic_duplicate_evidence_pair_ids": copy.deepcopy(same_run_evidence)}
    for relation in relations:
        if relation["decision"] == "DUPLICATE" and relation["scope"] == "recent_history":
            representative_id = representative_by_member.get(relation["left_id"])
            representative = by_id.get(representative_id)
            if representative:
                member_ids = component_members[representative_id]
                evidence_pair_ids = [candidate_relation["pair_id"] for candidate_relation in relations
                    if ((candidate_relation["scope"] == "same_run" and
                         candidate_relation["decision"] == "DUPLICATE" and
                         candidate_relation["left_id"] in member_ids and
                         candidate_relation["right_id"] in member_ids) or
                        (candidate_relation["scope"] == "recent_history" and
                         candidate_relation["decision"] == "DUPLICATE" and
                         candidate_relation["left_id"] in member_ids))]
                eliminated[representative_id] = {**copy.deepcopy(representative),
                    "semantic_duplicate_scope": "recent_history", "semantic_duplicate_of": relation["right_id"],
                    "semantic_duplicate_component_ids": sorted(member_ids),
                    "semantic_duplicate_evidence_pair_ids": evidence_pair_ids}
    snapshot["semantic_duplicate_skips"] = list(eliminated.values())
    snapshot["duplicate_gate_relations"] = copy.deepcopy(relations)
    snapshot["candidates"] = [row for row in snapshot.get("candidates", [])
                              if row["candidate_id"] not in eliminated]
    snapshot["authorized_relations"] = []
    _refresh_capacity_hint(snapshot)
    _finalize_active_input(snapshot)


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
    schema = json.loads(SCHEMA_PATH.read_text())
    digest = hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
    has_relations = bool(snapshot.get("authorized_relations"))
    gate_request = (OperationalAIRequest("Menzo", "editorial_director_duplicate_gate",
                    reason_code="editorial_director_duplicate_gate") if has_relations else None)
    request = (None if has_relations else OperationalAIRequest(
        "Menzo", "editorial_director_active", reason_code="editorial_director_active"))
    try:
        call = provider or shadow._default_provider_factory()
    except Exception as exc:
        (gate_request or request).initialization_failed(str(exc))
        return {**base, "status": "PROVIDER_UNAVAILABLE", "fallback_reason": type(exc).__name__}
    failures: list[dict[str, Any]] = []
    gate_attempts = 0
    gate_logical_request_id = None
    if has_relations:
        gate_logical_request_id = gate_request.logical_request_id
        gate_input_digest = snapshot["input_digest"]
        gate_schema = json.loads(RELATION_SCHEMA_PATH.read_text())
        relations = None
        for index in range(2):
            gate_attempts += 1
            repair = index == 1
            attempt = gate_request.start(MODEL, repair=repair,
                reason_code="duplicate_gate_validation_failed" if repair else "")
            started = time.monotonic(); gate_response = None
            try:
                gate_response = call(_duplicate_prompt(snapshot, failures if index else None), gate_schema,
                                     shadow.PROVIDER_TIMEOUT_SECONDS)
            except Exception as exc:
                record_gemini_attempt(response=gate_response, model_requested=MODEL,
                    operation_id=gate_request.logical_request_id, attempt_index=index, repair=repair,
                    fallback=False, agent="Menzo", workload="editorial_director_duplicate_gate",
                    phase="editorial_director_duplicate_gate_repair" if repair else
                          "editorial_director_duplicate_gate_primary",
                    shadow=False, logical_request_id=gate_request.logical_request_id,
                    canonical_attempt_id=attempt["attempt_id"], candidate_count=len(snapshot["candidates"]),
                    relation_count=len(snapshot["authorized_relations"]), input_digest=snapshot["input_digest"],
                    policy_version=POLICY_VERSION, policy_digest=digest, status="failed",
                    error_class=type(exc).__name__)
                gate_request.failed(attempt, error_class="upstream", error_terminal=True,
                    latency_ms=int((time.monotonic() - started) * 1000))
                return {**base, "attempts": gate_attempts, "status": "PROVIDER_FAILED",
                        "fallback_reason": type(exc).__name__,
                        "duplicate_gate_logical_request_id": gate_logical_request_id,
                        "duplicate_gate_input_digest": gate_input_digest}
            record_gemini_attempt(response=gate_response, model_requested=MODEL,
                operation_id=gate_request.logical_request_id, attempt_index=index, repair=repair,
                fallback=False, agent="Menzo", workload="editorial_director_duplicate_gate",
                phase="editorial_director_duplicate_gate_repair" if repair else
                      "editorial_director_duplicate_gate_primary",
                shadow=False, logical_request_id=gate_request.logical_request_id,
                canonical_attempt_id=attempt["attempt_id"], candidate_count=len(snapshot["candidates"]),
                relation_count=len(snapshot["authorized_relations"]), input_digest=snapshot["input_digest"],
                policy_version=POLICY_VERSION, policy_digest=digest, status="called")
            gate_request.defer(attempt, int((time.monotonic() - started) * 1000))
            try:
                relations, failures, telemetry = _validate_duplicate_gate(shadow._decode(gate_response), snapshot)
            except Exception as exc:
                relations, failures, telemetry = None, [
                    {"family": "parse_json", "detail": type(exc).__name__}], []
            base["validation_attempts"].append({"phase": "duplicate_gate", "attempt_index": index,
                "valid": not failures, "validation_families": failures, "canonicalizations": telemetry})
            gate_request.resolve_deferred(not failures, error_terminal=repair and bool(failures))
            if not failures:
                break
        if failures or relations is None:
            return {**base, "attempts": gate_attempts, "validation_errors": failures,
                    "fallback_reason": failures[0]["family"] if failures else "duplicate_gate_validation_failed",
                    "duplicate_gate_logical_request_id": gate_logical_request_id,
                    "duplicate_gate_input_digest": gate_input_digest}
        _apply_duplicate_gate(snapshot, relations)
        if not snapshot.get("candidates"):
            return {**base, "status": "VALIDATED", "attempts": gate_attempts,
                    "duplicate_gate_logical_request_id": gate_logical_request_id,
                    "duplicate_gate_input_digest": gate_input_digest,
                    "output": {"schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
                               "candidates": [], "relations": relations}, "validation_errors": []}
        request = OperationalAIRequest("Menzo", "editorial_director_active",
            reason_code="editorial_director_active")
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
            return {**base, "attempts": gate_attempts + index + 1, "status": "PROVIDER_FAILED",
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
            output["relations"] = copy.deepcopy(snapshot.get("duplicate_gate_relations", []))
            result = {**base, "status": "VALIDATED", "attempts": gate_attempts + index + 1,
                      "logical_request_id": request.logical_request_id, "policy_digest": digest,
                      "input_digest": snapshot["input_digest"], "output": output, "validation_errors": []}
            if gate_logical_request_id:
                result["duplicate_gate_logical_request_id"] = gate_logical_request_id
                result["duplicate_gate_input_digest"] = gate_input_digest
            return result
    return {**base, "attempts": gate_attempts + 2, "logical_request_id": request.logical_request_id,
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
        sidecar = snapshot.get("_active_bob_capacity_metadata", {})
        if isinstance(sidecar, Mapping):
            item.update(copy.deepcopy(sidecar.get(decision["candidate_id"], {})))
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
    for duplicate in snapshot.get("semantic_duplicate_skips", []):
        item = copy.deepcopy(duplicate); item.pop("candidate_id", None)
        scope = item.pop("semantic_duplicate_scope")
        item.update(decision="skip", priority="skip", article_type="duplicate",
                    decision_authority="semantic_duplicate_gate",
                    reason=f"semantic_{scope}_duplicate")
        projected["skipped"].append(item)
    # Reuse legacy bounded reconsideration only for candidates the Director has
    # just deferred again. A recovered SELECT remains authoritative.
    from agents.menzo_policy_v93_15 import apply_softpool_decay
    decay_view = {"selected": [], "pending": projected["pending"], "skipped": []}
    apply_softpool_decay(decay_view)
    projected["pending"] = decay_view["pending"]
    projected["skipped"].extend(decay_view["skipped"])
    projected["postprocess"] = decay_view.get("postprocess", {})
    projected["relations"] = copy.deepcopy(result["output"]["relations"])
    projected["handoff"] = {"to_bob_or_v92": len(projected["selected"]), "pending": len(projected["pending"]),
                             "skipped": len(projected["skipped"]), "decision_authority": "editorial_director"}
    projected["allowed_urls_for_v92"] = [str(item.get("url") or item.get("source_url"))
        for item in projected["selected"] if item.get("url") or item.get("source_url")]
    from agents.menzo_policy_v93_15 import (ARTIFACT_DECISIONS_FILE, HARD_SKIP_FILE, MENZO_DECISIONS_FILE,
        SOFTPOOL_FILE, V92_ALLOWED_URLS_FILE, save_hard_skips, save_softpool, utc_now, write_json)
    paths = tuple(Path(path) for path in (SOFTPOOL_FILE, HARD_SKIP_FILE, MENZO_DECISIONS_FILE,
                                         ARTIFACT_DECISIONS_FILE, V92_ALLOWED_URLS_FILE))
    before = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        save_softpool(projected)
        save_hard_skips(projected)
        write_json(MENZO_DECISIONS_FILE, projected)
        write_json(ARTIFACT_DECISIONS_FILE, projected)
        write_json(V92_ALLOWED_URLS_FILE, {"generated_at": utc_now(), "version": POLICY_VERSION,
                                          "decision_authority": "editorial_director",
                                          "allowed_urls": projected["allowed_urls_for_v92"]})
    except Exception:
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(path.suffix + ".active-rollback")
                temporary.write_bytes(content)
                temporary.replace(path)
        raise
    return projected
