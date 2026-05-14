# OpenWrestlingTV Bot v87.4 - Changelog

## Versione
`v87_4_publish_artifact_masterlog_restore`

## Fix bloccante
Ripristinato il salvataggio locale obbligatorio dopo ogni pubblicazione WordPress riuscita.

### Nuovo comportamento
Dopo un publish WordPress con successo, il bot deve ora eseguire sempre:

1. salvataggio articolo in `published/`;
2. salvataggio metadati articolo in `published/`;
3. append su `logs/master_log_events.jsonl`;
4. riepilogo finale su `logs/run_artifacts_latest.json`;
5. flush del master log principale.

## Log attesi

```text
[PUBLISHED v87.4] Articolo salvato: published/...
[MASTER LOG v87.4] Evento salvato: publish_artifact_saved <post_id>
[RUN ARTIFACTS v87.4] master_log=ok published=N errors=0 status=ok
```

## Altre correzioni

- Il post-publish artifact hook è idempotente per `wp_post_id`/URL.
- Se WordPress pubblica ma il salvataggio locale fallisce, la run lo dichiara esplicitamente.
- La history forte dei report viene ulteriormente ristretta a soli true-results report con key canonica `report:<show>-YYYY-MM-DD`.
- Il summary finale distingue pubblicazioni reali dagli hook legacy duplicati.

## Non modificato

- Scoring.
- Model routing v87.3.
- Embed positional guard v87.3.
- Title hard gate v87.3.
