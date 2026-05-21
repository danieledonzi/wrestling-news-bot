# CHANGELOG v90.2 - Editorial pacing and update gate

## Summary

v90.2 introduce una prima regia editoriale dopo i test RAW/NXT/Dynamite e dopo il caso Ludwig Kaiser.

L'obiettivo non e' ridurre la qualita' o cambiare le chain Gemini, ma evitare che ogni variazione dello stesso fatto venga tradotta e pubblicata automaticamente solo perche' ha score alto.

## Cosa cambia

- Aggiunge `scripts/apply_bot_patch_v90_2.py`.
- Aggiorna workflow a `OpenWrestlingTV Bot v90.2`.
- Persiste due nuovi artifact:
  - `v90_2_event_cores.json`
  - `soft_pool.json`

## Pilastri

### 1. Event core detection

Ogni candidato puo' essere ricondotto a un fatto centrale, per esempio:

```text
legal:ludwig-kaiser:case
return:baron-corbin:wwe
return:drew-mcintyre:wwe
business:tko:saudi-return
```

### 2. True update gate

Se il core e' gia' coperto, lo score da solo non basta piu'.

Regola:

```text
core non pubblicato -> scoring normale
core gia' pubblicato -> serve un aggiornamento sostanziale
```

Esempi di aggiornamenti sostanziali:

```text
not guilty plea
rientro dal Messico
restrizioni viaggio che impattano il lavoro WWE
nuova data ufficiale di ritorno
contratto/offerta/conferma
```

Esempi da saltare o spostare in soft pool:

```text
riformulazione dello stesso arresto
seconda fonte con gli stessi dettagli
backstage update senza fatto nuovo
commento/opinion/intervista gia' coperta
```

### 3. Soft pool

Gli update deboli o le soft news in giornata gia' piena non vengono pubblicati subito. Entrano in `soft_pool.json` con score, core, motivo e TTL.

### 4. Dense-window pacing

Se nelle ultime 4 ore sono gia' usciti molti articoli, le news soft/medie non vengono processate subito:

```text
published_last_4h >= 8
score <= 74
-> soft_pool / skip operativo
```

## Cosa non cambia

- Non cambia la chain Gemini.
- Non cambia la qualita' delle traduzioni.
- Non introduce ancora un refactor completo dello scoring.
- Non forza una riduzione secca del numero giornaliero di news.

## Expected logs

```text
[BOOT v90.2] Editorial pacing + update gate attivi: true-update gate, soft_pool, dense-window pacing
[UPDATEGATE v90.2] True update OK core=... score=... reason=... novel=[...]
[SKIP v90.2] Follow-up duplicato/non sostanziale core=...
[SOFTPOOL v90.2] Aggiunta: score=... core=... reason=...
[SKIP v90.2] Dense window soft hold: last4h=... score=...
[CORE v90.2] Registrato publish core=... count=... facts=[...]
```

## Caso guida Ludwig Kaiser

Articoli considerati sostanziali:

```text
arresto / mandato / cauzione
dettagli dell'episodio
not guilty plea
rientro dal Messico
restrizioni viaggio se impattano il lavoro WWE
```

Articoli da filtrare se non aggiungono nuovi fatti:

```text
assenza di precedenti
richiesta procedurale gia' coperta
stessa notizia ripetuta dalla stessa fonte
seconda fonte con dettagli gia' pubblicati
```

## Caso guida Baron Corbin

Il primo rumor sul possibile ritorno puo' essere pubblicato.

Follow-up successivi passano solo se aggiungono un fatto vero:

```text
data
contratto/offerta
brand assegnato
conferma WWE
ritorno effettivo on-screen
```

Altrimenti soft pool o skip.
