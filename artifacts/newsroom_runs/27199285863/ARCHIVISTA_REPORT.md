# Archivista report - 2026-06-09T10:14:14.381034+00:00

Status: **error**
Runs in ledger 48h: 38 | Published current run: 0 | Anomalies: 6

## Agent handoff
- massy: `{"to_simone": 0, "to_menzo": 8, "already_worked": 0, "hard_skipped": 27, "already_published_hard_skipped": 0, "menzo_memory_hard_skipped": 10, "old_news_hard_skipped": 0, "report_candidates_blocked_by_manual_or_history": 0, "event_recap_duplicates_blocked_by_report": 0, "event_factual_news_to_menzo": 0, "post_show_hard_news_to_menzo": 0, "event_soft_reactions_to_menzo": 0, "story_memory_hard_skipped": 16, "story_batch_hard_skipped": 0}`
- simone: `{"ready": 0, "waiting": 1, "skipped": 5}`
- menzo: `{"to_bob_or_v92": 2, "pending": 7, "skipped": 2}`
- bob: `{"ready_for_alfred": 0, "translation_pending": 2, "errors": 0, "extraction_empty": 0, "publishable_left_out_by_capacity": 0}`
- alfred: `{"approved": 0, "needs_revision": 2, "warnings": 0, "blockers": 4, "editorial_changes": 0}`
- publisher: `{"published": 0, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0, "skipped_capacity": 0, "approved_not_attempted": 0, "approved_accounted_for": 0}`

## Anomalies
- **error** `alfred_blockers`: Alfred ha trovato blocker qualitativi.
- **warning** `alfred_revision`: Alfred ha mandato articoli in revisione.
- **warning** `article_bob_not_ready`: Articolo non pronto in Bob.
- **warning** `article_needs_revision`: Articolo fermato da Alfred.
- **warning** `article_bob_not_ready`: Articolo non pronto in Bob.
- **warning** `article_needs_revision`: Articolo fermato da Alfred.

## Articles
### Flag At WWE HQ Reportedly Causes Significant Power Outage - Wrestling Inc.
- URL: https://www.wrestlinginc.com/2189525/wwe-headquarters-flag-power-outage
- Bob: extraction_ready_translation_pending | Alfred: needs_revision | Publisher: None
### WWE's Danhausen Reportedly Expected As Guest At Game 3 Of NBA Finals - Wrestling Inc.
- URL: https://www.wrestlinginc.com/2189951/wwe-danhausen-nba-finals-game-3-expected-guest
- Bob: extraction_ready_translation_pending | Alfred: needs_revision | Publisher: None
