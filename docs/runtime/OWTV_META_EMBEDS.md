# Instagram and Facebook media

Meta Embeds must be active on WordPress. The bot emits native `[embed]` shortcodes;
WordPress and Meta supply the actual embed HTML and frontend SDK, never source scripts.

News and ordered reports preserve links to individual Meta posts as media immediately
after their source paragraph, retaining the full prose. Profiles, share buttons, CTA and
unresolved short redirect links are not promoted. Existing embed containers and Facebook
plugin wrappers resolve only to allowlisted post permalinks. Required Facebook query IDs
and case-sensitive Instagram shortcodes are preserved; tracking parameters are removed.

Publisher canonicalizes existing Meta shortcodes, Gutenberg embeds, standalone URL/anchor
paragraphs and editorial inline links. Reprocessing must be idempotent and retain a single
media occurrence in document order. YouTube and X keep their established rendering paths.

Meta eligibility is authoritative: private, deleted or embedding-disabled media cannot be
made public by this change. WordPress retains its link fallback when oEmbed is unavailable.
No extra Gemini calls, model, editorial policy, duplicate decision or primary class changes.
