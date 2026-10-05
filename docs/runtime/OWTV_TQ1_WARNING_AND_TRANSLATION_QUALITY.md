# TQ-1 — Warning and translation quality diagnostics

## Problem and baseline

Base: main `9ed805a44461040ba8a5277db77794de0f3e5d4e` after DR-1/PS-1.
VPS daily evidence generated 2026-10-05 10:00 UTC: 19 unique published news,
19 source/candidate/final inventories, 20 unique article/code investigations:
15 insufficient_material and 5 technical. Twelve signals were
blockquote_missing_for_long_quotes. The canonical final retained representation
is flattened text; the old audit treated its unknown markup as zero blockquotes.
The role resolver also selected Alfred's approved HTML as the candidate because
both Bob and Alfred declare translated_candidate. This hid the original Bob stage.

## Contract and scope

TQ-1 is diagnostic only. Selection, duplicate recovery, show-news priority,
reports, Bob/Alfred prompts and runtime gates, model routing, retry, provider
calls and publication state stay under their existing authorities. V96.4A remains.
No model, network service or semantic judge is invoked. Prompt/guardrail changes
require repeated evidence and reviewed context; generated suggestions are hypotheses.

The audit keeps its compatible artifact_marker and adds schema_version
owtv_tq1_audit_v1. Bob and Alfred approved bodies are resolved separately by
producer within the publication instance selected by canonical content/correlation.
Integrity checks of the canonical artifact reader apply to both. An absent Bob
body is not replaced by Alfred or by a legacy body from another run.

Final plain text proves content, not HTML structure. final_markup_available=false
prevents a newly generated missing-blockquote or paragraph-drop conclusion from
that representation. An older structural warning is investigated as
final_structure_unavailable; unknown structure is not reported as correctness.

## Versioned taxonomy and evaluations

Policy owtv_tq1_rules_v1, analysis schema owtv_tq1_analysis_v1. Existing status
names remain compatible. reproduced means a local predicate matches; it is not
a confirmed semantic error. not_reproduced means the same available predicate
does not match, not proof that the article is flawless. possible_false_positive
is a candidate supplied by the audit, not an adjudicated label. technical is
separate. insufficient_material now has an explicit unavailable_reason:
source_material_unavailable, final_material_unavailable, title_material_unavailable,
source_structure_unavailable, final_structure_unavailable or evaluator_unavailable.

Lexical evaluators cover match/release/retirement/cleared, literal calques,
promo/chop gender and style triggers. Source-trigger context, short excerpts and
Bob/Alfred/final stage traces support review without assigning causal blame.
Title length reuses Alfred's >95 threshold. Residual English reuses the audit's
full conjunction, including its English-token minimum. Structural/comparative
checks require their actual materials. All semantic_verdict values are not_assessed.

## Weekly Pattern Report and operational integration

scripts/build_weekly_pattern_report.py reads one rolling 168h audit, without a
detail cap. It never sums overlapping daily snapshots. Grain: one unique article
and warning code. Three distinct articles marks a recurring review candidate,
not permission to rewrite a prompt. Technical cases do not enter the linguistic
review queue. Reproduction-rate denominator is reproduced+not_reproduced; zero
evaluated cases gives null. Confirmed false-positive rate is null until human
adjudication exists. Missing/incomplete publication authority, truncation or
duplicate identities makes available=false and the population count null.

The daily helper refreshes rolling weekly diagnostics after existing daily stages.
It adds a compact summary and current JSON/Markdown to the existing reporting
helpers. The external VPS caller already invokes generate_daily_diagnostics_24h
and the warning body helper; its attachment path is verified separately on deploy.
No additional email is sent by the diagnostic command.

Outputs: reports/owtv_weekly_quality_patterns_168h_<timestamp>.json/.md,
state/reports/owtv_weekly_quality_patterns_latest.json and a separate
state/reports/owtv_translation_quality_audit_weekly_latest.json. Daily latest
audit remains 24h. Failures overwrite weekly latest with explicit unavailable
state; integration never returns a previous result as current.

Coverage is the existing published-news audit population. Rejected translations,
blocked candidates and canonical report-show materials are not silently counted
as covered. Model-specific quality attribution and automatic semantic repair are
future evidence-dependent work, not inferred here.

## Validation and acceptance

The minimized corpus includes the observed Ryback idiom/statement ambiguity,
synthetic genuine calques, correct wrestling terms, residual prose and source
promotion. Tests cover separate producers, the same publication instance despite
later failed runs, structure availability, status reasons, exact thresholds,
unique grain, rates/nulls, population gaps and stale-output suppression.
Deployment requires compile/regression checks and a local-only diagnostic pass
on production evidence. Observation should review recurring candidates and
missing evaluators before authorizing any behavioral quality reform.
