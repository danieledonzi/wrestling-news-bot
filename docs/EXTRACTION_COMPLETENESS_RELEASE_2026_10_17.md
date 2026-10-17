# Complete editorial extraction: seven blocked sources — 2026-10-17

Owner authorization: correct the extraction reform and verify all seven previously diagnosed sources. Production base: main `f73780ac001c9b35dc62875ba22a6d5132a37724` (PR162).

## Scope and preserved behavior

Changes are restricted to Bob's deterministic extraction, shared source-body diagnostics and their source-material observations. No Gemini calls are added. Models, primary classes, duplicate policies/admission/judgment, source election, report renderer, publication scheduling and soft competition are unchanged. Existing valid primary classifications and terminal SKIPs remain final. No URL is forced to publish and no source/body cache is purged.

Ringside coverage now uses the unique `.entry-content.rsn-single-content` body inside its identified `rsn-single-article`, rather than charging headline/byline/author/Spotlight text against the cleaned body. The outer article remains the root for media extraction and all paywall/access-wall checks. The 55% DOM threshold, structured-body agreement and minimum text requirements are unchanged; ambiguous/unrecognized DOM retains the existing fallback.

A reference to a newsletter is not a subscription CTA. An editorial paragraph or quotation about following people is not an author bio. Quote blocks cannot terminate extraction through the generic bio rule. Identifiable source-promotion sentences are removed individually so substantive facts before/after them survive. Known author-box containers are excluded structurally, which also allows the existing terminal transcript-credit cleanup to operate without retaining a generic author bio. Text/media traversal order is unchanged.

Source failures now retain bounded structured diagnostics (coverage roots, counts/ratios, incomplete reasons, access markers) in source observations and technical holds. The diagnostics contain no HTML or article body, survive the same-attempt backoff, and are replaced/cleared when a different attempt has different evidence. Retry deadlines, retry policy and technical-HOLD semantics are unchanged.

## Replay evidence

All seven original HTML pages were fetched and saved in an isolated VPS `/tmp` diagnostic directory before changing production. Baseline extraction rejects every one. The candidate replay verifies the complete contract, every expected substantive paragraph/quote/heading, and absence of the identified author/CTA/transcript material. The retained public HTML snapshots are not committed to the repository.

| Source | Baseline cleaned chars | Corrected cleaned chars | Corrected coverage | Substantive blocks checked |
|---|---:|---:|---:|---:|
| Stacks hospitalized | 1,196 | 1,592 | 86.38% | 7 |
| ROH Final Battle date/venue | 1,151 | 1,151 | 87.60% | 5 |
| SmackDown closing spoiler | 922 | 800 | 73.60% | 5 |
| SmackDown opening spoiler | 921 | 799 | 74.81% | 5 |
| John Cena following accounts | 1,493 | 3,964 | 91.27% | 16 |
| Next SmackDown card | 1,181 | 1,075 | 79.75% | 6 |
| WWE denial concerning Max Caster | 963 | 1,660 | 90.46% | 4 |

**Seven of seven pass; 48 substantive blocks checked; zero missing blocks; zero identified boilerplate residues.** Shorter corrected bodies reflect removal of source-promotion sentences, not omitted facts. Stacks retains the diagnostic uncertainty paragraph; Cena retains the opening and all substantive interview quotes and final explanation; Caster retains all four paragraphs including both Newsletter citations and the WWE denial.

## Non-regression evidence

Six targeted regressions fail against the baseline. The final focused suite covers short real-layout articles, source citations, genuine CTAs and bios, mixed factual/promotional paragraphs, quote preservation, author containers and transcript notices, real partial bodies, paywalls inside/sibling/ancestor to the measured body, and diagnostic backoff/fresh-attempt behavior.

The complete VPS Python/venv suite passes 1,816 tests, with one already known oversized-body recovery test excluded after its same baseline failure had previously been established. It also fails unchanged in the first complete extraction suite run (1,808 other tests passed); that recovery mechanism is outside this reform. Report ordering, media/embeds, frozen classifications, permanent skips and duplicate contracts remain covered by the existing suite. Automated review additionally prompted regression coverage for prefixed social-follow calls and non-imperative newsletter promotion, while the seven substantive bodies remain protected.

Tests/replays do not run the newsroom producer, call Gemini or write WordPress. Release validation must check the reviewed files on the installed VPS, replay all seven using the installed extractor, and preserve editorial state during deployment. The normal scheduled pipeline owns subsequent classification and possible publication; extraction success does not establish editorial merit.
