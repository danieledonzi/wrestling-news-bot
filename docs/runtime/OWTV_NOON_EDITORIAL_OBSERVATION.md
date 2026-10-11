# Report delle 12 — osservazione del sistema attuale

Decisione del proprietario, 11 ottobre 2026: osservare ciclicamente e intervenire
solo su pattern potenzialmente dannosi chiaramente delineati. Ogni nuova regola
proposta deve essere approvata da Daniele prima dell'implementazione.
**Nessuna azione proposta** è l'esito normale.

## Contratto e fonti

Il runner versionato è `scripts.daily_report_email`; il launcher esterno
`/opt/owtv/send_daily_report.py` lo importa dal checkout installato. La cron delle
12, il lock esistente e i destinatari SMTP rimangono quelli della VPS.
`scripts/install_noon_report_runner.py` installa atomicamente il launcher dopo
aver conservato una copia del precedente. `python -m scripts.daily_report_email
--preview` genera gli allegati e una mail EML senza leggere credenziali o inviare.

| Sezione | Fonte e significato |
|---|---|
| Pubblicazioni | Ledger canonico validato tramite `observability_snapshot`: news uniche, report separati, mai selezioni sommate alle pubblicazioni. |
| Classi primarie | Store immutabile `menzo_primary_classifications_v1.json`, collegato agli URL. Le osservazioni ripetute di una classe non sono nuove classificazioni. Classi mancanti restano sconosciute. |
| Percorso MUST/SHOULD | Nuovi URL classificati nella finestra, pubblicati, skip definitivo, pending nell'ultima osservazione o esito non osservato. Gli URL pubblicati provenienti da coorti precedenti sono nel conteggio delle pubblicazioni, non nella nuova coorte. |
| Softpool | Ingressi, selezioni e pubblicazioni uniche osservate nella finestra; cronologia di stati, capacità e motivazioni delle review. Snapshot iniziale/finale separati: pool vuoto a fine giornata non implica inattività. Gli scarti del campione non sono un censimento completo. |
| Duplicate | Coppie ammesse nel percorso primario con URL, titoli e motivo semantico. La proiezione master non conserva tutti i verdetti né le coppie del softpool: queste lacune sono esplicite. Skip duplicate definitivi e rimozioni del softpool sono evidenze distinte, mai NO_MATCH dedotti dalla mancata eliminazione. |
| Invarianti | Confronti fra classi osservate e prima classe persistita; rientri/confronti dopo skip datato. Versioni precedenti separate dalla versione dell'ultima run. Copertura incompleta non certifica assenza di errori. |
| Snapshot correnti | Pool e coda prioritaria con aggiornamento, elementi raw ed esclusioni per pubblicazioni già osservate o skip. Il filtro pubblicazioni copre la storia master conservata; uno snapshot non ricostruisce la giornata. |
| Operatività | Run, Andrea, Alfred e Publisher dal ledger canonico, con metadati di copertura. Recuperi, eventi storici e fallimenti terminali restano distinti. |
| Costi | Ledger Gemini con contratto economico vigente; tentativi e costo a listino per classificazione, ammissione coppie, giudizio duplicate, competizione soft. Nessun costo controfattuale o prezzo stimato dalle vecchie metriche. |
| Traduzione | Audit completo delle news pubblicate, indagini offline e popolazione settimanale unica. `reproduced` significa controllo riprodotto: non dimostra un errore semantico e non genera da solo una modifica proposta. |

Il report osserva i totem correnti: classificazione definitiva prima di
duplicate/pool; skip definitivo escluso dalle valutazioni successive; quote
bookmaker escluse; news del feed MUST/SHOULD autonome durante il live. Il report
show non sostituisce le news e non viene usato per estrarre nuove notizie.

La finestra e l'ordinamento delle run usano il timestamp canonico master
(`recorded_at`, poi `run.ended_at`, poi `run.started_at`). Il controllo degli
skip successivi richiede inoltre l'ora d'inizio: se manca, la cronologia di
quella run è indisponibile, per evitare falsi rientri causati da uno skip
registrato durante la stessa esecuzione.

Il corpo mail contiene la sintesi corrente. Allegati: osservazione MD/JSON,
audit traduzione MD/JSON, indagini MD/JSON, pattern traduzione settimanali
MD/JSON. Sono allegati solo i risultati della stessa esecuzione: nessun recupero
di vecchi `latest` dopo un errore. Un controllo indisponibile è dichiarato.

Escono dal report corrente: giudizi OTTIMO/BUONO derivati dal volume, stime
hard/soft da score e tipo articolo, cluster lessicali di vecchi scorer,
raccomandazioni duplicate fra report e news, promozioni/riclassificazioni
ipotetiche. I parser legacy restano accessibili solo alle loro API storiche con
input espliciti; non alimentano più la mail di produzione.

## Note, proposte e storico

Ogni generazione corrente registra una nota append-only in
`state/reports/editorial_observation_notes.jsonl`: giorno locale, finestra,
copertura, proposta o nessuna azione, PR installata e data del merge ricavate
dalla storia git locale. Nessuna data viene inventata se il dato manca.
La stessa nota identica non viene registrata due volte; una nota successiva non
cancella o modifica quelle precedenti. Una corruzione dello storico è segnalata,
non ignorata o sovrascritta. Il JSON allegato contiene le ultime 30 note con
numero totale e riferimento allo storico completo; il Markdown riassume le
ultime 14.

Solo una violazione concreta di un'invariante nella versione corrente, con
copertura sufficiente ed evidenze URL/tempo/percorso, genera una proposta
specifica in attesa di approvazione. Attese tecniche del softpool restano
osservazioni da indagare. Una lacuna di telemetria, pochi articoli, slot liberi,
zero soft pubblicate o un segnale lessicale non determinano interventi.

Questo codice scrive esclusivamente artefatti di report e note diagnostiche.
Non invoca Gemini, produttori editoriali, mutatori di pool/coda o pubblicazioni.
