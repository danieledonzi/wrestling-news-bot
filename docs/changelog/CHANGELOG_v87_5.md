# CHANGELOG v87.5

Hotfix from v87.4.

## Fixed

- Prevented post-publish crash after a successful WordPress publish caused by incompatible legacy/new signatures of `v872_mark_report_confirmed()`.
- The confirmed report history marker now accepts both legacy and new keyword names:
  - `url` and `source_url`
  - `post_id` and `wp_post_id`
- Preserved v87.4 mandatory artifact behavior:
  - `published/` artifact save
  - `logs/master_log_events.jsonl`
  - `logs/run_artifacts_latest.json`
- Kept strict confirmed report history: only canonical true-results report keys can be written.

## Notes

Live model listing confirms the usable Gemini 3 Flash model id is:

```text
gemini-3-flash-preview
```

This hotfix records the id as `V875_AVAILABLE_GEMINI_3_FLASH_MODEL`, but does not change model routing yet.
