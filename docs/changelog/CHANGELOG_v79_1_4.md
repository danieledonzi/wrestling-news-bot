# CHANGELOG v79.1.4

## v79_1_4_spoiler_semantics_outcome_obsolete

Correzione mirata del layer spoiler dopo osservazione delle run v79.1.3.

### Fix principali

- Estesa la hard validation spoiler per risultati concreti:
  - `earns victory`, `gets win`, `victory over`, `defeats`, `beats`, `pins`, `submits`, `retains`, `new champion`, ecc.
- Gli annunci post-show senza outcome concreto non vengono marcati come `[SPOILER]`:
  - esempio: annuncio del torneo `John Cena Classic`.
- Gli spoiler pre-show diventano obsoleti se in history esiste già un risultato/report dello stesso evento:
  - esempio: `Opening Match Revealed` dopo che esiste già un risultato dell'opener.
- Aggiunto cap prudenziale per spoiler pre-show obsoleti, evitando che il floor spoiler li riporti sopra soglia.

### Obiettivo editoriale

Distinguere meglio tra:

- outcome spoiler: risultato, vittoria, retain, identità rivelata;
- post-show news non spoiler: annunci, dichiarazioni, segmenti senza outcome;
- pre-show spoiler valido: lineup/match order prima dell'esito;
- pre-show spoiler obsoleto: lineup/match order dopo che l'esito è già stato rilevato.
