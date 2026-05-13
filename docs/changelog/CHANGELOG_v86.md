# CHANGELOG v86 - Structured pipeline and hard embed engine

## Added

- New version name: `v86_structured_pipeline_embed_engine`.
- Contextual pre-Gemini dedupe policy:
  - broad `news_core` matches are no longer hard skips before editorial analysis;
  - broad `event_key` matches are no longer hard skips before editorial analysis;
  - expired previews and obsolete pre-show spoilers still skip early.
- Hard Embed Engine:
  - validates all embed URLs before insertion;
  - canonicalizes supported YouTube URLs;
  - preserves original embed positions;
  - deduplicates embeds by canonical identity;
  - rejects implausible/tracking/noisy embed URLs.
- YouTube inline exception:
  - YouTube links inside normal hyperlinks are extracted;
  - the video is inserted immediately after the original paragraph;
  - canonical form is `https://www.youtube.com/watch?v=<video_id>`.
- Conservative social embed policy:
  - inline X/Instagram/TikTok/Facebook links stay inline;
  - only true raw/standalone social embeds become oEmbed blocks.
- v86 runtime boot diagnostics:
  - `[BOOT v86] __main__ reached ...`
  - `[BOOT v86] entro in run_bot ...`
- New workflow environment variables for v86 gates.

## Changed

- `v851_early_news_core_key()` now returns no early core by default to prevent hard pre-Gemini core suppression.
- `v855_low_value_pre_gemini_reason()` no longer hard-skips `news_core_history_pre_gemini` or `event_history_pre_gemini` when v86 contextual dedupe is enabled.
- `v854_skip_ttl_for_reason()` uses shorter TTLs for soft/opinion/contextual skip classes.
- `build_ordered_content_blocks()` now owns strict embed placement, including inline YouTube extraction after text blocks.
- `_node_social_embed_urls()` is strict again and no longer promotes all social/video anchors.
- `v80_normalize_oembed_urls_in_html()` no longer converts inline X/TikTok/Instagram/Facebook anchors into standalone embed paragraphs.

## Fixed

- False duplicate suppression caused by broad business cores such as `business-tko-wrestlemania`.
- False early event-history skips caused by event keys repaired only after Gemini/editorial analysis.
- Regression from v84 where ordinary inline social links could be promoted to embed blocks.
- Version diagnostic confusion caused by v85.4 boot labels appearing in later runtime logs.

## Preserved

- v85.4 `skipped_history.json` performance behavior.
- v85.5 report pending pre-scraping skip.
- v85 draft-first publishing.
- Published HTML review archive.
- v80.9 career/status translation guardrails.
