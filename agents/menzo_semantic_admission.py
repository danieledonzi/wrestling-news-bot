"""Relation identities and archived semantic-admission readers.

The active provider path lives in menzo_card_admission and uses isolated factual
cards with an explicit assessment for every permitted pair. Legacy anchor helpers
remain available for retained artifacts and historical regression fixtures.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from agents.duplicate_pair_identity import recent_history_pair_id, same_run_pair_id

VERSION = 'isolated-card-complete-pair-admission-v1'
# Admission transport changes do not reopen unchanged final full-body judgments.
FINAL_JUDGMENT_BINDING_VERSION = 'totem-d01-factual-admission-v6'
FACT_LIMIT = 500


def bound_schema(template: Mapping[str, Any], primary: Mapping[str, Any], *, payload=None) -> dict[str, Any]:
    """Make invented/out-of-range refs unrepresentable in the provider contract."""
    schema = copy.deepcopy(dict(template))
    current = [row['ref'] for row in primary['_semantic_admission']['candidates']]
    history = [row['ref'] for row in primary['_semantic_admission']['history']]
    right = current + history
    if payload is not None:
        current = [payload['anchor']['ref']]
        right = [row['ref'] for row in payload['targets']]
    properties = schema['properties']['suspected_duplicates']['items']['properties']
    properties['left_ref'] = {'type': 'string', 'enum': current}
    properties['right_ref'] = {'type': 'string', 'enum': right}
    return schema


def anchored_payloads(primary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Elect sparsely from one current article; targets cannot be compared together."""
    data = primary['_semantic_admission']
    return [{'contract_version': VERSION, 'anchor': copy.deepcopy(row),
             'targets': copy.deepcopy(data['candidates'][index + 1:] + data['history'])}
            for index, row in enumerate(data['candidates'])
            if data['candidates'][index + 1:] or data['history']]


def compact(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in {
        'title': row.get('title') or row.get('source_title') or row.get('title_it') or '',
        'url': row.get('url') or row.get('source_url'),
        'summary': str(row.get('summary') or '')[:2500],
        'retained_body': row.get('retained_body'),
        'input_coverage': row.get('input_coverage'),
        'source': row.get('source'), 'published_at': row.get('published_at'),
        'show_report_id': row.get('show_report_id'), 'event_report_key': row.get('event_report_key'),
    }.items() if value not in (None, '')}


def attach(primary: dict[str, Any], all_candidates: list[dict[str, Any]],
           history: list[dict[str, Any]], known: list[dict[str, Any]]) -> None:
    fixed = {row['candidate_id']: row for row in known}
    primary['_semantic_admission'] = {
        'candidates': [{**compact(row), 'ref': f'a{i}'}
                       for i, row in enumerate(all_candidates)],
        'history': [{**compact(row), 'ref': f'h{i}'} for i, row in enumerate(history)],
        'contract_version': VERSION,
    }
    primary['_admission_candidate_ids'] = [row['candidate_id'] for row in all_candidates]
    primary['_admission_history_ids'] = [row['article_id'] for row in history]
    primary['_admission_fixed_classes'] = {key: row['editorial_class'] for key, row in fixed.items()}


def validate(raw: Any, primary: Mapping[str, Any], decisions: list[dict[str, Any]],
             max_relations: int) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]]]:
    ids = primary.get('_admission_candidate_ids', [])
    old_ids = primary.get('_admission_history_ids', [])
    classes = {**primary.get('_admission_fixed_classes', {}),
               **{row['candidate_id']: row['editorial_class'] for row in decisions}}
    eligible = {key for key in ids if classes.get(key) != 'SKIP'}
    # An empty or one-endpoint universe needs no semantic comparison decision.
    if not eligible or (len(eligible) == 1 and not old_ids):
        if raw.get('suspected_duplicates') not in (None, []):
            return None, [{'family': 'semantic_admission_ref', 'detail': 'no_eligible_pair'}]
        return [], []
    if raw.get('admission_complete') is not True:
        return None, [{'family': 'semantic_admission_coverage', 'detail': 'explicit_complete_required'}]
    suspects = raw.get('suspected_duplicates')
    if not isinstance(suspects, list) or len(suspects) > max_relations:
        return None, [{'family': 'semantic_admission_contract', 'detail': 'bounded_array_required'}]
    current = {f'a{i}': key for i, key in enumerate(ids)}
    history = {f'h{i}': key for i, key in enumerate(old_ids)}
    relations, seen, failures = [], set(), []
    for index, row in enumerate(suspects):
        if not isinstance(row, Mapping):
            failures.append({'family': 'semantic_admission_contract', 'detail': 'object_required'}); continue
        left, right, basis = row.get('left_ref'), row.get('right_ref'), row.get('basis')
        if (not isinstance(left, str) or not isinstance(right, str) or left not in current or
                right not in {**current, **history} or left == right):
            failures.append({'family': 'semantic_admission_ref', 'detail': 'invalid_endpoint',
                'ref': f'p{index}',
                'left_ref': left[:80] if isinstance(left, str) else None,
                'right_ref': right[:80] if isinstance(right, str) else None,
                'candidate_count': len(current), 'history_count': len(history)}); continue
        left_id = current[left]
        right_id = current.get(right) or history.get(right)
        scope = 'same_run' if right in current else 'recent_history'
        if left_id not in eligible or (scope == 'same_run' and right_id not in eligible):
            failures.append({'family': 'semantic_admission_ref', 'detail': 'skip_endpoint_forbidden'}); continue
        if not isinstance(basis, str) or not basis.strip() or len(basis) > 1000:
            failures.append({'family': 'semantic_admission_basis', 'detail': 'bounded_meaning_required'}); continue
        facts = {field: row.get(field) for field in ('anchor_fact', 'target_fact')}
        if any(not isinstance(value, str) or not value.strip() or len(value) > FACT_LIMIT
               for value in facts.values()):
            failures.append({'family': 'semantic_admission_facts',
                             'detail': 'bounded_endpoint_facts_required'}); continue
        # These are Gemini's factual explanations. Local validation never decides
        # whether the supplied facts really overlap or vetoes a semantic judgment.
        if scope == 'same_run':
            left_id, right_id = sorted((left_id, right_id))
        relation = make_relation(scope, left_id, right_id, basis.strip())
        relation['admission_evidence'] = {
            'anchor_id': current[left], 'target_id': current.get(right) or history.get(right),
            **{name: value.strip() for name, value in facts.items()}}
        if relation['pair_id'] in seen:
            failures.append({'family': 'semantic_admission_ref', 'detail': 'duplicate_pair'}); continue
        seen.add(relation['pair_id']); relations.append(relation)
    return (None, failures) if failures else (relations, [])


def make_relation(scope: str, left_id: str, right_id: str, basis: str) -> dict[str, Any]:
    pair_id = (same_run_pair_id(left_id, right_id) if scope == 'same_run'
               else recent_history_pair_id(left_id, right_id))
    return {'pair_id': pair_id, 'scope': scope, 'left_id': left_id, 'right_id': right_id,
            'scorer_version': FINAL_JUDGMENT_BINDING_VERSION, 'score': 1.0, 'threshold': 1.0,
            'components': {'gemini_semantic_suspicion': 1.0}, 'admission_basis': basis}
