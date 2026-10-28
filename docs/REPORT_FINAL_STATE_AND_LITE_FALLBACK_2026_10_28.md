# Completed-show report opening and economical fallback

Owner request: reconcile report openings and initial cards with the completed
show, and use `gemini-3.5-flash-lite` as the first fallback before Pro.

## Report behavior

- An explicit pre-show/results heading or recognizable opening narration bounds the
  replaceable source preamble. The chronological report, quotations, final
  segment, media and source block indexes are preserved.
- The first existing translation batch sees the complete source narrative and
  returns the final opening plus a source-indexed card projection. There is no
  additional provider request dedicated to the opening.
- Every announced card item must be accounted for once. Added matches must be
  included; explicit winner/result lines must be represented once. An absent
  result is `UNCONFIRMED`, never an inferred cancellation.
- A played match requires an actual result block. Its public card label and
  result are rendered from the actual match heading and result already
  translated in the body, rather than from the projected preview label.
- Unsupported result methods (for example No Contest instead of DQ), future
  matches presented as played, malformed references and incomplete card coverage
  fail the response contract and advance the existing model fallback chain.
- The initial complete narrative is included only in the first batch, increasing
  input tokens but not the normal number of provider calls. Later batches retain
  the integral translation contract. No existing WordPress posts are republished.
- If a preamble cannot be safely bounded, the existing full translation path is
  retained. The source and completed-show readiness authority are unchanged.

## Model routing and accounting

- Existing multi-model defaults try 3.5 Flash-Lite immediately after their
  configured primary. Report defaults start with 3.1 Flash-Lite, then 3.5
  Flash-Lite, then 2.5 Pro. Existing later fallback models remain available.
- Bob, legacy news translation/title paths, legacy Menzo chains and Alfred's
  resolver defaults include the economical fallback. Menzo's existing legacy
  second-pass model defaults to 3.5 Flash-Lite. This does not introduce retries or
  extra fallback calls in the current bounded single-model editorial/card calls.
- Explicit environment overrides remain authoritative. The checked-in installer
  updates the production multi-model chains while retaining each primary and
  preserving unrelated environment values and file permissions.
- The pricing table adds the verified standard text rates for 3.5 Flash-Lite:
  USD 0.30/M input, 2.50/M output including thinking, 0.03/M cached input. The
  table version changes; existing ledger rows and existing model rates remain
  untouched. Official source: https://ai.google.dev/gemini-api/docs/pricing

## Regression evidence and release

Reduced offline cases cover Raw's Vaquer/Lynch replacement, a future Crown Jewel
announcement, DQ versus No Contest, unknown AAA outcomes, additional actual
results, nested pre-show layout, media order, full body coverage and end-of-show
context beyond the first batch. Mocked provider failures verify Lite before Pro
for both invalid JSON and invalid report contracts.

Read-only first-batch probes use Raw (26 October), Collision (24 October), and
AAA Heroes Inmortales (24 October). These are maintenance provider requests with
their own ledger outside production state; they do not publish or consume a
production queue item. Failed probe responses were used to refine the guards.

Run offline tests in an isolated checkout with the production Python environment:

```sh
python -m pytest -q tests
```

Some historical targeted tests can mutate `config/reports_v92.json` in their
checkout. Restore that test-produced change before another full-suite run or
creating the release commit. Never execute those tests in the production tree.

After merge, deploy while holding `/tmp/owtv-bot.lock`, back up the runtime `.env`,
pull with `--ff-only`, and install the existing environment overrides:

```sh
python scripts/install_lite_fallback_env.py .env
python scripts/install_lite_fallback_env.py .env --apply
```

Verify the deployed commit, compile changed Python files, inspect the effective
chains after loading `.env`, and run read-only rendering/pricing checks. Compare
hashes of production state, artifacts and publication files before and after
deployment; do not start an extra newsroom run or replay a report.

PR review regressions also preserve pre-show headings without the word results,
recognize ordinary present/past-tense win statements while excluding future win
predictions, and render final-card result links through the same marker-aware
renderer as the chronological body.
