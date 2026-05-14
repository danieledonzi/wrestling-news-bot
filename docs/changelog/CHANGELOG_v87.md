# CHANGELOG v87

Versione: `v87_model_routing_tier3_anchor_guard`

## Modifiche principali

1. **Model routing stabilizzato**
   - Rimosso `gemini-3.1-flash` standard dalle chain di default.
   - Le chain operative diventano:
     - `V87_DEFAULT_LITE_CHAIN = gemini-3.1-flash-lite, gemini-2.5-flash-lite`
     - `V87_STRONG_CHAIN = gemini-2.5-flash, gemini-3.1-flash-lite, gemini-2.5-flash-lite`
     - `V87_STORM_REPORT_CHAIN = gemini-2.5-flash, gemini-3.1-flash-lite, gemini-2.5-flash-lite`
     - `V87_STORM_LITE_CHAIN = gemini-3.1-flash-lite, gemini-2.5-flash-lite`
   - Le vecchie variabili `V83_*` vengono riallineate alle chain v87 per compatibilità con il router ereditato.

2. **Blocco tier3 opinion/interview sotto 55**
   - Gli articoli opinion/interview/commentary sotto 55 non vengono più recuperati come tier3.
   - Evita casi come dichiarazioni/commenti di Cody Rhodes, Bully Ray, Russo, Meltzer, ecc. quando non c'è un fatto concreto nuovo.

3. **Sanitizzazione link inline non autorizzati**
   - Prima del publish vengono rimossi gli `<a>` non autorizzati dal body.
   - Nomi di wrestler o frasi normali non possono restare collegamenti ipertestuali.
   - Sono preservati solo link/embed tecnici autorizzati, in particolare social/video embeddabili e link con testo URL esplicito.

## Fix ereditate mantenute

- Report source recovery v86.9.
- Pending truth fix v86.7.
- Gemini offline pending preservation v86.8.
- Media guard contro perdita immagini/embed vicino alle CTA finali.
- True-results report gate stretto.
