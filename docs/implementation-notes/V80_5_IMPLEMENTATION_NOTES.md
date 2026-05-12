# v80.5 Implementation Notes

## Obiettivo

Rendere automatico il pacchetto di review senza richiedere modifiche manuali al workflow o variabili ambiente obbligatorie.

## Modifica principale

In v80.4 il codice aveva:

```python
REVIEW_PACKAGE_ENABLED = os.getenv("REVIEW_PACKAGE_ENABLED", "0")...
```

In v80.5 diventa:

```python
REVIEW_PACKAGE_ENABLED = os.getenv("REVIEW_PACKAGE_ENABLED", "1")...
```

Quindi la review e' ON di default. Per spegnerla:

```yaml
REVIEW_PACKAGE_ENABLED: 0
```

## Punto esatto della pipeline

Il wrapper `process_candidate_item()` registra l'item nel `finally`, quindi salva anche casi `published`, `skipped`, `pending`, `validation_fail`, `model_fail`, `exception`.

I campi `original.html`, `original_text.txt`, `ordered_blocks.json`, `translated.html` vengono scritti quando il candidato e' arrivato abbastanza avanti da produrli.

## GitHub Actions

`cron_v80_5.yml` carica automaticamente:

```yaml
path: review_packages/
```

come artifact `review-packages`.
