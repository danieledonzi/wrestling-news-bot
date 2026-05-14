# Implementation Notes v87.1

## Lazy embed extraction

RingsideNews often stores social embeds as lazy containers rather than direct `blockquote.twitter-tweet` nodes:

```html
<div class="rsn-lazy-embed rsn-lazy-embed--twitter" data-rsn-html="BASE64_HTML"></div>
```

v87.1 adds:

- `v871_decode_possible_base64()`
- `v871_extract_urls_from_rsn_lazy_html()`
- `v871_extract_rsn_lazy_embed_urls()`
- `v871_preprocess_rsn_lazy_embeds_in_html()`

The preprocessor replaces those containers with standalone `<p>URL</p>` blocks so the existing v86/v87 oEmbed flow can preserve original placement.

## Published review archive

The legacy review saver was no longer reliable because multiple later `process_candidate_item()` wrappers could bypass the old v80/v81 save hook.

v87.1 adds an outermost wrapper that:

1. calls the full underlying publish pipeline;
2. if status is `published`, checks whether review has already been saved;
3. fills missing final HTML/title from the final WordPress payload tracked in `create_post_without_image()`;
4. calls `save_published_html_review_item()` once.

## Feature flags

- `V871_RSN_LAZY_EMBED_ENABLED=1`
- `V871_OUTER_REVIEW_SAVE_ENABLED=1`
