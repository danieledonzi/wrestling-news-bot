# v80.8 Implementation Notes

## Obiettivo

Rendere effettiva la fix v80.7 evitando confusione di versione e ordine di esecuzione.

## Problema rilevato

In `bot_v80_7.py` l'entrypoint del bot era ancora prima del blocco v80.7. Di conseguenza la run partiva con:

```text
VERSION [v80_6_natural_italian_style_prompt (...)]
```

Gli override v80.7 venivano definiti solo dopo l'esecuzione di `run_bot()`, quindi non potevano incidere sul dedupe.

## Correzione

In `bot_v80_8.py`:

1. il blocco v80.7/v80.8 viene definito prima dell'avvio;
2. `BOT_VERSION` diventa `v80_8_followup_dedupe_startup_fix`;
3. l'unico `if __name__ == "__main__"` si trova in fondo al file.

## Verifica attesa

La prossima run deve mostrare:

```text
VERSION [v80_8_followup_dedupe_startup_fix (...)]
```

Per i casi Asuka:

- `Backstage Reaction...` non deve essere bloccato come semplice `run_stable_duplicate_v7915`;
- se un layer precedente lo segnala duplicato, deve essere convertito in `followup_advancement_not_duplicate_v807`.
