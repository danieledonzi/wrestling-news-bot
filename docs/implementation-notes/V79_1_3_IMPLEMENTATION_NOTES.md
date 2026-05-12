# v79.1.3 Implementation Notes

Implemented in `bot_v79_1_3.py`.

## Nuove funzioni/override

- `v7913_ai_reason_says_not_preview()`
- `v7913_title_text_is_live_announcement()`
- `v7913_is_ai_post_show()`
- `v7913_is_true_future_preview()`
- override di `v72_editorial_analysis()`
- override di `v68_is_expired_preview_only()`
- override di `calculate_importance_score()`
- override di `v723_conservative_score_after_ai()`
- override di `v723_repair_event_key_after_ai()`

## Regola centrale

Il deterministico resta guardrail, ma non deve contraddire un verdetto AI gia' coerente:

```text
AI POST_SHOW_NEWS / RESULTS_REPORT => no preview scaduta
AI reason: "non e' una preview" => no PREVIEW
spoiler validato => floor finale dopo i cap legacy
```

## Nota prudenziale

Le vere preview future restano cappate. La patch non trasforma preview generiche in pubblicazioni: interviene solo quando c'e' coerenza post-show/live o spoiler gia' validato dal layer ibrido.
