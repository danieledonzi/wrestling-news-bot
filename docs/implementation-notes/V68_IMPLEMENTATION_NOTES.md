# v68 Implementation Notes

Implemented in `bot_v68.py`.

## Obiettivo

Correggere la distinzione editoriale tra:

1. Preview di puntata/show.
2. Report completo della puntata/evento.
3. News autonoma su un fatto gia' accaduto durante la puntata/evento.

Il problema risolto e' che una news come `Lei Ying Lee Regains TNA Knockouts Title After Win Over Arianna Grace On Impact` non deve essere trattata come preview scaduta. E' una post-show news fresca.

## Nuove funzioni

- `normalize_article_type_v68()`
- `classify_article_type_fallback_v68()`
- `classify_article_type_with_gemini_v68()`
- `v68_is_expired_preview_only()`
- `v68_is_post_show_news()`
- `v68_score_cap()`

## Pipeline aggiornata

```text
feed title/summary -> article type hint -> scoring -> scrape -> article type Gemini/fallback -> freshness semantica -> refined scoring -> dedupe -> categoria Gemini -> traduzione -> publish
```

## Freshness

Prima:

```text
show gia' andato in onda + parole show/preview => skip
```

Ora:

```text
PREVIEW scaduta => skip
RESULTS_REPORT => coda report/editoriali
POST_SHOW_NEWS => pubblicabile se fresca e non duplicata
```

## Report

I report completi restano:

```python
REPORT_CATEGORY_ID = int(os.getenv("WP_EDITORIALI_CATEGORY_ID", "13"))
```

Il workflow mantiene:

```yaml
WP_EDITORIALI_CATEGORY_ID: 13
```

## Opinion cap

La v68 applica davvero `v66_score_cap()` dentro `calculate_importance_score()` e aggiunge `v68_score_cap()`.

Cap principali:

- Opinion/commentary duro senza news concreta: max 54.
- Opinion generica senza news concreta: max 68.
- Annunci vaghi tipo “will shock the foundation” senza dettaglio concreto: max 72.
- Post-show news concreta con cambio titolo/risultato: floor 55.
