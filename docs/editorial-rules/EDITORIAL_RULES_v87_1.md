# Editorial Rules v87.1

No editorial scoring changes from v87.

## Media rule

If an original article contains a social embed, including RingsideNews lazy embeds, the bot should preserve it as an oEmbed block in the original position.

The bot should not copy raw third-party iframe HTML. It should extract the canonical social URL and let WordPress render the embed.

## Review archive rule

Every successfully published article should produce `published_html_review` files whenever source or final HTML is available.
