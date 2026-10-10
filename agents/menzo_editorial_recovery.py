"""Single-attempt editorial operations with explicit, bounded technical backoff."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

from agents import menzo_policy_v93_15 as menzo

CACHE_FILE = menzo.NEWSROOM_STATE_DIR / 'menzo_editorial_recovery_v1.json'
VERSION = 'single-attempt-editorial-recovery-v1'


def _load():
    if not CACHE_FILE.exists():
        return {}
    value = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    if value.get('version') != VERSION or not isinstance(value.get('entries'), dict):
        raise ValueError('invalid_editorial_recovery_cache')
    return value['entries']


def lookup(fingerprint, *, success=False):
    row = _load().get(fingerprint)
    if not isinstance(row, dict):
        return None
    if success and row.get('status') == 'VALIDATED':
        return copy.deepcopy(row)
    if row.get('status') != 'VALIDATED' and datetime.fromisoformat(row['retry_after']) > datetime.now(timezone.utc):
        return copy.deepcopy(row)
    return None


def record(fingerprint, output, failures, *, success=False):
    entries = _load()
    prior = entries.get(fingerprint, {})
    now = datetime.now(timezone.utc)
    failures_count = int(prior.get('failure_count', 0)) + 1
    if not failures and success:
        row = {'status': 'VALIDATED', 'output': copy.deepcopy(output)}
    elif failures:
        # An unchanged failing request is retried after 60/120/240 minutes.
        # Changed material or contract has a different fingerprint immediately.
        delay = min(240, 60 * 2 ** min(failures_count - 1, 2))
        row = {'status': 'TECHNICAL_HOLD', 'validation_errors': copy.deepcopy(failures),
               'failure_count': failures_count, 'retry_after': (now + timedelta(minutes=delay)).isoformat()}
    else:
        entries.pop(fingerprint, None)
        row = None
    if row is not None:
        entries[fingerprint] = {**row, 'updated_at': now.isoformat()}
    entries = dict(sorted(entries.items(), key=lambda item: item[1].get('updated_at', ''))[-2048:])
    menzo.write_json(CACHE_FILE, {'version': VERSION, 'entries': entries})
