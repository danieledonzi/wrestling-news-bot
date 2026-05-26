# OpenWrestlingTV Bot v92 - Clean Split Pipeline Architecture

## Stato del documento

Documento di specifica editoriale e tecnica per la rifondazione v92.

Questa specifica nasce dopo le regressioni della linea v91.x, in particolare:

- report show trattati come news candidate;
- scoring applicato ai report;
- core/event mapping contaminato;
- patch cumulative con effetti collaterali su percorsi non correlati;
- report RAW rimasto in pending nonostante molte patch;
- articoli normali trasformati erroneamente in report.

La v92 non deve essere una patch della v91. Deve essere una rifondazione modulare che recupera solo i componenti funzionanti.

---

## Principio editoriale centrale

Il bot deve trattare contenuti di natura diversa con pipeline diverse.

```text
Report = contenuto programmato
News = contenuto selezionato
Editoriale umano = contenuto manuale
```

Ogni item deve avere un tipo immutabile:

```text
kind = report
kind = news
kind = manual_editorial
```

Il tipo non deve cambiare durante la lavorazione.

Non deve piu' accadere che:

```text
report -> news -> pending -> resolved-report-source -> report -> skip_final
news -> report
articolo normale -> titolo report
```

---

## Pipeline separate

La v92 deve avere almeno tre percorsi distinti:

```text
report_pipeline
news_pipeline
article_workshop
```

### report_pipeline

Gestisce report show / PLE / PPV.

Caratteristiche:

- nessuno scoring;
- nessuna competizione con le news;
- nessun soft pool;
- nessun dedupe news generico;
- titolo deterministico;
- categorie deterministiche;
- pubblicazione obbligatoria se il report atteso e' disponibile;
- fallback fonte controllato;
- stato dedicato in `report_status.json`.

### news_pipeline

Gestisce le news ordinarie.

Caratteristiche:

- scoring/ranking semplice;
- massimo 3 news per run;
- soft pool;
- dedupe semantico;
- valutazione di novita' rispetto a story core gia' coperti;
- titolo scritto da AI;
- categorie attuali mantenute.

### article_workshop

Catena tecnica comune per la lavorazione articolo.

Responsabilita':

- scraping;
- estrazione blocchi;
- preservazione immagini/embed;
- traduzione strutturata;
- post-edit;
- generazione titolo se richiesta;
- costruzione HTML;
- publish WordPress;
- salvataggio review artifacts.

Il workshop non decide se un contenuto e' report o news. Riceve un job gia' classificato dalla pipeline corretta.

---

## Budget di pubblicazione

Report e news hanno budget separati.

```text
max_reports_per_run = 1
max_news_per_run = 3
```

Quindi, se in una run c'e' un report dovuto e pubblicabile:

```text
1 report + fino a 3 news = massimo 4 pubblicazioni
```

Il report non consuma slot news.

Ordine della run:

```text
1. processa report dovuti
2. aggiorna report_status
3. processa news con spoiler policy aggiornata
```

---

## Report pipeline

Un report e' un contenuto programmato, non una news.

### Regola generale

```text
se e' un report results:
    usa pipeline report dedicata
    non passa dallo scoring news
    non passa dal dedupe news generico
    non passa dal title hardcode di articoli normali
```

### Scheduling

I report show settimanali e i report PLE/PPV devono essere configurati in un registry dedicato.

Esempio:

```yaml
reports:
  wwe_raw:
    enabled: true
    company: WWE
    category: WWE
    editorial_category: Editoriali
    show_name: WWE Raw
    expected_day_after: Tuesday
    publish_after: "06:30"
    preferred_source: ringsidenews
    fallback_source: wrestlinginc
    wait_for_preferred_until: "08:30"
    fallback_after: "08:30"
    title_template: "WWE Raw del {date_it} - risultati e momenti salienti"
```

### Fonte preferita

Per i report con struttura live/social migliore, la fonte preferita deve essere configurabile.

Regola proposta:

```text
06:30-08:30:
    aspetta Ringside se previsto come preferred_source

dopo 08:30:
    se Ringside non c'e' ma WrestlingInc c'e':
        usa WrestlingInc

dopo 10:00:
    se nessuna fonte valida:
        manual review / alert
```

Le fonti non competono tra loro come news. Sono fonti alternative dello stesso report programmato.

### Titolo report

Il titolo dei report e' deterministico e non passa dall'AI.

Esempi:

```text
WWE Raw del 25 maggio 2026 - risultati e momenti salienti
WWE SmackDown del 29 maggio 2026 - risultati e momenti salienti
WWE NXT del 26 maggio 2026 - risultati e momenti salienti
AEW Dynamite del 27 maggio 2026 - risultati e momenti salienti
AEW Collision del 30 maggio 2026 - risultati e momenti salienti
AEW Double or Nothing 2026 - risultati e momenti salienti
WWE Clash in Italy 2026 - risultati e momenti salienti
```

Funzione unica desiderata:

```python
def build_report_title(report_config, show_date):
    ...
```

Non devono esistere piu' hard-title fix multipli stratificati.

### Categorie report

Le categorie attuali non vanno cambiate. I report aggiungono una doppia categoria:

```text
Report WWE  -> Editoriali + WWE
Report NXT  -> Editoriali + NXT
Report AEW  -> Editoriali + AEW
Report TNA  -> Editoriali + TNA
Report World/altro -> Editoriali + World
```

NXT e' categoria autonoma.

### Stato report

I report devono avere stato separato:

```json
{
  "wwe_raw_2026_05_25": {
    "status": "published",
    "source": "ringsidenews",
    "source_url": "...",
    "published_at": "...",
    "wp_post_id": 1234
  }
}
```

Stati possibili:

```text
waiting_for_time
waiting_for_preferred_source
fallback_allowed
ready_to_publish
published
manual_review
failed_technical
```

---

## News pipeline

Le news sono contenuti selezionati e devono competere tra loro per il pacing del sito.

### Obiettivo dello scoring news

Lo scoring non deve decidere l'identita' del contenuto. Deve decidere l'ordine delle news.

Domanda principale:

```text
Tra le news disponibili, quali 3 pubblico adesso?
```

Domanda secondaria:

```text
Questa news aggiunge qualcosa rispetto a cio' che abbiamo gia' pubblicato?
```

### Classi decisionali

Preferire classi leggibili al posto di raffinamenti numerici multipli:

```text
must_publish
publish_if_space
soft_pool
skip
manual_review
```

Un punteggio puo' esistere, ma deve essere calcolato una sola volta.

Esempio:

```text
85+   must_publish
70-84 publish_if_space
55-69 soft_pool
<55   skip
```

### Nessun raffinamento v71

La v92 non deve portare il sistema di raffinamento successivo v71.

Da eliminare:

```text
score iniziale -> score raffinato -> cap legacy -> bypass -> floor registry -> nuova decisione
```

Lo score news deve essere stabile e motivato.

### Story core

Ogni news deve essere associata a un core semantico stabile.

Esempio:

```json
{
  "story_core": "aleister-black-wwe-release-2026-05",
  "entities": ["Aleister Black", "WWE"],
  "event_type": "release",
  "story_phase": "initial_report"
}
```

### Story phase

Fasi possibili:

```text
initial_report
official_confirmation
details
direct_quote
backstage_context
business_impact
future_destination
reaction
opinion
minor_repeat
duplicate
```

Esempio Aleister Black:

```text
Aleister Black licenziato -> initial_report -> must_publish
Dettagli sul licenziamento -> details -> publish_if_space
Dichiarazione diretta -> direct_quote -> publish_if_space
Reazione podcast generica -> opinion -> skip/soft_pool
Stessa notizia da altra fonte -> duplicate -> skip
```

### Valutazione semantica

L'AI analysis deve produrre una scheda strutturata, non uno scoring opaco.

Esempio:

```json
{
  "entities": ["Aleister Black", "WWE"],
  "companies": ["WWE"],
  "story_core": "aleister-black-wwe-release-2026-05",
  "event_type": "release",
  "story_phase": "details",
  "new_information": [
    "dettaglio nuovo 1",
    "dettaglio nuovo 2"
  ],
  "is_duplicate": false,
  "adds_new_value": true,
  "source_strength": "medium",
  "publish_recommendation": "publish_if_space"
}
```

### Confronto con pubblicato

Per ogni story core, lo stato deve conservare:

```json
{
  "story_core": "aleister-black-wwe-release-2026-05",
  "published_items": [
    {
      "phase": "initial_report",
      "facts": ["licenziamento", "data", "compagnia"],
      "url": "...",
      "published_at": "..."
    }
  ],
  "covered_facts": ["licenziamento", "data", "compagnia"]
}
```

La nuova news deve essere valutata sulla base dei fatti nuovi.

---

## Soft pool

Il soft pool va mantenuto, ma solo per le news.

Funzione:

```text
news valida ma non urgente ora
```

Regole:

- non contiene report;
- contiene news valide ma fuori dalle prime 3;
- decade se arriva una news migliore sullo stesso story_core;
- decade dopo TTL configurabile;
- puo' riempire slot se non ci sono news nuove migliori.

Esempio:

```text
Booker T commenta licenziamento Aleister Black -> soft_pool
Aleister Black rompe il silenzio -> publish
Booker T commenta -> scade o resta basso
```

---

## Spoiler policy

La spoiler policy deve dipendere dallo stato report.

Per ogni show/evento:

```text
report_published = true/false
```

Regola:

```text
se report non pubblicato:
    news post-show con outcome -> [SPOILER]

se report pubblicato:
    news post-show -> niente [SPOILER]
```

La decisione spoiler non deve dipendere solo da euristiche sparse su titolo/URL.

---

## Catena di traduzione da salvare

Le chain di traduzione sono considerate componenti funzionanti e da mantenere.

Da salvare:

```text
translate_normal
translate_medium
translate_report
postedit
protezione oEmbed
traduzione strutturata a blocchi
preservazione immagini/embed
fallback/cooldown modelli
```

La traduzione non decide cosa pubblicare. Riceve un job gia' deciso.

News:

```text
editorial_analysis -> translate_normal/medium -> postedit -> title AI -> publish
```

Report:

```text
extract_blocks -> translate_report -> postedit_report -> deterministic_title -> publish_report
```

### Titoli

News:

```text
titolo scritto da AI
```

Report:

```text
titolo deterministico
```

Questa distinzione e' obbligatoria.

---

## Categorie

Le categorie attuali rimangono.

Non cambiare mapping news esistente salvo bug espliciti.

Unica estensione richiesta:

```text
Report WWE -> Editoriali + WWE
Report NXT -> Editoriali + NXT
Report AEW -> Editoriali + AEW
Report TNA -> Editoriali + TNA
Report World -> Editoriali + World
```

---

## Componenti da recuperare dal bot attuale

Da recuperare, se isolabili:

```text
health check WordPress
publish WordPress create/draft/publish
upload featured image
upload immagini inline
scraping base articolo
estrazione blocchi ordinati
gestione embed Ringside
traduzione strutturata a blocchi
post-edit con oEmbed protetti
processed_urls
published_html_review
artifact bundle
cron GitHub Actions
soft pool concettuale
```

---

## Componenti da non portare nella v92

Da eliminare o riscrivere integralmente:

```text
report dentro news candidate queue
scoring applicato ai report
raffinamento score v71
event_key condivise e generiche tra report e news
title hardcode stratificati
repair v81 libero su HTML finale
wrapper multipli su process_candidate_item
patch chain infinita v91.x
core/event mapping aggressivo
report dedupe via news history
```

---

## Struttura proposta repository

```text
bot.py
config/
  reports.yml
  feeds.yml
  categories.yml
state/
  processed_urls.json
  report_status.json
  pending_reports.json
  pending_news.json
  story_cores.json
  soft_pool.json
modules/
  wp_client.py
  scraper.py
  extractor.py
  translator.py
  media.py
  article_workshop.py
  report_pipeline.py
  news_pipeline.py
  scoring.py
  story_core.py
  soft_pool.py
  logger.py
```

`main` deve essere leggibile:

```python
def main():
    wp_ok = wp.health_check()
    run_report_pipeline(wp_ok)
    run_news_pipeline(wp_ok, max_news=3)
    save_state()
```

---

## Roadmap proposta

### v92.0 - Report pipeline pulita

Obiettivo:

```text
pubblicare report programmati senza passare dalla news pipeline
```

Include:

- registry report;
- scheduler report;
- fonte preferita/fallback;
- titolo deterministico;
- categorie Editoriali + compagnia;
- report_status;
- publish report;
- budget separato.

### v92.1 - News pipeline pulita

Obiettivo:

```text
pubblicare max 3 news con scoring semplice e titolo AI
```

Include:

- feed scan;
- filtro listicle/preview/spazzatura;
- AI semantic analysis strutturata;
- story_core;
- scoring unico;
- publish max 3;
- categorie attuali;
- titolo AI.

### v92.2 - Soft pool e pacing

Obiettivo:

```text
gestire troppe news senza affollare il sito
```

Include:

- soft_pool news;
- TTL;
- dedupe con story_core;
- scadenza per news superate;
- riempimento slot.

### v92.3 - Spoiler policy basata su report_status

Obiettivo:

```text
spoiler coerente con pubblicazione report
```

Include:

- report_status lookup;
- spoiler prima del report;
- niente spoiler dopo report;
- regole show/evento.

---

## Frase guida

```text
Il report nasce report, resta report, esce report.
La news nasce news, compete con altre news, esce solo se aggiunge valore.
```
