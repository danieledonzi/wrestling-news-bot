# Alfred newsletter citations and factual pair admission — 2026-10-18

Owner authorization: two bounded interventions, Alfred and pair admission. Base: main/production
`f812c2472d2d706f9c72c3955fd092f06cfa843c` (PR163).

## Scope

Alfred no longer treats the standalone word `newsletter` as a CTA. Editorial citations, including references
to the Wrestling Observer Newsletter and reported speech about subscribing, remain reporting. Actual signup,
subscription, promotional and comment/social invitations remain blockers. New newsletter expressions require
promotional wording; imperative expressions allow common invitation lead-ins and are bounded to sentence
or HTML block starts, including after an unpunctuated paragraph. Inline markup remains transparent. The
block-aware representation is used only for CTA detection. Existing language, HTML, quote,
table, source-credit, translation and publication checks remain intact. No new AI request is introduced.

Admission V6 uses the existing one-anchor request and complete source bodies. Every suspected pair supplies
`anchor_fact`, `target_fact` (<=500 characters each), and the existing `basis` explaining a specific potentially
repeated/continuing development. Context-only overlap (show, promotion, person, broad action category) is
insufficient. Literal refs, source endpoint binding, sparse positive output, single attempt and exact-material
success caching remain. Local validation checks shape/length/refs only, never semantic adequacy or keyword
overlap. Genuine uncertainty, duplicates and important updates still reach the separate two-article judge.
Factual evidence is preserved with original anchor/target IDs even when same-run pair identities are sorted,
and is exposed with the existing prefilter relation telemetry.

The owner clarification on multi-story roundups is recorded in the canonical totems and admission policy:
a roundup does not automatically cover dedicated feed news. The approved detailed Jay White article remains
autonomous. This is not blanket pair immunity or permission for every extra detail/media asset to create an
update between equivalent dedicated articles. The independent judgment policy V4 is unchanged. Primary
classifications, 12-hour history, terminal skips, report source/rendering, pacing, model routing, complete-body
extraction, important-update threshold and same-run A+B coverage are unchanged. No runtime cache is purged.
The pair-cache fingerprint derives its admission contract from the live admission VERSION: old-contract
entries cannot reinstate pairs excluded by V6, while same-contract final decisions retain their binding reuse.

## Owner-directed URL closure

The old WrestlingInc Caster denial URL `/2289284/wwe-tna-max-caster-sources-deny-involvement-exit/` was closed
permanently at `2026-10-18T06:03:36.110858+00:00`, before further translation/publication. Its primary SHOULD
classification remains immutable; a distinct `owner_editorial_skip` tombstone records the final disposition
and the superseding therapy-news URL. Only that queue row was removed. The primary store, published history,
soft pool and source material remained byte-identical during this owner-directed action. Other URLs remain
untouched. The real source still serves as a retained offline quality regression; replay does not reopen it.

## Verification

- Fresh isolated production-Python checkout: **1,863 tests pass**, one previously established failing
  oversized-body recovery test excluded. Forty-four new regressions cover editorial citations, real CTA
  language, retained safety checks, required factual fields, endpoint evidence binding, cache reuse and owner
  terminal closure without primary reclassification, and exclusion of old-contract cached admissions while
  preserving current-contract binding decisions. Eight existing fixture providers now emit the new factual
  fields; their existing semantic/failure assertions are preserved.
- Actual retained Caster translation: baseline Alfred reports only `cta_residue: Newsletter`; new Alfred
  reports no issue and approves it. No new translation or WordPress write was used for this control.
- Nine retained-body admission controls: all five unrelated cases are excluded; all four genuine overlap/
  continuation cases remain admitted (Dragunov debut, Ospreay result, Stacks injury and Dragunov's professional
  explanation). The old policy reproduces an unrelated Jay White/Maya World suspicion (four of five unrelated
  controls clear); the candidate clears all five. These are controlled retained-body inputs, not claimed exact
  reconstructions of complete historical cohorts, and semantic model outcomes remain non-deterministic.
- Jay White roundup/dedicated boundary is checked at the publication-eligibility grain. Both admission policies
  can elect the pair. The unchanged isolated full-body judgment returns MATERIAL_UPDATE and retains the
  dedicated article. An initial expectation of pair immunity was overly restrictive and is not the release
  acceptance criterion; no blanket roundup bypass or judge change was added to force it.
- Model controls use the same installed Gemini model and only isolated diagnostic files. They do not run the
  producer, write production ledgers/state or publish. Total controlled provider requests: 27 (16 initial
  admission controls, 10 final admission controls and one Jay eligibility judgment).

The runtime request count per anchor is unchanged. The explicit instructions/facts add tokens (about 524
prompt tokens in the fixed control payloads); fewer unrelated full judgments can offset that work, but no
aggregate cost reduction or perfect future semantic classification is assumed. Final VPS validation must
verify reviewed file hashes, compile affected modules, repeat the retained Caster review, confirm the owner
tombstone and preserve all remaining newsroom state during deployment.
