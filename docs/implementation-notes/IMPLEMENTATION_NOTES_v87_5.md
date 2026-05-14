# IMPLEMENTATION NOTES v87.5

## Problem

v87.4 correctly saved the local published artifact and master log after WordPress publish, but then crashed during post-publish report-history marking:

```text
TypeError: v872_mark_report_confirmed() got an unexpected keyword argument 'url'
```

The crash happened because different wrapper layers used different parameter names for the same concept.

## Fix

`v872_mark_report_confirmed()` is now a tolerant compatibility wrapper accepting:

```python
url="..."
source_url="..."
post_id=123
wp_post_id=123
**kwargs
```

It normalizes these values internally and calls the available underlying implementation using a safe fallback cascade.

## Strict report history

The function still refuses to write strong report history unless the key is a canonical true-results report, for example:

```text
report:aew-dynamite-2026-05-13
```

Regular news items must not enter `confirmed_published_reports`.

## Model note

The live SDK list shows the correct Gemini 3 Flash id is:

```text
gemini-3-flash-preview
```

No routing change was made in this hotfix.
