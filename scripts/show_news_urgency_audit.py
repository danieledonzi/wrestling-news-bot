from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.news_scheduling import is_successful_news_publication, publication_timestamp

MASTER_LOG = ROOT / "state" / "newsroom" / "master_log.jsonl"
PUBLISHER_HISTORY = ROOT / "state" / "newsroom" / "publisher_history.json"
LATEST_JSON = ROOT / "state" / "reports" / "owtv_show_news_urgency_audit_latest.json"
REPORTS_DIR = ROOT / "reports"

LOCAL_TIMEZONE = "Europe/Rome"
DAILY_NEWS_CEILING = 30
URGENCY_REASON = "show_news_urgency_pre_report"
MASTER_SCHEMA_VERSION = "v93_19_1_show_news_urgency_audit"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _source_url(item: dict[str, Any]) -> str:
    return str(item.get("source_url") or item.get("url") or "").strip()


def _show_identity(item: dict[str, Any]) -> str:
    special = item.get("special_event_match")
    if isinstance(special, dict):
        special = special.get("report_key") or special.get("night_key") or special.get("event_key")
    return str(
        item.get("show_report_id")
        or item.get("event_report_key")
        or special
        or ""
    ).strip()


def _load_master_rows(
    path: Path,
    *,
    now: datetime,
    hours: int,
) -> tuple[list[tuple[datetime, dict[str, Any]]], dict[str, Any]]:
    meta = {
        "available": False,
        "reason": None,
        "nonempty_rows": 0,
        "malformed_rows": 0,
        "undated_rows": 0,
        "parseable_rows": 0,
    }
    if not path.exists():
        meta["reason"] = "missing_master_log"
        return [], meta
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError as exc:
        meta["reason"] = f"master_log_read_failed:{type(exc).__name__}"
        return [], meta

    cutoff = now - timedelta(hours=max(1, int(hours)))
    rows: list[tuple[datetime, dict[str, Any]]] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        meta["nonempty_rows"] += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            meta["malformed_rows"] += 1
            continue
        if not isinstance(payload, dict):
            meta["malformed_rows"] += 1
            continue
        meta["parseable_rows"] += 1
        run = payload.get("run") if isinstance(payload.get("run"), dict) else {}
        stamp = _parse_datetime(run.get("started_at")) or _parse_datetime(payload.get("recorded_at"))
        if stamp is None:
            meta["undated_rows"] += 1
            continue
        if cutoff <= stamp <= now + timedelta(minutes=5):
            rows.append((stamp, payload))

    if meta["nonempty_rows"] and meta["parseable_rows"] == 0:
        meta["reason"] = "master_log_no_parseable_rows"
        return [], meta
    meta["available"] = True
    return rows, meta


def _load_history(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = {"available": False, "reason": None, "records": 0, "malformed_records": 0}
    if not path.exists():
        meta["reason"] = "missing_publisher_history"
        return [], meta
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        meta["reason"] = f"publisher_history_read_failed:{type(exc).__name__}"
        return [], meta
    if isinstance(payload, dict):
        values = list(payload.values())
    elif isinstance(payload, list):
        values = list(payload)
    else:
        meta["reason"] = "publisher_history_invalid_shape"
        return [], meta

    rows: list[dict[str, Any]] = []
    malformed = 0
    for item in values:
        if not isinstance(item, dict):
            malformed += 1
            continue
        # Publisher history is an idempotency ledger: every record must retain
        # an identity, status and a timestamp understood by the ceiling logic.
        if (
            not _source_url(item)
            or not str(item.get("status") or "").strip()
            or publication_timestamp(item) is None
        ):
            malformed += 1
            continue
        rows.append(item)

    meta["malformed_records"] = malformed
    meta["records"] = len(rows)
    if malformed:
        meta["reason"] = f"publisher_history_malformed_records:{malformed}"
        return rows, meta
    meta["available"] = True
    return rows, meta


def _dedupe_urls(items: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({_source_url(item) for item in items if _source_url(item)})


def build_audit(
    *,
    root: Path = ROOT,
    hours: int = 24,
    now: datetime | None = None,
    timezone_name: str = LOCAL_TIMEZONE,
    daily_ceiling: int = DAILY_NEWS_CEILING,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    master_path = root / "state" / "newsroom" / "master_log.jsonl"
    history_path = root / "state" / "newsroom" / "publisher_history.json"
    rows, master_meta = _load_master_rows(master_path, now=current, hours=hours)
    history, history_meta = _load_history(history_path)
    local_tz = ZoneInfo(timezone_name)
    cutoff = current - timedelta(hours=max(1, int(hours)))

    supported_runs = sum(1 for _stamp, row in rows if row.get("schema_version") == MASTER_SCHEMA_VERSION)
    pending_truncated_runs = sum(
        1
        for _stamp, row in rows
        if isinstance(row.get("menzo"), dict) and row["menzo"].get("pending_sample_truncated") is True
    )
    master_clean = bool(
        master_meta["available"]
        and master_meta["malformed_rows"] == 0
        and master_meta["undated_rows"] == 0
    )
    urgency_coverage_complete = bool(
        rows
        and master_clean
        and supported_runs == len(rows)
        and pending_truncated_runs == 0
    )
    history_clean = bool(history_meta["available"])

    show_objects: list[dict[str, Any]] = []
    urgency_objects: list[dict[str, Any]] = []
    pending_eligible: list[dict[str, Any]] = []
    capacity_skips: list[dict[str, Any]] = []
    daily_ceiling_skips: list[dict[str, Any]] = []
    urgency_after_report: list[dict[str, Any]] = []

    urgency_selected_urls: set[str] = set()
    urgency_published_with_provenance: set[str] = set()
    published_urls_in_master: set[str] = set()

    for _stamp, row in rows:
        menzo = row.get("menzo") if isinstance(row.get("menzo"), dict) else {}
        publisher = row.get("publisher") if isinstance(row.get("publisher"), dict) else {}

        for section in ("selected", "pending"):
            values = menzo.get(section)
            for item in values if isinstance(values, list) else []:
                if not isinstance(item, dict):
                    continue
                identity = _show_identity(item)
                if identity:
                    show_objects.append(item)
                override = item.get("scheduling_override")
                if isinstance(override, dict) and override.get("reason") == URGENCY_REASON:
                    urgency_objects.append(item)
                    url = _source_url(item)
                    if section == "selected" and url:
                        urgency_selected_urls.add(url)
                    if item.get("corresponding_report_published") is True:
                        urgency_after_report.append(item)
                if section == "pending" and identity:
                    director = item.get("editorial_director") if isinstance(item.get("editorial_director"), dict) else {}
                    if (
                        item.get("corresponding_report_published") is not True
                        and director.get("editorial_class") in {"SHOULD_PUBLISH", "PUBLISHABLE_SOFT"}
                        and director.get("recommended_action") == "DEFER"
                    ):
                        pending_eligible.append(item)

        for item in publisher.get("results", []) if isinstance(publisher.get("results"), list) else []:
            if not isinstance(item, dict):
                continue
            url = _source_url(item)
            if item.get("status") == "published" and url:
                published_urls_in_master.add(url)
            override = item.get("scheduling_override")
            if (
                item.get("status") == "published"
                and url
                and isinstance(override, dict)
                and override.get("reason") == URGENCY_REASON
            ):
                urgency_published_with_provenance.add(url)

        for item in _walk_dicts(row):
            if item.get("status") == "skipped_capacity":
                capacity_skips.append(item)
                if str(item.get("reason") or "").startswith("daily_news_ceiling"):
                    daily_ceiling_skips.append(item)
            override = item.get("scheduling_override")
            if isinstance(override, dict) and override.get("reason") == URGENCY_REASON:
                if item not in urgency_objects:
                    urgency_objects.append(item)
                if item.get("corresponding_report_published") is True and item not in urgency_after_report:
                    urgency_after_report.append(item)

    per_day_record_counts: dict[str, int] = defaultdict(int)
    per_day_urls: dict[str, set[str]] = defaultdict(set)
    published_24h_urls: set[str] = set()
    if history_clean:
        for item in history:
            if not is_successful_news_publication(item):
                continue
            stamp = publication_timestamp(item)
            url = _source_url(item)
            if stamp is None or not url or stamp > current + timedelta(minutes=5):
                continue
            local_date = stamp.astimezone(local_tz).date().isoformat()
            # Match enforcement semantics exactly: every successful history
            # record consumes one daily slot, even if a source URL repeats.
            per_day_record_counts[local_date] += 1
            per_day_urls[local_date].add(url)
            if cutoff <= stamp <= current + timedelta(minutes=5):
                published_24h_urls.add(url)

    today_local = current.astimezone(local_tz).date().isoformat()
    daily_counts = dict(sorted(per_day_record_counts.items()))
    relevant_daily_counts = {
        date: count
        for date, count in daily_counts.items()
        if date >= cutoff.astimezone(local_tz).date().isoformat()
    }
    ceiling_violations = {
        date: count for date, count in relevant_daily_counts.items() if count > daily_ceiling
    } if history_clean else {}

    urgency_urls = set(_dedupe_urls(urgency_objects))
    lost_provenance_urls = sorted(
        url for url in urgency_selected_urls
        if url in published_urls_in_master and url not in urgency_published_with_provenance
    )
    show_urls = set(_dedupe_urls(show_objects))
    pending_eligible_urls = set(_dedupe_urls(pending_eligible))
    # A show identity alone is not an urgency opportunity: normally selected
    # or otherwise ineligible show news should keep the audit at no_opportunity.
    opportunity_observed = bool(urgency_urls or pending_eligible_urls)

    warnings: list[str] = []
    if not master_meta["available"]:
        warnings.append(str(master_meta["reason"] or "master_log_unavailable"))
    if master_meta["malformed_rows"]:
        warnings.append(f"master_log_malformed_rows:{master_meta['malformed_rows']}")
    if master_meta["undated_rows"]:
        warnings.append(f"master_log_undated_rows:{master_meta['undated_rows']}")
    if not history_meta["available"]:
        warnings.append(str(history_meta["reason"] or "publisher_history_unavailable"))
    if master_meta["available"] and not urgency_coverage_complete:
        warnings.append(f"urgency_master_coverage_partial:{supported_runs}/{len(rows)}")
    if pending_truncated_runs:
        warnings.append(f"urgency_pending_sample_truncated_runs:{pending_truncated_runs}")

    daily_check: bool | None = (not bool(ceiling_violations)) if history_clean else None
    master_checks_available = urgency_coverage_complete
    post_report_check: bool | None = (not bool(urgency_after_report)) if master_checks_available else None
    provenance_check: bool | None = (not bool(lost_provenance_urls)) if master_checks_available else None

    if not master_meta["available"] or not history_meta["available"]:
        status = "unavailable"
    elif master_meta["malformed_rows"]:
        status = "attention"
    elif daily_check is False or post_report_check is False or provenance_check is False:
        status = "attention"
    elif not urgency_coverage_complete:
        status = "partial_coverage"
    elif not opportunity_observed:
        status = "no_opportunity"
    else:
        status = "ok"

    return {
        "schema_version": "show_news_urgency_audit_v1",
        "generated_at": current.isoformat(),
        "hours": int(hours),
        "window_start_utc": cutoff.isoformat(),
        "window_end_utc": current.isoformat(),
        "status": status,
        "runs": len(rows),
        "source_coverage": {
            "master_log": {
                **master_meta,
                "runs_in_window": len(rows),
                "urgency_schema_version": MASTER_SCHEMA_VERSION,
                "urgency_supported_runs": supported_runs,
                "pending_truncated_runs": pending_truncated_runs,
                "urgency_complete_window": urgency_coverage_complete,
            },
            "publisher_history": history_meta,
        },
        "daily_ceiling": {
            "limit": int(daily_ceiling),
            "timezone": timezone_name,
            "today_local": today_local,
            "published_today_local": daily_counts.get(today_local) if history_clean else None,
            "published_unique_last_window": len(published_24h_urls) if history_clean else None,
            "per_day_counts": relevant_daily_counts if history_clean else {},
            "skipped_capacity_unique_urls": len(set(_dedupe_urls(capacity_skips))),
            "daily_ceiling_skips_unique_urls": len(set(_dedupe_urls(daily_ceiling_skips))),
            "violations": ceiling_violations,
        },
        "show_news_urgency": {
            "opportunity_observed": opportunity_observed if master_checks_available else None,
            "show_identity_unique_urls": len(show_urls),
            "promoted_unique_urls": len(urgency_urls),
            "published_with_provenance_unique_urls": len(urgency_published_with_provenance),
            "pending_eligible_unique_urls": len(pending_eligible_urls),
            "urgency_after_report_urls": _dedupe_urls(urgency_after_report),
            "lost_provenance_urls": lost_provenance_urls,
            "promoted_urls": sorted(urgency_urls),
            "pending_eligible_urls": sorted(pending_eligible_urls),
        },
        "checks": {
            "daily_ceiling_respected": daily_check,
            "no_post_report_urgency": post_report_check,
            "urgency_provenance_preserved": provenance_check,
        },
        "warnings": warnings,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    ceiling = payload["daily_ceiling"]
    urgency = payload["show_news_urgency"]
    checks = payload["checks"]
    coverage = payload.get("source_coverage", {}).get("master_log", {})
    def mark(value: Any) -> str:
        if value is True:
            return "OK"
        if value is False:
            return "ATTENTION"
        return "N.D."
    opportunity_value = urgency.get("opportunity_observed")
    opportunity = "yes" if opportunity_value is True else ("no" if opportunity_value is False else "n.d.")
    lines = [
        "# OWTV Show News Urgency Audit",
        "",
        f"Generated: {payload['generated_at']}",
        f"Window: {payload['hours']}h",
        f"Status: **{payload['status']}**",
        "",
        "## Summary",
        "",
        f"- Runs observed: {payload['runs']}",
        f"- Urgency observability coverage: {coverage.get('urgency_supported_runs', 0)}/{coverage.get('runs_in_window', 0)} runs",
        f"- News published in window: {ceiling['published_unique_last_window'] if ceiling['published_unique_last_window'] is not None else 'n.d.'}",
        f"- News published today ({ceiling['timezone']}): {ceiling['published_today_local'] if ceiling['published_today_local'] is not None else 'n.d.'} / {ceiling['limit']}",
        f"- Show/event opportunity observed: {opportunity}",
        f"- Show/event identities: {urgency['show_identity_unique_urls']}",
        f"- Urgency promotions: {urgency['promoted_unique_urls']}",
        f"- Urgency publications with provenance: {urgency['published_with_provenance_unique_urls']}",
        f"- Eligible-looking pending deferrals: {urgency['pending_eligible_unique_urls']}",
        f"- Capacity skips: {ceiling['skipped_capacity_unique_urls']}",
        f"- Daily-ceiling skips: {ceiling['daily_ceiling_skips_unique_urls']}",
        "",
        "## Checks",
        "",
        f"- Daily ceiling respected: {mark(checks['daily_ceiling_respected'])}",
        f"- No urgency after corresponding report: {mark(checks['no_post_report_urgency'])}",
        f"- Urgency provenance preserved to Publisher: {mark(checks['urgency_provenance_preserved'])}",
    ]
    if payload.get("warnings"):
        lines += ["", "## Diagnostic warnings", ""] + [f"- {warning}" for warning in payload["warnings"]]
    if urgency["urgency_after_report_urls"]:
        lines += ["", "## Urgency after report", ""] + [f"- {url}" for url in urgency["urgency_after_report_urls"]]
    if urgency["lost_provenance_urls"]:
        lines += ["", "## Lost provenance", ""] + [f"- {url}" for url in urgency["lost_provenance_urls"]]
    if urgency["promoted_urls"]:
        lines += ["", "## Promoted URLs", ""] + [f"- {url}" for url in urgency["promoted_urls"]]
    if urgency["pending_eligible_urls"]:
        lines += ["", "## Eligible-looking pending URLs", ""] + [f"- {url}" for url in urgency["pending_eligible_urls"]]
    return "\n".join(lines) + "\n"


def generate_outputs(
    *,
    root: Path = ROOT,
    hours: int = 24,
    now: datetime | None = None,
) -> dict[str, Path | dict[str, Any]]:
    payload = build_audit(root=root, hours=hours, now=now)
    current = _parse_datetime(payload["generated_at"]) or datetime.now(timezone.utc)
    stamp = current.strftime("%Y%m%d_%H%M%S")
    reports_dir = root / "reports"
    latest_json = root / "state" / "reports" / "owtv_show_news_urgency_audit_latest.json"
    reports_dir.mkdir(parents=True, exist_ok=True)
    latest_json.parent.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"owtv_show_news_urgency_audit_{hours}h_{stamp}.json"
    markdown_path = reports_dir / f"owtv_show_news_urgency_audit_{hours}h_{stamp}.md"
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    json_path.write_text(text, encoding="utf-8")
    latest_json.write_text(text, encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return {"payload": payload, "json": json_path, "markdown": markdown_path, "latest_json": latest_json}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit for show-news urgency and daily publication ceiling.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    outputs = generate_outputs(root=args.root, hours=args.hours)
    payload = outputs["payload"]
    assert isinstance(payload, dict)
    print(render_markdown(payload), end="")
    print(f"JSON: {outputs['json']}")
    print(f"Markdown: {outputs['markdown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
