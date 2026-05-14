# OpenWrestlingTV — Editorial policy notes

## Report true-results

I report risultati completi sono contenuti canonici. Una volta pubblicati, non devono tornare in pending anche se vengono ritrovati da una fonte alternativa o da un articolo duplicato.

Regola operativa:

- `report:*` pubblicato o confermato da WordPress = report chiuso;
- `DEDUPE BLOCKED` contro un post WordPress esistente = conferma di pubblicazione, non errore;
- la pending deve contenere solo report non ancora pubblicati e non confermati.

## Opinion/interview sotto soglia

Le opinion/interview tier3 sotto 55 restano bloccate. Questo evita pubblicazioni di commenti secondari senza notizia concreta, come analisi podcast o pareri isolati.

## Titoli

Il titolo pubblicato deve essere sempre italiano e prodotto/riparato da Gemini. Non si pubblica un fallback inglese deterministico.

## Embed e media

Gli embed devono preservare la posizione originale quando possibile. Gli URL nudi di YouTube/X non devono comparire duplicati nel corpo: devono diventare embed o essere rimossi se duplicati.

Per Twitter/X, la forma canonica è:

```text
https://x.com/<user>/status/<id>
```

## Artifact editoriali

Ogni pubblicazione deve salvare:

- HTML finale nella cartella `published/`;
- review HTML in `published_html_review/`;
- evento nel master log;
- summary artifact della run.
