from pathlib import Path

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_REPORT_RUNTIME_TWEAKS = True" in text:
    print("[V92 TWEAKS] runtime tweaks gia applicati")
    raise SystemExit(0)

text = text.replace(
    "V92_REPORT_PROMPT_STRATEGY_PATCH = True\n",
    "V92_REPORT_PROMPT_STRATEGY_PATCH = True\nV92_REPORT_RUNTIME_TWEAKS = True\n",
    1,
)

# Dedicated model chain for reports: default to 3 Flash Preview before 3.1 Lite.
if "REPORT_MODEL_CHAIN" not in text:
    text = text.replace(
        "MODEL_CHAIN = [m.strip() for m in os.getenv(\n    \"GEMINI_MODEL_CHAIN\",\n    \"gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash-lite,gemini-2.5-flash\",\n).split(\",\") if m.strip()]\n",
        "MODEL_CHAIN = [m.strip() for m in os.getenv(\n    \"GEMINI_MODEL_CHAIN\",\n    \"gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash-lite,gemini-2.5-flash\",\n).split(\",\") if m.strip()]\nREPORT_MODEL_CHAIN = [m.strip() for m in os.getenv(\n    \"GEMINI_REPORT_MODEL_CHAIN\",\n    \"gemini-3-flash-preview,gemini-3.1-flash-lite,gemini-2.5-flash,gemini-2.5-flash-lite\",\n).split(\",\") if m.strip()]\n",
        1,
    )

old_chain = '''    print(f"[TRANSLATE v92] Chain attiva: {chain_name} | modelli={','.join(MODEL_CHAIN)}", flush=True)
    client = genai.Client(api_key=GEMINI_API_KEY)
    last: Optional[Exception] = None
    for model in MODEL_CHAIN:
'''
new_chain = '''    active_models = REPORT_MODEL_CHAIN if chain_name.startswith("report_") else MODEL_CHAIN
    print(f"[TRANSLATE v92] Chain attiva: {chain_name} | modelli={','.join(active_models)}", flush=True)
    client = genai.Client(api_key=GEMINI_API_KEY)
    last: Optional[Exception] = None
    for model in active_models:
'''
if old_chain in text:
    text = text.replace(old_chain, new_chain, 1)

# If a featured image exists, skip the first inline image unconditionally. The same editorial image can have different URLs after WP upload.
old_loop = '''    parts: List[str] = []
    for idx, block in enumerate(blocks):
        btype = block["type"]
'''
new_loop = '''    parts: List[str] = []
    first_inline_image_seen = False
    for idx, block in enumerate(blocks):
        btype = block["type"]
'''
if old_loop in text:
    text = text.replace(old_loop, new_loop, 1)

old_image = '''        elif btype == "image":
            raw_src = block.get("src")
            if featured_image_url and normalize_media_identity(raw_src) == normalize_media_identity(featured_image_url):
                print(f"[MEDIA v92] Skip immagine inline gia usata come featured: {raw_src}", flush=True)
                continue
            _mid, src = upload_media(raw_src)
'''
new_image = '''        elif btype == "image":
            raw_src = block.get("src")
            if featured_image_url and not first_inline_image_seen:
                first_inline_image_seen = True
                print(f"[MEDIA v92] Skip prima immagine inline per featured attiva: {raw_src}", flush=True)
                continue
            first_inline_image_seen = True
            if featured_image_url and normalize_media_identity(raw_src) == normalize_media_identity(featured_image_url):
                print(f"[MEDIA v92] Skip immagine inline gia usata come featured: {raw_src}", flush=True)
                continue
            _mid, src = upload_media(raw_src)
'''
if old_image in text:
    text = text.replace(old_image, new_image, 1)
else:
    raise SystemExit("[V92 TWEAKS] blocco immagine non trovato")

p.write_text(text, encoding="utf-8")
print("[V92 TWEAKS] report model chain e skip first image applicati")
