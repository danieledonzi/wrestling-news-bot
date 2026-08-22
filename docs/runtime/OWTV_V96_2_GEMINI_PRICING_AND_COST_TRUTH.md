# OWTV V96.2 Gemini pricing and authoritative cost truth

## Authority and Owner decisions

`state/newsroom/gemini_call_ledger.jsonl` is the sole authority for provider attempts, usage, pricing evidence, and computed provider cost. The canonical event ledger separately owns logical AI-request lifecycle. Provider attempts—not `operation_id`—are the economic grain; retries, fallbacks, repairs, and failures are separate attempts. Avoided rows made no call, have observed cost zero, and are excluded from real-attempt denominators. No counterfactual savings are estimated.

The ratified basis is **computed paid-tier Standard Gemini list-price cost** from provider-reported usage and the frozen Google table verified 2026-08-22. It is not an invoice, billed/account-specific cost, tax, credit, discount, or enterprise-contract amount. The perimeter is scheduled newsroom production and genuine manual V92 production only; benchmarks, probes, development experiments, and standalone utilities are excluded.

## Frozen Standard text table

Rates are USD per million tokens:

| Model | Input | Output including thinking | Cached input |
|---|---:|---:|---:|
| gemini-3.5-flash | 1.50 | 9.00 | 0.15 |
| gemini-3.1-flash-lite | 0.25 | 1.50 | 0.025 |
| gemini-3-flash-preview | 0.50 | 3.00 | 0.05 |
| gemini-2.5-flash | 0.30 | 2.50 | 0.03 |
| gemini-2.5-flash-lite | 0.10 | 0.40 | 0.01 |
| gemini-2.5-pro (prompt <=200,000) | 1.25 | 10.00 | 0.125 |
| gemini-2.5-pro (prompt >200,000) | 2.50 | 15.00 | 0.25 |

The Pro tier uses full `promptTokenCount` before cached-token subtraction. These six exact production identities have no aliases. `gemini-3.5-flash-lite` is outside the perimeter. Unknown actual models stay unresolved; a requested model is used only when actual model is absent.

The table schema is `v96.2_pricing.v2`, version `google-gemini-paid-standard-2026-08-22.v1`, sourced to the official [Google Gemini Developer API pricing documentation](https://ai.google.dev/gemini-api/docs/pricing). Its `valid_from` is an OWTV official-source verification floor; it does not claim Google introduced prices that day and prevents unsupported historical backfill.

## Usage and resolution

For prompt P, cached K, candidates O, thoughts T, provider total must equal `P + O + T`. Cost is `((P-K)*input + K*cached + O*output + T*output)/1,000,000`. Negative counters, K>P, inconsistent totals, or any present-but-malformed economically relevant token field invalidate usage. Explicit thoughts are used; otherwise T is derived from provider-reported total-P-O when safe. A legacy input+output total is diagnostic only and is derived only when TOTAL was absent/null, never when malformed. For Google GenerateContent only, absent/null cached count is explicitly normalized to zero and recorded. It is never added twice.

Missing service tier resolves to Standard under the documented runtime default; provider `SERVICE_TIER_UNSPECIFIED`/`unspecified` resolves as Google's default Standard tier, and explicit Standard resolves. Flex, Priority, Batch, an unknown nonempty tier, or another class does not resolve. Current newsroom calls resolve as text under the runtime contract. Explicit economically different modality or material separately billed tool usage is unresolved. No request is changed to force tier or modality.

A failed attempt with valid usage can resolve cost; without usage its cost is unknown. Exception text never establishes billing or zero.

## Forward-only contract and read model

New real-attempt rows are ledger schema `v3`, with unique `provider_attempt_id`, usage contract `v96.2_usage.v1`, and pricing formula `v96.2_cost.v1`. Historical v1/v2 rows are untouched, remain real-attempt denominators, and receive reason `legacy_pre_v96_2_cost_contract`; they are never repriced. Thus a cutover-straddling window exposes known forward cost but null complete-window cost.

The canonical bounded economic read model reports authority/version, real attempts, usage and cost coverage, unknown attempts, known cost, complete-window cost, and reconciling model/agent/reason breakdowns. Trustworthy retained v2 provider usage (valid non-negative prompt/output evidence without malformed-field warnings) contributes to provider-usage coverage, while only integrity-valid v3 rows contribute cost. Economic `coverage` is `unavailable` when authority is unavailable, `full` for a readable fully cost-resolved window (including an empty window), and `partial` for a readable window containing unresolved real attempts. Ratios are null with zero attempts. A readable zero-attempt window has complete cost zero; a missing, unreadable, undated, or malformed ledger has null canonical scalars and no authoritative breakdowns. Complete-window cost exists only when every attempt resolves with homogeneous currency. Price-table version evidence is derived from resolved rows, never inferred from the current configuration.

Daily Judgment and Daily Report consume this model and render unavailable or partial complete cost as `n.d.`, never false zero. Older call/usage summaries are explicitly diagnostic and cannot override monetary authority.

## Closure criteria and behavior boundary

Closure requires exact table/model tests, usage/tier/modality/failure validation, attempt-grain and cutover tests, reconciling breakdowns, canonical report rendering, catalog validation, frozen Phase 0 validation, and the supported test suite. V96.2 changes measurement only: no routing, prompts, generation configuration, retry/fallback/repair behavior, publication, scheduling, or provider-call count changes; it adds zero provider calls.
