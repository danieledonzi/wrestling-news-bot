# v87.6 - Persist published artifacts workflow

## Fix bloccante
- Gli artifact scritti dal bot (`published/`, `published_html_review/`, `logs/`) ora vengono persistiti dal workflow GitHub Actions.
- Il workflow committa e pusha le modifiche prodotte dal bot nel repository.
- Gli artifact vengono anche caricati con `actions/upload-artifact` come backup della run.
- Il bot step salva l'exit code in `.bot_exit_code`; la persistenza gira comunque e solo dopo il job fallisce se il bot è fallito.

## Note
- La v87.5 scriveva i file nel filesystem effimero del runner, ma senza commit/upload quei file sparivano a fine job.
- Nessuna modifica a scoring, embed, modelli o title gate.
