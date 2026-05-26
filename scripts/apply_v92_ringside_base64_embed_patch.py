from pathlib import Path
import re

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_RINGSIDE_BASE64_EMBED_PATCH = True" in text and "decode_possible_base64_html" in text:
    print("[V92 RSN64] patch gia applicata")
    raise SystemExit(0)

# Marker and imports.
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

helper = r'''

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
            decoded_bytes = base64.b64decode(padded, validate=False)
            decoded = decoded_bytes.decode("utf-8", errors="ignore").strip()
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
        print("[V92 RSN64] anchor extract_social_urls non trovato: skip helper insert")

new_extract = '''def extract_social_urls_from_html_fragment(fragment: str) -> List[str]:
    out: List[str] = []
    if not fragment:
        return out
    candidates = decode_possible_base64_html(str(fragment)) if "decode_possible_base64_html" in globals() else [str(fragment)]
    for raw_candidate in candidates:
        raw = html_lib.unescape(str(raw_candidate))
        try:
            soup = BeautifulSoup(raw, "html.parser")
            for tag in soup.find_all(["a", "iframe", "blockquote"]):
                for attr in ["href", "src", "cite", "data-href", "data-url"]:
                    val = tag.get(attr)
                    if val and looks_like_social_embed_url(val):
                        out.append(normalize_social_url(val))
        except Exception:
            pass
        for m in re.finditer(r"https?://[^\s'\"<>]+", raw, flags=re.I):
            u = m.group(0).rstrip("),.;]")
            if looks_like_social_embed_url(u):
                out.append(normalize_social_url(u))
    deduped: List[str] = []
    seen: set[str] = set()
    for u in out:
        key = social_embed_key(u)
        if key and key not in seen:
            seen.add(key)
            deduped.append(u)
    return deduped
'''

func_pattern = re.compile(
    r'def extract_social_urls_from_html_fragment\(fragment: str\) -> List\[str\]:\n.*?\n\ndef extract_ringside_embed_blocks',
    re.DOTALL,
)
replacement = new_extract + "\n\ndef extract_ringside_embed_blocks"
text, count = func_pattern.subn(replacement, text, count=1)
if count != 1:
    if "decode_possible_base64_html(str(fragment))" in text:
        print("[V92 RSN64] extract_social_urls sembra gia base64-aware")
    else:
        print("[V92 RSN64] funzione extract_social_urls non trovata: non blocco il workflow")

# Include known v87.1 attr/class names in log scanning if the exact list exists.
text = text.replace(
    '            for attr in ["data-rsn-html", "data-html", "data-embed", "data-lazy", "data-src", "data-url", "href", "src"]:',
    '            for attr in ["data-rsn-html", "data-rsn_html", "data-html", "data-embed", "data-lazy", "data-src", "data-url", "href", "src"]:',
    1,
)

p.write_text(text, encoding="utf-8")
print("[V92 RSN64] decode base64 lazy embed applicato/tollerato")
