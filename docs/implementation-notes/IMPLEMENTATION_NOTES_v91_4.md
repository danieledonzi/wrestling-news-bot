# IMPLEMENTATION_NOTES v91.4

## Versione

`v91_4_publish_processed_softpool_repair`

## Obiettivo

v91.4 e' una patch tecnica conservativa. Non modifica scoring, soglie editoriali, feed, categorie o prompt di traduzione.

Risolve tre problemi emersi dal master log del 25 maggio 2026:

1. WordPress pubblicava correttamente, ma `processed_urls.json` non marcava l'URL come `published`.
2. `soft_pool.json` conteneva core legacy generici, in particolare `title:darby-allin:status`, anche per contenuti evento/report.
3. Il workflow applicava gia' patch v91, ma non esponeva marker, flag e artifact v91 in modo chiaro.

## Fix principale: processed URL dopo publish

Il log mostrava:

```text
[WP] Status create: 201
[WP v85] Status publish draft: 200
[PROCESSED v90.2.5] Publish result non conclusivo: non marco URL published
```

La causa probabile era il contratto di ritorno del publish: alcune funzioni ritornano tuple/list come `(post_id, post_json)`, mentre `v9025_publish_succeeded()` non le considerava successi.

v91.4 introduce:

```python
v914_post_id_from_publish_result(result)
```

che riconosce successi da:

- `True`;
- id numerico;
- stringhe di successo;
- dict con `post_id`, `id`, `wp_post_id`, `status`, `result` o `wp_status=publish`;
- tuple/list contenenti uno degli elementi precedenti.

Poi sovrascrive `v9025_publish_succeeded()` in modo compatibile e aggiunge una seconda guardia su `create_post_without_image()` per marcare esplicitamente l'URL come:

```json
{
  "status": "published",
  "reason": "v91_4_confirmed_wordpress_publish"
}
```

quando WordPress ha effettivamente pubblicato.

## Reconcile dei published artifact

Prima di avviare `run_bot()`, v91.4 legge i metadata gia' presenti in `published/*_metadata.json`.

Se trova artifact con:

- `wp_status = publish`, oppure
- `wp_post_id` valido,

ma `processed_urls.json` non contiene ancora `status=published`, aggiorna il record con:

```text
reason=v91_4_published_artifact_reconcile
```

Questo permette di correggere anche articoli gia' pubblicati prima della patch.

## Soft pool cleanup

v91.4 pulisce `soft_pool.json` prima della run:

- rimuove record scaduti in base a `created_at + ttl_hours`;
- migra alcuni core legacy evidenti quando sono ancora attivi.

Esempi:

```text
title:darby-allin:status
```

su report AEW Double or Nothing viene corretto verso:

```text
report:aew-double-or-nothing-2026-05-24
```

mentre news/event angles legati a Double or Nothing vengono riportati sotto:

```text
event:aew-double-or-nothing-2026-05-25:post-show-angle
```

La migrazione e' volutamente limitata: non tenta di riclassificare tutto il passato, ma corregge i casi che stavano interferendo con la transizione v90.2.7/v91.

## Workflow

Il workflow e' stato rinominato in:

```text
OpenWrestlingTV Bot v91.4
```

Sono stati aggiunti alla verifica source i marker:

- `v91 authoritative editorial pipeline refactor`;
- `v91.1 score return contract guard`;
- `v91.2 publish contract and authoritative lane guard`;
- `v91.3 corrected v723 parser`;
- `v91.4 publish processed and soft pool repair`.

Sono stati esplicitati i flag:

```text
V91_ENABLED=1
V91_1_ENABLED=1
V91_2_ENABLED=1
V91_3_ENABLED=1
V91_4_ENABLED=1
V91_ANALYSIS_CACHE_FILE=article_analysis_cache_v91.json
V91_4_RECONCILE_PUBLISHED_ENABLED=1
V91_4_SOFT_POOL_CLEANUP_ENABLED=1
```

`article_analysis_cache_v91.json` e' stato aggiunto agli artifact e alla persistenza runtime.

## Cosa verificare nella prossima run

Cercare nel master log:

```text
[BOOT v91.4] Publish processed + soft pool repair attivi
[PROCESSED v91.4] Published artifact reconcile: scanned=... fixed=...
[SOFTPOOL v91.4] cleanup keep=... expired=... migrated=...
[PROCESSED v91.4] URL marcato published dopo publish confermato
```

Dopo una pubblicazione, `processed_urls.json` deve contenere l'URL con:

```json
"status": "published"
```

Se questo avviene, il bug del publish non conclusivo puo' considerarsi risolto.
