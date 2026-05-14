# CHANGELOG v86.8

## Versione
`v86_8_gemini_offline_pending_preservation`

## Correzioni principali

1. **Gemini offline -> pending preservation**
   - Se `check_gemini()` fallisce, il bot non termina più perdendo i candidati della run.
   - Salva in `pending_articles.json` i candidati pubblicabili, come già faceva quando WordPress era offline.
   - I `TRUE_RESULTS_REPORT` hanno priorità nella coda pending.

2. **Report NXT preservato anche con Gemini indisponibile**
   - Il miglior true-results report viene forzatamente preservato in pending se Gemini è down.
   - Il report non viene considerato pubblicato se non c’è publish reale o conferma WordPress stretta.

3. **Cap per executive interview/opinion**
   - Articoli tipo `Cody Rhodes says he failed as a wrestling executive` non salgono più a 100 solo per termini business/dirigenza.
   - Cap default: `72`, configurabile con `V86_8_EXECUTIVE_OPINION_CAP`.

4. **Mantiene tutte le fix v86.7**
   - Pending truth fix.
   - True-results gate stretto.
   - Media guard per immagini/embed vicino a CTA finali.
   - Ricorsione report eliminata.
   - Error isolation per singolo item.

## Variabili nuove

- `V86_8_GEMINI_DOWN_PENDING_ENABLED=1`
- `V86_8_EXECUTIVE_OPINION_CAP_ENABLED=1`
- `V86_8_EXECUTIVE_OPINION_CAP=72`
