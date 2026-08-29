# Gemini Editorial Director — ED-1 Shadow Architecture

## Authority and insertion

ED-1 is a Menzo-owned, non-binding observer. `OWTV_EDITORIAL_DIRECTOR_SHADOW_ENABLED` defaults false. When enabled, the runner deep-copies the factual Massy/softpool opportunity immediately before legacy Menzo, then executes legacy Menzo, Andrea, Bob, Alfred and Publisher without consuming Shadow output. Only after Publisher completes does the runner call `gemini-3.1-flash-lite`. Disabling the flag or reverting the patch is the complete rollback; no state migration exists.

The observer cannot write candidate decisions, categories, softpool, hard skips, duplicate cache, or Publisher input. Every capture, call, validation, ledger, event and artifact boundary fails open. Production scoring, 30-reference behavior, 12-hour history, 0.55 suspicion threshold, duplicate calls and downstream code remain unchanged.

## Bounds and evidence

Technical defaults (not editorial policy) are configurable constants: 40 candidates, 80 authorized relations, 120000 serialized UTF-8 bytes and 12000 output tokens. Every opportunity records all three observed sizes and `within`, `approaching` (80%), or `exceeded`. Exceeded opportunities are `OVERSIZE_NOT_EVALUATED`: no chunking, partial evaluation, automatic increase, or provider attempt.

Exactly one logical request is created for a bounded actionable opportunity. It has one primary attempt and at most one same-model repair after local validation failure. Exceptions and SDK structured-output incompatibility terminate fail-open without alternate models.

Shadow capture applies the current `augment_board_with_softpool` helper to a deep copy of the Massy board. Production Menzo still receives the untouched original board and independently applies that same helper, so TTL, deferral and eligibility semantics have one implementation.

The closed Phase-1 event schema supports `artifact_refs` and `pair_id`, but not multiple artifact references through the convenience `active_event` interface. Each candidate event references its exact immutable package. Each relation event carries its stable `pair_id` and references one of the exact candidate packages containing that relation; the other endpoint package contains the same pair evidence, so the join is lossless without schema expansion.

## Existing Publisher semantic blockers

The three independent Publisher `story_signature` semantic blockers are **NON-BLOCKER FOR ED-1** and **BLOCKER BEFORE ED-2 AUTHORITY CLOSURE**. They remain unchanged to preserve the baseline. Before ED-2 authority closure Publisher must retain only Menzo-authorization validation plus factual publication/idempotency constraints.
