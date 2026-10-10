# Owner corrections: bookmaker exclusion, terminal SKIP and semantic admission

Authority: the owner's 2026-10-10 ratification of TOTEM-N02/S01/D01 and instruction to implement autonomously.
This release supersedes the earlier deterministic lexical admission and soft-tombstone comparison exceptions.

## Resulting behavior

- Clearly identified bookmaker-odds articles close before Gemini calls, including odds immediately before a PLE.
  Ambiguous legal/business developments that mention betting still reach Gemini's central-fact classification.
  V8 explicitly excludes articles centrally reporting odds, market movements or odds-derived predictions.
- Valid editorial SKIP closes the canonical URL permanently. Legacy available SKIP records remain effective beyond
  their old 168-hour expiry. Feed metadata changes, midnight and cache expiry cannot reopen an URL. Deleted
  historical records cannot be reconstructed from the blocklist alone; this release does not rewrite audit history.
- SKIP URLs cannot enter either semantic endpoint table. Soft tombstones remain audit/same-URL memory only.
  A new Director SKIP overrides any prior soft admission and drains the persistent strong queue.
- Valid SKIPs survive unrelated duplicate-provider failures and later handoff write failures. A corrupt permanent
  memory fails technically rather than silently becoming an empty blocklist. Memory writes remain atomic.
- Primary Gemini classification also supplies a sparse list of potential shared central developments from compact
  factual current/history tables. This adds no normal extra primary operation and sends no pair matrix. Promotion,
  show, generic match/action wording, incidental names and lexical scores cannot authorize a semantic comparison.
- Only Gemini-admitted pairs enter the existing full-material duplicate gate. Local ref/scope/coverage validation
  and bounded repair remain technical safeguards. Technically valid Gemini verdicts remain final; there is no second
  semantic confirmation. Accepted classes cannot change during admission repair, and accepted SKIP disappears from
  repair input. A later admission response cannot omit a same-contract cached final DUPLICATE for unchanged material.
- Soft Board uses the same admission/gate authority. Unchanged factual context reuses its clearance; changed pool,
  history, policy or material triggers review. Endpoint batches preserve its ability to review a pool larger than the
  primary candidate limit. A provider outage holds recoverable soft URLs without inventing terminal competition loss.

## Boundaries and validation

Successful Publisher history remains 12 hours. The Henry/24-hour question is unchanged. Reports create no news URLs
and never replace individual feed MUST/SHOULD news. Live-show coverage and strong-news priority remain unchanged.
Old-contract pair verdicts cannot supply V8 clearance; no history/cache reset is needed.

The regression suite covers odds/incidental betting, permanent legacy SKIP, both endpoint exclusions, 86 skipped
history rows, the unrelated final-card/EVOLVE subjects, new SKIP over carried soft, technical holds, immutable classes
during admission repair, cached final decisions, unchanged clearance, invalid refs and large/batched pools. Offline
mocked providers establish control flow and authority, not real Gemini accuracy or a measured savings percentage.
Production assessment should measure admitted pairs, gate calls, technical failures and ledger costs from subsequent
scheduled runs. Admission motivations/version are retained in Active telemetry.

Run `python -m pytest -q tests` (root collection contains historical operational scripts with side effects).
Deployment closure requires the merged source on the VPS, Python 3.9 compilation/import/schema checks and the full
suite in an isolated checkout using the production interpreter. Do not reset state, Publisher history or report IDs.
Finite review closes after these checks; new observed incidents justify a separate scoped investigation.
