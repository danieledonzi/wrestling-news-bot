from pathlib import Path

# -----------------------------------------------------------------------------
# v92 news factual guardrails.
# Problem observed: Gemini changed "Clash in Italy" into "Clash at the Castle",
# creating factually wrong articles. This is a factual hallucination, not a style
# issue. Add protected event names, deterministic cleanup, and a hard minimum on
# extracted article text before translation.
# -----------------------------------------------------------------------------

p = Path("modules/news_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_NEWS_FACTUAL_GUARDRAILS_PATCH = True" in text:
    print("[V92 NEWS FACTUAL] patch gia applicata")
    raise SystemExit(0)

text = text.replace(
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n",
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_NEWS_FACTUAL_GUARDRAILS_PATCH = True\nV92_MIN_NEWS_SOURCE_CHARS = int(os.getenv(\"V92_MIN_NEWS_SOURCE_CHARS\", \"650\"))\n",
    1,
)

# Insert helpers before translate_news.
anchor = "\n\ndef translate_news(source_title: str, source_text: str, source: str) -> Tuple[str, str, str]:\n"
helpers = r'''

def source_context_blob(source_title: str, source_text: str) -> str:
    return normalize_text(f"{source_title} {source_text}")


def protected_event_instructions(source_title: str, source_text: str) -> str:
    blob = source_context_blob(source_title, source_text)
    rules: List[str] = []
    if "clash in italy" in blob:
        rules.append("- Nome evento protetto: scrivi sempre e solo 'Clash in Italy'. Non trasformarlo mai in 'Clash at the Castle', 'Clash in the Castle' o varianti simili.")
    if "clash at the castle" in blob:
        rules.append("- Nome evento protetto: se il testo originale dice 'Clash at the Castle', mantieni esattamente 'Clash at the Castle'.")
    if "all in" in blob:
        rules.append("- Nome evento protetto: 'All In' resta 'All In'.")
    if "double or nothing" in blob:
        rules.append("- Nome evento protetto: 'Double or Nothing' resta 'Double or Nothing'.")
    if "forbidden door" in blob:
        rules.append("- Nome evento protetto: 'Forbidden Door' resta 'Forbidden Door'.")
    if "worlds end" in blob or "world's end" in blob:
        rules.append("- Nome evento protetto: 'Worlds End' resta 'Worlds End'.")
    return "\n".join(rules)


def cleanup_protected_event_names(title: str, body_html: str, source_title: str, source_text: str) -> Tuple[str, str]:
    blob = source_context_blob(source_title, source_text)
    out_title = title or ""
    out_body = body_html or ""
    if "clash in italy" in blob:
        patterns = [
            r"\bWWE\s+Clash\s+at\s+the\s+Castle\s+in\s+Italia\b",
            r"\bWWE\s+Clash\s+in\s+the\s+Castle\s+in\s+Italia\b",
            r"\bClash\s+at\s+the\s+Castle\s+in\s+Italia\b",
            r"\bClash\s+in\s+the\s+Castle\s+in\s+Italia\b",
            r"\bWWE\s+Clash\s+at\s+the\s+Castle\b",
            r"\bWWE\s+Clash\s+in\s+the\s+Castle\b",
            r"\bClash\s+at\s+the\s+Castle\b",
            r"\bClash\s+in\s+the\s+Castle\b",
        ]
        for pattern in patterns:
            out_title = re.sub(pattern, "WWE Clash in Italy", out_title, flags=re.I)
            out_body = re.sub(pattern, "WWE Clash in Italy", out_body, flags=re.I)
    return out_title, out_body


def validate_no_event_hallucination(title: str, body_html: str, source_title: str, source_text: str) -> None:
    src = source_context_blob(source_title, source_text)
    out = normalize_text(f"{title} {body_html}")
    if "clash at the castle" in out and "clash at the castle" not in src:
        raise RuntimeError("Factual guardrail: output contiene Clash at the Castle non presente nella fonte")
    if "clash in the castle" in out and "clash in the castle" not in src:
        raise RuntimeError("Factual guardrail: output contiene Clash in the Castle non presente nella fonte")


def validate_source_text_quality(source_text: str, source_url: str) -> None:
    chars = len(source_text or "")
    if chars < V92_MIN_NEWS_SOURCE_CHARS:
        raise RuntimeError(f"Source extraction too short for safe translation: chars={chars} url={source_url}")
'''
if anchor not in text:
    raise SystemExit("[V92 NEWS FACTUAL] translate_news anchor non trovato")
text = text.replace(anchor, helpers + anchor, 1)

# Add protected instructions to prompt after mandatory rules.
prompt_anchor = "- Evita stile AI, frasi gonfie, ripetizioni inutili e formule generiche.\n"
insert = "{protected_event_instructions(source_title, source_text)}\n"
if insert not in text:
    text = text.replace(prompt_anchor, prompt_anchor + insert, 1)

# Replace return cleanup in translate_news. This should also cooperate with other
# cleanup patches if present.
old_return = '''    title = clean_text(str(data.get("title") or source_title))[:120]
    body = str(data.get("body_html") or "").strip()
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
new_return = '''    title = clean_text(str(data.get("title") or source_title))[:120]
    body = str(data.get("body_html") or "").strip()
    title, body = cleanup_protected_event_names(title, body, source_title, source_text)
    validate_no_event_hallucination(title, body, source_title, source_text)
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
if old_return in text:
    text = text.replace(old_return, new_return, 1)
else:
    # Tolerant replacement if glossary cleanup already changed this area.
    old_alt = '''    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
    new_alt = '''    title, body = cleanup_protected_event_names(title, body, source_title, source_text)
    validate_no_event_hallucination(title, body, source_title, source_text)
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
    if old_alt in text:
        text = text.replace(old_alt, new_alt, 1)
    else:
        print("[V92 NEWS FACTUAL] return translate anchor non trovato")

# Validate extraction before translation.
old_run_line = '''    print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)}", flush=True)
    title, body_html, model = translate_news(str(job.get("source_title") or ""), source_text, str(job.get("source") or ""))
'''
new_run_line = '''    print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)}", flush=True)
    validate_source_text_quality(source_text, str(job.get("source_url") or ""))
    title, body_html, model = translate_news(str(job.get("source_title") or ""), source_text, str(job.get("source") or ""))
'''
if old_run_line in text:
    text = text.replace(old_run_line, new_run_line, 1)
else:
    old_run_line2 = '''    print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)} embeds={len(embeds)}", flush=True)
    title, body_html, model = translate_news(str(job.get("source_title") or ""), source_text, str(job.get("source") or ""))
'''
    new_run_line2 = '''    print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)} embeds={len(embeds)}", flush=True)
    validate_source_text_quality(source_text, str(job.get("source_url") or ""))
    title, body_html, model = translate_news(str(job.get("source_title") or ""), source_text, str(job.get("source") or ""))
'''
    if old_run_line2 in text:
        text = text.replace(old_run_line2, new_run_line2, 1)
    else:
        print("[V92 NEWS FACTUAL] run_news_workshop extraction validation anchor non trovato")

p.write_text(text, encoding="utf-8")
print("[V92 NEWS FACTUAL] protected event names + source quality guardrails applicati")
