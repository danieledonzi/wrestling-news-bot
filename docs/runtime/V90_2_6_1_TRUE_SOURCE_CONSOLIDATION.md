# v90.2.6.1 true source consolidation

## Obiettivo

Portare `bot.py` a contenere fisicamente la chain consolidata fino a v90.2.5.4.1, eliminando la necessita di applicare patch runtime a ogni run.

## Strategia sicura

Il workflow esegue:

```text
python scripts/consolidate_source_v90_2_6_1.py
```

Lo script:

1. controlla se `bot.py` contiene gia tutti i marker richiesti;
2. se mancano, applica una sola volta la chain v90.2.6;
3. verifica `python -m py_compile bot.py`;
4. aggiunge il marker `v90.2.6.1 true source consolidation`;
5. il workflow committa `bot.py` consolidato se ci sono differenze.

## Comportamento atteso

Prima run dopo merge:

```text
[v90.2.6.1] bot.py non consolidato: applico patch chain una tantum
[SOURCE CONSOLIDATION v90.2.6.1] bot.py consolidato e compilabile
```

Dalla run successiva:

```text
[v90.2.6.1] bot.py gia consolidato: skip patch chain
```

## Cosa cambia rispetto a v90.2.6

v90.2.6 aveva solo accorpato la patch chain in un runner unico.

v90.2.6.1 rende il consolidamento persistente su `bot.py`.

## Cosa non cambia

- Nessuna modifica allo scoring.
- Nessuna modifica a processed_urls.
- Nessuna modifica a event_registry.
- Nessuna modifica a Gemini chain.
- Nessuna modifica editoriale intenzionale.

## Prossimo passo

Dopo una run positiva e dopo che `bot.py` risulta consolidato nel repository:

```text
v90.2.7_feed_level_processed_skip
```
