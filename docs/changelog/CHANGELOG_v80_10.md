# CHANGELOG v80.10

## v80_10_published_html_review_archive

- Parte da v80.9.
- Disattiva di default il vecchio review package ZIP `review_packages` con tutti i candidati tentati.
- Aggiunge archivio persistente in repo per review editoriale: `published_html_review/`.
- Per ogni run crea una cartella `published_html_review/run_<timestamp>_<sha>/`.
- Salva esclusivamente gli articoli realmente pubblicati.
- Per ogni articolo pubblicato salva:
  - `original.html`: HTML originale sorgente estratto dallo scraping;
  - `final.html`: HTML finale generato dal bot e inviato a WordPress;
  - `metadata.json`: titolo sorgente/finale, URL, categoria, score, blocchi, embed e firma semantica.
- Crea `summary.json` per ogni run.
- Il workflow `cron_v80_10.yml` aggiunge `published_html_review/` al commit insieme a history/log/pending.
- Il vecchio pacchetto review completo resta riattivabile con `REVIEW_PACKAGE_ENABLED=1`, ma non è più il default.
