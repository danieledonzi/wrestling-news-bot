# CHANGELOG v90.1 - Quality correctness

## Summary

v90.1 corregge i problemi qualitativi emersi dal monitoraggio RAW/NXT senza modificare le chain Gemini e senza introdurre ancora una daily volume guard.

Questa release prepara Dynamite come nuova cavia: si concentra su correttezza editoriale visibile, pulizia media, titoli e dedupe topic.

## Cosa cambia

- Aggiunge `scripts/apply_bot_patch_v90_1.py`.
- Il workflow applica la patch prima del `py_compile`.
- Aggiorna il workflow label a `OpenWrestlingTV Bot v90.1`.
- Mantiene v90.0 metrics collector.

## Guard attive

### 1. Report title hardcode

Per true-results report riconosciuti, il titolo viene forzato in formato canonico:

```text
WWE Raw del 18 maggio 2026 - risultati e momenti salienti
WWE NXT del 19 maggio 2026 - risultati e momenti salienti
AEW Dynamite del ... - risultati e momenti salienti
```

### 2. Media tail guard

Riduce immagini/embed orfani in fondo al contenuto:

- per i report elimina media-only tail blocks;
- non passa `inline_images` residue al publisher per i report;
- per gli articoli normali evita append legacy quando il body contiene gia' media.

### 3. Source boilerplate sanitizer

Rimuove bio autore/source boilerplate, ad esempio frasi tipo:

```text
Subhojeet Mukherjee segue il wrestling da oltre 20 anni...
```

### 4. Numeric title fidelity

Protegge numeri fattuali nei titoli:

- `WrestleMania 42` non puo' diventare `WrestleMania 40`;
- pattern protetti: WrestleMania, WWE 2K, AEW Dynamite, NXT.

### 5. Topic/status dedupe guard

Aggiunge un dedupe editoriale su topic gia' problematici:

- `status:la-knight:wwe-absence`;
- `business:wwe:house-shows-expansion`.

### 6. Stale spoiler cleanup

Se un report per lo show risulta gia' confermato, il titolo di follow-up post-show non mantiene piu' `[SPOILER]`.

## Cosa non cambia

- Non cambia scoring generale.
- Non cambia feed.
- Non cambia chain Gemini.
- Non cambia soglie di pubblicazione.
- Non introduce target giornaliero / pacing.

## Expected logs

```text
[BOOT v90.1] Quality correctness guard attiva...
[TITLE v90.1] Report title hardcode: ...
[MEDIA v90.1] Rimossi media orfani in coda report: ...
[SANITIZE v90.1] Rimossi blocchi boilerplate/autore: ...
[TITLE v90.1] Numeric fidelity title fix: ...
[SKIP v90.1] Topic/status duplicate guard ...
[SPOILER v90.1] Rimosso spoiler post-report: ...
```

## Nota

Le chain Gemini restano volutamente invariate: le traduzioni sono considerate buone e la qualita' del singolo articolo non va sacrificata. L'ottimizzazione di pacing e volume resta prevista per v90.2.
