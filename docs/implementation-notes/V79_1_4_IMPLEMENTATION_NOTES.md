# v79.1.4 Implementation Notes

Implemented in `bot_v79_1_4.py`.

## Obiettivo

Raffinare la semantica dello spoiler senza modificare la pipeline principale.

## Nuove funzioni

- `v7914_has_outcome_or_reveal_spoiler()`
- `v7914_is_non_spoiler_announcement()`
- `v7914_preshow_spoiler_obsolete()`
- override di `v791_has_spoiler_hard_validation()`
- override di `v79_is_live_spoiler_candidate()`
- override di `v7912_is_score_floor_eligible()`
- override di `calculate_importance_score()`
- override di `v723_conservative_score_after_ai()`

## Regola outcome spoiler

Sono spoiler concreti gli articoli che rivelano:

- vincitore/esito del match;
- retain/cambio titolo;
- pin/submission;
- identità di un mystery partner/opponent;
- apparizione a sorpresa con identità esplicita.

## Regola announcement non-spoiler

Un annuncio fatto durante un PLE può essere una news importante e pubblicabile, ma non riceve `[SPOILER]` se non contiene outcome concreto.

Esempio: `John Cena announces plans for John Cena Classic Tournament during WWE Backlash`.

## Regola pre-show obsoleto

Un articolo pre-show (`opening match revealed`, `match order`, `spoiler lineup`) non viene più trattato come spoiler se in `history.txt` esiste già un risultato/report dello stesso evento.

Questo evita di pubblicare come `[SPOILER]` una preview già superata dai risultati live.
