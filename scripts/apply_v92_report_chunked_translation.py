from pathlib import Path
import re

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_REPORT_CHUNKED_TRANSLATION = True" in text:
    print("[V92 CHUNK] gia applicato")
    raise SystemExit(0)

# Marker.
if "V92_REPORT_SOURCE_INTRO_FILTER = True\n" in text:
    text = text.replace(
        "V92_REPORT_SOURCE_INTRO_FILTER = True\n",
        "V92_REPORT_SOURCE_INTRO_FILTER = True\nV92_REPORT_CHUNKED_TRANSLATION = True\n",
        1,
    )
elif "V92_REPORT_LEGACY_TRANSLATION_PROMPT = True\n" in text:
    text = text.replace(
        "V92_REPORT_LEGACY_TRANSLATION_PROMPT = True\n",
        "V92_REPORT_LEGACY_TRANSLATION_PROMPT = True\nV92_REPORT_CHUNKED_TRANSLATION = True\n",
        1,
    )
else:
    text = text.replace(
        'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
        'V92_REPORT_CHUNKED_TRANSLATION = True\nSOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
        1,
    )

if "REPORT_TRANSLATION_BATCH_SIZE" not in text:
    text = text.replace(
        'REQUEST_TIMEOUT_WP = int(os.getenv("V92_REQUEST_TIMEOUT_WP", "12"))\n',
        'REQUEST_TIMEOUT_WP = int(os.getenv("V92_REQUEST_TIMEOUT_WP", "12"))\nREPORT_TRANSLATION_BATCH_SIZE = int(os.getenv("V92_REPORT_TRANSLATION_BATCH_SIZE", "24"))\n',
        1,
    )

new_function = r'''def translate_report_blocks(source_title: str, blocks: List[Dict[str, str]], deterministic_title: str) -> Dict[int, str]:
    items = text_blocks(blocks)
    if not items:
        raise ValueError("Nessun blocco testuale da tradurre")

    translated: Dict[int, str] = {}
    total = len(items)
    batch_size = max(8, REPORT_TRANSLATION_BATCH_SIZE)
    print(f"[TRANSLATE v92] Avvio chain report_blocks_legacy_prompt | blocchi_testuali={total} | batch_size={batch_size}", flush=True)

    for start in range(0, total, batch_size):
        batch = items[start:start + batch_size]
        batch_indexes = [int(item["i"]) for item in batch]
        batch_no = (start // batch_size) + 1
        batch_total = (total + batch_size - 1) // batch_size

        prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Non fare una traduzione letterale: devi trasformare il materiale in italiano giornalistico naturale, mantenendo fatti e citazioni.

Stai lavorando su un report risultati/recap di uno show, non su una news breve.
Il titolo del report e' gia' deterministico e NON deve essere riscritto.

OBIETTIVO:
- trasformare i blocchi sorgente in italiano fluido, naturale e credibile per una testata italiana di wrestling;
- mantenere tutti i fatti, i match, i segmenti, i risultati, le citazioni e gli sviluppi presenti nei blocchi;
- rispettare l'ordine cronologico dello show;
- non saltare l'ultimo segmento;
- non inventare dettagli e non aggiungere commenti personali;
- non inserire frasi promozionali della fonte, call to action, domande ai lettori o inviti ai commenti.

REGOLE DI TRADUZIONE:
- non tradurre parola per parola se la frase italiana risulterebbe artificiale;
- se una frase inglese e' idiomatica, rendila con una formulazione italiana naturale;
- mantieni nomi propri, ring name, stable, show, eventi, sigle, date e numeri;
- mantieni in inglese i nomi ufficiali di titoli e cinture, come Intercontinental Championship, World Heavyweight Championship, Women's Tag Team Championship, United States Championship, WWE Championship, NXT Championship, AEW World Championship;
- mantieni in inglese i match type e le stipulazioni riconoscibili, come tag team match, triple threat match, fatal four-way match, Last Man Standing, WarGames, Hell in a Cell, ladder match, title match;
- mantieni le mosse riconoscibili in inglese, ma costruisci la frase in italiano naturale;
- release/released/roster cuts non e' rilascio: usa licenziamento, licenziato/licenziata, addio o uscita secondo contesto;
- retirement non e' pensione: usa ritiro o ritirarsi;
- cleared/not cleared significa autorizzato/non autorizzato a lottare;
- promo e' maschile: un promo, mai una promo;
- chop e' femminile: le chop, delle chop;
- grudge match non va tradotto letteralmente: usa regolamento di conti o resa dei conti.

REGOLE DI BLOCCO:
- ricevi solo un batch di blocchi testuali del report completo;
- devi restituire lo stesso numero di item ricevuti in questo batch;
- conserva esattamente l'indice i di ogni item;
- traduci ogni blocco separatamente;
- non fondere blocchi diversi;
- non cambiare ordine;
- non aggiungere link, immagini, tweet o placeholder: media ed embed sono reinseriti dal codice;
- per heading restituisci solo testo tradotto, senza tag HTML;
- per paragraph/quote restituisci solo testo italiano naturale, senza markdown.

STILE DA EVITARE:
- evita calchi come "SmackDown di WWE", "durante l'episodio di WWE Raw", "si e' aperto riguardo", "ha affrontato una sfida", "ha ottenuto una vittoria", "match di ripicca", "giocatore di main event";
- non lasciare inglese generico come "kick out" dentro frasi italiane: usa "si libera", "esce dal conteggio" o "alza la spalla";
- non usare virgolette inutili attorno ai nomi degli show;
- preferisci "puntata di Raw" o "Raw" a formule rigide come "WWE Raw" quando il contesto e' chiaro.

Rispondi solo con JSON valido in una riga:
{{"items":[{{"i":0,"text":"..."}}]}}

TITOLO DETERMINISTICO DA NON MODIFICARE:
{deterministic_title}

TITOLO FONTE:
{source_title}

BATCH:
{batch_no}/{batch_total}

BLOCCHI JSON:
{json.dumps(batch, ensure_ascii=False)}
"""
        print(f"[TRANSLATE v92] Batch report_blocks_legacy_prompt {batch_no}/{batch_total} | items={len(batch)} | indici={batch_indexes[0]}-{batch_indexes[-1]}", flush=True)
        data, model = generate_json(prompt, chain_name="report_blocks_legacy_prompt")
        arr = data.get("items") or []
        batch_translated: Dict[int, str] = {}
        for item in arr:
            try:
                i = int(item.get("i"))
                txt = clean_text(str(item.get("text") or ""))
                if txt:
                    batch_translated[i] = txt
            except Exception:
                continue
        expected_batch = set(batch_indexes)
        missing_batch = expected_batch.difference(batch_translated)
        if missing_batch:
            raise ValueError(f"Traduzione batch incompleta: batch={batch_no}/{batch_total} mancanti={sorted(list(missing_batch))} model={model}")
        translated.update(batch_translated)
        print(f"[TRANSLATE v92] Batch completato: {batch_no}/{batch_total} | modello={model} | blocchi={len(batch_translated)}/{len(expected_batch)}", flush=True)

    expected = {int(item["i"]) for item in items}
    missing = expected.difference(translated)
    if missing:
        raise ValueError(f"Traduzione a blocchi incompleta: mancanti={sorted(list(missing))[:20]}")
    print(f"[TRANSLATE v92] Chain completata: report_blocks_legacy_prompt | blocchi_tradotti={len(translated)}/{len(expected)}", flush=True)
    return translated
'''

pattern = re.compile(r'def translate_report_blocks\(source_title: str, blocks: List\[Dict\[str, str\]\], deterministic_title: str\) -> Dict\[int, str\]:\n.*?\n\ndef upload_media', re.DOTALL)
replacement = new_function + "\n\ndef upload_media"
new_text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit("[V92 CHUNK] funzione translate_report_blocks non trovata")

p.write_text(new_text, encoding="utf-8")
print("[V92 CHUNK] traduzione report a batch applicata")
