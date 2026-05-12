# CHANGELOG v85

Base: `bot_v84_1.py`.

## Modifiche
- Pubblicazione draft-first: quando c'è una featured image, il post viene creato come draft con `featured_media` già impostata e solo dopo viene pubblicato.
- Upload featured image prima del publish, con cache interna per evitare doppio download/upload nella stessa run.
- Health check WordPress più restrittivo: OK solo su status 200/201 dell'endpoint posts; 429 e altri 4xx non sono più considerati disponibili.
- Scrittura atomica di `history.txt` e `pending_articles.json` tramite file temporaneo + rename.
- Hard cap totale: massimo 5 pubblicazioni complessive per run, includendo pending e nuove news.
- Fix URL YouTube: preserva `watch?v=...` e normalizza anche `youtu.be` / embed / nocookie senza troncare l'ID video.
- La pipeline strutturata passa ora sempre `img_url` a `create_post_without_image`, così la featured può essere caricata prima del publish anche negli articoli tradotti a blocchi.

## Note
- La v85 mantiene gli override e i guardrail della v84.1.
- Non è una rifattorizzazione del file monolitico: sono override mirati sopra la base v84.1.
