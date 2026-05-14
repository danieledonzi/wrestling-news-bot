# Changelog v87.3 - Title gate and positional embed guard

Versione: `v87_3_title_gate_positional_embed_guard`

## Correzioni principali

- Rimosso `gemini-3-flash` dalle chain di default perché il nome modello ha restituito `404 NOT_FOUND` via API `v1beta`.
- Rafforzate le chain dopo cooldown: i task critici, soprattutto `title` ed `emergency_title`, provano tutti i modelli validi prima di fallire.
- Aggiunto hard gate titolo: nessun fallback deterministico o slug inglese può arrivare al publish.
- Se Gemini non produce un titolo italiano valido, l'articolo viene fermato e salvato in pending con retry.
- Corretto il salvataggio `confirmed_published_reports`: ora accetta solo veri true-results report canonici.
- Aggiunta reintegrazione posizionale degli embed: gli embed mancanti vengono reinseriti nel punto approssimativo originale, non in fondo all'articolo.
- Aggiunta pulizia specifica X/Twitter: se esiste embed X valido, il testo del tweet, firme tipo `- Nome (@handle) data` e link `t.co` residui vengono rimossi.
- Corretto il dedupe embed v87.2 che poteva cancellare il contenuto dello stesso paragrafo oEmbed durante il pass finale.
- Rafforzata la review: warning su titoli non tradotti, `twitter.com` residui e `t.co` residui quando è presente un embed X.

## Comportamento desiderato

- Titolo sempre generato/tradotto da Gemini.
- X/Twitter sempre in forma canonica `https://x.com/user/status/id`.
- YouTube una sola volta, senza URL grezzi duplicati.
- Embed preservati nella sequenza editoriale originale.
