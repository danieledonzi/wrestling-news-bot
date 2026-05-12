# OpenWrestlingTV Bot v80.7

## Scope
Microfix mirata sul dedupe semantico.

## Problema
Titoli come:
- `Backstage Reaction to Asuka’s Emotional WWE Backlash Moment Amid Uncertainty About Her Future`
- `Asuka May Be Semi-Retired Following WWE Backlash Moment`

venivano trattati come duplicati perché condividevano wrestler/evento con un precedente articolo sul risultato o sul momento emotivo di Backlash.

## Fix
Aggiunto layer v80.7 `followup_dedupe_context`:
- stesso wrestler + stesso evento non basta per bloccare un articolo;
- se il titolo introduce un nuovo angolo editoriale, la story signature cambia;
- backstage reaction, futuro, semi-ritiro, retirement/career status sono follow-up autonomi;
- se un vecchio layer dedupe prova comunque a bloccarli, il blocco viene convertito in `followup_advancement_not_duplicate_v807`.

## Non modificato
- scoring;
- spoiler;
- AAA boost;
- traduzione/stile;
- report;
- review packages;
- oEmbed.
