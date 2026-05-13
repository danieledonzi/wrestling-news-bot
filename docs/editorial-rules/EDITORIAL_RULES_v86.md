# EDITORIAL_RULES v86

## Editorial principle

The bot must understand a story before deciding it is a duplicate.

A broad shared topic is not enough to skip an article. A duplicate skip requires the same core fact, same principal subject, and same narrative outcome.

---

## Duplicate policy

### Hard duplicate

Skip when one of these is true:

- same URL already in `history.txt`;
- same semantic ID already published;
- same stable story signature with same principal entities and outcome;
- WordPress confirms an already published equivalent;
- same report event key already published.

### Soft duplicate

Do not skip before editorial analysis when only one of these is true:

- same broad `news_core`;
- same generic business topic;
- same event family;
- same company mentioned but different speaker/angle.

A soft duplicate may be skipped later only after article type, event key and entities have been repaired.

---

## Opinion policy

Opinion/commentary remains capped as in v68/v70. A weak opinion can be skipped, but the skip reason must be editorial value, not a premature duplicate core.

Examples of weak opinion signals:

- `thinks`;
- `believes`;
- `explains why`;
- `podcast`;
- generic ex-wrestler commentary without new facts.

---

## Preview and post-show policy

The v68/v70 rules remain active:

- explicit previews remain `PREVIEW`;
- expired previews can be skipped early;
- post-show news with concrete outcomes can be published even if a full report exists;
- complete results/report articles remain `Editoriali`.

---

## Embed policy

Embeds are editorial content and must be handled by code, not invented by Gemini.

### Real embeds

Treat as embeds only when source HTML contains:

- iframe video/social embed;
- AMP social node;
- social blockquote;
- standalone URL paragraph;
- standalone embed wrapper.

### Inline social links

Inline X/Instagram/TikTok/Facebook links inside prose stay inline and must not be promoted to standalone embeds.

Example:

```html
<p>Ha risposto su <a href="https://x.com/...">X</a>.</p>
```

This remains text/link, not an oEmbed block.

### YouTube exception

YouTube links are the only inline links promoted to standalone embeds.

If a paragraph contains:

```html
<p>Ha parlato al <a href="https://youtube.com/watch?v=abc">podcast</a>.</p>
```

The final article should contain the translated paragraph followed immediately by:

```text
https://www.youtube.com/watch?v=abc
```

The video must not be moved to the end of the article.

---

## Embed validation

Before insertion, every embed URL must be:

- canonicalized;
- checked against supported domains;
- checked for a plausible content path;
- deduplicated;
- stripped of tracking parameters.

Invalid or implausible embed URLs are discarded or kept as ordinary links only when editorially safe.

---

## Translation and post-edit

The model receives text blocks and placeholders, not raw embed HTML. It must not create, move, invent, summarize, or delete embed placeholders.

Career/status guardrails from v80.9 remain active: retirement is `ritiro`, release is not `rilascio`, cleared is not `pulito`.
