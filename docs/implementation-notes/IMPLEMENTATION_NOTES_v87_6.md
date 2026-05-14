# Implementation notes v87.6

La causa del problema non era il salvataggio runtime: i log confermavano la scrittura in `published/` e `logs/master_log_events.jsonl`.
Il problema era la persistenza fuori dal runner GitHub Actions.

Il nuovo workflow:
1. esegue `python bot.py` senza interrompere subito il job;
2. salva l'exit code in `.bot_exit_code`;
3. committa `published/`, `published_html_review/`, `logs/`, `pending_queue.json`, `history.json`, `confirmed_published_reports.json`, `review_bundle_latest.zip`;
4. carica gli stessi percorsi come artifact della run;
5. fallisce il job solo alla fine se il bot aveva exit code non-zero.

Serve `permissions: contents: write` nel workflow.
