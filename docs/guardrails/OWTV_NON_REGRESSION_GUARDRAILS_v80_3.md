# OpenWrestlingTV – Non Regression Guardrails v80.3

Questo file documenta i comportamenti che, dopo le run reali v79.1–v80.3, sono considerati **stabili, corretti e da non regredire**.

Scopo: quando si prepara una nuova patch del bot, queste aree vanno trattate come **guardrail**. Si possono estendere o rifinire, ma non riscrivere o disattivare senza una regressione dimostrata nei log.

Versione di riferimento codice: `bot_v80_3.py`  
Runtime atteso: `v80_3_review_package_all_attempted`

---

## 1. Spoiler: outcome concreti sì, annunci no

### Comportamento considerato corretto
Il tag `[SPOILER]` va applicato quando una news rivela un esito concreto o un'identità concreta:

- vittoria/sconfitta;
- mantenimento o cambio titolo;
- avanzamento/eliminazione;
- identità svelata;
- mystery partner/opponent rivelato;
- nuovo campione/campionessa.

Non va invece applicato a un annuncio post-show che non rivela un outcome, per esempio:

- John Cena annuncia un torneo;
- WWE annuncia TripleMania;
- annuncio di evento futuro;
- partnership o format announcement.

### Esempi osservati e validati
Corretti come spoiler:

- `Bron Breakker Defeats Seth Rollins...`
- `Trick Williams Retains...`
- `IYO SKY earns victory...`
- `Identity Of WWE's Minihausen Revealed...`
- `Mark Davis Defeats Jack Perry, Wins AEW National Championship...`

Corretti come non-spoiler:

- `John Cena Announces New WWE Event...`
- `WWE Announces First-Ever Two-Night TripleMania...`

### Codice da preservare
In `bot_v80_3.py`:

- outcome/reveal terms: linee `9878–9891` circa;
- announcement non-spoiler terms: linee `9893–9899` circa;
- hard validation outcome/reveal: linee `9910–9913`;
- exclusion announcement/non-outcome: linee `9916–9921`;
- floor spoiler escluso per announcement: linee `9930–9935`.

### Nota di non regressione
Non tornare a una logica solo keyword tipo `spoiler`, `revealed`, `during Backlash`. La distinzione importante è:

```text
outcome/reveal concreto => spoiler
announcement/non-outcome => non spoiler
```

---

## 2. Pre-show spoiler obsoleto

### Comportamento considerato corretto
Un articolo pre-show del tipo:

- `Opening Match Revealed`
- `Match Order Reportedly Revealed`
- `Spoiler Lineup`
- `Full Match Card`

non deve più essere pubblicato/spinto come spoiler se nel sistema è già stato rilevato un risultato/report reale dello stesso evento.

Questo evita di pubblicare una preview come `[SPOILER]` quando il match o l'evento è già finito.

### Esempi osservati e validati
Correttamente bloccati o cappati:

- `WWE Backlash 2026 Match Order Reportedly Revealed`
- `WWE Backlash Spoiler Lineup...`
- `Spoiler: Opening Match Revealed...` quando l'opener era già stato pubblicato come risultato.

### Codice da preservare
In `bot_v80_3.py`:

- termini pre-show obsolete: linee `9900–9902` circa;
- controllo history/event/result: linee `9896–9907` circa;
- esclusione in `v79_is_live_spoiler_candidate`: linee `9922–9927`;
- esclusione score floor: linee `9930–9935`;
- cap iniziale e finale: linee `9938–9963`.

### Nota di non regressione
Non usare solo l'orario previsto dell'evento come discriminante. È fragile per PLE fuori USA, fusi orari e feed ritardati. Il criterio stabile è:

```text
pre-show spoiler + result/report già rilevato per lo stesso evento => obsoleto
```

---

## 3. Dedupe semantico stabile pre-scraping/pre-Gemini

### Comportamento considerato corretto
Il bot deve bloccare rewrite cross-source o cross-title della stessa news **prima** di consumare scraping pesante, Gemini e minuti GitHub Actions.

La chiave stabile deve usare:

- entità principali;
- oggetto narrativo stabile;
- action bucket;
- contesto promotion/evento.

### Esempi osservati e validati
Il dedupe ha risolto casi come:

- due versioni della news John Cena Classic con titoli diversi;
- rewrite Big E/Asuka vs IYO SKY/Asuka;
- rewrite Minihausen/Danhausen/identity reveal.

### Codice da preservare
In `bot_v80_3.py`:

- sezione `v79.1.5: stable semantic dedupe before scraping/Gemini`: linee `9966–9971`;
- action bucket: linee `9988–10009`;
- alias canonici: linee `10018–10031`;
- primary entities: linee `10053–10076`;
- named object detection: linee `10088–10131`;
- stable story key: linee `10146–10176`;
- load history con stable keys: linee `10200–10214`;
- override `build_story_signature_v71`: linee `10217–10227`;
- duplicate check su run/history: linee `10230–10240`.

### Nota di non regressione
Non tornare a dedupe basato solo su URL, titolo, slug o semantic_id semplice. I rewrite editoriali cambiano titolo e URL, ma non cambiano il core narrativo.

---

## 4. Report: titolo deterministico da event_key

### Comportamento considerato corretto
I report maturi devono avere titolo deterministico basato su `report_event_key` o `event_key`, non su Gemini e non sul corpo completo.

Questo evita errori già visti:

- report Backlash ribattezzato WrestleMania;
- report Collision ribattezzato Dynamite.

### Titoli corretti attesi
Esempi:

```text
report:wwe-backlash-2026-05-09 => WWE Backlash 2026: risultati e momenti salienti
report:aew-collision-2026-05-09 => AEW Collision del 9 maggio 2026: risultati e momenti salienti
report:wwe-smackdown-2026-05-08 => WWE SmackDown del 8 maggio 2026: risultati e momenti salienti
```

### Codice da preservare
In `bot_v80_3.py`:

- mappa eventi: linee `10255–10280`;
- estrazione data/event key: linee `10283–10306`;
- `detect_report_display_name` title/url-first: linee `10309–10330`;
- `make_deterministic_report_title`: linee `10333–10352`;
- `process_report_pending_item` con forced title: linee `10355–10364`.

### Nota di non regressione
Nei report, il corpo articolo contiene molti riferimenti storici e storyline, quindi **non deve mai essere usato come fonte primaria per nominare lo show**.

---

## 5. Results report protetti dal cap pre-show obsoleto

### Comportamento considerato corretto
Il cap `pre-show spoiler obsoleto` non deve mai colpire `RESULTS_REPORT` o hard results report.

Un report completo può citare card, match order, preview precedenti o opener, ma resta un results report.

### Codice da preservare
In `bot_v80_3.py`:

- bypass del cap in `calculate_importance_score`: linee `10367–10375`;
- bypass del cap in `v723_conservative_score_after_ai`: linee `10377–10385`.

### Nota di non regressione
La regola è:

```text
RESULTS_REPORT > preview/pre-show cap
```

---

## 6. Tier3 sospeso quando ci sono report live/post-show pending

### Comportamento considerato corretto
Durante notti PLE o quando ci sono report maturi/in maturazione, il bot non deve riempire con tier3 deboli.

Questo riduce:

- consumo Gemini inutile;
- pubblicazioni secondarie mentre esistono report prioritari;
- rumore editoriale.

### Codice da preservare
In `bot_v80_3.py`:

- rilevamento report pending: linee `10387–10399`;
- override `editorial_tier`: linee `10401–10406`.

### Nota di non regressione
Non rimuovere senza sostituire con una logica equivalente di priorità report/live.

---

## 7. Social embed via oEmbed WordPress, non HTML raw

### Comportamento considerato corretto
Per Twitter/X, Instagram, YouTube, TikTok, Reddit:

- non preservare blockquote/script/iframe originali;
- non mandare HTML embed raw a Gemini;
- estrarre solo URL canonico;
- reinserire l'URL nudo su riga/paragrafo isolato;
- lasciare a WordPress la generazione automatica dell'oEmbed.

### Esempio corretto
```html
<p>https://x.com/JohnCena/status/2051285686259474866</p>
```

### Codice da preservare
In `bot_v80_3.py`:

- regola architetturale commentata: linee `10410–10417`;
- regex social oEmbed: linee `10419–10422`;
- canonical URL: linee `10425–10447`;
- render embed block come URL isolato: linee `10449–10459`;
- normalize HTML rimuovendo script/blockquote: linee `10462–10497`;
- protect/restore placeholders per AI: linee `10500–10524`;
- post-edit con mapping oEmbed: linee `10535–10606`;
- normalize anche dopo translate ordered blocks/news: linee `10627–10647`.

### Nota di non regressione
Non tornare a preservare il codice embed originale. Il codice embed raw è fragile e Gemini può corromperlo.

---

## 8. Post-edit/localizzazione wrestling italiana

### Comportamento considerato corretto
Non usare un dizionario infinito di pre-normalization. La strada corretta è post-edit Gemini istruito a fare localizzazione editoriale wrestling, non traduzione letterale.

Il post-edit deve:

- eliminare calchi inglesi;
- mantenere i fatti;
- non tradurre titoli/cinture ufficiali;
- usare gergo italiano credibile;
- correggere frasi tipo `match di ripicca`, `bastone di zucchero candito kendo stick`, `giocatore di main event`;
- usare `un promo`, mai `una promo`;
- rendere i report match-by-match meno ripetitivi.

### Codice da preservare
In `bot_v80_3.py`:

- prompt post-edit v80: linee `10551–10587`;
- vincoli terminologici e localizzazione: linee `10556–10572`;
- pipeline di cleanup/guardrails dopo Gemini: linee `10589–10618`;
- fallback sicuro se post-edit fallisce: linee `10620–10624`.

### Nota di non regressione
Non inserire dizionari rigidi troppo estesi prima della traduzione. La correzione deve restare editoriale/contestuale, non una sostituzione cieca.

---

## 9. Runtime version e alias compatibility

### Comportamento considerato corretto
Il file deve esporre il `BOT_VERSION` runtime corretto della patch finale e non deve più crashare per alias mancanti come `normalize_article_type`.

### Codice da preservare
In `bot_v80_3.py`:

- reset `BOT_VERSION` immediatamente prima del main: linee `10650–10657` e `10817–10818`;
- alias `normalize_article_type`: linee `10659–10661`.

### Nota di non regressione
Quando si aggiungono patch in fondo al file, controllare sempre che l'ultimo `BOT_VERSION` sia quello effettivo.

---

## 10. Review package temporaneo

### Comportamento considerato utile in fase review
Con `REVIEW_PACKAGE_ENABLED=1`, il bot deve creare pacchetti di review anche per candidati non pubblicati quando disponibili, includendo:

- metadata;
- original HTML/testo;
- ordered blocks;
- translated HTML;
- run log;
- summary.

Serve solo nel periodo di review e potrà essere rimosso quando le run saranno stabilmente pulite.

### Codice da preservare per ora
In `bot_v80_3.py`:

- env flags e base dir: linee `10672–10678`;
- creazione run dir: linee `10696–10710`;
- `review_record_candidate`: linee `10713–10768`;
- wrapper `process_candidate_item`: linee `10771–10784`;
- `review_finalize_package`: linee `10787–10815`;
- chiamata nel `finally`: linee `10821–10827`.

### Nota
Da migliorare ancora: quando WordPress è offline e il bot salva pending senza processare singolarmente i candidati, può servire un record `pending_wp_offline`. Ma il comportamento conservativo WordPress-offline è corretto: non chiamare Gemini e non tentare publish.

---

## 11. WordPress offline: comportamento conservativo

### Comportamento considerato corretto
Se WordPress/API non è disponibile:

- non chiamare Gemini;
- non provare a pubblicare;
- salvare i candidati plausibili in pending;
- terminare senza crash.

### Esempio osservato
Run `v80_3_review_package_all_attempted` del 2026-05-10 07:15:

```text
[BOT] WordPress offline: assegno score e salvo solo i candidati che sarebbero stati pubblicati, senza chiamare Gemini.
[PENDING] Candidati salvati per dopo: 2
```

### Nota di non regressione
Questo comportamento evita spreco di token e minuti quando il collo di bottiglia è WordPress, non il contenuto.

---

## Checklist da applicare prima di ogni nuova patch

Prima di rilasciare una nuova versione, verificare che:

1. gli outcome concreti continuino a ricevere `[SPOILER]`;
2. gli announcement non-outcome non ricevano `[SPOILER]`;
3. le preview/pre-show obsolete vengano cappate o bloccate;
4. i results report non siano colpiti dai cap preview;
5. i report abbiano titolo da `event_key`;
6. il dedupe stabile blocchi rewrite cross-title/cross-source;
7. gli embed social siano URL oEmbed canonici e non HTML raw;
8. il post-edit non rompa placeholder/embed;
9. `BOT_VERSION` runtime sia quello corretto;
10. WordPress offline non produca chiamate Gemini inutili.

---

## Regola finale

Queste parti sono considerate **codice stabile di produzione**. Ogni modifica futura deve essere una patch incrementale e testabile, non una riscrittura ampia.
