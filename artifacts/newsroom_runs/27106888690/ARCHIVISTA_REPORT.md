# Archivista report - 2026-06-07T22:37:27.260159+00:00

Status: **error**
Runs in ledger 48h: 62 | Published current run: 2 | Anomalies: 3

## Agent handoff
- massy: `{"to_simone": 0, "to_menzo": 19, "already_worked": 0, "hard_skipped": 16, "already_published_hard_skipped": 4, "menzo_memory_hard_skipped": 12, "old_news_hard_skipped": 0, "report_candidates_blocked_by_manual_or_history": 0, "event_recap_duplicates_blocked_by_report": 0, "event_factual_news_to_menzo": 0, "post_show_hard_news_to_menzo": 0, "event_soft_reactions_to_menzo": 0, "story_memory_hard_skipped": 0, "story_batch_hard_skipped": 0}`
- simone: `{"ready": 0, "waiting": 0, "skipped": 6}`
- menzo: `{"to_bob_or_v92": 6, "pending": 0, "skipped": 13}`
- bob: `{"ready_for_alfred": 3, "translation_pending": 0, "errors": 0, "extraction_empty": 0}`
- alfred: `{"approved": 2, "needs_revision": 1, "warnings": 3, "blockers": 1, "editorial_changes": 0}`
- publisher: `{"published": 2, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}`

## Anomalies
- **error** `alfred_blockers`: Alfred ha trovato blocker qualitativi.
- **warning** `alfred_revision`: Alfred ha mandato articoli in revisione.
- **warning** `article_needs_revision`: Articolo fermato da Alfred.

## Articles
### Nikki Blackheart Shuts Down Fan Who Told Her to Stop Cutting Promos
- URL: https://www.ringsidenews.com/nikki-blackheart-shuts-down-fan-who-told-her-stop-cutting-promos
- Bob: None | Alfred: None | Publisher: None
### Steve Maclin Sets the Record Straight on TNA Exit Announcement
- URL: https://www.ringsidenews.com/steve-maclin-sets-record-straight-tna-exit-announcement
- Bob: None | Alfred: None | Publisher: None
### Cancellato il processo per la causa degli azionisti WWE
- URL: https://www.ringsidenews.com/why-wwe-shareholder-lawsuit-trial-suddenly-cancelled
- Bob: ready_for_alfred | Alfred: approved | Publisher: published
- WP: https://news.openwrestlingtv.com/world/cancellato-il-processo-per-la-causa-degli-azionisti-wwe/
### La WWE ritiene che Mike Santana lascerà TNA alla scadenza del contratto
- URL: https://www.ringsidenews.com/wwe-believes-mike-santana-leaving-tna-when-his-contract-expires
- Bob: ready_for_alfred | Alfred: approved | Publisher: published
- WP: https://news.openwrestlingtv.com/tna/la-wwe-ritiene-che-mike-santana-lascera-tna-alla-scadenza-del-contratto/
### R-Truth Says WWE Contract Situation Was 'The Most Moving' Experience Of His Life - Wrestling Inc.
- URL: https://www.wrestlinginc.com/2188668/wwe-r-truth-contract-most-moving-experience-life
- Bob: ready_for_alfred | Alfred: needs_revision | Publisher: None
### Sol Ruca's First Women's IC Title Defense Set For WWE Raw In Paris
- URL: https://www.wrestlinginc.com/2189064/sol-ruca-first-womens-ic-title-defense-raw-paris-wwe
- Bob: None | Alfred: None | Publisher: None
