from pathlib import Path

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_REPORT_SOURCE_INTRO_FILTER = True" in text:
    print("[V92 INTRO FILTER] gia applicato")
    raise SystemExit(0)

# Marker.
if "V92_REPORT_LEGACY_TRANSLATION_PROMPT = True\n" in text:
    text = text.replace(
        "V92_REPORT_LEGACY_TRANSLATION_PROMPT = True\n",
        "V92_REPORT_LEGACY_TRANSLATION_PROMPT = True\nV92_REPORT_SOURCE_INTRO_FILTER = True\n",
        1,
    )
elif "V92_REPORT_RUNTIME_TWEAKS = True\n" in text:
    text = text.replace(
        "V92_REPORT_RUNTIME_TWEAKS = True\n",
        "V92_REPORT_RUNTIME_TWEAKS = True\nV92_REPORT_SOURCE_INTRO_FILTER = True\n",
        1,
    )
else:
    text = text.replace(
        'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
        'V92_REPORT_SOURCE_INTRO_FILTER = True\nSOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
        1,
    )

helper = '''\n\ndef is_source_intro_text(text: str) -> bool:\n    probe = normalize_text(text or "")\n    if not probe:\n        return False\n    source_intro_patterns = [\n        "welcome to wrestling inc",\n        "welcome to wrestlinginc",\n        "wrestling inc live coverage",\n        "wrestling inc s live coverage",\n        "wrestlinginc live coverage",\n        "benvenuti al report di wrestling inc",\n        "benvenuti alla copertura live di wrestling inc",\n        "benvenuti ai risultati di wrestling inc",\n        "benvenuti al live coverage di wrestling inc",\n        "ringside news live coverage",\n        "benvenuti alla copertura live di ringside news",\n    ]\n    if any(pattern in probe for pattern in source_intro_patterns):\n        return True\n    # Source-branded dateline intros add no editorial value in our report.\n    if probe.startswith("benvenuti") and ("wrestling inc" in probe or "ringside news" in probe):\n        return True\n    if probe.startswith("welcome") and ("wrestling inc" in probe or "ringside news" in probe):\n        return True\n    return False\n'''

if "def is_source_intro_text" not in text:
    text = text.replace("\n\ndef extract_blocks(content, base_url: str) -> List[Dict[str, str]]:\n", helper + "\n\ndef extract_blocks(content, base_url: str) -> List[Dict[str, str]]:\n", 1)

old = '''        text = clean_text(el.get_text(" ", strip=True))
        if len(text) < 20:
            continue
        if el.name in {"h2", "h3"}:
'''
new = '''        text = clean_text(el.get_text(" ", strip=True))
        if len(text) < 20:
            continue
        if is_source_intro_text(text):
            print(f"[REPORT v92] Skip source intro paragraph: {text[:140]}", flush=True)
            continue
        if el.name in {"h2", "h3"}:
'''

if old not in text:
    raise SystemExit("[V92 INTRO FILTER] blocco text extraction non trovato")
text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")
print("[V92 INTRO FILTER] source intro filter applicato")
