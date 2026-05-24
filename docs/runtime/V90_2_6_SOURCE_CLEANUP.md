# v90.2.6 source cleanup

## Obiettivo

Ridurre la fragilita del workflow senza cancellare prematuramente gli script storici di patch.

La v90.2.6 sostituisce la lunga lista YAML di patch runtime con un unico runner controllato:

```text
scripts/apply_runtime_chain_v90_2_6.py
```

## Perche non cancellare subito gli script patch

`bot.py` su main non contiene ancora fisicamente tutti i marker v90.2.x prima dell'applicazione runtime. Cancellare gli script patch in questa fase romperebbe la run.

Questa release quindi e una fase intermedia sicura:

1. la catena resta identica come effetto runtime;
2. il workflow diventa piu leggibile;
3. la verifica source resta attiva;
4. gli script storici restano disponibili per audit e rollback.

## Cosa cambia

Prima:

```yaml
python scripts/apply_bot_patch_v90_1.py
python scripts/apply_bot_patch_v90_1_review_fix.py
...
python scripts/apply_bot_patch_v90_2_5_4_1.py
```

Dopo:

```yaml
python scripts/apply_runtime_chain_v90_2_6.py
```

Il runner applica la stessa lista ordinata e verifica i marker attesi.

## Cosa non cambia

- Nessuna modifica allo scoring.
- Nessuna modifica al processed URL model.
- Nessuna modifica alla event registry.
- Nessuna modifica al comportamento editoriale.
- Nessuna eliminazione degli script storici.

## Prossimo passo

Dopo una run positiva:

```text
v90.2.7_feed_level_processed_skip
```

Obiettivo: controllare `processed_urls.json` subito dopo la lettura del feed, prima dello scoring e prima di qualunque chiamata Gemini.
