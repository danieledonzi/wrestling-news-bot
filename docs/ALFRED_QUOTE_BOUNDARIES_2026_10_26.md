# Alfred quotation boundaries — 2026-10-26

Owner authorization: implement the diagnosed quotation-boundary correction and
complete review, release and VPS validation. Repository and production baseline:
`a650298a386533e40dc16ba2199bf1183f6c36f9`.

## Evidence and bounded correction

The Vic Joseph/Beyond The Bell article was held on three runs before publication.
The retained Bob HTML reproduces the failure: the single-quote matcher interpreted
the apostrophe in `l'universo` as an opening delimiter and captured 421–473
characters of Italian prose. Three occurrences of `the` in program/network names
triggered the existing language heuristic. The resolver identified branding but
correctly could not allow the whole long expression under the short-name rule.
The fourth translation passed with a different incidental pairing of apostrophes.

Single-quote delimiters now require word boundaries;
contractions and elisions remain part of the quoted text. Ambiguous possessives
such as `James' work` retain both the shorter and enclosing quote interpretation
so the remainder of English speech still receives the language check. Straight double and
typographic quotes consume short pairs before the existing eight-character
filter, so a short name such as `WWE NXT` cannot shift subsequent delimiter pairs.
Curly single quotes and guillemets are covered by the same extraction contract.

This changes only quotation extraction in `agents/alfred.py`. It does not rewrite
article bytes, alter language thresholds, resolver acceptance rules, provider
models, retries, editorial classification, duplicate decisions, report scheduling
or publication pressure. Real untranslated quotations must still block. Invalid
resolver JSON remains a separate issue; no provider compatibility change is part
of this patch.

## Verification and operational closure

The regression fixtures are the four retained translated candidates, copied into
tests with archive provenance; original production artifacts remain immutable.
Tests exercise base Alfred plus its refinement path, require those candidates to
pass unchanged without any resolver call, and retain blocking for actual English
speech under straight/curly/single/double/guillemet delimiters, contractions and
nested quotations. Offline tests use the production Python environment in an
isolated checkout without production credentials.

Applicable guardrails: BT-02 (faithful translation), AQ-01 (limited corrections),
GC-03 (provider ledger authority), CP-02 (immutable retained material) and CR-04
(VPS validation before closure). No authority migration or policy exception is
introduced. Rollback is a code revert; there is no state or cache migration.

Closure requires regression checks, PR review, merged-code identity on the VPS,
targeted post-deploy checks and proof that deploy/smoke checks left production
state untouched. A future genuinely untranslated quote remains subject to the
normal blocker and resolver contracts.
