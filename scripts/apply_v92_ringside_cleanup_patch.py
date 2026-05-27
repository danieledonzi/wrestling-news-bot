from pathlib import Path

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_RINGSIDE_CLEANUP_PATCH_V2 = True" in text:
    print("[V92 RSN CLEAN] patch v2 gia applicata")
    raise SystemExit(0)

# Upgrade old marker/idempotency without blocking.
if "V92_RINGSIDE_CLEANUP_PATCH_V2 = True" not in text:
    marker = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
    if marker in text:
        text = text.replace(marker, 'V92_RINGSIDE_CLEANUP_PATCH_V2 = True\n' + marker, 1)
    elif "V92_RINGSIDE_CLEANUP_PATCH = True\n" in text:
        text = text.replace("V92_RINGSIDE_CLEANUP_PATCH = True\n", "V92_RINGSIDE_CLEANUP_PATCH = True\nV92_RINGSIDE_CLEANUP_PATCH_V2 = True\n", 1)

# Twitter/X embeds must be actual status URLs. Profile URLs create timelines or raw paragraphs.
start = text.find("def looks_like_social_embed_url(url: str) -> bool:")
end = text.find("\n\ndef extract_social_urls_from_html_fragment", start)
if start != -1 and end != -1:
    new_func = '''def looks_like_social_embed_url(url: str) -> bool:
    u = normalize_social_url(url or "")
    if not re.search(r"(?:twitter\\.com|x\\.com|instagram\\.com|youtube\\.com|youtu\\.be|tiktok\\.com)", u, re.I):
        return False
    if re.search(r"/(share|intent|hashtag|search)(?:/|\\?|$)", u, re.I):
        return False
    # X/Twitter: keep only concrete posts, never profiles/timelines.
    if re.search(r"(?:twitter\\.com|x\\.com)", u, re.I):
        return bool(re.search(r"/(?:status|statuses)/\\d+", u, re.I))
    # Instagram/YouTube are allowed only as concrete media, not profile/channel bars.
    if re.search(r"instagram\\.com", u, re.I):
        return bool(re.search(r"instagram\\.com/(?:p|reel|tv)/", u, re.I))
    if re.search(r"youtube\\.com|youtu\\.be", u, re.I):
        return bool(re.search(r"(?:watch\\?v=|youtu\\.be/|/shorts/|/embed/)", u, re.I))
    return True
'''
    text = text[:start] + new_func + text[end:]
else:
    print("[V92 RSN CLEAN] looks_like_social_embed_url function non trovata")

helper = '''

def is_raw_social_profile_text(text: str) -> bool:
    probe = (text or "").strip()
    if not probe:
        return False
    low = probe.lower()
    if "tweets by ringsidenews" in low or "follow us" in low or "connect with us" in low:
        return True
    if not re.match(r"^https?://", probe, re.I):
        return False
    # Any isolated profile/channel/social URL is boilerplate unless it is a concrete tweet/status.
    if re.search(r"(?:twitter\\.com|x\\.com)", probe, re.I):
        return not bool(re.search(r"/(?:status|statuses)/\\d+", probe, re.I))
    if re.search(r"(?:instagram\\.com|youtube\\.com/channel|youtube\\.com/@|facebook\\.com|linkedin\\.com|pinterest\\.com|snapchat\\.com|reddit\\.com|tumblr\\.com|t\\.me)", probe, re.I):
        return True
    return False


def is_source_author_bio_text(text: str) -> bool:
    probe = normalize_text(text or "")
    if not probe:
        return False
    author_patterns = [
        "sanjay thakur riporta i risultati",
        "sanjay thakur provides live results",
        "riporta i risultati in diretta degli show wwe e aew",
        "riporta i risultati in tempo reale per gli show wwe e aew",
        "provides live results for wwe and aew shows",
        "reports live results for wwe and aew shows",
        "covers live results for wwe and aew shows",
        "copertura dettagliata di raw smackdown dynamite nxt",
        "seguendo raw smackdown dynamite nxt",
    ]
    if any(pat in probe for pat in author_patterns):
        return True
    if "ringside news" in probe and "follow" in probe and "twitter" in probe:
        return True
    return False
'''

# Replace existing helper definitions if present; otherwise insert before source intro filter.
start = text.find("def is_raw_social_profile_text(text: str) -> bool:")
end = text.find("\n\ndef is_source_intro_text(text: str) -> bool:", start)
if start != -1 and end != -1:
    text = text[:start] + helper.strip() + text[end:]
elif "def is_source_intro_text(text: str) -> bool:" in text:
    text = text.replace("\n\ndef is_source_intro_text(text: str) -> bool:\n", helper + "\n\ndef is_source_intro_text(text: str) -> bool:\n", 1)
else:
    print("[V92 RSN CLEAN] helper anchor non trovato")

# Ensure extraction skip is present even if prior patch did not match.
if "Skip raw social/profile paragraph" not in text:
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

# Render-stage safety net: remove any remaining text blocks/social profile noise before HTML assembly.
render_anchor = "    rendered_parts: List[str] = []\n"
filter_block = '''    filtered_blocks: List[Dict[str, str]] = []
    for block in blocks:
        if block.get("type") in {"paragraph", "heading", "quote"}:
            candidate_text = block.get("translated") or block.get("text") or ""
            if is_raw_social_profile_text(candidate_text) or is_source_author_bio_text(candidate_text):
                print(f"[REPORT v92] Render skip boilerplate/social: {candidate_text[:140]}", flush=True)
                continue
        if block.get("type") == "embed" and not looks_like_social_embed_url(block.get("url", "")):
            print(f"[REPORT v92] Render skip invalid embed/profile: {block.get('url', '')[:140]}", flush=True)
            continue
        filtered_blocks.append(block)
    blocks = filtered_blocks

'''
if render_anchor in text and "Render skip boilerplate/social" not in text:
    text = text.replace(render_anchor, filter_block + render_anchor, 1)

p.write_text(text, encoding="utf-8")
print("[V92 RSN CLEAN] cleanup v2 applicato")
