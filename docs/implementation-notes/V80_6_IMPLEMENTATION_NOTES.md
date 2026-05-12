# v80.6 Implementation Notes

## Obiettivo

Ridurre lo stile artificiale/enfatico osservato in alcune traduzioni senza aumentare costi, latenza o complessita della pipeline.

## Strategia

Non sono stati aggiunti nuovi passaggi Gemini, servizi esterni o dizionari infiniti.

E' stata introdotta una costante di prompt:

```python
NATURAL_ITALIAN_STYLE_RULES_V806
```

usata nei punti in cui il modello genera o rifinisce testo:

- traduzione blocchi strutturati;
- post-edit v79/v80;
- riparazione/finalizzazione titolo.

## Principio

Il bot deve scrivere come una news wrestling italiana reale: diretto, concreto, asciutto, senza tono epico o formule AI.

## Non modificato

Restano invariati:

- scoring;
- spoiler layer;
- pre-show obsolete logic;
- AAA World priority;
- dedupe;
- pending/report;
- review packages.
