"""TOTEM-C01: append-only first valid primary decisions, keyed by canonical URL."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from agents import menzo_policy_v93_15 as menzo
from agents import menzo_editorial_director_shadow as shadow

STORE_FILE = menzo.NEWSROOM_STATE_DIR / 'menzo_primary_classifications_v1.json'
MASTER_LOG = menzo.NEWSROOM_STATE_DIR / 'master_log.jsonl'
VERSION = 'totem-c01-first-valid-primary-v1'
ACTIONS = {'MUST_PUBLISH': 'SELECT', 'SHOULD_PUBLISH': 'SELECT',
           'PUBLISHABLE_SOFT': 'DEFER', 'SKIP': 'SKIP'}


def valid(row: Any) -> bool:
    return (isinstance(row, Mapping) and row.get('editorial_class') in ACTIONS and
            row.get('recommended_action') == ACTIONS[row['editorial_class']] and
            row.get('category') in shadow.CATEGORIES and isinstance(row.get('story_core'), str) and
            bool(row['story_core'].strip()))


def key(row: Mapping[str, Any]) -> str:
    return menzo.source_key(str(row.get('url') or row.get('source_url') or ''))


def _entry(article, decision, when, policy):
    return {'url': article.get('url') or article.get('source_url'), 'title': article.get('title'),
            'classified_at': decision.get('classified_at') or when,
            'first_seen_at': decision.get('first_seen_at') or when,
            'policy_version': decision.get('policy_version') or policy,
            **{k: copy.deepcopy(decision.get(k)) for k in
               ('editorial_class', 'recommended_action', 'category', 'story_core', 'relative_rank')}}


def load() -> dict[str, dict[str, Any]]:
    if STORE_FILE.exists():
        value = json.loads(STORE_FILE.read_text(encoding='utf-8'))
        if (not isinstance(value, dict) or value.get('version') != VERSION or
                not isinstance(value.get('entries'), dict) or
                any(not valid(row) or key(row) != k for k, row in value['entries'].items())):
            raise ValueError('invalid_primary_classification_store')
        return value['entries']
    # One-time migration uses authoritative chronological observations, not the
    # last queue copy (which can already contain an illegitimate promotion).
    entries = {}
    if MASTER_LOG.exists():
        observations = []
        for line in MASTER_LOG.open(encoding='utf-8'):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            pipeline = row.get('editorial_pipeline') or {}
            if pipeline.get('status') != 'VALIDATED':
                continue
            when = (row.get('run') or {}).get('started_at') or row.get('recorded_at') or ''
            prefilter = pipeline.get('prefilter') or {}
            for decision in prefilter.get('candidates', []):
                if valid(decision) and key(decision):
                    observations.append((when, decision, prefilter.get('policy_version')))
        for when, row, policy in sorted(observations, key=lambda item: item[0]):
            entries.setdefault(key(row), _entry(row, row, when, policy))
    # Legacy pools/queues supply a valid decision only when no earlier evidence
    # is retained. Never delete terminal SKIP memory or revive a closed URL.
    paths = [menzo.SOFTPOOL_FILE, Path(menzo.SOFTPOOL_FILE).with_name('menzo_priority_queue.json')]
    for path in paths:
        if not path.exists():
            continue
        value = menzo.load_json(path, {})
        for row in value.get('items', []) if isinstance(value, dict) else []:
            decision = row.get('editorial_director') or {}
            if key(row) and valid(decision):
                entries.setdefault(key(row), _entry(row, decision,
                    row.get('soft_board_first_seen_at') or row.get('first_seen_at') or menzo.utc_now(),
                    decision.get('policy_version')))
    if entries:
        _write(entries)
    return entries


def _write(entries):
    menzo.write_json(STORE_FILE, {'version': VERSION, 'entries': entries})


def remember(articles, decisions, *, when, policy) -> dict[str, dict[str, Any]]:
    entries = load()
    by_id = {row['candidate_id']: row for row in articles}
    changed = False
    for decision in decisions:
        article = by_id.get(decision.get('candidate_id'))
        if article and key(article) and valid(decision) and key(article) not in entries:
            entries[key(article)] = _entry(article, decision, when, policy)
            changed = True
    if changed:
        _write(entries)
    return entries


def decision(entry, candidate_id):
    return {'candidate_id': candidate_id, **{k: copy.deepcopy(entry.get(k)) for k in
        ('editorial_class', 'recommended_action', 'category', 'story_core', 'relative_rank')}}
