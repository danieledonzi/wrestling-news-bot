from pathlib import Path

p = Path('agents/publisher.py')
s = p.read_text(encoding='utf-8')
if 'v93_29_base_embed_patch' in s:
    print('[V93 BASE PUBLISHER] gia applicato')
    raise SystemExit(0)

s = s.replace('PUBLISHER_VERSION = "v93_10_publisher_plain_oembed_urls"', 'PUBLISHER_VERSION = "v93_29_base_embed_patch"')
s = s.replace('from typing import Any\n', 'from typing import Any\nfrom urllib.parse import parse_qs, urlparse\n')
s = s.replace('PLAIN_EMBED_URL_RE = re.compile(r"(?m)^\\s*(https?://(?:www\\.)?(?:x\\.com|twitter\\.com|instagram\\.com|youtube\\.com|youtu\\.be|tiktok\\.com|threads\\.net|facebook\\.com|bsky\\.app)/\\S+)\\s*$", re.I)\n', 'EMBED_URL_PATTERN = r"https?://(?:www\\.)?(?:x\\.com|twitter\\.com|instagram\\.com|youtube\\.com|youtube-nocookie\\.com|youtu\\.be|tiktok\\.com|threads\\.net|facebook\\.com|bsky\\.app)/\\S+"\nPLAIN_EMBED_URL_RE = re.compile(rf"(?m)^\\s*({EMBED_URL_PATTERN})\\s*$", re.I)\nP_ONLY_EMBED_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s*</p>", re.I)\nP_START_EMBED_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s*(?:<br\\s*/?>|\\n|\\r\\n)+\\s*(.*?)</p>", re.I | re.S)\nP_URL_THEN_TEXT_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s+([^<].*?)</p>", re.I | re.S)\nWP_EMBED_BLOCK_RE = re.compile(r"<!-- wp:embed [\\s\\S]*?<!-- /wp:embed -->", re.I)\nEMBED_URL_ANY_RE = re.compile(rf"({EMBED_URL_PATTERN})", re.I)\n')
insert_after = '''def extract_image_placeholders(body_html: str) -> list[str]:
    return [m.group(1).strip() for m in IMAGE_PLACEHOLDER_RE.finditer(body_html or "") if m.group(1).strip()]

'''
helpers = '''def clean_url(url: str) -> str:
    return html.unescape(str(url or "").strip()).rstrip(".,;:)]}\\u201d\\u2019</p>")


def embed_key(url: str) -> str:
    u = clean_url(url)
    parsed = urlparse(u)
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.strip("/")
    q = parse_qs(parsed.query)
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        vid = ""
        if host == "youtu.be":
            vid = path.split("/", 1)[0]
        elif path.startswith("watch"):
            vid = (q.get("v") or [""])[0]
        elif path.startswith("embed/"):
            vid = path.split("/", 1)[1].split("/", 1)[0]
        if vid:
            return "youtube:" + vid.lower()
    if host in {"x.com", "twitter.com"}:
        parts = [x for x in path.split("/") if x]
        if "status" in parts:
            i = parts.index("status")
            if i + 1 < len(parts):
                return "twitter:" + parts[i + 1].lower()
    return host + ":" + path.lower()


def display_embed_url(url: str) -> str:
    u = clean_url(url)
    k = embed_key(u)
    if k.startswith("youtube:"):
        return "https://www.youtube.com/watch?v=" + k.split(":", 1)[1]
    return u


def embed_block(url: str) -> str:
    u = display_embed_url(url)
    host = urlparse(u).netloc.lower().replace("www.", "")
    provider = "twitter" if host in {"x.com", "twitter.com"} else ("youtube" if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"} else "")
    typ = "video" if provider == "youtube" else "rich"
    cls = "is-type-video is-provider-youtube wp-block-embed-youtube" if provider == "youtube" else "is-type-rich is-provider-twitter wp-block-embed-twitter"
    attrs = json.dumps({"url": u, "type": typ, "providerNameSlug": provider, "responsive": True}, ensure_ascii=False, separators=(",", ":"))
    return '<!-- wp:embed ' + attrs + ' -->\\n<figure class="wp-block-embed ' + cls + '"><div class="wp-block-embed__wrapper">\\n' + html.escape(u) + '\\n</div></figure>\\n<!-- /wp:embed -->'


def convert_embed_urls(body_html: str) -> str:
    seen: set[str] = set()
    def repl(match):
        url = match.group(1)
        k = embed_key(url)
        if k in seen:
            return ""
        seen.add(k)
        rest = match.group(2).strip() if len(match.groups()) > 1 and match.group(2) else ""
        out = "\\n\\n" + embed_block(url) + "\\n\\n"
        return out + ("<p>" + rest + "</p>" if rest else "")
    text = body_html or ""
    text = P_START_EMBED_RE.sub(repl, text)
    text = P_URL_THEN_TEXT_RE.sub(repl, text)
    text = P_ONLY_EMBED_RE.sub(repl, text)
    text = PLAIN_EMBED_URL_RE.sub(repl, text)
    text = re.sub(r"\\n{3,}", "\\n\\n", text)
    return text


'''
if insert_after not in s:
    raise SystemExit('[V93 BASE PUBLISHER] image placeholder anchor non trovato')
s = s.replace(insert_after, insert_after + helpers, 1)
s = s.replace('    body_html = re.sub(r"<p>\\s*</p>", "", body_html)\n    body_html = re.sub(r"\\n{3,}", "\\n\\n", body_html)\n', '    body_html = convert_embed_urls(body_html)\n    body_html = re.sub(r"<p>\\s*</p>", "", body_html)\n    body_html = re.sub(r"\\n{3,}", "\\n\\n", body_html)\n', 1)
s = s.replace('"mode": "wordpress_publisher_plain_oembed_urls",', '"mode": "wordpress_publisher_gutenberg_embeds",')
s = s.replace('"preserve_plain_embed_urls_for_wordpress_oembed": True,', '"plain_embed_urls_to_gutenberg_blocks": True, "normalized_embed_dedupe": True,')
p.write_text(s, encoding='utf-8')
print('[V93 BASE PUBLISHER] applicato')
