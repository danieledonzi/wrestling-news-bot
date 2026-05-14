# Implementation Notes v87.2

## Files

- `bot_v87_2.py`
- `cron_v87_2.yml`

## Patches applied

### Task model routing

A `v872_model_task` stack wraps Gemini calls. `generate_and_parse_json()` now routes by current task instead of relying only on the old v83 context router.

Wrapped tasks:

- `check_gemini()` -> `healthcheck`
- `v72_editorial_analysis()` -> `editorial_analysis`
- `translate_ordered_content_blocks()` -> `translate_normal`, `translate_medium`, or `translate_report`
- `translate_news()` -> same translation tiers
- `v79_editorial_post_edit()` -> `postedit`
- `v82_repair_ai_smell_microtexts()` -> `repair`
- `v82_repair_title_editorial()` and `v721_ensure_italian_title()` -> `title`

A 503 marks the model in global cooldown for the rest of the run by default (`V872_MODEL_COOLDOWN_SECONDS=3600`).

### Confirmed report history

New JSON file:

```text
confirmed_published_reports.json
```

Shape:

```json
{
  "confirmed_published_report_keys": ["report:wwe-nxt-2026-05-12"],
  "published_reports": {
    "report:wwe-nxt-2026-05-12": {
      "report_key": "report:wwe-nxt-2026-05-12",
      "title": "...",
      "source_url": "...",
      "wp_post_id": 1234,
      "confirmed_at": "2026-05-13T00:00:00Z",
      "reason": "publish_success"
    }
  }
}
```

This store is written only after strict WP confirmation or publish success.

### Embed dedupe

New functions:

- `v872_canonical_embed_url()`
- `v872_embed_key()`
- `v872_remove_duplicate_embed_urls_from_html()`

They normalize:

- `twitter.com`, `mobile.twitter.com`, `x.com?...` -> `https://x.com/user/status/id`
- `youtu.be`, `/embed/`, `youtube.com/watch?...` -> `https://www.youtube.com/watch?v=id`

### Published review dedupe

`save_published_html_review_item()` is wrapped with an in-run stable key to avoid duplicate review files caused by legacy + outer hooks firing together.

## Recommended log checks

Expected model logs:

```text
[MODEL v87.2] task=editorial_analysis chain=...
[MODEL v87.2] task=translate_medium chain=...
[MODEL v87.2] task=title chain=...
```

Expected embed logs:

```text
[EMBED v87.2] Canonicalizzati/deduplicati embed nel body: N
```

Expected report logs:

```text
[REPORT v87.2] Report confermato in history forte: report:...
[REPORT v87.2] True-results confermato da history forte: skip offline-safe report:...
```
