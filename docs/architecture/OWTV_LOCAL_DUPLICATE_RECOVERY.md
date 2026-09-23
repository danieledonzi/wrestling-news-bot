# Active relation-local duplicate recovery

`ed-2.2-local-duplicate-recovery-v3` supplements, but does not replace, the
Active Editorial Director and its `ed-2.1.2-active-final-pair-result-v1` cache.
The four editorial classes and their ordinary actions are unchanged.

After primary and repair validation, a malformed root, ambiguous relation
identity, provider failure, or other unattributable failure still invokes the
whole-run legacy Menzo fallback. A failure attached uniquely to an authorized
relation is instead `LOCAL_UNRESOLVED`. Independently complete relations remain
usable and cacheable under PR131; unresolved relations are never inserted into
that cache and never imply `DUPLICATE`, `NO_MATCH`, or `MATERIAL_UPDATE`.

Local unresolved relations form an undirected graph. Each connected component
is reconciled once, so a candidate cannot acquire contradictory pair-by-pair
states. Every current member receives an individual binding-policy MUST triage.
Triage failure is not `NOT_MUST`: it returns to the global safety fallback.

* A zero-MUST component is held locally without jury work.
* A one-MUST same-run component preserves that candidate and holds its peers.
* A multiple-MUST component runs pair-only, full-context jury calls for the
  necessary unresolved MUST edges. Every evidence span must ground in its exact
  endpoint. A strict majority is required (and quorum is never below two).
  Reconciliation first contracts validated duplicate classes, then preserves
  validated NOT_DUPLICATE constraints while conservatively resolving remaining
  risk connectivity. UNRESOLVED is never treated as duplicate authority.
* Against published history, a non-MUST current candidate is held. A MUST uses
  the jury; `DUPLICATE` suppresses it, while material/autonomous and unresolved
  outcomes publish the current MUST. The latter is explicitly diagnostic, not
  a fabricated material-update verdict.

A temporary recovery hold is emitted only in the dedicated top-level `held`
diagnostic section. It is not SELECT, DEFER, SKIP, a hard skip, or a softpool
mutation; downstream handoffs and canonical selection events ignore it. An
already-eligible softpool entry therefore remains eligible for a later run.

Mixed components are reconciled edge-by-edge: current/current edges use the
same-run schema while current/history edges use the history schema. A valid
same-run duplicate gate exposes its canonical representative map; unresolved
edges referencing eliminated members are remapped through that map while
retaining original pair provenance. Ambiguous remapping returns to global
fallback. Only candidates in the affected component are hydrated before triage
and jury, and coverage is reported as FULL_BODY, RETAINED_BODY, or METADATA_ONLY.
Current canonical source-body contracts are read through `source_body`, including
publisher-history `cleaned_full_text`, into the private
`_duplicate_recovery_body_by_id` sidecar. The normal provider projection, input
digest, and size calculation never include that sidecar. Recovery copies the
bounded body into component-local endpoint objects only; current hydration and
history retention therefore remain available without changing ordinary Active
or duplicate-gate prompts.

When two or more MUST candidates are connected through non-MUST current nodes,
recovery juries every same-run edge in that component. Validated DUPLICATE
classes may therefore span intermediary nodes, NOT_DUPLICATE boundaries remain
authoritative, and unresolved residual connectivity conservatively retains at
least one MUST representation without fabricating duplicate authority.

History recovery runs only after same-run contraction and survivor selection.
Every unresolved history risk carried by any member of a surviving MUST-bearing
class is remapped to that class's current representative, while retaining the
original member, history endpoint, pair/ref, class membership, and validated
duplicate-path provenance. Each distinct representative/history endpoint is
juried once. One validated DUPLICATE verdict is sufficient to suppress the
current class: MATERIAL_UPDATE_OR_AUTONOMOUS or UNRESOLVED against a different
history endpoint cannot negate an already-proven historical duplicate. When no
history verdict is DUPLICATE, material/autonomous and unresolved outcomes both
preserve the current MUST under their existing provenance.

Both recovery prompts mark article text as untrusted factual data, prohibit
following embedded instructions or role/tool requests, and wrap source payloads
in explicit `<UNTRUSTED_SOURCE_DATA>` delimiters.

Jury models are bounded and configurable through
`OWTV_DUPLICATE_RECOVERY_JURY_MODELS`. Defaults are the two model identities
already present in production routing and pricing: `gemini-3.1-flash-lite` and
`gemini-3.5-flash`. Both must agree with this reduced jury. The normal Director
model remains `gemini-3.1-flash-lite`.

Recovery writes immutable `owtv_duplicate_recovery_diagnostic_v1` supporting
artifacts. They contain component membership, original validation families,
triage, body-coverage labels, jury votes/failures/quorum, reconciliation,
held/surviving IDs, call counters, cache telemetry, and the avoided-fallback
marker, but no complete article bodies. These artifacts are diagnostic and do
not replace `owtv_editorial_director_active_v3` as editorial authority.
They distinguish duplicate-layer fallback avoidance from final whole-run legacy
fallback use and are also retained when triage or later Active classification
fails. Provider attempts use one request ID consistently in vote/triage
provenance and the Gemini ledger, including failed attempts.

No separate recovery-result cache is enabled in this first contract. This is a
deliberate fail-open boundary: jury semantics cannot accidentally contaminate
PR131, and a later cache must fingerprint the recovery prompt, model set,
scope, endpoint content, and retained-body digests before it may store only
final semantic verdicts. Whole-run legacy fallback remains the terminal path
for global gate, classification, class/action, capacity, projection, and
component-invariant failures.
