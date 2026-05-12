# v67 Implementation Notes

Implemented in `bot_v67.py`.

## Obiettivo

Spostare la categorizzazione editoriale prima della traduzione, usando Gemini come interprete della notizia e lasciando la traduzione il piu' invariata possibile.

## Nuove funzioni

- `normalize_category_slug_v67()`
- `category_id_from_slug_v67()`
- `classify_category_fallback_v67()`
- `classify_category_with_gemini_v67()`

## Pipeline aggiornata

1. Estrazione titolo, URL e testo/lead.
2. Riconoscimento report/results.
3. Categorizzazione:
   - se report/results: categoria Editoriali forzata;
   - altrimenti Gemini sceglie tra WWE, AEW, NXT, TNA, World, Business, Editoriali;
   - se Gemini fallisce: fallback deterministico.
4. Traduzione strutturata o fallback di traduzione con categoria gia' fissata.
5. Prima della pubblicazione, la categoria viene nuovamente fissata dal codice.

## Report

`REPORT_CATEGORY_ID` ora usa default `13`:

```python
REPORT_CATEGORY_ID = int(os.getenv("WP_EDITORIALI_CATEGORY_ID", "13"))
```

Il workflow GitHub Actions include:

```yaml
WP_EDITORIALI_CATEGORY_ID: 13
```

## Guardrail categoria

- I report/results/recap non possono finire in World/TNA/WWE: sempre Editoriali.
- TNA e' usata solo quando TNA/Impact e' il focus reale.
- Dark Side of the Ring e documentari vanno in World.
- WWE main roster, Raw, SmackDown e Sami Zayn vanno in WWE.
- Se un ex-NJPW/AAA/ROH/NOAH e' atteso o diretto in WWE, prevale la destinazione WWE.
