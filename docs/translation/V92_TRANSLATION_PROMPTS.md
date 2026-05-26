# OpenWrestlingTV Bot v92 - Translation Prompt Strategy

## Stato

Documento operativo per la rifondazione dei prompt di traduzione v92.

Obiettivo: separare la politica editoriale di traduzione dal codice, rendendo chiaro quale prompt si usa per ogni tipo di contenuto.

I prompt storici vengono cannibalizzati: si mantengono le regole migliori, ma vengono rese generiche e modulari.

---

## Principio generale

Ogni tipo di contenuto deve avere un prompt dedicato.

```text
report/results -> prompt report_blocks_faithful
news -> prompt news_article_translation
titolo news -> prompt news_title_rewrite
analisi editoriale -> prompt editorial_analysis
post-edit -> prompt stylistic_postedit
repair -> prompt single_sentence_repair / missing_facts_repair
```

Non esiste un prompt unico valido per tutto.

---

## Elementi da proteggere sempre

Prima della traduzione il sistema deve identificare e proteggere:

```text
nomi propri
ring name
nomi di show
eventi
stable/fazioni
stipulazioni
nomi ufficiali dei titoli/cinture
date
numeri
sigle
nomi delle mosse riconoscibili
placeholder/embed ID
```

Se il modello non e' sicuro, deve copiare esattamente dal sorgente.

---

## Whitelist / termini da non tradurre

Questa lista deve diventare configurabile, ma il principio e' stabile.

### Titoli e cinture

Non tradurre mai i nomi ufficiali dei titoli/cinture.

Esempi:

```text
World Heavyweight Championship
Intercontinental Championship
United States Championship
WWE Championship
WWE Women's Championship
Women's World Championship
NXT Championship
NXT North American Championship
AEW World Championship
AEW World Tag Team Championship
TNA Knockouts Title
TNA Knockouts World Championship
AAA Mega Championship
Money in the Bank
```

### Stipulazioni e match type

Restano in inglese:

```text
tag team match
mixed tag team match
6-Man Tag Team Match
8-Woman Tag Team Match
10-Man Tag Team Match
triple threat match
fatal four-way match
4-Way
5-Way
Six-Pack Challenge
Last Man Standing
Last Woman Standing
WarGames
Royal Rumble
Hell in a Cell
cage match
steel cage match
ladder match
street fight
no disqualification match
title match
```

### Gergo wrestling

Restano normalmente in inglese, salvo contesto:

```text
match
promo
segment
storyline
push
turn
feud
stable
tag team
heel
face
main event
main eventer
```

Regole:

```text
promo e' maschile: un promo, mai una promo
chop e' femminile: le chop, delle chop
```

### Mosse

Le mosse riconoscibili restano in inglese, ma la frase deve essere italiana naturale.

Esempi:

```text
prova una Spear
lo colpisce con una Superkick
connette con la Curb Stomp
chiude con l'Operation Dragon
mantieni Tongan Death Grip in inglese
```

---

## Regole lessicali obbligatorie

```text
release / released / roster cuts -> licenziamento, licenziato/licenziata, addio, uscita
mai rilascio/rilasciato

retirement -> ritiro/ritirarsi
mai pensione/pensionamento

cleared / not cleared -> autorizzato/non autorizzato a lottare
mai pulito/non pulito

grudge match -> regolamento di conti oppure resa dei conti, secondo contesto
```

---

## Forme da evitare

```text
SmackDown di WWE -> SmackDown
durante l'episodio di WWE Raw -> nell'ultima puntata di Raw
si e' aperto riguardo -> ha parlato di
ha affrontato una sfida -> ha combattuto / e' salito sul ring
e' stato coinvolto in un match -> ha preso parte a un match
ha fatto il suo ritorno -> e' tornato
ha ottenuto una vittoria -> ha vinto
connected with a spear -> ha colpito con una Spear
tide turned -> l'inerzia del match e' cambiata
match di ripicca -> regolamento di conti / resa dei conti
giocatore di main event -> nome da main eventer
una promo -> un promo
```

Evitare parole innaturali o troppo tradotte:

```text
stella
rivelatrice
prevalenza
coinvolto in una dinamica
all'interno della compagnia
televisione nazionale
si sono ritrovati come tag team
```

---

## Prompt: report/results

Uso: report show settimanali, PLE/PPV, recap completi.

Input atteso:

```json
{
  "title": "titolo deterministico non modificabile",
  "source_title": "titolo fonte",
  "blocks": [
    {"i": 0, "type": "paragraph", "text": "..."},
    {"i": 1, "type": "heading", "text": "..."}
  ]
}
```

Regole fondamentali:

```text
- Questo e' un report risultati/recap, non una news breve.
- Coprire l'intero show dall'inizio alla fine.
- Non saltare nessun match, promo, segmento o sviluppo importante.
- Mantenere l'ordine cronologico.
- Ogni match deve includere il vincitore se presente.
- L'ultimo segmento dello show deve essere sempre incluso.
- Ogni blocco tradotto deve restare aderente al blocco originale.
- Non fondere blocchi diversi.
- Non cambiare ordine.
- Non sintetizzare.
- Se il testo sorgente e' lungo, si possono rendere piu agili le fasi di lotta, ma non tagliare inizio, fine o snodi narrativi.
```

Output richiesto:

```json
{"items":[{"i":0,"text":"..."}]}
```

Note:

```text
Il titolo del report e' deterministico e non passa dall'AI.
Gli embed e le immagini sono reinseriti dal codice.
Il modello traduce solo blocchi testuali.
```

---

## Prompt: news article translation

Uso: news normali selezionate dalla news_pipeline.

Regole fondamentali:

```text
- Riscrivere in italiano la specifica notizia come articolo per sito italiano di news wrestling.
- Non fare traduzione letterale.
- Conservare tutti i fatti.
- Non mescolare con altre news.
- Non inventare dettagli.
- Rimuovere riferimenti promozionali alla fonte, commenti, hub, stay tuned, copertura live.
- Citazioni importanti in <blockquote>.
- HTML semplice: <p>, <b>, <blockquote>.
- Titolo scritto da AI ma semanticamente aderente.
```

Output richiesto:

```json
{"titolo":"...","testo":"html","categoria":"WWE"}
```

---

## Prompt: title rewrite

Uso: titolo news, non report.

Regole:

```text
- Riscrivi solo il titolo in italiano naturale.
- Deve sembrare una headline italiana, non tradotta parola per parola.
- Massimo 110 caratteri salvo necessita assoluta.
- Non inventare fatti.
- Non aggiungere clickbait.
- Mantieni nomi propri, promotion, show e titoli ufficiali.
- Non tradurre titoli/cinture ufficiali.
- released/release/departure non e' rilascio: usa licenziamento, addio o uscita.
```

Output:

```json
{"titolo":"..."}
```

---

## Prompt: editorial analysis

Uso: prima della traduzione news, per classificare e generare note.

Classi ammesse:

```text
PREVIEW
RESULTS_REPORT
POST_SHOW_NEWS
OPINION
RUMOR
OTHER
```

Categorie ammesse:

```text
WWE
AEW
NXT
TNA
World
Business
Editoriali
```

Regole:

```text
- RESULTS_REPORT -> Editoriali.
- Preview solo se l'articolo presenta davvero un evento futuro.
- News post-show non e' preview.
- Rumor/backstage -> categoria promotion, non Business salvo focus corporate reale.
- Business solo per corporate reale, media rights, ricavi, executive, acquisizioni, contratti aziendali.
- Dark Side of the Ring/Vice/docuserie -> World.
```

Output:

```json
{
  "article_type":"POST_SHOW_NEWS",
  "category":"WWE",
  "translation_notes":["..."]
}
```

---

## Prompt: stylistic post-edit

Uso: rifinitura su traduzione gia corretta nei fatti.

Regole:

```text
- Fare solo post-editing stilistico.
- Rendere testo e titolo naturali, fluidi, giornalistici.
- Eliminare calchi inglesi, ripetizioni, frasi macchinose.
- Non aggiungere informazioni.
- Non tagliare fatti rilevanti.
- Non cambiare enfasi editoriale.
- Non modificare nomi, date, numeri, eventi, titoli ufficiali, sigle e stipulazioni.
- Non rimuovere immagini, figure, iframe, embed, link fonte o CTA gia presenti.
- Se una frase e' gia buona, lasciarla invariata.
```

---

## Prompt: repair

Il repair non deve essere una fase generica sempre attiva. Deve essere un tool mirato.

Usi ammessi:

```text
single_sentence_repair -> corregge una frase con errore lessicale/status/carriera
missing_facts_repair -> reinserisce fatti editoriali mancanti, se rilevati
```

Non deve modificare l'intero articolo senza motivo.

---

## Integrazione bot v92

### Da integrare subito

```text
report_blocks_faithful
termini protetti / whitelist base
log chain + modello scelto
```

### Da integrare dopo news pipeline

```text
editorial_analysis
news_article_translation
news_title_rewrite
stylistic_postedit
soft-pool-aware translation notes
```

### Da tenere documentato per ora

```text
repair generale
missing facts repair
```

Il repair rientra solo dopo che le pipeline principali sono stabili.
