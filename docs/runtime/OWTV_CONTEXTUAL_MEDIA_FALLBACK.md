# Contextual fallback for supported editorial media

Owner-approved 2026-10-25. News and reports keep the source paragraph associated
with its individual Instagram, Facebook, X, YouTube, TikTok, Threads and Bluesky
post. Profiles, sharing UI and source CTA remain excluded.

Local balanced markers preserve the linked span inside the existing full-paragraph
translation call. URLs remain deterministic metadata. Markers do not affect the
existing language validation; missing markers retain the entire translated prose
and supply a short contextual reference instead of failing or repairing translation.

Immediately before publishing, the authenticated WordPress oEmbed proxy supplies
eligibility, once per distinct supported permalink. Available media retains native
shortcodes/Gutenberg rendering. Missing/private media becomes a link in its original
paragraph; standalone media links attach to nearby prose without empty report media
containers. Captions remain text. Source scripts are never copied.

Provider token/permission errors and timeouts are temporary, not proof of privacy.
Process cache: available 1h, unavailable 10min, temporary 1min; WordPress retains its
own oEmbed cache. These statuses never enter editorial SKIP memory, duplicate rules
or frozen primary classes. Preview/missing configuration performs no network calls.

The change adds no Gemini calls or retries and keeps model routing unchanged.
Publisher results and immutable published traces retain per-article counts and
reason codes. Report review JSON retains the same diagnostics in its job metadata.
