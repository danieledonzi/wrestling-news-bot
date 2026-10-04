# DR-1: bounded body-aware local revalidation

DR-1 supplements the Active duplicate gate after its ordinary primary and one
repair attempt. It does not restore the unmerged PR132 jury, MUST triage,
component recovery, held state, or emergency survivor policy.

## Admission and authority

Validators can retain independently valid rows without accepting failed rows.
A repair cannot revoke an independently validated row from its primary attempt.
Malformed roots and ambiguous relation identities still use whole-run legacy
fallback. An ordinary primary `DUPLICATE` remains unconfirmed until E04C succeeds.

After applying existing `NO_MATCH` constraints, DR-1 admits exactly one remaining
unresolved authorized pair. It uses the existing normal Director model and
semantic validators. A gate retry that returns `DUPLICATE` requires independent
confirmation; a confirmation-phase retry does not repeat the already valid gate.
There is no local repair loop: at most two additional provider attempts per run.
Multiple unresolved pairs, missing body evidence, an unchanged metadata-only
projection, input-size overflow, provider failure, or local validation failure
keep the existing whole-run fallback. Partial Active results never become a
mixed Active/legacy publication handoff.

An already validated or cached `NO_MATCH` bypasses local work. Only confirmed
same-run duplicate classes can carry that constraint to equivalent endpoints.
All class members participate, regardless of which richer representative will
survive. Unresolved edges never establish equivalence or transfer historical
risk. DR-1 does not implement an A MUST / B NOT_MUST emergency survivor rule.

## Body and cache boundaries

Capture retains valid `owtv_canonical_source_body_v1.cleaned_full_text` privately
in `_duplicate_revalidation_bodies`. Existing legacy `{text: ...}` behavior is
preserved. Attaching this sidecar does not change ordinary provider projection,
capture/Active input digests, or serialized provider-input byte counts.

Only the affected current endpoints may be hydrated with the existing canonical
extractor. Historical evidence is reused from retained Publisher history, never
recrawled. Body text is limited to 24,000 characters per endpoint and the existing
UTF-8 projection byte bound. Diagnostics distinguish full, truncated canonical,
retained and unavailable coverage. Full canonical contracts from temporary
hydration are removed from provider rows; only bounded text is projected.
Article text remains untrusted factual data.

Independently final ordinary results may persist in PR131 even when another pair
forces fallback. Unconfirmed duplicates, body-enriched verdicts, and equivalence
projections are not stored in PR131. Its fingerprint/version and ordinary routing
remain unchanged. No new recovery cache is introduced.

Validated local results rejoin the normal gate/classification path with the
existing `semantic_duplicate_gate` authority. PR133's prohibition against
persisting unresolved arbitration as a hard skip remains intact. No production
memory migration or cleanup is part of DR-1.

## Evidence and release acceptance

`duplicate_body_revalidation` records the original pair, bounded body hashes and
coverage, local phase, request IDs/input digests, attempt count, and outcome.
These diagnostics describe the local duplicate phase, not final run success.
Each concrete provider attempt is recorded once in the operational lifecycle
and Gemini ledger, including failures. Authoritative usage/cost remains in that
ledger. Existing PR139 cache events remain in use.

Focused acceptance tests use real semantic validators with mocked external calls
and isolated storage. They cover capture compatibility, input invariance, local
success, mandatory confirmation, failure atomicity, PR131 isolation and partial
persistence, reference mapping, validated-class historical constraints, body
reuse/hydration limits, and unsupported fallback cases.

Release requires focused tests and compilation, review of concrete regressions,
then production commit/compile/test/status validation. The runtime outcome and
economic benefit must subsequently be observed; a successful deployment alone
does not demonstrate fewer lost articles or a specific saving.

Rollback requires deploying the preceding validated code revision using the
normal release process. DR-1 requires no new persistent state schema.
