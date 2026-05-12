# CHANGELOG v79.1.2

## v79_1_2_spoiler_score_floor

- Mantiene la logica v79.1.1: hard rules, cache spoiler, Gemini classifier e hard validation finale.
- Aggiunge uno scoring floor controllato per spoiler live/pre-show gia' validati dal layer ibrido.
- Risolve il caso in cui articoli come `Match Order Reportedly Revealed` o `Opening Match Revealed` venivano riconosciuti come spoiler ma restavano sotto soglia per i cap preview/rumor.
- Il floor non si applica a:
  - results report completi;
  - opinion/interview/retrospective/business/evergreen;
  - articoli senza evento live attivo;
  - contenuti che Gemini non classifica come spoiler o che non superano la hard validation.
- Nuove env opzionali:
  - `V7912_SPOILER_SCORE_FLOOR`, default `MIN_PUBLISH_SCORE`;
  - `V7912_SPOILER_SCORE_CAP`, default `82`.
