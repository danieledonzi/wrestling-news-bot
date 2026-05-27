# OpenWrestlingTV v92 - News Scoring Architecture

## Stato del documento

Questo documento cristallizza le decisioni architetturali per la pipeline news v92 di OpenWrestlingTV.

La pipeline report resta separata e non deve essere modificata da queste regole.

## Obiettivo

La pipeline news deve scegliere quali articoli pubblicare senza usare limiti rigidi per fonte o personaggio.

Non devono esistere regole del tipo:

- massimo 1 news su Cody Rhodes per run;
- massimo 2 news da Ringside News per run;
- massimo 1 news per categoria.

In giornate eccezionali possono uscire più news sullo stesso soggetto o dalla stessa fonte, se il valore editoriale lo giustifica.

La selezione deve avvenire tramite scoring editoriale progressivo.

## Principio guida

La pipeline deve separare tre concetti:

1. **Non rivalutare mai più**: contenuti da hard skip.
2. **Candidabile ma non prioritario ora**: contenuti da soft pool.
3. **Pubblicare subito**: hard news.

Lo scoring non deve solo ordinare una lista. Deve determinare il destino editoriale di ogni item.

## Flusso generale

```text
raccolta feed
→ hard skip deterministico
→ Fase A: pre-score locale
→ Fase B: analisi editoriale leggera
→ Fase C: decisione finale hard news / soft pool
→ catena di montaggio news
```

## 0. Raccolta feed

La raccolta feed produce una lista grezza di item con almeno:

```json
{
  "source": "ringsidenews",
  "title": "...",
  "url": "...",
  "summary": "...",
  "published": "..."
}
```

In questa fase non si decide la pubblicazione.

Si normalizzano solo i dati.

## 1. Hard skip deterministico

Questa fase elimina gli item che non devono entrare nello scoring.

Sono hard skip deterministici:

- URL già pubblicato;
- URL già hard-skippato;
- URL duplicato identico nella stessa run;
- URL assente o non valido;
- titolo assente;
- item che appartiene chiaramente alla pipeline report;
- recap/results/report show già gestito dalla pipeline report;
- preview scaduta chiaramente riconoscibile;
- contenuto evidentemente non wrestling;
- contenuto tecnico del sito/fonte non editoriale.

Gli hard skip deterministici vengono salvati in:

```text
state/news_hard_skips.json
```

Esempio:

```json
{
  "https://example.com/article": {
    "reason": "report_like",
    "title": "WWE Raw Results 5/25...",
    "source": "wrestlinginc",
    "created_at": "2026-05-27T17:37:44"
  }
}
```

### Regola importante

Non tutto ciò che non viene pubblicato è hard skip.

Una news soft non pubblicata deve poter entrare nel soft pool, non sparire definitivamente.

## 2. Fase A - Pre-score locale

La Fase A è economica e non usa Gemini.

Serve a decidere se vale la pena spendere token nella Fase B.

Input usato:

- titolo;
- summary RSS;
- fonte;
- data feed;
- URL;
- keyword forti;
- categoria probabile;
- segnali di tipo articolo.

Output possibile:

```text
A-hard-skip
A-candidate
A-low-soft-candidate
```

### Scala suggerita

```text
0-14   → hard skip locale
15-29  → candidato debole / possibile soft basso, normalmente non mandato a Gemini salvo run povera
30+    → candidato da mandare in Fase B
```

Questa scala è indicativa e può essere tarata.

### A-hard-skip tipici

- sport crossover debole;
- listicle generico;
- curiosità marginale;
- contenuto evergreen non urgente;
- articolo di opinione senza notizia;
- reazione social debole;
- preview scaduta;
- gossip non operativo.

### Attenzione

La Fase A non deve pubblicare.

La Fase A decide solo se un item merita o meno analisi editoriale.

## 3. Fase B - Analisi editoriale leggera

La Fase B usa Gemini, ma con prompt breve e output strutturato.

Serve a capire la natura editoriale reale dell'articolo.

Output richiesto:

```json
{
  "article_type": "hard_news | soft_news | rumor | opinion | report_like | low_value",
  "editorial_score": 0,
  "priority": "hard | soft | skip",
  "category": "WWE | AEW | NXT | TNA | World | Business",
  "main_entities": ["Cody Rhodes", "The Rock"],
  "story_core": "cody-rhodes-the-rock-soul-storyline",
  "news_action": "addresses_future_storyline",
  "freshness": "fresh | stale | evergreen",
  "reason": "..."
}
```

## 4. Criteri Fase B

### Hard news

Una news può essere hard news quando contiene uno sviluppo concreto, nuovo e rilevante.

Esempi:

- ritorno importante;
- debutto importante;
- firma o rinnovo importante;
- licenziamento;
- infortunio rilevante;
- cambio titolo;
- cambio creativo sostanziale;
- cambio proprietà;
- acquisizione;
- accordo TV;
- causa legale;
- sospensione;
- cancellazione evento;
- annuncio ufficiale importante;
- aggiornamento operativo su storyline principale;
- notizia business rilevante.

Range suggerito:

```text
70-100 → hard news
```

### Soft news

Una news è soft quando ha valore informativo o di intrattenimento, ma non è prioritaria.

Esempi:

- dichiarazione da intervista;
- commento da podcast;
- curiosità backstage;
- possibilità vaga;
- ricordo personale;
- dettaglio secondario;
- update non decisivo;
- reazione social interessante ma non determinante.

Range suggerito:

```text
40-69 → soft pool
```

### Hard skip da Fase B

La Fase B può produrre hard skip quando, dopo analisi, l'articolo non ha valore editoriale per il sito.

Esempi:

- recap/report/results;
- opinion puro;
- listicle leggero;
- duplicato sostanziale già pubblicato;
- contenuto non wrestling;
- contenuto obsoleto;
- follow-up superato da notizia più nuova;
- rumor troppo vago;
- articolo costruito su una frase irrilevante.

Range suggerito:

```text
0-39 → skip
```

## 5. Fase C - Decisione finale di pubblicazione

La Fase C non ricalcola il senso editoriale.

Prende le classificazioni della Fase B e decide cosa pubblicare nella run.

Si costruiscono due liste:

```text
hard_news = item con priority hard
soft_pool = item con priority soft
```

Entrambe ordinate per:

```text
editorial_score desc
freshness desc
source reliability
```

### Regola di pubblicazione

Con `MAX_NEWS_PER_RUN = 3`:

```text
se hard_news >= 3:
    pubblica prime 3 hard_news

se hard_news == 2:
    pubblica 2 hard_news + prima soft_pool

se hard_news == 1:
    pubblica 1 hard_news + prime 2 soft_pool

se hard_news == 0:
    pubblica prime 3 soft_pool
```

Questa regola permette di riempire il sito anche in giornate povere, ma protegge le giornate forti.

Se ci sono almeno 3 hard news, le soft news non competono.

## 6. Soft pool persistente

Le soft news candidate ma non pubblicate possono sopravvivere alla run.

Devono essere salvate in:

```text
state/news_soft_pool.json
```

Esempio:

```json
{
  "https://example.com/article": {
    "title": "...",
    "source": "ringsidenews",
    "score": 61,
    "category": "WWE",
    "story_core": "cody-rhodes-the-rock-storyline",
    "first_seen": "2026-05-27T17:37:44",
    "last_seen": "2026-05-27T17:37:44",
    "expires_at": "2026-05-27T23:37:44"
  }
}
```

### TTL suggeriti

```text
soft news standard       → 6 ore
soft post-show           → 3 ore
intervista/evergreen     → 12 ore
hard news non pubblicata → 12-24 ore, caso raro
```

Quando una soft news scade, viene rimossa dalla coda attiva.

Non deve necessariamente diventare hard skip permanente.

## 7. Dedupe semantico morbido

Non devono esistere blocchi rigidi per soggetto o fonte.

Però il sistema deve riconoscere quando due item sono sostanzialmente simili.

Fase B deve produrre:

```text
main_entities
story_core
news_action
```

Esempio:

```text
Cody Rhodes reveals concussion protocol after Randy Orton punt
story_core = cody-rhodes-randy-orton-concussion-protocol
news_action = reveals_injury_consequence

Cody Rhodes addresses whether The Rock still wants his soul
story_core = cody-rhodes-the-rock-soul-storyline
news_action = addresses_future_storyline
```

Questi due item condividono Cody Rhodes, ma non sono duplicati.

Al contrario:

```text
Cody Rhodes says The Rock may still want his soul
Cody Rhodes comments again on The Rock soul storyline
```

sono probabilmente duplicati o quasi duplicati.

### Regola

Il dedupe semantico non deve bloccare automaticamente.

Deve applicare una penalità o favorire la news con score più alto, salvo eventi eccezionali.

## 8. Nessun limite rigido per fonte o personaggio

Non usare regole come:

```text
max 1 Cody Rhodes per run
max 2 Ringside per run
max 1 WWE per run
```

In caso di eventi eccezionali, questi limiti farebbero perdere notizie rilevanti.

La varietà deve essere effetto dello scoring, non di un cap arbitrario.

## 9. Relazione con la catena di montaggio

Solo gli item scelti dalla Fase C entrano nella catena di montaggio:

```text
scrape articolo
→ traduzione/adattamento
→ titolo italiano
→ HTML cleanup
→ featured image
→ categoria
→ fonte
→ pubblicazione WordPress
```

Gli item non scelti ma soft restano nel soft pool.

Gli item hard skip vengono salvati con motivo.

## 10. Priorità implementativa

Implementare in questo ordine:

1. Pulizia HTML finale news, in particolare blockquote fuori dai paragrafi.
2. Stato `news_hard_skips.json`.
3. Stato `news_soft_pool.json` con TTL.
4. Fase A locale più strutturata.
5. Fase B Gemini con JSON editoriale.
6. Fase C hard/soft decision.
7. Dedupe semantico morbido basato su `story_core`.

## Decisione cristallizzata

La pipeline news v92 deve essere basata su:

```text
pre-score locale
+ analisi editoriale leggera
+ hard news / soft pool
+ soft pool persistente
+ dedupe semantico morbido
```

Non deve essere basata su limiti rigidi di fonte, personaggio o categoria.
