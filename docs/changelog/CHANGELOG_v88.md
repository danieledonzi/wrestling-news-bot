# Changelog v88

- Fix embed report assenti quando `structured_used=True` e `BLOCKSEQ embed=0`.
- Fix immagini inline assenti quando il ramo strutturato scartava `inline_images` legacy.
- Fix persistenza repository: `git add -A` + `git add -f` per file ignorati.
- Fix nomi file artifact con caratteri non portabili.
- Confermata disponibilità `gemini-3-flash-preview` nelle chain.

## v88.2 - editorial performance guards

- Aggiunto cap per articoli `OTHER`/feature non-news: default 65.
- Aggiunto cap più severo per feature con molti numeri storici di eventi, es. WrestleMania 28/29/32/35: default 60.
- Aggiunto pre-guard per saltare feature/OTHER non-results prima di traduzioni lunghe e costose.
- Aggiunto cap celebrity/crossover: pubblicabile ma sotto hard news se non contiene impatto reale su roster, contratto, titolo, infortunio o release.
- Ridotto rischio di usare `translate_report` su feature lunghe non urgenti.
- Mantenuti i punti previsti per la v88.2 originaria: `gemini-3.1-flash-lite` e `gemini-3-flash-preview` ammessi; `gemini-3-flash` e `gemini-3.1-flash` vietati; fallback multipli obbligatori.
- Workflow v88.2 aggiornato con permessi espliciti, `fetch-depth: 0`, configurazione Git separata e chain modelli completa.
- Nota: il patching runtime v88.1/v88.2 resta transitorio; la prossima fase deve consolidare la logica direttamente in `bot.py`.
