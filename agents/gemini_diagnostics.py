from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from decimal import Decimal, InvalidOperation

from agents.gemini_ledger import PRICING_FORMULA_VERSION, USAGE_CONTRACT_VERSION

ROOT = Path(__file__).resolve().parents[1]
LEDGER_FILE = ROOT / "state" / "newsroom" / "gemini_call_ledger.jsonl"
MENZO_CACHE_FILE = ROOT / "state" / "newsroom" / "menzo_duplicate_arbitration_cache_v2.json"
MENZO_DECISIONS_FILES = (
    ROOT / "state" / "newsroom" / "menzo_decisions_latest.json",
    ROOT / "artifacts" / "newsroom" / "menzo_decisions.json",
)

REASON_FIELDS = ("reason", "purpose", "phase", "task", "selected_model_chain_reason")
MODEL_FIELDS = ("actual_model", "model_requested", "model", "selected_model", "translation_model")
AGENT_FIELDS = ("agent", "stage", "caller")

MENZO_V9518_INT_FIELDS = (
    "same_run_pairs_theoretical",
    "same_run_exact_duplicates",
    "same_run_pairs_below_threshold",
    "same_run_pairs_above_threshold",
    "same_run_suspicious_components",
    "same_run_candidates_sent_to_gemini",
    "recent_history_candidates",
    "recent_history_publications_12h",
    "recent_history_pairs_theoretical",
    "recent_history_exact_duplicates",
    "recent_history_pairs_below_threshold",
    "recent_history_pairs_above_threshold",
    "recent_history_candidates_sent_to_gemini",
    "recent_history_publications_sent_to_gemini",
    "duplicate_cache_hits",
    "duplicate_cache_misses",
    "gemini_duplicate_calls_planned",
    "gemini_duplicate_calls_executed",
    "gemini_duplicate_calls_avoided",
    "duplicate_suspicion_audit_omitted",
    "menzo_duplicate_arbitration_fail_closed",
    "menzo_recent_history_material_updates",
)

MENZO_V9518_META_FIELDS = (
    "duplicate_scorer_version",
    "duplicate_suspect_threshold",
    "gemini_duplicate_input_tokens",
    "gemini_duplicate_output_tokens",
    "gemini_duplicate_estimated_cost",
)


def _first(record: dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = record.get(field)
        if value is not None and str(value).strip():
            return str(value).strip()
    return "unknown"


def reason_or_purpose(record: dict[str, Any]) -> str:
    return _first(record, REASON_FIELDS)


def model_name(record: dict[str, Any]) -> str:
    return _first(record, MODEL_FIELDS)


def agent_name(record: dict[str, Any]) -> str:
    return _first(record, AGENT_FIELDS)


def status_name(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "").strip().lower()
    if status in {"called", "avoided", "failed"}:
        return status
    if record.get("saved_gemini_call") is True:
        return "avoided"
    return "unknown"


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def load_ledger(
    path: Path = LEDGER_FILE,
    *,
    hours: int = 24,
    now: datetime | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    strict_bounded: bool = False,
    return_metadata: bool = False,
) -> Any:
    warnings: list[str] = []
    metadata = {"readable": False, "valid_rows": 0, "malformed_rows": 0, "undated_rows": 0}
    if not path.exists():
        result = ([], [f"ledger file missing: {path}"])
        return (*result, metadata) if return_metadata else result
    cutoff = since or ((now or datetime.now(timezone.utc)) - timedelta(hours=hours))
    upper = until
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        metadata["readable"] = True
        for idx, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except Exception as exc:
                warnings.append(f"invalid ledger JSON line {idx}: {exc}")
                metadata["malformed_rows"] += 1
                continue
            if not isinstance(data, dict):
                metadata["malformed_rows"] += 1
                continue
            ts = parse_dt(data.get("timestamp") or data.get("generated_at") or data.get("started_at"))
            if ts is None:
                metadata["undated_rows"] += 1
                if not strict_bounded:
                    records.append(data)
                continue
            if ts >= cutoff and (upper is None or ts <= upper):
                records.append(data)
                metadata["valid_rows"] += 1
    except Exception as exc:
        result = ([], [f"ledger read failed: {exc}"])
        return (*result, metadata) if return_metadata else result
    result = (records, warnings)
    return (*result, metadata) if return_metadata else result


def normalize_title(title: Any) -> str:
    text = re.sub(r"\s+", " ", str(title or "").strip().lower())
    text = re.sub(r"[^a-z0-9à-ÿ ]+", "", text)
    return text or "unknown"


def _counter(records: list[dict[str, Any]], *parts: str) -> Counter[str]:
    c: Counter[str] = Counter()
    for r in records:
        vals = []
        for part in parts:
            vals.append({"model": model_name, "agent": agent_name, "reason": reason_or_purpose, "status": status_name}[part](r))
        c[" × ".join(vals)] += 1
    return c



def _top_titles(records: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        display_identity = (
            record.get("title")
            or record.get("candidate_title")
            or record.get("current_url")
            or record.get("url")
            or record.get("cluster_id")
            or reason_or_purpose(record)
        )
        grouped[normalize_title(display_identity)].append(record)

    rows = []
    for key, items in grouped.items():
        times = [
            str(item.get("timestamp") or "")
            for item in items
            if item.get("timestamp")
        ]
        rows.append(
            {
                "title": key[:120],
                "called_count": len(items),
                "models": sorted({model_name(item) for item in items}),
                "agents": sorted({agent_name(item) for item in items}),
                "reasons": sorted({reason_or_purpose(item) for item in items}),
                "first_timestamp": min(times) if times else "",
                "last_timestamp": max(times) if times else "",
            }
        )

    return sorted(
        rows,
        key=lambda row: (-int(row["called_count"]), str(row["title"])),
    )[:limit]


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _usage_evidence_resolved(record: dict[str, Any]) -> bool:
    if record.get("ledger_schema_version") == "v3":
        return record.get("usage_resolution_status") == "resolved"
    if record.get("ledger_schema_version") != "v2" or record.get("usage_available") is not True:
        return False
    warning = str(record.get("usage_warning") or "")
    if "malformed_" in warning or "usage_metadata_all_token_fields_malformed" in warning:
        return False
    prompt = _coerce_int(record.get("input_tokens"))
    output = _coerce_int(record.get("output_tokens"))
    return prompt is not None and output is not None and prompt >= 0 and output >= 0


def _resolved_cost_row(record: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    if record.get("ledger_schema_version") != "v3" or record.get("cost_resolution_status") != "resolved":
        return None, None
    required = {
        "provider_attempt_id": record.get("provider_attempt_id"),
        "usage_contract_version": record.get("usage_contract_version") == USAGE_CONTRACT_VERSION,
        "pricing_formula_version": record.get("pricing_formula_version") == PRICING_FORMULA_VERSION,
        "pricing_currency": record.get("pricing_currency"),
        "price_table_version": record.get("price_table_version"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return None, "resolved_row_integrity_missing:" + ",".join(missing)
    try:
        value = Decimal(str(record.get("computed_list_price_cost")))
    except (InvalidOperation, ValueError, TypeError):
        return None, "resolved_row_integrity_invalid_cost"
    if not value.is_finite() or value < 0:
        return None, "resolved_row_integrity_invalid_cost"
    components: list[Decimal] = []
    for field in ("computed_non_cached_input_cost", "computed_cached_input_cost",
                  "computed_candidate_output_cost", "computed_thinking_cost"):
        try:
            component = Decimal(str(record.get(field)))
        except (InvalidOperation, ValueError, TypeError):
            return None, "resolved_row_integrity_invalid_component"
        if not component.is_finite() or component < 0:
            return None, "resolved_row_integrity_invalid_component"
        components.append(component)
    if value != sum(components, Decimal("0")):
        return None, "resolved_row_integrity_component_mismatch"
    return value, None


def build_gemini_economic_truth(records: list[dict[str, Any]], *, available: bool = False) -> dict[str, Any]:
    """Canonical bounded provider-attempt economic read model (never deduplicated)."""
    invalid_v3_status_rows = [r for r in records if r.get("ledger_schema_version") == "v3" and str(r.get("status") or "").strip().lower() not in {"called", "failed", "avoided"}]
    provider_attempt_counts = Counter(str(r.get("provider_attempt_id")).strip() for r in records
                                      if r.get("ledger_schema_version") == "v3" and str(r.get("provider_attempt_id") or "").strip())
    duplicate_attempt_counts = {key: count for key, count in provider_attempt_counts.items() if count > 1}
    available = bool(available and not invalid_v3_status_rows and not duplicate_attempt_counts)
    real = [r for r in records if status_name(r) in {"called", "failed"}]
    usage_resolved = [r for r in real if _usage_evidence_resolved(r)]
    resolved_values: dict[int, Decimal] = {}
    integrity_reasons: Counter[str] = Counter()
    for r in real:
        value, integrity_reason = _resolved_cost_row(r)
        if value is not None:
            resolved_values[id(r)] = value
        elif integrity_reason:
            integrity_reasons[integrity_reason] += 1
    cost_resolved = [r for r in real if id(r) in resolved_values]
    known = Decimal(0)
    for r in cost_resolved:
        known += resolved_values[id(r)]
    def breakdown(key):
        result = {}
        for r in real:
            name = key(r)
            item = result.setdefault(name, {"attempts": 0, "usage_resolved": 0, "cost_resolved": 0, "unknown_cost": 0, "known_computed_list_price_cost": Decimal(0)})
            item["attempts"] += 1
            if r in usage_resolved: item["usage_resolved"] += 1
            if r in cost_resolved:
                item["cost_resolved"] += 1; item["known_computed_list_price_cost"] += resolved_values[id(r)]
            else: item["unknown_cost"] += 1
        for item in result.values(): item["known_computed_list_price_cost"] = format(item["known_computed_list_price_cost"], "f")
        return dict(sorted(result.items()))
    currencies = {r.get("pricing_currency") for r in cost_resolved if r.get("pricing_currency")}
    versions = sorted({str(r.get("price_table_version")) for r in cost_resolved})
    complete = available and len(cost_resolved) == len(real) and len(currencies) <= 1
    reason_counts = Counter(str(r.get("cost_resolution_reason") or ("legacy_pre_v96_2_cost_contract" if r.get("ledger_schema_version") != "v3" else "usage_missing")) for r in real)
    diagnostics = {
        "actual_model_populated": sum(bool(r.get("actual_model")) for r in real), "requested_model_populated": sum(bool(r.get("model_requested")) for r in real),
        "cached_token_rows": sum(r.get("cached_input_tokens") is not None for r in real), "cached_token_nonzero_rows": sum((_coerce_int(r.get("cached_input_tokens")) or 0) > 0 for r in real),
        "thinking_token_rows": sum(r.get("thinking_tokens") is not None for r in real), "thinking_token_nonzero_rows": sum((_coerce_int(r.get("thinking_tokens")) or 0) > 0 for r in real),
        "failed_with_usage": sum(status_name(r)=="failed" and r.get("usage_resolution_status")=="resolved" for r in real), "failed_without_usage": sum(status_name(r)=="failed" and r.get("usage_resolution_status")!="resolved" for r in real),
        "retry_attempts": sum(r.get("retry") is True for r in real), "fallback_attempts": sum(r.get("fallback") is True for r in real), "repair_attempts": sum(r.get("repair") is True for r in real),
        "unknown_model_identities": sorted({model_name(r) for r in real if r.get("cost_resolution_reason") == "model_unresolved"}), "resolution_reasons": dict(sorted(reason_counts.items())),
        "economic_row_integrity_reasons": dict(sorted(integrity_reasons.items())),
        "invalid_v3_status_rows": len(invalid_v3_status_rows),
        "duplicate_provider_attempt_ids": len(duplicate_attempt_counts),
        "duplicate_provider_attempt_rows": sum(duplicate_attempt_counts.values())}
    if not available:
        return {"available": False, "coverage": "unavailable", "complete_window": False, "source": "state/newsroom/gemini_call_ledger.jsonl",
                "pricing_basis": "paid_tier_standard_list_price", "currency": None, "price_table_version": None, "price_table_versions": [],
                "pricing_formula_version": PRICING_FORMULA_VERSION, "usage_contract_version": USAGE_CONTRACT_VERSION,
                "real_attempts": None, "provider_usage_resolved_attempts": None, "provider_usage_coverage": None,
                "computed_cost_resolved_attempts": None, "computed_cost_coverage": None, "unknown_computed_cost_attempts": None,
                "known_computed_list_price_cost": None, "complete_window_computed_list_price_cost": None,
                "breakdowns": {}, "diagnostics": diagnostics}
    return {"available": True, "coverage": "full" if complete else "partial", "complete_window": complete, "source": "state/newsroom/gemini_call_ledger.jsonl",
            "pricing_basis": "paid_tier_standard_list_price", "currency": (next(iter(currencies)) if len(currencies) == 1 else ("mixed" if currencies else None)),
            "price_table_version": (versions[0] if len(versions) == 1 else ("mixed" if versions else None)), "price_table_versions": versions,
            "pricing_formula_version": PRICING_FORMULA_VERSION, "usage_contract_version": USAGE_CONTRACT_VERSION,
            "real_attempts": len(real), "provider_usage_resolved_attempts": len(usage_resolved), "provider_usage_coverage": len(usage_resolved)/len(real) if real else None,
            "computed_cost_resolved_attempts": len(cost_resolved), "computed_cost_coverage": len(cost_resolved)/len(real) if real else None,
            "unknown_computed_cost_attempts": len(real)-len(cost_resolved), "known_computed_list_price_cost": format(known, "f"),
            "complete_window_computed_list_price_cost": format(known, "f") if complete else None,
            "breakdowns": {"by_model": breakdown(model_name), "by_agent": breakdown(agent_name), "by_reason": breakdown(reason_or_purpose)}, "diagnostics": diagnostics}



def _extract_menzo_postprocess(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None

    postprocess = (
        data.get("postprocess")
        if isinstance(data.get("postprocess"), dict)
        else data
    )

    legacy_int_fields = (
        "duplicate_arbitration_cache_hit",
        "duplicate_arbitration_cache_miss",
        "duplicate_arbitration_cache_expired",
        "gemini_calls_avoided_by_duplicate_arbitration_cache",
    )

    found: dict[str, Any] = {}

    for key in legacy_int_fields + MENZO_V9518_INT_FIELDS:
        value = _coerce_int(postprocess.get(key))
        if value is not None:
            found[key] = value

    for key in MENZO_V9518_META_FIELDS:
        value = postprocess.get(key)
        if value is not None and value != "":
            found[key] = value

    return found or None


def load_menzo_postprocess(
    context: dict[str, Any] | None = None,
    paths: tuple[Path, ...] = MENZO_DECISIONS_FILES,
) -> dict[str, Any]:
    """Load latest Menzo postprocess cache counters without making them look like 24h ledger counts."""
    sources: list[tuple[str, Any]] = []
    if context:
        sources.append(("archivista_context", context))
    for path in paths:
        try:
            if path.exists():
                sources.append((str(path), json.loads(path.read_text(encoding="utf-8"))))
        except Exception as exc:
            return {"available": False, "source": str(path), "warnings": [f"Menzo postprocess read/parse warning: {exc}"]}
    for source, data in sources:
        counters = _extract_menzo_postprocess(data)
        if counters is not None:
            return {"available": True, "source": source, "counters": counters, "warnings": []}
    return {"available": False, "source": "not_available", "counters": {}, "warnings": []}

def load_menzo_cache(path: Path = MENZO_CACHE_FILE, *, now: datetime | None = None) -> dict[str, Any]:
    out = {"cache_contract": "active_v2", "present": path.exists(), "warnings": [], "entries_total": 0,
           "failures_total": 0, "contract_fingerprint": "", "load_status": "missing", "newest": []}
    if not path.exists():
        return out
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        out["warnings"].append(f"cache read/parse warning: {exc}")
        return out
    if not isinstance(data, dict) or data.get("schema_version") != "2":
        out["load_status"]="obsolete_or_invalid_schema"; return out
    out["load_status"]="loaded"; out["contract_fingerprint"]=str(data.get("contract_fingerprint") or "")
    out["failures_total"]=len(data.get("failures",{})) if isinstance(data.get("failures"),dict) else 0
    entries = data.get("entries",{}).values() if isinstance(data.get("entries"),dict) else []
    rows = [e for e in entries if isinstance(e, dict)]
    out["entries_total"] = len(rows)
    # v2 is content/contract addressed. Legacy TTL labels are deliberately not
    # emitted because they do not describe active reuse decisions.
    rows.sort(key=lambda e: str(e.get("stored_at") or ""), reverse=True)
    out["newest"] = [{k: str(e.get(k) or "")[:120] for k in ("stored_at", "scope", "outcome", "contract_fingerprint")} for e in rows[:5]]
    return out



def build_gemini_diagnostics(
    records: list[dict[str, Any]],
    cache_path: Path = MENZO_CACHE_FILE,
    menzo_context: dict[str, Any] | None = None,
    menzo_decisions_paths: tuple[Path, ...] = MENZO_DECISIONS_FILES,
    economic_available: bool = False,
) -> dict[str, Any]:
    called = [record for record in records if status_name(record) == "called"]
    avoided = [record for record in records if status_name(record) == "avoided"]
    failed = [record for record in records if status_name(record) == "failed"]

    called35 = [record for record in called if "3.5" in model_name(record)]
    failed35 = [record for record in failed if "3.5" in model_name(record)]
    attempted35 = called35 + failed35

    real_attempts = [
        record
        for record in records
        if status_name(record) in {"called", "failed"}
    ]
    v2_real = [
        record
        for record in real_attempts
        if record.get("ledger_schema_version") == "v2"
    ]
    real_with_usage = [
        record for record in v2_real if record.get("usage_available") is True
    ]
    real_with_cost = [
        record for record in v2_real if record.get("estimated_cost") is not None
    ]

    avoided35 = [record for record in avoided if "3.5" in model_name(record)]

    ledger_cache_hits = sum(
        1
        for record in avoided
        if reason_or_purpose(record) == "duplicate_arbitration_cache_hit"
    )

    menzo_postprocess = load_menzo_postprocess(
        menzo_context,
        menzo_decisions_paths,
    )
    latest_counters = (
        menzo_postprocess.get("counters", {})
        if isinstance(menzo_postprocess.get("counters"), dict)
        else {}
    )
    not_available = "not_available"
    v9518_fields = MENZO_V9518_INT_FIELDS + MENZO_V9518_META_FIELDS
    v9518_snapshot = {
        key: latest_counters.get(key, not_available)
        for key in v9518_fields
    }
    v9518_available = any(key in latest_counters for key in v9518_fields)

    economic = build_gemini_economic_truth(records, available=economic_available)
    shadow_available = bool(economic.get("available"))
    shadow_rows = [r for r in records if r.get("workload") == "editorial_director_shadow"]
    shadow_real = [r for r in shadow_rows if status_name(r) in {"called", "failed"}]
    shadow_logical = {str(r.get("logical_request_id")) for r in shadow_real if r.get("logical_request_id")}
    shadow_cost_rows = [_resolved_cost_row(r)[0] for r in shadow_real]
    shadow_cost_known = [x for x in shadow_cost_rows if x is not None]
    evaluated_occurrences = sum(int(r.get("candidate_count") or 0) for r in shadow_real if int(r.get("attempt_index") or 0) == 0)
    complete = shadow_available and len(shadow_cost_known) == len(shadow_real)
    shadow_cost = sum(shadow_cost_known, Decimal("0"))
    available_value = lambda value: value if shadow_available else None
    shadow = {
        "source_available": shadow_available,
        "logical_requests": available_value(len(shadow_logical)), "provider_attempts": available_value(len(shadow_real)),
        "primary_attempts": available_value(sum(not bool(r.get("repair")) for r in shadow_real)),
        "repairs": available_value(sum(bool(r.get("repair")) for r in shadow_real)),
        "fallbacks": available_value(sum(bool(r.get("fallback")) for r in shadow_real)),
        "input_tokens": (sum(int(r.get("input_tokens") or 0) for r in shadow_real)
                         if shadow_available and all(_usage_evidence_resolved(r) for r in shadow_real) else None),
        "output_tokens": (sum(int(r.get("output_tokens") or 0) for r in shadow_real)
                          if shadow_available and all(_usage_evidence_resolved(r) for r in shadow_real) else None),
        "known_cost": format(shadow_cost, "f") if shadow_available else None,
        "known_cost_semantics": "partial_known_cost" if shadow_available and not complete else ("complete" if complete else None),
        "complete_window_cost": format(shadow_cost, "f") if complete else None,
        "cost_per_logical_request": format(shadow_cost / len(shadow_logical), "f") if complete and shadow_logical else None,
        "cost_per_evaluated_candidate_occurrence": format(shadow_cost / evaluated_occurrences, "f") if complete and evaluated_occurrences else None,
        "by_phase": dict(Counter(str(r.get("phase") or "unknown") for r in shadow_real)) if shadow_available else None,
        "bound_status": None,
        "bound_status_availability": "partial_latest_run_only_not_authoritative_window",
    }
    return {
        "economic": economic,
        "editorial_director_shadow": shadow,
        **{k: economic[k] for k in ("provider_usage_resolved_attempts", "provider_usage_coverage", "computed_cost_resolved_attempts", "computed_cost_coverage", "unknown_computed_cost_attempts", "known_computed_list_price_cost", "complete_window_computed_list_price_cost")},
        "real_attempts": len(real_attempts),
        "completed_calls": len(called),
        "completed_successful_calls": len(called),  # deprecated compatibility alias
        "failures": len(failed),
        "avoided_calls": len(avoided),
        "fallbacks": sum(
            1 for record in real_attempts if record.get("fallback") is True
        ),
        "gemini_3_5_attempts": len(attempted35),
        "gemini_3_5_completed_calls": len(called35),
        "gemini_3_5_completed_successful_calls": len(called35),  # deprecated compatibility alias
        "gemini_3_5_failures": len(failed35),
        "gemini_3_5_avoided_calls": len(avoided35),
        "called_total": len(called),
        "avoided_total": len(avoided),
        "failed_total": len(failed),
        "called_by_model_agent": dict(_counter(called, "model", "agent")),
        "called_by_model_agent_reason": dict(
            _counter(called, "model", "agent", "reason")
        ),
        "called_by_agent_reason": dict(_counter(called, "agent", "reason")),
        "called_35_total": len(called35),
        "called_35_rows": [
            {
                "timestamp": str(record.get("timestamp") or ""),
                "agent": agent_name(record),
                "reason_or_purpose": reason_or_purpose(record),
                "title": str(
                    record.get("title")
                    or record.get("candidate_title")
                    or record.get("current_url")
                    or record.get("url")
                    or record.get("cluster_id")
                    or reason_or_purpose(record)
                )[:120],
                "url": str(record.get("url") or "")[:180],
                "run_id": str(record.get("run_id") or ""),
            }
            for record in called35[:50]
        ],
        "called_35_by_agent": dict(_counter(called35, "agent")),
        "called_35_by_reason": dict(_counter(called35, "reason")),
        "failed_35_total": len(failed35),
        "failed_35_by_agent": dict(_counter(failed35, "agent")),
        "failed_35_by_reason": dict(_counter(failed35, "reason")),
        "attempted_35_total": len(attempted35),
        "avoided_35_total": len(avoided35),
        "avoided_35_by_reason": dict(_counter(avoided35, "reason")),
        "avoided_by_agent": dict(_counter(avoided, "agent")),
        "avoided_by_agent_reason": dict(
            _counter(avoided, "agent", "reason")
        ),
        "duplicate_arbitration_cache_hit": ledger_cache_hits,
        "ledger_duplicate_arbitration_cache_hit_24h": ledger_cache_hits,
        "ledger_duplicate_arbitration_cache_hit_window": ledger_cache_hits,
        "purpose_gate_not_met": sum(
            1
            for record in avoided
            if reason_or_purpose(record) == "purpose_gate_not_met"
        ),
        "deterministic_novelty_allow": sum(
            1
            for record in avoided
            if reason_or_purpose(record) == "deterministic_novelty_allow"
        ),
        "high_ambiguity_gate_not_met": sum(
            1
            for record in avoided
            if reason_or_purpose(record) == "high_ambiguity_gate_not_met"
        ),
        "menzo_postprocess": menzo_postprocess,
        "menzo_v9518_available": v9518_available,
        "menzo_v9518_snapshot": v9518_snapshot,
        "menzo_latest_cache_hit": latest_counters.get(
            "duplicate_arbitration_cache_hit",
            not_available,
        ),
        "menzo_latest_cache_miss": latest_counters.get(
            "duplicate_arbitration_cache_miss",
            not_available,
        ),
        "menzo_latest_cache_expired": latest_counters.get(
            "duplicate_arbitration_cache_expired",
            not_available,
        ),
        "menzo_latest_cache_avoided": latest_counters.get(
            "gemini_calls_avoided_by_duplicate_arbitration_cache",
            not_available,
        ),
        "menzo_cache_miss": latest_counters.get(
            "duplicate_arbitration_cache_miss",
            not_available,
        ),
        "menzo_cache_expired": latest_counters.get(
            "duplicate_arbitration_cache_expired",
            not_available,
        ),
        "menzo_cache": load_menzo_cache(cache_path),
        "v2_real_attempts": len(v2_real),
        "real_attempts_with_usage": len(real_with_usage),
        "real_attempts_with_cost": len(real_with_cost),
        "usage_coverage": (
            len(real_with_usage) / len(v2_real)
            if v2_real
            else None
        ),
        "pricing_coverage": (
            len(real_with_cost) / len(v2_real)
            if v2_real
            else None
        ),
        "top_repeated_titles": _top_titles(called),
        "top_repeated_35_titles": _top_titles(called35),
    }


def _fmt_counter(counter: dict[str, int], limit: int = 30) -> list[str]:
    if not counter:
        return ["- none"]
    return [f"- {k}: {v}" for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]



def render_gemini_diagnostics_markdown(
    diag: dict[str, Any],
    *,
    hours: int = 24,
) -> str:
    economic = diag.get("economic") or {}
    fmt = lambda value: "n.d." if value is None else str(value)
    pct = lambda value: "n.d." if value is None else f"{value:.1%}"
    lines = [
        f"## Gemini Economic Authority and Non-Authoritative Diagnostics {hours}h",
        "",
        "### AUTHORITATIVE Gemini economic truth",
        f"- available: {'yes' if economic.get('available') else 'no'}",
        f"- real provider attempts: {fmt(economic.get('real_attempts') if economic.get('available') else None)}",
        f"- provider usage coverage: {pct(economic.get('provider_usage_coverage'))}",
        f"- computed cost coverage: {pct(economic.get('computed_cost_coverage'))}",
        f"- known computed paid-tier Standard list-price cost: {fmt(economic.get('known_computed_list_price_cost'))} {economic.get('currency') or 'n.d.'}",
        f"- complete-window computed list-price cost: {fmt(economic.get('complete_window_computed_list_price_cost'))} {economic.get('currency') or 'n.d.'}",
        f"- unknown-cost attempts: {fmt(economic.get('unknown_computed_cost_attempts') if economic.get('available') else None)}",
        f"- price-table version evidence: {economic.get('price_table_version') or 'n.d.'}",
        "",
        "### NON-AUTHORITATIVE legacy call and usage diagnostics",
        "",
        "### Gemini called by model × agent",
    ]

    lines += _fmt_counter(diag.get("called_by_model_agent", {}))
    lines += [
        "",
        "### Gemini called by model × agent × reason_or_purpose",
    ] + _fmt_counter(diag.get("called_by_model_agent_reason", {}))
    lines += [
        "",
        "### Gemini called by agent × reason_or_purpose",
    ] + _fmt_counter(diag.get("called_by_agent_reason", {}))

    lines += [
        "",
        "### Gemini 3.5 Flash attempts",
        f"- 3.5 attempts total: {diag.get('attempted_35_total', 0)}",
        f"- 3.5 successful calls: {diag.get('called_35_total', 0)}",
        f"- 3.5 failed attempts: {diag.get('failed_35_total', 0)}",
        "- 3.5 called by agent:",
    ]
    lines += [
        "  " + line
        for line in _fmt_counter(diag.get("called_35_by_agent", {}))
    ]
    lines += ["- 3.5 called by reason_or_purpose:"]
    lines += [
        "  " + line
        for line in _fmt_counter(diag.get("called_35_by_reason", {}))
    ]
    lines += ["- 3.5 failed by agent:"]
    lines += [
        "  " + line
        for line in _fmt_counter(diag.get("failed_35_by_agent", {}))
    ]
    lines += ["- 3.5 failed by reason_or_purpose:"]
    lines += [
        "  " + line
        for line in _fmt_counter(diag.get("failed_35_by_reason", {}))
    ]
    lines += [
        f"- 3.5 avoided total: {diag.get('avoided_35_total', 0)}",
        "- 3.5 avoided by reason_or_purpose:",
    ]
    lines += [
        "  " + line
        for line in _fmt_counter(diag.get("avoided_35_by_reason", {}))
    ]

    for row in diag.get("called_35_rows", []):
        lines.append(
            f"- {row['timestamp']} | {row['agent']} | "
            f"{row['reason_or_purpose']} | {row['title']} | "
            f"{row['url']} | run_id={row['run_id']}"
        )

    lines += [
        "",
        "### Gemini avoided calls",
        f"- avoided total: {diag.get('avoided_total', 0)}",
        "- avoided by agent:",
    ]
    lines += [
        "  " + line
        for line in _fmt_counter(diag.get("avoided_by_agent", {}))
    ]
    lines += ["- avoided by agent × reason_or_purpose:"]
    lines += [
        "  " + line
        for line in _fmt_counter(diag.get("avoided_by_agent_reason", {}))
    ]

    for key in (
        "duplicate_arbitration_cache_hit",
        "purpose_gate_not_met",
        "deterministic_novelty_allow",
        "high_ambiguity_gate_not_met",
    ):
        lines.append(f"- {key}: {diag.get(key, 0)}")

    snapshot = diag.get("menzo_v9518_snapshot", {}) or {}
    post = diag.get("menzo_postprocess", {}) or {}

    lines += [
        "",
        "### Menzo Duplicate Gate v95.18 — latest run snapshot",
    ]

    if not diag.get("menzo_v9518_available"):
        lines += [
            "- available: no",
            f"- source: {post.get('source', 'not_available')}",
        ]
    else:
        lines += [
            "- available: yes",
            f"- source: {post.get('source', 'not_available')}",
            f"- scorer version: "
            f"{snapshot.get('duplicate_scorer_version', 'not_available')}",
            f"- effective threshold: "
            f"{snapshot.get('duplicate_suspect_threshold', 'not_available')}",
            "",
            "#### Same-run gate",
            f"- theoretical pairs: "
            f"{snapshot.get('same_run_pairs_theoretical', 'not_available')}",
            f"- exact duplicates: "
            f"{snapshot.get('same_run_exact_duplicates', 'not_available')}",
            f"- below threshold: "
            f"{snapshot.get('same_run_pairs_below_threshold', 'not_available')}",
            f"- above threshold: "
            f"{snapshot.get('same_run_pairs_above_threshold', 'not_available')}",
            f"- suspicious components: "
            f"{snapshot.get('same_run_suspicious_components', 'not_available')}",
            f"- candidates sent to Gemini: "
            f"{snapshot.get('same_run_candidates_sent_to_gemini', 'not_available')}",
            "",
            "#### Recent-history gate",
            f"- current candidates: "
            f"{snapshot.get('recent_history_candidates', 'not_available')}",
            f"- authoritative publications in lookback: "
            f"{snapshot.get('recent_history_publications_12h', 'not_available')}",
            f"- theoretical pairs: "
            f"{snapshot.get('recent_history_pairs_theoretical', 'not_available')}",
            f"- exact duplicates: "
            f"{snapshot.get('recent_history_exact_duplicates', 'not_available')}",
            f"- below threshold: "
            f"{snapshot.get('recent_history_pairs_below_threshold', 'not_available')}",
            f"- above threshold: "
            f"{snapshot.get('recent_history_pairs_above_threshold', 'not_available')}",
            f"- candidates sent to Gemini: "
            f"{snapshot.get('recent_history_candidates_sent_to_gemini', 'not_available')}",
            f"- publications sent to Gemini: "
            f"{snapshot.get('recent_history_publications_sent_to_gemini', 'not_available')}",
            "",
            "#### Arbitration and cache",
            f"- cache hits: "
            f"{snapshot.get('duplicate_cache_hits', 'not_available')}",
            f"- cache misses: "
            f"{snapshot.get('duplicate_cache_misses', 'not_available')}",
            f"- Gemini calls planned: "
            f"{snapshot.get('gemini_duplicate_calls_planned', 'not_available')}",
            f"- Gemini calls executed: "
            f"{snapshot.get('gemini_duplicate_calls_executed', 'not_available')}",
            f"- Gemini calls avoided: "
            f"{snapshot.get('gemini_duplicate_calls_avoided', 'not_available')}",
            f"- material updates allowed: "
            f"{snapshot.get('menzo_recent_history_material_updates', 'not_available')}",
            f"- fail-closed units: "
            f"{snapshot.get('menzo_duplicate_arbitration_fail_closed', 'not_available')}",
            f"- audit records omitted: "
            f"{snapshot.get('duplicate_suspicion_audit_omitted', 'not_available')}",
            f"- measured input tokens: "
            f"{snapshot.get('gemini_duplicate_input_tokens', 'not_available')}",
            f"- measured output tokens: "
            f"{snapshot.get('gemini_duplicate_output_tokens', 'not_available')}",
            f"- measured estimated cost: "
            f"{snapshot.get('gemini_duplicate_estimated_cost', 'not_available')}",
        ]

    cache = diag.get("menzo_cache", {}) or {}

    lines += [
        "",
        "### Menzo duplicate arbitration cache (active v2)",
        f"- cache file present: {'yes' if cache.get('present') else 'no'}",
        f"- cache contract: {cache.get('cache_contract', 'not_available')}",
        f"- load status: {cache.get('load_status', 'not_available')}",
        f"- cache entries total: {cache.get('entries_total', 0)}",
        f"- cache failures total: {cache.get('failures_total', 0)}",
        f"- contract fingerprint: {cache.get('contract_fingerprint', 'not_available')}",
    ]

    for entry in cache.get("newest", []):
        lines.append(
            f"- newest: {entry.get('stored_at')} | "
            f"{entry.get('scope')} | "
            f"{entry.get('outcome')} | "
            f"{entry.get('contract_fingerprint')}"
        )

    lines += [
        "",
        "### Legacy cache-counter compatibility diagnostics",
        f"- {hours}h ledger duplicate_arbitration_cache_hit avoided records: "
        f"{diag.get('ledger_duplicate_arbitration_cache_hit_window', 0)}",
        f"- latest Menzo run cache counters source: "
        f"{post.get('source', 'not_available')}",
        f"- latest Menzo run duplicate_arbitration_cache_hit: "
        f"{diag.get('menzo_latest_cache_hit', 'not_available')}",
        f"- latest Menzo run duplicate_arbitration_cache_miss: "
        f"{diag.get('menzo_latest_cache_miss', 'not_available')}",
        f"- latest Menzo run duplicate_arbitration_cache_expired: "
        f"{diag.get('menzo_latest_cache_expired', 'not_available')}",
        f"- latest Menzo run gemini_calls_avoided_by_duplicate_arbitration_cache: "
        f"{diag.get('menzo_latest_cache_avoided', 'not_available')}",
    ]

    for warning in cache.get("warnings", []):
        lines.append(f"- warning: {warning}")

    for warning in post.get("warnings", []):
        lines.append(f"- warning: {warning}")

    lines += ["", "### Top repeated Gemini titles"]

    for label, rows in (
        ("called", diag.get("top_repeated_titles", [])),
        ("3.5 called", diag.get("top_repeated_35_titles", [])),
    ):
        lines.append(f"- {label}:")
        for row in rows:
            lines.append(
                f"  - {row['called_count']} | {row['title']} | "
                f"models={','.join(row['models'])} | "
                f"agents={','.join(row['agents'])} | "
                f"reasons={','.join(row['reasons'])} | "
                f"first={row['first_timestamp']} | "
                f"last={row['last_timestamp']}"
            )

    return "\n".join(lines) + "\n"


def build_email_gemini_summary(diag: dict[str, Any]) -> str:
    top_agent = next(iter(sorted((diag.get("called_35_by_agent") or {}).items(), key=lambda kv: (-kv[1], kv[0]))), ("none", 0))
    top_reason = next(iter(sorted((diag.get("called_35_by_reason") or {}).items(), key=lambda kv: (-kv[1], kv[0]))), ("none", 0))
    top_title = (diag.get("top_repeated_35_titles") or [{}])[0]
    economic = diag.get("economic") or {}
    fmt = lambda value: "n.d." if value is None else str(value)
    lines = ["Gemini summary:", f"- Real provider attempts: {fmt(economic.get('real_attempts'))}", f"- Usage coverage / cost coverage: {fmt(economic.get('provider_usage_coverage'))} / {fmt(economic.get('computed_cost_coverage'))}", f"- Known paid-tier Standard list-price cost: {fmt(economic.get('known_computed_list_price_cost'))} {economic.get('currency') or 'n.d.'}", f"- Complete-window computed cost: {fmt(economic.get('complete_window_computed_list_price_cost'))}", f"- Unknown-cost attempts: {fmt(economic.get('unknown_computed_cost_attempts'))}; table={economic.get('price_table_version') or 'n.d.'}", f"- Gemini calls total: {diag.get('called_total', 0)} (diagnostic)", f"- Gemini 3.5 called total: {diag.get('called_35_total', 0)} (diagnostic)", f"- Gemini 3.5 top agent/purpose: {top_agent[0]} ({top_agent[1]}) / {top_reason[0]} ({top_reason[1]})", f"- Gemini avoided total: {diag.get('avoided_total', 0)}", f"- Menzo duplicate arbitration cache hits / avoided: latest={diag.get('menzo_latest_cache_hit', 'not_available')} / {diag.get('menzo_latest_cache_avoided', 'not_available')}; 24h ledger hits={diag.get('ledger_duplicate_arbitration_cache_hit_24h', 0)}"]
    if top_title:
        lines.append(f"- Top repeated 3.5 title: {top_title.get('title')} ({top_title.get('called_count', 0)} calls)")
    return "\n".join(lines)
