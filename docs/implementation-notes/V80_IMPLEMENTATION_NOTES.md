# OpenWrestlingTV Bot v80

## Focus

- Social embed safe pipeline: Twitter/X and compatible social embeds are rendered as canonical standalone URLs so WordPress can generate oEmbed automatically.
- Raw blockquote/script/iframe social embed code is not preserved and is not sent to Gemini.
- Post-edit protects oEmbed URLs with placeholders before Gemini and restores them afterward.
- Stronger wrestling localization prompt: less literal phrasing, more natural Italian editorial language, masculine "un promo", better handling of kayfabe/comedy/storyline idioms.

## Permanent embed rule

Do not send raw social embed HTML to Gemini. Extract the canonical post URL and publish it as a standalone paragraph.
