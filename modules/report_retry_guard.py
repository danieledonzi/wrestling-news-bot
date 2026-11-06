"""Source-aware, bounded report retry guard. No editorial outcome inference.

Only objectively unfinished postshow sources and repeated terminal provider-contract
failures can defer work.  Every source-content or declared contract change unlocks it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from modules.report_content import CONTENT_SELECTORS, NOISE_SELECTOR

CONTRACT_VERSION = "postshow_source_retry_v1_20261106"
STATE_DIR = Path(__file__).resolve().parents[1] / "state" / "newsroom" / "report_retry_guard_v1"
TEXT_TYPES = {"heading", "paragraph", "quote"}
UNFINISHED_RE = re.compile(
    r"\b(?:update(?:s)? coming|results? (?:to follow|coming soon|will be updated)|"
    r"check back (?:for|soon)|live updates? (?:to follow|coming soon)|"
    r"match(?:es)? (?:currently )?in progress)\b", re.I
)
MATCH_PREVIEW_RE = re.compile(r"\b(?:vs\.?|versus)\b|\b(?:championship|title)\b[^.]{0,45}\b(?:match|challenge)\b", re.I)
EXPLICIT_NOT_HELD_RE = re.compile(r"\b(?:cancelled|canceled|postponed|scrapped|replaced|called off|did not take place|didn't happen)\b", re.I)


class ReportRetryDeferred(RuntimeError):
    """Report stays pending. Never represents a completed/published show."""

    def __init__(self, reason: str, source_digest: str, *, key: str = "") -> None:
        self.reason = reason
        self.source_digest = source_digest
        self.report_key = key
        super().__init__(f"report_retry_deferred:{reason}:digest={source_digest[:16]}")



def route_contract_version(models: list[str]) -> str:
    """Unlock terminal failures when the effective provider route changes."""
    signature = hashlib.sha256(json.dumps(list(models), separators=(",", ":")).encode()).hexdigest()[:20]
    return f"{CONTRACT_VERSION}:models:{signature}"


def original_source_unfinished(source_html: str | None) -> bool:
    """Inspect only the article body before boilerplate sentence cleanup.

    Promotional 'please check back' text is often removed by clean_source_prose;
    it must remain available as *evidence* for the pre-provider check, never
    copied into the published Italian report.
    """
    if not source_html:
        return False
    soup = BeautifulSoup(source_html, "html.parser")
    root = next((node for selector in CONTENT_SELECTORS
                 if (node := soup.select_one(selector)) is not None), None)
    if root is None:
        return False
    for node in root.select(NOISE_SELECTOR):
        node.decompose()
    return any(UNFINISHED_RE.search(node.get_text(" ", strip=True))
               for node in root.find_all(("p", "li", "blockquote")))


def _identity(job: dict[str, Any]) -> str:
    # Source identity, report identity and date: separate shows cannot share a lock.
    url = str(job.get("source_url") or "")
    parsed = urlsplit(url)
    source = f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    values = [str(job.get(k) or "") for k in ("report_key", "date", "date_local", "report_id", "event_key", "night_key")]
    return hashlib.sha256(json.dumps([*values, source], separators=(",", ":")).encode()).hexdigest()


def digest_blocks(blocks: list[dict[str, Any]]) -> str:
    material = [{"type": b.get("type"), "text": re.sub(r"\s+", " ", str(b.get("text") or "")).strip(),
                 "url": b.get("url"), "src": b.get("src")} for b in blocks]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _state_path(job: dict[str, Any], state_dir: Path | None = None) -> Path:
    return (state_dir or STATE_DIR) / (_identity(job) + ".json")


def _read(job: dict[str, Any], state_dir: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads(_state_path(job, state_dir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save(job: dict[str, Any], state: dict[str, Any], state_dir: Path | None = None) -> None:
    path = _state_path(job, state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".report-retry-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as writer:
            json.dump(state, writer, ensure_ascii=False, indent=2, sort_keys=True)
            writer.write("\n")
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def source_completion_issue(blocks: list[dict[str, Any]], plan: dict | None, *, original_html: str | None = None) -> str | None:
    """Positive proof of an unfinished source, NOT a global readiness threshold.

    A safely bounded preview and explicit pending-updates marker are both required.
    Unknown, changed or cancelled matches are not inferred to be held.
    Sources without a separable preview are never suppressed by this heuristic.
    """
    if not plan or not plan.get("preview_indexes"):
        return None
    previews = [str(blocks[i].get("text") or "") for i in plan["preview_indexes"]]
    expected_matches = sum(bool(MATCH_PREVIEW_RE.search(t)) for t in previews)
    if expected_matches < 2:
        return None
    actual = len(set(plan.get("result_indexes") or []))
    narrative = [str(blocks[i].get("text") or "") for i in plan.get("source_indexes", []) if blocks[i].get("type") in TEXT_TYPES]
    if not narrative:
        return "missing_postshow_narrative"
    unfinished = original_source_unfinished(original_html) or any(UNFINISHED_RE.search(t) for t in narrative)
    explicitly_not_held = sum(bool(EXPLICIT_NOT_HELD_RE.search(t)) for t in narrative)
    # Never claim an upcoming match happened merely because the preview lists it.
    # An explicit "updates coming" marker with several unresolved bouts is strong
    # evidence of an unfinished live article (unlike an unknown outcome alone).
    if unfinished and actual + explicitly_not_held < expected_matches:
        return "source_results_still_updating"
    if unfinished and actual == 0:
        return "source_without_completed_match_results"
    return None


def preflight(job: dict[str, Any], blocks: list[dict[str, Any]], plan: dict | None,
              *, contract_version: str = CONTRACT_VERSION, state_dir: Path | None = None,
              original_html: str | None = None) -> str:
    """Return digest if eligible; otherwise defer with actionable reason.

    Always rescrape outside this function: changed source or contract unlocks it.
    """
    digest = digest_blocks(blocks)
    key = str(job.get("report_key") or "")
    issue = source_completion_issue(blocks, plan, original_html=original_html)
    if issue:
        _save(job, {"schema": 1, "reason": issue, "source_digest": digest,
                    "contract_version": contract_version, "kind": "source_incomplete"}, state_dir)
        raise ReportRetryDeferred(issue, digest, key=key)
    saved = _read(job, state_dir)
    if (saved.get("kind") == "terminal_model_contract"
            and saved.get("source_digest") == digest
            and saved.get("contract_version") == contract_version):
        raise ReportRetryDeferred("unchanged_source_terminal_contract", digest, key=key)
    return digest


def mark_terminal_contract(job: dict[str, Any], source_digest: str, *, error: Exception,
                           contract_version: str = CONTRACT_VERSION, state_dir: Path | None = None) -> None:
    """Only persist a terminal *validation* failure, never upstream timeouts/429."""
    _save(job, {"schema": 1, "kind": "terminal_model_contract", "reason": "provider_contract_invalid",
                "source_digest": source_digest, "contract_version": contract_version,
                "last_error": str(error)[:300]}, state_dir)
