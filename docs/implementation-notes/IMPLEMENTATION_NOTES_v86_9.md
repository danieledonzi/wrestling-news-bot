# Implementation Notes v86.9

## Report source recovery
The old report processor expected report items to have a `sources[]` list. Normal feed items do not always have that structure, so `choose_best_report_source()` could return `None` even though the current item had a valid report URL.

v86.9 overrides `choose_best_report_source()`:

- first tries the existing aggregate-source logic;
- if no aggregate source is valid, it scrapes the current item URL;
- computes `report_source_completeness_score()`;
- returns a normal best-source dict if usable.

The log now explains why the fallback is used:

```text
[REPORT v86.9] Nessuna fonte aggregata valida: sources=0; provo candidato corrente
[REPORT v86.9] Fonte corrente valutata: len=... completeness=...
```

## Report-ready re-entry prevention
When a source is chosen, the report processor creates an internal `kind=report_ready` item. Older v86.5/v86.6 wrappers could classify that item again as `kind=report`, causing it to re-enter the report gate. v86.9 temporarily disables the true-results detector only for that internal `report_ready` hop.

## Report priority
`build_candidates()` is wrapped so strict true-results reports are processed before normal news, even if a normal article has a slightly higher score.

## Commentary cap
Some opinion/commentary pieces were misclassified by AI as `POST_SHOW_NEWS` and boosted to 100. v86.9 caps patterns such as `reveals why`, `doesn't think`, `believes`, `explains why`, `comments on`, and named-commentator takes unless the article contains a concrete new fact.
