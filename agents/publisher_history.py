"""Bounded heavy-field retention for Publisher's permanent idempotency history."""
from __future__ import annotations

import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any
from agents.duplicate_pair_identity import article_id

DEFAULT_CANONICAL_BODY_RETENTION_HOURS = 72
HEAVY_BODY_FIELDS = {
    "canonical_source_body", "source_cleaned_full_text", "published_cleaned_full_text",
    "cleaned_full_text", "full_body", "body_text", "article_text", "extracted_text",
    "body_html", "content",
}


def retention_hours() -> int:
    try:
        return max(0, int(os.getenv("PUBLISHER_CANONICAL_BODY_RETENTION_HOURS", str(DEFAULT_CANONICAL_BODY_RETENTION_HOURS))))
    except (TypeError, ValueError):
        return DEFAULT_CANONICAL_BODY_RETENTION_HOURS


def _timestamp(record: dict[str, Any]) -> datetime | None:
    value = record.get("published_at") or record.get("publication_timestamp") or record.get("updated_at") or record.get("created_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def body_within_retention(record: dict[str, Any], *, now: datetime | None = None, hours: int | None = None) -> bool:
    current = now or datetime.now(timezone.utc)
    stamp = _timestamp(record)
    window = retention_hours() if hours is None else max(0, int(hours))
    return bool(stamp and stamp <= current and current - stamp <= timedelta(hours=window))


def prune_record(record: dict[str, Any], *, now: datetime | None = None, hours: int | None = None) -> dict[str, Any]:
    output = deepcopy(record)
    calculated_id = article_id(output)
    if output.get("article_id") and output.get("article_id") != calculated_id:
        output["article_id_migrated_from"] = output["article_id"]
    output["article_id"] = calculated_id
    recent = body_within_retention(output, now=now, hours=hours)
    # The source text already lives inside canonical_source_body; final editorial
    # text belongs only in the per-publication trace.
    output.pop("source_cleaned_full_text", None)
    output.pop("published_cleaned_full_text", None)
    for field in HEAVY_BODY_FIELDS - {"canonical_source_body", "source_cleaned_full_text", "published_cleaned_full_text"}:
        output.pop(field, None)
    if not recent:
        output.pop("canonical_source_body", None)
    return output


def prune_history(history: Any, *, now: datetime | None = None, hours: int | None = None) -> Any:
    """Return the same legacy shape with deterministic record-level cleanup."""
    if isinstance(history, dict):
        return {key: prune_record(value, now=now, hours=hours) if isinstance(value, dict) else value for key, value in history.items()}
    if isinstance(history, list):
        return [prune_record(value, now=now, hours=hours) if isinstance(value, dict) else value for value in history]
    return history
