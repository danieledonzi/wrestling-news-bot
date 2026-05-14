# V88 - Media/artifact cleanup release

## Situazione prima della v88

Dalle ultime run risultavano quattro regressioni residue:

1. I report venivano pubblicati, ma gli embed non sempre entravano nel body. Il caso AEW Dynamite mostrava `Embed trovati: 19`, ma `BLOCKSEQ ... embed=0`, quindi il percorso strutturato marcava `structured_used=True` e poi passava `embed_urls=[]` al publish.
2. In alcuni articoli mancavano immagini inline per lo stesso motivo: quando la traduzione strutturata era attiva, il ramo legacy passava `inline_images=[]` anche se lo scraping aveva trovato media.
3. `published/` e `logs/master_log_events.jsonl` venivano creati nel runner, ma non committati perché il workflow vedeva `!!` su file ignorati e non li forzava correttamente nello staging.
4. I file `run_YYYY-MM-DD HH:MM:SS_summary.json` contenevano `:`, bloccando o complicando upload/commit artifact.

## Interventi v87.8

La v87.8 è considerata una pulizia workflow-only: staging forzato dei file ignorati, gestione rename/sanitizzazione e commit anche di `logs/`, `published/`, `published_html_review/`.

## Interventi v88

- Media recovery indipendente dal block engine.
- Mappa posizionale degli embed costruita direttamente dall'HTML sorgente, inclusi `rsn-lazy` e `data-rsn-html`.
- Se il block engine trova `embed=0` ma lo scraper trova embed, la v88 forza `V873_EXPECTED_EMBEDS_BY_URL`.
- Prima del publish, gli embed mancanti vengono reinseriti nella posizione approssimata dal numero di paragrafi testuali precedenti.
- Se il positional guard reinserisce tutti gli embed, `embed_urls` viene svuotato prima dei vecchi appender per evitare duplicati a fondo articolo.
- Recupero immagini inline se il body finale non contiene `<img>` e lo scraper aveva trovato immagini.
- Sanitizzazione nomi file anche lato bot.
- Workflow v88 con `git add -A` + `find ... git add -f` per file ignorati.
- Gemini 3 Flash Preview confermato come `gemini-3-flash-preview`.
