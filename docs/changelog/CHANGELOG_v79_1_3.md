# CHANGELOG v79.1.3

## v79_1_3_type_freshness_cap_coherence

Patch mirata costruita sopra v79.1.2.

### Obiettivo

Rendere coerenti il layer spoiler/type AI con i vecchi cap/freshness deterministici.

### Correzioni principali

- Se l'analisi AI riconosce una news come `POST_SHOW_NEWS` o `RESULTS_REPORT`, il vecchio filtro `preview scaduta` non puo' piu' abbattere lo score a 20.
- Se Gemini restituisce `PREVIEW` ma nella motivazione dice che l'articolo **non e' una preview** o che e' un **annuncio fatto durante un live/show**, il tipo viene corretto a `POST_SHOW_NEWS`.
- Il floor spoiler validato viene riapplicato dopo i cap finali, cosi' non appare piu' il caso `floor 56->75` seguito da score finale 56.
- Gli annunci fatti durante un evento live, come un annuncio durante Backlash, non vengono trattati come preview scadute.
- Riparazione dell'event key: se nasce un falso `event:legal:*` senza keyword legali forti nel titolo, viene convertito in una chiave `event:postshow:*` o `event:story:*`.

### Casi osservati dalle run v79.1.2

- `John Cena Announces Plans For 'John Cena Classic' Tournament During WWE Backlash` non deve passare da 95 a 20 per `v68 preview scaduta`.
- `WWE Announces First-Ever Two-Night TripleMania During Backlash` non deve essere classificata come preview se la reason dice che e' un annuncio post-show.
- Gli spoiler validati non devono essere cappati sotto soglia dopo l'applicazione del floor.
- Falsi `event:legal:cm-punk` su contenuti Danhausen/Minihausen vengono evitati.
