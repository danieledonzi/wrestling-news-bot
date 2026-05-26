from pathlib import Path

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_RINGSIDE_CLEANUP_PATCH = True" in text:
    print("[V92 RSN CLEAN] patch gia applicata")
    raise SystemExit(0)

marker = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
text = text.replace(marker, 'V92_RINGSIDE_CLEANUP_PATCH = True\n' + marker, 1)

# Twitter/X embeds must be actual status URLs. Profile URLs create timelines or raw paragraphs.
old = '''def looks_like_social_embed_url(url: str) -> bool:
    u = normalize_social_url(url or "")
    if not re.search(r"(?:twitter\.com|x\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com)", u, re.I):
        return False
    # Filter obvious sharing/profile/credit noise where possible.
    if re.search(r"/(share|intent|hashtag|search)(?:/|\?|$)", u, re.I):
        return False
    return True
'''
new = '''def looks_like_social_embed_url(url: str) -> bool:
    u = normalize_social_url(url or "")
    if not re.search(r"(?:twitter\.com|x\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com)", u, re.I):
        return False
    if re.search(r"/(share|intent|hashtag|search)(?:/|\?|$)", u, re.I):
        return False
    if re.search(r"(?:twitter\.com|x\.com)", u, re.I):
        return bool(re.search(r"/(?:status|statuses)/\d+", u, re.I))
    return True
'''
if old in text:
    text = text.replace(old, new, 1)
else:
    print("[V92 RSN CLEAN] looks_like_social_embed_url block non trovato")

# Remove raw profile/social URL paragraphs from extracted text blocks.
helper = '''

def is_raw_social_profile_text(text: str) -> bool:
    probe = (text or "").strip()
    if not probe:
        return False
    if not re.match(r"^https?://", probe, re.I):
        return False
    if re.search(r"(?:twitter\.com|x\.com)", probe, re.I):
        return not bool(re.search(r"/(?:status|statuses)/\d+", probe, re.I))
    if re.search(r"(?:instagram\.com|youtube\.com|youtu\.be|facebook\.com|t\.me)", probe, re.I):
        return True
    return False


def is_source_author_bio_text(text: str) -> bool:
    probe = normalize_text(text or "")
    if not probe:
        return False
    author_patterns = [
        "riporta i risultati in tempo reale per gli show wwe e aew",
        "reports live results for wwe and aew shows",
        "covers live results for wwe and aew shows",
        "seguendo raw smackdown dynamite nxt",
    ]
    if any(pat in probe for pat in author_patterns):
        return True
    if "ringside news" in probe and "follow" in probe and "twitter" in probe:
        return True
    return False
'''
anchor = "\n\ndef is_source_intro_text(text: str) -> bool:\n"
if "def is_raw_social_profile_text" not in text and anchor in text:
    text = text.replace(anchor, helper + anchor, 1)

old_extraction = '''        if is_source_intro_text(text):
            print(f"[REPORT v92] Skip source intro paragraph: {text[:140]}", flush=True)
            continue
        if el.name in {"h2", "h3"}:
'''
new_extraction = '''        if is_source_intro_text(text):
            print(f"[REPORT v92] Skip source intro paragraph: {text[:140]}", flush=True)
            continue
        if is_raw_social_profile_text(text):
            print(f"[REPORT v92] Skip raw social/profile paragraph: {text[:140]}", flush=True)
            continue
        if is_source_author_bio_text(text):
            print(f"[REPORT v92] Skip source author/bio paragraph: {text[:140]}", flush=True)
            continue
        if el.name in {"h2", "h3"}:
'''
if old_extraction in text:
    text = text.replace(old_extraction, new_extraction, 1)
else:
    print("[V92 RSN CLEAN] extraction skip block non trovato")

p.write_text(text, encoding="utf-8")
print("[V92 RSN CLEAN] profile link e author boilerplate filter applicati")
