# IMPLEMENTATION_NOTES v86.5

## Files changed
- `bot.py`
- `cron.yml`

In questo pacchetto:
- `bot_v86_5.py`
- `cron_v86_5.yml`

## Problema risolto
La v86.4 ha superato i vecchi gate su URL/history/title, ma ha allargato troppo `report-like`, trattando come report completi anche backstage update, ratings report e news già pubblicate.

## Modifiche principali

### 1. Gate stretto `TRUE_RESULTS_REPORT`
Aggiunta funzione:

```python
v865_is_true_results_report(title, link, summary)
```

Richiede marker risultati + show riconosciuto + data, ed esclude viewership/ratings/backstage/update/status/appearance/release/exit/pushing/opinion/preview.

### 2. Override del detector largo v86.4
`v864_is_report_like_feed_item()` ora restituisce true solo per `v865_is_true_results_report()`.

### 3. History cleanup mirato
`load_history()` rimuove in memoria solo record riconducibili a veri results report. Non rimuove più chiavi broad come `report:wwe-raw-backstage-update...`.

### 4. Pending/process gate
`process_candidate_item()` autorizza il bypass report solo per true results report e solo dopo verifica WordPress stretta.

### 5. Vecchie logiche incompatibili
Le vecchie logiche non vengono eliminate fisicamente dal file per compatibilità, ma vengono rese subordinate al gate v86.5. Il comportamento attuale desiderato è: vecchi gate generici non comandano sui veri report; falso report-like non riceve più privilegi.

## Variabili nuove

```yaml
V86_5_TRUE_RESULTS_REPORT_GATE_ENABLED: "1"
V86_5_STRIP_TRUE_REPORT_HISTORY_ENABLED: "1"
```
