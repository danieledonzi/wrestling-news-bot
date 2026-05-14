# Implementation Notes v86.6

## Fixed recursion

v86.5 accidentally created this loop:

```python
v865_report_event_key -> v864_report_event_key -> v865_report_event_key
```

v86.6 replaces both wrappers with `v866_direct_report_event_key()`, which calls `make_report_event_key()` directly and only after `v865_is_true_results_report()` returns true.

## Isolated item errors

`build_candidates()` now isolates exceptions per feed entry. A bad item logs:

```text
[BOT v86.6] Errore item feed isolato: ...
```

and the feed continues.

## True results gate remains strict

Only titles/URLs with real results markers, show anchors and date markers use report bypass behavior.

Excluded examples remain:

- Viewership & Ratings Report
- Backstage Update
- First Wrestling Appearance
- After WWE Release
- AEW Talent Already Pushing

## Future return/speculation cap

Articles framed as possible return dates or advertised future appearances are capped at `V86_6_FUTURE_SPEC_SCORE_CAP`, default `72`.

The cap is applied both in initial scoring and after AI editorial analysis.

## Media preservation

`v61_strip_body_images_if_featured()` is overridden to preserve `figure.owtv-inline-image` blocks.

`translate_ordered_content_blocks()` records expected image/embed URLs.

`create_post_without_image()` checks the final body before publish and reinserts missing expected media when possible.

## Diagnostics

A lightweight print wrapper rewrites stale runtime labels such as `[BOOT v86.1]`, `[BOOT v85.4]`, `[SKIP v85.4]` and `[RUN v85]` into v86.6-compatible labels for readability.
