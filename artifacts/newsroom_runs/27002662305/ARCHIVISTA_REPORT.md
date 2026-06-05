# Archivista report - 2026-06-05T07:53:05.763167+00:00

Status: **error**
Runs in ledger 48h: 44 | Published current run: 2 | Anomalies: 3

## Agent handoff
- massy: `{"to_simone": 1, "to_menzo": 25, "already_worked": 0, "hard_skipped": 9, "already_published_hard_skipped": 1, "menzo_memory_hard_skipped": 6, "old_news_hard_skipped": 0, "report_candidates_blocked_by_manual_or_history": 0, "event_recap_duplicates_blocked_by_report": 0, "event_factual_news_to_menzo": 0, "post_show_hard_news_to_menzo": 0, "event_soft_reactions_to_menzo": 3, "story_memory_hard_skipped": 1, "story_batch_hard_skipped": 0}`
- simone: `{"ready": 1, "waiting": 0, "skipped": 5}`
- menzo: `{"to_bob_or_v92": 9, "pending": 2, "skipped": 16}`
- bob: `{"ready_for_alfred": 3, "translation_pending": 0, "errors": 0, "extraction_empty": 0}`
- alfred: `{"approved": 2, "needs_revision": 1, "warnings": 1, "blockers": 1, "editorial_changes": 0}`
- publisher: `{"published": 2, "already_published": 0, "dry_run": 0, "wp_not_ready": 0, "errors": 0}`

## Anomalies
- **error** `alfred_blockers`: Alfred ha trovato blocker qualitativi.
- **warning** `alfred_revision`: Alfred ha mandato articoli in revisione.
- **warning** `article_needs_revision`: Articolo fermato da Alfred.

## Articles
### Booker T Says Brock Lesnar Is Still Huge For WWE But Oba Femi Needs A Real Ending
- URL: https://www.ringsidenews.com/booker-t-says-brock-lesnar-still-huge-wwe-oba-femi-needs-real-ending
- Bob: None | Alfred: None | Publisher: None
### Knockouts Title Match Set for 2026 TNA Slammiversary
- URL: https://www.ringsidenews.com/knockouts-title-match-set-2026-tna-slammiversary
- Bob: None | Alfred: None | Publisher: None
### ROH Title Match Confirmed for Global Wars Cincinnati
- URL: https://www.ringsidenews.com/roh-title-match-confirmed-global-wars-cincinnati
- Bob: None | Alfred: None | Publisher: None
### Seth Rollins: "Disgustato nel vedere CM Punk e Roman Reigns combattere per il mio titolo"
- URL: https://www.ringsidenews.com/seth-rollins-says-he-disgusted-watching-cm-punk-roman-reigns-fight-his-wwe-title
- Bob: ready_for_alfred | Alfred: approved | Publisher: published
- WP: https://news.openwrestlingtv.com/wwe/seth-rollins-disgustato-nel-vedere-cm-punk-e-roman-reigns-combattere-per-il-mio-titolo/
### Several WWE ID Talents Pulled From Dreamwave Wrestling All Star Weekend
- URL: https://www.ringsidenews.com/several-wwe-id-talents-pulled-dreamwave-wrestling-all-star-weekend
- Bob: None | Alfred: None | Publisher: None
### Former WWE Star Fabian Aichner Discusses Future In TNA
- URL: https://www.wrestlinginc.com/2187580/former-wwe-star-fabian-aichner-discusses-future-tna
- Bob: None | Alfred: None | Publisher: None
### Update On Frustrations With WWE's Handling Of Liv Morgan And Dom Mysterio
- URL: https://www.wrestlinginc.com/2187674/update-frustrations-wwe-handling-liv-morgan-dom-mysterio
- Bob: None | Alfred: None | Publisher: None
### Due wrestler lasciano la AEW dopo diversi anni
- URL: https://www.wrestlinginc.com/2188002/aew-departures-butcher-blade-gone
- Bob: ready_for_alfred | Alfred: needs_revision | Publisher: None
### AEW: si spera che l'infortunio di MJF non sia grave
- URL: https://www.wrestlinginc.com/2188012/aew-hoping-legitimate-mjf-injury-dynamite-serious
- Bob: ready_for_alfred | Alfred: approved | Publisher: published
- WP: https://news.openwrestlingtv.com/aew/aew-si-spera-che-linfortunio-di-mjf-non-sia-grave/
