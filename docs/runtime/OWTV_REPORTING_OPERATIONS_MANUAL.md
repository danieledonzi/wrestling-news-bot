# OpenWrestlingTV — Manuale operativo dei report

## 1. Scopo e autorità del documento

Questo documento descrive l'architettura operativa dei report OpenWrestlingTV, la generazione dell'email giornaliera, gli artifact prodotti, le procedure di verifica, il comportamento in caso di errore e le modalità di rollback.

È il riferimento operativo per:

- controllo del report giornaliero;
- verifica della catena diagnostica introdotta con v95.16a;
- diagnosi di errori o artifact non aggiornati;
- esecuzioni manuali sicure;
- manutenzione del runner esterno alla repository;
- passaggio di consegne tecnico.

Il documento distingue sempre tra:

1. componenti versionati nella repository;
2. componenti esterni presenti soltanto sulla VPS;
3. artifact timestamped, riferiti a una singola esecuzione;
4. artifact `latest`, che rappresentano lo stato più recente disponibile;
5. dati autorevoli e dati legacy o soltanto diagnostici.

## 2. Architettura generale

### 2.1 Repository

Checkout operativo:

```text
/opt/owtv/wrestling-news-bot
```

Modulo repository usato per la catena diagnostica:

```text
/opt/owtv/wrestling-news-bot/send_daily_report.py
```

Script principali:

```text
scripts/translation_quality_audit.py
scripts/translation_warning_analysis.py
scripts/daily_editorial_judgment.py
```

Questi file sono sotto controllo versione Git.

### 2.2 Componenti esterni alla repository

I seguenti componenti sono residenti sulla VPS e non sono attualmente versionati nella repository:

```text
/opt/owtv/send_daily_report.py
/opt/owtv/send_daily_report.sh
/opt/owtv/report_email.env
/opt/owtv/owtv_report.sh
/opt/owtv/owtv_editorial_report.sh
/opt/owtv/owtv_gemini_ledger_report.py
/opt/owtv/reports
```

Il file `/opt/owtv/send_daily_report.py` è il runner reale dell'email giornaliera. Non va confuso con il modulo omonimo presente nella repository.

Lo script operativo `/opt/owtv/owtv_gemini_ledger_report.py` deve essere un collegamento simbolico alla sorgente canonica versionata `/opt/owtv/wrestling-news-bot/scripts/owtv_gemini_ledger_report.py`.

Il collegamento viene installato o aggiornato tramite `scripts/install_runtime_reporting_links.sh`.

Il runner esterno importa il modulo repository con un nome distinto e richiama:

```python
generate_daily_diagnostics_24h()
```

Questa separazione evita collisioni tra i due file omonimi.

## 3. Schedulazione

### 3.1 Cron giornaliero

Configurazione verificata:

```cron
CRON_TZ=Europe/Rome
0 12 * * * /opt/owtv/send_daily_report.sh >> /opt/owtv/wrestling-news-bot/logs/daily_report_email.log 2>&1
```

Il report giornaliero viene avviato alle 12:00 nel fuso `Europe/Rome`.

### 3.2 Wrapper e lock

Il wrapper esegue:

```bash
flock -n /tmp/owtv-daily-report.lock /opt/owtv/send_daily_report.py
```

Il lock impedisce due esecuzioni concorrenti del report giornaliero.

### 3.3 Timer del bot

Il timer del bot principale è un'autorità separata dalla schedulazione dell'email giornaliera. Va verificato indipendentemente:

```bash
systemctl list-timers --all | grep -Ei "owtv|daily|report|mail"
```

Il fatto che il bot sia schedulato tramite systemd non prova che il report email sia schedulato correttamente, e viceversa.

## 4. Ordine obbligatorio della catena diagnostica

L'ordine deve essere sempre:

```text
Translation Quality Audit
→ Automatic Warning Investigation
→ Daily Editorial Judgment
```

Motivazione:

- il Translation Quality Audit costruisce l'inventario dei warning e la provenienza dei materiali;
- l'Automatic Warning Investigation analizza quei warning;
- il Daily Editorial Judgment incorpora la sintesi dell'investigazione.

Eseguire il Judgment prima dell'audit o dell'investigazione produce un report incompleto o basato su artifact precedenti.

Il punto di ingresso corretto è:

```python
generate_daily_diagnostics_24h()
```

Non sostituirlo con chiamate isolate salvo procedure diagnostiche esplicitamente controllate.

## 5. Report inclusi nell'email

L'email giornaliera contiene le seguenti sezioni:

1. Sintesi operativa;
2. Sintesi editoriale;
3. Story Cluster Audit;
4. Daily Editorial Judgment;
5. Translation Quality Audit;
6. Automatic Warning Investigation.

Gli allegati previsti in una run completamente riuscita sono nove:

1. Operational Report Markdown;
2. Editorial Audit Markdown;
3. Story Cluster Audit Markdown;
4. Daily Editorial Judgment Markdown;
5. Daily Editorial Judgment latest JSON;
6. Translation Quality Audit Markdown;
7. Translation Quality Audit latest JSON;
8. Automatic Warning Investigation Markdown;
9. Automatic Warning Investigation latest JSON.

La presenza di tutti e nove gli allegati va verificata nei test end-to-end. In caso di errore di uno stadio opzionale, il numero degli allegati può essere inferiore e la run va interpretata tramite log ed errori riportati nel corpo email.

## 6. Artifact principali

### 6.1 Translation Quality Audit

Artifact timestamped:

```text
reports/owtv_translation_quality_audit_24h_*.md
```

Stato latest:

```text
state/reports/owtv_translation_quality_audit_latest.json
```

### 6.2 Automatic Warning Investigation

Artifact timestamped:

```text
reports/owtv_translation_warning_analysis_24h_*.json
reports/owtv_translation_warning_analysis_24h_*.md
```

Stato latest:

```text
state/reports/owtv_translation_warning_analysis_latest.json
```

### 6.3 Daily Editorial Judgment

Artifact timestamped:

```text
reports/owtv_daily_editorial_judgment_24h_*.json
reports/owtv_daily_editorial_judgment_24h_*.md
```

Stato latest:

```text
state/reports/owtv_daily_editorial_judgment_latest.json
```

## 7. Autorità e provenienza dei dati

### 7.1 Dati autorevoli

Per pubblicazioni e conteggi finali va privilegiato l'insieme autorevole ricostruito dall'observability snapshot e dai record di pubblicazione.

Il Daily Editorial Judgment deve indicare esplicitamente gli artifact usati in `source_artifacts_used`.

Per verificare che l'investigazione warning sia stata incorporata, controllare che compaia:

```text
state/reports/owtv_translation_warning_analysis_latest.json
```

### 7.2 Dati legacy o diagnostici

Sono diagnostici e non necessariamente autorevoli:

- conteggi ricavati da Markdown legacy;
- rapporti Menzo ricostruiti da campioni incompleti;
- warning aggregati con semantiche diverse;
- segnali duplicati legacy;
- conteggi tecnici ripetuti per singola occorrenza.

Una differenza tra conteggi legacy e autorevoli non deve essere corretta arbitrariamente nel report finale. Va prima identificata la diversa semantica.

## 8. Semantica dell'Automatic Warning Investigation

### `reproduced`

La regola deterministica esistente ha trovato una corrispondenza nel materiale disponibile.

Non equivale a conferma editoriale umana. Un warning riprodotto può ancora essere un falso positivo, per esempio quando una regex intercetta terminologia wrestling legittima, nomi di eventi o espressioni come `pay-per-view`.

### `not_reproduced`

Il materiale autorevole richiesto era disponibile e la stessa regola deterministica non ha trovato corrispondenze.

### `possible_false_positive`

L'audit ha fornito esplicitamente questa classificazione come evidenza.

### `insufficient_material`

Manca il materiale autorevole necessario oppure non esiste una regola locale deterministica adatta.

Non è prova che l'articolo sia corretto.

### `technical`

Il warning riguarda immagini, media o condizioni tecniche.

Non implica automaticamente un difetto editoriale.

### Regola generale

L'investigazione:

- non blocca la pubblicazione;
- non modifica articoli;
- non riprova la pubblicazione;
- non elimina contenuti;
- non sostituisce la revisione umana.

## 9. Semantica dei conteggi

Il Translation Quality Audit può contare ogni singola occorrenza di warning.

L'Automatic Warning Investigation deduplica per:

```text
articolo + warning_code
```

Per questo motivo valori apparentemente diversi possono essere entrambi corretti.

Esempio:

```text
24 occorrenze image_placeholder_present
11 investigazioni technical
```

Il primo numero rappresenta occorrenze aggregate; il secondo rappresenta coppie uniche articolo-warning.

## 10. Comportamento non bloccante e protezione dagli artifact obsoleti

La consegna dell'email deve continuare anche se un diagnostico opzionale fallisce. La protezione dagli artifact obsoleti, però, non è identica per tutti gli stadi.

### 10.1 Translation Quality Audit

In caso di errore dell'audit:

- l'orchestratore non deve presentare il precedente JSON `latest` come risultato della run corrente;
- il risultato restituito allo stadio successivo deve indicare l'errore;
- il runner esterno non deve allegare un audit precedente come se fosse appena generato.

### 10.2 Automatic Warning Investigation

Questo è lo stadio con la protezione completa introdotta da v95.16a:

- un errore produce un artifact controllato della run corrente;
- il file `latest` dell'investigazione viene sostituito con lo stato di errore corrente;
- il Markdown allegato viene ricostruito in coerenza con il `generated_at` del JSON `latest`;
- un artifact di una run precedente non deve essere presentato come investigazione corrente;
- l'errore compare nel corpo email o nel JSON diagnostico senza interrompere SMTP.

La garanzia di pairing temporale e sostituzione dello stato `latest` descritta sopra riguarda specificamente l'Automatic Warning Investigation.

### 10.3 Daily Editorial Judgment: eccezione nota

Il Daily Editorial Judgment non dispone ancora della stessa protezione completa.

Nell'implementazione corrente, se la generazione del Judgment fallisce:

- `generate_daily_editorial_judgment_24h()` può restituire il JSON `latest` già esistente;
- la selezione del Markdown e del JSON può avvenire indipendentemente;
- un artifact di una run precedente può quindi restare disponibile o essere selezionato durante una run fallita.

Regola operativa obbligatoria:

> Quando la run segnala un errore del Daily Editorial Judgment, nessun allegato o file `latest` del Judgment deve essere considerato corrente senza verifica esplicita del `generated_at`, del timestamp del Markdown e del log della run.

Il completamento della protezione anti-stale del Judgment è una correzione successiva e non fa parte di v95.16a.

## 11. Procedure operative

### 11.1 Verifica del commit installato

```bash
cd /opt/owtv/wrestling-news-bot
git pull origin main
git log -1 --oneline
```

### 11.2 Compilazione statica

Questa verifica non genera report e non invia email:

```bash
python3 -m py_compile \
  /opt/owtv/send_daily_report.py \
  /opt/owtv/wrestling-news-bot/send_daily_report.py \
  /opt/owtv/wrestling-news-bot/scripts/translation_warning_analysis.py \
  /opt/owtv/wrestling-news-bot/scripts/translation_quality_audit.py \
  /opt/owtv/wrestling-news-bot/scripts/daily_editorial_judgment.py
```

### 11.3 Verifica dell'ordine nel runner esterno

```bash
grep -nE \
  "load_repo_daily_report_module|run_repository_diagnostics|generate_daily_diagnostics_24h|translation_warning_" \
  /opt/owtv/send_daily_report.py
```

### 11.4 Esecuzione dei soli diagnostici, senza SMTP

Questa procedura importa il runner esterno ma non richiama `main()`:

```bash
cd /opt/owtv/wrestling-news-bot

python3 - <<'PY'
import importlib.util
from pathlib import Path

runner_path = Path("/opt/owtv/send_daily_report.py")
spec = importlib.util.spec_from_file_location("owtv_external_daily_report_test", runner_path)
if spec is None or spec.loader is None:
    raise SystemExit("Impossibile caricare il runner esterno")

runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

repository_module, results = runner.run_repository_diagnostics()
print("Modulo repository caricato:", repository_module is not None)
print("Ordine:", " -> ".join(results.keys()))
for name, result in results.items():
    print(name, result)
PY
```

Ordine atteso:

```text
translation_quality_audit
→ translation_warning_analysis
→ daily_editorial_judgment
```

### 11.5 Esecuzione completa manuale con invio email

Questa procedura invia realmente l'email:

```bash
cd /opt/owtv
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="/tmp/owtv_daily_report_${STAMP}.log"

bash -o pipefail -c \
  "/opt/owtv/send_daily_report.sh 2>&1 | tee '$LOG'"

tail -n 100 "$LOG"
```

Indicatori attesi nel log:

```text
[TRANSLATION QUALITY] generated
[WARNING INVESTIGATION] generated
[DAILY JUDGMENT] generated
[WARNING INVESTIGATION] attached
[DAILY REPORT] Email inviata
```

### 11.6 Lettura del log giornaliero

```bash
tail -n 200 /opt/owtv/wrestling-news-bot/logs/daily_report_email.log
```

### 11.7 Verifica degli artifact recenti

```bash
cd /opt/owtv/wrestling-news-bot

ls -lt \
  reports/owtv_translation_quality_audit_24h_* \
  reports/owtv_translation_warning_analysis_24h_* \
  reports/owtv_daily_editorial_judgment_24h_* \
  state/reports/owtv_translation_quality_audit_latest.json \
  state/reports/owtv_translation_warning_analysis_latest.json \
  state/reports/owtv_daily_editorial_judgment_latest.json \
  2>/dev/null | head -n 30
```

### 11.8 Verifica cron

```bash
crontab -l
```

Controllare la presenza della riga delle 12:00 con `CRON_TZ=Europe/Rome`.

### 11.9 Verifica timer systemd del bot

```bash
systemctl list-timers --all | grep -Ei "owtv|daily|report|mail"
```

### 11.10 Conferma dell'input warning nel Daily Judgment

```bash
python3 - <<'PY'
import json
from pathlib import Path

path = Path("/opt/owtv/wrestling-news-bot/state/reports/owtv_daily_editorial_judgment_latest.json")
data = json.loads(path.read_text(encoding="utf-8"))
print(data.get("generated_at"))
print(data.get("translation_warning_analysis"))
print(data.get("source_artifacts_used"))
PY
```

Verificare che `source_artifacts_used` includa il latest JSON dell'investigazione e che `generated_at` appartenga alla run attesa.

### 11.11 Controllo temporale del Judgment dopo un errore

Quando il log contiene un errore del Daily Editorial Judgment:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path("/opt/owtv/wrestling-news-bot")
latest = root / "state/reports/owtv_daily_editorial_judgment_latest.json"

if latest.exists():
    data = json.loads(latest.read_text(encoding="utf-8"))
    print("latest JSON:", latest)
    print("generated_at:", data.get("generated_at"))

for path in sorted(
    (root / "reports").glob("owtv_daily_editorial_judgment_24h_*.md"),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)[:3]:
    print("markdown:", path, "mtime:", path.stat().st_mtime)
PY
```

Se i timestamp non appartengono alla run corrente, il Judgment non va considerato valido anche se il file è presente.

## 12. Backup e rollback del runner esterno

### 12.1 Backup

Schema del backup introdotto con v95.16a:

```text
/opt/owtv/send_daily_report.py.pre_v95_16a_<timestamp>
```

Creazione manuale:

```bash
STAMP="$(date +%Y%m%d_%H%M%S)"
cp -a \
  /opt/owtv/send_daily_report.py \
  "/opt/owtv/send_daily_report.py.pre_change_${STAMP}"
```

### 12.2 Rollback

Prima di ripristinare un backup, preservare sempre il file corrente:

```bash
STAMP="$(date +%Y%m%d_%H%M%S)"
cp -a \
  /opt/owtv/send_daily_report.py \
  "/opt/owtv/send_daily_report.py.before_rollback_${STAMP}"
```

Ripristino:

```bash
cp -a \
  /opt/owtv/send_daily_report.py.pre_v95_16a_<timestamp> \
  /opt/owtv/send_daily_report.py
```

Validazione obbligatoria:

```bash
python3 -m py_compile /opt/owtv/send_daily_report.py
```

Durante il rollback non eseguire automaticamente il runner completo, perché la sua esecuzione avvia SMTP. Prima usare controlli statici e import senza `main()`.

## 13. Known current diagnostic discrepancies

### Cron riportato come assente

Il report operativo può indicare:

```text
Cron installato: NO
```

anche quando il crontab dell'utente contiene correttamente il job giornaliero. Questa è una discrepanza del rilevatore legacy, non prova che il cron sia assente.

### Warning Alfred non coincidenti

Il Markdown editoriale legacy può riportare un numero di warning Alfred diverso dal Daily Judgment autorevole.

Il Judgment può quindi mostrare:

```text
observability_alfred_warning_events_differs_from_markdown
```

La differenza va interpretata come divergenza di fonte o semantica, non corretta manualmente.

### Rapporto Menzo finale pari a zero

Il report legacy può riportare rapporti final-selected pari a zero nonostante esistano pubblicazioni autorevoli ricostruite dall'observability snapshot.

### Working tree apparentemente sporco

Sono modifiche runtime attese:

```text
.bot_exit_code
logs/master_log.log
reports/
```

Non devono essere considerate automaticamente regressioni del codice sorgente.

### Residual English riprodotto ma legittimo

Warning riprodotti possono essere falsi positivi per terminologia wrestling, nomi propri, eventi o espressioni legittime come `pay-per-view`.

### Daily Judgment e artifact precedenti

In caso di errore del Daily Editorial Judgment, il file `latest` o il Markdown più recente possono appartenere a una run precedente. La loro semplice presenza non prova che il Judgment corrente sia stato generato.

### Simone

La readiness di Simone e la semantica degli errori di pubblicazione dei report show appartengono a una riforma diagnostica successiva.

## 14. Troubleshooting

### Nessun artifact nuovo

Controllare:

1. timestamp dei file latest;
2. log giornaliero;
3. permessi su `reports/` e `state/reports/`;
4. compilazione degli script;
5. presenza del checkout repository;
6. esito di `run_repository_diagnostics()`.

### Email ricevuta senza alcuni allegati

Controllare:

- che il relativo stadio non abbia prodotto errore;
- che il path restituito esista;
- che il Markdown sia coerente con `generated_at` quando lo stadio offre questa garanzia;
- che il JSON latest sia quello della run corrente;
- che il runner esterno sia la versione corretta.

Per il Daily Editorial Judgment, un errore invalida l'assunzione che il file disponibile sia corrente: verificare sempre i timestamp.

### Investigazione con zero elementi

Può essere corretto se non esistono warning. Controllare sempre `errors` nel JSON prima di interpretare zero come assenza di problemi.

### Artifact precedente presentato come corrente

Per Translation Quality Audit e Automatic Warning Investigation è una regressione grave. Non considerare il report valido e verificare immediatamente:

- `generated_at` del latest JSON;
- nome e timestamp del Markdown associato;
- comportamento del failure artifact;
- eventuale richiamo diretto di funzioni legacy fuori dall'orchestratore.

Per il Daily Editorial Judgment è una limitazione nota nella gestione degli errori: segnalare la run come non valida, non fidarsi dell'allegato e controllare il log prima di qualsiasi conclusione editoriale.

## 15. Checklist di deployment

- [ ] `main` aggiornato sulla VPS;
- [ ] commit atteso verificato con `git log -1`;
- [ ] `py_compile` superato;
- [ ] backup del runner esterno creato;
- [ ] ordine audit → investigation → judgment verificato;
- [ ] test diagnostico senza SMTP superato;
- [ ] tutti e tre i latest JSON rigenerati nella run riuscita;
- [ ] Daily Judgment usa il latest JSON dell'investigazione;
- [ ] email completa ricevuta;
- [ ] tutti e nove gli allegati presenti nella run riuscita;
- [ ] log senza errori non controllati;
- [ ] successiva esecuzione cron non assistita verificata.

## 16. Roadmap esclusa da v95.16a

v95.16a non comprende:

- aggregazione settimanale dei pattern di warning;
- miglioramento persistente della catena source → candidate → final;
- riforma della diagnostic readiness di Simone;
- riconciliazione autorevole dei conteggi;
- diagnostica di costi e budget;
- fase Guardian editoriale e stilistica;
- protezione anti-stale completa del Daily Editorial Judgment.

Queste aree devono essere implementate separatamente per evitare regressioni e sovrapposizioni di responsabilità.

## 17. Registro di validazione

### 2026-07-22 — v95.16a

Validazione manuale completata con successo:

- repository aggiornata al merge di PR #86;
- compilazione statica superata;
- runner esterno aggiornato con backup;
- catena diagnostica eseguita nell'ordine corretto;
- tre latest JSON rigenerati;
- Daily Judgment integrato con l'analisi warning;
- email manuale ricevuta;
- nove allegati presenti.

Questa validazione manuale non dimostra, da sola, che la successiva esecuzione cron non assistita sia riuscita. La prima run automatica successiva va controllata separatamente nel log giornaliero e nella casella email.
