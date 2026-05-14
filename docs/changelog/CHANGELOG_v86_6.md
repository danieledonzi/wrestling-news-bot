# Changelog v86.6

## Added

- `v866_direct_report_event_key()` to remove v86.5 recursion.
- Item-level feed exception isolation.
- Media guard for inline images and embeds extracted by the structured block engine.
- Future return/speculation scoring cap.
- Runtime label cleanup wrapper.

## Changed

- `v864_report_event_key()` and `v865_report_event_key()` now call the direct v86.6 report key builder.
- `build_candidates()` now keeps scanning a feed after a single item failure.
- `v61_strip_body_images_if_featured()` no longer removes structured editorial inline images.
- True results report handling remains strict and does not apply to ratings, rumors, backstage updates or single post-show news.

## Fixed

- Maximum recursion depth error in v86.5.
- Loss of inline image/embed near removed source CTA paragraphs.
- Over-scoring of “possible return date” future speculation items.
- Noisy legacy runtime labels in new runs.
