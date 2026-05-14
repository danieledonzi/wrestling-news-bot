# IMPLEMENTATION NOTES v87

## Model routing

La v87 non usa più `gemini-3.1-flash` standard nelle chain di default. Il router ereditato si chiama ancora internamente `v83`, quindi la patch v87 riallinea le variabili `V83_*` ai nuovi valori `V87_*`.

```python
V87_DEFAULT_LITE_CHAIN = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
V87_STRONG_CHAIN = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
V87_STORM_REPORT_CHAIN = ["gemini-2.5-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
V87_STORM_LITE_CHAIN = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
```

## Tier3 opinion/interview

La funzione `editorial_tier()` viene wrappata. Se lo score raffinato è sotto 55, il tier sarebbe `tier3`, e il titolo/testo contiene segnali opinion/interview senza fatti concreti, il bot restituisce `skip`.

## Link inline

`create_post_without_image()` passa il body da `strip_unwanted_inline_anchors_v87()` prima del publish. La regola è conservativa: preserva link social/video embeddabili o URL espliciti, ma rimuove anchor su nomi e frasi comuni.

Questo risolve casi come nomi di wrestler trasformati in link senza istruzione editoriale.
