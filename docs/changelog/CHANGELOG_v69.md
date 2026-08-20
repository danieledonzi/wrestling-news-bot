# CHANGELOG v69

## v69_translation_title_guardrails

- Mantiene tutta la logica v68 su freshness semantica, report, post-show news e cap opinion.
- Aggiunti guardrail generali sulla traduzione dei titoli/cinture ufficiali: non devono essere tradotti, parafrasati o abbassati di casing.
- Aggiunta lista generale `PROTECTED_CHAMPIONSHIP_TERMS_V69`, estendibile, con titoli WWE, AEW, TNA, NXT, ROH, NJPW e AAA.
- Aggiunto esplicitamente `TNA Knockouts Title` alla lista dei titoli da non tradurre mai.
- Aggiunto post-processing deterministico `v69_apply_translation_guardrails()` dopo Gemini e dopo eventuale repair editoriale.
- Aggiunto ripristino casing da sorgente per nomi propri, eventi e show, per evitare titoli tipo `Lei ying lee` o `arianna grace`.
- Aggiunta regola lessicale forte: in italiano editoriale wrestling `release/released/roster cuts` non deve diventare `rilascio`, ma `licenziamento`, `licenziato/licenziata` o `addio` secondo contesto.
- Aggiornati i prompt di traduzione per dare a Gemini le stesse regole, mantenendo comunque il controllo deterministico a valle.
