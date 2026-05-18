# CHANGELOG v89.2 - Source consolidation

## Summary

v89.2 e' una release di pulizia prima della v90.

L'obiettivo e' consolidare nel source runtime il comportamento ormai stabile fino a v89.1 e semplificare il workflow GitHub Actions, evitando di applicare a ogni run la catena storica di patch `v88.1 -> v89.1`.

## Cosa cambia

- Il workflow non esegue piu' gli step runtime:
  - `Apply v88_1 source patch to bot.py`
  - `Apply v88_2 editorial performance patch to bot.py`
- Aggiunge uno step leggero `Verify consolidated source` che:
  - compila `bot.py`;
  - verifica la presenza dei marker consolidati fino a v89.1.
- Aggiorna i label/log del workflow da v88.2 a v89.2.
- Mantiene lo step `Print runner public IP`, utile per diagnosi Imunify/hosting.
- Mantiene invariata la persistenza artifact/log.

## Cosa non cambia

- Non cambia feed.
- Non cambia scoring editoriale.
- Non cambia model routing Gemini.
- Non cambia WordPress/API.
- Non introduce la daily volume guard: quella resta prevista per v90.

## Motivazione

La chain di patch applicata a ogni run era diventata lunga e difficile da leggere:

```text
v88.1
v88.2
v88.3
v88.3.1
v88.4
v88.4.1
v88.4.2
v88.4.2.1
v89
v89.1
```

Dopo la stabilizzazione di v89/v89.1, e prima di introdurre la logica giornaliera v90, conviene rendere il workflow piu' semplice e meno fragile.

## Expected logs

```text
[SOURCE CONSOLIDATION v89.2] bot.py contiene gia la chain consolidata fino a v89.1
[NET] GitHub Actions public IP:
[BOOT v89.1] Legacy return/debut rumor guard attiva
```

## Nota

Gli script storici `scripts/apply_bot_patch_*` restano nel repository come archivio tecnico e per eventuale audit, ma non vengono piu' chiamati dal workflow principale.
