# V82 Implementation Notes

## Strategia
La v82 parte da v81.1 e aggiunge solo un layer finale di qualita percepita. L'obiettivo e ridurre l'odore AI senza rompere la stabilita ottenuta su dedupe, spoiler, oEmbed, anti-omissione e review bundle.

## Flusso effettivo

```text
traduzione strutturata v72/v80
-> post-edit v80/v81
-> anti-omissione v81
-> microtext AI-smell repair v82
-> titolo v82 se necessario
-> pubblicazione
-> published_html_review + review_bundle_latest.zip
```

## Microtesti
La v82 estrae microtesti da elementi HTML semplici:
- `<p>`
- `<li>`
- `<h2>`
- `<h3>`

Vengono esclusi elementi che contengono markup rischioso:
- link;
- immagini;
- figure;
- iframe;
- blockquote;
- script;
- embed social.

Questo protegge la pipeline oEmbed e impedisce al modello di danneggiare media e link.

## Safety check
Una repair viene scartata se:
- rimuove URL presenti nel testo precedente;
- riduce troppo il numero di parole;
- espande troppo il numero di parole;
- restituisce testo vuoto o troppo corto.

## Variabili ambiente

```yaml
V82_EDITORIAL_REALISM_ENABLED: "1"
V82_AI_SMELL_REPAIR_ENABLED: "1"
V82_TITLE_REPAIR_ENABLED: "1"
V82_MAX_MICROTEXTS: "28"
V82_MAX_TEXT_CHARS: "12000"
V82_MIN_REPAIRED_WORD_RATIO: "0.90"
V82_MAX_REPAIRED_WORD_RATIO: "1.18"
```

## Nota
Il layer v82 puo aggiungere una chiamata Gemini per articolo, ma solo quando il prefilter trova segnali sospetti o quando l'articolo e abbastanza lungo/opinion-oriented da meritare review stilistica.
