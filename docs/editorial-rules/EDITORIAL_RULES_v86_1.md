# EDITORIAL_RULES v86.1

## Report/results rule

A report/results article must not be suppressed only because its `report_event_key` exists in local history. The bot must verify WordPress.

- If WordPress confirms the report exists: skip.
- If WordPress does not confirm the report: publish/recover it.

## Post-show outcome rule

A title containing a concrete post-show action is not a preview, even if it mentions a show date.

Examples:

- `Naraku Makes WWE In-Ring Debut During 5/12 NXT` -> post-show news, not expired preview.
- `WWE NXT Preview for May 12` -> preview, can expire.

## AAA priority rule

AAA priority requires a hard AAA anchor in title or URL, such as `AAA`, `TripleMania`, `AAA Mega Championship`, `El Grande Americano`, or `Los Americanos`.

A body-only mention of AAA/TripleMania is not enough to activate major priority.

## Duplicate rule

Story signatures must represent the actual subject and action of the story. Title entities are stronger than body-only entities. Broad body context must not pollute the dedupe key.

## Validation rule

Meta/source-promo sentences should be removed before final body validation. A candidate should fail only if the cleaned body is still too short, too meta, or structurally invalid.
