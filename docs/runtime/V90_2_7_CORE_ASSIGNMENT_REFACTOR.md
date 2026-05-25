# v90.2.7 core assignment refactor

## Obiettivo

Rendere il core story/evento una decisione centrale, stabile e deterministica.

Il problema emerso nei log e' che un report evento riconosciuto dalla event registry poteva comunque finire in update gate/soft pool con un core legacy sbagliato, per esempio:

```text
core=title:darby-allin:status
```

Questo e' errato per un report AEW Double or Nothing, che deve avere core:

```text
report:aew-double-or-nothing-YYYY-MM-DD
```

## Nuova funzione centrale

```python
assign_story_core_v9027(item, title, url, text, editorial_analysis=None)
```

La funzione restituisce un dizionario strutturato:

```python
{
  "core": "...",
  "core_type": "event_report|event_news|event_context|business|legacy",
  "event_key": "...",
  "report_key": "...",
  "subject": "...",
  "action": "...",
  "confidence": 0.0,
  "source": "event_registry|deterministic_business|legacy"
}
```

## Gerarchia

1. Event results report da registry:

```text
core_type=event_report
core=report:<promotion>-<event>-<date>
```

2. Singola news post-show evento:

```text
core_type=event_news
core=event:<promotion>-<event>-<date>:<subject-action>
```

3. News di contesto/logistica evento:

```text
core_type=event_context
core=event:<promotion>-<event>-<date>:<angle-type>
```

4. Business/corporate reale:

```text
core_type=business
core=business:<entity>:<topic>
```

5. Fallback legacy solo quando nessuna regola sopra si applica.

## Consumer aggiornati

La patch intercetta:

- make_news_core_key
- make_story_signature_v71
- make_event_key
- process_candidate_item
- soft_pool add

Quando `core_assigned_by == v90.2.7`, i consumer devono usare `story_core_v9027` e non ricalcolare un core generico.

## Non obiettivi

- Non cambia le soglie dello scoring.
- Non cambia la event registry.
- Non cambia la Gemini chain.
- Non pubblica retroattivamente report vecchi.

## Prossimo passo

Dopo una run positiva, valutare separatamente:

```text
v90.2.8_feed_level_processed_skip
```

per anticipare l'hard skip URL subito dopo la lettura feed.
