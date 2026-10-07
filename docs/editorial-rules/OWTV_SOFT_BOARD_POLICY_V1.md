# OWTV Soft Board Policy V1 — ED-3

**Policy version:** `owtv_soft_board_policy_v1`
**Totem authority:** `docs/editorial-rules/OWTV_EDITORIAL_TOTEMS_AND_SOFT_BOARD_CONTRACT.md`

This operation evaluates only candidates already classified primary `PUBLISHABLE_SOFT`.

It never changes a primary editorial class.

The soft board is a separate persistent container from the primary Active candidate list. Morning-held rows are
not re-injected into primary classification on every run and do not count toward the primary `MAX_CANDIDATES`
capture limit. At an eligible review, evaluate the entire currently eligible soft container as one board.

## Contextual judgment

Judge the entire supplied soft board in the context of what OpenWrestlingTV has already published today.

The input includes current Europe/Rome time, published MUST/SHOULD/soft counts, total publications, run capacity, residual soft capacity, daily residual soft capacity, show/report context when available, and each candidate's title, story core, source, age, first-seen time and prior meaningful soft reviews.

A quiet-looking count early in the day is not a reason to publish. This operation is only valid from 12:00 Europe/Rome onward.

## Dispositions

`SOFT_MUST`:
The candidate adds enough editorial value **now** to deserve publication in this run. Use sparingly. The number of SOFT_MUST rows MUST NOT exceed `soft_capacity_this_run`.

`SOFT_SHOULD`:
The candidate is still worth bounded reconsideration but does not deserve publication now. It stays in the pool and accumulates one meaningful review.

`SOFT_SKIP`:
The candidate no longer has enough current editorial value, freshness, or standalone usefulness. Its soft eligibility ends now.

## Non-filling rule

Unused capacity has no editorial value.

Do not manufacture SOFT_MUST selections because slots are available. Zero SOFT_MUST is always a valid answer, including for consecutive runs.

## Comparative rule

Evaluate the whole board comparatively, but do not confuse relative rank with publishability. The best item on a weak board may still be SOFT_SHOULD or SOFT_SKIP.

Older content is not automatically worse than newer content. Freshness matters as eligibility and current usefulness; an older still-relevant soft story may beat a newer weaker one.

## Output order

Order `SOFT_MUST` candidates by publication preference, then `SOFT_SHOULD`, then `SOFT_SKIP`. Evaluate every supplied ref exactly once.
