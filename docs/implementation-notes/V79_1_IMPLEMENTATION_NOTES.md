# v79.1 Implementation Notes

Implemented in `bot_v79_1.py`.

## Obiettivo

Rendere il layer spoiler più contestuale e meno aggressivo. La v79 applicava il prefisso `[SPOILER]` partendo da keyword e contesto evento; la v79.1 richiede prima una vera finestra live attiva e poi usa Gemini solo come supporto semantico.

## Nuove funzioni

- `v791_has_any()`
- `v791_is_live_event_active()`
- `v791_is_auto_no_spoiler()`
- `v791_has_spoiler_hard_validation()`
- `v791_gemini_spoiler_classifier()`
- override di `v79_is_live_spoiler_candidate()`

## Pipeline spoiler aggiornata

```text
source title/text/url
  -> hard no gates
     - spoiler mode off
     - report completo
     - nessun evento live attivo
     - retrospective/opinion/business/interview/evergreen/preview
  -> Gemini semantic spoiler classifier
     - SPOILER / NOT_SPOILER
  -> hard validation finale
     - result/winner/retained/new champion/return/surprise/attack/segment/cash-in/heel turn/betrayal...
  -> eventuale prefisso [SPOILER]
```

## Finestra live

`v791_is_live_event_active()` usa:

- override manuale via `V791_FORCE_LIVE_EVENT`;
- finestre tipiche Europe/Rome per show settimanali USA;
- finestre strette notturne per PLE/PPV;
- segnali live espliciti solo se la run è in una finestra oraria plausibile.

## Gemini

Il prompt è volutamente minimale:

```text
Questa news contiene spoiler concreti di un evento live WWE/AEW/TNA/AEW in corso?
Rispondi SOLO:
SPOILER
oppure
NOT_SPOILER
```

Input passati:

- titolo;
- URL;
- editorial type, se disponibile;
- excerpt/primo paragrafo limitato da `V791_SPOILER_CONTEXT_MAX_CHARS`.

## Fallback

Se Gemini non è disponibile, il sistema resta conservativo: applica `[SPOILER]` solo se evento live attivo + contesto evento + hard validation concreta.
