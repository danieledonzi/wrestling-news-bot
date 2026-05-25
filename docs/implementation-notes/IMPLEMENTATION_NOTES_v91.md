# IMPLEMENTATION_NOTES v91

## Versione

`v91_editorial_pipeline_refactor`

## Obiettivo

La v91 introduce un layer editoriale autoritativo per interrompere la catena di patch/cap legacy che poteva contraddirsi dopo l'analisi della notizia.

Il principio guida e':

```text
hard skip URL -> cheap classifier -> editorial analysis -> core -> score_story_v91 -> lane -> traduzione solo se pubblicabile
```

## Problemi risolti

1. URL gia' lavorati potevano entrare ancora nello scoring.
2. News evento autonome potevano essere abbassate da vecchi cap `OTHER/feature`.
3. `event_key` generici potevano bloccare news autonome dello stesso evento.
4. Gemini/traduzione rischiavano di essere usati su articoli non pubblicabili.
5. Le decisioni post-AI potevano essere sovrascritte da cap legacy.

## Nuove funzioni

- `cheap_classifier_v91()`
- `editorial_analysis_v91()`
- `assign_story_core_v91()`
- `score_story_v91()`
- `decide_lane_v91()`
- `v91_apply_item_fields()`
- cache `article_analysis_cache_v91.json`

## Flusso v91

1. Controllo URL gia' finale in `processed_urls.json`.
2. Cheap classifier deterministico su titolo/URL/summary.
3. Skip finale senza Gemini per trash/previews/listing evidenti.
4. Editorial analysis strutturata solo per candidati plausibili.
5. Core assignment centralizzato, riusando il layer v90.2.7 quando disponibile.
6. Scoring v91 unico e autoritativo.
7. Decisione lane:
   - `publish_now`
   - `publish_candidate`
   - `strategic_pool`
   - `soft_pool`
   - `skip_final`
8. Le vecchie logiche possono ancora eseguire la pubblicazione/traduzione, ma non devono piu' abbassare score/core/lane quando v91 e' autoritativa.

## Gemini e costi

La v91 separa analisi editoriale e traduzione.

- Nessuna chiamata Gemini per URL gia' lavorati.
- Nessuna chiamata Gemini per hard skip deterministici.
- Una sola analisi editoriale per candidato plausibile.
- Analisi salvata in `article_analysis_cache_v91.json`.
- Traduzione solo quando la lane consente pubblicazione.

## Compatibilita'

La patch viene caricata dal runner gia' esistente:

```text
scripts/apply_bot_patch_v90_2_7.py
```

che ora applica:

```text
scripts/apply_bot_patch_v90_2_7_2.py
scripts/apply_bot_patch_v90_2_8.py
scripts/apply_bot_patch_v91.py
```

## Flag

```text
V91_ENABLED=1
V91_ANALYSIS_CACHE_FILE=article_analysis_cache_v91.json
V91_MIN_AI_CHEAP_SCORE=45
V91_MIN_PUBLISH_SCORE=75
V91_STRATEGIC_POOL_SCORE=68
V91_SOFT_POOL_SCORE=55
V91_SKIP_FINAL_SCORE=54
```
