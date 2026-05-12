# V85 Implementation Notes

Questa versione parte da `bot_v84_1.py` e aggiunge un layer finale di override prima dell'entrypoint runtime.

## Publish safety

La funzione `create_post_without_image()` è stata sovrascritta per:

1. validare il body prima della creazione;
2. caricare la featured image prima del publish;
3. creare il post come `draft` quando c'è una featured image;
4. creare il draft già con `featured_media` impostata;
5. pubblicare il draft solo dopo la creazione corretta.

Se l'immagine esiste ma l'upload fallisce, la pubblicazione viene bloccata quando `V85_REQUIRE_FEATURED_BEFORE_PUBLISH=1`.

## Stato e anti-race

`save_to_history()` e `save_pending_articles()` ora scrivono su file temporaneo e fanno `os.replace()`, riducendo il rischio di file corrotti. La concurrency GitHub resta comunque il blocco principale contro run parallele.

## Limite run

È stato aggiunto `V85_MAX_TOTAL_PUBLISHED_PER_RUN`, default `5`. Il conteggio è globale e include sia pending sia nuove news.

## YouTube URL fix

`clean_tracking_params()` e `normalize_embed_url()` sono stati sovrascritti per preservare sempre il parametro `v=`:

- `https://www.youtube.com/watch?v=ID`
- `https://youtu.be/ID`
- `https://www.youtube.com/embed/ID`
- `https://www.youtube-nocookie.com/embed/ID`

La funzione `v85_repair_youtube_urls_in_text()` ripassa anche l'HTML finale prima del publish per normalizzare eventuali URL YouTube rimasti nel testo.

## Variabili cron aggiunte

```yaml
V85_DRAFT_FIRST_ENABLED: "1"
V85_REQUIRE_FEATURED_BEFORE_PUBLISH: "1"
V85_MAX_TOTAL_PUBLISHED_PER_RUN: "5"
```
