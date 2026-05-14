# Implementation Notes v87.3

## Title hard gate

La v87.3 sostituisce la logica permissiva precedente. Il titolo non può più degradare a fallback deterministico se la title chain fallisce.

Flusso:

1. `v721_ensure_italian_title` chiama la chain `title`.
2. Se il risultato sembra ancora inglese, rotto, uguale al source title o contiene residui come `wants`, `prepares for`, `title defense`, viene chiamata `emergency_title`.
3. Se anche `emergency_title` fallisce, viene sollevato `TITLE_MODEL_FAILURE`.
4. `process_candidate_item` intercetta `TITLE_MODEL_FAILURE`, salva il candidato in pending e restituisce `model_fail`.
5. `create_post_without_image` ha un ultimo blocco di sicurezza: se il titolo è ancora non pubblicabile, il post non viene creato.

## Model matrix

`gemini-3-flash` è escluso per default. Può essere riabilitato solo con:

```bash
V873_ENABLE_GEMINI_3_FLASH=1
```

quando il nome API esatto sarà confermato.

## Positional embed guard

Durante `translate_ordered_content_blocks`, la v87.3 salva per ogni embed:

- URL canonico;
- chiave dedupe;
- indice sorgente;
- numero di blocchi testo precedenti.

Prima del publish, se l'embed manca dal body tradotto, viene reinserito dopo lo stesso numero di paragrafi editoriali tradotti. Questo evita il vecchio comportamento di append in fondo articolo.

## X/Twitter dedupe semantico

Se è presente un embed X valido:

- i paragrafi con `t.co` vengono rimossi;
- le firme tipo `- Rey Fenix WWE (@ReyFenixMx) 13 maggio 2026` vengono rimosse;
- `twitter.com` viene canonicalizzato in `x.com`;
- resta un solo oEmbed nella posizione originale.

## Report history forte

`confirmed_published_reports.json` ora viene scritto solo per chiavi report vere, ad esempio:

```text
report:wwe-nxt-2026-05-12
```

Non vengono più salvati come report articoli normali con slug trasformato in `report:*`.
