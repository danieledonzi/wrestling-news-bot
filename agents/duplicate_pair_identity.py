"""Stable technical identities for deterministic duplicate-pair coverage."""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from agents.menzo_duplicate_scorer import canonical_source_url

IDENTITY_VERSION = "canonical_source_url_sha256_v1"
PAIR_IDENTITY_VERSION = "scoped_article_pair_sha256_v1"


def article_id(item: Mapping[str, Any]) -> str:
    """Return the stable source-URL identity, or ``""`` when it is unresolved."""
    canonical = canonical_source_url(dict(item))
    if not canonical or not canonical.split("://", 1)[-1].split("/", 1)[0]:
        return ""
    return "art_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def same_run_pair_id(article_id_a: str, article_id_b: str) -> str:
    left, right = sorted((article_id_a, article_id_b))
    material = f"same_run\0{left}\0{right}"
    return "pair_sr_" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def recent_history_pair_id(candidate_article_id: str, published_article_id: str) -> str:
    material = f"recent_history\0{candidate_article_id}\0{published_article_id}"
    return "pair_rh_" + hashlib.sha256(material.encode("utf-8")).hexdigest()
