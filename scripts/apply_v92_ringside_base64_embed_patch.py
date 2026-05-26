from pathlib import Path

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_RINGSIDE_BASE64_EMBED_PATCH = True" in text and "decode_possible_base64_html" in text:
    print("[V92 RSN64] patch gia applicata")
    raise SystemExit(0)

if "import base64" not in text:
    text = text.replace(
        "from urllib.parse import urljoin, urlparse\n",
        "from urllib.parse import urljoin, urlparse\nimport base64\n",
        1,
    )

marker = "V92_RINGSIDE_EMBED_RECOVERY = True\n"
if "V92_RINGSIDE_BASE64_EMBED_PATCH = True" not in text:
    if marker in text:
        text = text.replace(marker, marker + "V92_RINGSIDE_BASE64_EMBED_PATCH = True\n", 1)
    else:
        text = text.replace(
            'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
            'V92_RINGSIDE_BASE64_EMBED_PATCH = True\nSOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n',
            1,
        )

helper = '''

def decode_possible_base64_html(value: str) -> List[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    candidates = [raw]
    unescaped = html_lib.unescape(raw).strip()
    if unescaped and unescaped not in candidates:
        candidates.append(unescaped)
    normalized = unescaped.replace("-", "+").replace("_", "/")
    variants = [unescaped, normalized, normalized + ("=" * ((4 - len(normalized) % 4) % 4))]
    for candidate in variants:
        if not candidate:
            continue
        try:
            padded = candidate + ("=" * ((4 - len(candidate) % 4) % 4))
            decoded = base64.b64decode(padded, validate=False).decode("utf-8", errors="ignore").strip()
            if decoded and decoded not in candidates:
                candidates.append(decoded)
        except Exception:
            continue
    return candidates
'''

if "def decode_possible_base64_html" not in text:
    anchor = "\n\ndef extract_social_urls_from_html_fragment(fragment: str) -> List[str]:\n"
    if anchor in text:
        text = text.replace(anchor, helper + anchor, 1)
    else:
        print("[V92 RSN64] anchor funzione social non trovato: continuo senza bloccare")

old_line = '    raw = html_lib.unescape(str(fragment))\n'
new_block = '''    decoded_candidates = decode_possible_base64_html(str(fragment)) if "decode_possible_base64_html" in globals() else [str(fragment)]
    raw = html_lib.unescape(" ".join(decoded_candidates))
'''
if old_line in text and "decoded_candidates = decode_possible_base64_html" not in text:
    text = text.replace(old_line, new_block, 1)
elif "decoded_candidates = decode_possible_base64_html" in text:
    print("[V92 RSN64] funzione social gia base64-aware")
else:
    print("[V92 RSN64] riga raw social non trovata: continuo senza bloccare")

text = text.replace(
    '            for attr in ["data-rsn-html", "data-html", "data-embed", "data-lazy", "data-src", "data-url", "href", "src"]:',
    '            for attr in ["data-rsn-html", "data-rsn_html", "data-html", "data-embed", "data-lazy", "data-src", "data-url", "href", "src"]:',
    1,
)

p.write_text(text, encoding="utf-8")
print("[V92 RSN64] decode base64 lazy embed applicato/tollerato")
