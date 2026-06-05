from pathlib import Path
import py_compile
import re

p = Path('agents/bob.py')
text = p.read_text(encoding='utf-8')

if 'v93_31_universal_embed_extractor' in text:
    print('[V93 EMBED EXTRACTOR] gia applicato')
    py_compile.compile(str(p), doraise=True)
    raise SystemExit(0)

text = re.sub(r'BOB_VERSION = "[^"]+"', 'BOB_VERSION = "v93_31_universal_embed_extractor"', text, count=1)

old_canonical = '''def canonical_embed_url(url: str) -> str:
    url = html.unescape((url or "").replace("\\/", "/").strip())
    url = url.replace("https://twitter.com/", "https://x.com/").replace("http://twitter.com/", "https://x.com/")
    if "x.com/" in url or "twitter.com/" in url:
        url = re.sub(r"\?.*$", "", url)
    return url.rstrip("/")


'''
new_canonical = '''def tweet_id_from_value(value: str) -> str:
    raw = html.unescape((value or "").replace("\\/", "/"))
    patterns = [
        r"data-tweet-id=[\\\"']?(\\d{8,25})",
        r"(?:tweet_id|tweetId|id)=[\\\"']?(\\d{8,25})",
        r"/(?:status|statuses)/(\\d{8,25})",
        r"twitter\\.com/i/status/(\\d{8,25})",
    ]
    for pattern in patterns:
        m = re.search(pattern, raw, re.I)
        if m:
            return m.group(1)
    return ""


def youtube_id_from_value(value: str) -> str:
    raw = html.unescape((value or "").replace("\\/", "/"))
    parsed = urlparse(raw if re.match(r"https?://", raw, re.I) else "https://dummy.local/" + raw.lstrip("/"))
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.strip("/")
    if host in {"youtube.com", "youtube-nocookie.com"}:
        if path == "watch":
            m = re.search(r"(?:^|&)v=([^&]+)", parsed.query)
            return m.group(1) if m else ""
        if path.startswith(("embed/", "shorts/")):
            return path.split("/", 1)[1].split("/", 1)[0]
    if host == "youtu.be" and path:
        return path.split("/", 1)[0]
    m = re.search(r"(?:youtube(?:-nocookie)?\\.com/(?:embed|shorts)/|youtu\\.be/)([A-Za-z0-9_-]{6,})", raw, re.I)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|[?&])v=([A-Za-z0-9_-]{6,})", raw, re.I)
    return m.group(1) if m else ""


def canonical_embed_url(url: str) -> str:
    raw = html.unescape((url or "").replace("\\/", "/").strip())
    tweet_id = tweet_id_from_value(raw)
    if tweet_id:
        return f"https://twitter.com/i/status/{tweet_id}"
    youtube_id = youtube_id_from_value(raw)
    if youtube_id:
        return f"https://www.youtube.com/watch?v={youtube_id}"
    raw = re.sub(r"\s+", "", raw).rstrip(".,;:)]}”’</p>")
    if "x.com/" in raw or "twitter.com/" in raw:
        raw = re.sub(r"\?.*$", "", raw)
        raw = raw.replace("https://x.com/", "https://twitter.com/").replace("http://x.com/", "https://twitter.com/")
        raw = raw.replace("http://twitter.com/", "https://twitter.com/")
    return raw.rstrip("/")


'''
if old_canonical not in text:
    print('[V93 EMBED EXTRACTOR] canonical_embed_url anchor non trovato, salto patch canonical')
else:
    text = text.replace(old_canonical, new_canonical, 1)

old_valid = '''    if host in {"x.com", "twitter.com"}:
        return "/status/" in path or "/statuses/" in path
'''
new_valid = '''    if host in {"x.com", "twitter.com"}:
        return "/status/" in path or "/statuses/" in path or path.startswith("i/status/")
'''
if old_valid in text:
    text = text.replace(old_valid, new_valid, 1)
else:
    print('[V93 EMBED EXTRACTOR] twitter validation anchor non trovato, salto validation')

old_extract = '''def extract_embed_urls_from_text(raw: str, base_url: str) -> list[str]:
    text = html.unescape((raw or "").replace("\\/", "/"))
    out: list[str] = []
    seen: set[str] = set()
    for match in EMBED_URL_RE.findall(text):
        url = canonical_embed_url(absolute_url(base_url, match))
        if is_valid_editorial_embed_url(url) and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def extract_embed_url(node: Tag, base_url: str) -> str:
    candidates: list[str] = []
    for attr in ["src", "href", "cite", "data-url", "data-href", "data-src", "data-lazy-src", "data-embed-url", "data-permalink"]:
        value = node.get(attr)
        if value:
            candidates.append(str(value))
    for link in node.find_all("a", href=True):
        candidates.append(str(link.get("href")))
    candidates.extend(extract_embed_urls_from_text(str(node), base_url))
    for raw in candidates:
        url = canonical_embed_url(absolute_url(base_url, raw))
        if is_valid_editorial_embed_url(url):
            return url
    return ""


'''
new_extract = '''def extract_embed_urls_from_text(raw: str, base_url: str) -> list[str]:
    text = html.unescape((raw or "").replace("\\/", "/"))
    out: list[str] = []
    seen: set[str] = set()
    for match in EMBED_URL_RE.findall(text):
        url = canonical_embed_url(absolute_url(base_url, match))
        if is_valid_editorial_embed_url(url) and url not in seen:
            seen.add(url)
            out.append(url)
    tweet_id = tweet_id_from_value(text)
    if tweet_id:
        url = canonical_embed_url(f"https://twitter.com/i/status/{tweet_id}")
        if is_valid_editorial_embed_url(url) and url not in seen:
            seen.add(url)
            out.append(url)
    youtube_id = youtube_id_from_value(text)
    if youtube_id:
        url = canonical_embed_url(f"https://www.youtube.com/watch?v={youtube_id}")
        if is_valid_editorial_embed_url(url) and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def extract_embed_url(node: Tag, base_url: str) -> str:
    # Universal extractor: explicit URLs, blockquote cite, iframe attrs, lazy/data attrs,
    # and rendered WrestlingInc/X widgets exposing only data-tweet-id.
    for current in [node] + list(node.find_all(True)):
        if not isinstance(current, Tag):
            continue
        for attr in ["data-tweet-id", "tweet-id", "data-twitter-id"]:
            value = current.get(attr)
            if value and re.fullmatch(r"\d{8,25}", str(value).strip()):
                return f"https://twitter.com/i/status/{str(value).strip()}"
        title = str(current.get("title", ""))
        if title.lower() in {"x post", "twitter post", "tweet"}:
            for attr in ["src", "data-src", "data-lazy-src"]:
                value = current.get(attr)
                tweet_id = tweet_id_from_value(str(value or ""))
                if tweet_id:
                    return f"https://twitter.com/i/status/{tweet_id}"

    candidates: list[str] = []
    for current in [node] + list(node.find_all(True)):
        if not isinstance(current, Tag):
            continue
        for attr in ["src", "href", "cite", "data-url", "data-href", "data-src", "data-lazy-src", "data-embed-url", "data-permalink", "data-oembed-url"]:
            value = current.get(attr)
            if value:
                candidates.append(str(value))
    for link in node.find_all("a", href=True):
        candidates.append(str(link.get("href")))
    candidates.extend(extract_embed_urls_from_text(str(node), base_url))
    for raw in candidates:
        url = canonical_embed_url(absolute_url(base_url, raw))
        if is_valid_editorial_embed_url(url):
            return url
    return ""


'''
if old_extract in text:
    text = text.replace(old_extract, new_extract, 1)
else:
    print('[V93 EMBED EXTRACTOR] extract functions anchor non trovato, salto extract')

p.write_text(text, encoding='utf-8')
py_compile.compile(str(p), doraise=True)
print('[V93 EMBED EXTRACTOR] applicato')
