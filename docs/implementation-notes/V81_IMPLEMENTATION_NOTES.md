# V81 Implementation Notes

## Perche v81
Le run v80.9 e v80.10 hanno mostrato tre esigenze:

1. L'archivio review per run funziona, ma e scomodo per scaricare molti HTML dopo 4-5 run.
2. Il guardrail career/status risolve il caso Asuka, ma puo essere troppo ampio su frasi storyline non legate a carriera/contratto.
3. Il post-edit puo omettere parti narrative importanti, come nel caso Roman/Fatu, dove mancava la sequenza post-match finale.

## Dettagli tecnici

### Flat archive
`published_html_review_run_dir()` ora punta direttamente a `published_html_review/`.
`save_published_html_review_item()` scrive file flat con suffisso:
- `_original.html`
- `_final.html`
- `_metadata.json`

`finalize_published_html_review_index()` aggiorna `index.json` cumulativo e salva un summary della singola run.

### Narrow career trigger
Override di:
- `v809_source_has_career_status_concept()`
- `v809_extract_career_status_source_excerpt()`

La lista termini rimuove trigger generici come `future` e `status` presi isolatamente, sostituendoli con espressioni piu specifiche.

### Anti-omissione
Nuove funzioni:
- `v81_translation_may_have_omissions()`
- `v81_repair_possible_omissions()`
- `v81_cleanup_wrestling_action_language()`

Il wrapper finale di `v79_editorial_post_edit()` applica cleanup lessicale, controllo omissioni e cleanup finale.

## Variabili ambiente

- `PUBLISHED_HTML_REVIEW_ENABLED=1` default
- `PUBLISHED_HTML_REVIEW_DIR=published_html_review` default
- `PUBLISHED_HTML_REVIEW_MAX_CHARS=0` default, nessun troncamento
- `V81_MIN_TRANSLATION_WORD_RATIO=0.78` default
- `REVIEW_PACKAGE_ENABLED=0` default

## Atteso nel log

```text
VERSION [v81_translation_preservation_and_flat_review_archive (...)]
[PUBLISHED REVIEW v81] Salvati HTML pubblicati flat: published_html_review/...
[PUBLISHED REVIEW v81] Index flat salvato: published_html_review/index.json
```

Se il controllo anti-omissione interviene:

```text
[PRESERVE v81] Repair anti-omissione applicato ...
[PRESERVE v81] Guardrail finale testo applicato
```
