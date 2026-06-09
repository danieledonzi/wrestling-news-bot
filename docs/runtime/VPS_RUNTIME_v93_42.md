# OpenWrestlingTV v93.42 - VPS clean runtime

## Obiettivo

`bot.py` e' l'entrypoint stabile per il cron VPS:

```bash
cd /opt/owtv/wrestling-news-bot
git pull --ff-only
python bot.py
git status --short
```

Dopo una run normale, i sorgenti tracciati non devono risultare modificati.

## Comportamento atteso

`python bot.py`:

1. verifica i marker del sorgente consolidato v93;
2. se i marker sono presenti, salta automaticamente il bootstrap storico delle patch;
3. esegue `newsroom_runner.py`;
4. stampa un controllo finale:

```text
[BOT v93_42_vps_clean_runtime] vps_clean_check=ok tracked_source_status=clean
```

## Modifiche ammesse dopo una run

Sono ammessi solo file runtime ignorati da Git, per esempio:

- `logs/`
- `artifacts/`
- `published/`
- `published_html_review/`
- `state/`
- `history.txt`
- `pending_articles.json`
- `failed_articles.json`
- `processed_urls.json`
- `skipped_history.json`
- `confirmed_published_reports.json`
- `review_bundle_latest.zip`

Questi file non devono bloccare il normale flusso VPS.

## Modifiche non ammesse

Dopo una run non devono comparire modifiche a sorgenti tracciati come:

- `agents/*.py`
- `modules/*.py`
- `bot_v92.py`
- `newsroom_runner.py`
- `bot.py`
- workflow o script di patch

Se compaiono, significa che il sorgente non e' davvero consolidato oppure che una patch runtime sta ancora mutando file sorgente.

## Override di emergenza

Per forzare il bootstrap storico delle patch:

```bash
OWTV_FORCE_PATCH_BOOTSTRAP=1 python bot.py
```

Per saltarlo manualmente:

```bash
OWTV_SKIP_PATCH_BOOTSTRAP=1 python bot.py
```

In produzione VPS, il comportamento normale e' non impostare nessuna delle due variabili.
