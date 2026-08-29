"""Fail-open P1.2 canonical artifact index and immutable material archive."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from agents.canonical_event_ledger import content_id, correlation_id
from agents.duplicate_pair_identity import article_id
from agents import source_body

VERSION = "v95.24_p1_2_artifact_index_material_chain"
SCHEMA_VERSION = "owtv_artifact_manifest_schema_v1"
POLICY_VERSION = "v95.22_a3"
DEFAULT_INDEX_PATH = "state/newsroom/canonical_artifact_index.jsonl"
DEFAULT_MATERIAL_ROOT = "state/newsroom/material_chain"
ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    return json.loads((ROOT / "config/artifact_manifest_schema_v1.json").read_text(encoding="utf-8"))


def _utc_valid(value: str) -> bool:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        return parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    except ValueError:
        return False


def validate_manifest_entry(row: Any) -> list[str]:
    """Validate the frozen A3 closed envelope and its nested contracts."""
    if not isinstance(row, dict):
        return ["manifest entry must be an object"]
    spec = schema()
    env = spec["envelope"]
    fields = {field["name"]: field for field in env["fields"]}
    errors = [f"unknown field: {key}" for key in row if key not in fields]
    errors += [f"missing required field: {key}" for key in env["required_fields"] if key not in row]
    types = {"string": str, "integer": int, "array": list, "object": dict}
    for key, value in row.items():
        expected = types.get(fields.get(key, {}).get("type"))
        if expected and (not isinstance(value, expected) or (expected is int and isinstance(value, bool))):
            errors.append(f"invalid type for {key}")
        if isinstance(value, str) and not value:
            errors.append(f"empty string for {key}")
    if row.get("schema_version") != spec["schema_version"]:
        errors.append("invalid schema_version")
    if row.get("policy_version") != spec["policy_version"]:
        errors.append("invalid policy_version")
    tax = spec["taxonomies"]
    for field, taxonomy in (("artifact_type", "artifact_types"), ("storage_class", "storage_classes"),
                            ("format", "formats"), ("persistence_class", "persistence_classes"),
                            ("mutation_mode", "mutation_modes"), ("producer_stage", None)):
        allowed = spec["a2_compatibility"]["producer_stages"] if taxonomy is None else tax[taxonomy]
        if row.get(field) not in allowed:
            errors.append(f"invalid {field}")
    if "producer_agent" in row and row.get("producer_agent") not in spec["a2_compatibility"]["producer_agents"]:
        errors.append("invalid producer_agent")
    for field in ("manifested_at_utc", "artifact_created_at_utc"):
        if field in row and isinstance(row[field], str) and not _utc_valid(row[field]):
            errors.append(f"{field} must be an RFC3339 UTC timestamp")
    path = row.get("path")
    if isinstance(path, str):
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or path.startswith(("/", "\\")):
            errors.append("path must be relative and traversal-free")
        suffix_map = spec["path_contract"]["extension_format_mapping"]
        if pure.suffix in suffix_map and suffix_map[pure.suffix] != row.get("format"):
            errors.append("path extension does not match format")
    roles = row.get("semantic_roles")
    if isinstance(roles, list) and (not roles or any(not isinstance(x, str) or x not in tax["semantic_roles"] for x in roles)):
        errors.append("invalid semantic_roles")
    retention = row.get("retention_policy")
    contract = spec["retention_policy_contract"]
    if isinstance(retention, dict):
        allowed = set(contract["required_fields"] + contract["optional_fields"])
        if set(retention) - allowed or any(k not in retention for k in contract["required_fields"]):
            errors.append("invalid retention_policy fields")
        if retention.get("mode") not in tax["retention_modes"] or retention.get("value_source") not in tax["retention_value_sources"]:
            errors.append("invalid retention_policy taxonomy")
        max_items = retention.get("max_items")
        if retention.get("mode") == "bounded_count" and (
                not isinstance(max_items, int) or isinstance(max_items, bool) or max_items < 1):
            errors.append("retention_policy max_items required")
        max_age_days = retention.get("max_age_days")
        if retention.get("mode") == "bounded_time" and (
                not isinstance(max_age_days, int) or isinstance(max_age_days, bool) or max_age_days < 1):
            errors.append("retention_policy max_age_days required")
    claims = row.get("authority_claims")
    claim_contract = spec["authority_claim_contract"]
    if isinstance(claims, list):
        allowed = set(claim_contract["required_fields"] + claim_contract["optional_fields"])
        if not claims:
            errors.append("authority_claims must not be empty")
        for claim in claims:
            if not isinstance(claim, dict) or set(claim) - allowed or any(k not in claim for k in claim_contract["required_fields"]):
                errors.append("invalid authority_claim fields")
            elif claim["purpose"] not in tax["authority_purposes"] or claim["level"] not in tax["authority_levels"]:
                errors.append("invalid authority_claim taxonomy")
            elif any(key in claim and not isinstance(claim[key], str) for key in ("selector", "note")):
                errors.append("invalid authority_claim optional field type")
    artifact_schema = row.get("artifact_schema_version")
    if isinstance(artifact_schema, dict):
        status = artifact_schema.get("status")
        if set(artifact_schema) - {"status", "version"} or status not in tax["artifact_schema_statuses"]:
            errors.append("invalid artifact_schema_version")
        elif status in {"known", "producer_version_only"} and (
                not isinstance(artifact_schema.get("version"), str) or not artifact_schema["version"]):
            errors.append("invalid artifact_schema_version version")
        elif status in {"none_unknown", "varies"} and "version" in artifact_schema:
            errors.append("invalid artifact_schema_version version")
    sha = row.get("sha256")
    if sha is not None and (not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None):
        errors.append("invalid sha256")
    size = row.get("size_bytes")
    if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 0):
        errors.append("invalid size_bytes")
    return errors


def artifact_id(run_id: str, stable_content_id: str, producer_stage: str,
                semantic_role: str, exact_bytes: bytes) -> str:
    digest = hashlib.sha256(exact_bytes).hexdigest()
    material = "\0".join((run_id, stable_content_id, producer_stage, semantic_role, digest))
    return "afi_" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class CanonicalArtifactIndex:
    """Observe existing payloads without mutation, networking, or model calls."""
    def __init__(self, run_id: str, index_path: str | Path | None = None,
                 material_root: str | Path | None = None, enabled: bool | None = None,
                 repository_root: str | Path | None = None):
        flag = os.getenv("OWTV_CANONICAL_ARTIFACT_INDEX_ENABLED", "true").strip().lower()
        self.enabled = flag not in {"0", "false", "no", "off"} if enabled is None else enabled
        self.run_id = run_id
        self.repository_root = Path(repository_root or Path.cwd()).resolve()
        self.index_path = Path(index_path or os.getenv("OWTV_CANONICAL_ARTIFACT_INDEX_PATH", DEFAULT_INDEX_PATH))
        self.material_root = Path(material_root or os.getenv("OWTV_MATERIAL_CHAIN_ROOT", DEFAULT_MATERIAL_ROOT))
        self.stats = {"enabled": self.enabled, "index_path": str(self.index_path),
                      "material_root": str(self.material_root), "artifacts_attempted": 0,
                      "artifacts_archived": 0, "manifest_rows_written": 0, "artifacts_reused": 0,
                      "artifacts_skipped": 0, "validation_errors": 0, "identity_unresolved": 0,
                      "archive_write_errors": 0, "index_write_errors": 0, "initialization_error": ""}
        self.known_ids: set[str] = set()
        self.code_commit = self._commit()
        if self.enabled:
            self._load_ids()

    def _commit(self) -> str:
        try:
            return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                  capture_output=True, timeout=2, check=False).stdout.strip()
        except Exception:
            return ""

    def _load_ids(self) -> None:
        try:
            if self.index_path.exists():
                for line in self.index_path.read_text(encoding="utf-8").splitlines():
                    try:
                        value = json.loads(line)
                        if isinstance(value.get("artifact_id"), str):
                            self.known_ids.add(value["artifact_id"])
                    except (json.JSONDecodeError, AttributeError):
                        continue
        except Exception as exc:
            self.stats["initialization_error"] = str(exc)
            self.enabled = False
            self.stats["enabled"] = False

    def safely(self, method: str, *args: Any) -> Any:
        try:
            return getattr(self, method)(*args)
        except Exception as exc:
            self.stats["artifacts_skipped"] += 1
            print(f"[ARTIFACT INDEX] observer {method} failed open: {exc}", flush=True)
            return None

    def summary(self) -> dict[str, Any]:
        return dict(self.stats)

    def _identity(self, item: Mapping[str, Any]) -> tuple[str, str]:
        cid = content_id(item)
        return cid, correlation_id(self.run_id, cid)

    def _retain(self, item: Mapping[str, Any], data: bytes, *, stem: str, extension: str,
                fmt: str, agent: str, stage: str, roles: list[str], purpose: str,
                authority: str = "supporting", artifact_schema: dict[str, str] | None = None) -> bool:
        self.stats["artifacts_attempted"] += 1
        if not self.enabled:
            self.stats["artifacts_skipped"] += 1
            return False
        cid, corr = self._identity(item)
        if not cid or not corr:
            self.stats["identity_unresolved"] += 1
            self.stats["artifacts_skipped"] += 1
            return False
        sha = hashlib.sha256(data).hexdigest()
        aid = artifact_id(self.run_id, cid, stage, "+".join(roles), data)
        run_token = hashlib.sha256(self.run_id.encode("utf-8")).hexdigest()[:20]
        target = self.material_root / run_token / cid / f"{stem}-{sha[:20]}.{extension}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != data:
                    self.stats["archive_write_errors"] += 1
                    self.stats["artifacts_skipped"] += 1
                    return False
                self.stats["artifacts_reused"] += 1
            else:
                with target.open("xb") as handle:
                    handle.write(data)
                self.stats["artifacts_archived"] += 1
        except Exception:
            self.stats["archive_write_errors"] += 1
            self.stats["artifacts_skipped"] += 1
            return False
        try:
            relative = target.resolve().relative_to(self.repository_root).as_posix()
        except ValueError:
            self.stats["validation_errors"] += 1
            self.stats["artifacts_skipped"] += 1
            return False
        now = datetime.now(timezone.utc).isoformat()
        row: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "policy_version": POLICY_VERSION,
            "artifact_id": aid, "artifact_type": "archive", "path": relative,
            "storage_class": "runtime_state",
            "format": fmt, "producer_agent": agent, "producer_stage": stage,
            "producer_component": "agents.canonical_artifact_index", "manifested_at_utc": now,
            "run_id": self.run_id, "correlation_id": corr, "content_id": cid,
            "semantic_roles": roles, "persistence_class": "immutable_archive", "mutation_mode": "immutable",
            "retention_policy": {"mode": "persistent", "value_source": "fixed_contract"},
            "authority_claims": [{"purpose": purpose, "level": authority}],
            "artifact_schema_version": artifact_schema or {"status": "none_unknown"},
            "sha256": sha, "size_bytes": len(data)}
        article = article_id(item)
        if article:
            row["article_id"] = article
        if self.code_commit:
            row["code_commit"] = self.code_commit
        problems = validate_manifest_entry(row)
        if problems:
            self.stats["validation_errors"] += 1
            self.stats["artifacts_skipped"] += 1
            return False
        if aid in self.known_ids:
            return True
        try:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            with self.index_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            self.known_ids.add(aid)
            self.stats["manifest_rows_written"] += 1
            return True
        except Exception:
            self.stats["index_write_errors"] += 1
            self.stats["artifacts_skipped"] += 1
            return False

    def observe_bob(self, payload: Any) -> None:
        for item in payload.get("articles", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            contract = item.get("canonical_source_body")
            if source_body.valid_contract(contract):
                data = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self._retain(item, data, stem="source", extension="json", fmt="json", agent="Bob",
                             stage="generation", roles=["source_material"], purpose="source_material",
                             authority="authoritative", artifact_schema={"status": "known", "version": source_body.SCHEMA})
            if item.get("status") == "ready_for_alfred" and isinstance(item.get("body_html"), str) and item["body_html"]:
                self._retain(item, item["body_html"].encode("utf-8"), stem="bob", extension="html", fmt="html",
                             agent="Bob", stage="generation", roles=["translated_candidate"],
                             purpose="translated_candidate_material")

    def observe_alfred(self, payload: Any) -> None:
        allowed = ("source_url", "decision", "quality_score", "issues", "warnings", "editorial_changes", "diagnostics")
        for review in payload.get("reviews", []) if isinstance(payload, dict) else []:
            if not isinstance(review, dict):
                continue
            metadata = {key: review[key] for key in allowed if key in review}
            data = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self._retain(review, data, stem="alfred", extension="json", fmt="json", agent="Alfred",
                         stage="quality", roles=["quality_review"], purpose="quality_review", authority="diagnostic")
            approved = review.get("approved_article")
            if isinstance(approved, dict) and isinstance(approved.get("body_html"), str) and approved["body_html"]:
                identity = dict(approved)
                identity.setdefault("source_url", review.get("source_url"))
                self._retain(identity, approved["body_html"].encode("utf-8"), stem="alfred-body", extension="html",
                             fmt="html", agent="Alfred", stage="quality",
                             roles=["quality_review", "translated_candidate"], purpose="translated_candidate_material")

    def observe_publisher(self, payload: Any) -> None:
        for result in payload.get("results", []) if isinstance(payload, dict) else []:
            if not isinstance(result, dict) or result.get("status") != "published":
                continue
            representation = "published_cleaned_full_text"
            text = result.get(representation)
            if not isinstance(text, str) or not text:
                representation = "cleaned_full_text"
                text = result.get(representation)
            if isinstance(text, str) and text:
                final = {"schema": "owtv_p1_2_published_text_v1", "representation": representation,
                         "source_url": str(result.get("source_url") or result.get("url") or ""), "text": text}
                data = json.dumps(final, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self._retain(result, data, stem="final", extension="json", fmt="json",
                             agent="Publisher", stage="publication", roles=["final_published_material"],
                             purpose="final_published_material", authority="supporting",
                             artifact_schema={"status": "known", "version": "owtv_p1_2_published_text_v1"})
            else:
                self.stats["artifacts_attempted"] += 1
                self.stats["artifacts_skipped"] += 1

    def observe_editorial_director_shadow(self, snapshot: Mapping[str, Any], output: Mapping[str, Any],
                                           legacy_menzo: Mapping[str, Any], result: Mapping[str, Any]) -> None:
        """Retain immutable per-candidate diagnostic packages, never production material."""
        legacy: dict[str, Any] = {}
        for section, action in (("selected", "SELECT"), ("pending", "DEFER"), ("skipped", "SKIP")):
            for item in legacy_menzo.get(section, []) if isinstance(legacy_menzo, Mapping) else []:
                if isinstance(item, Mapping) and article_id(item):
                    legacy[article_id(item)] = {"action": action, "class": item.get("priority"),
                                                "category": item.get("category") or item.get("category_hint")}
        rows = {x.get("candidate_id"): x for x in output.get("candidates", []) if isinstance(x, Mapping)}
        relations = output.get("relations", []) if isinstance(output.get("relations"), list) else []
        artifact_by_candidate: dict[str, str] = {}
        for candidate in snapshot.get("candidates", []):
            cid = candidate.get("candidate_id")
            package = {"artifact_schema_version": "owtv_editorial_director_shadow_v1",
                "candidate": {k: candidate.get(k) for k in ("candidate_id", "title", "summary", "source", "feed_url", "url", "published", "origin")},
                "input_coverage": candidate.get("input_coverage"), "director_output": rows.get(cid),
                "relations": [x for x in relations if x.get("left_id") == cid or x.get("right_id") == cid],
                "run_id": snapshot.get("run_id"), "logical_request_id": result.get("logical_request_id"),
                "input_digest": snapshot.get("input_digest"), "validation_status": result.get("status"),
                "legacy_menzo": legacy.get(cid)}
            data = json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            identity = {"url": candidate.get("url"), "source_url": candidate.get("url"), "title": candidate.get("title")}
            retained = self._retain(identity, data, stem="editorial-director-shadow", extension="json", fmt="json",
                agent="Menzo", stage="selection", roles=["diagnostic_output"], purpose="pipeline_observability",
                authority="diagnostic", artifact_schema={"status": "known", "version": "owtv_editorial_director_shadow_v1"})
            if retained:
                stable_cid = content_id(identity)
                run_token = hashlib.sha256(self.run_id.encode("utf-8")).hexdigest()[:20]
                path = (self.material_root / run_token / stable_cid /
                        f"editorial-director-shadow-{hashlib.sha256(data).hexdigest()[:20]}.json")
                artifact_path = path.resolve().relative_to(self.repository_root).as_posix()
                artifact_by_candidate[str(cid)] = artifact_path
                from agents.canonical_event_ledger import active_event
                active_event("stage_completed", "Menzo", "selection", "success", item=identity,
                             result="editorial_director_shadow_evaluated",
                             reason_code="editorial_director_shadow", artifact=artifact_path)
        from agents.canonical_event_ledger import active_event
        for relation in relations:
            paths = [artifact_by_candidate.get(str(relation.get(key))) for key in ("left_id", "right_id")]
            path = next((value for value in paths if value), "")
            if path:
                active_event("stage_completed", "Menzo", "duplicate", "success",
                             result="editorial_director_shadow_evaluated",
                             pair_id=relation.get("pair_id"), logical_request_id=result.get("logical_request_id"),
                             reason_code="editorial_director_shadow", artifact=path)
