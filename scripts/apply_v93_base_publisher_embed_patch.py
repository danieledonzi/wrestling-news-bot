from pathlib import Path

p = Path('agents/publisher.py')
s = p.read_text(encoding='utf-8')
if 'v93_33_youtube_plain_social_shortcode_story_dedupe' in s:
    print('[V93 BASE PUBLISHER] gia applicato')
    raise SystemExit(0)

for old_version in [
    'PUBLISHER_VERSION = "v93_10_publisher_plain_oembed_urls"',
    'PUBLISHER_VERSION = "v93_29_base_embed_patch"',
    'PUBLISHER_VERSION = "v93_30_base_embed_shortcode_story_dedupe"',
]:
    s = s.replace(old_version, 'PUBLISHER_VERSION = "v93_33_youtube_plain_social_shortcode_story_dedupe"')

if 'from urllib.parse import parse_qs, urlparse' not in s:
    s = s.replace('from typing import Any\n', 'from typing import Any\nfrom urllib.parse import parse_qs, urlparse\n')

old_re = 'PLAIN_EMBED_URL_RE = re.compile(r"(?m)^\\s*(https?://(?:www\\.)?(?:x\\.com|twitter\\.com|instagram\\.com|youtube\\.com|youtu\\.be|tiktok\\.com|threads\\.net|facebook\\.com|bsky\\.app)/\\S+)\\s*$", re.I)\n'
new_re = 'EMBED_URL_PATTERN = r"https?://(?:www\\.)?(?:x\\.com|twitter\\.com|instagram\\.com|youtube\\.com|youtube-nocookie\\.com|youtu\\.be|tiktok\\.com|threads\\.net|facebook\\.com|bsky\\.app)/\\S+"\nPLAIN_EMBED_URL_RE = re.compile(rf"(?m)^\\s*({EMBED_URL_PATTERN})\\s*$", re.I)\nP_ONLY_EMBED_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s*</p>", re.I)\nP_START_EMBED_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s*(?:<br\\s*/?>|\\n|\\r\\n)+\\s*(.*?)</p>", re.I | re.S)\nP_URL_THEN_TEXT_RE = re.compile(rf"<p>\\s*({EMBED_URL_PATTERN})\\s+([^<].*?)</p>", re.I | re.S)\nWP_EMBED_BLOCK_RE = re.compile(r"<!-- wp:embed [\\s\\S]*?<!-- /wp:embed -->", re.I)\nEMBED_URL_ANY_RE = re.compile(rf"({EMBED_URL_PATTERN})", re.I)\n'
if 'EMBED_URL_PATTERN = r"https?' not in s:
    if old_re not in s:
        raise SystemExit('[V93 BASE PUBLISHER] embed regex anchor non trovato')
    s = s.replace(old_re, new_re, 1)

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
        if len(parts) >= 3 and parts[0] == "i" and parts[1] == "status":
            return "twitter:" + parts[2].lower()
    return host + ":" + path.lower()


def display_embed_url(url: str) -> str:
    u = clean_url(url)
    parsed = urlparse(u)
    host = parsed.netloc.lower().replace("www.", "")
    k = embed_key(u)
    if k.startswith("youtube:"):
        return "https://www.youtube.com/watch?v=" + k.split(":", 1)[1]
    if k.startswith("twitter:") and host in {"x.com", "twitter.com"}:
        parts = [x for x in parsed.path.strip("/").split("/") if x]
        if len(parts) >= 3 and parts[1] == "status":
            return "https://twitter.com/" + parts[0] + "/status/" + parts[2]
        if len(parts) >= 3 and parts[0] == "i" and parts[1] == "status":
            return "https://twitter.com/i/status/" + parts[2]
    return u


def embed_block(url: str) -> str:
    u = display_embed_url(url)
    host = urlparse(u).netloc.lower().replace("www.", "")
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        # v93.33: YouTube embeds work best in WordPress as a plain URL on its own line.
        # This avoids an ugly Shortcode block in the editor while preserving front-end oEmbed.
        return html.escape(u)
    # v93.33: social embeds are kept as shortcode blocks because plain X/Twitter URLs
    # often remain plain text until a manual editor conversion.
    return '<!-- wp:shortcode -->\\n[embed]' + html.escape(u) + '[/embed]\\n<!-- /wp:shortcode -->'


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


def normalized_story_blob(article: dict[str, Any]) -> str:
    parts = [article.get("title_it"), article.get("source_title"), article.get("excerpt_it"), article.get("source_url")]
    meta = article.get("meta") if isinstance(article.get("meta"), dict) else {}
    parts.extend([meta.get("title"), meta.get("source_title")])
    blob = " ".join(str(x or "") for x in parts).lower()
    return re.sub(r"\\s+", " ", blob)


def story_signature(article: dict[str, Any]) -> str:
    blob = normalized_story_blob(article)
    if "mjf" in blob and any(x in blob for x in ["injury", "infortun", "pulled", "rimosso", "rinunciare", "booking"]) and any(x in blob for x in ["indie", "independent", "evento indipendente", "beyond wrestling"]):
        return "story:aew:mjf:indie_injury"
    if "liv morgan" in blob and "dominik" in blob and any(x in blob for x in ["frustration", "frustrazione", "booking"]):
        return "story:wwe:liv_morgan_dominik_booking_frustration"
    if "jim ross" in blob and "lawsuit" in blob and any(x in blob for x in ["vince", "shareholder", "azionisti"]):
        return "story:wwe:vince_shareholder_lawsuit_jim_ross"
    return ""


def existing_story_duplicate(history: dict[str, Any], signature: str) -> dict[str, Any] | None:
    if not signature:
        return None
    for item in history.values():
        if isinstance(item, dict) and item.get("story_signature") == signature:
            return item
    return None


'''
start = s.find('def clean_url(url: str) -> str:')
end = s.find('def clean_body_for_wordpress(body_html: str) -> str:')
if start != -1 and end != -1:
    s = s[:start] + helpers + s[end:]
else:
    if insert_after not in s:
        raise SystemExit('[V93 BASE PUBLISHER] image placeholder anchor non trovato')
    s = s.replace(insert_after, insert_after + helpers, 1)

if 'convert_embed_urls(body_html)' not in s:
    s = s.replace('    body_html = re.sub(r"<p>\\s*</p>", "", body_html)\n    body_html = re.sub(r"\\n{3,}", "\\n\\n", body_html)\n', '    body_html = convert_embed_urls(body_html)\n    body_html = re.sub(r"<p>\\s*</p>", "", body_html)\n    body_html = re.sub(r"\\n{3,}", "\\n\\n", body_html)\n', 1)

old_dup = '''    if key in history:
        return {"source_url": url, "status": "already_published", "wp_post_id": history[key].get("wp_post_id"), "title_it": title}

    cleaned_body = clean_body_for_wordpress(str(article.get("body_html") or ""))
'''
new_dup = '''    if key in history:
        return {"source_url": url, "status": "already_published", "wp_post_id": history[key].get("wp_post_id"), "title_it": title}
    sig = story_signature(article)
    duplicate = existing_story_duplicate(history, sig)
    if duplicate:
        return {"source_url": url, "title_it": title, "status": "already_published", "reason": "semantic_story_duplicate", "story_signature": sig, "duplicate_of": duplicate.get("source_url"), "wp_post_id": duplicate.get("wp_post_id")}

    cleaned_body = clean_body_for_wordpress(str(article.get("body_html") or ""))
'''
if old_dup in s:
    s = s.replace(old_dup, new_dup, 1)
elif 'semantic_story_duplicate' not in s:
    raise SystemExit('[V93 BASE PUBLISHER] duplicate guard anchor non trovato')

old_hist = 'history[key] = {"source_url": url, "title_it": title, "wp_post_id": post_id, "wp_link": post_link, "published_at": utc_now(), "status": POST_STATUS, "source": source}'
new_hist = 'history[key] = {"source_url": url, "title_it": title, "wp_post_id": post_id, "wp_link": post_link, "published_at": utc_now(), "status": POST_STATUS, "source": source, "story_signature": story_signature(article)}'
s = s.replace(old_hist, new_hist, 1)
s = s.replace('"mode": "wordpress_publisher_plain_oembed_urls",', '"mode": "wordpress_publisher_mixed_embed_blocks",')
s = s.replace('"mode": "wordpress_publisher_gutenberg_embeds",', '"mode": "wordpress_publisher_mixed_embed_blocks",')
s = s.replace('"mode": "wordpress_publisher_embed_shortcode_blocks",', '"mode": "wordpress_publisher_mixed_embed_blocks",')
s = s.replace('"preserve_plain_embed_urls_for_wordpress_oembed": True,', '"plain_youtube_urls_for_wordpress_oembed": True, "social_embed_shortcode_blocks": True, "normalized_embed_dedupe": True, "semantic_story_dedupe": True,')
s = s.replace('"plain_embed_urls_to_gutenberg_blocks": True, "normalized_embed_dedupe": True,', '"plain_youtube_urls_for_wordpress_oembed": True, "social_embed_shortcode_blocks": True, "normalized_embed_dedupe": True, "semantic_story_dedupe": True,')
s = s.replace('"plain_embed_urls_to_shortcode_blocks": True, "normalized_embed_dedupe": True, "semantic_story_dedupe": True,', '"plain_youtube_urls_for_wordpress_oembed": True, "social_embed_shortcode_blocks": True, "normalized_embed_dedupe": True, "semantic_story_dedupe": True,')
p.write_text(s, encoding='utf-8')
print('[V93 BASE PUBLISHER] applicato')
