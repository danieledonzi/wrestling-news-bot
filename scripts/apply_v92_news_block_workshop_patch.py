from pathlib import Path

# -----------------------------------------------------------------------------
# v92 news block workshop patch.
# Problem: the news workshop extracted a single text body and asked Gemini for a
# whole article. In practice this caused summaries, lost embeds and lost internal
# media. Reports work better because they extract ordered blocks and translate
# block-by-block. This patch switches NEWS publication to the same philosophy:
# scrape ordered blocks, translate each text block separately, preserve images and
# embeds in place, and render final HTML deterministically.
# -----------------------------------------------------------------------------

p = Path("modules/news_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_NEWS_BLOCK_WORKSHOP_PATCH = True" in text:
    print("[V92 NEWS BLOCKS] patch gia applicata")
    raise SystemExit(0)

# Marker after imports/cache area.
text = text.replace(
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n",
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_NEWS_BLOCK_WORKSHOP_PATCH = True\n",
    1,
)

# Add block helpers before run_news_workshop.
anchor = "\n\ndef run_news_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:\n"
pos = text.find(anchor)
if pos == -1:
    raise SystemExit("[V92 NEWS BLOCKS] run_news_workshop anchor non trovato")

helpers = r'''

def news_text_blocks(blocks: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        if block.get("type") in {"heading", "paragraph", "quote"}:
            txt = clean_text(str(block.get("text") or ""))
            if txt:
                items.append({
                    "i": idx,
                    "type": block.get("type"),
                    "level": block.get("level"),
                    "text": txt,
                })
    return items


def validate_news_blocks_quality(blocks: List[Dict[str, str]], source_url: str) -> None:
    text_chars = sum(len(str(b.get("text") or "")) for b in blocks if b.get("type") in {"heading", "paragraph", "quote"})
    text_count = len([b for b in blocks if b.get("type") in {"heading", "paragraph", "quote"}])
    embed_count = len([b for b in blocks if b.get("type") == "embed"])
    image_count = len([b for b in blocks if b.get("type") == "image"])
    print(f"[NEWS v92] Blocchi news estratti: total={len(blocks)} text={text_count} images={image_count} embeds={embed_count} chars={text_chars}", flush=True)
    if text_chars < int(os.getenv("V92_MIN_NEWS_SOURCE_CHARS", "650")):
        raise RuntimeError(f"News block extraction too short for safe publication: chars={text_chars} url={source_url}")


def protected_news_event_rules(source_title: str, blocks: List[Dict[str, str]]) -> str:
    blob = normalize_text(source_title + " " + " ".join(str(b.get("text") or b.get("url") or "") for b in blocks))
    rules: List[str] = []
    if "clash in italy" in blob:
        rules.append("- Nome evento protetto: scrivi sempre e solo 'Clash in Italy'. Non trasformarlo mai in 'Clash at the Castle' o varianti simili.")
    if "clash at the castle" in blob:
        rules.append("- Nome evento protetto: mantieni esattamente 'Clash at the Castle' solo se presente nella fonte.")
    if "all in" in blob:
        rules.append("- Nome evento protetto: 'All In' resta 'All In'.")
    if "double or nothing" in blob:
        rules.append("- Nome evento protetto: 'Double or Nothing' resta 'Double or Nothing'.")
    if "forbidden door" in blob:
        rules.append("- Nome evento protetto: 'Forbidden Door' resta 'Forbidden Door'.")
    return "\n".join(rules)


def translate_news_blocks(source_title: str, blocks: List[Dict[str, str]], source: str) -> Tuple[str, Dict[int, str], str]:
    items = news_text_blocks(blocks)
    if not items:
        raise RuntimeError("Nessun blocco testuale news da tradurre")
    prompt = f"""
Sei un giornalista italiano esperto di wrestling.
Devi adattare in italiano i blocchi di una news mantenendo la struttura originale.

Regole obbligatorie:
- NON riassumere.
- NON comprimere più blocchi in uno solo.
- Restituisci lo stesso numero di item ricevuti.
- Conserva l'indice i di ogni item.
- Traduci ogni blocco separatamente.
- Mantieni fatti, nomi, date, show, titoli e citazioni.
- Non inventare informazioni non presenti nella fonte.
- Match resta sempre "match", non partita/incontro/gara/gioco.
- Per heading usa solo testo tradotto, senza tag HTML.
- Per paragraph/quote usa testo italiano naturale, senza markdown.
- Le quote restano quote: non trasformarle in paragrafo narrativo.
- Non citare la fonte nel corpo: la fonte viene aggiunta automaticamente dal sistema.
- Titolo italiano: naturale, giornalistico, non clickbait, massimo 95 caratteri.
{protected_news_event_rules(source_title, blocks)}

Rispondi SOLO con JSON valido:
{{"title":"titolo italiano","items":[{{"i":0,"text":"..."}}]}}

Fonte: {source_label(source)}
Titolo originale: {source_title}

BLOCCHI JSON:
{json.dumps(items, ensure_ascii=False)}
""".strip()
    raw, model = gemini_generate(prompt, purpose="news_translate_blocks")
    data = extract_json(raw)
    title = clean_text(str(data.get("title") or source_title))[:120]
    arr = data.get("items") or []
    translated: Dict[int, str] = {}
    for item in arr:
        try:
            idx = int(item.get("i"))
            txt = clean_text(str(item.get("text") or ""))
            if txt:
                translated[idx] = txt
        except Exception:
            continue
    expected = {int(item["i"]) for item in items}
    missing = expected.difference(translated)
    if len(missing) > max(2, int(len(expected) * 0.12)):
        raise RuntimeError(f"Traduzione news a blocchi incompleta: mancanti={sorted(list(missing))[:20]} model={model}")
    source_blob = normalize_text(source_title + " " + " ".join(str(b.get("text") or "") for b in blocks))
    out_blob = normalize_text(title + " " + " ".join(translated.values()))
    if "clash in italy" in source_blob and ("clash at the castle" in out_blob or "clash in the castle" in out_blob):
        raise RuntimeError("Factual guardrail: Clash in Italy trasformato in Clash at the Castle")
    return title, translated, model


def normalize_news_embed_url(url: str) -> str:
    try:
        from modules import report_workshop_v92 as report_engine
        return report_engine.normalize_social_url(url)
    except Exception:
        return re.sub(r"^https?://x\.com/", "https://twitter.com/", (url or "").strip(), flags=re.I)


def render_news_blocks(blocks: List[Dict[str, str]], translated: Dict[int, str]) -> str:
    parts: List[str] = []
    for idx, block in enumerate(blocks):
        btype = block.get("type")
        if btype == "heading":
            level = block.get("level") or "h2"
            if level not in {"h2", "h3"}:
                level = "h2"
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            if txt:
                parts.append(f"<{level}>{txt}</{level}>")
        elif btype == "paragraph":
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            if txt:
                parts.append(f"<p>{txt}</p>")
        elif btype == "quote":
            txt = html_lib.escape(translated.get(idx) or block.get("text", ""))
            if txt:
                parts.append(f"<blockquote><p>{txt}</p></blockquote>")
        elif btype == "image":
            media_id, src = upload_media(block.get("src"))
            if src:
                alt = html_lib.escape(block.get("alt") or "")
                parts.append(f'<figure class="wp-block-image owtv-inline-image"><img src="{html_lib.escape(src)}" alt="{alt}" /></figure>')
        elif btype == "embed":
            url = normalize_news_embed_url(block.get("url", ""))
            if url:
                parts.append(f"\n\n{html_lib.escape(url)}\n\n")
    html = "\n".join(parts)
    # Reuse cleanup helpers when previous patches have installed them.
    for fn_name in ["cleanup_news_quotes", "strip_internal_placeholders"]:
        fn = globals().get(fn_name)
        if callable(fn):
            html = fn(html)
    return html
'''
text = text[:pos] + helpers + text[pos:]

start = text.find("def run_news_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:")
end = text.find("\n", start + 1)
# Need to find function end: current run_news_workshop is last function in file in base, but patches may add after it.
next_def = text.find("\n\ndef ", start + 1)
if next_def == -1:
    next_def = len(text)

new_run = r'''def run_news_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:
    print(f"[NEWS v92] Avvio workshop news BLOCK: {job.get('news_key')} url={job.get('source_url')}", flush=True)
    from modules import report_workshop_v92 as report_engine
    blocks, _html, featured_image = report_engine.scrape_article(str(job["source_url"]))
    validate_news_blocks_quality(blocks, str(job.get("source_url") or ""))
    title, translated, model = translate_news_blocks(str(job.get("source_title") or ""), blocks, str(job.get("source") or ""))
    body_html = render_news_blocks(blocks, translated)
    print(f"[NEWS v92] Traduzione news blocchi completata: modello={model} title={title}", flush=True)
    if not body_html or len(clean_text(re.sub(r"<[^>]+>", " ", body_html))) < 300:
        raise RuntimeError("Body HTML news troppo corto dopo render a blocchi")
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    (review_dir / f"news_{slug}.blocks.json").write_text(json.dumps({
        "job": job,
        "blocks": blocks[:120],
        "translated_indexes": sorted(translated.keys()),
        "featured_image": featured_image,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (review_dir / f"news_{slug}.prepublish.html").write_text(body_html, encoding="utf-8")
    post_id, post_json = publish_news(job, title, body_html, featured_image)
    (published_dir / f"news_{slug}.html").write_text(body_html, encoding="utf-8")
    return post_id, post_json
'''
text = text[:start] + new_run + text[next_def:]

p.write_text(text, encoding="utf-8")
print("[V92 NEWS BLOCKS] news workshop a blocchi applicato")
