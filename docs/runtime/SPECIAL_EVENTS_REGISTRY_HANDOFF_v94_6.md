# OpenWrestlingTV - Special Events Registry Handoff v94.6

## 1. Scopo del documento

Questo documento descrive il lavoro svolto sul sistema OpenWrestlingTV per introdurre, alimentare e monitorare un registro degli eventi speciali di wrestling, separato dalla normale copertura settimanale dei programmi TV.

L'obiettivo e permettere a Simone, l'agente dedicato ai report, di riconoscere con certezza gli eventi speciali confermati, produrre il relativo report post-evento e attivare la logica di blocco delle news ridondanti dopo la pubblicazione del report.

Il sistema non sostituisce la copertura ordinaria degli show settimanali, ma la integra con un livello dedicato a PLE, PPV e special event.

---

## 2. Contesto operativo

OpenWrestlingTV e passato da una gestione basata su cron GitHub Actions a una gestione su VPS Oracle, per ridurre i problemi di timeout verso WordPress e avere un ambiente piu stabile.

La produzione attuale gira su VPS Oracle:

- Host: `owtv-publisher`
- Public IP: `84.8.252.172`
- Repository locale: `/opt/owtv/wrestling-news-bot`
- Ambiente Python: `/opt/owtv/wrestling-news-bot/.venv`
- File env runtime: `/opt/owtv/wrestling-news-bot/.env`
- Directory report operativi: `/opt/owtv/reports`

Il cron attivo sulla VPS gestisce:

```cron
*/30 * * * * /opt/owtv/run_bot.sh

# OpenWrestlingTV daily operational/editorial report
CRON_TZ=Europe/Rome
0 12 * * * /opt/owtv/send_daily_report.sh >> /opt/owtv/wrestling-news-bot/logs/daily_report_email.log 2>&1

# OpenWrestlingTV special events registry report - biweekly
CRON_TZ=Europe/Rome
0 10 */14 * * /opt/owtv/send_special_events_report.sh >> /opt/owtv/wrestling-news-bot/logs/special_events_report_email.log 2>&1
```

---

## 3. Problema affrontato

Prima di questo intervento, Simone era in grado di lavorare in modo affidabile sugli show settimanali principali, ma non aveva una base strutturata per riconoscere in anticipo tutti gli eventi speciali.

La copertura ordinaria comprende:

- WWE Raw
- WWE NXT
- AEW Dynamite
- TNA Impact
- WWE SmackDown
- AEW Collision

Per questi programmi la logica e collegata alla scansione dei feed, al riconoscimento dei report/results e alla pubblicazione del report post-show.

Il problema era diverso per PLE, PPV e special event:

- non tutti hanno cadenza settimanale;
- alcuni cambiano data, nome o sede;
- alcuni sono multi-night;
- alcuni sono annunciati con largo anticipo;
- alcuni non devono generare report automatici se non ancora ritenuti parte del perimetro editoriale;
- dopo la pubblicazione del report bisogna bloccare le news semplicemente riassuntive dello stesso evento.

Per questo e stato introdotto un registro eventi speciale.

---

## 4. File principale: `config/special_events.json`

Il cuore del sistema e il file:

```text
config/special_events.json
```

Il file contiene il registry degli eventi speciali conosciuti dal sistema.

Ogni evento contiene informazioni come:

- `key`
- `promotion`
- `brand`
- `event_name`
- `event_type`
- `priority`
- `status`
- `coverage_policy`
- `category_hint`
- `aliases`
- `nights`
- `venue`
- `location`
- `source`
- `last_verified_at_utc`

Esempio concettuale:

```json
{
  "key": "aew_redemption_2026",
  "promotion": "AEW",
  "brand": "AEW",
  "event_name": "Redemption",
  "event_type": "PPV",
  "priority": "major",
  "status": "confirmed",
  "coverage_policy": "report_and_post_event_freeze",
  "category_hint": "AEW",
  "aliases": [
    "AEW Redemption",
    "Redemption",
    "Redemption 2026"
  ],
  "nights": [
    {
      "night_key": "aew_redemption_2026_main",
      "label": "Main show",
      "date_local": "2026-07-26",
      "report_publish_after_local": "06:30",
      "enabled": true,
      "aliases": [
        "AEW Redemption results",
        "Redemption results"
      ]
    }
  ],
  "venue": "Bell Centre",
  "location": "Montreal, Quebec",
  "source": "wikipedia_schedule_auto_applied",
  "last_verified_at_utc": "2026-06-12T13:57:14Z"
}
```

---

## 5. Stati degli eventi

Gli stati principali sono:

### `confirmed`

Evento confermato, con data certa nel registry. Simone puo considerarlo operativo.

### `expected`

Evento atteso, ma non ancora confermato. Non deve attivare automaticamente la produzione di report.

### `cancelled`

Evento annullato. Non deve essere considerato operativo.

### `completed`

Evento gia passato e chiuso.

---

## 6. Coverage policy

La policy piu importante e:

```text
report_and_post_event_freeze
```

Significa che per quell'evento Simone deve:

1. cercare il report/results dopo l'evento;
2. produrre il report post-evento;
3. pubblicarlo nella finestra prevista;
4. bloccare successivamente le news ridondanti basate solo sui risultati o sul semplice recap dell'evento.

La logica non deve bloccare invece contenuti con valore aggiunto, come:

- dichiarazioni post-evento;
- retroscena;
- piani futuri;
- infortuni;
- reazioni rilevanti;
- analisi editoriali;
- implicazioni di storyline.

---

## 7. Orario di pubblicazione report

Il registry usa come default:

```text
default_report_publish_after_local: 06:30
timezone: Europe/Rome
```

Questo significa che, salvo eccezioni, il report post-evento viene pubblicato non appena disponibile ma non prima della finestra editoriale mattutina italiana.

Per gli eventi multi-night, ogni night ha la propria voce in `nights`.

Esempio:

```json
"nights": [
  {
    "night_key": "wwe_summerslam_2026_night_1",
    "label": "Night 1",
    "date_local": "2026-08-01",
    "report_publish_after_local": "06:30",
    "enabled": true
  },
  {
    "night_key": "wwe_summerslam_2026_night_2",
    "label": "Night 2",
    "date_local": "2026-08-02",
    "report_publish_after_local": "06:30",
    "enabled": true
  }
]
```

---

## 8. Fonti usate per il calendario eventi

Per alimentare il registry e stato scelto un approccio a due livelli.

### Livello 1: fonti ufficiali

Sono utili come riferimento generale, ma non sempre espongono in modo semplice e stabile le date in formato leggibile dal parser.

### Livello 2: Wikipedia schedule layer

Per la verifica operativa degli eventi e stato introdotto un layer basato sulle pagine Wikipedia che elencano gli eventi futuri.

Le pagine usate sono:

- WWE/NXT: `https://en.wikipedia.org/wiki/List_of_WWE_pay-per-view_and_livestreaming_supercards`
- AEW: `https://en.wikipedia.org/wiki/List_of_All_Elite_Wrestling_pay-per-view_events`
- TNA: `https://en.wikipedia.org/wiki/List_of_TNA_pay-per-view_and_livestreaming_events`
- ROH: `https://en.wikipedia.org/wiki/List_of_Ring_of_Honor_pay-per-view_and_livestreaming_events`
- AAA: `https://en.wikipedia.org/wiki/List_of_major_Lucha_Libre_AAA_Worldwide_events`

La scelta e stata fatta perche queste pagine contengono sezioni `Upcoming` abbastanza strutturate e aggiornate.

---

## 9. Script Wikipedia schedule layer

File:

```text
tools/special_events_wikipedia_schedule_layer.py
```

Funzione:

- legge le pagine Wikipedia configurate;
- usa il formato raw `?action=raw`;
- individua solo le sezioni upcoming;
- estrae eventi, date, venue e location;
- confronta gli eventi con il registry;
- produce un JSON e un report Markdown.

Esecuzione manuale:

```bash
cd /opt/owtv/wrestling-news-bot
python3 tools/special_events_wikipedia_schedule_layer.py --report-dir /opt/owtv/reports
```

Output tipico:

```text
[WIKI SCHEDULE] events=14
[WIKI SCHEDULE] json=/opt/owtv/reports/special_events_wikipedia_schedule_layer_YYYY-MM-DD_HH-MM.json
[WIKI SCHEDULE] report=/opt/owtv/reports/special_events_wikipedia_schedule_layer_YYYY-MM-DD_HH-MM.md
```

---

## 10. Script registry apply

File:

```text
tools/special_events_registry_apply.py
```

Funzione:

- legge l'ultimo JSON prodotto dal Wikipedia schedule layer;
- confronta gli eventi con `config/special_events.json`;
- propone azioni di update/add/skip;
- di default lavora in dry-run;
- aggiorna davvero il registry solo con `--write`.

Dry-run:

```bash
cd /opt/owtv/wrestling-news-bot
python3 tools/special_events_registry_apply.py --report-dir /opt/owtv/reports
```

Apply reale:

```bash
python3 tools/special_events_registry_apply.py --report-dir /opt/owtv/reports --write
```

Dopo l'apply e necessario controllare il diff:

```bash
git diff -- config/special_events.json | sed -n '1,260p'
```

Se il diff e corretto:

```bash
git add config/special_events.json
git commit -m "data: update special events registry from Wikipedia schedule"
git push https://danieledonzi@github.com/danieledonzi/wrestling-news-bot.git main
```

---

## 11. Policy per AAA

AAA e stata lasciata in modalita watchlist/report-only.

Il layer Wikipedia puo rilevare eventi AAA come:

- Verano de Escandalo
- Triplemania

Tuttavia, allo stato attuale questi eventi non vengono automaticamente inseriti nel registry operativo e non attivano Simone.

Motivo:

- AAA e fuori dal perimetro principale attuale;
- puo diventare rilevante in futuro;
- per ora va monitorata senza generare report automatici.

Nel report email gli eventi AAA appaiono come:

```text
SKIP AAA - Nome evento: report_only
```

---

## 12. Eventi attualmente confermati nel registry

Alla chiusura della v94.6, gli eventi speciali sicuri sono:

### WWE / NXT

- WWE Night of Champions  
  Data: 2026-06-27  
  Policy: report + freeze post-evento

- NXT The Great American Bash  
  Data: 2026-06-28  
  Policy: report + freeze post-evento

- WWE Saturday Night's Main Event XLV  
  Data: 2026-07-18  
  Policy: report + freeze post-evento

- WWE SummerSlam Night 1  
  Data: 2026-08-01  
  Policy: report separato Night 1

- WWE SummerSlam Night 2  
  Data: 2026-08-02  
  Policy: report separato Night 2

- WWE Sunday Night Main Event  
  Data: 2026-09-06  
  Policy: report + freeze post-evento

- WWE Money in the Bank  
  Data: 2026-10-10  
  Policy: report + freeze post-evento

### AEW

- AEW Forbidden Door  
  Data: 2026-06-28  
  Policy: report + freeze post-evento

- AEW Redemption  
  Data: 2026-07-26  
  Policy: report + freeze post-evento

- AEW All In  
  Data: 2026-08-30  
  Policy: report + freeze post-evento

### TNA

- TNA Slammiversary  
  Data: 2026-06-28  
  Policy: report + freeze post-evento

- TNA Lockdown  
  Data: 2026-08-23  
  Policy: report + freeze post-evento

- TNA Bound for Glory  
  Data: 2026-10-11  
  Policy: report + freeze post-evento

---

## 13. Report email bisettimanale

E stato creato uno script locale sulla VPS:

```text
/opt/owtv/send_special_events_report.py
```

Wrapper:

```text
/opt/owtv/send_special_events_report.sh
```

La mail viene inviata usando il file gia esistente:

```text
/opt/owtv/report_email.env
```

Lo script:

1. esegue il Wikipedia schedule layer;
2. esegue il registry apply in dry-run;
3. include il report Markdown completo;
4. invia una mail;
5. non modifica il registry;
6. non fa commit;
7. non fa push.

Esecuzione manuale:

```bash
/opt/owtv/send_special_events_report.sh
```

Cron installato:

```cron
# OpenWrestlingTV special events registry report - biweekly
CRON_TZ=Europe/Rome
0 10 */14 * * /opt/owtv/send_special_events_report.sh >> /opt/owtv/wrestling-news-bot/logs/special_events_report_email.log 2>&1
```

Nota: `*/14` nel campo giorno del mese significa giorni 1, 15 e 29 del mese. E una cadenza bisettimanale pratica, non un intervallo mobile esatto ogni 14 giorni.

---

## 14. Aggiornamento manuale del registry

Quando la mail bisettimanale segnala nuovi eventi o cambiamenti, la procedura corretta e:

```bash
cd /opt/owtv/wrestling-news-bot

git pull --ff-only

python3 tools/special_events_wikipedia_schedule_layer.py --report-dir /opt/owtv/reports

python3 tools/special_events_registry_apply.py --report-dir /opt/owtv/reports
```

Se il dry-run e corretto:

```bash
python3 tools/special_events_registry_apply.py --report-dir /opt/owtv/reports --write

git diff -- config/special_events.json | sed -n '1,260p'
```

Se il diff e pulito:

```bash
git add config/special_events.json
git commit -m "data: update special events registry from Wikipedia schedule"
git push https://danieledonzi@github.com/danieledonzi/wrestling-news-bot.git main
```

In caso di richiesta password durante il push, usare il GitHub Personal Access Token, non la password dell'account.

---

## 15. Stato GitHub alla chiusura

Commit principale di chiusura:

```text
d344c42 data(v94.5): apply Wikipedia special event schedule
```

Stato locale/remoto verificato:

```text
d344c42 (HEAD -> main, origin/main, origin/HEAD)
```

Questo conferma che la VPS e GitHub sono allineati.

---

## 16. Cosa e stato deliberatamente evitato

Per prudenza non e stato attivato l'aggiornamento automatico completo del registry.

Il cron bisettimanale non esegue:

- `--write`;
- commit automatici;
- push automatici.

Questa scelta riduce il rischio di aggiornare il registry sulla base di dati sporchi o di modifiche impreviste nelle pagine Wikipedia.

La logica scelta e:

```text
mail bisettimanale -> controllo umano -> apply manuale -> diff -> commit -> push
```

---

## 17. Miglioramenti futuri consigliati

### 17.1 Cambiare `UPDATE` in `KEEP`

Nel dry-run, quando un evento e gia confermato e le date coincidono, oggi appare:

```text
UPDATE nome_evento: already_confirmed_dates_match
```

Funzionalmente e corretto, perche il registry non viene modificato. Tuttavia sarebbe piu leggibile usare:

```text
KEEP nome_evento: already_confirmed_dates_match
```

### 17.2 Integrare pienamente Simone con il registry

Il passo successivo piu importante e assicurare che Simone legga direttamente `config/special_events.json` e usi:

- date;
- aliases;
- nights;
- coverage policy;
- report publish window;
- post-event freeze.

### 17.3 Alert selettivi

La mail bisettimanale potrebbe essere resa piu sintetica, evidenziando in alto solo:

- nuovi eventi;
- date cambiate;
- eventi attesi ora confermati;
- eventi rimossi;
- eventi AAA in watchlist.

### 17.4 Eventi ROH

Al momento la pagina ROH non espone eventi upcoming reali utili. Il sistema la controlla, ma non aggiunge eventi se trova solo righe non operative o legend row.

### 17.5 Possibile futuro auto-apply controllato

In futuro si potrebbe valutare un auto-apply limitato a:

- WWE;
- NXT;
- AEW;
- TNA;
- ROH;

escludendo AAA e richiedendo comunque diff/report email.

Per ora questa automazione non e stata attivata.

---

## 18. Conclusione

Con la v94.6 OpenWrestlingTV dispone di una base piu solida per la gestione dei grandi eventi.

Il sistema ora ha:

- un registry eventi speciali;
- un layer di controllo Wikipedia;
- un tool di dry-run/apply;
- una mail bisettimanale di monitoraggio;
- una procedura manuale sicura di aggiornamento;
- una lista di eventi confermati che Simone potra usare come base operativa.

La filosofia resta prudente: automatizzare il monitoraggio, ma mantenere controllo umano sull'aggiornamento effettivo del registry.
