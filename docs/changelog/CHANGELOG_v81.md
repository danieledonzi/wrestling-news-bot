# CHANGELOG v81

## Versione
`v81_translation_preservation_and_flat_review_archive`

## Obiettivo
Stabilizzare la pipeline dopo i test v80.9/v80.10: archivio review piu comodo, guardrail career/status meno invasivo e protezione contro omissioni di contenuto nel post-edit.

## Modifiche principali

### 1. Published HTML review flat archive
La review degli articoli pubblicati viene salvata in una singola cartella piatta:

```text
published_html_review/
  <timestamp>_<idx>_<slug>_<hash>_original.html
  <timestamp>_<idx>_<slug>_<hash>_final.html
  <timestamp>_<idx>_<slug>_<hash>_metadata.json
  index.json
  run_<RUN_ID>_summary.json
```

Non vengono piu create sottocartelle per run in modalita flat. Questo rende possibile scaricare/bloccare tutta la cartella dopo piu run e analizzarla insieme al master log cumulativo.

### 2. Career/status guardrail piu stretto
Il guardrail v80.9 era utile per casi come retirement/released/status, ma poteva attivarsi su frasi storyline generiche come "last night here".

In v81 si attiva solo con termini espliciti di status carriera/contratto/medicale, ad esempio:
- retirement / retired / semi-retired
- released / roster cuts
- contract / free agent
- cleared / not cleared
- career status / WWE status

### 3. Anti-omissione post-edit
Aggiunto un controllo conservativo dopo il post-edit:
- se la traduzione finale e troppo corta rispetto al testo sorgente;
- oppure se mancano cluster narrativi importanti rilevati nel testo originale;

il bot chiede una repair mirata a Gemini per reinserire solo i fatti mancanti, mantenendo HTML semplice e senza aggiungere informazioni esterne.

### 4. Cleanup lessicale wrestling
Aggiunta correzione deterministica per frasi come:
- `ha svincolato la presa` -> `ha lasciato la presa`
- `ha rilasciato la presa` -> `ha lasciato la presa`

## Nota operativa
Il vecchio ZIP review resta disattivato di default come in v80.10, salvo `REVIEW_PACKAGE_ENABLED=1`.
