# OpenWrestlingTV — Architectural Decisions and Non-Regression Guardrails

**Document status:** FINAL  
**Document version:** 1.0.1  
**Knowledge cutoff:** 2026-08-20  
**Current runtime baseline:** Phase 1 closed; production baseline `fcf22dbde5fa013fbff056331bea0fd12acdfa10`  
**Purpose:** permanent decision-memory and pre-implementation authority for OpenWrestlingTV

## 1. Purpose and scope

This document preserves the architectural and editorial knowledge that would otherwise be lost when legacy notes are retired. It is not a version history and does not replace detailed implementation contracts. It records active guardrails, accepted trade-offs, rejected approaches, historical context and unresolved questions.

It must be consulted before proposing any reform. A technically cleaner design is not automatically preferable: API cost, Gemini use, VPS resources, operational complexity, reliability, maintenance burden and editorial risk must be evaluated together.

This document does not design V96.1 and does not authorize code changes.

## 2. Decision classes

- **ACTIVE GUARDRAIL** — normative behavior that must not be violated without an explicit decision change.
- **ACTIVE TRADE-OFF** — deliberate compromise currently accepted; it may be revisited only with explicit evidence and authority.
- **REJECTED APPROACH** — previously evaluated behavior that must not be proposed again without materially new evidence.
- **HISTORICAL ONLY** — useful evolutionary context that is not current authority.
- **OPEN QUESTION** — unresolved point requiring evidence or an explicit owner decision.

For every ACTIVE decision, `Current confirmation` uses one of these values:

- `CONFIRMED BY CURRENT FINAL SOURCES`
- `OWNER CONFIRMED — 2026-08-20`
- `PENDING RUNTIME VERIFICATION`
- `LEGACY ONLY`

## 3. Quick Non-Regression Index

| ID | Synthetic non-regression rule |
|---|---|
| AA-01 | Authority class prevails over mere recency; lower-authority material cannot silently replace an active decision. |
| AA-02 | One canonical semantic has one declared primary authority. |
| AA-03 | Stable identity precedes cross-run aggregation and lifecycle reconstruction. |
| AA-07 | Agents retain separate, limited decision authorities; no second monolith. |
| RT-01 | Observability defects must not change newsroom execution. |
| RT-03 | Preflight may stop expensive work before translation. |
| OB-02 | Unknown or unavailable evidence must never be rendered as zero. |
| OB-04 | Current state, TTL memory and latest-run snapshots are not event history. |
| OB-05 | Do not fabricate historical canonical evidence or identities by inference. |
| EP-01 | The pipeline behaves as an editor, not as a feed copier. |
| EP-08 | Complete or materially updated PLE/PPV cards are not generic previews and retain medium-high editorial and SEO value. |
| EP-09 | Anecdotes, routine ratings and weak social reactions are not automatically news. |
| MD-01 | Menzo owns duplicate arbitration; Publisher does not. |
| MD-02 | Deterministic suspicion gates Gemini duplicate arbitration. |
| MD-10 | Footprints and fingerprints cannot regain autonomous blocking authority. |
| BT-01 | Bob translates only approved material and does not make publication decisions. |
| BT-02 | Translation remains complete, faithful, non-inventive and natural in Italian. |
| AQ-01 | Alfred may make only local, safe and reversible corrections. |
| AQ-03 | Warnings, blockers and final unresolved blockers remain different grains. |
| SR-01 | Simone/report authority remains separate from normal-news authority. |
| GC-03 | Provider usage, token, price and cost facts remain authoritative in the Gemini ledger. |
| CP-02 | Retained canonical material is immutable and content-addressed. |
| MD-09 | Duplicate fail-closed effects remain isolated to the actually suspicious candidate/component. |
| RF-04 | WordPress retry-strategy changes require an authoritative baseline. |
| CR-01 | Work analyzes/specifies; Codex implements; authority boundaries and human review remain explicit. |
| CR-04 | Merge is not operational closure until the production VPS is validated. |

## 4. Source register and precedence

### 4.1 Source register

| Ref | Source | Authority role |
|---|---|---|
| `S1` | `NEWS_EDITORIAL_DECISIONS_v92.md` | Legacy editorial decision memory; active only where owner-confirmed or preserved by a higher authority. |
| `S2` | `OpenWrestlingTV Virtual Newsroom – Descrizione agenti v93.pdf` | Legacy role/permission model; active only where owner-confirmed or preserved by a higher authority. |
| `S3` | `OWTV_CODEX_REVIEW_AND_RELEASE_WORKFLOW(1).md` | Operational review/release workflow. |
| `S4` | `V95_18_DETERMINISTIC_DUPLICATE_GATE_HANDOFF(1).md` | Approved Menzo duplicate-architecture handoff; subordinate to current FINAL sources and this ratification. |
| `S5` | `OWTV_PROGRAMMATIC_ROADMAP_DIAGNOSTICS_AND_REFORMS_2026-07-25(1).md` | Programmatic rationale and reform proposals; not automatically current normative authority. |
| `S6` | `OWTV_PHASE0_FINAL.md` | FINAL authority for foundational contracts and invariants. |
| `S7` | `OWTV_PHASE1_FINAL.md` | FINAL authority for current implemented architecture and runtime closure. |
| `OWNER` | Explicit owner confirmations dated 2026-08-20 | Direct authority for the decisions specifically confirmed or promoted in this document. |

### 4.2 Precedence rule

Authority class prevails over simple recency. Within the available corpus, this FINAL document and explicit owner confirmations govern the classifications recorded here; `S7` governs current implemented Phase 1 state; `S6` governs foundational contracts and invariants. Narrow implementation specifications and operational workflows apply only inside their scope and only where consistent with higher authority. Legacy and programmatic sources preserve rationale but do not become current authority merely because they are detailed or recent.

A chat, roadmap, handoff or implementation note that is newer than an ACTIVE GUARDRAIL cannot replace it implicitly. A change requires an explicit decision, identified authority, evidence, non-regression analysis and an entry in the Decision Change Log.

## 5. Architecture / authority / identity

### AA-01 — Authority class prevails over recency

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Resolve conflicts by authority class and scope, not by timestamp alone.
- **Motivazione:** Recency does not prove ratification or semantic compatibility.
- **Problema risolto:** Roadmaps, chats and handoffs silently displacing stabilized contracts.
- **Compromesso accettato:** A newer idea may remain non-operative until formally promoted.
- **Alternative scartate:** “Newest document wins.”
- **Motivo dello scarto:** It confuses discussion or implementation detail with authority.
- **Non reintrodurre:** Implicit guardrail replacement through a newer lower-authority note.
- **Riconsiderazione:** Only through an explicit, logged owner or successor-FINAL decision.
- **Fonti:** `OWNER`; `S6` §7; `S7` §§7, 10.

### AA-02 — One semantic, one primary authority

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Each canonical semantic has one declared primary authority; secondary evidence may reconcile or diagnose but cannot silently override it.
- **Motivazione:** Similar counters frequently have different grain and coverage.
- **Problema risolto:** Conflicting totals produced from interchangeable-looking sources.
- **Compromesso accettato:** Some values remain unavailable when the authority lacks coverage.
- **Alternative scartate:** Opportunistic source substitution and majority voting among logs.
- **Motivo dello scarto:** They create false precision and unstable semantics.
- **Non reintrodurre:** A legacy counter overriding complete canonical evidence.
- **Riconsiderazione:** With an explicit authority migration, compatibility period and schema/policy version.
- **Fonti:** `S6` §§3.4, 7.1; `S7` §§5.1, 7.1.

### AA-03 — Identity before aggregation

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Cross-run uniqueness, lifecycle reconstruction and artifact linkage use stable identities at the correct grain.
- **Motivazione:** A repeated observation is not necessarily a new content item or processing instance.
- **Problema risolto:** Inflation and accidental chain joining based on titles, URLs or counters.
- **Compromesso accettato:** Metrics remain null where required identities do not exist.
- **Alternative scartate:** Title/slug matching and summing per-run counts as unique content.
- **Motivo dello scarto:** Collisions, drift and repeated observations make those methods unreliable.
- **Non reintrodurre:** Identity-free cross-run aggregation where the contract requires identity.
- **Riconsiderazione:** Only by introducing a stronger explicit identity contract.
- **Fonti:** `S6` §§4.2, 7.2; `S7` §§2.1, 7.5.

### AA-04 — Identities are not fabricated

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Optional identities such as `story_id` remain absent when no authoritative grouping exists.
- **Motivazione:** Filled fields can falsely imply knowledge.
- **Problema risolto:** Synthetic identity contaminating later aggregation and audit.
- **Compromesso accettato:** Some relationships remain unknown.
- **Alternative scartate:** Creating identifiers from loose similarity merely to complete schemas.
- **Motivo dello scarto:** It turns inference into asserted fact.
- **Non reintrodurre:** Placeholder or guessed canonical identity.
- **Riconsiderazione:** When a producer with explicit authority creates the relationship.
- **Fonti:** `S6` §4.2.

### AA-05 — Logical AI request and provider attempt are separate identities

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** One newsroom intention has one `logical_request_id`; each concrete invocation has its own `attempt_id` and attempt ordinal.
- **Motivazione:** Retry, repair and fallback can multiply provider calls without multiplying editorial intentions.
- **Problema risolto:** Ambiguous cost, reliability and outcome counts.
- **Compromesso accettato:** More event and identity complexity.
- **Alternative scartate:** Treating provider `operation_id`, attempt count or successful response as the logical request.
- **Motivo dello scarto:** It collapses different grains.
- **Non reintrodurre:** One undifferentiated “Gemini calls” metric.
- **Riconsiderazione:** Only through a versioned canonical schema preserving both grains.
- **Fonti:** `S6` §4.3; `S7` §§4.1–4.2, 7.3.

### AA-06 — Events, artifact index and artifact bytes remain distinct

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** The event ledger records what happened, the artifact index records retained material, and the material chain contains the bytes.
- **Motivazione:** A reference is not content and presence is not universal authority.
- **Problema risolto:** Reports or manifests being treated as primary evidence for facts they do not contain.
- **Compromesso accettato:** Multiple coordinated evidence layers must be maintained.
- **Alternative scartate:** A single overloaded log or Markdown report as truth.
- **Motivo dello scarto:** It cannot preserve role, integrity and lifecycle semantics cleanly.
- **Non reintrodurre:** Inferring artifact contents or authority from an event reference alone.
- **Riconsiderazione:** Only with an equivalent explicit separation of semantics and integrity.
- **Fonti:** `S6` §5; `S7` §§3, 7.4.

### AA-07 — Agent authorities remain separated and limited

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Jarvis, Massy, Simone, Menzo, Bob, Alfred, Publisher and Archivista retain distinct roles and permissions; no agent silently becomes a second monolith.
- **Motivazione:** Separation makes decisions attributable and limits failure impact.
- **Problema risolto:** Selection, translation, correction and publication authority becoming entangled.
- **Compromesso accettato:** Sequential handoffs and explicit contracts add operational structure.
- **Alternative scartate:** A single agent selecting, rewriting and publishing autonomously.
- **Motivo dello scarto:** Higher editorial risk, weaker auditability and unclear fault ownership.
- **Non reintrodurre:** Authority leakage between selection, report choice, translation, QA and publication.
- **Riconsiderazione:** Only through an explicit owner-ratified authority redesign with equivalent controls.
- **Fonti:** `S2` §§1–12; `OWNER`.

## 6. Runtime and deployment

### RT-01 — Canonical observation is fail-open

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Canonical producer, reader, telemetry initialization, validation, indexing and append failures cannot alter the newsroom execution path.
- **Motivazione:** Measurement infrastructure must not become an editorial dependency.
- **Problema risolto:** Observability defects blocking production.
- **Compromesso accettato:** An operationally successful run may complete with reduced, incomplete or unavailable observability.
- **Alternative scartate:** Failing the newsroom when canonical emission fails.
- **Motivo dello scarto:** Disproportionate availability risk.
- **Non reintrodurre:** Mandatory telemetry success as a prerequisite for editorial execution.
- **Riconsiderazione:** Only for narrowly scoped safety-critical evidence under an explicit policy.
- **Fonti:** `S6` §7.6; `S7` §§2.3, 5.3.

### RT-02 — Foundational canonicalization does not change editorial behavior

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Measurement and reader infrastructure does not silently change selection, thresholds, prompts, model routing, publication, schedule or retention outside its declared scope.
- **Motivazione:** Baselines and causal comparisons require behavioral isolation.
- **Problema risolto:** Instrumentation and reform effects becoming inseparable.
- **Compromesso accettato:** Desired optimizations are delayed until evidence is reliable.
- **Alternative scartate:** Combining canonicalization and editorial reform in one release.
- **Motivo dello scarto:** Regression attribution would be unreliable.
- **Non reintrodurre:** Behavioral changes disguised as observability work.
- **Riconsiderazione:** Through a separately scoped, measured reform.
- **Fonti:** `S6` §§1, 7.6; `S7` §§1, 7.6.

### RT-03 — Preflight may stop expensive work before translation

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Preflight may stop expensive work before translation when WordPress is demonstrably unavailable.
- **Motivazione:** Avoid API and Gemini expenditure for work that cannot be published.
- **Problema risolto:** Translation and downstream processing launched despite a known blocking publication outage.
- **Compromesso accettato:** A false-negative readiness result can delay otherwise valid content.
- **Alternative scartate:** Always translating regardless of publication readiness.
- **Motivo dello scarto:** Economic waste and unusable downstream output.
- **Non reintrodurre:** Costly translation work launched after an authoritative preflight has determined that publication cannot proceed.
- **Riconsiderazione:** When an authoritative readiness/retry baseline supports a safer or more efficient policy.
- **Fonti:** `S2` §1; `OWNER`.

### RT-04 — Runtime artifacts are not repository source

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Runtime state, ledgers and material artifacts remain outside accidental source-versioning; retained evidence uses declared runtime persistence.
- **Motivazione:** Code reproducibility and mutable production state have different lifecycles.
- **Problema risolto:** Dirty deployments and accidental publication of production artifacts.
- **Compromesso accettato:** Runtime persistence needs separate operational management.
- **Alternative scartate:** Committing live state and generated artifacts into the repository.
- **Motivo dello scarto:** Noise, privacy/size risk and non-reproducible deploy state.
- **Non reintrodurre:** Runtime dirt as versioned application source.
- **Riconsiderazione:** Only for intentionally minimized fixtures or schemas.
- **Fonti:** `S5` §§3.8, 7.9, 14; `S6` §5; `S7` §3.

### RT-05 — Production closure requires VPS validation

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** LEGACY ONLY
- **Decisione attiva:** Merge to `main` is not operational closure until the deployed commit and relevant checks succeed on the VPS.
- **Motivazione:** Repository tests do not prove production environment behavior.
- **Problema risolto:** Declaring success before deployment/runtime validation.
- **Compromesso accettato:** Release closure requires an additional operational phase.
- **Alternative scartate:** Treating merge or CI alone as completion.
- **Motivo dello scarto:** Environment, version and runtime-state differences remain possible.
- **Non reintrodurre:** “Merged equals closed.”
- **Riconsiderazione:** If an equivalent automated production validation becomes authoritative.
- **Fonti:** `S3` §§4–5.

## 7. Observability and diagnostics

### OB-01 — Canonical evidence wins only with adequate coverage

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Canonical evidence is authoritative when coverage is complete; partial or unavailable coverage stays explicit.
- **Motivazione:** A canonical source can still begin after the requested window.
- **Problema risolto:** Incomplete canonical data presented as complete truth.
- **Compromesso accettato:** Some requested totals remain `null`/`n.d.`.
- **Alternative scartate:** Filling canonical gaps with legacy estimates.
- **Motivo dello scarto:** Mixed authority produces unverifiable values.
- **Non reintrodurre:** Legacy backfill of a partial canonical window.
- **Riconsiderazione:** After authoritative retained coverage exists for the full window.
- **Fonti:** `S6` §§3, 6, 7.3; `S7` §§5.1–5.3, 7.1.

### OB-02 — Zero is not missing data

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Zero is valid only when an authoritative source covers the window and contains no qualifying entity; missing evidence is null/unavailable.
- **Motivazione:** Zero asserts a measured quiet outcome.
- **Problema risolto:** Missing telemetry masking failures or gaps.
- **Compromesso accettato:** Reports may display unavailable values.
- **Alternative scartate:** Defaulting absent metrics to zero.
- **Motivo dello scarto:** It creates false operational confidence.
- **Non reintrodurre:** Zero coercion for absent, unreadable or incomplete authority.
- **Riconsiderazione:** Never without complete authoritative coverage.
- **Fonti:** `S6` §§3.1, 7.4; `S7` §5.2.

### OB-03 — Metric grain is explicit

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Occurrences, unique entities, attempts, logical requests, recovered errors and terminal outcomes remain distinct metrics.
- **Motivazione:** Similar labels do not imply comparable units.
- **Problema risolto:** Mismatches caused by comparing different grains.
- **Compromesso accettato:** More metrics and more precise reader logic.
- **Alternative scartate:** One generic warnings/errors/calls counter.
- **Motivo dello scarto:** It cannot answer operational or editorial questions reliably.
- **Non reintrodurre:** Reconciliation by label similarity.
- **Riconsiderazione:** Only where equivalence is formally proven.
- **Fonti:** `S6` §3.3; `S7` §§4, 7.2–7.3.

### OB-04 — Current state is not event history

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** TTL state, current caches, current snapshots and latest-run artifacts cannot stand in for historical event series or authoritative historical-window totals.
- **Motivazione:** State retention and event-window coverage are different semantics.
- **Problema risolto:** Latest duplicate/report state or current cache inventory being extrapolated across 24- or 30-day windows.
- **Compromesso accettato:** Historical metrics may remain unavailable.
- **Alternative scartate:** Inferring coverage from TTL or file modification time.
- **Motivo dello scarto:** Neither proves event timestamps or completeness.
- **Non reintrodurre:** Snapshot-, cache- or TTL-state-as-history aggregation.
- **Riconsiderazione:** When an explicit authoritative history is retained.
- **Fonti:** `S6` §§6.2–6.3, 7.5.

### OB-05 — No inferred historical backfill

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Canonical history begins at a real cutover and is not rewritten from uncertain legacy evidence.
- **Motivazione:** Historical completeness must be observed, not manufactured.
- **Problema risolto:** False continuity across schema deployments.
- **Compromesso accettato:** Long windows remain partial until enough time passes.
- **Alternative scartate:** Synthetic events from aggregates, timestamps or similarly named fields.
- **Motivo dello scarto:** The original grain and identity cannot be recovered safely.
- **Non reintrodurre:** Canonical rows created solely to make old windows complete.
- **Riconsiderazione:** Only for evidence whose semantics and identities are independently authoritative and auditable.
- **Fonti:** `S6` §§6.3, 7.7; `S7` §4.6.

### OB-06 — Schemas and metric meanings evolve additively and explicitly

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Schema/policy versions identify semantic changes; an existing metric name is not silently redefined.
- **Motivazione:** Time-series comparability depends on stable meaning.
- **Problema risolto:** One field meaning attempts in one version and successes in another.
- **Compromesso accettato:** Compatibility and deprecation overhead.
- **Alternative scartate:** In-place semantic mutation.
- **Motivo dello scarto:** Historical comparisons become invalid.
- **Non reintrodurre:** Same name, changed grain or authority.
- **Riconsiderazione:** Through an explicit versioned migration.
- **Fonti:** `S5` §§3.4–3.5; `S6` §§3–4; `S7` §7.

### OB-07 — Raw events and aggregates remain separable

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Aggregates must remain traceable to the qualifying canonical events or retained evidence.
- **Motivazione:** Audit and metric correction require reconstructability.
- **Problema risolto:** Unexplained totals that cannot be verified.
- **Compromesso accettato:** Storage and reader complexity.
- **Alternative scartate:** Markdown-only or aggregate-only diagnostics.
- **Motivo dello scarto:** They conceal grain and source defects.
- **Non reintrodurre:** A canonical aggregate with no declared underlying evidence.
- **Riconsiderazione:** Only for privacy/retention constraints with an explicit alternative audit contract.
- **Fonti:** `S5` §§3.7–3.8; `S6` §§4–5; `S7` §§2–5.

### OB-08 — Reports are derived views, not independent authorities

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Markdown reports consume canonical readers/snapshots and do not recalculate independent truth.
- **Motivazione:** Two readers of the same logs had produced incompatible numbers.
- **Problema risolto:** Presentation-layer semantics becoming de facto authority.
- **Compromesso accettato:** Reports can show `n.d.` when the read model lacks authority.
- **Alternative scartate:** Per-report bespoke parsing and formulas.
- **Motivo dello scarto:** Semantic drift and reconciliation cost.
- **Non reintrodurre:** An ad hoc metric existing only in the final Markdown.
- **Riconsiderazione:** Only by adding the semantic first to the canonical catalog/read model.
- **Fonti:** `S5` §3.3; `S6` §2; `S7` §§5.1, 5.6.

### OB-09 — Corrupt canonical evidence fails availability, not precision

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Malformed or schema-invalid authoritative rows make the affected event-backed section unavailable instead of computing a precise value from a damaged subset.
- **Motivazione:** Silent row dropping hides integrity defects.
- **Problema risolto:** Plausible but incomplete canonical totals.
- **Compromesso accettato:** A local defect can suppress an affected metric family.
- **Alternative scartate:** Best-effort aggregation without an explicit completeness contract.
- **Motivo dello scarto:** It overstates authority.
- **Non reintrodurre:** Silent corruption tolerance in authoritative readers.
- **Riconsiderazione:** With an explicit quarantine/completeness protocol that proves unaffected coverage.
- **Fonti:** `S7` §5.3.

## 8. Editorial pipeline

### EP-01 — Editorial value outranks feed completeness

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** The bot behaves as an editor, not a feed copier, and prioritizes material value for the OWTV audience.
- **Motivazione:** Publication volume is not editorial quality.
- **Problema risolto:** Weak items being published merely because they appear in feeds.
- **Compromesso accettato:** Valid but low-value items may remain unpublished.
- **Alternative scartate:** Publish-all intake.
- **Motivo dello scarto:** Site clutter and editorial dilution.
- **Non reintrodurre:** Feed presence as sufficient publication justification.
- **Riconsiderazione:** Only by explicit owner change to the editorial mission.
- **Fonti:** `S1` §§Core philosophy, Handoff summary; `OWNER`.

### EP-02 — Soft content does not fill empty capacity

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Publish fewer items when only weak soft news is available; capacity is a ceiling, not an obligation.
- **Motivazione:** Empty slots do not create editorial value.
- **Problema risolto:** Soft items promoted to satisfy a numerical target.
- **Compromesso accettato:** Some runs publish fewer or no normal news.
- **Alternative scartate:** Filling every run to its maximum.
- **Motivo dello scarto:** It rewards weakness and increases noise.
- **Non reintrodurre:** Automatic threshold lowering solely to fill capacity.
- **Riconsiderazione:** With explicit owner-approved policy and evidence of audience value.
- **Fonti:** `S1` §§Core philosophy, Soft news, Scoring and publication count; `OWNER`.

### EP-03 — Fixed publication count is not a target

- **Status:** REJECTED APPROACH
- **Decisione:** “Publish exactly three” or fill to the run maximum.
- **Problema che tentava di risolvere:** Predictable output volume.
- **Compromesso/motivo dello scarto:** Predictability was rejected because it promotes weak content; the maximum is a ceiling.
- **Non reintrodurre:** A mandatory per-run article count.
- **Riconsiderazione:** Only with new editorial evidence and an explicit owner decision.
- **Fonti:** `S1` §Scoring and publication count.

### EP-04 — Rigid person/source/category caps are rejected

- **Status:** REJECTED APPROACH
- **Decisione:** Do not impose simple caps such as one person, source or promotion item per run.
- **Problema che tentava di risolvere:** Perceived repetition and source concentration.
- **Compromesso/motivo dello scarto:** Major events can legitimately generate several distinct high-value stories; semantic difference and scoring are preferred.
- **Non reintrodurre:** Arbitrary caps detached from story identity and value.
- **Riconsiderazione:** Only if measured concentration harm cannot be controlled editorially.
- **Fonti:** `S1` §No rigid person/source caps.

### EP-05 — Editorial classes and separate hard/soft thresholds remain active policy

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Maintain differentiated editorial classes and separate hard/soft admission thresholds; current taxonomy, categories and numeric values are policy parameters rather than immutable architecture.
- **Motivazione:** Urgency, strategic value and softness require different treatment.
- **Problema risolto:** One undifferentiated score admitting low-value material.
- **Compromesso accettato:** Classification and thresholds require calibration and can produce borderline cases.
- **Alternative scartate:** A single universal threshold or no class distinction.
- **Motivo dello scarto:** It cannot express the accepted editorial priorities.
- **Non reintrodurre:** Removing class-sensitive admission without an explicit replacement decision.
- **Riconsiderazione:** Taxonomies, classes and thresholds may change through a future explicit owner decision supported by evidence.
- **Fonti:** `S1` §§Content classes, Hard/soft thresholds; `OWNER`.

### EP-06 — Simple pacing caps are rejected; editorial scoring controls volume

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Recent site volume alone does not block additional valid hard news; volume is governed through editorial value and context.
- **Motivazione:** Breaking periods and major events produce legitimate clusters.
- **Problema risolto:** Artificial throttling losing important news.
- **Compromesso accettato:** Publication volume may rise substantially during news storms.
- **Alternative scartate:** A simple recent-publication pacing cap.
- **Motivo dello scarto:** It ignores the quality and independence of new stories.
- **Non reintrodurre:** A hard volume block based only on recent count.
- **Riconsiderazione:** Evidence-based scoring modes may be explicitly designed; not a blind cap.
- **Fonti:** `S1` §No simple pacing cap; `OWNER`.

### EP-07 — Category policy is semantic, with strict Business and separate NXT

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Business requires corporate/economic signals; NXT remains distinct from WWE; model suggestions are not blindly trusted.
- **Motivazione:** Categories are reader-facing editorial claims.
- **Problema risolto:** Personal/legal/in-ring stories mislabeled as Business and NXT collapsed into WWE.
- **Compromesso accettato:** Deterministic validation can override a model category and needs maintained signals.
- **Alternative scartate:** Blind acceptance of Gemini category output and broad “Business” labeling.
- **Motivo dello scarto:** Editorial misclassification.
- **Non reintrodurre:** Model authority over categories without semantic validation.
- **Riconsiderazione:** Taxonomies, category sets and signal rules may change through a future explicit owner decision.
- **Fonti:** `S1` §§Business category, Category trust, NXT category; `OWNER`.

### EP-08 — Complete or materially updated PLE/PPV cards have editorial value

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Complete, updated or materially changed major-event cards are not treated as generic previews and may receive medium-high editorial/SEO value.
- **Motivazione:** Users actively seek complete card information.
- **Problema risolto:** Valuable event-card updates discarded as low-value previews.
- **Compromesso accettato:** Card items require distinction between real updates and generic preview repetition.
- **Alternative scartate:** Blanket skipping of all preview/card content.
- **Motivo dello scarto:** It loses useful search and planning information.
- **Non reintrodurre:** Classifying an official material card update as low value solely because it concerns a future show.
- **Riconsiderazione:** With audience/search evidence and explicit policy change.
- **Fonti:** `S1` §PLE/PPV card items; `OWNER`.

### EP-09 — Anecdotes, routine ratings and weak social reactions are not automatically news

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Anecdotes, routine ratings and weak social reactions are not automatically news; they require independent current, operational, strategic or otherwise material editorial value.
- **Motivazione:** Format, subject popularity or social visibility alone does not establish newsworthiness.
- **Problema risolto:** Routine interview anecdotes, ordinary audience figures and minor reactions being promoted without meaningful current impact.
- **Compromesso accettato:** These content types may still qualify when they contain material contract, health, legal, storyline, business, programming or perception implications.
- **Alternative scartate:** Automatically admitting anecdotes, ratings or social-reaction items as news categories.
- **Motivo dello scarto:** It would increase weak and repetitive output without proportional editorial value.
- **Non reintrodurre:** Treating a routine anecdote, ordinary rating or weak social reaction as sufficient publication justification.
- **Riconsiderazione:** With explicit owner-approved policy change supported by audience and editorial evidence.
- **Fonti:** `S1` §§Interviews and anecdotes, Viewership/ratings, Social-media/bot engagement stories; `OWNER`.

### EP-10 — Publication may proceed without failed media

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** An otherwise valid article is not lost solely because an image/media operation fails; when safe and supported, publish without media and log the failure.
- **Motivazione:** Media is supporting presentation, not the editorial article itself.
- **Problema risolto:** Complete content discarded for a recoverable image failure.
- **Compromesso accettato:** Some posts may publish without ideal visual presentation.
- **Alternative scartate:** Universal hard failure on media upload.
- **Motivo dello scarto:** Reliability and editorial loss outweigh presentation benefit.
- **Non reintrodurre:** Media success as an unconditional publication prerequisite.
- **Riconsiderazione:** Only for content types where media is explicitly essential and safely detectable.
- **Fonti:** `S1` §Media and publication; `OWNER`.

## 9. Menzo and dedupe

### MD-01 — Menzo owns duplicate arbitration before budget/caps

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Menzo resolves duplicate eligibility before budget, caps and capacity; Publisher does not perform semantic dedupe.
- **Motivazione:** Editorial capacity must operate on distinct candidates.
- **Problema risolto:** Duplicate candidates consuming budget or late technical stages making editorial decisions.
- **Compromesso accettato:** Menzo becomes a critical controlled gate.
- **Alternative scartate:** Publisher dedupe or budget-before-dedupe.
- **Motivo dello scarto:** Wrong authority and distorted capacity.
- **Non reintrodurre:** Semantic duplicate authority downstream of Menzo.
- **Riconsiderazione:** Only with an explicit authority redesign.
- **Fonti:** `S4` §§2–4, 12; `S7` §§6.3, 7.6.

### MD-02 — Deterministic suspicion gate before Gemini

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Deterministic evidence decides whether a plausible duplicate doubt exists; Gemini decides only admitted suspicious/ambiguous cases.
- **Motivazione:** Most comparisons do not justify semantic-model cost, input tokens, latency or additional provider-failure exposure.
- **Problema risolto:** Broad all-to-all Gemini comparison, unnecessary spend and operational coupling.
- **Compromesso accettato:** A deterministic scorer must be maintained and may require calibration.
- **Alternative scartate:** Gemini as the universal comparison engine.
- **Motivo dello scarto:** API cost, latency and avoidable operational failure surface.
- **Non reintrodurre:** Sending clearly distinct or merely topically related pairs to Gemini.
- **Riconsiderazione:** Only if measured quality/cost evidence supports a different gate.
- **Fonti:** `S4` §§1–6, 12; `S7` §§6.3, 8.4.

### MD-03 — Exact duplicates are resolved deterministically

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Equal canonical source URL or equal material content hash is handled without Gemini.
- **Motivazione:** Certain identity does not require probabilistic arbitration.
- **Problema risolto:** Paying for and risking inconsistent answers on exact duplicates.
- **Compromesso accettato:** Canonicalization and material hashing must remain reliable.
- **Alternative scartate:** Model arbitration for exact equality.
- **Motivo dello scarto:** No editorial benefit for added cost.
- **Non reintrodurre:** Gemini calls for deterministically exact duplicates.
- **Riconsiderazione:** If exactness semantics change through a versioned contract.
- **Fonti:** `S4` §5.

### MD-04 — One versioned suspicion threshold for both scopes

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Same-run and recent-history use the same versioned suspicion threshold; the v95.18 contract value is `0.55`.
- **Motivazione:** Comparable admission semantics and cache fingerprinting.
- **Problema risolto:** Scope-specific drift that is difficult to audit.
- **Compromesso accettato:** One threshold may be less locally optimal.
- **Alternative scartate:** Unversioned or silently divergent thresholds.
- **Motivo dello scarto:** Unreproducible decisions and stale-cache risk.
- **Non reintrodurre:** Threshold changes without policy/cache versioning.
- **Riconsiderazione:** With measured false-positive/false-negative evidence and explicit version migration.
- **Fonti:** `S4` §6.2.

### MD-05 — Same-run Gemini scope is limited to suspicious components

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Same-run pairs below threshold pass without Gemini; only suspicious connected components are arbitrated.
- **Motivazione:** Component isolation limits input and failure blast radius.
- **Problema risolto:** Entire candidate board sent to the model for one local ambiguity.
- **Compromesso accettato:** Component construction adds deterministic logic.
- **Alternative scartate:** One universal same-run batch.
- **Motivo dello scarto:** Excess context, cost and coupled failure.
- **Non reintrodurre:** Non-suspicious candidates in duplicate prompts.
- **Riconsiderazione:** With superior measured architecture preserving isolation.
- **Fonti:** `S4` §§4.1, 7, 10.

### MD-06 — Recent-history authority is successful Publisher history in a bounded window

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Recent-history compares survivors only with real successful publications in the last 12 hours, deduplicated by canonical source URL.
- **Motivazione:** Selected, pending, failed and intermediate items are not published history.
- **Problema risolto:** False duplicate blocking against content never published.
- **Compromesso accettato:** The bounded window may not detect older story repetition.
- **Alternative scartate:** Master log, footprints, generalized fingerprints or selected candidates as blocking history.
- **Motivo dello scarto:** Wrong lifecycle authority.
- **Non reintrodurre:** Unpublished artifacts as authoritative recent-history blockers.
- **Riconsiderazione:** With a successor authoritative publication-history contract.
- **Fonti:** `S4` §§4.2, 8, 12.

### MD-07 — Material updates survive duplicate control

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Same story or related context is not sufficient to block a materially new development.
- **Motivazione:** Editorial novelty can exist inside an ongoing story.
- **Problema risolto:** Real updates suppressed as duplicates.
- **Compromesso accettato:** Ambiguous novelty sometimes needs Gemini arbitration.
- **Alternative scartate:** Story-level blanket blocking.
- **Motivo dello scarto:** Loss of important developments.
- **Non reintrodurre:** Treating shared subject/event alone as duplicate proof.
- **Riconsiderazione:** Only with evidence that a new novelty model improves both duplicate and update outcomes.
- **Fonti:** `S4` §§6–8, 12–13.

### MD-08 — Cache only previously arbitrated real doubts

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Cache units represent suspicious pairs/components and are reusable only when identities, material hashes, scorer, threshold, prompt and contract fingerprint are unchanged.
- **Motivazione:** Cache is for avoiding repeated arbitration, not subsidizing bad comparison scope.
- **Problema risolto:** Stale decisions and economically tolerable all-to-all comparison.
- **Compromesso accettato:** More misses after any material or contract change.
- **Alternative scartate:** Universal `reviewed_history` and partial/incompatible cache reuse.
- **Motivo dello scarto:** Incorrect reuse and concealed excess work.
- **Non reintrodurre:** Cached decisions without complete invalidation inputs.
- **Riconsiderazione:** With an equivalent auditable invalidation contract.
- **Fonti:** `S4` §9.

### MD-09 — Duplicate failure isolation is scoped

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Fail-closed applies only to the candidate/component actually involved in an above-threshold unresolved doubt; clearly distinct candidates and independent components remain unaffected.
- **Motivazione:** An unrelated model failure must not block content that has already passed the deterministic gate.
- **Problema risolto:** Whole-run suppression or cross-component failure propagation from one duplicate call failure.
- **Compromesso accettato:** A suspicious item may be conservatively suspended.
- **Alternative scartate:** Global fail-closed duplicate gate.
- **Motivo dello scarto:** Disproportionate availability and editorial loss.
- **Non reintrodurre:** Propagating one arbitration failure to independent candidates.
- **Riconsiderazione:** Only for a demonstrated systemic-integrity condition.
- **Fonti:** `S4` §10.

### MD-10 — Footprints/fingerprints are signals, not blocking authorities

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Footprints, fingerprints, entities, actions, events and slugs may inform suspicion but cannot autonomously declare a non-exact duplicate.
- **Motivazione:** Shared subject or vocabulary does not prove the same news.
- **Problema risolto:** False positives from broad similarity heuristics.
- **Compromesso accettato:** Ambiguous cases require the higher-cost semantic arbiter.
- **Alternative scartate:** Restoring legacy footprint/fingerprint blockers.
- **Motivo dello scarto:** They lost material updates and distinct same-subject stories.
- **Non reintrodurre:** Any renamed heuristic with equivalent autonomous blocking power.
- **Riconsiderazione:** Only with new validated evidence and explicit owner ratification.
- **Fonti:** `S4` §§1, 6, 12.

## 10. Bob and translation

### BT-01 — Bob has translation authority, not selection authority

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Bob processes only material approved by Menzo or Simone and cannot choose URLs, change their decisions or publish.
- **Motivazione:** Selection and translation are different authorities.
- **Problema risolto:** Translation behavior changing the editorial queue.
- **Compromesso accettato:** Bob cannot rescue unapproved content autonomously.
- **Alternative scartate:** Translator as selector/publisher.
- **Motivo dello scarto:** Authority leakage and unreviewed publication risk.
- **Non reintrodurre:** Bob-side editorial admission or publication choice.
- **Riconsiderazione:** Only through explicit owner authority redesign.
- **Fonti:** `S2` §5; `OWNER`.

### BT-02 — Translation is complete, faithful and natural

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Bob translates/adapts into natural Italian without summarizing when full translation is required, inventing facts, altering quotes or changing certainty; wrestling terminology remains natural and correct.
- **Motivazione:** Editorial trust depends on factual and quotation fidelity as well as readable Italian.
- **Problema risolto:** AI filler, literal calques, invented interpretation and semantic drift.
- **Compromesso accettato:** Fidelity can constrain stylistic rewriting.
- **Alternative scartate:** Free-form rewriting, summarization and literal terminology substitution.
- **Motivo dello scarto:** Editorial/legal risk and degraded specialist language.
- **Non reintrodurre:** Invented connective claims, quote modification, or `match` rendered as “partita/incontro/gara/gioco.”
- **Riconsiderazione:** Terminology may evolve only through explicit editorial decision without weakening fidelity.
- **Fonti:** `S1` §Translation editorial rules; `S2` §5; `OWNER`.

### BT-03 — Structure, attribution and supported media are preserved

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Bob preserves source structure, quotes, attribution, images and embeds when provided by the supported contract, and produces reviewable HTML for Alfred.
- **Motivazione:** Translation must not erase evidence or presentation structure.
- **Problema risolto:** Flattened articles and missing provenance.
- **Compromesso accettato:** Extraction/translation logic is more complex than plain-text rewriting.
- **Alternative scartate:** Text-only paraphrase detached from source structure.
- **Motivo dello scarto:** Lower fidelity and auditability.
- **Non reintrodurre:** Silent removal of attribution, quotes or supported structural blocks.
- **Riconsiderazione:** When a source format or rights constraint requires an explicit handling rule.
- **Fonti:** `S1` §Translation editorial rules; `S2` §5; `OWNER`.

## 11. Alfred and quality control

### AQ-01 — Alfred corrections are local, safe and reversible

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Alfred may correct micro-errors and improve presentation only through local, safe, reversible changes.
- **Motivazione:** QA must reduce defects without acquiring authorship authority.
- **Problema risolto:** A corrector rewriting editorial meaning.
- **Compromesso accettato:** Some broader quality defects must be blocked or escalated rather than rewritten.
- **Alternative scartate:** Whole-article autonomous rewriting.
- **Motivo dello scarto:** Uncontrolled factual and editorial drift.
- **Non reintrodurre:** Broad semantic rewriting disguised as correction.
- **Riconsiderazione:** Only through explicit owner-approved authoring authority and separate controls.
- **Fonti:** `S2` §6; `OWNER`.

### AQ-02 — Alfred cannot change facts, quotes or certainty

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Alfred cannot add/delete facts, alter quotations, change degree of certainty, turn rumor into fact or edit human editorials without explicit mode.
- **Motivazione:** These are substantive editorial actions, not quality corrections.
- **Problema risolto:** Safe-looking edits changing the story.
- **Compromesso accettato:** Some detected issues remain blockers requiring upstream/human resolution.
- **Alternative scartate:** QA granted implicit fact-editing authority.
- **Motivo dello scarto:** Editorial and attribution risk.
- **Non reintrodurre:** Semantic escalation inside automated correction.
- **Riconsiderazione:** Only through explicit mode, authority and audit trail.
- **Fonti:** `S2` §6; `OWNER`.

### AQ-03 — Warning and blocker grains remain distinct

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Each warning-list entry is a warning occurrence; a blocker is recorded only as a blocker unless independently present as a warning; occurrence is distinct from final unresolved state.
- **Motivazione:** A blocker can be repaired before publication.
- **Problema risolto:** Historical blockers misreported as final failures and warnings double-counted.
- **Compromesso accettato:** Reports need several related Alfred metrics.
- **Alternative scartate:** One combined warning/blocker count.
- **Motivo dello scarto:** Different lifecycle meanings.
- **Non reintrodurre:** Comparing occurrence counts with unique/final outcomes as if identical.
- **Riconsiderazione:** Only via versioned semantic mappings preserving all grains.
- **Fonti:** `S7` §§4.4, 7.2, 8.2.

### AQ-04 — One case opens investigation, not a general reform

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** A single case can trigger investigation and a justified local correction; changing prompts, taxonomies or general guardrails requires broader evidence.
- **Motivazione:** Anecdotal fixes can create wider false positives and regressions.
- **Problema risolto:** Global policy oscillation after isolated defects.
- **Compromesso accettato:** A general fix may wait while evidence accumulates.
- **Alternative scartate:** Immediate global rule from one example.
- **Motivo dello scarto:** Insufficient evidence of prevalence and safety.
- **Non reintrodurre:** Treating one incident as proof of a systemic pattern.
- **Riconsiderazione:** When repeated pattern, sufficient evidence, low false-positive risk and regression tests exist.
- **Fonti:** `S5` §§7.3, 14; `OWNER`.

## 12. Simone and reports

### SR-01 — Simone owns reports, not normal-news selection

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Simone handles scheduled weekly and major PLE/PPV reports; Menzo handles normal news. Reports do not compete with news budgets.
- **Motivazione:** Report coverage is deterministic and structurally different from news selection.
- **Problema risolto:** Mixed authorities, duplicate counting and missed scheduled coverage.
- **Compromesso accettato:** Separate discovery, status and duplicate logic.
- **Alternative scartate:** A single news selector for reports and ordinary news.
- **Motivo dello scarto:** Wrong lifecycle and counting semantics.
- **Non reintrodurre:** Simone selecting hard news or Menzo treating reports as news inventory.
- **Riconsiderazione:** Only by explicit owner authority redesign.
- **Fonti:** `S1` §Reports are not news; `S2` §3; `OWNER`.

### SR-02 — Post-show outcomes are normally redundant after a complete report

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** After a complete show report is published, ordinary show-angle outcomes are normally skipped as redundant; a materially autonomous hard-news development may be published as an explicit exception.
- **Motivazione:** The report already covers the show, but some outcomes have independent future impact.
- **Problema risolto:** Site clutter and duplication without suppressing genuine hard news.
- **Compromesso accettato:** Editorial judgment is required at the boundary between recap and autonomous development.
- **Alternative scartate:** Publish every outcome after the report; or block every post-show item without exception.
- **Motivo dello scarto:** The first duplicates coverage; the second can lose materially independent news.
- **Non reintrodurre:** Automatic post-report publication of routine angles, or an absolute ban that ignores autonomous hard news.
- **Riconsiderazione:** With explicit evidence about overlap, cannibalization and reader value.
- **Fonti:** `S1` §Event outcomes after report; `OWNER`.

### SR-03 — Reports pass through Bob, Alfred and Publisher

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** LEGACY ONLY
- **Decisione attiva:** Simone prepares report selection/title/category, but publication still passes through translation, QA and Publisher.
- **Motivazione:** Report authority does not include translation, correction or WordPress authority.
- **Problema risolto:** Scheduled content bypassing normal quality/publication controls.
- **Compromesso accettato:** Additional stages can delay report publication.
- **Alternative scartate:** Simone publishing directly.
- **Motivo dello scarto:** Authority leakage and reduced quality control.
- **Non reintrodurre:** Direct report publication outside Bob–Alfred–Publisher.
- **Riconsiderazione:** Only through explicit owner authority redesign.
- **Fonti:** `S2` §§3, 10.

### SR-04 — Simone outcomes use lifecycle semantics, not generic errors

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Candidate absence/ambiguity, waiting, already-published, readiness failure, recovered error, terminal error and SLA outcome remain distinguishable.
- **Motivazione:** A generic `errors` value does not establish report failure.
- **Problema risolto:** Benign or recovered states presented as terminal failures.
- **Compromesso accettato:** More status fields and reconciliation logic.
- **Alternative scartate:** Treating any nonzero legacy `errors` as canonical terminal failure.
- **Motivo dello scarto:** It misstates the report outcome.
- **Non reintrodurre:** Generic error count as the sole Simone health metric.
- **Riconsiderazione:** Only with an equivalent explicit lifecycle taxonomy.
- **Fonti:** `S5` §§6.6, 7.7; `S7` §4.5.

### SR-05 — Source preference is operational, not universal authority

- **Status:** HISTORICAL ONLY
- **Decisione storica:** v93 preferred WrestlingInc for structurally reliable automatic report extraction and used RingsideNews as fallback/manual where extraction was not deterministic.
- **Valore storico:** Explains prior report-source routing.
- **Non normativa perché:** Current FINAL sources do not ratify this source-specific preference.
- **Riconsiderazione:** Requires runtime verification and explicit owner confirmation.
- **Fonti:** `S2` §3.

## 13. Gemini use and cost control

### GC-01 — Selective Gemini duplicate authority (consolidated)

- **Status:** HISTORICAL ONLY
- **Consolidation note:** Semantic consolidated into `MD-02`. ID reserved and must not be reused.
- **Historical knowledge retained:** Earlier documentation placed the deterministic-gate limitation on Gemini inside the Gemini/cost area. The active canonical decision now remains under Menzo duplicate-gate authority in `MD-02`, including its economic rationale.
- **Fonti:** `S4` §§1–4, 9; `S7` §§6.3, 8.4; Decision Change Log 2026-08-20.

### GC-02 — Provider invocation and cost-accounting grain is explicit

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** For provider and cost accounting, one logical request is distinct from each real provider attempt; retry, repair and fallback invocations are recorded when actually executed, while avoided work has no provider attempt or latency. Usage and cost are attributed at the provider-attempt grain.
- **Authority boundary:** `GC-02` owns provider/cost-accounting grain; it does not define the reliability interpretation of recovered success, which belongs to `RF-05`.
- **Motivazione:** Economic analysis requires the grain of actual provider invocations and their usage.
- **Problema risolto:** Hidden provider-call overhead, unattributed usage/cost and misleading “call” counts.
- **Compromesso accettato:** More telemetry and correlation requirements.
- **Alternative scartate:** Counting logical work, provider operations and successful outputs as the same metric.
- **Motivo dello scarto:** Provider usage and cost attribution become impossible.
- **Non reintrodurre:** Estimated calls inferred from final article count.
- **Riconsiderazione:** Only through a richer compatible lifecycle model.
- **Fonti:** `S6` §4.3; `S7` §§4.1–4.3, 7.3.

### GC-03 — Gemini ledger owns provider economic evidence

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** `gemini_call_ledger.jsonl` is the authority for provider usage, tokens, model/version, price and cost evidence; canonical events own newsroom lifecycle semantics.
- **Motivazione:** Provider economics and editorial lifecycle have different authorities.
- **Problema risolto:** Cost reconstructed from article or logical-request counts.
- **Compromesso accettato:** Analysis must join two evidence families carefully.
- **Alternative scartate:** Moving provider facts into generic newsroom counters or letting the provider ledger define logical identity.
- **Motivo dello scarto:** Each loses the other's grain.
- **Non reintrodurre:** `operation_id` promoted to canonical logical request identity.
- **Riconsiderazione:** Through an explicit authority migration preserving provider-level evidence.
- **Fonti:** `S6` §§2, 6.2; `S7` §§4.1, 5.1, 10.

### GC-04 — Model routing requires quality/cost/latency/reliability evidence

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** LEGACY ONLY
- **Decisione attiva:** More expensive or capable models are not routed by score/category until comparable baseline evidence exists.
- **Motivazione:** Technical capability alone does not establish economic or editorial value.
- **Problema risolto:** Costly routing changes without measurable benefit.
- **Compromesso accettato:** Potential quality gains are delayed.
- **Alternative scartate:** Immediate score-based routing to a higher-cost model.
- **Motivo dello scarto:** Missing comparative quality, cost, latency and fallback data.
- **Non reintrodurre:** Routing reform justified only by model reputation or isolated examples.
- **Riconsiderazione:** When authoritative per-model evidence and controlled comparison exist.
- **Fonti:** `S5` §7.6.

### GC-05 — Gemini editorial director is deferred

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** The Gemini editorial director is **deferred, not rejected**. It remains a possible future architecture whose evaluation is postponed until the stated convergence, authoritative cost-truth and Menzo-efficiency baselines are available. It must not be interpreted as a `REJECTED APPROACH`.
- **Motivazione:** Converged metrics, cost truth and an optimized baseline are prerequisites for meaningful evaluation.
- **Problema risolto:** Adding a broad expensive authority before the existing system can measure its benefit and cost.
- **Compromesso accettato:** Potentially ambitious editorial automation is postponed despite possible future benefits.
- **Alternative scartate:** Introducing the director during or immediately after foundational canonicalization.
- **Motivo dello scarto:** Insufficient convergence, cost attribution and efficiency baseline.
- **Non reintrodurre:** Director implementation disguised as a smaller convergence or efficiency patch.
- **Riconsiderazione:** Only after the stated convergence, authoritative cost evidence and Menzo-efficiency prerequisites establish a stable comparison baseline.
- **Fonti:** `S7` §9.

## 14. Cache and persistence

### CP-01 — Canonical event and artifact indexes are append-only

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Canonical ledgers/indexes append evidence rather than rewriting prior rows.
- **Motivazione:** Audit requires stable history.
- **Problema risolto:** Mutable snapshots erasing earlier lifecycle facts.
- **Compromesso accettato:** Retention and compaction need separate policy.
- **Alternative scartate:** Latest-state replacement as canonical history.
- **Motivo dello scarto:** It destroys event provenance.
- **Non reintrodurre:** In-place canonical history mutation.
- **Riconsiderazione:** Only with integrity-preserving archival/compaction semantics.
- **Fonti:** `S7` §§2–3.

### CP-02 — Retained material is immutable and content-addressed

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Equal bytes may be verified/reused; different bytes are never overwritten under one artifact identity.
- **Motivazione:** Quality audit needs the actual stage material.
- **Problema risolto:** Mutable files invalidating past comparisons.
- **Compromesso accettato:** Additional storage use.
- **Alternative scartate:** Title/slug/WordPress-ID identity and overwrite-in-place retention.
- **Motivo dello scarto:** Presentation identifiers change and do not prove byte identity.
- **Non reintrodurre:** Mutable canonical material under a stable identity.
- **Riconsiderazione:** Only with equivalent immutable versioning and integrity evidence.
- **Fonti:** `S7` §3.1.

### CP-03 — Material chains do not cross run boundaries

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Chain resolution is scoped by `correlation_id`; missing roles are never borrowed from another run sharing `content_id`.
- **Motivazione:** Repeated content can be processed differently in separate runs.
- **Problema risolto:** Constructing a synthetic article chain that never existed.
- **Compromesso accettato:** A chain can remain incomplete despite matching global content elsewhere.
- **Alternative scartate:** Global `content_id` stitching.
- **Motivo dello scarto:** It violates process-instance identity.
- **Non reintrodurre:** Cross-run role borrowing.
- **Riconsiderazione:** Only through an explicit cross-run lineage contract that does not claim one processing instance.
- **Fonti:** `S7` §§3.3, 5.4, 7.5.

### CP-04 — Cache/state historical authority (consolidated)

- **Status:** HISTORICAL ONLY
- **Consolidation note:** Semantic consolidated into `OB-04`. ID reserved and must not be reused.
- **Historical knowledge retained:** TTL memories and current caches serve runtime decisions but cannot establish historical event-window totals. This cache-specific application is now explicit in the active general current-state versus event-history rule `OB-04`.
- **Fonti:** `S6` §§6.2, 7.5; `S7` §8.4; Decision Change Log 2026-08-20.

### CP-05 — Cache invalidation is atomic and contract-fingerprinted

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** PENDING RUNTIME VERIFICATION
- **Decisione attiva:** Incompatible duplicate-cache structures are ignored or rebuilt atomically; reuse depends on all material and policy inputs.
- **Motivazione:** A stale arbitration decision can wrongly block or admit content.
- **Problema risolto:** Partial rollout and policy changes reusing invalid decisions.
- **Compromesso accettato:** Cold-cache cost after contract changes.
- **Alternative scartate:** Best-effort partial reuse across scorer/prompt/threshold versions.
- **Motivo dello scarto:** Correctness cannot be proven.
- **Non reintrodurre:** Non-atomic migration or incomplete cache keys.
- **Riconsiderazione:** With an equivalent transactional/versioned migration mechanism.
- **Fonti:** `S4` §9.

## 15. Reliability and fallback

### RF-01 — Telemetry fail-open reliability (consolidated)

- **Status:** HISTORICAL ONLY
- **Consolidation note:** Semantic consolidated into `RT-01`. ID reserved and must not be reused.
- **Historical knowledge retained:** Canonical producer/reader defects remain telemetry defects; an operationally successful run may have incomplete diagnostics. These details are now retained by active canonical decision `RT-01`.
- **Fonti:** `S6` §7.6; `S7` §§2.3, 5.3; Decision Change Log 2026-08-20.

### RF-02 — Scoped duplicate fail-closed reliability (consolidated)

- **Status:** HISTORICAL ONLY
- **Consolidation note:** Semantic consolidated into `MD-09`. ID reserved and must not be reused.
- **Historical knowledge retained:** Clearly distinct candidates and independent components remain unaffected by a failed Gemini duplicate decision. The active canonical rule and its conservative trade-off now remain in `MD-09`.
- **Fonti:** `S4` §10; Decision Change Log 2026-08-20.

### RF-04 — WordPress retry-strategy changes require a baseline

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Authority note:** Current authority derives from explicit owner confirmation, not from the programmatic nature of `S5`.
- **Decisione attiva:** WordPress retry-strategy changes require an authoritative baseline before activation.
- **Motivazione:** Retry, delay, readiness and fail-fast changes must be evaluated against observed recovery and failure behavior.
- **Problema risolto:** Anecdotal changes that increase delay, wasted work or missed publications without proving an operational benefit.
- **Compromesso accettato:** Potential retry/readiness optimizations are postponed until current recovery, delay, failure and endpoint behavior are measurable.
- **Alternative scartate:** Changing startup, retry or circuit-breaker policy from isolated incidents or generic assumptions.
- **Motivo dello scarto:** Without a baseline, reliability and economic effects cannot be distinguished from normal WordPress/network variability.
- **Non reintrodurre:** A WordPress retry-strategy change without pre-change coverage, success criteria and regression evidence.
- **Riconsiderazione:** When the baseline establishes current recoveries, delays, terminal failures and the predictive value of relevant endpoints.
- **Fonti:** `S5` §7.8 (programmatic rationale only); `OWNER`.

### RF-05 — Reliability recovery path remains explicit

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** The retry, repair, fallback and recovery path remains observable even when the final outcome is success; first-attempt success and recovered success are distinct reliability outcomes.
- **Authority boundary:** `RF-05` owns reliability lifecycle interpretation; it does not own provider usage or cost attribution, which belongs to `GC-02` and the Gemini ledger authority.
- **Motivazione:** A recovered success has different operational reliability meaning from a first-attempt success.
- **Problema risolto:** Hidden operational fragility behind an undifferentiated final success.
- **Compromesso accettato:** More event volume and reporting complexity.
- **Alternative scartate:** Final-outcome-only telemetry.
- **Motivo dello scarto:** It conceals recovery paths and recovered incidents.
- **Non reintrodurre:** Erasing recovery path once a request succeeds.
- **Riconsiderazione:** Only with an equivalent richer reliability model.
- **Fonti:** `S7` §§4.2–4.3, 7.3.

### RF-06 — Missing authority is explicit during fallback

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** CONFIRMED BY CURRENT FINAL SOURCES
- **Decisione attiva:** Diagnostic fallback may remain visible, but cannot manufacture authoritative values or override complete canonical evidence.
- **Motivazione:** Availability of some legacy evidence is not semantic equivalence.
- **Problema risolto:** Fallback silently changing authority.
- **Compromesso accettato:** Readers may provide diagnostics without an authoritative number.
- **Alternative scartate:** Automatic legacy substitution whenever canonical data is incomplete.
- **Motivo dello scarto:** False precision and inconsistent readers.
- **Non reintrodurre:** Hidden authority promotion in fallback code.
- **Riconsiderazione:** Only through explicit, versioned authority migration.
- **Fonti:** `S6` §§3.4, 7; `S7` §§5.1–5.3, 7.1.

## 16. Codex / review / release workflow

### CR-01 — Work specifies and reviews; Codex implements

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** OWNER CONFIRMED — 2026-08-20
- **Decisione attiva:** Work reconstructs authority, performs pre-implementation review, designs bounded specifications/prompts and reviews evidence; code changes are performed through Codex with human-controlled handoffs.
- **Motivazione:** Architectural memory and implementation execution require distinct controls.
- **Problema risolto:** Unreviewed code changes and loss of owner authority.
- **Compromesso accettato:** Manual transfer/review steps add latency.
- **Alternative scartate:** Work silently modifying production code or assuming Codex work was automatically reviewed.
- **Motivo dello scarto:** Scope, audit and authority risk.
- **Non reintrodurre:** Implementation without an explicit prompt, diff/test evidence and human review path.
- **Riconsiderazione:** Only through explicit owner-approved workflow revision.
- **Fonti:** `S3` §§1–3; `OWNER` and current Work governance.

### CR-02 — Pre-PR review uses supplied diff, summary and tests and must converge

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** LEGACY ONLY
- **Decisione attiva:** Before a PR exists, review is based on the full materials supplied by the owner; iterations stop once concrete blockers are resolved, scope is respected and tests are green.
- **Motivazione:** A branch not exposed through the repository connector cannot be reviewed as if remotely visible.
- **Problema risolto:** False review claims and endless cosmetic loops.
- **Compromesso accettato:** Completeness depends on the supplied diff/test package.
- **Alternative scartate:** Pretending the branch is available; infinite micro-correction cycles.
- **Motivo dello scarto:** Unverifiable review and wasted effort.
- **Non reintrodurre:** Closure delayed by non-material comments after acceptance criteria are met.
- **Riconsiderazione:** If tooling makes the full branch authoritatively available earlier.
- **Fonti:** `S3` §§1–2.

### CR-03 — PR review begins from the actual PR state

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** LEGACY ONLY
- **Decisione attiva:** Once the owner opens the PR, review addresses concrete comments and the updated repository diff until relevant findings are resolved.
- **Motivazione:** PR state is the reviewable integration artifact.
- **Problema risolto:** Reviewing stale or partial implementation material.
- **Compromesso accettato:** Manual owner coordination remains part of the cycle.
- **Alternative scartate:** Treating pre-PR notes as proof of final PR correctness.
- **Motivo dello scarto:** The branch can change.
- **Non reintrodurre:** Merge recommendation based on a superseded diff.
- **Riconsiderazione:** With an equivalent authoritative review integration.
- **Fonti:** `S3` §3.

### CR-04 — Merge requires production validation before closure

- **Status:** ACTIVE GUARDRAIL
- **Current confirmation:** LEGACY ONLY
- **Decisione attiva:** Validate installed commit, runtime versions, compilation, targeted/full tests as appropriate, smoke behavior, production state safety and final working-tree status on the VPS.
- **Motivazione:** Deployment correctness is not identical to repository correctness.
- **Problema risolto:** Undetected environment and operational regressions.
- **Compromesso accettato:** Release completion takes longer than merge.
- **Alternative scartate:** CI-only or merge-only closure.
- **Motivo dello scarto:** Production-specific conditions remain untested.
- **Non reintrodurre:** Declaring operational success before VPS evidence.
- **Riconsiderazione:** With equivalent automated production acceptance evidence.
- **Fonti:** `S3` §4.

### CR-05 — Review is rigorous but finite

- **Status:** ACTIVE TRADE-OFF
- **Current confirmation:** LEGACY ONLY
- **Decisione attiva:** Continue review while concrete, relevant issues remain; stop when functionality, scope, non-regression, tests and VPS validation satisfy the closure contract.
- **Motivazione:** Marginal micro-edits can indefinitely delay safe value.
- **Problema risolto:** Review loops without a material stopping condition.
- **Compromesso accettato:** Non-impactful imperfections may remain.
- **Alternative scartate:** Both premature closure and perfection-without-limit.
- **Motivo dello scarto:** The former raises risk; the latter raises operational cost without concrete benefit.
- **Non reintrodurre:** New blocking requests lacking a specific impact after criteria are satisfied.
- **Riconsiderazione:** When explicit risk or acceptance evidence changes.
- **Fonti:** `S3` §§2–5.

## 17. Historical-only register

### HO-01 — v92 “maximum three” context

- **Status:** HISTORICAL ONLY
- **Knowledge retained:** Earlier operation discussed a maximum of three news per run; the durable decision was that a maximum is a ceiling, not a target.
- **Fonti:** `S1` §Scoring and publication count.

### HO-02 — v93 daily target and five-window assumptions

- **Status:** HISTORICAL ONLY
- **Knowledge retained:** v93 described 20–30 normal news per day, five windows and suggested per-run volumes. Current FINAL sources do not ratify those numeric assumptions as architectural invariants.
- **Fonti:** `S2` §4.

### HO-03 — Phase 0 pre-authority observation state

- **Status:** HISTORICAL ONLY
- **Knowledge retained:** P1.1 initially emitted observational, non-authoritative events; P1.4 later promoted the covered common snapshot/read model. The early non-authoritative status must not be mistaken for current Phase 1 authority.
- **Fonti:** `S7` §§2, 5.

### HO-04 — Legacy diagnostic files remain context, not silent authority

- **Status:** HISTORICAL ONLY
- **Knowledge retained:** Master logs, current snapshots, Publisher/Simone histories and Menzo TTL artifacts explain earlier diagnostics and baseline limitations; their existence does not grant them current canonical authority.
- **Fonti:** `S6` §§2, 6; `S7` §5.1.

## 18. Open questions

### OQ-01 — Andrea canonical coverage

- **Status:** OPEN QUESTION
- **Question:** Which producer/reader gap prevents complete per-content Andrea canonical coverage?
- **Constraint:** Do not replace missing canonical Andrea evidence with legacy counters.
- **Success evidence:** Complete, validated event coverage and reader convergence.
- **Fonti:** `S7` §8.1.

### OQ-02 — Alfred reconciliation equivalence

- **Status:** OPEN QUESTION
- **Question:** Which remaining report comparisons still combine non-equivalent warning/blocker grains?
- **Constraint:** Preserve occurrence, unique-content and final-unresolved distinctions.
- **Success evidence:** Semantically equivalent reconciliation without unexplained mismatches.
- **Fonti:** `S7` §8.2.

### OQ-03 — Authoritative Gemini monetary cost

- **Status:** OPEN QUESTION
- **Question:** When and under which versioned configuration will `config/gemini_pricing.json` make monetary estimates authoritative?
- **Constraint:** Token evidence must not be presented as authoritative currency cost while pricing is unconfigured.
- **Success evidence:** Validated price/version/coverage evidence by model, agent, purpose and logical work.
- **Fonti:** `S7` §8.3.

### OQ-04 — Menzo efficiency baseline and optimization

- **Status:** OPEN QUESTION
- **Question:** What measured balance of repair reduction, persistent reuse and prompt/context reduction preserves duplicate quality?
- **Constraint:** No loss of real duplicate blocking or material updates; preserve gate and authority guardrails.
- **Success evidence:** Lower calls/tokens/repairs with stable editorial outcomes.
- **Fonti:** `S7` §§6.3, 8.4, 9; `S4` §§11–13.

### OQ-05 — Canonical retention and compaction

- **Status:** OPEN QUESTION
- **Question:** What retention, archival and compaction policy controls VPS storage while preserving required auditability?
- **Constraint:** Do not mutate evidence or confuse current state with history.
- **Success evidence:** Versioned retention semantics, integrity validation and documented coverage impact.
- **Fonti:** `S6` §5; `S7` §3.

### OQ-06 — Future Gemini editorial director

- **Status:** OPEN QUESTION
- **Question:** After convergence, cost truth and Menzo optimization, does a broader Gemini editorial director produce sufficient net editorial value?
- **Constraint:** It is deferred, not rejected, and cannot be smuggled into convergence work.
- **Success evidence:** Stable baseline and comparative quality/cost/latency/reliability evaluation.
- **Fonti:** `S7` §9; `GC-05`.

### OQ-07 — Runtime confirmation of v95.18-specific duplicate parameters

- **Status:** OPEN QUESTION
- **Question:** Which exact v95.18 gate, threshold, cache and 12-hour-history details remain installed after the Phase 1 implementation sequence?
- **Constraint:** The handoff is not promoted to current runtime fact merely by being detailed.
- **Success evidence:** Repository/runtime inspection tied to the deployed commit.
- **Fonti:** `S4`; `S7` §§6.3, 7.6.

### OQ-08 — Owner review of legacy-only operational workflow details

- **Status:** OPEN QUESTION
- **Question:** Which `LEGACY ONLY` deployment/review and source-routing rules should be promoted, revised or retired in a future explicit decision?
- **Constraint:** Until then, they cannot override higher-authority guardrails.
- **Success evidence:** Owner confirmation or a successor FINAL operational contract.
- **Fonti:** `S2`; `S3`; `S5`.

## 19. Mandatory pre-implementation review contract

Before any new reform is designed or handed to Codex, the review must identify:

1. current behavior reconstructed from authoritative project evidence;
2. authorities involved before and after the proposed change;
3. applicable non-regression guardrails by decision ID;
4. previous decisions, intentional compromises and relevant rejected approaches;
5. API/Gemini cost, VPS resource, operational-complexity, reliability, maintenance and editorial-risk effects;
6. behavior that must remain unchanged;
7. baseline and diagnostic coverage available before activation;
8. success, safety, rollback and closure criteria;
9. any authority conflict and the explicit decision required to resolve it;
10. evidence showing that the reform measures the editorial/operational phenomenon, not only the current function implementation.

No implementation prompt should silently treat an `OPEN QUESTION`, `HISTORICAL ONLY` statement or programmatic proposal as an approved active design.

## 20. Decision Change Log

**Log schema version:** 1  
**Initial state:** version 1.0 was not ratified; version 1.0.1 records the semantic-drift corrections and consolidation decisions approved during ratification review.

| Date | Decision ID | Previous state | New state | Evidence / authority | Reason for change |
|---|---|---|---|---|---|
| 2026-08-20 | `RT-03` | Semantic conflict: sequential-runtime rule occupied the approved ID; preflight rule was duplicated as `RF-03` and marked `LEGACY ONLY` | Approved preflight/cost rule restored as `ACTIVE TRADE-OFF`, `OWNER CONFIRMED`; duplicate `RF-03` removed | Owner-approved reconciliation audit | Correct ID/semantic drift before ratification of 1.0.1 |
| 2026-08-20 | `EP-08` | Semantic conflict: reports rule occupied the approved ID; card policy was placed under `EP-09` | Approved PLE/PPV card policy restored as `ACTIVE TRADE-OFF`, `OWNER CONFIRMED`; reports duplication removed in favor of `SR-01` | Owner-approved reconciliation audit | Correct ID/semantic drift before ratification of 1.0.1 |
| 2026-08-20 | `EP-09` | Semantic conflict: PLE/PPV card policy occupied the approved ID; anecdotes/ratings/social rule was absent | Approved anecdotes/ratings/social rule restored as `ACTIVE TRADE-OFF`, `OWNER CONFIRMED` | Owner-approved reconciliation audit | Correct ID/semantic drift before ratification of 1.0.1 |
| 2026-08-20 | `RF-04` | Semantic conflict: media-failure rule duplicated `EP-10`; approved WordPress retry-baseline rule was absent | Approved WordPress retry-baseline rule restored as `ACTIVE GUARDRAIL`, `OWNER CONFIRMED`; media duplication removed | Owner-approved reconciliation audit | Correct ID/semantic drift before ratification of 1.0.1 |
| 2026-08-20 | `RT-01` / `RF-01` | Duplicate ACTIVE fail-open telemetry semantics | `RT-01` retained as canonical ACTIVE decision with producer/reader and incomplete-diagnostics details; `RF-01` declassified to `HISTORICAL ONLY` and reserved | Explicit owner reconciliation decision | Remove active semantic duplication without losing historical knowledge |
| 2026-08-20 | `OB-04` / `CP-04` | Duplicate ACTIVE current-state/cache versus event-history semantics | Cache/TTL application integrated into canonical `OB-04`; `CP-04` declassified to `HISTORICAL ONLY` and reserved | Explicit owner reconciliation decision | Consolidate the specific cache case under the general authority rule |
| 2026-08-20 | `MD-02` / `GC-01` | Duplicate ACTIVE deterministic-gate limitation on Gemini | Economic rationale integrated into canonical Menzo decision `MD-02`; `GC-01` declassified to `HISTORICAL ONLY` and reserved | Explicit owner reconciliation decision | Keep duplicate-gate authority in the Menzo family |
| 2026-08-20 | `MD-09` / `RF-02` | Duplicate ACTIVE scoped fail-closed semantics | Independent-candidate/component details integrated into canonical `MD-09`; `RF-02` declassified to `HISTORICAL ONLY` and reserved | Explicit owner reconciliation decision | Keep duplicate-failure isolation in the Menzo family |
| 2026-08-20 | `GC-02` / `RF-05` | Overlapping wording between provider/cost grain and reliability recovery lifecycle | Both remain ACTIVE with explicit non-overlapping authority boundaries: provider usage/cost in `GC-02`, recovered-success reliability in `RF-05` | Explicit owner reconciliation decision | Clarify separation without consolidation or new policy |

Future changes must append one row; they must not erase the prior classification without trace.

## 21. Maintenance policy

- New decisions receive stable IDs; existing IDs are not recycled.
- IDs declassified after semantic consolidation remain permanently reserved and cannot be reused for another meaning.
- A change to status, rationale, confirmation, source authority or non-regression behavior requires an explicit Decision Change Log entry.
- `RATIONALE NOT RECOVERED` must be used whenever the available sources establish a decision but do not support its motivation.
- Lower-authority material may add context but cannot silently weaken a higher-authority guardrail.
- Owner confirmation promotes only the specifically confirmed decision, not every proposal in the cited source.
- Runtime verification confirms implementation state; it does not by itself create editorial authority.

## 22. Closure principle

OpenWrestlingTV evolves by preserving explicit authority, semantic identity, measurable evidence and deliberate trade-offs. Elegance alone is not a success criterion. A reform is acceptable only when its editorial benefit, economic cost, operational reliability, maintainability and non-regression behavior can be evaluated against an authoritative baseline.
