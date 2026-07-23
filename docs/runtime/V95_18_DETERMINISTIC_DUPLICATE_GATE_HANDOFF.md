# OpenWrestlingTV — Architettura autorevole del controllo duplicati Menzo v95.18

**Stato:** specifica approvata da implementare  
**Repository:** `danieledonzi/wrestling-news-bot`  
**Branch di riferimento:** `main`  
**Data:** 23 luglio 2026  
**Sostituisce integralmente:** `V95_11_DUPLICATE_ARCHITECTURE_HANDOFF.md`

---

## 1. Scopo

Questo documento definisce l'architettura autorevole per il controllo dei duplicati nella newsroom OpenWrestlingTV.

Il principio fondamentale e' il seguente:

> Il controllo deterministico stabilisce se esiste un dubbio plausibile di duplicazione. Gemini decide soltanto i casi realmente sospetti o ambigui.

Gemini non deve essere usato come motore generale di confronto tra URL che non hanno elementi concreti per rappresentare la stessa notizia.

La cache serve a non ripetere uno stesso dubbio gia' arbitrato. Non deve essere usata per rendere economicamente tollerabile un universo di confronti generici che non avrebbero dovuto essere creati.

---

## 2. Ruoli degli agenti

### 2.1 Massy

Massy:

- raccoglie e normalizza i candidati;
- applica i propri controlli di ammissibilita';
- individua segnali deterministici utili;
- consegna a Menzo soltanto i candidati ancora azionabili.

Massy non decide il vincitore editoriale finale di un dubbio semantico.

### 2.2 Menzo

Menzo:

1. riceve i candidati azionabili;
2. costruisce i confronti potenzialmente utili;
3. applica il gate deterministico di sospetto;
4. autorizza direttamente i casi chiaramente distinti;
5. risolve deterministicamente soltanto i duplicati esatti;
6. chiama Gemini esclusivamente sopra la soglia di sospetto;
7. applica la decisione semantica finale;
8. ripete lo stesso processo contro le pubblicazioni realmente riuscite nelle ultime 12 ore.

### 2.3 Gemini

Gemini e' il decisore finale dei soli casi sospetti ammessi dal gate deterministico.

Gemini non deve ricevere:

- l'intero insieme dei candidati se non esistono archi sospetti tra loro;
- l'intera cronologia recente per ogni candidato;
- coppie sotto soglia;
- coppie gia' arbitrate e immutate;
- coppie che condividono soltanto federazione, wrestler, show o argomento generale.

### 2.4 Publisher

Publisher:

- non effettua deduplicazione semantica;
- non chiama Gemini;
- registra soltanto pubblicazioni realmente riuscite;
- fornisce la cronologia autorevole usata dal controllo recent-history.

---

## 3. Flusso runtime autorevole

```text
Massy candidati azionabili
    -> Menzo classificazione e regole editoriali non duplicate
    -> same-run deterministic suspicion gate
        -> exact duplicate: risoluzione deterministica
        -> score sotto soglia: entrambi autorizzati senza Gemini
        -> score sopra soglia: cache, poi Gemini se necessario
    -> sopravvissuti same-run
    -> caricamento sole pubblicazioni riuscite delle ultime 12 ore
    -> recent-history deterministic suspicion gate
        -> exact duplicate: blocco deterministico
        -> score sotto soglia: candidato autorizzato senza Gemini
        -> score sopra soglia: cache, poi Gemini se necessario
    -> budget editoriale
    -> cap e capacity buffer
    -> autorizzazione finale Menzo
    -> Bob, Alfred, Publisher
```

I controlli duplicati devono avvenire prima di budget, cap e capacity buffer, in modo che il budget operi soltanto sui candidati realmente distinti o sugli aggiornamenti materiali autorizzati.

---

## 4. Universo dei confronti

### 4.1 Same-run

L'universo iniziale contiene soltanto i candidati azionabili ricevuti da Massy e rimasti in `selected` o `pending` dopo le regole editoriali non relative ai duplicati.

Per `N` candidati e' possibile generare internamente fino a `N * (N - 1) / 2` coppie, ma Gemini non deve ricevere tutte le coppie.

Ogni coppia passa prima dallo scorer deterministico.

### 4.2 Recent-history

Dopo il same-run si considerano soltanto i candidati sopravvissuti.

La cronologia deve contenere esclusivamente articoli:

- pubblicati con successo da Publisher;
- con timestamp di pubblicazione reale entro le ultime 12 ore;
- con URL sorgente canonico valorizzato;
- con URL WordPress valorizzato quando disponibile;
- deduplicati per URL sorgente canonico.

Non sono fonti autorevoli per questo gate:

- `master_log.jsonl` generico;
- story footprints;
- generalized fingerprints;
- candidati selezionati ma non pubblicati;
- articoli falliti, pending, skipped o dry-run;
- artefatti intermedi di Menzo, Bob o Alfred.

La fonte primaria e' `state/newsroom/publisher_history.json`, filtrata sui record di pubblicazione riuscita.

---

## 5. Duplicati esatti

Prima dello scoring semantico vengono gestiti i casi certi.

### 5.1 Stesso URL sorgente canonico

```text
canonical_source_url(A) == canonical_source_url(B)
```

- same-run: scegliere il record piu' ricco e autorizzare un solo rappresentante;
- recent-history: bloccare il nuovo candidato come gia' pubblicato;
- nessuna chiamata Gemini.

### 5.2 Stesso content hash materiale

```text
material_content_hash(A) == material_content_hash(B)
```

Stesso trattamento dello stesso URL.

Il content hash deve ignorare rumore non semantico e includere almeno titolo, sommario o estratto significativo e fatto centrale disponibile.

---

## 6. Scorer deterministico di sospetto

### 6.1 Obiettivo

Lo scorer non decide se due articoli sono duplicati. Decide soltanto se e' plausibile che parlino della stessa notizia e se il dubbio merita l'arbitraggio Gemini.

Il punteggio e' compreso tra `0.0` e `1.0`.

### 6.2 Soglia unica

La stessa soglia deve essere usata per same-run e recent-history.

Configurazione autorevole:

```text
MENZO_DUPLICATE_SUSPECT_THRESHOLD=0.55
```

Per compatibilita' temporanea, in assenza della nuova variabile e' consentito leggere il precedente valore `MASSY_DUPLICATE_SUSPECT_THRESHOLD`, con fallback finale `0.55`.

La soglia e la versione dello scorer fanno parte del contract fingerprint della cache.

### 6.3 Componenti del punteggio

Ogni componente restituisce un valore tra `0.0` e `1.0`.

```text
entity_subject_score       peso 0.30
central_fact_action_score  peso 0.25
event_show_match_score     peso 0.20
promotion_score            peso 0.10
temporal_context_score     peso 0.05
title_slug_lexical_score   peso 0.10
```

Formula base:

```text
score =
    0.30 * entity_subject_score
  + 0.25 * central_fact_action_score
  + 0.20 * event_show_match_score
  + 0.10 * promotion_score
  + 0.05 * temporal_context_score
  + 0.10 * title_slug_lexical_score
```

Il risultato finale deve essere limitato all'intervallo `[0.0, 1.0]`.

### 6.4 Soggetto ed entita'

Devono essere considerate almeno:

- wrestler;
- stable o tag team;
- dirigente, promoter o altra persona centrale;
- cintura o titolo specifico;
- match specifico;
- organizzazione coinvolta quando e' il soggetto reale della notizia.

La sola presenza di termini generici come WWE, AEW, Raw o SmackDown non deve produrre un punteggio elevato.

### 6.5 Fatto centrale o azione

Devono essere normalizzate categorie fattuali come:

- infortunio, operazione, medical clearance;
- firma, rinnovo, scadenza, rilascio;
- ritorno, debutto, assenza;
- annuncio o modifica di match;
- vittoria o cambio titolo;
- sospensione o questione legale;
- turn heel o face;
- dichiarazione o reazione a uno specifico fatto;
- cancellazione, rinvio o cambio di sede/data;
- rumor, conferma ufficiale, smentita.

Due articoli sullo stesso wrestler ma con azioni centrali differenti devono normalmente restare sotto soglia.

### 6.6 Evento, show, match e contesto

Devono essere considerate:

- promozione;
- show;
- evento premium o pay-per-view;
- data dell'evento;
- match e avversari;
- segmento o angle specifico.

Condividere soltanto lo stesso evento non basta per creare un sospetto forte se soggetti e fatto centrale sono differenti.

### 6.7 Sovrapposizione titolo e slug

La similarita' lessicale deve:

- usare parole significative;
- rimuovere stopword e termini generici;
- considerare titolo e slug canonico;
- non dominare il punteggio;
- aiutare a riconoscere formulazioni diverse dello stesso fatto.

### 6.8 Penalita' e incompatibilita'

Sono previste penalita' deterministiche, senza trasformarle in decisioni definitive:

```text
-0.20  show/eventi esplicitamente incompatibili
-0.15  promozioni incompatibili senza soggetto crossover
-0.15  fatti centrali esplicitamente diversi
-0.10  finestre temporali incompatibili per eventi distinti
```

Il punteggio finale resta limitato a `[0.0, 1.0]`.

### 6.9 Regola di ammissione al dubbio

```text
score < threshold
    -> chiaramente distinto per il gate
    -> nessuna chiamata Gemini
    -> autorizzazione a proseguire

score >= threshold
    -> vero sospetto di duplicazione
    -> controllo cache
    -> Gemini soltanto se la decisione non e' gia' disponibile
```

Il deterministico non deve scartare come duplicato una coppia soltanto perche' supera la soglia.

---

## 7. Same-run: costruzione dei componenti sospetti

### 7.1 Grafo di sospetto

Ogni candidato e' un nodo.

Si crea un arco soltanto quando:

```text
score(A, B) >= threshold
```

I nodi senza archi non vengono inviati a Gemini.

### 7.2 Componenti connesse

Gemini riceve una richiesta per ciascuna componente connessa sospetta.

Esempio:

```text
A-B = 0.82
A-C = 0.18
B-C = 0.21
D-E = 0.67
```

Richieste Gemini:

```text
[A, B]
[D, E]
```

C non viene inviato.

Una componente deve contenere soltanto candidati collegati da almeno un arco sospetto. Non deve essere estesa con tutti gli altri survivor cached.

### 7.3 Output Gemini same-run

Schema:

```json
{
  "duplicate_groups": [
    {
      "keep_id": "c0",
      "discard_ids": ["c1"],
      "reason": "same central fact"
    }
  ]
}
```

Regole:

- Gemini puo' dichiarare duplicati soltanto candidati presenti nella componente;
- candidati omessi restano distinti;
- gruppi disgiunti;
- un solo rappresentante autorizzato per gruppo;
- nessun candidato esterno alla componente puo' essere coinvolto.

---

## 8. Recent-history: confronto con pubblicazioni riuscite

### 8.1 Stesso scorer, stessa soglia

Ogni sopravvissuto same-run viene confrontato deterministicamente con ogni pubblicazione riuscita delle ultime 12 ore.

Si usa lo stesso scorer e la stessa soglia del same-run.

### 8.2 Creazione delle richieste

Per un candidato corrente vengono raccolte soltanto le pubblicazioni con:

```text
score(current, published) >= threshold
```

Se non esistono pubblicazioni sospette:

- nessuna chiamata Gemini;
- candidato autorizzato a proseguire.

Se esiste una o piu' pubblicazioni sospette:

- Gemini riceve il candidato e soltanto quelle pubblicazioni;
- non riceve la history completa;
- puo' scegliere il match rilevante.

### 8.3 Output Gemini recent-history

Decisioni ammesse:

```text
DUPLICATE
MATERIAL_UPDATE
NO_MATCH
```

Schema consigliato:

```json
{
  "decision": "DUPLICATE|MATERIAL_UPDATE|NO_MATCH",
  "published_id": "p0",
  "new_fact": "",
  "reason": ""
}
```

`published_id` e' obbligatorio per `DUPLICATE` e `MATERIAL_UPDATE`.

### 8.4 Material update

Una `MATERIAL_UPDATE` e' valida soltanto quando contiene un fatto nuovo concreto, grounded nel candidato e assente nel pubblicato.

Non sono aggiornamenti materiali:

- altra fonte;
- articolo piu' lungo;
- nuove citazioni;
- contesto aggiuntivo;
- media aggiuntivi;
- formulazione diversa;
- conferma generica senza evoluzione fattuale.

---

## 9. Cache incrementale

### 9.1 Unita' di cache

La cache deve rappresentare un dubbio reale, non un batch generico.

Unita' minima:

```text
same-run: coppia o componente sospetta
recent-history: candidato + insieme delle sole pubblicazioni sospette
```

### 9.2 Chiave e invalidazione

La chiave deve includere almeno:

- scope;
- identita' canoniche;
- material hash dei record;
- versione scorer;
- soglia;
- versione prompt;
- contract fingerprint.

Una decisione e' riutilizzabile soltanto se tutti gli elementi materiali sono immutati.

### 9.3 Rollout

L'introduzione del gate deterministico deve cambiare il contract fingerprint. Le strutture cache incompatibili devono essere ignorate o ricostruite atomicamente, senza usare decisioni parziali.

La cache v95.17 puo' essere riusata come infrastruttura, ma non deve conservare il concetto di `reviewed_history` universale contro ogni record recente. Deve memorizzare soltanto dubbi sopra soglia effettivamente arbitrati.

---

## 10. Fail-closed

Il fail-closed deve essere limitato ai soli candidati realmente coinvolti in un sospetto sopra soglia.

Non e' consentito bloccare un candidato chiaramente distinto perche' una chiamata Gemini relativa a un'altra componente e' fallita.

### Same-run

- fallimento su una componente: solo quella componente viene gestita fail-closed;
- candidati senza archi sospetti restano autorizzati;
- componenti indipendenti restano indipendenti.

### Recent-history

- fallimento sul candidato sospetto: solo quel candidato viene sospeso o bloccato secondo la policy esistente;
- candidati senza pubblicazioni sopra soglia non sono coinvolti.

---

## 11. Diagnostica obbligatoria

Per ogni run devono essere registrati almeno:

```text
same_run_pairs_theoretical
same_run_exact_duplicates
same_run_pairs_below_threshold
same_run_pairs_above_threshold
same_run_suspicious_components
same_run_candidates_sent_to_gemini

recent_history_candidates
recent_history_publications_12h
recent_history_pairs_theoretical
recent_history_exact_duplicates
recent_history_pairs_below_threshold
recent_history_pairs_above_threshold
recent_history_candidates_sent_to_gemini
recent_history_publications_sent_to_gemini

duplicate_cache_hits
duplicate_cache_misses
gemini_duplicate_calls_planned
gemini_duplicate_calls_executed
gemini_duplicate_calls_avoided
gemini_duplicate_input_tokens
gemini_duplicate_output_tokens
gemini_duplicate_estimated_cost
```

Per audit deve essere possibile ricostruire, per ogni coppia sopra soglia:

- identita' dei record;
- score totale;
- score per componente;
- ragioni deterministiche;
- decisione cache o Gemini;
- esito editoriale finale.

I record sotto soglia possono essere conservati in forma aggregata; non e' necessario serializzare tutte le coppie nella diagnostica ordinaria.

---

## 12. Non regressioni

La modifica non deve cambiare:

- classificazione editoriale di base;
- scoring nativo delle notizie;
- budget dinamico;
- cap e capacity buffer;
- ordine Bob, Alfred, Publisher;
- modello Gemini attivo, salvo configurazione separata;
- regole di `MATERIAL_UPDATE`;
- propagazione dei metadati Menzo;
- atomicita' della persistenza;
- fail-closed finale del Publisher per metadati incoerenti.

Non devono essere riattivate vecchie autorita' bloccanti basate su footprint o fingerprint.

Footprint, fingerprint, entita', azioni, eventi e slug possono alimentare lo scorer di sospetto, ma non decidere autonomamente un duplicato non esatto.

---

## 13. Test di accettazione

### 13.1 Same-run chiaramente distinto

Tre candidati su wrestler e fatti differenti.

Atteso:

```text
pairs_theoretical = 3
pairs_above_threshold = 0
gemini_duplicate_calls_executed = 0
tutti autorizzati
```

### 13.2 Same-run sospetto reale

Due fonti riportano lo stesso infortunio; terzo articolo sullo stesso wrestler ma su un contratto.

Atteso:

```text
solo la coppia infortunio sopra soglia
Gemini vede soltanto i due articoli sospetti
articolo contratto non inviato
```

### 13.3 Stesso soggetto, fatto differente

Due articoli sullo stesso wrestler, uno su un match e uno su una dichiarazione personale.

Atteso:

```text
score sotto soglia
nessuna chiamata Gemini
entrambi autorizzati
```

### 13.4 Recent-history senza sospetti

Quattro pubblicazioni recenti ma nessuna con soggetto/fatto/evento compatibile.

Atteso:

```text
pairs_theoretical = 4
pairs_above_threshold = 0
gemini_duplicate_calls_executed = 0
```

### 13.5 Recent-history duplicato

Candidato e pubblicato riportano lo stesso annuncio da fonti diverse.

Atteso:

```text
score sopra soglia
Gemini chiamato una volta o cache hit
DUPLICATE
candidato bloccato
```

### 13.6 Recent-history aggiornamento materiale

Pubblicato: rumor. Candidato: conferma ufficiale con data e match definiti.

Atteso:

```text
score sopra soglia
Gemini chiamato
MATERIAL_UPDATE
new_fact grounded
candidato autorizzato
```

### 13.7 Cache

Stessa coppia sospetta e stessi material hash in una run successiva.

Atteso:

```text
cache hit
nessuna nuova chiamata Gemini
```

### 13.8 Ricambio della history

Nuova pubblicazione sotto soglia per tutti i candidati esistenti.

Atteso:

```text
nessuna nuova chiamata Gemini
nessuna rivalutazione dei dubbi precedenti
```

### 13.9 Fallimento Gemini isolato

Due componenti sospette indipendenti; Gemini fallisce su una sola.

Atteso:

```text
fail-closed limitato alla componente fallita
altra componente e candidati distinti non bloccati
```

---

## 14. Piano di implementazione

1. introdurre lo scorer deterministico versionato;
2. usare una sola soglia configurabile per same-run e recent-history;
3. sostituire il batch same-run globale con componenti sospette;
4. sostituire la frontier recent-history universale con soli match sopra soglia;
5. caricare esclusivamente `publisher_history.json` con pubblicazioni riuscite nelle ultime 12 ore;
6. mantenere Gemini come decisore finale sopra soglia;
7. adattare la cache ai soli dubbi sospetti;
8. cambiare il contract fingerprint;
9. aggiungere diagnostica e test focali;
10. eseguire suite completa, `py_compile` e `git diff --check`;
11. rilasciare tramite branch e pull request, senza modificare direttamente `main`;
12. verificare in produzione chiamate, token e percentuale di coppie sotto/sopra soglia.

---

## 15. Criterio finale

Una run corretta non si misura dal fatto che Gemini abbia confrontato tutto e non abbia trovato duplicati.

Si misura dal fatto che:

- il deterministico abbia escluso dal dubbio le coppie chiaramente impossibili;
- Gemini abbia visto soltanto casi concretamente sospetti;
- una stessa coppia sospetta non sia stata arbitrata due volte senza modifiche materiali;
- le pubblicazioni recenti usate nel confronto siano soltanto quelle realmente riuscite;
- nessun duplicato plausibile sopra soglia sia stato autorizzato senza decisione cache o Gemini.
