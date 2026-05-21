# CHANGELOG v90.1.3 - Spoiler hotfix

## Summary

v90.1.3 e' una hotfix minima sugli spoiler.

La v90.1.2 aveva introdotto la regola corretta, ma la wrapper v90.1.1 continuava ad aggiungere `[SPOILER]` dopo la cleanup calendar-aware. Risultato: news non-show come Ludwig Kaiser/arresto uscivano ancora con `[SPOILER]`.

## Cosa cambia

- Aggiunge `scripts/apply_bot_patch_v90_1_3.py`.
- Aggiorna workflow a `OpenWrestlingTV Bot v90.1.3`.
- Applica v90.1.3 dopo v90.1.2.

## Fix

### Single source of truth per spoiler

v90.1.3 sovrascrive direttamente la funzione larga di v90.1.1:

```text
v9011_should_prefix_spoiler -> v9013_should_prefix_spoiler -> v9012_should_prefix_spoiler
```

Da ora solo la calendar-aware guard puo' aggiungere `[SPOILER]`.

### Cleanup difensiva finale

Se un titolo arriva comunque con `[SPOILER]`, la wrapper finale lo rimuove salvo conferma della regola calendario.

## Caso guida

```text
Giovedi': expected_show=dynamite
Ludwig Kaiser arresto/caso giudiziario -> NON spoiler
Willow/Dynamite pre-report -> spoiler solo se il report Dynamite non e' ancora pubblicato
```

## Cosa non cambia

- Non cambia scoring.
- Non cambia media guard.
- Non cambia chain Gemini.
- Non cambia pacing.
- Non cambia soft pool.

## Expected logs

```text
[SPOILER v90.1.3] v90.1.1 spoiler guard sovrascritta con calendar-aware guard
[BOOT v90.1.3] Spoiler hotfix attiva: solo calendar-aware guard puo' aggiungere [SPOILER]
[SPOILER v90.1.3] Rimosso spoiler falso/fuori calendario: ...
```
