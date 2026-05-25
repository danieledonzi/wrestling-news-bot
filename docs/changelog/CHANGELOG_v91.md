# CHANGELOG v91

## v91_editorial_pipeline_refactor

### Added

- Nuovo layer autoritativo `score_story_v91()`.
- Nuovo `cheap_classifier_v91()` per hard skip deterministici prima di Gemini.
- Nuova `editorial_analysis_v91()` con cache `article_analysis_cache_v91.json`.
- Nuovo `assign_story_core_v91()` che riusa il core assignment v90.2.7 quando disponibile.
- Nuova lane decision:
  - `publish_now`
  - `publish_candidate`
  - `strategic_pool`
  - `soft_pool`
  - `skip_final`
- Bypass legacy quando `v91_authoritative=True`.

### Changed

- Lo scoring v91 diventa la decisione editoriale primaria.
- Le vecchie logiche di cap/scoring non devono piu' abbassare una decisione autoritativa v91.
- La traduzione diventa uno step solo per candidati effettivamente pubblicabili.
- Le soft news con valore di discussione vengono separate dal soft trash.

### Preserved

- Report in categoria Editoriali.
- Regole preview hard v68/v70.
- Regola: una puntata puo' generare sia report sia news autonome.
- Draft-first publishing.
- Review HTML/artifact.
- Guardrail traduzione/casing/titoli ufficiali.

### Notes

La v91 e' un refactor decisionale: non e' una micro-patch su Double or Nothing o su un evento specifico.
