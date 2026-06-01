# OpenWrestlingTV Virtual Newsroom - Documento programmatico v93

OpenWrestlingTV News evolve da un bot monolitico a una redazione virtuale modulare.

La v93.0 introduce una cornice conservativa: un solo orchestratore, esecuzione sequenziale, agenti con responsabilita separate e log chiari. Non introduce bot paralleli e non riscrive scoring, dedupe, traduzione, report, health check, pending o pubblicazione.

## Principio operativo

La redazione virtuale deve comportarsi come una piccola redazione automatizzata:

- Massy monitora i feed e prepara la candidate board.
- Simone cura report settimanali e principali PLE/PPV.
- Menzo decide quali news lavorare e gestisce il budget giornaliero.
- Bob traduce solo elementi approvati.
- Alfred controlla qualita, refusi e terminologia.
- Jarvis controlla lo stato tecnico e WordPress.
- Publisher pubblica solo pacchetti approvati.
- Archivista salva log, metriche e memoria.

## Target editoriale

Obiettivo operativo medio:

```text
20-30 news al giorno, report esclusi.
```

I report non contano nel budget news giornaliero.

## Architettura

```text
cron GitHub
-> newsroom_runner.py
-> Jarvis
-> Massy
-> Simone
-> Menzo
-> Bob
-> Alfred
-> Publisher
-> Archivista
```

La differenza rispetto al bot unico non e il parallelismo. La differenza e l'organizzazione.

## v93.0

La v93.0 e una release bootstrap:

- aggiunge `newsroom_runner.py`;
- crea `artifacts/newsroom/`;
- salva `jarvis_status.json`, `agent_timeline.json` e `run_summary.json`;
- delega una sola volta al runtime esistente;
- non importa il motore se lo esegue via subprocess;
- propaga l'exit code del runtime;
- mantiene invariata la logica editoriale core.

## Gestione oraria

GitHub Actions da solo la campanella. Il codice deve riconoscere la finestra operativa e decidere cosa e dovuto.

Con poche finestre giornaliere, Menzo deve alzare dinamicamente il numero di news per run per mantenere il target 20-30 news/giorno.

## Regole conservative

Non modificare in v93.0:

- scoring;
- dedupe;
- traduzione;
- report matcher;
- categoria WordPress;
- health check;
- pending;
- skipped history;
- review package;
- published HTML review;
- manual mode.

## Fasi successive

```text
v93.1 Massy reale
v93.2 Menzo reale
v93.3 Simone reale
v93.4 Bob separato
v93.5 Alfred pre/post publish
v93.6 Archivista metriche e regressioni
```
