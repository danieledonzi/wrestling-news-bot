# IMPLEMENTATION NOTES v86.8

La v86.8 parte dalla v86.7 e interviene su due punti emersi dalla run del 13 maggio 2026.

## 1. Gemini down non deve far perdere candidati

Prima:

```text
check_gemini() == False -> stop run
```

Ora:

```text
check_gemini() == False
↓
salva candidati pubblicabili in pending
↓
priorità ai TRUE_RESULTS_REPORT
↓
stop run
```

La funzione nuova è:

```python
v868_save_candidates_when_gemini_down(queue, mode, limit)
```

Usa `save_selected_candidates_to_pending()` sulla queue riordinata e forza la preservazione del primo true-results report se necessario.

## 2. Executive/opinion cap

Il boost business/dirigenza era troppo largo per interviste/opinioni. La v86.8 aggiunge:

```python
v868_is_executive_opinion_interview()
```

e wrappa:

```python
calculate_importance_score()
v723_conservative_score_after_ai()
```

per cappare a 72 articoli di commento/intervista su ruoli executive passati/futuri senza notizia corporate concreta.

## 3. Non riscrivere il gate pending v86.7

Il gate pending v86.7 resta valido. La v86.8 non lo sostituisce: aggiunge la preservazione quando la run si ferma prima della fase di processing per indisponibilità Gemini.
