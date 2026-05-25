# EDITORIAL_RULES v91

## Regola principale

La v91 decide prima il valore editoriale della storia e solo dopo consente scraping/traduzione/pubblicazione.

La traduzione non deve essere usata per valutare se un articolo e' pubblicabile.

## Hard skip iniziale

Un URL gia' pubblicato o scartato definitivamente non deve entrare in:

```text
story signature
core assignment
scoring
scraping
Gemini
pending
```

## Cheap classifier

Il cheap classifier puo' bloccare senza Gemini solo contenuti chiaramente non pubblicabili:

- preview/listing espliciti;
- viewership/ratings routine;
- lifestyle/foto/curiosita' deboli;
- clickbait o meta-commentary senza fatto nuovo.

Il cheap classifier non deve bloccare:

- risultati evento;
- ritorni/debutti;
- title changes;
- news business/TV deal;
- controversie community rilevanti;
- fan backlash/logistica evento rilevante.

## Eventi e report

Una puntata/evento puo' generare:

1. report completo;
2. news autonome sui risultati principali;
3. news di contesto/logistica;
4. discussione strategica.

Il report non blocca automaticamente le news autonome.

Un event_key generico non basta per dichiarare duplicato un articolo.

## Discussion value

Una soft news non e' trash se puo' generare discussione autonoma nella community.

Esempi pubblicabili o da strategic pool:

- WWE vs AEW;
- MJF/Tony Khan/Triple H/TKO;
- TV deal/media rights;
- push evidente;
- fan backlash;
- problemi logistici evento;
- direzione creativa di star importanti.

Esempi skip:

- quote generica da podcast senza fatto;
- vecchio aneddoto senza aggancio attuale;
- reaction social banale;
- lifestyle non wrestling.

## Traduzione

La traduzione parte solo quando la decisione e':

```text
publish_now
publish_candidate effettivamente selezionata
```

Non si traduce cio' che andra' in skip_final o soft_pool.

## Cache analisi

L'analisi editoriale v91 viene salvata in:

```text
article_analysis_cache_v91.json
```

Lo stesso URL non deve richiedere una nuova analisi nelle run successive salvo modifica sostanziale.
