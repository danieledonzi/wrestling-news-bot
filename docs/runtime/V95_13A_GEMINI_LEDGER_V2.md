# V95.13a Gemini Ledger v2

V95.13a collects raw measurements. V95.13b will produce the final cost report and publication reconciliation.

## Raw v2 schema

New rows written by the Gemini ledger include `ledger_schema_version: "v2"` and preserve the append-only JSONL file at `state/newsroom/gemini_call_ledger.jsonl`. Real-attempt rows support identity (`timestamp`, `run_id`, `operation_id`, `attempt_index`), context (`agent`, `phase`, `purpose`, URL/title/source/article/report/candidate identifiers), model fields (`model_requested`, `model`, `actual_model`, selected chain metadata), outcome (`status`, `result`), attempt flags (`retry`, `fallback`, `repair`), usage fields, and pricing fields.

Unknown or unavailable values are `null`. Authoritative zero values remain `0`. Boolean flags are `true` or `false`.

## Operation and attempt identity

`operation_id` is stable for one logical generation operation. `attempt_index` starts at zero and increases for every real SDK invocation in that operation. Fallbacks and retries therefore produce separate rows with the same `operation_id` and distinct `attempt_index` values. Repair generations are recorded as their own operation or as explicitly marked child attempts with `repair=true`.

## Usage extraction

`extract_usage_metadata(response)` reads Google GenAI response usage without modifying the response, consuming streams, estimating token counts, or using a tokenizer. It supports object and dictionary response shapes and these metadata variants: `usage_metadata`, `usageMetadata`, `usage`, `prompt_token_count`, `input_token_count`, `candidates_token_count`, `output_token_count`, `total_token_count`, `cached_content_token_count`, `cached_input_token_count`, `thoughts_token_count`, and `thinking_token_count`.

Missing metadata records `usage_available=false` and null token fields. Malformed metadata records null token fields plus a compact `usage_warning`. SDK totals are preferred; total is derived only when input and output are authoritative and the warning/source records that derivation.

## Pricing configuration

Pricing is loaded from `config/gemini_pricing.json` or `GEMINI_PRICING_FILE`. The production file defines the schema, currency, aliases, and models map but intentionally contains no prices. Calculations use `Decimal` and write JSON-safe decimal strings without per-attempt aggressive rounding. Aliases are explicit JSON entries. Unknown model prices leave usage intact, leave cost fields null, and add `price_not_configured:<model>` to the warning path.

## Avoided events

Avoided rows are not real SDK attempts. New v2 avoided rows use zero token and zero cost fields, `usage_available=true`, and `usage_source="avoided_no_api_call"`. Summaries keep avoided rows separate from real called/failed attempts.

## Historical v1 compatibility

Historical rows are never rewritten. Normalization returns copies with `ledger_schema_version="v1"`, null token/cost fields for real calls, and `usage_available=false` for historical real calls without usage. Existing diagnostics and call counts remain compatible.

## Active call-site inventory

Active runtime call sites instrumented for real attempts:

- `agents/bob.py`: Bob article translation model chain.
- `agents/menzo.py`: Menzo AI editorial review model chain.
- `agents/menzo_policy_v93_15.py`: Menzo duplicate/cross-run JSON model call helper.
- `agents/alfred_policy_v93_20.py`: Alfred quote resolver model chain.
- `modules/report_workshop_v92.py`: report translation JSON generation chain.
- `modules/news_workshop_v92.py`: news workshop Gemini generation chain.

Compatibility/legacy call sites:

- `scripts/gemini_models_list.py`: diagnostic model listing script; not a generation attempt.
- `scripts/apply_v92_report_runtime_tweaks.py`: historical patch helper with client construction only.
- `scripts/apply_v92_report_quality_patch.py`: historical patch helper containing generation snippets but not active runtime.

Inactive archived call sites live under `docs/archive/**` and are intentionally excluded from instrumentation.

## Known limitations and v95.13b boundary

V95.13a does not implement the final cost-report CLI, daily-email redesign, publication-outcome reconciliation, budget guards, automatic alerts, cost routing, or production price discovery. Those remain v95.13b work.
