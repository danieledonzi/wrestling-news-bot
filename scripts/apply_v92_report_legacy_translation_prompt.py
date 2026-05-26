from pathlib import Path
import re

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_REPORT_LEGACY_TRANSLATION_PROMPT = True" in text:
    print("[V92 LEGACY PROMPT] gia applicato")
    raise SystemExit(0)

# Marker.
if "V92_REPORT_RUNTIME_TWEAKS = True\n" in text:
    text = text.replace(
        "V92_REPORT_RUNTIME_TWEAKS = True\n",
        "V92_REPORT_RUNTIME_TWEAKS = True\nV92_REPORT_LEGACY_TRANSLATION_PROMPT = True\n",
        1,
    )
elif "V92_REPORT_PROMPT_STRATEGY_PATCH = True\n" in text:
    text = text.replace(
        "V92_REPORT_PROMPT_STRATEGY_PATCH = True\n",
        "V92_REPORT_PROMPT_STRATEGY_PATCH = True\nV92_REPORT_LEGACY_TRANSLATION_PROMPT = True\n",
        1,
    )
else:
    text = text.replace(
        'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
        'V92_REPORT_LEGACY_TRANSLATION_PROMPT = True\nSOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
        1,
    )

legacy_block = '''    prompt = f"""
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
- ricevi una lista di blocchi testuali con indice i;
- devi restituire lo stesso numero di item ricevuti;
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

BLOCCHI JSON:
{json.dumps(items, ensure_ascii=False)}
"""
    print(f"[TRANSLATE v92] Avvio chain report_blocks_legacy_prompt | blocchi_testuali={len(items)}", flush=True)
    data, model = generate_json(prompt, chain_name="report_blocks_legacy_prompt")
'''

pattern = re.compile(
    r'    prompt = f"""\n.*?\n"""\n    print\(f"\[TRANSLATE v92\] Avvio chain .*?\n    data, model = generate_json\(prompt, chain_name="[^"]+"\)\n',
    re.DOTALL,
)

new_text, count = pattern.subn(legacy_block, text, count=1)
if count != 1:
    raise SystemExit("[V92 LEGACY PROMPT] blocco prompt non trovato")
text = new_text

text = text.replace(
    'Chain completata: report_blocks_faithful_v2',
    'Chain completata: report_blocks_legacy_prompt',
)

p.write_text(text, encoding="utf-8")
print("[V92 LEGACY PROMPT] prompt storico integrato")
