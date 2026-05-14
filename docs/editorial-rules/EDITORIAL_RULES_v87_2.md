# Editorial Rules v87.2

## Embed rules

- YouTube links embedded in hyperlinks or text must become one standalone oEmbed URL in the original position.
- The original inline YouTube link/text must be removed if the embed already exists.
- X/Twitter links must always be rendered as:

```text
https://x.com/<user>/status/<id>
```

- Never output `twitter.com` in the final body.
- Never keep query params on X/Twitter status URLs.
- Each canonical embed key can appear once only.
- Do not append embeds blindly at the bottom if a reliable original position exists.

## Opinion/interview tier rules

- Tier3 opinion/interview/commentary pieces below 55 stay blocked.
- A post-AI score under 55 for opinion/commentary should not be rescued unless there is a concrete new fact.

## Report rules

- True-results reports remain a special class.
- Generic history does not prove a report was published.
- `confirmed_published_reports.json` does prove it.
- Confirmed true-results reports can be skipped even if WordPress is temporarily offline.

## CTA rules

- Source CTAs such as “Leave your thoughts and feedback below” remain removed.
- Media immediately before a CTA must be preserved unless it is a duplicate embed/image.
