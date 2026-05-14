# Implementation notes v88.2 — editorial performance guards

## Contesto
La run v88.1 del 2026-05-14 20:12 ha mostrato una selezione complessivamente buona, ma con un costo eccessivo su articoli non prioritari.

Casi osservati:

- Ronda Rousey / Becky Lynch: scelta editoriale forte, ma traduzione lunga per repair anti-omissione.
- Fit For WrestleMania and the FIFA World Cup: articolo feature/OTHER non urgente, promosso troppo in alto e trattato come report lungo; ha consumato circa 90 secondi di traduzione e poi è stato scartato per alterazione dei numeri storici di WrestleMania.
- Tekashi 6ix9ine / WWE: pubblicabile come crossover/click traffic, ma non deve superare notizie wrestling più sostanziali.
- Fatal Influence: scelta accettabile, con warning non bloccante sulle quote.

## Obiettivi v88.2

1. Ridurre il costo delle run evitando traduzioni lunghe su feature non-news.
2. Non usare la pipeline `translate_report` per articoli OTHER/feature.
3. Proteggere i veri results/report completi: Raw, SmackDown, NXT, Dynamite, Collision, Impact, PPV/PLE results.
4. Cappare i contenuti celebrity/crossover sotto la soglia hard, salvo news reali di contratto, infortunio, titolo, ritorno o release.
5. Mantenere i suggerimenti v88.2 già previsti da Codex:
   - `gemini-3.1-flash-lite` resta modello valido.
   - `gemini-3-flash-preview` resta modello valido.
   - `gemini-3-flash` e `gemini-3.1-flash` restano ID non validi.
   - ogni chain deve avere fallback multipli.
   - `confirmed_published_reports.json` deve supportare sia schema storico sia schema compatibile `reports`.
   - i true-results già confermati non devono tornare in pending.
   - `published/`, `published_html_review/` e `logs/master_log.log` devono essere persistiti.

## Fix introdotti

### Cap OTHER/feature
Se l'analisi editoriale restituisce `OTHER`, o se il titolo/testo indica chiaramente un feature non-news, il punteggio viene cappato:

- default cap: 65
- cap più severo per feature con numeri storici di eventi tipo WrestleMania 28/29/32/35: 60

Questo evita casi come l'articolo sugli stadi WrestleMania/FIFA World Cup, che non è una notizia urgente e non deve usare la pipeline report.

### Guard pre-traduzione
Per feature/OTHER non-results, `process_candidate_item` può saltare il candidato prima di attivare traduzioni costose.

### Cap celebrity/crossover
Gli articoli celebrity/crossover sono ancora pubblicabili, ma cappati a 74 quando non sono news concrete di roster, contratto, infortunio, titolo o release.

### Workflow v88.2
Il workflow attivo ora:

- espone permessi espliciti `contents: write`, `pull-requests: write`, `issues: write`, `actions: read`;
- usa checkout con `fetch-depth: 0`;
- configura Git in uno step separato;
- applica v88.1 e v88.2 come patch runtime solo finché `bot.py` non viene consolidato nativamente;
- usa chain con `gemini-3.1-flash-lite`, `gemini-3-flash-preview`, `gemini-2.5-flash-lite`, `gemini-2.5-flash`.

## Log attesi

Durante la prossima run ci si aspetta:

```text
[BOOT v88.2] Editorial performance guards attivi
[SCORE v88.2] v88.2 cap OTHER/feature non-news ...
[SKIP v88.2] Feature/OTHER non-news sotto priorita hard ...
```

Per celebrity/crossover non hard-news:

```text
[SCORE v88.2] v88.2 cap celebrity/crossover ...
```

## Rischi residui

- Il patching runtime resta una soluzione transitoria. La fase successiva deve consolidare v88.1/v88.2 direttamente in `bot.py`.
- La detection feature/OTHER è conservativa ma può richiedere aggiustamenti se blocca un approfondimento desiderato.
- Le feature realmente strategiche potranno richiedere whitelist futura.

## Verifica prossima run

Controllare:

1. durata totale run;
2. assenza di `translate_report` su feature/OTHER;
3. qualità selezione dei 3 articoli pubblicati;
4. presenza di `published/*_final.html`;
5. aggiornamento di `logs/master_log.log`;
6. corretto upload artifact;
7. assenza di pending true-results già confermati.
