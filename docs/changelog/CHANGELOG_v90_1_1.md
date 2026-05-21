# CHANGELOG v90.1.1 - Media duplicate and spoiler fixes

## Summary

v90.1.1 corregge tre regressioni/osservazioni emerse dopo Dynamite:

1. immagini/embed gia' presenti nel body venivano duplicati in fondo;
2. il report Dynamite poteva essere titolato come Collision perche' la detection leggeva riferimenti nel corpo;
3. risultati/angle pubblicati prima del report devono essere marcati `[SPOILER]`.

## Cosa cambia

- Aggiunge `scripts/apply_bot_patch_v90_1_1.py`.
- Aggiorna workflow a `OpenWrestlingTV Bot v90.1.1`.
- Applica v90.1.1 dopo v90.1 e review fix.

## Guard introdotte

### 1. Media queue dedupe

Se immagini/embed sono gia' nel body finale, non vengono piu' lasciati nelle code residue `inline_images` / `embed_urls`, evitando duplicati in fondo.

Regola forte per i report:

```text
report true-results -> non appendere mai code media residue a fondo articolo
```

Per articoli normali:

```text
body contiene figure/img/blockquote/embed -> scarta code media residue
```

### 2. Report show strict title

Il titolo hardcoded dei report usa campi affidabili in ordine:

```text
event_key -> source title -> url -> body solo come fallback
```

Questo evita casi tipo report Dynamite titolato come Collision per riferimenti interni al testo.

### 3. Pre-report spoiler guard

Se una news rivela risultati, ritorni, infortuni, title change o angle di uno show e il report relativo non e' ancora confermato, viene prefissata con `[SPOILER]`.

Esempio atteso:

```text
Willow Nightingale lascia il titolo AEW TBS prima del report Dynamite -> [SPOILER]
```

Se invece il report e' gia' confermato, v90.1 continua a rimuovere spoiler non necessari sui follow-up post-report.

## Cosa non cambia

- Non cambia scoring generale.
- Non cambia chain Gemini.
- Non introduce ancora pacing/soft pool.
- Non cambia i feed.

## Expected logs

```text
[BOOT v90.1.1] Media duplicate queues, strict report title and pre-report spoiler guard attivi
[MEDIA v90.1.1] Report: scarto code media residue per evitare duplicati in fondo images=X embeds=Y
[MEDIA v90.1.1] Articolo con media nel body: scarto code residue images=X embeds=Y
[TITLE v90.1.1] Report title strict fix: ...
[SPOILER v90.1.1] Aggiunto spoiler pre-report: ...
```
