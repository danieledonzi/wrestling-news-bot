# CHANGELOG v90.1.2 - Calendar-aware spoiler guard

## Summary

v90.1.2 restringe la gestione spoiler introdotta in v90.1.1.

La regola non deve aggiungere `[SPOILER]` a qualunque news WWE/AEW. Deve farlo solo quando la news rivela fatti rilevanti della puntata il cui report e' atteso in quel giorno.

## Logica editoriale

Esempio: giovedi' italiano.

```text
report atteso: AEW Dynamite
spoiler: solo notizie che rivelano risultati/angle/infortuni/title change di Dynamite prima del report
non spoiler: notizie WWE generiche, arresti, podcast, business, interviste, ascolti, rumor non legati alla puntata attesa
```

## Calendario base

```text
martedi' -> RAW
mercoledi' -> NXT
giovedi' -> Dynamite
venerdi' -> Impact
sabato -> SmackDown
domenica -> Collision
lunedi' -> nessun weekly report standard
```

## Cosa cambia

- Aggiunge `scripts/apply_bot_patch_v90_1_2.py`.
- Aggiorna workflow a `OpenWrestlingTV Bot v90.1.2`.
- Applica v90.1.2 dopo v90.1.1.

## Guard introdotta

### Calendar-aware spoiler guard

La label `[SPOILER]` viene aggiunta solo se:

1. esiste uno show atteso per il giorno corrente;
2. la news cita quello show specifico;
3. la news contiene un outcome rilevante della puntata;
4. il report di quello show non risulta ancora confermato;
5. la news non e' chiaramente non-show news, come arresti, cause legali, podcast, interviste, health/business ecc.

### False spoiler cleanup

Se una wrapper precedente ha gia' aggiunto `[SPOILER]` ma la regola calendario non lo conferma, v90.1.2 rimuove il prefisso.

Caso guida:

```text
Ludwig Kaiser si costituisce per mandato d'arresto -> NON spoiler
Willow Nightingale lascia il titolo AEW TBS prima del report Dynamite -> spoiler solo se giovedi' e report Dynamite non pubblicato
```

## Cosa non cambia

- Non cambia media guard.
- Non cambia scoring.
- Non cambia chain Gemini.
- Non introduce pacing o soft pool.

## Expected logs

```text
[BOOT v90.1.2] Calendar-aware spoiler guard attiva: expected_show=dynamite
[SPOILER v90.1.2] Aggiunto spoiler calendario: ...
[SPOILER v90.1.2] Rimosso spoiler non coerente con calendario (...): ...
```
