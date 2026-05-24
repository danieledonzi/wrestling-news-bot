# v90.2.6.2 clean boot/version

## Obiettivo

Dopo la v90.2.6.1, `bot.py` e' consolidato ma contiene ancora molti `print()` storici di boot derivati dalle patch integrate nel source.

La v90.2.6.2 pulisce il log di avvio senza modificare la logica editoriale.

## Cosa fa

Aggiunge:

```text
scripts/cleanup_boot_version_v90_2_6_2.py
```

Lo script:

1. commenta i vecchi `print()` di boot storici v88/v89/v90.1/v90.2;
2. imposta `BOT_VERSION` finale a `v90_2_6_2_clean_consolidated_source`;
3. aggiunge un solo boot sintetico:

```text
[BOOT v90.2.6.2] Source consolidato attivo: chain fino a v90.2.5.4.1
```

## Cosa non cambia

- Nessuna modifica allo scoring.
- Nessuna modifica a processed_urls.
- Nessuna modifica a event_registry.
- Nessuna modifica al report flow.
- Nessuna modifica alla Gemini chain.

## Comportamento atteso

Prima run dopo merge:

```text
[v90.2.6.2] bot.py aggiornato: boot storici silenziati e versione finale impostata
[SOURCE CONSOLIDATION v90.2.6.2] bot.py contiene source consolidato e boot pulito
```

Dalle run successive:

```text
[v90.2.6.2] bot.py gia pulito nel repository
[BOOT v90.2.6.2] Source consolidato attivo: chain fino a v90.2.5.4.1
===== RUN START [...] VERSION [v90_2_6_2_clean_consolidated_source (...)] =====
```
