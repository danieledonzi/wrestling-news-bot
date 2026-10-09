# ED-5: editorial eligibility before semantic duplicate work

Owner-approved change, 9 October 2026. Supersedes ED-3's universal duplicate-before-classification order.

## Runtime order

1. Existing exact-identity checks remain local.
2. Primary Gemini classification receives factual candidate data and show identity, without history, relation matrix or pacing context.
3. SKIP is terminal before semantic work. Its story core explains the class decision.
4. Build the semantic relation matrix only for MUST, SHOULD and PUBLISHABLE_SOFT. Keep existing grounding, confirmation, repair and PR131 contracts.
5. Duplicate-cleared MUST takes precedence. SHOULD uses ordinary capacity; overflow persists independently of the feed. Fresh live show items precede ordinary SHOULD.
6. Only cleared PUBLISHABLE_SOFT enters the existing contextual soft board. Fine-grained soft selectivity is deferred until observation.
7. The full show report remains autonomous, including the established same-run news-before-report sequencing.

The primary operation is moved, not duplicated. Queued unchanged strong stories reuse their validated primary class under the same policy and still obtain current duplicate clearance. A changed factual payload is classified again.

`state/newsroom/menzo_priority_queue.json` retains all admitted strong stories until confirmed Publisher success or a validated terminal decision. It therefore covers both capacity overflow and downstream failure. It does not expire at the soft midnight boundary. Queue persistence is rolled back with the other Active projection state if projection fails.

## Observation

Start the window at a verified deployed commit, not at merge time. The master log records every primary decision, source, class/reason, authorized pair endpoints, cache hit/miss totals, soft admissions and priority overflow. Phase costs remain in the canonical Gemini ledger. Publisher editorial provenance carries first-seen and classification times.

Run:

```sh
.venv/bin/python scripts/editorial_prefilter_observation.py \
  --since '<verified-deploy-UTC-ISO-time>' --hours 24 \
  --output reports/editorial_prefilter_24h.json
```

The summary separates unique candidates/pairs from repeated evaluations. Unpriced calls are explicit and known USD cost is a lower bound when any remain. First-seen delay measures pipeline latency, not event-to-feed latency. The 30-news reference remains a soft ceiling; reports are counted separately by existing Publisher accounting.

## Validation and operational notes

Regression coverage includes all-SKIP with no semantic calls; mixed admission; duplicate MUST suppression; primary and gate failures; persistent SHOULD overflow without feed rediscovery; live priority; old-policy pooled live reclassification; transactional queue rollback; same-run report autonomy; unique-versus-repeated observation metrics.

The revised primary policy changes the current shared policy fingerprint, so PR131 may initially have a cold cache. Do not interpret initial cold misses as steady-state performance. No duplicate thresholds or model choice change in this PR.
