# v79.1.5 - Stable Story Dedupe

## Obiettivo
Ridurre spreco di minuti GitHub Actions e chiamate Gemini bloccando prima possibile i rewrite cross-source/cross-title della stessa notizia.

## Correzione principale
Aggiunto un livello deterministico `stable_story_key` prima di scraping pesante e Gemini:

- entita principali;
- oggetto narrativo stabile;
- azione editoriale;
- contesto promotion/evento filtrato.

Esempio generale:

```text
John Cena Annonuces Plans For 'John Cena Classic' Tournament During WWE Backlash
John Cena Announces New WWE Event, Championship With Unique Rules At Backlash 2026
```

ora convergono sulla stessa firma stabile:

```text
stable:john_cena|john_cena_classic|announcement|wwe|backlash
```

## Regola generale
Non e una regola hardcoded su John Cena: il sistema cerca un oggetto narrativo stabile, come:

- tornei/classic/cup/series;
- titoli/championship;
- eventi annunciati;
- identita rivelate;
- outcome di match.

## Punto tecnico
Le stable key vengono anche derivate dai record gia presenti in `history.txt`, usando URL, semantic_id, title_key, event_key e story_signature. Cosi la protezione funziona anche contro articoli gia pubblicati prima della v79.1.5, quando possibile.
