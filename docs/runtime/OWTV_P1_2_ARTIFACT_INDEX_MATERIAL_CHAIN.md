# P1.2 Canonical Artifact Index and Material Chain

Implementation version: `v95.24_p1_2_artifact_index_material_chain`.

P1.2 is fail-open measurement infrastructure for the standard article chain only. It does not alter agents,
publication, policies, prompts, model routing, reports, or Simone report material. The UTF-8 append-only JSONL
index defaults to `state/newsroom/canonical_artifact_index.jsonl`; immutable bytes default to
`state/newsroom/material_chain/`. `OWTV_CANONICAL_ARTIFACT_INDEX_PATH` and `OWTV_MATERIAL_CHAIN_ROOT` override
those locations. `OWTV_CANONICAL_ARTIFACT_INDEX_ENABLED` defaults to true and recognizes `0`, `false`, `no`,
and `off` as false.

## Identity and immutable layout

The artifact ID is `afi_` plus SHA-256 of the UTF-8 sequence
`run_id NUL content_id NUL producer_stage NUL joined_semantic_roles NUL artifact_byte_sha256`.
`content_id` and `correlation_id` come exclusively from P1.1. Archive paths are
`<material-root>/<first-20-hex-of-SHA256(run_id)>/<content_id>/<role-stem>-<first-20-hex-of-byte-SHA256>.<ext>`.
Titles, slugs, indexes, and WordPress IDs are not identity inputs. Existing equal bytes are verified and reused;
different bytes are never overwritten. Existing artifact IDs loaded from the index and an in-process ID set prevent
duplicate appends without rewriting the ledger.

## Retention rules and authority

* Bob source JSON is retained only when `source_body.valid_contract(canonical_source_body)` succeeds. Its
  lossless canonical JSON is authoritative for `source_material`; no hydration or fetching occurs.
* Bob HTML is retained byte-for-byte only for non-empty `ready_for_alfred` candidates and is supporting
  `translated_candidate_material`.
* Alfred receives a minimized diagnostic JSON review. A non-empty `approved_article.body_html` is separately
  retained byte-for-byte; absent bodies are never fabricated.
* Publisher final material is considered only for item rows whose status is exactly `published`. The preferred
  `published_cleaned_full_text` (or fallback `cleaned_full_text`) is preserved without text normalization inside a
  minimal `owtv_p1_2_published_text_v1` JSON artifact. It has **supporting** final-material authority: it is a
  lossless representation of Publisher's successful result field, not exact authoritative WordPress HTML. All other
  statuses and unresolved representations are skipped.

Because its physical location is under `state/newsroom`, all P1.2 material uses storage class `runtime_state`.
All material is classified `immutable_archive` / `immutable` with persistent fixed-contract retention. Failures in
initialization, hashing, validation, directories, archive writes, or index appends are contained and appear only in
`run_summary.canonical_artifact_index`. No retained body or manifest row is placed in the summary. P1.3 request
identity, P1.4 reader migration, pruning, rotation, and special Simone/report retention are explicitly out of scope.

Validator material-chain coverage is keyed by P1.1 `correlation_id`. Consequently, each reported chain is one
run/content instance; stages from separate runs are never combined even when their global `content_id` is identical.
