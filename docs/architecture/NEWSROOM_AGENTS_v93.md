# OpenWrestlingTV Virtual Newsroom - Descrizione agenti v93

## Jarvis - Tecnico e diagnostica WordPress

Jarvis controlla che l'ambiente operativo sia pronto prima che la redazione consumi risorse costose.

Responsabilita:

- raggiungibilita sito;
- DNS;
- homepage;
- REST API WordPress;
- endpoint post e media;
- autenticazione;
- tempi di risposta;
- eventuali timeout da GitHub Actions;
- possibilita concreta di pubblicare.

Jarvis puo bloccare lavori costosi. Non pubblica, non traduce e non decide priorita editoriali.

## Massy - La Sentinella

Massy guarda le fonti, raccoglie URL, normalizza i dati e prepara la board dei candidati.

Responsabilita:

- leggere feed RSS;
- raccogliere URL;
- normalizzare titolo, summary e data;
- eliminare URL gia visti;
- applicare skip economici;
- separare news candidate e report candidate;
- preparare la candidate board per Menzo e Simone.

Massy non traduce, non pubblica e non decide la linea editoriale finale.

## Simone - Reporter show/results

Simone e il reporter degli show.

Copertura settimanale:

- WWE Raw;
- WWE NXT;
- AEW Dynamite;
- TNA Impact;
- WWE SmackDown;
- AEW Collision.

Copertura special events:

- principali PLE/PPV WWE;
- principali PPV AEW;
- principali PPV ROH.

Regola fondamentale:

```text
I report non sono news.
```

I report non passano dallo scoring news, non competono con il numero massimo di news e non contano nel target 20-30 news al giorno.

Simone prepara il report per Bob, assegna titolo deterministico e categorie Editoriali + promotion/show. Non pubblica news normali.

## Menzo - Responsabile editoriale

Menzo e il responsabile editoriale della redazione automatica.

Responsabilita:

- ricevere candidate news da Massy;
- distinguere hard news, strategic discussion, standard useful, soft news e low value;
- decidere quante news lavorare nella finestra;
- rispettare il target 20-30 news al giorno, report esclusi;
- calcolare budget residuo in base alle run previste;
- evitare soft news pubblicate solo per riempire;
- mandare a Bob solo URL approvati.

Con poche finestre giornaliere, Menzo alza dinamicamente il numero di news per run.

## Bob - Traduttore

Bob traduce e adatta in italiano giornalistico naturale solo articoli approvati da Menzo o report approvati da Simone.

Regole:

- non riassumere quando serve traduzione completa;
- preservare fatti e citazioni;
- usare terminologia wrestling corretta;
- evitare calchi inglesi;
- evitare tono AI;
- non inventare contesto.

Esempi di guardrail:

- match non diventa partita;
- release non diventa rilascio;
- titoli ufficiali delle cinture non vanno tradotti;
- show e nomi propri mantengono casing corretto.

## Alfred - Correttore e manutenzione editoriale

Alfred controlla grammatica, refusi, terminologia wrestling, titoli e qualita finale.

Alfred puo lavorare pre-pubblicazione e post-pubblicazione, ma solo con modifiche locali, sicure e reversibili.

Puo correggere:

- rilascio WWE -> licenziamento WWE;
- partita -> match;
- ha collegato una spear -> ha messo a segno una spear;
- la marea e cambiata -> l'inerzia del match e cambiata;
- Wwe Raw -> WWE Raw;
- Smackdown -> SmackDown.

Alfred non aggiunge informazioni, non elimina fatti, non cambia citazioni e non riscrive interi articoli.

## Publisher - Pubblicazione WordPress

Publisher riceve pacchetti approvati da Alfred e pubblica su WordPress.

Responsabilita:

- creare draft;
- caricare featured image;
- caricare immagini interne quando previsto;
- assegnare categorie;
- validare il draft;
- pubblicare;
- restituire post ID e URL.

Publisher non sceglie notizie, non traduce e non corregge.

## Archivista - Log, metriche e memoria editoriale

Archivista registra cosa e successo, perche e successo e cosa va controllato dopo.

Responsabilita:

- salvare run summary;
- aggiornare history, skipped history e pending;
- aggiornare report status;
- registrare decisioni di Menzo;
- registrare correzioni di Alfred;
- registrare diagnostica Jarvis;
- produrre riepilogo giornaliero;
- distinguere news e report nel conteggio giornaliero.

Archivista non pubblica, non traduce, non sceglie notizie e non corregge articoli.

## Sintesi

```text
Jarvis -> tecnica e WordPress
Massy -> feed e candidate board
Simone -> report show e PLE/PPV
Menzo -> decisione editoriale e budget news
Bob -> traduzione
Alfred -> QA e correzione
Publisher -> pubblicazione
Archivista -> memoria e metriche
```
