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
from agents import menzo_active_duplicate_pair_cache as pair_cache
from agents import source_body
from agents import menzo_semantic_admission as admission
from agents import menzo_primary_classification_store as primary_store
from agents import menzo_editorial_recovery as recovery
from agents.canonical_event_ledger import OperationalAIRequest, active_event
from agents.gemini_ledger import record_gemini_attempt

ROOT = Path(__file__).resolve().parents[1]
MODEL = shadow.MODEL
SCHEMA_VERSION = "owtv_editorial_director_output_v6"
POLICY_VERSION = "owtv_editorial_director_policy_v9_active"
SCHEMA_PATH = ROOT / "config/editorial_director_output_schema_v6.json"
POLICY_PATH = ROOT / "docs/editorial-rules/OWTV_GEMINI_EDITORIAL_DIRECTOR_POLICY_V9_ACTIVE.md"
ADMISSION_SCHEMA_PATH = ROOT / "config/editorial_duplicate_admission_schema_v1.json"
ADMISSION_POLICY_PATH = ROOT / "docs/editorial-rules/OWTV_DUPLICATE_ADMISSION_POLICY_V1.md"
RELATION_SCHEMA_PATH = ROOT / "config/editorial_director_duplicate_gate_schema_v4.json"
RELATION_POLICY_PATH = ROOT / "docs/editorial-rules/OWTV_DUPLICATE_JUDGMENT_POLICY_V1.md"
EVENT_REGISTRY_PATH = ROOT / "config/event_registry.json"
BOB_CAPACITY_FIELDS = ("article_type", "source_title", "category_hint", "reason",
                       "ai_editorial_reason", "event_key", "show_report_id", "show_name",
                       "special_event_match", "event_report_key", "corresponding_report_published",
                       "_soft_board_existing", "_soft_board_existing_day",
                       "_soft_board_existing_review_count", "_soft_board_existing_fingerprint",
                       "first_seen_at", "priority_queue_first_seen_at", "_priority_queue_editorial")
DUPLICATE_EVIDENCE_FIELDS = ("left_evidence", "right_evidence")
DUPLICATE_CENTRALITY_FIELDS = ("left_central_development", "right_central_development",
                               "centrality_basis")
DUPLICATE_RELATION_FIELDS = {"ref", "decision", "shared_fact", "new_fact", "temporal_basis",
                             *DUPLICATE_EVIDENCE_FIELDS, *DUPLICATE_CENTRALITY_FIELDS}
GROUNDING_SOURCE_FIELDS = ("title", "source_title", "title_it", "summary", "retained_body")
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

    from agents.menzo_policy_v93_15 import terminal_skip_memory, source_key, is_bookmaker_odds_news
    closed = terminal_skip_memory()
    def key(row):
        return source_key(str(row.get("url") or row.get("source_url") or ""))
    original = list(snapshot.get("candidates", []))
    memory_skips = [{**copy.deepcopy(row), "terminal_skip_reason": "terminal_skip_memory"}
                    for row in original if key(row) in closed]
    odds_skips = [{**copy.deepcopy(row), "terminal_skip_reason": "skip:betting_odds_low_editorial_value"}
                  for row in original if key(row) not in closed and is_bookmaker_odds_news(row)]
    snapshot["terminal_policy_skips"] = list({row['candidate_id']: row for row in
        snapshot.get('terminal_policy_skips', []) + memory_skips + odds_skips}.values())
    if odds_skips:
        from agents.menzo_policy_v93_15 import save_hard_skips
        save_hard_skips({"skipped": [{**row, "decision_authority": "editorial_director",
            "reason": row["terminal_skip_reason"], "editorial_director": {"editorial_class": "SKIP"}}
            for row in odds_skips]})
    candidates = [row for row in original if key(row) not in closed and not is_bookmaker_odds_news(row)]
    history = [row for row in snapshot.get("publisher_history_12h", [])
               if row.get("history_state") != "soft_tombstone" and key(row) not in closed
               and row.get("status", "published") in {"published", "publish", "success", "succeeded"}
               and row.get("dry_run") is not True]
    snapshot["publisher_history_12h"] = history
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
            local_winner, _ = canonical_richer_winner(local_group, earliest_arrival=True)
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
        ((relation.get("scope") == "same_run" and relation.get("right_id") in winner_ids) or
         (relation.get("scope") == "recent_history" and relation.get("right_id") in
          {row['article_id'] for row in history}))]
    # Active admission never rebuilds semantic pairs from lexical scores.
    snapshot["deterministic_exact_skips"] = list({row['candidate_id']: row for row in
        snapshot.get('deterministic_exact_skips', []) + deterministic_skips}.values())
    if deterministic_skips:
        from agents.menzo_policy_v93_15 import save_hard_skips
        save_hard_skips({'skipped': [{**row, 'decision_authority': 'deterministic_exact_duplicate',
                                    'reason': 'exact_duplicate'} for row in deterministic_skips]})
    # This pre-provider value remains only the existing compact-pool hint. The
    # authoritative capacity is recomputed from sidecar-restored SELECT rows.
    _refresh_capacity_hint(snapshot)
    _finalize_active_input(snapshot)
    return snapshot


def active_provider_input(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """No pacing context; canonical bodies are exposed only for authorized endpoints."""
    provider_data = shadow.provider_input(snapshot)
    provider_data.pop("publication_context", None)
    involved = {relation[key] for relation in snapshot.get("authorized_relations", [])
                for key in ("left_id", "right_id")}
    bodies = snapshot.get("_duplicate_revalidation_bodies", {})
    for table, source_table, identity in (
            ("candidates", "candidates", "candidate_id"),
            ("history", "publisher_history_12h", "article_id")):
        for row, endpoint in zip(provider_data[table], snapshot.get(source_table, [])):
            endpoint_id = endpoint[identity]
            retained = bodies.get(endpoint_id, {})
            if endpoint_id in involved and retained.get("text"):
                row["retained_body"] = retained["text"][:shadow.REVALIDATION_MAX_BODY_CHARS]
                row["input_coverage"] = retained.get("coverage", "RETAINED_BODY")
    if snapshot.get("_semantic_admission") is not None:
        provider_data["duplicate_admission"] = copy.deepcopy(snapshot["_semantic_admission"])
    for row, relation in zip(provider_data["authorized_relations"], snapshot.get("authorized_relations", [])):
        if relation.get("admission_basis"):
            row["admission_basis"] = relation["admission_basis"]
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
        allowed = {"MUST_PUBLISH": {"SELECT"}, "SHOULD_PUBLISH": {"SELECT"},
                   "PUBLISHABLE_SOFT": {"DEFER"}, "SKIP": {"SKIP"}}
        if canonical.get("editorial_class") in allowed and action not in allowed[canonical["editorial_class"]]:
            failures.append({"family": "class_action_incompatibility", "ref": ref,
                             "editorial_class": canonical.get("editorial_class"), "recommended_action": action})
    if any(row.get("detail") == "skip_invariant_overridden" for row in telemetry):
        failures.append({"family": "skip_action_invariant", "detail": "active_semantic_rewrite_forbidden"})
    if failures:
        return None, failures, telemetry
    output["schema_version"] = SCHEMA_VERSION
    output["policy_version"] = POLICY_VERSION
    return output, [], telemetry


def _prompt(snapshot: Mapping[str, Any]) -> str:
    policy = POLICY_PATH.read_text(encoding="utf-8")
    provider_data = active_provider_input(snapshot)
    prompt = (f"ACTIVE_POLICY_VERSION={POLICY_VERSION}\nACTIVE_POLICY_SHA256={hashlib.sha256(policy.encode()).hexdigest()}\n"
              f"<ACTIVE_POLICY>\n{policy}\n</ACTIVE_POLICY>\nReturn only JSON with candidates. Classify each supplied unclassified candidate once. "
              "Candidate order expresses preference within class. INPUT=" +
              json.dumps(provider_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
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
    provider_data = _duplicate_provider_input(snapshot)
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


def _duplicate_provider_input(snapshot):
    data = active_provider_input(snapshot)
    fields = {'ref', 'title', 'source_title', 'title_it', 'summary', 'source', 'url',
              'published_at', 'published', 'retained_body', 'input_coverage'}
    endpoints = {row[key] for row in data['authorized_relations'] for key in ('left_ref', 'right_ref')}
    return {'candidates': [{k: v for k, v in row.items() if k in fields}
                           for row in data['candidates'] if row['ref'] in endpoints],
            'history': [{k: v for k, v in row.items() if k in fields}
                        for row in data['history'] if row['ref'] in endpoints],
            'authorized_relations': [{k: v for k, v in row.items() if k in
                {'ref', 'scope', 'left_ref', 'right_ref'}} for row in data['authorized_relations']]}


def _validate_duplicate_gate(value, snapshot, *, preserve_valid=False):
    failures = []; telemetry = []
    if not isinstance(value, Mapping) or not isinstance(value.get('relations'), list):
        return None, [{'family': 'parse_json', 'detail': 'relations_array_required'}], telemetry
    _, mapping = shadow.short_ref_maps(snapshot)
    rows = value['relations']; counts = {}
    for row in rows:
        if isinstance(row, Mapping) and isinstance(row.get('ref'), str):
            counts[row['ref']] = counts.get(row['ref'], 0) + 1
    canonical = []; seen = set()
    for row in rows:
        if not isinstance(row, Mapping):
            failures.append({'family': 'relation_ref', 'detail': 'object_required'}); continue
        ref = row.get('ref')
        if not isinstance(ref, str) or ref not in mapping:
            failures.append({'family': 'relation_ref', 'detail': 'unknown_reference'}); continue
        if counts[ref] != 1:
            failures.append({'family': 'relation_ref', 'ref': ref, 'detail': 'duplicate'}); continue
        decision = shadow._enum(row.get('decision'), shadow.DECISIONS, 'relation_decision', telemetry, ref)
        if decision is None:
            failures.append({'family': 'relation_decision', 'ref': ref}); continue
        supplied = mapping[ref]
        if decision == 'MATERIAL_UPDATE' and supplied['scope'] != 'recent_history':
            failures.append({'family': 'material_update_scope', 'ref': ref}); continue
        seen.add(ref)
        entry = {key: supplied[key] for key in ('pair_id', 'scope', 'left_id', 'right_id')}
        entry.update(decision=decision, semantic_authority='gemini_final',
            scorer={key: copy.deepcopy(supplied.get(key)) for key in
                    ('scorer_version', 'score', 'threshold', 'components')})
        for field in ('shared_fact', 'new_fact', 'temporal_basis', *DUPLICATE_EVIDENCE_FIELDS, *DUPLICATE_CENTRALITY_FIELDS):
            value = row.get(field)
            entry[field] = value.strip()[:500] if isinstance(value, str) and value.strip() else None
        canonical.append(entry)
    missing = sorted(set(mapping) - seen)
    if missing:
        failures.append({'family': 'relation_coverage', 'missing_refs': missing})
    return (canonical if preserve_valid or not failures else None), failures, telemetry


def _duplicate_prompt(snapshot):
    data = _duplicate_provider_input(snapshot)
    return (RELATION_POLICY_PATH.read_text() +
            '\nDUPLICATE GATE PHASE ONLY. Return only JSON with relations. INPUT=' +
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def _store_ordinary_pairs(cache: dict[str, Any], materials: Mapping[str, Any],
                          relations: list[dict[str, Any]], base: dict[str, Any], stored_pairs: set[str]) -> None:
    """Persist final Gemini decisions only against their exact provider material."""
    rows = [(materials[row["pair_id"]], row) for row in relations
            if row["pair_id"] in materials and row["pair_id"] not in stored_pairs and not row.get("body_revalidation")
            and not row.get("validated_equivalence")
            and row.get("semantic_authority") == "gemini_final"]
    if not rows:
        return
    # A failed cache write is diagnostic, not permission to retry the write in
    # the same operation or repeat the semantic judgment.
    stored_pairs.update(row['pair_id'] for _, row in rows)
    try:
        stored = pair_cache.store(cache, rows)
        base["duplicate_pair_cache_entries_stored"] += stored
        stored_pairs.update(row["pair_id"] for _, row in rows)
        for material, _ in rows:
            active_event("duplicate_pair_cache_stored", "Menzo", "duplicate", "success",
                         "state/newsroom/menzo_active_duplicate_pair_cache_v1.json",
                         pair_id=material["identity"]["pair_id"],
                         reason_code="validated_pair_result_stored")
    except Exception as exc:
        active_event("stage_failed", "Menzo", "duplicate", "failed",
                     "state/newsroom/menzo_active_duplicate_pair_cache_v1.json",
                     reason_code="duplicate_pair_cache_store_failed", result=type(exc).__name__,
                     error_class="invariant", error_terminal=False)


def _body_pair_snapshot(snapshot: Mapping[str, Any], relation: Mapping[str, Any]):
    """Build a private, bounded two-endpoint projection without changing ordinary inputs."""
    current = {row["candidate_id"]: row for row in snapshot.get("candidates", [])}
    history = {row["article_id"]: row for row in snapshot.get("publisher_history_12h", [])}
    right_table = current if relation["scope"] == "same_run" else history
    if relation["left_id"] not in current or relation["right_id"] not in right_table:
        return None, "missing_pair_endpoints"
    left = copy.deepcopy(current[relation["left_id"]])
    right = copy.deepcopy(right_table[relation["right_id"]])
    bodies = snapshot.get("_duplicate_revalidation_bodies", {})
    provider_rows = active_provider_input(snapshot)
    seen_bodies = {endpoint[identity]: row.get("retained_body")
        for table, source_table, identity in (("candidates", "candidates", "candidate_id"),
            ("history", "publisher_history_12h", "article_id"))
        for row, endpoint in zip(provider_rows[table], snapshot.get(source_table, []))}
    changed = False
    coverage = {}
    for endpoint_id, endpoint, is_current in (
            (relation["left_id"], left, True),
            (relation["right_id"], right, relation["scope"] == "same_run")):
        retained = bodies.get(endpoint_id, {})
        text, label = retained.get("text", ""), retained.get("coverage", "METADATA_ONLY")
        if not text and is_current:
            complete, _ = source_body.hydrate(endpoint)
            if complete:
                full = source_body.contract_text(endpoint)
                text = full[:shadow.REVALIDATION_MAX_BODY_CHARS]
                label = "FULL_BODY" if text == full else "TRUNCATED_CANONICAL_BODY"
        if not text:
            text = str(endpoint.get("retained_body") or "")[:shadow.REVALIDATION_MAX_BODY_CHARS]
            label = "RETAINED_BODY" if text else "METADATA_ONLY"
        if not text:
            return None, "body_unavailable"
        changed |= text != seen_bodies.get(endpoint_id)
        endpoint["retained_body"] = text
        endpoint.pop("canonical_source_body", None)
        coverage[endpoint_id] = {"coverage": label, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    if not changed:
        return None, "no_new_body_evidence"
    local = {**copy.deepcopy(dict(snapshot)), "candidates": [left], "publisher_history_12h": [],
             "authorized_relations": [copy.deepcopy(dict(relation))]}
    if relation["scope"] == "same_run":
        local["candidates"].append(right)
    else:
        local["publisher_history_12h"].append(right)
    _finalize_active_input(local)
    if local["limit_status"] == "exceeded":
        return None, "body_projection_exceeded"
    return local, coverage


def _apply_duplicate_gate(snapshot: dict[str, Any], relations: list[dict[str, Any]]) -> None:
    """Remove semantic duplicates before any classified survivor can be published."""
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
            winner, _ = canonical_richer_winner(hydrated, earliest_arrival=True)
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
    if eliminated:
        from agents.menzo_policy_v93_15 import save_hard_skips
        save_hard_skips({'skipped': [{**row, 'decision_authority': 'semantic_duplicate_gate',
            'reason': 'semantic_duplicate'} for row in eliminated.values()]})
    snapshot["semantic_duplicate_skips"] = list(eliminated.values())
    snapshot["duplicate_gate_relations"] = copy.deepcopy(relations)
    snapshot["candidates"] = [row for row in snapshot.get("candidates", [])
                              if row["candidate_id"] not in eliminated]
    snapshot["authorized_relations"] = []
    _refresh_capacity_hint(snapshot)
    _finalize_active_input(snapshot)


def _evaluate_duplicate_gate_batch(batch_snapshot, *, call, digest, cache, materials,
        cached_relations, base, stored_pairs, batch_index):
    def validate(raw):
        return _validate_duplicate_gate(raw, batch_snapshot, preserve_valid=True)
    result = _run_once(batch_snapshot, call, _duplicate_prompt(batch_snapshot),
        json.loads(RELATION_SCHEMA_PATH.read_text()), 'editorial_director_duplicate_gate',
        RELATION_POLICY_PATH, validate)
    base['validation_attempts'].extend(result.get('validation_attempts', []))
    relations = result.get('output') or []
    provenance = {'duplicate_gate_logical_request_id': result.get('logical_request_id'),
                  'duplicate_gate_input_digest': result.get('input_digest')}
    for row in relations:
        row['validated_provenance'] = copy.deepcopy(provenance)
    # Individually valid Gemini decisions are final even if another row is invalid.
    _store_ordinary_pairs(cache, materials, relations, base, stored_pairs)
    return {'ok': result['status'] == 'VALIDATED', 'attempts': result.get('attempts', 0),
            'relations': relations, 'valid_relations': relations,
            'logical_request_id': result.get('logical_request_id'),
            'input_digest': result.get('input_digest'), 'result': result}


def _evaluate_duplicate_stage(snapshot: Mapping[str, Any], *, provider: Callable[..., Any] | None = None,
                              artifact_index: Any = None) -> dict[str, Any]:
    base = {"status": "failed", "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
            "observed": copy.deepcopy(snapshot.get("observed")), "limit_status": snapshot.get("limit_status"),
            "attempts": 0, "validation_attempts": []}
    stored_pairs: set[str] = set()
    if snapshot.get("limit_status") == "projection_failed":
        return {**base, "status": "PROJECTION_FAILED", "fallback_reason": "PROJECTION_FAILED"}
    if snapshot.get("limit_status") == "exceeded":
        # PR131 can reduce only the duplicate-relation payload. Candidate count and
        # the relation-free provider projection remain hard pre-cache bounds.
        pre_cache_probe = copy.deepcopy(snapshot)
        pre_cache_probe["authorized_relations"] = []
        _finalize_active_input(pre_cache_probe)
        if pre_cache_probe.get("limit_status") == "exceeded":
            return {**base, "status": "OVERSIZE_NOT_EVALUATED",
                    "fallback_reason": "OVERSIZE_NOT_EVALUATED"}
        base["capture_observed"] = copy.deepcopy(snapshot.get("observed"))
        base["capture_limit_status"] = snapshot.get("limit_status")
        base["relation_limit_deferred_to_pr131"] = True
    if not snapshot.get("candidates"):
        return {**base, "status": "VALIDATED", "attempts": 0,
                "output": {"schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
                           "candidates": [], "relations": []}, "validation_errors": []}
    schema = json.loads(SCHEMA_PATH.read_text())
    digest = hashlib.sha256(RELATION_POLICY_PATH.read_bytes()).hexdigest()
    call = provider
    authorized = list(snapshot.get("authorized_relations", []))
    contract = pair_cache.contract_fingerprint(
        policy_version=POLICY_VERSION, model=MODEL, policy_path=RELATION_POLICY_PATH,
        gate_schema_path=RELATION_SCHEMA_PATH,
        event_registry_path=EVENT_REGISTRY_PATH)
    cache = pair_cache.load()
    active_event(
        "duplicate_pair_cache_cycle", "Menzo", "duplicate", "success",
        "state/newsroom/menzo_active_duplicate_pair_cache_v1.json",
        result=str(cache.get("load_status") or "unknown"),
        reason_code="pr131_duplicate_pair_cache_cycle",
    )
    _, endpoint_relations = _duplicate_gate_endpoint_maps(snapshot)
    _, relation_refs = shadow.short_ref_maps(snapshot)
    endpoint_by_pair = {relation_refs[ref]["pair_id"]: endpoints
                        for ref, endpoints in endpoint_relations.items() if ref in relation_refs}
    materials: dict[str, dict[str, Any]] = {}
    cached_relations: dict[str, dict[str, Any]] = {}
    misses = []
    for relation in authorized:
        pair_id = str(relation.get("pair_id") or "")
        endpoints = endpoint_by_pair.get(relation.get("pair_id"))
        if endpoints is None:
            misses.append(relation)
            active_event(
                "duplicate_pair_cache_miss", "Menzo", "duplicate", "success",
                "state/newsroom/menzo_active_duplicate_pair_cache_v1.json",
                pair_id=pair_id, reason_code="missing_pair_endpoints",
            )
            continue
        material = pair_cache.pair_material(relation, endpoints, contract)
        materials[pair_id] = material
        hit = pair_cache.lookup(cache, material)
        if hit is None:
            misses.append(relation)
            active_event(
                "duplicate_pair_cache_miss", "Menzo", "duplicate", "success",
                "state/newsroom/menzo_active_duplicate_pair_cache_v1.json",
                pair_id=pair_id, reason_code="cache_lookup_miss",
            )
        else:
            cached_relations[pair_id] = hit
            active_event(
                "duplicate_pair_cache_hit", "Menzo", "duplicate", "success",
                "state/newsroom/menzo_active_duplicate_pair_cache_v1.json",
                pair_id=pair_id, reason_code="cache_lookup_hit",
            )
    base.update(duplicate_pair_cache_hits=len(cached_relations),
                duplicate_pair_cache_misses=len(misses),
                duplicate_pair_cache_entries_stored=0,
                duplicate_pair_cache_load_status=cache.get("load_status", "unknown"),
                duplicate_pair_cache_contract_version=pair_cache.CONTRACT_VERSION)
    has_relations = bool(misses)
    phase_snapshot = snapshot
    if isinstance(snapshot, dict):
        phase_snapshot = copy.deepcopy(snapshot)
        phase_snapshot["authorized_relations"] = copy.deepcopy(misses)
        _finalize_active_input(phase_snapshot)
        base["provider_bound_observed"] = copy.deepcopy(phase_snapshot.get("observed"))
        base["provider_bound_limit_status"] = phase_snapshot.get("limit_status")
        base["provider_bound_relation_count"] = len(misses)
        if phase_snapshot.get("limit_status") != "exceeded":
            base["observed"] = copy.deepcopy(phase_snapshot.get("observed"))
            base["limit_status"] = phase_snapshot.get("limit_status")
    if authorized and not has_relations:
        gate_avoided = OperationalAIRequest(
            "Menzo", "editorial_director_duplicate_gate",
            reason_code="pr131_duplicate_pair_cache_all_hit",
        )
        gate_avoided.avoided("pr131_duplicate_pair_cache_all_hit")
        record_gemini_attempt(
            response=None, model_requested=MODEL, operation_id=gate_avoided.logical_request_id,
            attempt_index=0, repair=False, fallback=False, agent="Menzo",
            workload="editorial_director_duplicate_gate",
            phase="editorial_director_duplicate_gate_cache_avoided",
            shadow=False, logical_request_id=gate_avoided.logical_request_id,
            candidate_count=len(snapshot.get("candidates", [])),
            relation_count=len(authorized), input_digest=snapshot.get("input_digest"),
            policy_version=POLICY_VERSION, policy_digest=digest, status="avoided",
            reason="pr131_duplicate_pair_cache_all_hit",
        )
    request = None
    if authorized and not has_relations and not snapshot.get("_defer_duplicate_application"):
        _apply_duplicate_gate(snapshot, [cached_relations[str(row["pair_id"])] for row in authorized])
        if not snapshot.get("candidates"):
            return {**base, "status": "VALIDATED", "attempts": 0,
                    "output": {"schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
                               "candidates": [], "relations": copy.deepcopy(
                                   snapshot.get("duplicate_gate_relations", []))},
                    "validation_errors": []}
    failures: list[dict[str, Any]] = []
    gate_attempts = 0
    gate_logical_request_id = None
    gate_input_digest = None
    gate_logical_request_ids: list[str] = []
    gate_input_digests: list[str] = []
    relations: list[dict[str, Any]] = []
    final_relations = [copy.deepcopy(cached_relations[str(row["pair_id"])]) for row in authorized] if not has_relations else []
    if has_relations:
        batch_size = max(1, shadow.MAX_RELATIONS)
        batch_snapshots = []
        batch_diagnostics = []
        for batch_index, offset in enumerate(range(0, len(misses), batch_size)):
            batch_snapshot = copy.deepcopy(snapshot)
            batch_snapshot["authorized_relations"] = copy.deepcopy(misses[offset:offset + batch_size])
            _finalize_active_input(batch_snapshot)
            diagnostic = {
                "batch_index": batch_index,
                "relation_count": len(batch_snapshot["authorized_relations"]),
                "observed": copy.deepcopy(batch_snapshot.get("observed")),
                "limit_status": batch_snapshot.get("limit_status"),
            }
            batch_diagnostics.append(diagnostic)
            if batch_snapshot.get("limit_status") == "exceeded":
                base.update(
                    duplicate_gate_batched=len(misses) > batch_size,
                    duplicate_gate_batch_count=len(batch_diagnostics),
                    duplicate_gate_batches=batch_diagnostics,
                    observed=copy.deepcopy(batch_snapshot.get("observed")),
                    limit_status=batch_snapshot.get("limit_status"),
                )
                return {**base, "status": "OVERSIZE_NOT_EVALUATED",
                        "fallback_reason": "OVERSIZE_NOT_EVALUATED"}
            batch_snapshots.append(batch_snapshot)
        base["duplicate_gate_batched"] = len(batch_snapshots) > 1
        base["duplicate_gate_batch_count"] = len(batch_snapshots)
        base["duplicate_gate_batches"] = batch_diagnostics
        if batch_snapshots:
            largest_batch = max(
                batch_snapshots,
                key=lambda value: int((value.get("observed") or {}).get("serialized_input_bytes", 0)))
            base["observed"] = copy.deepcopy(largest_batch.get("observed"))
            base["limit_status"] = largest_batch.get("limit_status")
        for batch_index, batch_snapshot in enumerate(batch_snapshots):
            outcome = _evaluate_duplicate_gate_batch(
                batch_snapshot, call=call, digest=digest, cache=cache, materials=materials,
                cached_relations=cached_relations, base=base, stored_pairs=stored_pairs,
                batch_index=batch_index)
            gate_attempts += int(outcome.get("attempts", 0))
            gate_logical_request_ids.append(str(outcome.get("logical_request_id") or ""))
            gate_input_digests.append(str(outcome.get("input_digest") or ""))
            gate_logical_request_id = gate_logical_request_id or outcome.get("logical_request_id")
            gate_input_digest = gate_input_digest or outcome.get("input_digest")
            if not outcome.get("ok"):
                finals = list(cached_relations.values()) + relations + outcome.get('valid_relations', [])
                if any(row['decision'] == 'DUPLICATE' for row in finals):
                    _apply_duplicate_gate(snapshot, finals)
                failure_result = dict(outcome.get("result") or {})
                return {**base, **failure_result, "attempts": gate_attempts,
                        "validation_attempts": base["validation_attempts"],
                        "duplicate_gate_logical_request_id": gate_logical_request_id,
                        "duplicate_gate_input_digest": gate_input_digest,
                        "duplicate_gate_logical_request_ids": gate_logical_request_ids,
                        "duplicate_gate_input_digests": gate_input_digests}
            relations.extend(copy.deepcopy(outcome.get("relations") or []))
        base["duplicate_gate_logical_request_ids"] = copy.deepcopy(gate_logical_request_ids)
        base["duplicate_gate_input_digests"] = copy.deepcopy(gate_input_digests)
        new_by_pair = {str(row["pair_id"]): row for row in relations}
        final_relations = [copy.deepcopy(cached_relations.get(str(row["pair_id"])) or
                                        new_by_pair[str(row["pair_id"])]) for row in authorized]
        if not snapshot.get("_defer_duplicate_application"):
            _apply_duplicate_gate(snapshot, final_relations)
        _store_ordinary_pairs(cache, materials, relations, base, stored_pairs)
        if not snapshot.get("candidates"):
            return {**base, "status": "VALIDATED",
                    "attempts": gate_attempts,
                    "duplicate_gate_logical_request_id": gate_logical_request_id,
                    "duplicate_gate_input_digest": gate_input_digest,
                    "output": {"schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
                               "candidates": [], "relations": final_relations}, "validation_errors": []}
    return {**base, "status": "VALIDATED", "attempts": gate_attempts,
            "duplicate_gate_logical_request_id": gate_logical_request_id,
            "duplicate_gate_input_digest": gate_input_digest,
            "output": {"candidates": [], "relations": final_relations},
            "validation_errors": []}


def _preserve_cached_duplicate_admissions(snapshot: Mapping[str, Any], relations: list[dict[str, Any]]) -> None:
    """A later admission response cannot bypass a final, same-contract cached DUPLICATE.

    The full gate still checks exact endpoint material before applying/reusing it.
    """
    contract = pair_cache.contract_fingerprint(policy_version=POLICY_VERSION, model=MODEL,
        policy_path=RELATION_POLICY_PATH, gate_schema_path=RELATION_SCHEMA_PATH, event_registry_path=EVENT_REGISTRY_PATH)
    current = {row['candidate_id'] for row in snapshot.get('candidates', [])}
    history = {row['article_id'] for row in snapshot.get('publisher_history_12h', [])}
    included = {row['pair_id'] for row in relations}
    for entry in pair_cache.load().get('entries', {}).values():
        if not isinstance(entry, Mapping):
            continue
        identity = entry.get('identity', {})
        final = entry.get('final_relation', {})
        if not isinstance(identity, Mapping) or not isinstance(final, Mapping):
            continue
        scope, left, right = (identity.get(k) for k in ('scope', 'left_id', 'right_id'))
        if (scope not in {'same_run', 'recent_history'} or not isinstance(identity.get('pair_id'), str) or
                not isinstance(left, str) or not isinstance(right, str) or left == right or
                any(final.get(key) != identity.get(key) for key in ('pair_id', 'scope', 'left_id', 'right_id')) or
                entry.get('contract_fingerprint') != contract or final.get('decision') != 'DUPLICATE' or
                final.get('semantic_authority') != 'gemini_final' or identity.get('pair_id') in included or
                left not in current or right not in (current if scope == 'same_run' else history)):
            continue
        row = admission.make_relation(scope, left, right, 'Preserve a final cached Gemini decision for exact material validation.')
        row['pair_id'] = identity['pair_id']
        relations.append(row); included.add(row['pair_id'])


def _technical_failures(failures):
    """Persist technical structure only, never model rationale or article bodies."""
    return [{key: (value[:80] if isinstance(value, str) else value)
             for key, value in row.items() if key in
             {'family', 'detail', 'ref', 'missing_refs', 'fields'}} for row in failures]


def _run_once(snapshot, call, prompt, schema, phase, policy_path, validate, *, cache_success=False,
              policy_version=None, recovery_material=None):
    """One provider attempt; unchanged failures recover on an explicit backoff."""
    binding = {key: snapshot.get(key) for key in ('_admission_candidate_ids', '_admission_history_ids')}
    fingerprint = hashlib.sha256(json.dumps({'prompt': prompt if recovery_material is None else recovery_material, 'schema': schema,
        'policy': hashlib.sha256(policy_path.read_bytes()).hexdigest(), 'phase': phase,
        'model': MODEL, 'binding': binding}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    try:
        cached = recovery.lookup(fingerprint, success=cache_success)
    except Exception as exc:
        return {"status": "TECHNICAL_HOLD", "attempts": 0, "output": None,
                "validation_errors": [{"family": "recovery_cache", "detail": type(exc).__name__}],
                "validation_attempts": [], "fallback_reason": "recovery_cache_unavailable"}
    if cached:
        return {'status': cached['status'], 'attempts': 0, 'output': cached.get('output'),
                'validation_errors': cached.get('validation_errors', []), 'validation_attempts': [],
                'input_digest': fingerprint, 'retry_after': cached.get('retry_after'),
                'recovery_cache_hit': True, 'fallback_reason': 'technical_recovery_backoff'}
    if call is None:
        try:
            call = shadow._default_provider_factory()
        except Exception as exc:
            failures = [{'family': 'provider_initialization', 'detail': type(exc).__name__}]
            try:
                recovery.record(fingerprint, None, failures)
            except Exception:
                pass
            return {'status': 'PROVIDER_UNAVAILABLE', 'attempts': 0, 'output': None,
                    'validation_errors': failures, 'validation_attempts': [],
                    'fallback_reason': 'provider_initialization'}
    request = OperationalAIRequest('Menzo', phase, reason_code=phase)
    attempt = request.start(MODEL)
    started = time.monotonic(); response = None; raw = None
    output = None; telemetry = []; failure_kind = 'validation'
    try:
        response = call(prompt, schema, shadow.PROVIDER_TIMEOUT_SECONDS)
    except Exception as exc:
        failures = [{'family': 'provider_failure', 'detail': type(exc).__name__}]
        failure_kind = 'upstream'
    else:
        try:
            raw = shadow._decode(response)
            output, failures, telemetry = validate(raw)
        except Exception as exc:
            failures = [{'family': 'parse_json', 'detail': type(exc).__name__}]
    failures = _technical_failures(failures)
    shape = {'object': isinstance(raw, Mapping),
             'keys': sorted(str(k)[:80] for k in raw)[:20] if isinstance(raw, Mapping) else [],
             'array_lengths': {str(k)[:80]: len(v) for k, v in raw.items() if isinstance(v, list)}
                              if isinstance(raw, Mapping) else {}}
    elapsed = int((time.monotonic() - started) * 1000)
    record_gemini_attempt(response=response, model_requested=MODEL,
        operation_id=request.logical_request_id, logical_request_id=request.logical_request_id,
        canonical_attempt_id=attempt['attempt_id'], attempt_index=0, repair=False, fallback=False,
        agent='Menzo', workload=phase, phase=phase + '_primary', shadow=False,
        candidate_count=len(snapshot.get('candidates', [])),
        relation_count=len(snapshot.get('authorized_relations', [])), input_digest=fingerprint,
        policy_version=policy_version or POLICY_VERSION,
        policy_digest=hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        status='failed' if failure_kind == 'upstream' else 'called',
        validation_families=[x['family'] for x in failures], validation_errors=failures,
        response_shape=shape, error_class=failure_kind if failures else None)
    if failure_kind == 'upstream':
        request.failed(attempt, error_class='upstream', error_terminal=True, latency_ms=elapsed,
                       reason_code=failures[0]['family'])
    else:
        request.defer(attempt, elapsed)
        request.resolve_deferred(not failures, error_terminal=bool(failures),
                                 validation_reason=failures[0]['family'] if failures else '')
    recovery_error = None
    try:
        recovery.record(fingerprint, output, failures, success=cache_success)
    except Exception as exc:
        recovery_error = type(exc).__name__
    result = {'status': ('PROVIDER_FAILED' if failure_kind == 'upstream' else 'failed') if failures else 'VALIDATED',
              'attempts': 1, 'logical_request_id': request.logical_request_id, 'input_digest': fingerprint,
              'output': output, 'validation_errors': failures,
              'policy_digest': hashlib.sha256(policy_path.read_bytes()).hexdigest(),
              'validation_attempts': [{'phase': phase, 'attempt_index': 0, 'valid': not failures,
                    'validation_families': failures, 'canonicalizations': telemetry, 'response_shape': shape}]}
    if failures:
        result['fallback_reason'] = failures[0]['family']
        if recovery_error is None:
            result['retry_after'] = (recovery.lookup(fingerprint) or {}).get('retry_after')
    if recovery_error:
        result['recovery_cache_error'] = recovery_error
    return result


def _classify(snapshot: dict[str, Any], call: Callable[..., Any]) -> dict[str, Any]:
    """Classify unclassified URLs only; preserve every independently valid row."""
    if not snapshot.get('candidates'):
        return {'status': 'VALIDATED', 'attempts': 0, 'output': {'candidates': [], 'relations': []},
                'validation_attempts': [], 'validation_errors': []}
    def validate(raw):
        value = {**raw, 'relations': []} if isinstance(raw, Mapping) else raw
        output, failures, telemetry = _validate_active(value, snapshot)
        accepted = []
        if isinstance(raw, Mapping) and isinstance(raw.get('candidates'), list):
            refs, _ = shadow.short_ref_maps(snapshot)
            counts = {}
            for row in raw['candidates']:
                if isinstance(row, Mapping) and isinstance(row.get('ref'), str):
                    counts[row['ref']] = counts.get(row['ref'], 0) + 1
            for row in raw['candidates']:
                if not isinstance(row, Mapping):
                    continue
                ref = row.get('ref')
                if not isinstance(ref, str) or ref not in refs or counts[ref] != 1:
                    continue
                part = {**snapshot, 'candidates': [refs[ref]], 'authorized_relations': []}
                decision, errors, _ = _validate_active({'candidates': [{**row, 'ref': 'c0'}], 'relations': []}, part)
                if not errors:
                    accepted.extend(decision['candidates'])
        if not failures:
            accepted = copy.deepcopy(output['candidates'])
        try:
            primary_store.remember(snapshot['candidates'], accepted,
                when=snapshot.get('observation_timestamp'), policy=POLICY_VERSION)
        except Exception as exc:
            return None, failures + [{'family': 'primary_persistence', 'detail': type(exc).__name__}], telemetry
        snapshot['editorial_prefilter_decisions'] = copy.deepcopy(accepted)
        snapshot['editorial_prefilter_skips'] = [row for row in snapshot['candidates'] if
            any(d['candidate_id'] == row['candidate_id'] and d['editorial_class'] == 'SKIP' for d in accepted)]
        from agents.menzo_policy_v93_15 import save_hard_skips
        by_id = {row['candidate_id']: row for row in accepted}
        if snapshot['editorial_prefilter_skips']:
            save_hard_skips({'skipped': [{**row, 'reason': 'editorial_class_skip',
                'decision_authority': 'editorial_director', 'editorial_director': by_id[row['candidate_id']]}
                for row in snapshot['editorial_prefilter_skips']]})
        return output, failures, telemetry
    return _run_once(snapshot, call, _prompt(snapshot), json.loads(SCHEMA_PATH.read_text()),
                     'editorial_director_active', POLICY_PATH, validate)


def _admit(snapshot, call):
    """Factual pair election only. No classification fields or primary validator."""
    ids = snapshot.get('_admission_candidate_ids', [])
    if not ids or (len(ids) < 2 and not snapshot.get('_admission_history_ids')):
        return {'status': 'VALIDATED', 'attempts': 0, 'output': [], 'admitted_relations': [],
                'validation_attempts': [], 'validation_errors': []}
    payload = snapshot['_semantic_admission']
    prompt = ADMISSION_POLICY_PATH.read_text() + '\nReturn only JSON. INPUT=' + json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    def validate(raw):
        if not isinstance(raw, Mapping):
            return None, [{'family': 'parse_json', 'detail': 'object_required'}], []
        rows, errors = admission.validate(raw, snapshot, [], max(300, shadow.MAX_RELATIONS))
        return rows, errors, []
    phase = 'editorial_soft_duplicate_admission' if snapshot.get('_semantic_admission_only') else 'editorial_duplicate_admission'
    result = _run_once(snapshot, call, prompt, json.loads(ADMISSION_SCHEMA_PATH.read_text()), phase,
                       ADMISSION_POLICY_PATH, validate, cache_success=True)
    result['admitted_relations'] = result.get('output') or []
    return result


def evaluate(snapshot: Mapping[str, Any], *, provider: Callable[..., Any] | None = None,
             artifact_index: Any = None) -> dict[str, Any]:
    """Immutable primary -> independent factual election -> duplicate clearance."""
    if not isinstance(snapshot, dict):
        snapshot = copy.deepcopy(dict(snapshot))
    prepare_snapshot(snapshot)
    primary_snapshot = copy.deepcopy(snapshot)
    primary_snapshot["authorized_relations"] = []
    primary_snapshot["authorized_relations_complete"] = True
    primary_snapshot["publisher_history_12h"] = []
    # Supply factual show identity without leaking capacity or local class guesses.
    for candidate in primary_snapshot.get("candidates", []):
        metadata = _capacity_candidate(snapshot, candidate)
        for field in ("show_report_id", "show_name", "event_report_key", "corresponding_report_published"):
            if field in metadata:
                candidate[field] = copy.deepcopy(metadata[field])
    all_primary_candidates = copy.deepcopy(primary_snapshot.get("candidates", []))
    reused = []
    fresh = []
    try:
        stored = primary_store.load()
    except Exception as exc:
        return {'status': 'TECHNICAL_HOLD', 'attempts': 0, 'failure_stage': 'editorial_prefilter',
                'fallback_reason': 'primary_store_unavailable',
                'validation_errors': [{'family': 'primary_store', 'detail': type(exc).__name__}]}
    for candidate in all_primary_candidates:
        prior = stored.get(primary_store.key(candidate))
        if prior:
            reused.append(primary_store.decision(prior, candidate['candidate_id']))
        else:
            fresh.append(candidate)
    primary_snapshot['candidates'] = fresh
    _finalize_active_input(primary_snapshot)
    if primary_snapshot.get('limit_status') in {'exceeded', 'projection_failed'}:
        return {'status': 'OVERSIZE_NOT_EVALUATED', 'attempts': 0, 'fallback_reason': 'primary_input_limit'}
    call = provider
    primary = _classify(primary_snapshot, call)
    if primary.get('status') != 'VALIDATED':
        snapshot['editorial_prefilter_decisions'] = reused + primary_snapshot.get('editorial_prefilter_decisions', [])
        snapshot['editorial_prefilter_skips'] = primary_snapshot.get('editorial_prefilter_skips', [])
        return {**primary, 'failure_stage': 'editorial_prefilter'}
    decisions = reused + primary['output']['candidates']
    decisions.sort(key=lambda row: shadow.CLASSES.index(row["editorial_class"]))
    by_id = {row["candidate_id"]: row for row in decisions}
    skipped = [row for row in snapshot.get("candidates", [])
               if by_id[row["candidate_id"]]["editorial_class"] == "SKIP"]
    snapshot["editorial_prefilter_skips"] = copy.deepcopy(skipped)
    snapshot["editorial_prefilter_decisions"] = copy.deepcopy(decisions)
    snapshot["candidates"] = [row for row in snapshot.get("candidates", [])
                              if by_id[row["candidate_id"]]["editorial_class"] != "SKIP"]
    eligible = {row["candidate_id"] for row in snapshot["candidates"]}
    # Pair election sees only eligible facts, never classes or SKIP context.
    supplied = list(snapshot.get('authorized_relations', []))
    election = copy.deepcopy(snapshot)
    election['candidates'] = []; election['authorized_relations'] = []; election['publisher_history_12h'] = []
    admission.attach(election, snapshot['candidates'], snapshot.get('publisher_history_12h', []), decisions)
    _finalize_active_input(election)
    if election.get('limit_status') == 'exceeded':
        return {'status': 'OVERSIZE_NOT_EVALUATED', 'attempts': primary.get('attempts', 0),
                'failure_stage': 'duplicate_admission', 'fallback_reason': 'admission_input_limit'}
    admission_result = _admit(election, call)
    if admission_result['status'] != 'VALIDATED':
        return {**admission_result, 'attempts': primary.get('attempts', 0) + admission_result.get('attempts', 0),
                'failure_stage': 'duplicate_admission',
                'validation_attempts': primary.get('validation_attempts', []) + admission_result.get('validation_attempts', [])}
    relations = copy.deepcopy(admission_result['admitted_relations'])
    for row in relations:
        alias = next((old for old in supplied if old.get("scope") == row["scope"] and
            ((old.get("left_id"), old.get("right_id")) == (row["left_id"], row["right_id"]) or
             (row["scope"] == "same_run" and {old.get("left_id"), old.get("right_id")} ==
              {row["left_id"], row["right_id"]}))), None)
        if alias:
            row.update({key: alias[key] for key in ("pair_id", "left_id", "right_id")})
    _preserve_cached_duplicate_admissions(snapshot, relations)
    snapshot["authorized_relations"] = relations
    snapshot["authorized_relations_complete"] = True
    # Primary SKIP persists even if a sibling's duplicate provider later fails.
    from agents.menzo_policy_v93_15 import save_hard_skips
    if skipped:
        save_hard_skips({"skipped": [{**row, "decision_authority": "editorial_director",
            "editorial_director": by_id[row["candidate_id"]], "reason": "editorial_class_skip"} for row in skipped]})
    _finalize_active_input(snapshot)
    endpoints = {row.get("candidate_id") or row.get("article_id"): row
                 for row in snapshot["candidates"] + snapshot.get("publisher_history_12h", [])}
    counts = {cls: sum(row["editorial_class"] == cls for row in decisions) for cls in shadow.CLASSES}
    telemetry = {"policy_version": POLICY_VERSION, "order": "classify_then_duplicate",
                 "classified": len(decisions), "newly_classified": len(fresh), "reused_primary_classes": len(reused), "reused_strong_classes": sum(row["editorial_class"] in {"MUST_PUBLISH", "SHOULD_PUBLISH"} for row in reused), "classes": counts, "skipped_before_duplicate": len(skipped),
                 "duplicate_candidates": len(eligible), "duplicate_relations": len(snapshot["authorized_relations"]),
                 "duplicate_admission_version": admission.VERSION,
                 "terminal_policy_skips": len(snapshot.get("terminal_policy_skips", [])),
                 "relations": [{"pair_id": row["pair_id"], "scope": row["scope"],
                                "left_url": endpoints[row["left_id"]].get("url") or endpoints[row["left_id"]].get("source_url"),
                                "right_url": endpoints[row["right_id"]].get("url") or endpoints[row["right_id"]].get("source_url"),
                                "left_title": endpoints[row["left_id"]].get("title") or endpoints[row["left_id"]].get("source_title"),
                                "right_title": endpoints[row["right_id"]].get("title") or endpoints[row["right_id"]].get("source_title"),
                                "admission_version": row.get('scorer_version'),
                                "admission_basis": row.get('admission_basis')}
                               for row in snapshot["authorized_relations"]],
                 "candidates": [{"candidate_id": row["candidate_id"], "title": row.get("title"),
                                  "url": row.get("url"), "source": row.get("source"),
                                  "show_report_id": row.get("show_report_id"),
                                  "event_report_key": row.get("event_report_key"),
                                  "observed_at": snapshot.get("observation_timestamp"), **by_id[row["candidate_id"]]}
                                for row in all_primary_candidates]}
    gate = _evaluate_duplicate_stage(snapshot, provider=call, artifact_index=artifact_index)
    result = {**gate, "editorial_prefilter": telemetry,
              "attempts": int(primary.get("attempts", 0)) + int(admission_result.get("attempts", 0)) + int(gate.get("attempts", 0)),
              "logical_request_id": primary.get("logical_request_id"),
              "input_digest": primary.get("input_digest"), "policy_digest": primary.get("policy_digest"),
              "validation_attempts": primary.get("validation_attempts", []) + admission_result.get("validation_attempts", []) + gate.get("validation_attempts", []),
              "schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION}
    if gate.get("status") == "VALIDATED":
        survivors = {row["candidate_id"] for row in snapshot["candidates"]}
        result["output"] = {"schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
            "candidates": [row for row in decisions if row["candidate_id"] in survivors or row["editorial_class"] == "SKIP"],
            "relations": gate["output"].get("relations", [])}
    return result


def project(snapshot: Mapping[str, Any], result: Mapping[str, Any], *, soft_board_provider: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Mechanically project one wholly validated Active decision into Menzo's handoff."""
    originals = {row["candidate_id"]: row for row in
                 list(snapshot.get("candidates", [])) + list(snapshot.get("editorial_prefilter_skips", []))}
    sections = {"SELECT": "selected", "DEFER": "pending", "SKIP": "skipped"}
    projected: dict[str, Any] = {"selected": [], "pending": [], "skipped": [], "version": POLICY_VERSION,
        "policy_version": POLICY_VERSION, "mode": "editorial_director_active",
        "decision_authority": "editorial_director"}
    frozen_primary = primary_store.load()
    for decision in result["output"]["candidates"]:
        item = copy.deepcopy(originals[decision["candidate_id"]])
        item.pop("candidate_id", None)
        sidecar = snapshot.get("_active_bob_capacity_metadata", {})
        if isinstance(sidecar, Mapping):
            item.update(copy.deepcopy(sidecar.get(decision["candidate_id"], {})))
        item["editorial_director"] = {"policy_version": POLICY_VERSION, **copy.deepcopy(decision),
                                      "decision_authority": "editorial_director"}
        prior_editorial = frozen_primary.get(primary_store.key(item), {})
        item.pop("_priority_queue_editorial", None)
        item["editorial_director"]["policy_version"] = prior_editorial.get("policy_version") or POLICY_VERSION
        item["editorial_director"]["classified_at"] = prior_editorial.get("classified_at") or snapshot.get("observation_timestamp")
        item["editorial_director"]["first_seen_at"] = prior_editorial.get("first_seen_at") or item.get("priority_queue_first_seen_at") or item.get("first_seen_at") or snapshot.get("observation_timestamp")
        item["decision_authority"] = "editorial_director"
        item["pipeline_version"] = POLICY_VERSION
        item["decision"] = decision["recommended_action"].lower()
        item["category_hint"] = decision["category"]
        item["priority"] = {"MUST_PUBLISH": "high", "SHOULD_PUBLISH": "high",
                            "PUBLISHABLE_SOFT": "medium", "SKIP": "skip"}[decision["editorial_class"]]
        projected[sections[decision["recommended_action"]]].append(item)
    for closed in snapshot.get("terminal_policy_skips", []):
        item = copy.deepcopy(closed); item.pop("candidate_id", None)
        item.update(decision="skip", priority="skip", decision_authority="editorial_director",
                    reason=item.pop("terminal_skip_reason"), editorial_director={"editorial_class": "SKIP"})
        projected["skipped"].append(item)
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
    for item in projected['skipped']:
        entry = frozen_primary.get(primary_store.key(item))
        if entry:
            item['editorial_director'] = {'policy_version': entry.get('policy_version'),
                **primary_store.decision(entry, shadow.article_id(item)),
                'classified_at': entry.get('classified_at'), 'first_seen_at': entry.get('first_seen_at'),
                'decision_authority': 'editorial_director'}
    # ED-3: primary PUBLISHABLE_SOFT never competes here. The contextual
    # soft-board owns morning HOLD, post-noon competition, decay and tombstones.
    from agents.menzo_policy_v93_15 import (ARTIFACT_DECISIONS_FILE, MENZO_DECISIONS_FILE,
        SOFTPOOL_FILE, V92_ALLOWED_URLS_FILE, utc_now, write_json, save_hard_skips)
    from agents import menzo_priority_queue as priority_queue
    # Valid terminal decisions are irreversible even if a later handoff write fails.
    save_hard_skips({'skipped': projected['skipped']})
    paths = tuple(Path(path) for path in (SOFTPOOL_FILE, MENZO_DECISIONS_FILE,
                                         ARTIFACT_DECISIONS_FILE, V92_ALLOWED_URLS_FILE, priority_queue.queue_path()))
    before = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        from agents.menzo_soft_board import apply as apply_soft_board
        projected["editorial_prefilter"] = copy.deepcopy(result.get("editorial_prefilter", {}))
        priority_queue.schedule(projected, snapshot)
        projected = apply_soft_board(projected, snapshot, provider=soft_board_provider)
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
