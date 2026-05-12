# v80.10 Implementation Notes

## Obiettivo

Permettere review cumulativa dopo 4-5 run senza scaricare artifact temporanei GitHub Actions.

Il master log è già cumulativo; mancava una cartella versionata nel repo contenente solo gli HTML utili: sorgente e finale degli articoli effettivamente pubblicati.

## Nuove variabili

```yaml
PUBLISHED_HTML_REVIEW_ENABLED: "1"
PUBLISHED_HTML_REVIEW_DIR: published_html_review
```

Optional:

```yaml
PUBLISHED_HTML_REVIEW_MAX_CHARS: "0"
```

`0` significa nessun troncamento.

## Nuove funzioni

- `published_html_review_run_dir()`
- `save_published_html_review_item(item)`
- `finalize_published_html_review_index()`

## Struttura output

```text
published_html_review/
  run_20260510_150000_abcdef0/
    summary.json
    001_titolo-articolo_xxxxxxxx/
      original.html
      final.html
      metadata.json
```

## Cosa viene salvato

Solo candidati con status finale:

```python
status == "published"
```

Non vengono salvati skipped, pending, validation_fail, model_fail o wp_fail.

## Interazione con vecchio review package

La v80.10 imposta:

```python
REVIEW_PACKAGE_ENABLED = os.getenv("REVIEW_PACKAGE_ENABLED", "0")...
```

Quindi il vecchio ZIP all-attempted è off di default. Può essere riattivato manualmente impostando `REVIEW_PACKAGE_ENABLED=1`.

## GitHub Actions

`cron_v80_10.yml` aggiunge:

```bash
[ -d published_html_review ] && git add -f published_html_review/
```

Così dopo alcune run basta scaricare/passare:

- `logs/master_log.log`
- l'intera cartella `published_html_review/`
