"""Small, deterministic scheduling rules applied after editorial classification."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")
DAILY_NEWS_CEILING = 30


def _timestamp(record: Mapping[str, Any]) -> datetime | None:
    value = record.get("published_at") or record.get("publication_timestamp") or record.get("updated_at") or record.get("created_at")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def published_news_today_local(records: Iterable[Mapping[str, Any]], *, now: datetime | None = None) -> int:
    """Count successful news publications since local midnight in Europe/Rome."""
    current = now or datetime.now(timezone.utc)
    current_local = current.astimezone(ROME)
    today = current_local.date()
    count = 0
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if str(record.get("status") or "").lower() not in {"publish", "published", "success", "succeeded"}:
            continue
        # Publisher history is news-only. Be defensive if a mixed fixture is supplied.
        if str(record.get("content_type") or record.get("article_type") or "").lower() in {"report", "show_report", "weekly_report"}:
            continue
        stamp = _timestamp(record)
        if stamp and stamp <= current and stamp.astimezone(ROME).date() == today:
            count += 1
    return count


def remaining_news_slots(published_today: int) -> int:
    return max(0, DAILY_NEWS_CEILING - max(0, int(published_today)))


def apply_show_news_urgency(projected: dict[str, Any], *, remaining_slots_today: int) -> int:
    """Promote eligible Director deferrals, preserving Director order and provenance."""
    slots = max(0, int(remaining_slots_today)) - len(projected.get("selected", []))
    if slots <= 0:
        return 0
    promoted: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for item in projected.get("pending", []):
        director = item.get("editorial_director") if isinstance(item.get("editorial_director"), dict) else {}
        has_identity = bool(item.get("show_report_id") or item.get("special_event_match") or item.get("event_report_key"))
        eligible = (slots > 0 and has_identity and not item.get("corresponding_report_published") and
                    director.get("editorial_class") in {"SHOULD_PUBLISH", "PUBLISHABLE_SOFT"} and
                    director.get("recommended_action") == "DEFER")
        if not eligible:
            pending.append(item)
            continue
        item["decision"] = "selected"
        item["scheduling_override"] = {
            "reason": "show_news_urgency_pre_report",
            "original_recommended_action": "DEFER",
            "final_action": "SELECT",
        }
        item["reason"] = "show_news_urgency_pre_report"
        promoted.append(item)
        slots -= 1
    projected["selected"].extend(promoted)
    projected["pending"] = pending
    return len(promoted)
