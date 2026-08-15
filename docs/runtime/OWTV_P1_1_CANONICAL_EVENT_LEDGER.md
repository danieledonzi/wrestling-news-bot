# OWTV P1.1 canonical event ledger

Implementation `v95.23_p1_1_canonical_event_ledger_identity` adds a parallel,
observational ledger. It does not change newsroom decisions or payloads.

## Operation

Events are UTF-8 JSON objects appended, one per line, to
`state/newsroom/canonical_event_ledger.jsonl`. Set
`OWTV_CANONICAL_LEDGER_PATH` to override the path. Emission defaults on; set
`OWTV_CANONICAL_LEDGER_ENABLED` to `0`, `false`, `no`, or `off` to roll it back.
Validation, identity, directory, and append failures are counted and logged but
fail open: they cannot change the editorial exit path. Import or initialization
failure installs a no-op observer and exposes `initialization_error` in the run
summary, so agent execution and master-log writing still continue.

Rows implement the frozen `owtv_event_schema_v1` / `v95.22_a2` envelope. The
runtime caches that contract and resolves `code_commit` once per emitter.
Validate a ledger with:

```bash
PYTHONPATH=. python scripts/validate_canonical_event_ledger.py [ledger.jsonl]
```

## Identity and coverage

The duplicate subsystem's canonical URL normalization is reused. `content_id`
is `cnt_` plus SHA-256 of that URL; existing `article_id` remains `art_` plus
the same hash. `correlation_id` is `corr_` plus SHA-256 of
`run_id + NUL + content_id`. Report-only correlation uses the distinct material
`report + NUL + run_id + NUL + report_key`; a report key never becomes a
content ID. A URL-backed report always retains the normal content correlation;
the report-only correlation namespace is used only when no source URL resolves.
`story_id` is intentionally not fabricated.

Massy's observable universe is the unique URL-backed union of
`news_candidates_for_menzo`, `report_candidates`, `hard_skipped`, and
`already_worked`. Aggregate `found_urls` cannot create rows. The observer emits
item evidence where available for run start/completion, Massy seen/skipped,
Simone candidates/selections/publications, Menzo selected/pending/skipped,
Andrea sufficiency, Bob requests/generated articles, Alfred reviews, Publisher
attempts/completions/already-present results, and Archivista completion.
Simone selections are observed from its production `ready_reports` rows rather
than aggregate handoff counts. Bob request evidence references the immediate
Andrea pre-Bob artifact.

Bob emits `article_generated` only for item rows whose runtime status is
`ready_for_alfred`; extraction-empty, translation-pending, and error packages
remain intentionally without a successful generation event. Publisher attempts
are reconstructed after Publisher returns from actual item rows in
`publisher_result.json` (`published`, `already_published`, `dry_run`,
`wp_not_ready`, `publish_error`, or `skipped/missing_url_or_title`). Duplicate
safety and capacity exclusions are not attempts. P1.1 does not turn non-success
outcomes into canonical failures.

Artifact references require a non-empty `path` and an input/output/evidence
`relation`; A2 optional `artifact_type`, `schema_version`, and lowercase
SHA-256 fields are accepted. The standalone validator additionally proves that
content and report-only correlations equal their deterministic P1.1 algorithms.
Envelope validation requires `timestamp_utc` to be a valid RFC 3339 timestamp
with an explicit UTC `Z` or `+00:00` timezone.

## Boundaries

The ledger contains references rather than bodies, HTML, prompts, or model
responses. It is append-only and non-authoritative: the canonical ledger is not
yet the authority for current daily reports, master log, or Gemini ledger.
P1.2 adds artifact indexing. P1.3 adds model attempt, fallback, error, and
warning taxonomy. P1.4 migrates observability readers. Consequently exhaustive
A2 stage/model/failure/warning/blocker events, terminal error classification,
and artifact indexing are intentionally deferred. No editorial, Gemini,
WordPress, scheduling, or report-selection behavior changes in P1.1.
