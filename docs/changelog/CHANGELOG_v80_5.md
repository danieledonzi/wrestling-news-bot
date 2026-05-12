# CHANGELOG v80.5

## v80_5_review_packages_default_on

- Parte da v80.4.
- I review package sono ora attivi di default durante il periodo di review.
- `REVIEW_PACKAGE_ENABLED` resta configurabile: impostare `0`/`false` per disattivare.
- Il pacchetto crea sempre `review_packages/run_...` con `summary.json`, `run.log` e gli item processati quando disponibili.
- `cron_v80_5.yml` include `REVIEW_PACKAGE_ENABLED: 1` e upload artifact della cartella `review_packages/`.
- Nessuna modifica alla logica editoriale AAA/spoiler/dedupe della v80.4.
