Undated weekly fallback report identity
======================================

The existing source order remains Ringside News until 08:30 Europe/Rome,
then Wrestleview. A publication timestamp does not establish the show's date.

For an otherwise eligible weekly Wrestleview results article with no explicit
title/slug date, Simone may inspect the article once the report is due and no
existing source can be elected. It accepts an explicit show/date report label
in the opening article blocks, or at least two distinct article YouTube videos
that explicitly name the configured show and agree on its date. Comments,
tweet timestamps, related content, previews and conflicting dates do not supply
this evidence. An explicit conflicting title/slug date is never repaired.

The URL/show/date/version-bound cache lives in
state/report_source_dates_v1/. Positive evidence references an immutable
SHA-256 HTML snapshot and is revalidated from that snapshot, including during
pending-source replay. Negative/network results retry after ten minutes.
Only accepted evidence retains HTML. This directory is outside state/newsroom,
so per-run newsroom snapshots do not recursively duplicate those HTML pages.
Snapshots and the evidence summary are runtime state, never source fixtures.
The selected pending reservation retains the evidence without changing the
original source headline. Existing successful completion records remain final.

This path adds no Gemini requests and does not change translation, publishing,
model routing, source priority or the 08:30 fallback deadline. Fetches have an
hard 8-second wall-clock deadline across redirects and body streaming, a 2 MB
page bound, and at most three HTTP requests for same-identity canonical spelling.
The POSIX main-thread deadline restores the previous signal handler; runtimes
that cannot provide that deadline leave the candidate waiting. Fetch/cache failures leave the article waiting with a specific reason.

Regression cases include the October 29 Impact article's two video titles,
wrong dates/shows, old and upcoming references, repeated videos, related-content
exclusion, redirect identity, cache/retry behavior and pending replay.
