# Scoring System v68

La v68 mantiene la base v66/v67 ma corregge due punti.

## 1. Freshness semantica

Lo scoring non usa piu' `v62_is_expired_preview()` come blocco grezzo.

Ora viene prima classificato il tipo articolo:

```text
PREVIEW / RESULTS_REPORT / POST_SHOW_NEWS / OPINION / RUMOR / OTHER
```

Solo `PREVIEW` puo' essere abbassata o bloccata per show gia' andato in onda.

## 2. Cap opinion applicato davvero

Dentro `calculate_importance_score()` ora vengono applicati:

```python
v66_score_cap(...)
v68_score_cap(...)
```

Cap v68:

- Opinion/commentary duro senza fatto concreto: massimo 54.
- Opinion generica senza fatto concreto: massimo 68.
- Annuncio vago/futuro senza dettaglio concreto: massimo 72.
- Post-show news concreta: floor 55.

## Esempi attesi

- `Lei Ying Lee Regains TNA Knockouts Title After Win Over Arianna Grace On Impact` -> POST_SHOW_NEWS, non preview scaduta.
- `TNA Impact preview for tonight` -> PREVIEW, bloccabile dopo la puntata.
- `TNA Impact results 5/7/2026` -> RESULTS_REPORT, Editoriali ID 13.
- `Bully Ray Lays Out Options For John Cena's Announcement` -> OPINION, cap duro.
