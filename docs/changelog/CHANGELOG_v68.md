# CHANGELOG v68

## v68_semantic_freshness_reports_opinion_cap

- Aggiunta classificazione semantica del tipo articolo prima della traduzione: `PREVIEW`, `RESULTS_REPORT`, `POST_SHOW_NEWS`, `OPINION`, `RUMOR`, `OTHER`.
- Il filtro freshness ora blocca solo le vere preview scadute, non le news post-show.
- Le news su eventi avvenuti in puntata, inclusi cambi titolo, vittorie, debutti, ritorni e attacchi, possono essere pubblicate anche se esiste un report della puntata.
- I report/results/recap completi restano forzati in categoria Editoriali, ID 13.
- La categorizzazione editoriale Gemini della v67 resta separata dalla traduzione.
- Aggiunto log `[TYPE]` per tracciare il tipo articolo.
- Aggiunto log `[FRESHNESS] Post-show news fresca` quando il bot evita correttamente il blocco preview.
- Applicato davvero il cap v66/v68 allo scoring finale.
- Cap piu' duro per opinion/commentary/speculazioni, inclusi articoli tipo “Bully Ray lays out options”, “believes”, “explains why”, podcast/interviste e annunci vaghi senza fatto concreto.
- Aggiunto floor per post-show news concrete, in modo che un cambio titolo in una puntata settimanale non venga schiacciato dal filtro freshness.
