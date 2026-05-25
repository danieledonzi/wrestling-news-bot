# IMPLEMENTATION_NOTES v91.5

## Versione

`v91_5_html_integrity_block_safe_repair`

## Obiettivo

v91.5 e' una patch tecnica di sicurezza sulla qualita' dell'HTML pubblicato.

Nasce dopo l'analisi dell'articolo SNME `Biggest Winners & Losers`, pubblicato con frasi duplicate, grassetti contaminati e blocchi di testo incastrati. Il problema non era solo editoriale: la pipeline di composizione HTML poteva produrre un articolo formalmente rotto anche su contenuti altrimenti pubblicabili.

La patch introduce tre principi:

1. i listicle/opinion automatici vengono esclusi in hard skip;
2. il repair anti-omissione v81 non puo' piu' innestare testo libero nel finale HTML;
3. prima del publish viene eseguito un controllo deterministico di integrita' HTML.

## Hard skip listicle/opinion

La funzione `cheap_classifier_v91()` viene estesa con `v915_is_hard_listicle()`.

Pattern bloccati:

- `biggest winners` / `biggest losers`;
- `winners and losers` / `winners & losers`;
- `things we hated` / `things we loved`;
- `draws and duds` / `draws & duds`;
- `opinion review` / `opinion-review`;
- `best and worst` / `best & worst`;
- `ranked`, `ranking`, `listicle`.

Quando intercettati, i contenuti ricevono:

```text
skip_final=True
cheap_score<=20
reason=v91_5_hard_skip_listicle_opinion
```

## Repair v81 libero disattivato

Il repair v81 nacque per compensare omissioni della pipeline 2.5 Flash Lite / 2.5 Flash. Con il passaggio alla chain 3.1 Flash Lite, il repair libero sul finale HTML diventa piu' rischioso che utile.

v91.5 sovrascrive:

```python
v81_translation_may_have_omissions()
v81_repair_possible_omissions()
```

in modo che:

- non venga avviato un innesto libero nel finale HTML;
- eventuali problemi siano demandati a validator/retry/blocco manuale;
- il testo finale non venga mai modificato con append/merge parziale.

Log atteso:

```text
[PRESERVE v91.5] Anti-omissione v81 libero disattivato: uso validator/retry, non innesto HTML
[PRESERVE v91.5] Repair v81 libero bypassato: nessun merge sul finale HTML
```

## HTML integrity guard

Prima del publish, `create_post_without_image()` viene protetta da un validator deterministico:

```python
v915_html_integrity_issues(html)
```

Il validator rileva:

- `<b>` / `<strong>` troppo lunghi;
- grassetti che contengono intere frasi;
- grassetti che duplicano il contesto immediatamente precedente;
- frasi quasi duplicate nello stesso paragrafo;
- pattern di innesto come `X ... <b>X ...`;
- span duplicati verbatim;
- pattern noti emersi dall'articolo SNME.

Se trova problemi:

```text
[HTMLGUARD v91.5] BLOCCO publish per integrita HTML issues=[...] title=...
```

Il contenuto viene salvato in:

```text
manual_review/
```

con file `.html` e `.json`, e l'URL viene marcato in `processed_urls.json` come:

```json
{
  "status": "needs_manual_review",
  "reason": "v91_5_html_integrity_failed"
}
```

## Workflow

Il workflow e' stato rinominato in:

```text
OpenWrestlingTV Bot v91.5
```

Sono stati aggiunti:

- marker source `v91.5 html integrity and block-safe repair guard`;
- flag `V91_5_ENABLED=1`;
- flag `V91_5_BLOCK_FREE_REPAIR=1`;
- flag `V91_5_HTML_GUARD_ENABLED=1`;
- flag `V91_5_LISTICLE_HARD_SKIP_ENABLED=1`;
- artifact/persistenza `manual_review/`.

## Cosa verificare nella prossima run

Cercare nel log:

```text
[BOOT v91.5] HTML integrity guard + block-safe repair policy attivi
[V91.5 HARD SKIP] listicle/opinion automatico escluso
[HTMLGUARD v91.5] BLOCCO publish per integrita HTML
```

Se non pubblica nulla, la run puo' comunque essere valida se mostra il boot v91.5 e continua senza errori.

Se pubblica, verificare che non compaiano piu':

- frasi duplicate nello stesso paragrafo;
- `<b>` con interi periodi;
- frasi incastrate dentro il grassetto;
- `Repair anti-omissione applicato` senza controllo successivo.
