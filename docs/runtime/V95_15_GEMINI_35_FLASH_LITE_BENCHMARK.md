# V95.15 Offline Gemini 3.5 Flash-Lite Benchmark

## Measurement-only boundary

This offline harness compares `gemini-3.1-flash-lite` with `gemini-3.5-flash-lite` independently for Bob, Simone, and Menzo. It does not change a production model chain, prompt, validator, score, dedupe decision, state file, ledger, cache, report pipeline, WordPress record, or publication. Production modules are imported lazily only to call prompt builders, pure compactors, parsers, renderers, and validators. The tool never invokes an agent runner or production persistence function.

Every output is placed under the explicit output/run root. Roots below `state/`, `artifacts/newsroom/`, `reports/`, `published/`, and `published_html_review/` are rejected.

## Reproducible source discovery

```bash
python3 tools/gemini_35_flash_lite_benchmark.py discover \
  --artifact-root artifacts \
  --output-root artifacts/model_benchmarks/gemini_35_flash_lite
```

Discovery reads JSON artifacts only. It does not treat arbitrary Markdown, text, HTML, logs, reports, or diagnostics as source articles. Bob requires an explicit original/source field such as `raw_html`, `source_html`, `original_html`, `source_text`, `original_text`, or `extracted_text`; generic translated bodies and final Italian HTML are rejected. Simone requires substantive source blocks. Menzo requires non-empty, production-shaped dictionary records with substantive summaries and, for recent-history cases, both current and published sets.

The requested output tree, all `artifacts/model_benchmarks/` trees, prior inventories/manifests/metrics/reports, and blind-review output are excluded. Candidate records include `source_provenance`, `source_material_field`, `source_language`, `source_material_hash`, and `selection_reason`. Selection is deterministic and stratum-first rather than filesystem-first. Coverage reports missing Bob, Simone, and Menzo strata without fabricating cases. Re-running discovery against the same inputs produces the same manifest.

Inspect the proposal, set top-level `"frozen": true`, save it as `frozen_manifest.json`, then validate it:

```bash
python3 tools/gemini_35_flash_lite_benchmark.py validate \
  --manifest artifacts/model_benchmarks/gemini_35_flash_lite/frozen_manifest.json \
  --require-frozen
```

## Authoritative production prompt boundaries

### Bob

Bob imports `agents.bob` and `agents.bob_policy_v93_15`, thereby installing the production v94.14 prompt guardrails. It applies production extraction, translation-unit construction, prompt building, JSON parsing, rendering, and post-processing to deep copies. Raw response, parsed JSON, rendered body, and post-processed body are retained under the run root.

### Simone

Simone temporarily replaces `modules.report_workshop_v92.generate_json`, invokes the real `translate_report_blocks()`, records every exact production batch prompt, supplies a synthetic valid response only during capture, and restores the original function in `finally`. Each batch is sent separately to both benchmark models. Metrics carry `prompt_id`, `batch_index`, and `batch_total`. The blind package recomposes successful batches by source index into one complete output per model; a missing, failed, or structurally invalid batch marks the complete report invalid.

### Menzo v95.11 batch authority

The benchmark does not use the superseded simple/pairwise helpers. Same-run records receive stable `c0`, `c1`, … IDs through `compact_candidate_record()`, use `build_same_run_batch_prompt()`, and are checked by `validate_same_run_batch()`. The retained result preserves `duplicate_groups`, `keep_id`, `discard_ids`, and `reason` while diagnostics detect invalid survivors, overlapping groups, groups without a survivor, expected-survivor regressions, and expected-unique candidates included in a duplicate group.

Recent-history current records receive `c0`, … IDs and publications receive `p0`, … IDs through `compact_candidate_record()` and `compact_published_record()`. The exact prompt comes from `build_recent_history_batch_prompt()` and validation from `validate_recent_history_batch()`. Diagnostics cover invalid IDs, duplicate blocking, grounded `MATERIAL_UPDATE` facts, generic updates, expected matches, and unmatched current stories incorrectly blocked.

## A/B execution

```bash
GEMINI_API_KEY='...' python3 tools/gemini_35_flash_lite_benchmark.py run \
  --manifest artifacts/model_benchmarks/gemini_35_flash_lite/frozen_manifest.json \
  --output-root artifacts/model_benchmarks/gemini_35_flash_lite/run_001 \
  --models gemini-3.1-flash-lite gemini-3.5-flash-lite \
  --repetitions 1
```

A missing API key stops before creating the run root or making a call. Each model receives the identical prompt through exactly `client.models.generate_content(model=model, contents=prompt)`: no fallback, implicit retry, temperature, thinking budget, or other generation configuration. A/B order alternates deterministically. `--repetitions 2` repeats critical cases only unless `--repeat-all` is explicitly supplied.

Each metric includes `comparison_id`, `prompt_id`, `batch_index`, `batch_total`, call order, hashes, requested and actual model, latency, status/error, raw and parsed paths, structural validity, diagnostics, token usage, and component/total costs. Exact prompts are stored under `prompts/` for audit but are never copied into reviewer-visible output. Failed calls and invalid responses remain metric and blind/report records. Pricing always uses the requested benchmark model; `actual_model` remains independent provenance. Thinking tokens are billed at the output rate from the dated benchmark-local pricing snapshot.

## Blind review package

```bash
python3 tools/gemini_35_flash_lite_benchmark.py blind \
  --run-root artifacts/model_benchmarks/gemini_35_flash_lite/run_001 \
  --seed 9515
```

For each comparison the command creates:

```text
blind_review/cases/<comparison_id>/source.json
blind_review/cases/<comparison_id>/output_A.json
blind_review/cases/<comparison_id>/output_B.json
```

`source.json` contains common source blocks/records but excludes expected Menzo outcomes, model identity/order, prices, and tokens. Successful Bob/Menzo files expose only `{"status":"ok","output":...}`; structurally invalid results use a neutral `invalid_output` status, and failed calls use a neutral failure shape. Internal diagnostics—including expected-outcome checks, protected-term findings, missing IDs/indexes, and validator errors—remain exclusively in `metrics.json` and the internal report. Reviewer output therefore contains neither model identity nor automatic correctness judgments. `answer_key.json` is separate.

`review_template.csv` has exactly one row and one preference per comparison. It provides distinct A and B score columns. A completed preference must be exactly `A`, `B`, or `TIE`; blank, duplicated, contradictory, out-of-range, incomplete, or unmapped review data is rejected. Menzo dimensions that do not apply to a case are prefilled as `NA`; `NA` is accepted only when the answer-key case metadata declares that dimension inapplicable, while every applicable dimension requires a `0` or `1` for both outputs.

## Derived report and promotion gates

```bash
python3 tools/gemini_35_flash_lite_benchmark.py report \
  --run-root artifacts/model_benchmarks/gemini_35_flash_lite/run_001 \
  --reviews blind_review/review_completed.csv
```

`benchmark_report.json` and `.md` contain separate Bob, Simone, and Menzo decisions. Every preference is counted once, and all rates are asserted within `[0, 1]`. Human dimensions and hallucination/omission severity are mapped from blind label to the correct model via the answer key.

Bob/Simone statistics derive per-model dimension means, composite mean, structured-output and repair rates, protected-term violations, critical regressions relative to baseline, missing blocks/indexes, severe hallucinations/omissions, complete Simone report validity, calls/failures, token, latency/p95, cost, and repetition stability.

Menzo statistics keep automatic and human evidence separate. Automatic statistics derive unique-story losses, missing or outside-payload survivors, overlaps, discard-all groups, generic/ungrounded updates, critical expected-outcome rate, structural validity, failures, costs, latency, and decision stability. Expected `MATERIAL_UPDATE` entries additionally compare meaningful tokens from `new_fact_contains` with the validated model fact, tolerating harmless wording changes but rejecting a different fact. Human statistics report duplicate-decision, survivor, and material-update accuracy plus reviewer-reported unique-story losses. Promotion requires perfect applicable critical human decisions and zero human unique-story losses in addition to all automatic gates.

The report reads its ordered baseline/candidate model IDs from `run_manifest.json`; the first requested model is always the baseline and the second the candidate. Custom IDs are therefore never silently aggregated under the default model names. Any fatal automatic or human candidate Menzo metric makes promotion impossible. Decisions remain independent: `PROMOTE`, `KEEP_BASELINE`, `NEEDS_MORE_DATA`, or `REJECT`.

## Offline tests

Fixtures under `tests/fixtures/v95_15_model_benchmark/` are synthetic source-backed examples. Tests use fake SDK objects and reversible monkeypatches; they make no real Gemini or network calls.
