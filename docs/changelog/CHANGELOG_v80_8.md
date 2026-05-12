# CHANGELOG v80.8

## v80_8_followup_dedupe_startup_fix

- Parte da v80.7.
- Corregge il problema di startup della v80.7: gli override del follow-up dedupe ora vengono definiti prima dell'entrypoint `if __name__ == "__main__"`.
- La run deve mostrare `VERSION [v80_8_followup_dedupe_startup_fix (...)]`.
- Mantiene la microfix v80.7: backstage reaction, futuro/status carriera e semi-ritiro possono passare come follow-up autonomi anche se condividono wrestler + evento con una news precedente.
- Nessuna modifica a scoring, spoiler, AAA boost, traduzione/stile, report, review packages o oEmbed.
