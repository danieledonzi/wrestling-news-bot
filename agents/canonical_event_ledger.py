"""Fail-open A2 canonical event ledger and P1.1 newsroom observers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from agents.duplicate_pair_identity import article_id
from agents.menzo_duplicate_scorer import canonical_source_url

VERSION = "v95.25_p1_3_operational_event_semantics"
SCHEMA_VERSION = "owtv_event_schema_v1"
POLICY_VERSION = "v95.22_a2"
DEFAULT_PATH = "state/newsroom/canonical_event_ledger.jsonl"
ROOT = Path(__file__).resolve().parents[1]
_ACTIVE_LEDGER: Any = None


def install_active_ledger(ledger: Any) -> None:
    """Register the runner's writer; nested telemetry must never open a second ledger."""
    global _ACTIVE_LEDGER
    _ACTIVE_LEDGER = ledger


def clear_active_ledger() -> None:
    global _ACTIVE_LEDGER
    _ACTIVE_LEDGER = None


def active_event(*args: Any, **kwargs: Any) -> bool:
    """Fail-open event emission for model call sites."""
    try:
        return bool(_ACTIVE_LEDGER and _ACTIVE_LEDGER.safely("event", *args, **kwargs))
    except Exception:
        return False


def new_logical_request_id() -> str:
    return "lrq_" + uuid.uuid4().hex


def new_attempt_id() -> str:
    return "att_" + uuid.uuid4().hex


class OperationalAIRequest:
    """Canonical identity for one AI intention and its concrete calls.

    Callers, rather than legacy operation_id/attempt_index, own this object.
    """
    def __init__(self, owner: str, model_role: str, *, item: Mapping[str, Any] | None = None,
                 reason_code: str = "", report_key: str = ""):
        self.logical_request_id = new_logical_request_id()
        self.owner, self.model_role, self.item = owner, model_role, item
        self.attempt_number = 0
        self.last_model = ""
        self.pending_attempt: Mapping[str, Any] | None = None
        self.pending_latency_ms: int | None = None
        facts = {"logical_request_id": self.logical_request_id, "model_role": model_role,
                 "reason_code": reason_code or None, "report_key": report_key or None}
        active_event("logical_ai_request_created", owner, "model", "started", item=item, **facts)

    def start(self, model_name: str, *, fallback: bool = False, repair: bool = False,
              reason_code: str = "") -> dict[str, Any]:
        if fallback and self.last_model:
            active_event("fallback_started", "Gemini", "model", "started",
                         logical_request_id=self.logical_request_id,
                         fallback_from=self.last_model, fallback_to=model_name)
        if repair:
            active_event("repair_started", "Gemini", "model", "started",
                         logical_request_id=self.logical_request_id, reason_code=reason_code or None)
        self.attempt_number += 1
        attempt = {"logical_request_id": self.logical_request_id,
                   "attempt_id": new_attempt_id(), "attempt_number": self.attempt_number,
                   "model_name": model_name, "model_role": self.model_role}
        active_event("model_attempt_started", "Gemini", "model", "started", item=self.item, **attempt)
        self.last_model = model_name
        return attempt

    def defer(self, attempt: Mapping[str, Any], latency_ms: int | None = None) -> None:
        """Retain a provider result until the caller's domain validator decides it."""
        self.pending_attempt = attempt
        self.pending_latency_ms = latency_ms

    def resolve_deferred(self, accepted: bool, *, error_terminal: bool) -> None:
        attempt, latency = self.pending_attempt, self.pending_latency_ms
        self.pending_attempt = None
        self.pending_latency_ms = None
        if not attempt:
            return
        if accepted:
            self.completed(attempt, latency)
        else:
            self.failed(attempt, error_class="validation", error_terminal=error_terminal,
                        latency_ms=latency, reason_code="invalid_semantic_output")

    def completed(self, attempt: Mapping[str, Any], latency_ms: int | None = None) -> None:
        active_event("model_attempt_completed", "Gemini", "model", "success", item=self.item,
                     latency_ms=latency_ms, **dict(attempt))

    def failed(self, attempt: Mapping[str, Any], *, error_class: str,
               error_terminal: bool, latency_ms: int | None = None,
               reason_code: str = "") -> None:
        active_event("model_attempt_failed", "Gemini", "model", "failed", item=self.item,
                     error_class=error_class, error_terminal=error_terminal,
                     latency_ms=latency_ms, reason_code=reason_code or None, **dict(attempt))

    def avoided(self, reason_code: str) -> None:
        active_event("model_attempt_avoided", "Gemini", "model", "avoided", item=self.item,
                     logical_request_id=self.logical_request_id, model_role=self.model_role,
                     reason_code=reason_code)

    def initialization_failed(self, reason_code: str = "model_client_initialization_failed") -> None:
        """Close a request that failed before any concrete provider attempt existed."""
        active_event("stage_failed", self.owner, "model", "failed", item=self.item,
                     logical_request_id=self.logical_request_id, model_role=self.model_role,
                     reason_code=reason_code, error_class="upstream", error_terminal=True)


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    return json.loads((ROOT / "config/event_schema_v1.json").read_text(encoding="utf-8"))


def validate_event(event: Any) -> list[str]:
    """Validate the complete closed A2 envelope without external packages."""
    if not isinstance(event, dict):
        return ["event must be an object"]
    spec = schema()
    env = spec["envelope"]
    fields = {row["name"]: row for row in env["fields"]}
    errors = [f"unknown field: {key}" for key in event if key not in fields]
    errors += [f"missing required field: {key}" for key in env["required_fields"] if key not in event]
    types = {"string": str, "integer": int, "array": list, "boolean_or_null": (bool, type(None))}
    for key, value in event.items():
        expected = types.get(fields.get(key, {}).get("type"))
        if expected and (not isinstance(value, expected) or (expected is int and isinstance(value, bool))):
            errors.append(f"invalid type for {key}")
    if event.get("schema_version") != spec["schema_version"]:
        errors.append("invalid schema_version")
    if event.get("policy_version") != spec["policy_version"]:
        errors.append("invalid policy_version")
    timestamp = event.get("timestamp_utc")
    if isinstance(timestamp, str):
        timestamp_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)"
        try:
            parsed_timestamp = datetime.fromisoformat(
                timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
            )
            timestamp_valid = (
                re.fullmatch(timestamp_pattern, timestamp) is not None
                and parsed_timestamp.utcoffset() == timezone.utc.utcoffset(parsed_timestamp)
            )
        except ValueError:
            timestamp_valid = False
        if not timestamp_valid:
            errors.append("timestamp_utc must be an RFC3339 UTC timestamp")
    if event.get("stage") not in spec["stages"]:
        errors.append("invalid stage")
    if event.get("agent") not in spec["agents"]:
        errors.append("invalid agent")
    event_specs = {row["name"]: row for row in spec["event_types"]}
    rule = event_specs.get(event.get("event_type"))
    if not rule:
        errors.append("invalid event_type")
    else:
        allowed_stages = rule.get("allowed_stages", [rule.get("stage")])
        if event.get("stage") not in allowed_stages:
            errors.append("event_type not allowed for stage")
        if event.get("agent") not in rule["agents"]:
            errors.append("event_type not allowed for agent")
    statuses = spec.get("outcome_contract", {}).get("status_values", [])
    if statuses and event.get("status") not in statuses:
        errors.append("invalid status")
    refs = event.get("artifact_refs")
    if isinstance(refs, list):
        required_ref_fields = {"path", "relation"}
        allowed_ref_fields = required_ref_fields | {"artifact_type", "schema_version", "sha256"}
        for ref in refs:
            if not isinstance(ref, dict):
                errors.append("invalid artifact_refs")
                break
            if not required_ref_fields.issubset(ref) or not set(ref).issubset(allowed_ref_fields):
                errors.append("invalid artifact_refs fields")
            if not isinstance(ref.get("path"), str) or not ref.get("path"):
                errors.append("invalid artifact_refs path")
            if ref.get("relation") not in {"input", "output", "evidence"}:
                errors.append("invalid artifact_refs relation")
            for key in ("artifact_type", "schema_version"):
                if key in ref and not isinstance(ref[key], str):
                    errors.append(f"invalid artifact_refs {key}")
            if "sha256" in ref and (not isinstance(ref["sha256"], str)
                                    or re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) is None):
                errors.append("invalid artifact_refs sha256")
    for conditional in env["conditional_requirements"]:
        if event.get("event_type") in conditional.get("when_event_types", []):
            errors += [f"conditional field required: {key}" for key in conditional.get("require", []) if key not in event]
            errors += [f"conditional field forbidden: {key}" for key in conditional.get("forbid", []) if key in event]
    return errors


def content_id(item: Mapping[str, Any]) -> str:
    canonical = canonical_source_url(dict(item))
    if not canonical or not canonical.split("://", 1)[-1].split("/", 1)[0]:
        return ""
    return "cnt_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def correlation_id(run_id: str, stable_content_id: str) -> str:
    if not run_id or not stable_content_id:
        return ""
    return "corr_" + hashlib.sha256(f"{run_id}\0{stable_content_id}".encode()).hexdigest()


def report_correlation_id(run_id: str, report_key: str) -> str:
    if not run_id or not report_key:
        return ""
    return "corr_" + hashlib.sha256(f"report\0{run_id}\0{report_key}".encode()).hexdigest()


def _rows(value: Any, keys: Iterable[str]) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, list):
            rows.extend(row for row in candidate if isinstance(row, dict))
    return rows


class CanonicalEventLedger:
    """Append-only emitter. All public observation methods are fail-open."""
    def __init__(self, run_id: str, path: str | Path | None = None, enabled: bool | None = None):
        flag = os.getenv("OWTV_CANONICAL_LEDGER_ENABLED", "true").strip().lower()
        self.enabled = flag not in {"0", "false", "no", "off"} if enabled is None else enabled
        self.run_id = run_id
        self.path = Path(path or os.getenv("OWTV_CANONICAL_LEDGER_PATH", DEFAULT_PATH))
        self.stats = {"enabled": self.enabled, "path": str(self.path), "events_attempted": 0,
                      "events_written": 0, "events_skipped": 0, "validation_errors": 0,
                      "identity_unresolved": 0, "write_errors": 0}
        self.code_commit = self._commit()

    @staticmethod
    def _commit() -> str:
        for key in ("GITHUB_SHA", "CI_COMMIT_SHA", "SOURCE_VERSION"):
            if os.getenv(key, "").strip():
                return os.environ[key].strip()
        try:
            return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                  capture_output=True, check=False, timeout=2).stdout.strip()
        except Exception:
            return ""

    def safely(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Production boundary: no observer defect may escape into orchestration."""
        try:
            return getattr(self, method)(*args, **kwargs)
        except Exception as exc:
            self.stats["events_skipped"] += 1
            print(f"[CANONICAL LEDGER] observer {method} failed open: {exc}", flush=True)
            return None

    def event(self, event_type: str, agent: str, stage: str, status: str,
              artifact: str = "", item: Mapping[str, Any] | None = None, **facts: Any) -> bool:
        self.stats["events_attempted"] += 1
        if not self.enabled:
            self.stats["events_skipped"] += 1
            return False
        row = {"schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
               "timestamp_utc": datetime.now(timezone.utc).isoformat(), "run_id": self.run_id,
               "stage": stage, "agent": agent, "event_type": event_type, "status": status,
               "artifact_refs": ([{"path": artifact, "relation": "evidence"}] if artifact else [])}
        if self.code_commit:
            row["code_commit"] = self.code_commit
        if item is not None:
            cid = content_id(item)
            if not cid:
                self.stats["identity_unresolved"] += 1
                self.stats["events_skipped"] += 1
                return False
            row.update(content_id=cid, correlation_id=correlation_id(self.run_id, cid), article_id=article_id(item))
            if not row["article_id"]:
                row.pop("article_id")
        row.update({key: value for key, value in facts.items() if value is not None and value != ""})
        problems = validate_event(row)
        if problems:
            self.stats["validation_errors"] += 1
            self.stats["events_skipped"] += 1
            print(f"[CANONICAL LEDGER] rejected {event_type}: {'; '.join(problems)}", flush=True)
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.stats["events_written"] += 1
            return True
        except Exception as exc:
            self.stats["write_errors"] += 1
            self.stats["events_skipped"] += 1
            print(f"[CANONICAL LEDGER] append failed: {exc}", flush=True)
            return False

    def observe_items(self, value: Any, keys: Iterable[str], event_type: str, agent: str,
                      stage: str, status: str, artifact: str, result: str = "") -> None:
        for item in _rows(value, keys):
            self.event(event_type, agent, stage, status, artifact, item, result=result or None)

    def observe_massy(self, board: Any) -> None:
        seen: set[str] = set()
        for key in ("news_candidates_for_menzo", "report_candidates", "hard_skipped", "already_worked"):
            for item in _rows(board, (key,)):
                cid = content_id(item)
                if cid and cid not in seen:
                    self.event("candidate_seen", "Massy", "intake", "success", "artifacts/newsroom/massy_board.json", item)
                    seen.add(cid)
                reason = item.get("reason_code") or item.get("reason")
                if key in {"hard_skipped", "already_worked"} and reason:
                    # A2 fixes candidate_skipped at selection even for Massy.
                    self.event("candidate_skipped", "Massy", "selection", "skipped", "artifacts/newsroom/massy_board.json", item,
                               reason_code=reason)
        if isinstance(board, dict):
            found = board.get("found_urls")
            if isinstance(found, int) and found > len(seen):
                self.stats["massy_found_urls_discrepancy"] = found - len(seen)

    def observe_menzo(self, result: Any) -> None:
        for key, event_type, status in (("selected", "candidate_selected", "success"),
                                        ("pending", "candidate_pending", "pending"),
                                        ("skipped", "candidate_skipped", "skipped")):
            for item in _rows(result, (key,)):
                reason = item.get("reason") if key == "skipped" else None
                self.event(event_type, "Menzo", "selection", status, "artifacts/newsroom/menzo_decisions.json", item, reason_code=reason)

    def observe_andrea(self, result: Any) -> None:
        nested = result.get("andrea", {}) if isinstance(result, dict) else {}
        for item in _rows(nested, ("items",)):
            decision = item.get("decision")
            mapped = "passed_with_exception" if decision == "passed_with_exception" else ("blocked" if decision == "blocked_before_bob" or item.get("ok") is False else "passed")
            self.event("content_sufficiency_checked", "Andrea", "content_sufficiency", "success",
                       "artifacts/newsroom/andrea_pre_bob_latest.json", item, result=mapped)

    def observe_bob_requested(self, value: Any) -> None:
        self.observe_items(value, ("selected",), "article_generation_requested", "Bob", "generation", "started", "artifacts/newsroom/andrea_pre_bob_latest.json")

    def observe_bob_generated(self, value: Any) -> None:
        for item in _rows(value, ("articles",)):
            if item.get("status") == "ready_for_alfred":
                self.event("article_generated", "Bob", "generation", "success",
                           "artifacts/newsroom/bob_articles.json", item)

    def observe_alfred(self, value: Any) -> None:
        for item in _rows(value, ("reviews",)):
            decision = item.get("decision")
            self.event("quality_review_completed", "Alfred", "quality", "success",
                       "artifacts/newsroom/alfred_review.json", item,
                       result=decision if decision in {"approved", "needs_revision"} else None)
            # Preserve occurrences: repeated codes are separate operational facts.
            for warning in _rows(item, ("warnings",)):
                code = str(warning.get("code") or "").strip()
                severity = str(warning.get("severity") or "").strip().lower()
                if not code:
                    continue
                self.event("warning_recorded", "Alfred", "audit", "success",
                           "artifacts/newsroom/alfred_review.json", item,
                           reason_code=code, result=severity or "warning")
            for issue in _rows(item, ("issues",)):
                code = str(issue.get("code") or "").strip()
                severity = str(issue.get("severity") or "").strip().lower()
                if severity == "blocker":
                    self.event("blocker_recorded", "Alfred", "audit", "success",
                               "artifacts/newsroom/alfred_review.json", item,
                               reason_code=code, result="blocker")

    def observe_publisher(self, value: Any) -> None:
        for item in _rows(value, ("results",)):
            status = item.get("status")
            reason = item.get("reason")
            # A publication attempt means an actual write path, not a preflight,
            # validation, dry-run, or already-present observation.
            attempted = status in {"published", "publish_error"}
            if attempted:
                self.event("publication_attempted", "Publisher", "publication", "started",
                           "artifacts/newsroom/publisher_result.json", item)
            if status == "published":
                self.event("publication_completed", "Publisher", "publication", "success", "artifacts/newsroom/publisher_result.json", item)
            elif status == "already_published":
                self.event("publication_already_present", "Publisher", "publication", "skipped", "artifacts/newsroom/publisher_result.json", item)
            elif status == "publish_error":
                self.event("publication_failed", "Publisher", "publication", "failed",
                           "artifacts/newsroom/publisher_result.json", item,
                           reason_code="publish_error", error_class="downstream", error_terminal=True)
            elif status == "wp_not_ready":
                self.event("stage_failed", "Publisher", "publication", "failed",
                           "artifacts/newsroom/publisher_result.json", item,
                           reason_code="wp_not_ready", error_class="downstream", error_terminal=True)
            elif status == "missing_url_or_title" or (status == "skipped" and reason == "missing_url_or_title"):
                self.event("stage_failed", "Publisher", "publication", "failed",
                           "artifacts/newsroom/publisher_result.json",
                           item if content_id(item) else None,
                           reason_code="missing_url_or_title", error_class="validation", error_terminal=True)

    def observe_simone(self, decision: Any, published: Any = None) -> None:
        self.observe_items(decision, ("candidates", "report_candidates"), "report_candidate_seen", "Simone", "reporting", "success", "artifacts/newsroom/simone_reports.json")
        for item in _rows(decision, ("ready_reports",)):
            self._report_event("report_selected", item, "success", "artifacts/newsroom/simone_reports.json")
        for item in _rows(published, ("results",)):
            item_status = item.get("status")
            if item_status == "published":
                self._report_event("report_published", item, "success", "artifacts/newsroom/simone_report_publish.json")
            elif item_status in {"publish_error", "wp_not_ready"}:
                self._report_event("stage_failed", item, "failed", "artifacts/newsroom/simone_report_publish.json",
                                   error_class="downstream", error_terminal=True,
                                   reason_code=str(item_status))

    def _report_event(self, kind: str, item: Mapping[str, Any], status: str, artifact: str,
                      **extra: Any) -> None:
        key = str(item.get("report_key") or "")
        facts = {"report_key": key or None}
        has_content = bool(content_id(item))
        if key and not has_content:
            facts["correlation_id"] = report_correlation_id(self.run_id, key)
        facts.update(extra)
        self.event(kind, "Simone", "reporting", status, artifact, item if has_content else None, **facts)

    def summary(self) -> dict[str, Any]:
        return dict(self.stats)
