# CHANGELOG v67

## v67_gemini_category_report_editoriali_fix

- Aggiunta categorizzazione a monte con Gemini, separata dalla traduzione.
- La traduzione strutturata non viene riscritta: riceve solo la categoria gia' decisa.
- Aggiunto mapping categorie WordPress:
  - WWE: 4
  - AEW: 5
  - NXT: 6
  - TNA: 7
  - World: 8
  - Editoriali: 13
  - Business: 15
- I report/results/recap vengono sempre forzati in categoria Editoriali.
- Default `WP_EDITORIALI_CATEGORY_ID` corretto da 8 a 13.
- Aggiunto fallback deterministico se Gemini non risponde o restituisce confidence bassa.
- Correzioni specifiche:
  - Report TNA -> Editoriali, non World.
  - Sami Zayn/Raw/SmackDown -> WWE, non NXT.
  - Dark Side of the Ring/Vice/docuserie -> World, non TNA.
  - Ex-NJPW/AAA/ROH/NOAH diretto o atteso in WWE -> WWE.
- Aggiunto log `[CATEGORY]` per tracciare categoria, confidence e motivazione.
