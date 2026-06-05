# Archivista report - 2026-06-05T17:28:32.052429+00:00

Status: **error**
Runs in ledger 48h: 54 | Published current run: 2 | Anomalies: 3

## Agent handoff
- massy: `{"to_simone": 1, "to_menzo": 5, "already_worked": 0, "hard_skipped": 29, "already_published_hard_skipped": 7, "menzo_memory_hard_skipped": 20, "old_news_hard_skipped": 0, "report_candidates_blocked_by_manual_or_history": 0, "event_recap_duplicates_blocked_by_report": 0, "event_factual_news_to_menzo": 0, "post_show_hard_news_to_menzo": 0, "event_soft_reactions_to_menzo": 0, "story_memory_hard_skipped": 1, "story_batch_hard_skipped": 0}`
- simone: `{"ready": 1, "waiting": 0, "skipped": 5}`
- menzo: `{"to_bob_or_v92": 3, "pending": 1, "skipped": 1}`
- bob: `{"ready_for_alfred": 3, "translation_pending": 0, "errors": 0, "extraction_empty": 0}`
- alfred: `{"approved": 2, "needs_revision": 1, "warnings": 2, "blockers": 1, "editorial_changes": 0}`
- publisher: `{"published": 2, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}`

## Anomalies
- **error** `alfred_blockers`: Alfred ha trovato blocker qualitativi.
- **warning** `alfred_revision`: Alfred ha mandato articoli in revisione.
- **warning** `article_needs_revision`: Articolo fermato da Alfred.

## Articles
### Nuovi match annunciati per la puntata di SmackDown del 5 giugno
- URL: https://www.ringsidenews.com/new-matches-revealed-june-5-wwe-smackdown
- Bob: ready_for_alfred | Alfred: approved | Publisher: published
- WP: https://news.openwrestlingtv.com/wwe/nuovi-match-annunciati-per-la-puntata-di-smackdown-del-5-giugno/
### WWE SmackDown: definita la data di fine per il formato da tre ore
- URL: https://www.ringsidenews.com/wwe-smackdowns-three-hour-run-now-end-date
- Bob: ready_for_alfred | Alfred: needs_revision | Publisher: None
### WWE annuncia una partnership strategica con la Juventus
- URL: https://www.wrestlinginc.com/2188371/wwe-juventus-football-club-strategic-partnership
- Bob: ready_for_alfred | Alfred: approved | Publisher: published
- WP: https://news.openwrestlingtv.com/world/wwe-annuncia-una-partnership-strategica-con-la-juventus/
