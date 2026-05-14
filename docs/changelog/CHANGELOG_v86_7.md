# Changelog v86.7

## Added

- Truth-based pending gate.
- Separate runtime sets for pending-loaded, processed, and actually published keys.
- Strict WordPress confirmation before skipping a true results report.
- Protection that keeps true results reports pending if they were not published and not confirmed on WordPress.

## Changed

- Rewrote the v72.1-style “already published from pending” behavior.
- True results reports no longer get consumed merely because they appear in pending/history/title/semantic state.
- Runtime labels mapped to v86.7 for the new gate path.

## Preserved

- v86.6 recursion fix.
- v86.6 media guard for images/embeds near source CTA paragraphs.
- v86.5 strict true-results report detector.
- v86.2 morning report hold.
- v86.6 cap for “possible return date” future speculation.

## Expected log change

Instead of:

```text
[SKIP v72.1] Gia pubblicata da pending in questa run: WWE NXT Results...
```

v86.7 should log:

```text
[REPORT v86.7] Pending true-results non pubblicato: resta lavorabile via candidate queue report:wwe-nxt-2026-05-12
[REPORT v86.7] Ignoro gate legacy title_key: true-results non confermato su WordPress report:wwe-nxt-2026-05-12
```
