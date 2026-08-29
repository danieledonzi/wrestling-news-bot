# V96.4A translation correctness runtime note

## Problem and evidence

A non-empty Gemini response (`result=text`) could previously be treated as a successful Bob translation even when Bob JSON was malformed, translation units were absent or empty, or English source prose was returned unchanged. Production evidence includes an untranslated Bully Ray article passing both Bob and Alfred. The separate Lola Vice title incident is title-quality evidence only; this change deliberately adds no `revealed`/`rivolta` lexical rule or glossary.

## Runtime boundary

Bob now requires valid Bob JSON, a non-empty `title_it`, a translations object, and a non-empty value for every required unit. The deterministic boundary covers every user-visible translated field: title, rendered body units, and any non-empty excerpt. An absent or empty excerpt remains allowed; a supplied non-empty excerpt must be text and must not be unchanged/highly similar English source-description prose or conservatively detectable residual English. Failures use `translation_validation_failed`, retain bounded structured diagnostics, and expose neither source-fallback content nor invalid translated fields as successful output.

Alfred independently blocks bodies substantially unchanged from retained source elements, macroscopically English prose, clearly English unchanged titles, and obviously untranslated non-empty excerpts. It reports stable blockers; it does not translate, broadly rewrite, change facts or quotations, or infer content.

This adds no provider calls, model changes, prompt changes, retries, fallback models, pricing changes, or Gemini-ledger semantic changes. `result=text` continues to mean only that non-empty provider text was received. Bob remains translation-only and Alfred remains a conservative local quality gate; Menzo, Publisher, Simone, and editorial authority are unchanged.

## Validation plan

* **Immediate:** verify the installed commit, service/timer health, normal Bob/Alfred execution, and no provider-call increase.
* **24 hours:** review validation failures and reasons, false positives, Alfred English blockers, and articles reaching Publisher.
* **72 hours:** inspect malformed, incomplete, and unchanged-English examples separately; confirm wrestling names, shows, quotations, and terminology remain accepted.
* **7 days:** decide from frequency whether a future semantic repair/retry is justified and review recurring title-quality evidence, including lexical anomalies.

## Rollback

Rollback is the single V96.4A commit. No state migration or canonical-history rewrite is required. Deployment remains an OWNER decision while V96.3A evidence collection continues; automatic semantic retry remains out of scope.
