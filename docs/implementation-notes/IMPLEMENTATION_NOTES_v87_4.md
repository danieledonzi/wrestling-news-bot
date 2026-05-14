# Implementation Notes v87.4

## Obiettivo
La v87.4 non introduce nuove logiche editoriali. Ripristina gli artifact locali e il master log, diventati regressione bloccante.

## Funzioni principali

### `v874_save_published_artifacts(...)`
Wrapper obbligatorio post-publish. Riceve il payload dell'articolo, il `wp_post_id`, URL sorgente, `semantic_id`, `event_key`, embed, immagini e featured image.

Scrive:

- `published/<timestamp>_<idx>_<slug>_<post_id>_final.html`
- `published/<timestamp>_<idx>_<slug>_<post_id>_metadata.json`
- `published/<timestamp>_<idx>_<slug>_<post_id>_source.txt`

### `v874_append_master_event(...)`
Append JSONL su:

```text
logs/master_log_events.jsonl
```

Ogni riga contiene `run_id`, `bot_version`, `post_id`, titolo, source URL, semantic ID, event key e path artifact.

### `v874_finalize_run_artifacts()`
Scrive:

```text
logs/run_artifacts_latest.json
```

e stampa il riepilogo:

```text
[RUN ARTIFACTS v87.4] master_log=ok published=N errors=M status=...
```

## Regola tassativa
Un publish WordPress riuscito senza artifact locale non deve passare inosservato. Il bot non elimina il post già pubblicato, ma deve dichiarare la run incompleta.

## Report history
`v872_mark_report_confirmed` è stato ristretto: `confirmed_published_reports` accetta solo report veri, con chiave canonica e contenuto/titolo da results/highlights/key moments.
