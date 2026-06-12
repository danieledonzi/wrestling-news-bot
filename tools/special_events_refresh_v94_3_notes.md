# v94.3 - Special Events two-layer refresh

Planned implementation:

1. Layer 1 official discovery
   - Read official company event pages from `config/special_event_sources.json`.
   - Mark an event as officially discovered when one of its aliases is present in the official source.
   - Extract a date only if it is clearly associated with that event.

2. Layer 2 Wikipedia detail enrichment
   - For events already present in `config/special_events.json`, check likely Wikipedia pages such as `<Event Name> (2026)`.
   - Extract future dates from the article intro / infobox text.
   - Compare official dates, Wikipedia dates and registry dates.

3. Registry decision
   - No automatic write to `config/special_events.json`.
   - Generate proposals with `official_discovery_found`, `wikipedia_detail_found`, `existing_dates`, `detected_dates`, `matching_dates`, `new_candidate_dates`.

Approval policy:

- official discovery + Wikipedia date + registry date match = `no_action_if_dates_match`
- official discovery + Wikipedia future date + no registry date = `safe_to_accept_after_review`
- only Wikipedia = `manual_review`
- multiple conflicting dates = `manual_review`
