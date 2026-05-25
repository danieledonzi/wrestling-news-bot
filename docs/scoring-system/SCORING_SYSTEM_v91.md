# SCORING_SYSTEM v91

## Principio centrale

La v91 introduce uno scoring unico e autoritativo:

```text
score_story_v91()
```

Quando v91 produce una decisione autoritativa, i vecchi cap legacy non devono piu' abbassare score, core o lane.

## Pipeline scoring

```text
1. feed-level hard skip URL
2. cheap classifier deterministico
3. editorial analysis strutturata per candidati plausibili
4. assign_story_core_v91
5. score_story_v91 una sola volta
6. lane decision
```

## Classi editoriali

### Hard news / must publish

Score indicativo: 82-100.

Include:

- morte;
- arresto/causa legale grave;
- infortunio serio;
- licenziamenti/addii importanti;
- title change importante;
- ritorno/debutto di top name;
- report PLE/PPV/special event.

### Event outcome

Score indicativo: 72-90.

Include risultati reali di show/eventi:

- wins/defeats;
- retains;
- new champion/captures;
- advances;
- betrayal/turn;
- return/debut.

Una news evento autonoma non deve essere bloccata dal solo report dell'evento.

### Strategic discussion

Score indicativo: 68-82.

Include:

- WWE vs AEW;
- Tony Khan / Triple H / TKO;
- TV deal / media rights / WBD / Paramount / Netflix / ESPN;
- fan backlash rilevante;
- problemi organizzativi importanti;
- push evidente di una star discussa.

### Standard useful

Score indicativo: 55-67.

Include interviste e dettagli utili ma non urgenti.

### Soft trash / skip finale

Score indicativo: 0-54.

Include:

- quote generiche da podcast;
- reaction social banale;
- lifestyle/foto/curiosita' senza valore editoriale;
- viewership/ratings routine;
- preview/listing scadute o non pubblicabili.

## Lane

```text
82-100  publish_now / hard
75-81   publish_candidate
68-74   strategic_pool
55-67   soft_pool
0-54    skip_final
```

## Report ed eventi

- `RESULTS_REPORT` di PLE/PPV/special event: floor 82.
- Weekly show report: resta pubblicabile se fonte valida.
- Un report senza fonte concreta non marca l'evento come coperto.
- Un `event_key` generico non blocca singole news autonome.

## Opinion

- Opinion generica senza nuovo fatto: cap 60.
- Opinion con discussion value reale: puo' salire a strategic_pool.
- Opinion + WWE/AEW/business war/TV deal: valutare come strategic discussion, non soft trash.

## Gemini

Gemini non assegna lo score finale.

L'analisi editoriale produce campi semantici; il punteggio finale viene calcolato da codice.
