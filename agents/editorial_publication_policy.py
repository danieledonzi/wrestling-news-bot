"""Owner-approved rolling publication pressure, independent of immutable classes."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from agents.news_scheduling import is_successful_news_publication, publication_timestamp

POLICY_VERSION = 'owtv_publication_pressure_v1'
SOFT_STOP = 25
ORDINARY_SHOULD_STOP = 25
PRIORITY_SHOULD_STOP = 30


def now_at(value=None):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def published_count(records=None, *, now=None):
    """Successful unique news in (now-24h, now]; reports/dry runs do not count.

    An unreadable existing history is an error, never a fabricated zero.
    """
    if records is None:
        from agents.menzo_policy_v93_15 import publisher_history_file
        path = publisher_history_file()
        raw = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(raw, (dict, list)):
            raise ValueError('invalid_publication_pressure_history')
        records = raw.values() if isinstance(raw, dict) else raw
    current = now_at(now)
    seen = set()
    from agents.menzo_policy_v93_15 import source_key
    for index, row in enumerate(records):
        if not isinstance(row, Mapping) or not is_successful_news_publication(row) or row.get('dry_run'):
            continue
        at = publication_timestamp(row)
        if at and current - timedelta(hours=24) < at <= current:
            # Missing legacy identity is explicit: retain the record in the count.
            seen.add(source_key(str(row.get('source_url') or row.get('url') or '')) or f'legacy:{index}')
    return len(seen)


def primary_class(row):
    return str((row.get('editorial_director') or {}).get('editorial_class') or '')


def coverage_priority(row):
    return (row.get('editorial_director') or {}).get('coverage_priority') is True


def rejection_reason(row, count):
    if str(row.get('content_type') or row.get('article_type') or '').lower() in {'report', 'show_report', 'weekly_report'}:
        return None
    cls = primary_class(row)
    if cls == 'MUST_PUBLISH':
        return None
    if count >= PRIORITY_SHOULD_STOP:
        return 'publication_pressure:30_must_only'
    if count >= ORDINARY_SHOULD_STOP and not (cls == 'SHOULD_PUBLISH' and coverage_priority(row)):
        return 'publication_pressure:25_priority_should_only'
    return None


def terminal_skip(row, reason, count, *, stage):
    item = copy.deepcopy(row)
    item.update(decision='skip', decision_authority='editorial_pacing', reason=reason,
                publication_pressure={'policy_version': POLICY_VERSION, 'window_hours': 24,
                    'projected_news_count': count, 'stage': stage,
                    'coverage_priority': coverage_priority(row)})
    return item


def soft_remaining(selected, *, now=None):
    return max(0, SOFT_STOP - published_count(now=now) - len(selected))
