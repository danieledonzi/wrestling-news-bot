"""Immutable pair specifications and fail-closed deterministic coverage checks."""
from __future__ import annotations

import math
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from agents.duplicate_pair_identity import article_id, recent_history_pair_id, same_run_pair_id
from agents import menzo_duplicate_scorer


@dataclass(frozen=True)
class PairSpec:
    pair_id: str
    scope: str
    left_article_id: str
    right_article_id: str
    left: dict[str, Any]
    right: dict[str, Any]
    left_role: str
    right_role: str


def _snapshot(item: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(item)


def build_same_run_pair_specs(items: Iterable[dict[str, Any]]) -> list[PairSpec]:
    snapshots = sorted((_snapshot(x) for x in items), key=lambda x: article_id(x))
    output: list[PairSpec] = []
    for index, left in enumerate(snapshots):
        left_id = article_id(left)
        for right in snapshots[index + 1:]:
            right_id = article_id(right)
            if not left_id or not right_id or left_id == right_id:
                continue
            output.append(PairSpec(same_run_pair_id(left_id, right_id), "same_run", left_id,
                                   right_id, left, right, "candidate", "candidate"))
    return output


def build_recent_history_pair_specs(candidates: Iterable[dict[str, Any]], history: Iterable[dict[str, Any]]) -> list[PairSpec]:
    current = sorted((_snapshot(x) for x in candidates), key=lambda x: article_id(x))
    published = sorted((_snapshot(x) for x in history), key=lambda x: article_id(x))
    return [PairSpec(recent_history_pair_id(article_id(candidate), article_id(old)), "recent_history",
                     article_id(candidate), article_id(old), candidate, old, "candidate", "published")
            for candidate in current for old in published if article_id(candidate) and article_id(old)]


def _record(spec: PairSpec, scored: dict[str, Any], evaluation_pass: str) -> dict[str, Any]:
    allowed = {
        "score", "threshold", "above_threshold", "exact_duplicate", "exact_reason",
        "components", "penalties", "reasons", "scorer_version",
    }
    score_fields = {key: scored[key] for key in allowed if key in scored}
    score_fields = {"scorer_version": menzo_duplicate_scorer.SCORER_VERSION,
                    "components": {}, "penalties": {}, "reasons": [], **score_fields}
    return {"pair_id": spec.pair_id, "scope": spec.scope,
            "left_article_id": spec.left_article_id, "right_article_id": spec.right_article_id,
            "left_role": spec.left_role, "right_role": spec.right_role,
            "left_source_url": menzo_duplicate_scorer.canonical_source_url(spec.left),
            "right_source_url": menzo_duplicate_scorer.canonical_source_url(spec.right),
            "left_title": str(spec.left.get("title") or spec.left.get("source_title") or ""),
            "right_title": str(spec.right.get("title") or spec.right.get("source_title") or ""),
            **score_fields, "evaluation_pass": evaluation_pass, "status": "evaluated",
            "gemini_decision": "", "cache_status": "not_applicable", "final_disposition": "pending"}


def _coverage(expected: set[str], records: list[dict[str, Any]]) -> dict[str, Any]:
    ids = [str(x.get("pair_id") or "") for x in records]
    counts = Counter(ids)
    invalid = []
    for value in records:
        valid = (value.get("pair_id") in expected and isinstance(value.get("score"), (int, float))
                 and not isinstance(value.get("score"), bool) and math.isfinite(float(value["score"]))
                 and isinstance(value.get("threshold"), (int, float))
                 and isinstance(value.get("above_threshold"), bool)
                 and isinstance(value.get("exact_duplicate"), bool) and bool(value.get("scorer_version")))
        if not valid:
            invalid.append(str(value.get("pair_id") or ""))
    evaluated = set(ids)
    duplicate = sorted(key for key, count in counts.items() if count > 1)
    unexpected = sorted(evaluated - expected)
    missing = sorted(expected - evaluated)
    complete = evaluated == expected and len(records) == len(expected) and not duplicate and not invalid
    return {"coverage_complete": complete, "missing_pair_ids": missing,
            "unexpected_pair_ids": unexpected, "duplicate_evaluation_pair_ids": duplicate,
            "invalid_score_pair_ids": sorted(set(invalid))}


def evaluate_pair_matrix(specs: list[PairSpec], *, evaluator: Callable[[PairSpec, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Score the entire snapshot; replay the *entire* matrix after any invariant failure."""
    expected = {spec.pair_id for spec in specs}
    score = evaluator or (lambda spec, _pass: menzo_duplicate_scorer.score_pair(spec.left, spec.right))

    def run(evaluation_pass: str) -> list[dict[str, Any]]:
        records = []
        for spec in specs:
            try:
                value = score(spec, evaluation_pass)
                records.append(_record(spec, value, evaluation_pass))
            except Exception:
                # Exceptions deliberately remain absent; coverage must fail rather than be padded.
                continue
        return records

    first = run("normal")
    before = _coverage(expected, first)
    replayed = not before["coverage_complete"]
    authoritative = run("forced_full_replay") if replayed else first
    after = _coverage(expected, authoritative)
    return {"expected_pair_ids": expected, "first_pass_records": first,
            "records": authoritative, "first_pass_evaluated_pair_count": len(first),
            "forced_full_replay_triggered": replayed,
            "forced_replay_pair_count": len(authoritative) if replayed else 0,
            "authoritative_evaluated_pair_count": len(authoritative),
            "coverage_complete": after["coverage_complete"],
            "missing_pair_ids_before_replay": before["missing_pair_ids"],
            "missing_pair_ids_after_replay": after["missing_pair_ids"],
            "unexpected_pair_ids": after["unexpected_pair_ids"],
            "duplicate_evaluation_pair_ids": after["duplicate_evaluation_pair_ids"],
            "invalid_score_pair_ids": after["invalid_score_pair_ids"]}
