# v85.1 - anti-waste e log cleanup

Base: v85.

## Fix principali

- Ridotto rumore dei log spoiler: la stessa decisione spoiler viene loggata una sola volta per articolo/URL.
- Skip pre-Gemini per preview/preshow obsoleti e future card announcement sotto soglia.
- Skip pre-Gemini per news core già presenti in history, per evitare sprechi su articoli già coperti.
- Skip pre-scraping dei report pending già pubblicati o già presenti in history/WP.
- Storm mode più severa sugli articoli opinion/filler sotto soglia.
- Protezione anti-retry Gemini: se sullo stesso articolo si accumulano troppi 503, la lavorazione viene interrotta.
- Workflow aggiornato con `git pull --rebase` prima del push dello stato.

## Note

Restano inalterate le protezioni v85: draft-first publishing, featured image prima del publish, health check restrittivo, max 5 articoli per run, atomic write e fix YouTube URL.
