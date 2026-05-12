# v69 Implementation Notes

Implemented in `bot_v69.py`.

## Obiettivo

Rafforzare la qualita' della traduzione senza modificare la logica editoriale v68.

Il caso emerso nella run v68 era corretto dal punto di vista editoriale: la news su Lei Ying Lee e' stata classificata come `POST_SHOW_NEWS`, pubblicata in TNA e non bloccata dal filtro preview. Il problema era nella resa italiana del titolo/cintura e nel casing.

## Nuove funzioni

- `v69_extract_proper_names_from_source()`
- `v69_restore_source_proper_case()`
- `v69_detect_source_official_titles()`
- `v69_fix_release_lexicon()`
- `v69_restore_official_titles()`
- `v69_apply_translation_guardrails()`

## Titoli/cinture

Aggiunta lista:

```python
PROTECTED_CHAMPIONSHIP_TERMS_V69 = [...]
```

Include titoli WWE, AEW, TNA, NXT, ROH, NJPW e AAA. Tra questi c'e' esplicitamente:

```python
"TNA Knockouts Title"
```

La lista viene estesa dentro `PROTECTED_WRESTLING_TERMS`, quindi viene usata sia come riferimento editoriale sia come guardrail.

## Pipeline traduzione aggiornata

Dopo Gemini:

```python
titolo, testo = apply_translation_glossary(titolo, testo)
titolo, testo = v69_apply_translation_guardrails(titolo, testo, source_title, source_text)
titolo, testo = repair_protected_source_facts(...)
```

La stessa protezione viene riapplicata dopo eventuale repair e dentro `v63_editorial_finalize()`.

## Release / rilascio

Regola generale:

- `WWE release` -> `licenziamento WWE`
- `released by/from WWE` -> `licenziato/licenziata dalla WWE`
- `roster cuts` / `talent cuts` -> `licenziamenti`
- `departure` resta piu' neutro e puo' diventare `addio` se il contesto non implica tagli.

## Casing

Il sistema estrae nomi propri dal titolo/testo sorgente e li ripristina nel titolo e nel body. Esempio:

```text
Lei ying lee -> Lei Ying Lee
arianna grace -> Arianna Grace
impact -> Impact
```

## Nota

Le regole sono generali e non hardcoded su un singolo episodio. Il caso Lei Ying Lee/TNA Knockouts Title e' coperto perche' il titolo ufficiale e' ora nella lista generale dei titoli protetti.
