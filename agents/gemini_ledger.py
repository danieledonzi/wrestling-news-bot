from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state" / "newsroom"
ARTIFACT_DIR = ROOT / "artifacts" / "newsroom"
LEDGER_FILE = STATE_DIR / "gemini_call_ledger.jsonl"
LATEST_FILE = ARTIFACT_DIR / "gemini_call_ledger_latest.json"
PRICING_FILE = ROOT / "config" / "gemini_pricing.json"
V2_TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "thinking_tokens")
V2_COST_FIELDS = ("estimated_input_cost", "estimated_output_cost", "estimated_thinking_cost", "estimated_cached_input_cost", "estimated_cost")
USAGE_CONTRACT_VERSION = "v96.2_usage.v1"
PRICING_FORMULA_VERSION = "v96.2_cost.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_run_id() -> str | None:
    return os.getenv("NEWSROOM_RUN_ID", "").strip() or None


def _clean(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    return str(value)



def make_operation_id(agent: str, phase: str, key: Any = None) -> str:
    safe_key = str(key or "operation").replace(" ", "_")[:80]
    return f"{agent}:{phase}:{safe_key}:{uuid.uuid4().hex}"


def _get_value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _coerce_token(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("boolean_token")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValueError("non_integer_token")
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    raise ValueError("invalid_token")


def _normalize_service_tier(value: Any) -> str | None:
    """Return stable Google UsageMetadata service-tier evidence."""
    if value is None:
        return None
    underlying = getattr(value, "value", value)
    if underlying is None:
        return None
    text = str(underlying).strip().lower()
    if not text:
        return None
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    if text.startswith("service_tier_"):
        text = text[len("service_tier_"):]
    return text or None


def _metadata_with_source(response: Any) -> tuple[Any, Any]:
    if response is None:
        return None, None
    for name in ("usage_metadata", "usageMetadata", "usage"):
        value = _get_value(response, name)
        if value is not None:
            return value, name
    return None, None


def extract_actual_model(response: Any) -> Any:
    try:
        if response is None:
            return None
        for name in ("model_version", "modelVersion", "model", "model_name", "modelName"):
            value = _get_value(response, name)
            if value is not None and str(value).strip():
                return str(value).strip()
    except Exception:
        return None
    return None


def extract_usage_metadata(response: Any) -> dict[str, Any]:
    out = {"input_tokens": None, "output_tokens": None, "total_tokens": None, "cached_input_tokens": None, "thinking_tokens": None, "token_field_states": {}, "total_tokens_provider_reported": False, "total_tokens_legacy_derived": False, "service_tier": None, "modality": None, "economically_material_tool_usage": False, "usage_available": False, "usage_source": None, "usage_warning": None}
    try:
        meta, source = _metadata_with_source(response)
        if meta is None:
            return out
        warnings: list[str] = []
        recognized = 0
        parsed = 0
        aliases = {
            "input_tokens": ("prompt_token_count", "promptTokenCount", "input_token_count", "inputTokenCount"),
            "output_tokens": ("candidates_token_count", "candidatesTokenCount", "output_token_count", "outputTokenCount"),
            "total_tokens": ("total_token_count", "totalTokenCount"),
            "cached_input_tokens": ("cached_content_token_count", "cachedContentTokenCount", "cached_input_token_count", "cachedInputTokenCount"),
            "thinking_tokens": ("thoughts_token_count", "thoughtsTokenCount", "thinking_token_count", "thinkingTokenCount"),
        }
        for field, names in aliases.items():
            out["token_field_states"][field] = "absent_or_null"
            for name in names:
                val = _get_value(meta, name)
                if val is not None:
                    recognized += 1
                    try:
                        out[field] = _coerce_token(val)
                        out["token_field_states"][field] = "present_valid"
                        parsed += 1
                    except Exception:
                        out[field] = None
                        out["token_field_states"][field] = "present_malformed"
                        warnings.append(f"malformed_{name}")
                    break
        out["total_tokens_provider_reported"] = out["token_field_states"].get("total_tokens") == "present_valid"
        raw_service_tier = _get_value(meta, "service_tier")
        if raw_service_tier is None:
            raw_service_tier = _get_value(meta, "serviceTier")
        out["service_tier"] = _normalize_service_tier(raw_service_tier)
        out["modality"] = _get_value(meta, "modality")
        out["economically_material_tool_usage"] = bool(_get_value(meta, "economically_material_tool_usage") or _get_value(meta, "economicallyMaterialToolUsage"))
        if recognized == 0:
            out["usage_warning"] = "usage_metadata_no_recognized_token_fields"
            return out
        if parsed == 0:
            out["usage_warning"] = ";".join(warnings + ["usage_metadata_all_token_fields_malformed"])[:240]
            return out
        out["usage_available"] = True
        out["usage_source"] = str(source)
        if out["token_field_states"].get("total_tokens") == "absent_or_null" and out["input_tokens"] is not None and out["output_tokens"] is not None:
            out["total_tokens"] = int(out["input_tokens"]) + int(out["output_tokens"])
            out["total_tokens_legacy_derived"] = True
            warnings.append("total_tokens_derived_from_input_output")
        if warnings:
            out["usage_warning"] = ";".join(warnings)[:240]
        return out
    except Exception as exc:
        out["usage_warning"] = f"usage_extract_failed:{str(exc)[:120]}"
        return out

def load_pricing_table(path: Any = None) -> dict[str, Any]:
    try:
        configured = path or os.getenv("GEMINI_PRICING_FILE", "").strip() or PRICING_FILE
        data = json.loads(Path(configured).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_pricing_model(model: Any, pricing_table: Any = None) -> tuple[Any, Any, Any]:
    table = pricing_table if isinstance(pricing_table, dict) else load_pricing_table()
    raw = str(model or "").strip()
    if not raw:
        return None, None, "price_not_configured:unknown"
    aliases = table.get("aliases") if isinstance(table.get("aliases"), dict) else {}
    models = table.get("models") if isinstance(table.get("models"), dict) else {}
    key = aliases.get(raw, raw)
    conf = models.get(key) if isinstance(models, dict) else None
    if isinstance(conf, dict):
        return str(key), conf, None
    return None, None, f"price_not_configured:{raw}"


def _decimal_or_none(value: Any) -> Any:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def calculate_v96_2_cost(usage: dict[str, Any], actual_model: Any = None, model_requested: Any = None,
                         pricing_table: Any = None, timestamp: Any = None) -> dict[str, Any]:
    """Resolve authoritative Standard text list-price cost using Decimal arithmetic."""
    table = pricing_table if isinstance(pricing_table, dict) else load_pricing_table()
    out = {"usage_contract_version": USAGE_CONTRACT_VERSION, "pricing_formula_version": PRICING_FORMULA_VERSION,
           "price_table_version": table.get("price_table_version"), "pricing_currency": table.get("currency"),
           "pricing_model_key": None, "pricing_identity_source": None, "pricing_service_tier": None,
           "pricing_service_tier_source": None, "pricing_modality": None, "pricing_modality_source": None,
           "non_cached_input_tokens": None, "effective_cached_input_tokens": None, "effective_thinking_tokens": None,
           "cached_input_tokens_zero_normalized": False, "thinking_tokens_derived": False,
           "usage_resolution_status": "unresolved", "usage_resolution_reason": "usage_missing",
           "computed_non_cached_input_cost": None, "computed_cached_input_cost": None,
           "computed_candidate_output_cost": None, "computed_thinking_cost": None,
           "computed_list_price_cost": None, "cost_resolution_status": "unresolved", "cost_resolution_reason": "usage_missing"}
    if usage.get("usage_available") is not True:
        return out
    try:
        states = usage.get("token_field_states") if isinstance(usage.get("token_field_states"), dict) else {}
        if any(states.get(field) == "present_malformed" for field in ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "thinking_tokens")):
            out["usage_resolution_reason"] = out["cost_resolution_reason"] = "usage_invalid"; return out
        p, o, total = (_coerce_token(usage.get(k)) for k in ("input_tokens", "output_tokens", "total_tokens"))
        if p is None or o is None:
            return out
        k = _coerce_token(usage.get("cached_input_tokens"))
        if k is None:
            k = 0; out["cached_input_tokens_zero_normalized"] = True
        t = _coerce_token(usage.get("thinking_tokens"))
        if t is None:
            if total is None or usage.get("total_tokens_legacy_derived"):
                return out
            t = total - p - o; out["thinking_tokens_derived"] = True
        provider_total = bool(usage.get("total_tokens_provider_reported")) or (total is not None and not usage.get("total_tokens_legacy_derived"))
        if min(p, o, k, t) < 0 or k > p or (provider_total and total != p + o + t):
            out["usage_resolution_reason"] = out["cost_resolution_reason"] = "usage_invalid"; return out
        out.update(non_cached_input_tokens=p-k, effective_cached_input_tokens=k, effective_thinking_tokens=t,
                   usage_resolution_status="resolved", usage_resolution_reason="resolved")
    except Exception:
        out["usage_resolution_reason"] = out["cost_resolution_reason"] = "usage_invalid"; return out
    model = actual_model if actual_model is not None and str(actual_model).strip() else model_requested
    out["pricing_identity_source"] = "actual_model" if actual_model is not None and str(actual_model).strip() else "model_requested"
    key, conf, _ = resolve_pricing_model(model, table)
    if not conf:
        out["cost_resolution_reason"] = "model_unresolved"; return out
    out["pricing_model_key"] = key
    tier = _normalize_service_tier(usage.get("service_tier"))
    if tier and tier not in {"standard", "unspecified", "paid_tier_standard", "paid-tier-standard"}:
        out["pricing_service_tier"] = tier; out["pricing_service_tier_source"] = "provider_usage"
        out["cost_resolution_reason"] = "price_class_unresolved"; return out
    out["pricing_service_tier"] = "standard"
    out["pricing_service_tier_source"] = "provider_usage_default_standard" if tier == "unspecified" else ("provider_usage" if tier else "runtime_default_standard")
    modality = str(usage.get("modality") or "").strip().lower()
    if usage.get("economically_material_tool_usage") or (modality and modality != "text"):
        out["cost_resolution_reason"] = "mixed_or_unresolved_modality"; return out
    out["pricing_modality"] = "text"; out["pricing_modality_source"] = "provider_usage" if modality else "runtime_text_contract"
    if timestamp:
        valid_from = datetime.fromisoformat(str(table["valid_from"]).replace("Z", "+00:00"))
        row_time = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if row_time < valid_from:
            out["cost_resolution_reason"] = "outside_price_validity"; return out
    if "tiers" in conf:
        tiers = conf["tiers"]
        conf = tiers[0] if p <= 200000 else tiers[1]
    if any(conf.get(k) is None for k in ("input_price_per_million", "output_price_per_million", "cached_input_price_per_million")):
        out["cost_resolution_reason"] = "price_class_unresolved"; return out
    ip, op, kp = map(Decimal, (str(conf["input_price_per_million"]), str(conf["output_price_per_million"]), str(conf["cached_input_price_per_million"])))
    million = Decimal(1000000)
    components = ((Decimal(p-k)*ip/million), (Decimal(k)*kp/million), (Decimal(o)*op/million), (Decimal(t)*op/million))
    names = ("computed_non_cached_input_cost", "computed_cached_input_cost", "computed_candidate_output_cost", "computed_thinking_cost")
    out.update({n: format(v, "f") for n, v in zip(names, components)})
    out["computed_list_price_cost"] = format(sum(components, Decimal(0)), "f")
    out["cost_resolution_status"] = out["cost_resolution_reason"] = "resolved"
    return out


def calculate_estimated_cost(usage: dict[str, Any], model: Any, pricing_table: Any = None) -> dict[str, Any]:
    out = {"pricing_currency": None, "price_table_version": None, "pricing_model_key": None, "input_price_per_million": None, "output_price_per_million": None, "cached_input_price_per_million": None, "estimated_input_cost": None, "estimated_output_cost": None, "estimated_thinking_cost": None, "estimated_cached_input_cost": None, "estimated_cost": None, "pricing_warning": None}
    try:
        if usage.get("usage_available") is not True:
            return out
        table = pricing_table if isinstance(pricing_table, dict) else load_pricing_table()
        out["pricing_currency"] = table.get("currency")
        out["price_table_version"] = table.get("price_table_version")
        key, conf, warning = resolve_pricing_model(model, table)
        if warning:
            out["pricing_warning"] = warning
            return out
        out["pricing_model_key"] = key
        in_p = _decimal_or_none(conf.get("input_price_per_million"))
        out_p = _decimal_or_none(conf.get("output_price_per_million"))
        cache_p = _decimal_or_none(conf.get("cached_input_price_per_million"))
        out["input_price_per_million"] = str(in_p) if in_p is not None else None
        out["output_price_per_million"] = str(out_p) if out_p is not None else None
        out["cached_input_price_per_million"] = str(cache_p) if cache_p is not None else None
        total = Decimal("0")
        complete = True
        billable_seen = False
        incomplete: list[str] = []
        components = (("input_tokens", in_p, "estimated_input_cost", "input"), ("output_tokens", out_p, "estimated_output_cost", "output"), ("thinking_tokens", out_p, "estimated_thinking_cost", "thinking"), ("cached_input_tokens", cache_p, "estimated_cached_input_cost", "cached_input"))
        for token_field, price, cost_field, label in components:
            tokens = usage.get(token_field)
            if tokens is None:
                continue
            billable_seen = True
            token_count = int(tokens)
            if token_count == 0 and price is None:
                out[cost_field] = "0"
                continue
            if price is None:
                complete = False
                incomplete.append(label)
                continue
            cost = Decimal(token_count) * price / Decimal(1000000)
            out[cost_field] = format(cost, "f")
            total += cost
        if not billable_seen:
            out["pricing_warning"] = "no_billable_token_components"
        elif complete:
            out["estimated_cost"] = format(total, "f")
        elif incomplete:
            out["pricing_warning"] = "incomplete_price_configuration:" + ",".join(incomplete)
    except (InvalidOperation, Exception) as exc:
        out["pricing_warning"] = f"pricing_failed:{str(exc)[:120]}"
    return out

def _merge_warning(a: Any, b: Any) -> Any:
    parts = [str(x) for x in (a, b) if x]
    return ";".join(parts)[:300] if parts else None


def record_gemini_attempt(*, response: Any = None, model_requested: Any = None, actual_model: Any = None, operation_id: Any = None, attempt_index: int = 0, retry: bool = False, fallback: bool = False, repair: bool = False, **kwargs: Any) -> None:
    try:
        usage = extract_usage_metadata(response)
        response_actual_model = actual_model if actual_model is not None else extract_actual_model(response)
        authoritative = calculate_v96_2_cost(usage, response_actual_model, model_requested)
        model_value = response_actual_model or model_requested or kwargs.pop("model", None)
        record_gemini_event(ledger_schema_version="v3", provider_attempt_id=str(uuid.uuid4()), legacy_estimated_cost_authoritative=False, legacy_cost_semantics="deprecated_non_authoritative_not_computed", operation_id=operation_id or make_operation_id(str(kwargs.get("agent") or "Gemini"), str(kwargs.get("phase") or "generation")), attempt_index=attempt_index, model_requested=model_requested, model=model_value, actual_model=response_actual_model, retry=bool(retry), fallback=bool(fallback), repair=bool(repair), **usage, **authoritative, **kwargs)
    except Exception:
        return

def record_gemini_event(**kwargs: Any) -> None:
    """Best-effort append-only Gemini/cost observability ledger."""
    try:
        record: dict[str, Any] = {
            "timestamp": kwargs.pop("timestamp", None) or utc_now(),
            "run_id": kwargs.pop("run_id", None) or current_run_id(),
            "ledger_schema_version": kwargs.pop("ledger_schema_version", None) or "v2",
            "agent": kwargs.pop("agent", None),
            "phase": kwargs.pop("phase", None),
            "model": kwargs.pop("model", None),
            "url": kwargs.pop("url", None),
            "title": kwargs.pop("title", None),
            "candidate_id": kwargs.pop("candidate_id", None),
            "source_id": kwargs.pop("source_id", None),
            "reason": kwargs.pop("reason", None),
            "status": kwargs.pop("status", None),
            "result": kwargs.pop("result", None),
            "published": kwargs.pop("published", None),
            "blocked_by_andrea": kwargs.pop("blocked_by_andrea", None),
            "blocked_by_alfred": kwargs.pop("blocked_by_alfred", None),
            "saved_gemini_call": bool(kwargs.pop("saved_gemini_call", False)),
        }
        if record.get("status") == "avoided" and record.get("ledger_schema_version") == "v2":
            record.update({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_input_tokens": 0, "thinking_tokens": 0, "usage_available": True, "usage_source": "avoided_no_api_call", "estimated_input_cost": "0", "estimated_output_cost": "0", "estimated_thinking_cost": "0", "estimated_cached_input_cost": "0", "estimated_cost": "0"})
        elif record.get("ledger_schema_version") == "v2":
            for field in V2_TOKEN_FIELDS:
                record.setdefault(field, None)
            for field in V2_COST_FIELDS:
                record.setdefault(field, None)
            record.setdefault("usage_available", False)
            record.setdefault("usage_source", None)
            record.setdefault("usage_warning", None)
        record.update({str(k): _clean(v) for k, v in kwargs.items()})
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        with LEDGER_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_clean(record), ensure_ascii=False, sort_keys=True) + "\n")
        write_latest_snapshot(run_id=record.get("run_id"))
    except Exception:
        return


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out.setdefault("ledger_schema_version", "v1")
    if out.get("ledger_schema_version") == "v1":
        for field in V2_TOKEN_FIELDS:
            out.setdefault(field, None)
        for field in V2_COST_FIELDS:
            out.setdefault(field, None)
        out.setdefault("usage_available", False if out.get("status") != "avoided" else None)
    return out


def iter_records() -> list[dict[str, Any]]:
    try:
        if not LEDGER_FILE.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in LEDGER_FILE.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    out.append(normalize_record(data))
            except Exception:
                continue
        return out
    except Exception:
        return []


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [r for r in records if r.get("status") == "called"]
    avoided = [r for r in records if r.get("status") == "avoided"]
    failed = [r for r in records if r.get("status") == "failed"]
    by_agent = Counter(str(r.get("agent") or "unknown") for r in calls)
    premium_calls = [r for r in calls if r.get("selected_model_chain_kind") == "premium" or str(r.get("model") or "") == "gemini-3.5-flash"]
    standard_calls = [r for r in calls if r.get("selected_model_chain_kind") == "standard" or str(r.get("model") or "") != "gemini-3.5-flash"]
    real_attempts = [r for r in records if r.get("status") in {"called", "failed"}]
    v2_real = [r for r in real_attempts if r.get("ledger_schema_version") == "v2"]
    with_usage = [r for r in v2_real if r.get("usage_available") is True]
    with_cost = [r for r in v2_real if r.get("estimated_cost") is not None]
    return {
        "gemini_model_routing_v95_4": True,
        "gemini_calls_total": len(calls),
        "gemini_calls_by_agent": dict(sorted(by_agent.items())),
        "gemini_calls_avoided_total": len(avoided),
        "gemini_calls_avoided_by_andrea": sum(1 for r in avoided if str(r.get("agent") or "").lower() == "andrea"),
        "gemini_calls_failed": len(failed),
        "premium_model_calls": len(premium_calls),
        "standard_model_calls": len(standard_calls),
        "purpose_gate_avoided_calls": sum(1 for r in avoided if r.get("reason") in {"purpose_gate_not_met", "high_ambiguity_gate_not_met"}),
        "menzo_second_pass_35_avoided": sum(1 for r in avoided if r.get("agent") == "Menzo" and r.get("phase") == "duplicate_arbitration_second_pass"),
        "gemini_calls_avoided_by_duplicate_arbitration_cache": sum(1 for r in avoided if r.get("agent") == "Menzo" and r.get("reason") == "duplicate_arbitration_cache_hit"),
        "menzo_model_cooldown_avoided": sum(1 for r in avoided if r.get("reason") == "model_cooldown_after_failure"),
        "bob_premium_articles": sum(1 for r in calls if r.get("agent") == "Bob" and r.get("selected_model_chain_kind") == "premium"),
        "bob_standard_articles": sum(1 for r in calls if r.get("agent") == "Bob" and r.get("selected_model_chain_kind") == "standard"),
        "v2_real_attempts": len(v2_real),
        "real_attempts_with_usage": len(with_usage),
        "real_attempts_with_cost": len(with_cost),
        "usage_coverage": (len(with_usage) / len(v2_real)) if v2_real else None,
        "pricing_coverage": (len(with_cost) / len(v2_real)) if v2_real else None,
    }


def latest_for_run(run_id: str | None = None) -> dict[str, Any]:
    run_id = run_id or current_run_id()
    records = iter_records()
    if run_id:
        records = [r for r in records if r.get("run_id") == run_id]
    return {"generated_at": utc_now(), "run_id": run_id, "summary": summarize(records), "records": records}


def write_latest_snapshot(run_id: str | None = None) -> dict[str, Any]:
    data = latest_for_run(run_id)
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = LATEST_FILE.with_suffix(LATEST_FILE.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(LATEST_FILE)
    except Exception:
        pass
    return data


def record_andrea_avoided(candidate: dict[str, Any] | None = None, *, phase: str = "pre_bob_content_sufficiency_guard", reason: str | None = None) -> None:
    candidate = candidate or {}
    record_gemini_event(
        ledger_schema_version="v2",
        agent="Andrea",
        phase=phase,
        status="avoided",
        url=candidate.get("url") or candidate.get("source_url"),
        title=candidate.get("title") or candidate.get("source_title"),
        candidate_id=candidate.get("candidate_id") or candidate.get("id") or candidate.get("semantic_id"),
        source_id=candidate.get("source_id") or candidate.get("source"),
        reason=reason or candidate.get("andrea_reason") or candidate.get("reason") or "blocked_before_bob",
        blocked_by_andrea=True,
        saved_gemini_call=True,
        would_have_agent="Bob",
    )
