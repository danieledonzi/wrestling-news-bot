# IMPLEMENTATION_NOTES v86

## Version name

`v86_structured_pipeline_embed_engine`

## Goal

v86 is a structural cleanup release. It keeps the performance gains introduced in v85.4/v85.5, but removes the most dangerous regression: treating broad `news_core` or `event_key` matches as hard duplicate skips before the bot has understood the article context.

The release also introduces a hard Embed Engine with explicit rules for extraction, validation, canonicalization and positional reinsertion.

---

## Files changed

- `bot.py`
- `cron.yml`

In this package they are provided as:

- `bot_v86.py`
- `cron_v86.yml`

---

## Pipeline target

```text
RSS feed
  -> URL/history/skipped_history prefilter
  -> local low-value/expired-preview prefilter
  -> initial scoring/type hint
  -> scraping
  -> ordered block extraction
  -> lightweight editorial analysis / existing v72.3 analysis
  -> repaired article_type/category/event_key
  -> semantic dedupe / WP dedupe
  -> refined scoring
  -> structured translation
  -> controlled post-edit
  -> deterministic guardrails
  -> final validation
  -> draft-first publish
  -> history + published HTML review
```

The rule is:

```text
Understand the story before declaring it a duplicate.
```

---

## Main implementation points

### 1. Pre-Gemini duplicate gates are no longer hard skips

v85.5 added fast pre-Gemini gates for `news_core` and `event_key`. This saved model calls but could skip valid contextual follow-ups before Gemini/editorial analysis repaired the event key.

v86 overrides:

- `v851_early_news_core_key()`
- `v855_low_value_pre_gemini_reason()`

The new behavior keeps hard pre-Gemini skips only for:

- URL already in `history.txt`;
- valid `skipped_history.json` record;
- expired hard previews;
- obsolete pre-show spoilers;
- clearly low-value items below the configured cutoff.

`news_core` and `event_key` history matches are no longer hard skips before AI context.

### 2. Shorter TTL for soft/contextual skips

`v854_skip_ttl_for_reason()` is overridden so soft duplicate/opinion/business-core records do not suppress evolving stories for too long:

- generic business-core soft skip: 6h;
- soft duplicate: 12h;
- low-value opinion: 24h;
- true hard duplicates keep the old behavior.

### 3. Hard Embed Engine

The new hard embed layer owns embed extraction and placement before Gemini translation.

New helpers include:

- `v86_youtube_video_id()`
- `v86_canonical_youtube_url()`
- `v86_canonical_embed_url()`
- `v86_is_plausible_embed_url()`
- `v86_raw_embed_urls_from_node()`
- `v86_youtube_inline_urls_from_node()`
- `v86_standalone_embed_urls_from_node()`

### 4. YouTube exception

YouTube is the only provider promoted from inline hyperlink to standalone embed.

Supported YouTube shapes:

- `youtube.com/watch?v=...`
- `youtu.be/...`
- `youtube.com/live/...`
- `youtube.com/shorts/...`
- `youtube.com/embed/...`

All are canonicalized to:

```text
https://www.youtube.com/watch?v=<video_id>
```

The video embed is inserted immediately after the original paragraph/list item.

### 5. Other social links stay inline unless they are real embeds

Inline links to X/Twitter, Instagram, TikTok or Facebook inside normal prose are not promoted to oEmbed blocks.

They become embeds only if they are:

- raw iframe/embed nodes;
- `blockquote` social embeds;
- AMP social embeds;
- standalone/pure embed wrapper links.

### 6. Final oEmbed normalization is conservative

`v80_normalize_oembed_urls_in_html()` is overridden so it does not promote inline X/Instagram/TikTok/Facebook anchors to embed blocks. It normalizes standalone URL paragraphs and YouTube anchors only.

### 7. Clean v86 runtime diagnostics

The v85.4 boot wrapper printed `[BOOT v85.4]` even in later versions. v86 routes the runtime through the raw bot entrypoint saved by v85.4 and prints:

```text
[BOOT v86] __main__ reached ...
[BOOT v86] entro in run_bot ...
```

---

## Environment variables

```yaml
V86_CONTEXTUAL_DEDUPE_ENABLED: "1"
V86_HARD_EMBED_ENGINE_ENABLED: "1"
V86_YOUTUBE_INLINE_AS_EMBED: "1"
V86_DISABLE_PRE_GEMINI_CORE_HISTORY_HARD_SKIP: "1"
V86_DISABLE_V851_EARLY_CORE_HARD_SKIP: "1"
```

Existing v85 variables remain valid.

---

## Expected behavior on the v85.5 regression case

A candidate like:

```text
WWE HOFer Eric Bischoff Thinks Triple H Deserves A Raise
```

must not be skipped before Gemini/editorial analysis just because an early core looks like:

```text
business-tko-wrestlemania
```

It may still be skipped later as low-value opinion, duplicate, or below the editorial threshold, but the reason must be editorially accurate, not a premature broad-core duplicate.

---

## Non-regression requirements

v86 must preserve:

- skipped history performance from v85.4;
- report pre-scraping skip from v85.5;
- draft-first publishing from v85;
- published-only HTML review archive;
- v68/v70 preview vs post-show distinction;
- v80.3 spoiler guardrails;
- v80.9 career/status translation guardrails.
