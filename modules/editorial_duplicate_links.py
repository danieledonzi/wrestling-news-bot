"""Read-only derivative of validated Menzo decisions for future hyperlinks.

Never infer semantic equivalence, traverse duplicate components, or use a
temporary model cache as authority. The source manifest is append-only;
the index is rebuildable and does not participate in editorial decisions.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from agents.duplicate_pair_identity import article_id, recent_history_pair_id, same_run_pair_id
from modules.editorial_internal_links import source_identity

INDEX_NAME = "editorial_duplicate_link_index_v1.json"
MANIFEST_NAME = "canonical_artifact_index.jsonl"
VERSION = "editorial-duplicate-links-v1"
SCHEMA = "owtv_editorial_director_active_v3"
_ID = re.compile(r"art_[0-9a-f]{64}")
MAX_ARTIFACT_BYTES = 8_000_000


def _id(value):
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _safe_identity(url):
    """Menzo IDs drop query and collapse slashes; never resolve those variants."""
    key = source_identity(url)
    if key is None or key[4] or "//" in key[3]:
        return None
    return key


def _token(url):
    key = _safe_identity(url)
    return json.dumps(key, separators=(",", ":")) if key is not None else ""


def _pair(left, right):
    return "|".join(sorted((left, right)))


def _empty():
    return {"version": VERSION, "cursor": {}, "urls": {}, "pairs": {}, "skips": {}, "stats": {"artifacts": 0, "gate_skips": 0, "direct": 0}}


def _read_index(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if (isinstance(value, dict) and value.get("version") == VERSION
                and all(isinstance(value.get(k), dict) for k in ("cursor", "urls", "pairs", "skips", "stats"))):
            return value
    except (OSError, ValueError, TypeError):
        pass
    return _empty()


def _remember(mapping, key, value):
    values = mapping.setdefault(key, [])
    if value not in values:
        values.append(value)


def _active_manifest(row):
    return (row.get("producer_agent") == "Menzo"
            and row.get("producer_stage") == "selection"
            and row.get("semantic_roles") == ["selection_decision"]
            and row.get("artifact_schema_version") == {"status": "known", "version": SCHEMA}
            and row.get("persistence_class") == "immutable_archive"
            and row.get("mutation_mode") == "immutable"
            and {"purpose": "pipeline_observability", "level": "authoritative"} in row.get("authority_claims", []))


def _read_artifact(row, root, material_root):
    path = (root / row["path"]).resolve()
    if not path.is_relative_to(material_root) or not path.name.startswith("editorial-director-active-"):
        raise ValueError("invalid_active_artifact_path")
    size = row.get("size_bytes")
    if type(size) is not int or not 0 < size <= MAX_ARTIFACT_BYTES or path.stat().st_size != size:
        raise ValueError("invalid_active_artifact_size")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row.get("sha256"):
        raise ValueError("active_artifact_digest_mismatch")
    package = json.loads(data)
    if (not isinstance(package, dict) or package.get("artifact_schema_version") != SCHEMA
            or package.get("run_id") != row.get("run_id")):
        raise ValueError("active_artifact_binding_mismatch")
    return package


def _observe(index, row, package):
    if package.get("validation_status") != "VALIDATED":
        return
    candidate = package.get("candidate")
    if not isinstance(candidate, dict):
        raise ValueError("invalid_active_candidate")
    url, cid = candidate.get("url"), candidate.get("candidate_id")
    if not isinstance(url, str) or not _id(cid) or article_id({"url": url}) != cid or row.get("article_id") != cid:
        raise ValueError("active_candidate_identity_mismatch")
    _remember(index["urls"], cid, _token(url))
    index["stats"]["artifacts"] += 1
    relations = package.get("relations")
    if not isinstance(relations, list):
        raise ValueError("invalid_active_relations")
    direct = set()
    for rel in relations:
        if not isinstance(rel, dict):
            raise ValueError("invalid_active_relation")
        left, right, scope = rel.get("left_id"), rel.get("right_id"), rel.get("scope")
        if not _id(left) or not _id(right) or left == right:
            raise ValueError("invalid_active_relation_identity")
        if scope == "same_run":
            expected = same_run_pair_id(left, right)
        elif scope == "recent_history":
            expected = recent_history_pair_id(left, right)
        else:
            raise ValueError("invalid_active_relation_scope")
        if expected != rel.get("pair_id"):
            raise ValueError("invalid_active_pair_binding")
        decision = rel.get("decision")
        duplicate = decision == "DUPLICATE" and not rel.get("new_fact")
        pair = _pair(left, right)
        # Any contrary validated decision for the same endpoints vetoes reuse.
        index["pairs"][pair] = index["pairs"].get(pair, 0) | (1 if duplicate else 2)
        if duplicate and scope == package.get("semantic_duplicate_scope"):
            if scope == "recent_history" and left == cid:
                direct.add(right)
            elif scope == "same_run" and cid in {left, right}:
                direct.add(right if left == cid else left)
    if package.get("decision_authority") != "semantic_duplicate_gate":
        return
    index["stats"]["gate_skips"] += 1
    winner = package.get("semantic_duplicate_of")
    # Retain ambiguous and unsupported dispositions as veto evidence, not aliases.
    evidence_ids = candidate.get("semantic_duplicate_evidence_pair_ids")
    supported = (_id(winner) and winner != cid and winner in direct
                 and package.get("director_output") is None
                 and candidate.get("semantic_duplicate_of") == winner
                 and candidate.get("semantic_duplicate_scope") == package.get("semantic_duplicate_scope")
                 and isinstance(evidence_ids, list)
                 and any(isinstance(r, dict) and r.get("pair_id") in evidence_ids
                         and r.get("decision") == "DUPLICATE" and not r.get("new_fact")
                         and {r.get("left_id"), r.get("right_id")} == {cid, winner}
                         and r.get("scope") == package.get("semantic_duplicate_scope")
                         and (r.get("scope") != "recent_history" or r.get("left_id") == cid)
                         for r in relations)
                 and candidate.get("semantic_duplicate_reason") != "semantic_same_run_duplicate_covered_by_update")
    _remember(index["skips"], cid, winner if supported else "")
    if supported:
        index["stats"]["direct"] += 1


def _boundary(handle, offset):
    handle.seek(max(0, offset - 4096))
    return hashlib.sha256(handle.read(min(offset, 4096))).hexdigest()


def _write(path, index):
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=path.name+".", delete=False) as handle:
            tmp = Path(handle.name)
            json.dump(index, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def refresh_duplicate_index(state_dir: Path, root: Path, *, index_dir: Path | None = None):
    """Consume new manifest records only; a failed refresh cannot return stale aliases."""
    manifest = state_dir / MANIFEST_NAME
    path = (index_dir or state_dir) / INDEX_NAME
    if not manifest.is_file():
        return _empty()
    index = _read_index(path)
    material_root = (state_dir / "material_chain").resolve()
    with manifest.open("rb") as handle:
        stat = os.fstat(handle.fileno())
        cursor = index["cursor"]
        offset = cursor.get("offset", 0)
        if (type(offset) is not int or offset < 0 or offset > stat.st_size
                or cursor.get("dev") != stat.st_dev or cursor.get("ino") != stat.st_ino
                or cursor.get("boundary") != _boundary(handle, offset)):
            index = _empty()
            offset = 0
        if offset == stat.st_size and index["cursor"]:
            return index
        handle.seek(offset)
        while handle.tell() < stat.st_size:
            line = handle.readline(stat.st_size - handle.tell())
            if not line.endswith(b"\n"):
                raise ValueError("incomplete_manifest_record")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("invalid_manifest_record")
            if _active_manifest(row):
                package = _read_artifact(row, root, material_root)
                _observe(index, row, package)
        # Do not commit a cursor over a changed or concurrently replaced manifest.
        end = os.fstat(handle.fileno())
        current = manifest.stat()
        if end.st_size != stat.st_size or current.st_ino != stat.st_ino or current.st_dev != stat.st_dev:
            raise ValueError("manifest_changed_during_refresh")
        index["cursor"] = {"offset": stat.st_size, "dev": stat.st_dev, "ino": stat.st_ino,
                           "boundary": _boundary(handle, stat.st_size)}
    path.parent.mkdir(parents=True, exist_ok=True)
    _write(path, index)
    return index


def duplicate_link_records(index, history):
    """Map a skipped exact URL to directly evidenced, unambiguous news history."""
    if not isinstance(history, dict):
        return {}
    by_id = {}
    history_tokens = {}
    for row in history.values():
        if not isinstance(row, dict):
            continue
        url = row.get("source_url")
        if not isinstance(url, str) or not url:
            continue
        try:
            cid = article_id({"url": url})
        except (TypeError, ValueError):
            continue
        if not _id(cid):
            continue
        _remember(history_tokens, cid, _token(url))
        by_id.setdefault(cid, []).append(row)
    result = {}
    for cid, winners in index["skips"].items():
        if len(winners) != 1 or not _id(winners[0]):
            continue
        winner = winners[0]
        if index["pairs"].get(_pair(cid, winner)) != 1 or cid in by_id:
            continue
        # A target also eliminated by Menzo is not a terminal representative.
        if winner in index["skips"]:
            continue
        sources = index["urls"].get(cid, [])
        destinations = set(index["urls"].get(winner, [])) | set(history_tokens.get(winner, []))
        if len(sources) != 1 or not sources[0] or len(destinations) != 1 or "" in destinations:
            continue
        rows = by_id.get(winner)
        if rows:
            result[tuple(json.loads(sources[0]))] = rows
    return result
