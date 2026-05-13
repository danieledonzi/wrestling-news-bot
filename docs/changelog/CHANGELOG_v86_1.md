# CHANGELOG v86.1 - Scoring, report and validation stabilizer

## Added

- New version name: `v86_1_scoring_signature_validation_stabilizer`.
- WordPress verification before suppressing report/results articles from local history.
- Post-show outcome rescue for titles such as `Makes WWE In-Ring Debut During ...`, which must not be treated as expired previews.
- Contextual story signatures based primarily on title entities, article type and action bucket.
- Cleaner v86.1 boot diagnostics.

## Changed

- AAA major priority boost is now strict and requires a hard AAA anchor in the title or URL. Body-only mentions of AAA/TripleMania/Dominik no longer force score 100 or storm mode.
- Report keys found only in local `history.txt` no longer cause an automatic skip. If WordPress does not confirm the report, the bot attempts publication/recovery.
- Body/meta validation now strips removable source promo/meta sentences before failing a top candidate.

## Fixed

- NXT reports could be skipped because `report:wwe-nxt-YYYY-MM-DD` existed in local history even when WordPress did not confirm publication.
- Post-show debut items could be misclassified as expired previews.
- v71 story signatures could pick noisy body entities instead of the actual subject of the title.
- v80.4 AAA boost could incorrectly elevate ordinary WWE status/opinion stories.

## Preserved

- v86 hard embed engine and YouTube inline extraction.
- v85 draft-first publishing.
- v85.4 skipped history.
- v68/v70 preview and post-show rules.
