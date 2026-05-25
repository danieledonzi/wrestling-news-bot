# v90.2.8 feed-level processed URL hard skip

## Obiettivo

Evitare che URL gia lavorati in modo finale vengano analizzati ancora nelle run successive.

Il controllo deve avvenire il prima possibile, subito dopo la lettura del feed, prima di:

```text
story signature
core assignment
scoring
scraping
Gemini
pending
```

## Problema osservato

Articoli vecchi come:

```text
WWE Announces Major Change To Becky Lynch/Sol Ruca SNME Match
```

continuavano a entrare nello scoring anche se erano gia stati scartati/lavorati.

## Implementazione

La patch:

```text
scripts/apply_bot_patch_v90_2_8.py
```

installa un wrapper su:

```python
feedparser.parse
```

Dopo il parsing del feed, filtra `parsed.entries` rimuovendo gli URL che risultano finali in `processed_urls.json`.

Sono considerati finali:

```text
published
skipped_duplicate
skipped_existing_wp
skipped_existing_history
skipped_editorial_exclude
skipped_soft_trash
skipped_stale
low_score_final
skipped_below_threshold / rejected con score basso finale
```

## Compatibilita workflow

Per evitare modifiche rischiose al workflow, `scripts/apply_bot_patch_v90_2_7.py` diventa un delegatore che applica:

```text
scripts/apply_bot_patch_v90_2_7_2.py
scripts/apply_bot_patch_v90_2_8.py
```

Il workflow corrente chiama gia `apply_bot_patch_v90_2_7.py`, quindi la patch viene caricata senza cambiare `cron.yml`.

## Non obiettivi

Questa fix non cambia lo scoring.

La revisione dello scoring sara la fase successiva.
