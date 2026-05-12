# CHANGELOG v82

## Versione
`v82_editorial_realism_microtext_adaptation`

## Obiettivo
Aumentare la qualita percepita degli articoli prima del lancio pubblico, riducendo calchi, sintassi da traduzione automatica e titoli con residui inglesi, senza toccare la logica stabile di v81.1.

## Modifiche principali

### 1. Layer newsroom realism
Dopo il post-edit v81.1, il testo finale viene diviso in micro-paragrafi reali (`<p>`, `<li>`, `<h2>`, `<h3>`). Gemini controlla solo questi microtesti e restituisce repair mirate per le frasi che suonano da AI/traduzione.

### 2. Repair mirato, non riscrittura globale
La v82 non riscrive tutto l'articolo. Ripara solo i microtesti problematici e scarta automaticamente repair che:
- accorciano troppo il testo;
- espandono troppo il testo;
- rimuovono URL/embed;
- toccano markup rischioso come link, iframe, figure, immagini o blockquote.

### 3. Prompt anti-calco senza dizionario rigido
Non viene introdotta una lista hardcoded di idiomi da sostituire. Il prompt chiede al modello di riconoscere idiomi/metafore inglesi e renderli con equivalenti italiani naturali, preservando fatti, quote, nomi e titoli ufficiali.

### 4. Headline realism
Aggiunto un passaggio leggero sui titoli quando restano segnali come:
- residui inglesi (`Future di`, `made by`, `Breaking down`);
- titoli ufficiali tronchi;
- headline troppo tradotte o poco naturali.

### 5. Non modificato
Restano invariati:
- scoring principale;
- dedupe;
- spoiler;
- embed/oEmbed;
- anti-omissione v81;
- review flat archive;
- review bundle cumulativo.

## Log attesi

```text
VERSION [v82_editorial_realism_microtext_adaptation (...)]
[VOICE v82] AI-smell check OK: nessuna repair (...)
[VOICE v82] Micro-repair applicate: N
[VOICE v82] Layer newsroom realism applicato
[TITLE v82] Headline realism applicato (...): ...
[REVIEW BUNDLE v81.1] Creato bundle cumulativo: review_bundle_latest.zip (...)
```
