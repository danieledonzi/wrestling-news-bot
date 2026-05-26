from pathlib import Path

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_REPORT_PROMPT_STRATEGY_PATCH = True" in text:
    print("[V92 PROMPT] patch strategia prompt gia applicata")
    raise SystemExit(0)

# Do not exit on the older quality marker: this patch supersedes it.
if "V92_REPORT_QUALITY_PATCH = True" not in text:
    text = text.replace(
        'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
        'V92_REPORT_QUALITY_PATCH = True\nSOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
        1,
    )

text = text.replace(
    'V92_REPORT_QUALITY_PATCH = True\n',
    'V92_REPORT_QUALITY_PATCH = True\nV92_REPORT_PROMPT_STRATEGY_PATCH = True\n',
    1,
)

old_generate = '''def generate_json(prompt: str) -> Tuple[Dict[str, Any], str]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY mancante")
    client = genai.Client(api_key=GEMINI_API_KEY)
    last: Optional[Exception] = None
    for model in MODEL_CHAIN:
        try:
            res = client.models.generate_content(model=model, contents=prompt)
            return extract_json_object(res.text), model
        except Exception as exc:
            last = exc
            continue
    raise last if last else RuntimeError("Nessun modello disponibile")
'''

new_generate = '''def generate_json(prompt: str, chain_name: str = "unknown") -> Tuple[Dict[str, Any], str]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY mancante")
    print(f"[TRANSLATE v92] Chain attiva: {chain_name} | modelli={','.join(MODEL_CHAIN)}", flush=True)
    client = genai.Client(api_key=GEMINI_API_KEY)
    last: Optional[Exception] = None
    for model in MODEL_CHAIN:
        try:
            print(f"[TRANSLATE v92] Provo modello: {model} | chain={chain_name}", flush=True)
            res = client.models.generate_content(model=model, contents=prompt)
            data = extract_json_object(res.text)
            print(f"[TRANSLATE v92] Modello scelto: {model} | chain={chain_name}", flush=True)
            return data, model
        except Exception as exc:
            last = exc
            print(f"[TRANSLATE v92] Modello fallito: {model} | chain={chain_name} | error={str(exc)[:220]}", flush=True)
            continue
    raise last if last else RuntimeError("Nessun modello disponibile")
'''
if old_generate in text:
    text = text.replace(old_generate, new_generate, 1)

old_prompt = '''    prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Traduci in italiano i blocchi di un report risultati, senza riassumere.
Regole obbligatorie:
- restituisci lo stesso numero di item ricevuti;
- conserva l'indice i di ogni item;
- traduci ogni blocco separatamente;
- non unire blocchi diversi;
- non inventare nulla;
- non modificare il titolo deterministico;
- per heading usa solo testo tradotto, senza tag HTML;
- per paragraph/quote usa testo italiano naturale, senza markdown.
Rispondi solo con JSON valido in una riga: {{"items":[{{"i":0,"text":"..."}}]}}

TITOLO DETERMINISTICO:
{deterministic_title}

TITOLO FONTE:
{source_title}

BLOCCHI JSON:
{json.dumps(items, ensure_ascii=False)}
"""
    data, model = generate_json(prompt)
'''

old_prompt_quality = '''    prompt = f"""
Sei un giornalista italiano esperto di wrestling e lavori per una testata italiana.

Devi tradurre in italiano i blocchi di un report risultati, mantenendo il contenuto integrale e il tono giornalistico naturale.
Questa NON e' una sintesi: e' una traduzione editoriale fedele, fluida e leggibile.

REGOLE OBBLIGATORIE:
- restituisci lo stesso numero di item ricevuti;
- conserva esattamente l'indice i di ogni item;
- traduci ogni blocco separatamente, senza unirlo ad altri blocchi;
- non accorciare i blocchi e non comprimere le sequenze d'azione;
- se un blocco originale contiene piu' mosse, passaggi o dettagli, mantienili tutti;
- non inventare nulla e non aggiungere opinioni;
- conserva nomi propri, nomi delle mosse, titoli, stable e show nel modo piu' naturale per il pubblico italiano;
- traduci le citazioni in modo fedele, mantenendo intenzione, tono e sfumature;
- rendi l'italiano naturale, non meccanico e non letterale quando una resa libera e' piu' fluida;
- non modificare il titolo deterministico;
- per heading usa solo testo tradotto, senza tag HTML;
- per paragraph/quote usa solo testo italiano naturale, senza markdown.

Rispondi solo con JSON valido in una riga: {{"items":[{{"i":0,"text":"..."}}]}}

TITOLO DETERMINISTICO DA NON MODIFICARE:
{deterministic_title}

TITOLO FONTE:
{source_title}

BLOCCHI JSON:
{json.dumps(items, ensure_ascii=False)}
"""
    print(f"[TRANSLATE v92] Avvio chain report_blocks_faithful | blocchi_testuali={len(items)}", flush=True)
    data, model = generate_json(prompt, chain_name="report_blocks_faithful")
'''

new_prompt = '''    prompt = f"""
Sei un giornalista italiano esperto di wrestling e lavori per una testata italiana.

Devi tradurre in italiano i blocchi testuali di un report risultati/recap di uno show.
Questo NON e' una news breve e NON e' una sintesi: e' una traduzione editoriale fedele, fluida e naturale.

OBIETTIVO EDITORIALE:
- coprire l'intero show dall'inizio alla fine;
- mantenere l'ordine cronologico dei blocchi;
- non saltare match, promo, segmenti, sviluppi importanti o risultati;
- ogni match deve mantenere il vincitore se presente nel blocco originale;
- l'ultimo segmento dello show deve essere sempre preservato;
- se una fase di lotta e' lunga, puoi renderla piu agile in italiano, ma non devi tagliare snodi narrativi, risultati o passaggi decisivi.

REGOLE DI OUTPUT:
- restituisci lo stesso numero di item ricevuti;
- conserva esattamente l'indice i di ogni item;
- traduci ogni blocco separatamente;
- non fondere blocchi diversi;
- non cambiare ordine;
- non aggiungere link, tweet, immagini o placeholder: media ed embed sono reinseriti dal codice;
- per heading usa solo testo tradotto, senza tag HTML;
- per paragraph/quote usa solo testo italiano naturale, senza markdown;
- rispondi solo con JSON valido in una riga: {{"items":[{{"i":0,"text":"..."}}]}}

FEDELTA' AI FATTI:
- non inventare dettagli;
- non correggere il sorgente anche se ti sembra strano;
- non modificare nomi propri, ring name, date, numeri, eventi, sigle o rapporti tra soggetti;
- se non sei sicuro di un nome, evento, numero o titolo, copialo esattamente dal sorgente;
- traduci le citazioni in modo fedele, mantenendo intenzione, tono e sfumature.

TERMINI UFFICIALI DA MANTENERE IN INGLESE:
World Heavyweight Championship; Intercontinental Championship; United States Championship; WWE Championship; WWE Women's Championship; Women's World Championship; NXT Championship; NXT North American Championship; AEW World Championship; AEW World Tag Team Championship; TNA Knockouts Title; TNA Knockouts World Championship; AAA Mega Championship; Money in the Bank.

STIPULAZIONI E MATCH TYPE DA MANTENERE IN INGLESE:
tag team match; mixed tag team match; 6-Man Tag Team Match; 8-Woman Tag Team Match; 10-Man Tag Team Match; triple threat match; fatal four-way match; 4-Way; 5-Way; Six-Pack Challenge; Last Man Standing; Last Woman Standing; WarGames; Royal Rumble; Hell in a Cell; cage match; steel cage match; ladder match; street fight; no disqualification match; title match.

GERGO E LOCALIZZAZIONE:
- mantieni naturali termini come match, promo, segment, storyline, push, turn, feud, stable, tag team, heel, face, main event, main eventer;
- promo e' maschile: scrivi un promo, mai una promo;
- chop e' femminile: scrivi le chop, delle chop;
- grudge match non va tradotto letteralmente: usa regolamento di conti o resa dei conti;
- release/released/roster cuts non e' rilascio: usa licenziamento, licenziato/licenziata, addio o uscita secondo contesto;
- retirement non e' pensione: usa ritiro o ritirarsi;
- cleared/not cleared significa autorizzato/non autorizzato a lottare;
- mantieni le mosse riconoscibili in inglese, ma costruisci la frase in italiano naturale: prova una Spear, lo colpisce con una Superkick, connette con la Curb Stomp.

STILE:
- scrivi in italiano giornalistico naturale, non meccanico;
- non tradurre parola per parola se la resa suona artificiale;
- evita calchi come: SmackDown di WWE, durante l'episodio di WWE Raw, si e' aperto riguardo, ha affrontato una sfida, ha ottenuto una vittoria, match di ripicca, giocatore di main event;
- nei report match-by-match usa cronaca agile: alterna colpisce, prova, connette, chiude, schiena, evita, ribalta, stende;
- non aggiungere domande ai lettori, inviti ai commenti o frasi promozionali della fonte.

TITOLO DETERMINISTICO DA NON MODIFICARE:
{deterministic_title}

TITOLO FONTE:
{source_title}

BLOCCHI JSON:
{json.dumps(items, ensure_ascii=False)}
"""
    print(f"[TRANSLATE v92] Avvio chain report_blocks_faithful_v2 | blocchi_testuali={len(items)}", flush=True)
    data, model = generate_json(prompt, chain_name="report_blocks_faithful_v2")
'''

if old_prompt in text:
    text = text.replace(old_prompt, new_prompt, 1)
elif old_prompt_quality in text:
    text = text.replace(old_prompt_quality, new_prompt, 1)
else:
    raise SystemExit("[V92 PROMPT] prompt block non trovato")

# Add completion log if not already present.
text = text.replace(
    '    if len(missing) > max(3, int(len(expected) * 0.15)):\n        raise ValueError(f"Traduzione a blocchi incompleta: mancanti={sorted(list(missing))[:20]} model={model}")\n    return translated\n',
    '    if len(missing) > max(3, int(len(expected) * 0.15)):\n        raise ValueError(f"Traduzione a blocchi incompleta: mancanti={sorted(list(missing))[:20]} model={model}")\n    print(f"[TRANSLATE v92] Chain completata: report_blocks_faithful_v2 | modello={model} | blocchi_tradotti={len(translated)}/{len(expected)}", flush=True)\n    return translated\n',
    1,
)

# Insert URL normalization helper before render_blocks if needed.
if "def normalize_media_identity" not in text:
    helper = '''\n\ndef normalize_media_identity(url: Optional[str]) -> str:\n    raw = (url or "").split("?", 1)[0].strip().lower().rstrip("/")\n    return raw\n'''
    text = text.replace('\n\ndef render_blocks(blocks: List[Dict[str, str]], translated: Dict[int, str]) -> str:\n', helper + '\n\ndef render_blocks(blocks: List[Dict[str, str]], translated: Dict[int, str], featured_image_url: Optional[str] = None) -> str:\n', 1)

old_image = '''        elif btype == "image":
            _mid, src = upload_media(block.get("src"))
            if src:
                alt = html_lib.escape(block.get("alt") or "")
                parts.append(f'<figure class="wp-block-image owtv-inline-image"><img src="{html_lib.escape(src)}" alt="{alt}" /></figure>')
'''
new_image = '''        elif btype == "image":
            raw_src = block.get("src")
            if featured_image_url and normalize_media_identity(raw_src) == normalize_media_identity(featured_image_url):
                print(f"[MEDIA v92] Skip immagine inline gia usata come featured: {raw_src}", flush=True)
                continue
            _mid, src = upload_media(raw_src)
            if src:
                alt = html_lib.escape(block.get("alt") or "")
                parts.append(f'<figure class="wp-block-image owtv-inline-image"><img src="{html_lib.escape(src)}" alt="{alt}" /></figure>')
'''
if old_image in text:
    text = text.replace(old_image, new_image, 1)

text = text.replace(
    '    blocks, _html, featured_image = scrape_article(job["source_url"])\n    translated = translate_report_blocks(job.get("source_title") or job.get("title") or "", blocks, job["title"])\n    content = render_blocks(blocks, translated)\n',
    '    blocks, _html, featured_image = scrape_article(job["source_url"])\n    print(f"[REPORT v92] Blocchi estratti: total={len(blocks)} text={len([b for b in blocks if b.get(\'type\') in {\'heading\',\'paragraph\',\'quote\'}])} images={len([b for b in blocks if b.get(\'type\') == \'image\'])} embeds={len([b for b in blocks if b.get(\'type\') == \'embed\'])} featured={bool(featured_image)}", flush=True)\n    translated = translate_report_blocks(job.get("source_title") or job.get("title") or "", blocks, job["title"])\n    content = render_blocks(blocks, translated, featured_image)\n',
    1,
)

p.write_text(text, encoding="utf-8")
print("[V92 PROMPT] patch strategia prompt applicata")
