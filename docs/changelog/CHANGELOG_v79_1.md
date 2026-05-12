# CHANGELOG v79.1

## v79_1_hybrid_live_spoiler_classifier

- Mantiene la base v79: traduzione AI-native, post-editing editoriale e prefisso `[SPOILER]`.
- Sostituisce il layer spoiler keyword-first con una logica ibrida:
  1. hard rules deterministiche prima dell'AI;
  2. Gemini solo come classificatore semantico di supporto;
  3. hard validation deterministica dopo Gemini.
- Il prefisso `[SPOILER]` non viene più applicato se non c'è un evento live attivo.
- I contenuti retrospective, opinion/commentary, business, interview, evergreen, preview e report completi sono auto-`NOT_SPOILER`.
- Aggiunto classificatore Gemini minimale per lo spoiler semantico, con risposta obbligata `SPOILER` / `NOT_SPOILER`.
- Anche quando Gemini risponde `SPOILER`, il tag viene applicato solo se il testo contiene almeno un segnale concreto: risultato, vincitore, cambio titolo, ritorno, sorpresa, attacco, segmento, cash-in, heel turn, betrayal, ecc.
- Aggiunti log `[SPOILER v79.1]` per distinguere hard no, risposta Gemini, validazione finale e fallback deterministico.
- Aggiunte variabili ambiente:
  - `V791_ENABLE_GEMINI_SPOILER_CLASSIFIER=1`
  - `V791_FORCE_LIVE_EVENT=` per test/override manuale
  - `V791_SPOILER_CONTEXT_MAX_CHARS=900`
