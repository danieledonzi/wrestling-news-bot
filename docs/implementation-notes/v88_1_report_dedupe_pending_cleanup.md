# v88.1 — Report dedupe pending cleanup

## Obiettivo

Rendere permanente la logica che impedisce ai report true-results già pubblicati di rientrare nella pending queue quando WordPress o il dedupe semantico li riconoscono come duplicati.

## Problema osservato

Nelle run v87/v88 un report già pubblicato poteva essere intercettato da `DEDUPE BLOCKED`, ma subito dopo una logica legacy lo rimetteva in pending con messaggi del tipo:

```text
[PENDING v86.8] Mantengo true-results in coda: non pubblicato né confermato su WordPress
```

Questo comportamento è errato: se WordPress/dedupe trova il post già pubblicato, il report è da considerare confermato.

## Regola implementativa

Se un true-results report viene bloccato da dedupe contro un post WordPress esistente:

1. il `report_key` viene marcato in `confirmed_published_reports.json`;
2. il report viene marcato anche in history;
3. la pending viene pulita per `report_key` e URL;
4. `add_pending_report_article` e `add_pending_article` non possono reinserirlo.

## Log attesi

```text
[REPORT v88.1] True-results confermato da DEDUPE BLOCKED: report:aew-dynamite-2026-05-13 -> WP 4515
[PENDING v88.1] Non salvo report confermato in pending: report:aew-dynamite-2026-05-13
```

## Nota tecnica

La patch v88.1 deve vivere direttamente in `bot.py`. Il workflow può applicare lo script `scripts/apply_bot_patch_v88_1.py` una sola volta e committare la modifica; dopo il commit, lo step diventa no-op.
