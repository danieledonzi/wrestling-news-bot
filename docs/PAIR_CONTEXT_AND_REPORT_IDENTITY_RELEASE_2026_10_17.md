# Bounded report identity and duplicate context fixes — 2026-10-17

Owner authorization: 2026-10-17. Correct the two observed harmful patterns after regression testing; preserve the recent editorial equilibrium. Baseline: main `ad848e344ab2fdf207ffe6beafb2b7133e83e4e3` (PR161).

## Report identity

A Wrestleview viewership article was accepted as an Impact results report because its category folder was `impact-wrestling-results`; a generated pending title and its publication timestamp could then reinforce the false identity/date. Source identity now uses the original source headline and the final article slug, excluding category folders and URL query parameters. A stored source headline takes precedence over the generated OWTV title. Wrestleview fallback also requires an explicit show date in that source identity; publication time alone cannot establish the show date.

No global weekday veto was added: a real dated results report for a rescheduled show must still replay. Ringside priority, 08:30 fallback election, permanent source lock, full text/media translation and report/news separation remain unchanged. Eight report regressions include the real false source, generated-title pending replay, genuine dated slugs and a legitimate rescheduled-show replay. Six fail on the baseline; all eight pass after the fix.

## Duplicate context boundaries

Admission still elects sparse pairs from article meaning, independently of primary classification. Each request now has exactly one current `anchor`, plus eligible current/history `targets`. Only anchor-to-target suspicions are legal. Same-run unordered pairs are offered once; two targets cannot authorize a comparison that does not involve the anchor. The bound response schema and local structural validation enforce this boundary. This is not a lexical/entity filter or an all-pairs judgment matrix.

Each admitted pair is then judged in its own request containing exactly its two endpoints and a single `r0` decision. The duplicate judgment policy remains **V4, byte-for-byte unchanged**; V7 changes only the provider schema's cardinality/reference binding. An unavailable/invalid pair cannot prevent later independent pairs from being judged. Valid decisions are persisted, and unresolved components retain the existing technical HOLD. There are no repair calls or new semantic validator vetoes.

First classifications, terminal SKIP memory, publisher history/lookback, complete source bodies, important-update threshold, same-run A+B coverage, richer-source/arrival arbitration, soft competition and pacing are unchanged. Admission input-profile telemetry now counts `anchor` and `targets`; provider attempts remain separately observable. Admission and pair contract fingerprints change; no primary or terminal memory is cleared. More individual requests can be made for a cohort, so aggregate latency/tokens should be observed rather than assumed unchanged. Exact-material success clearance, pair caching and failure backoff remain active.

## Evidence and limitations

All checks run with the installed VPS Python/venv in an isolated `/tmp` checkout. No producer run or WordPress write was used for testing.

- Full regression suite: 1,793 passing tests, with one pre-existing oversized-body recovery test excluded after reproducing its same `IndexError` on the baseline. The complete run before the final four new boundary tests had 1,789 passes and that same single failure. The unrelated recovery mechanism was not modified.
- Eleven clear retained-body controls: eight unrelated fact pairs and three real duplicates (PAC, R-Truth, Montez Ford). The isolated judgment replay correctly distinguishes these, including Copeland/WrestleMania, GUNTHER/Gowen, Regal/Copeland, Samoa Joe/Dragunov and PAC/injury news. A separate unique-URL mixed-context stress replay reproduces wrong endpoint/fact assignments; it is not presented as an exact historical run.
- An exact, hash-verified reconstruction of the October 16 09:47 UTC admission input (two current articles, eight history articles) reproduces a false GUNTHER/Gowen suspicion with the old request. Both anchored requests return no suspicion. A complete Copeland cohort replay was not claimed because one retained body's digest had changed; the isolated Copeland pair controls are available.
- The final replay using unchanged V4 judgment instructions and the one-pair V7 schema returns all 12 expected decisions. Crown Jewel remains a borderline control, not a guaranteed future pass: the older full article already mentions a backup plan, while the later one specifies a ready U.S. venue. Repeated single-pair trials produce both DUPLICATE and MATERIAL_UPDATE under the existing V4 policy as well as the provisional V5 prefix tested during investigation. V5 was not adopted. This fix does not alter the update threshold to force that case.
- Deterministic regressions continue to exercise true updates, explicit same-run A+B covering-side selection, preservation of both articles when coverage is absent, published-history precedence, cache reuse, frozen classes and terminal skips. New regressions enforce exact per-request endpoints and independent progress after a first-pair failure.

Replay outcomes support a bounded context fix, not a guarantee that Gemini will never make another semantic error. Continue the approved daily observation process. No additional editorial reform is proposed here.

The already published false Impact report and previous terminal decisions are not rewritten or reopened by this release.
