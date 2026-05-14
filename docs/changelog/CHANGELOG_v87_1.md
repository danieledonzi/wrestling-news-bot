# Changelog v87.1

## Fixed

- Extracts RingsideNews lazy Twitter/X embeds stored in `data-rsn-html`.
- Preserves social embed positions by converting lazy embed containers into standalone oEmbed URL blocks before block extraction.
- Restores reliable `published_html_review` output for newly published articles.
- Adds final outer review save hook with anti-duplicate guard.

## Kept from v87

- No `gemini-3.1-flash` standard in default chains.
- Tier3 opinion/interview below 55 blocked.
- Inline anchor sanitizer before publish.
