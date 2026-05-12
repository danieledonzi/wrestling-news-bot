# CHANGELOG v79.1.1

## v79_1_1_spoiler_cache_preshow_validation

Patch mirata sulla v79.1 dopo la run del 2026-05-09.

### Problemi osservati

- Il layer spoiler chiamava Gemini piu' volte per lo stesso articolo nella stessa run.
- Alcuni spoiler pre-show concreti, come `Match Order Revealed` o `Opening Match Revealed`, ricevevano `Gemini SPOILER` ma venivano bloccati dalla hard validation per assenza di termini come `revealed`, `match order`, `opening match`.
- Un titolo esplicitamente spoiler poteva essere neutralizzato dalla hard auto-no se il body conteneva parole da preview/card.

### Modifiche

- Aggiunta cache per decisione spoiler per articolo/run: `V791_SPOILER_DECISION_CACHE`.
- Aggiunta chiave cache: `v791_spoiler_cache_key()`.
- Estesa hard validation con segnali pre-show concreti:
  - `revealed`
  - `lineup`
  - `spoiler lineup`
  - `match order`
  - `opening match`
  - `opener`
  - `backstage notes`
- Aggiunta lista `V791_PRESHOW_SPOILER_TERMS`.
- Modificata `v791_is_auto_no_spoiler()` per non bloccare titoli esplicitamente spoiler/pre-show solo perche' nel testo compaiono parole come card/full card/preview.
- Aggiornati i log a `[SPOILER v79.1.1]` nei percorsi decisionali cache-aware.

### Filosofia mantenuta

La logica resta ibrida:

1. hard rules prima dell'AI;
2. Gemini come classificatore semantico;
3. hard validation obbligatoria dopo Gemini.

Gemini non ha potere assoluto: se dice `SPOILER` ma non esiste un segnale concreto, il prefisso non viene applicato.
