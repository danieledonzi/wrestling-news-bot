# CHANGELOG v90.0 - Cost and volume observability

## Summary

v90.0 introduce una fase di osservabilita' senza modificare la logica editoriale del bot.

L'obiettivo e' raccogliere dati reali per decidere, mercoledi' 20, come impostare la daily volume guard, il budget giornaliero e il routing dei modelli Gemini sulla base di evidenze e non di sensazioni.

## Cosa cambia

- Aggiunge `scripts/collect_v90_metrics.py`.
- Aggiunge lo step GitHub Actions `Collect v90.0 metrics` dopo `Run bot` e prima della persistenza artifact.
- Aggiorna il workflow label a `OpenWrestlingTV Bot v90.0`.
- Salva metriche in:
  - `logs/v90_metrics_latest.json`;
  - `logs/v90_metrics.jsonl`.

## Metriche raccolte

Per ogni run:

- run start/end;
- versione bot;
- mode normal/storm;
- candidati totali;
- candidati provati;
- pubblicati totali/pending/nuovi;
- skip totali e skip v89;
- chiamate Gemini osservate dai log;
- modelli Gemini usati;
- task model dichiarati;
- modelli scartati/fallback;
- tempi `[PERF v71]` aggregati;
- pubblicati nella giornata e nelle ultime 4 ore.

Per ogni articolo pubblicato con HTML disponibile:

- path HTML;
- word count finale;
- paragrafi;
- blockquote;
- immagini;
- iframe/embed hints;
- titolo pubblicato.

## Cosa non cambia

- Non cambia scoring.
- Non cambia soglie.
- Non cambia selezione news.
- Non cambia routing Gemini.
- Non blocca o favorisce soft news.
- Non introduce ancora daily volume guard.

## Expected logs

```text
[METRICS v90.0] published=... candidates=... gemini_calls=... models=... daily=...
[METRICS v90.0] article words=... images=... quotes=... title=...
```

## Decisioni rimandate

Dopo RAW e NXT, il 20 maggio verranno valutati:

- quanti report sono stati pubblicati;
- quante news autonome rilevanti sulle puntate sono state pubblicate;
- quante soft news lunghe sono state pubblicate;
- costo Gemini approssimato da chiamate/modelli/tempi;
- se introdurre un budget giornaliero dinamico;
- se introdurre routing Gemini per valore e lunghezza.
