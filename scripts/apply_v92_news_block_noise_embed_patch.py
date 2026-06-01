from pathlib import Path

# -----------------------------------------------------------------------------
# v92 block noise/embed patch.
# Shared block scraper cleanup for report/news pages.
# Important v2 fix: never decompose the whole article/content container just
# because it contains author/social/footer text somewhere inside. Remove only
# small/local noise nodes and skip noisy leaf text blocks during extraction.
# -----------------------------------------------------------------------------

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_BLOCK_NOISE_EMBED_PATCH = True" in text:
    print("[V92 BLOCK NOISE] patch gia applicata")
    raise SystemExit(0)

text = text.replace(
    "media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n",
    "media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_BLOCK_NOISE_EMBED_PATCH = True\n",
    1,
)

anchor = "\n\ndef extract_blocks(content, base_url: str) -> List[Dict[str, str]]:\n"
pos = text.find(anchor)
if pos == -1:
    raise SystemExit("[V92 BLOCK NOISE] extract_blocks anchor non trovato")

helpers = r'''

def node_blob(node) -> str:
    if not node:
        return ""
    attrs = []
    try:
        attrs.extend(node.get("class", []) or [])
        attrs.append(str(node.get("id", "")))
        attrs.append(str(node.get("aria-label", "")))
        attrs.append(str(node.get("role", "")))
        for k, v in getattr(node, "attrs", {}).items():
            if isinstance(v, str) and k.startswith("data"):
                attrs.append(v)
    except Exception:
        pass
    try:
        txt = node.get_text(" ", strip=True)
    except Exception:
        txt = ""
    return normalize_text(" ".join(attrs) + " " + txt)


def text_len_of_node(node) -> int:
    try:
        return len(clean_text(node.get_text(" ", strip=True)))
    except Exception:
        return 0


def is_core_content_node(node) -> bool:
    blob = node_blob(node)
    core_terms = [
        "entry content", "rsn single content", "post content", "article content",
        "article body", "single post content", "td post content",
    ]
    return any(term in blob for term in core_terms) or text_len_of_node(node) > 900


def is_ringside_noise_node(node) -> bool:
    blob = node_blob(node)
    if not blob:
        return False
    if is_core_content_node(node):
        return False
    noise_terms = [
        "posts by ringsidenews", "tweets by ringsidenews", "follow us", "connect with us",
        "share this", "social share", "share buttons", "post share", "rsn social", "ringside social",
        "please credit ringside news", "please cite ringside news", "if you use the transcription",
        "author bio", "author box", "derek holloway", "ringsidenewscom", "youtube com channel",
        "instagram com ringsidenewscom", "twitter com intent tweet", "x com ringsidenews",
        "related articles", "recommended", "newsletter", "comments", "subscribe",
    ]
    return any(term in blob for term in noise_terms)


def is_local_noise_node(node) -> bool:
    if not node or is_core_content_node(node):
        return False
    blob = node_blob(node)
    txt_len = text_len_of_node(node)
    # Whole article wrappers can contain noisy footer text; only decompose compact
    # blocks or explicit service/sidebar/author/share containers.
    classes = " ".join(node.get("class", []) if hasattr(node, "get") else []).lower()
    node_id = str(node.get("id", "") if hasattr(node, "get") else "").lower()
    explicit = any(x in f"{classes} {node_id}" for x in [
        "rsn-social", "ringside-social", "social", "share", "follow", "author", "bio",
        "byline", "profile", "newsletter", "related", "recommended", "comments", "widget", "sidebar",
    ])
    if explicit:
        return True
    compact_noise = any(term in blob for term in [
        "posts by ringsidenews", "tweets by ringsidenews", "follow us", "connect with us",
        "please credit ringside news", "please cite ringside news", "if you use the transcription",
        "derek holloway", "twitter com intent tweet", "youtube com channel", "instagram com ringsidenewscom",
    ])
    return compact_noise and txt_len < 500


def remove_block_noise(content) -> None:
    remove_noise(content)
    selectors = [
        ".rsn-social", ".ringside-social", ".social-links", ".social-share",
        ".post-share", ".share-buttons", ".follow-us",
        ".author-box", ".author-bio", ".byline", ".post-author", ".user-profile",
        ".newsletter", ".related", ".recommended", ".comments-area", ".widget", ".sidebar",
    ]
    for sel in selectors:
        for node in list(content.select(sel)):
            if not is_core_content_node(node):
                node.decompose()
    # Work from leaves upward and never decompose article-sized containers.
    candidates = list(content.find_all(["p", "li", "figure", "blockquote", "ul", "div", "section", "aside", "nav", "footer"]))
    for node in reversed(candidates):
        if node is content:
            continue
        if is_local_noise_node(node):
            node.decompose()


def normalize_url_for_embed(raw_url: str, base_url: str = "") -> str:
    url = html_lib.unescape((raw_url or "").strip())
    if not url:
        return ""
    url = urljoin(base_url, url)
    url = re.sub(r"[\s\"'<>]+$", "", url).rstrip(".,;:)]}")
    if url.startswith("//"):
        url = "https:" + url
    return url


def is_short_social_url(url: str) -> bool:
    low = (url or "").lower()
    return "pic.twitter.com/" in low or "t.co/" in low


def resolve_short_social_url(url: str) -> str:
    if not is_short_social_url(url):
        return url
    try:
        res = session.get(url, timeout=8, allow_redirects=True)
        final_url = normalize_url_for_embed(res.url)
        if final_url:
            print(f"[BLOCK EMBED v92] Shortlink risolto: {url} -> {final_url}", flush=True)
            return final_url
    except Exception as exc:
        print(f"[BLOCK EMBED v92] Warning shortlink non risolto: {url} | {exc}", flush=True)
    return url


def canonical_embed_url(raw_url: str, base_url: str = "") -> str:
    url = normalize_url_for_embed(raw_url, base_url)
    if not url:
        return ""
    url = resolve_short_social_url(url)
    low = url.lower()
    reject_terms = [
        "twitter.com/intent/", "x.com/intent/", "twitter.com/share", "x.com/share",
        "facebook.com/sharer", "mailto:", "youtube.com/channel/", "youtube.com/user/",
        "youtube.com/c/", "instagram.com/ringsidenewscom", "x.com/ringsidenews", "twitter.com/ringsidenews",
    ]
    if any(term in low for term in reject_terms):
        return ""
    if "twitter.com/" in low or "x.com/" in low:
        if "/status/" not in low:
            return ""
        return normalize_social_url(url)
    if "pic.twitter.com/" in low or "t.co/" in low:
        return ""
    if "instagram.com/" in low:
        if not any(x in low for x in ["/p/", "/reel/", "/tv/"]):
            return ""
        return url
    if "youtube.com/" in low:
        if not any(x in low for x in ["/watch", "/embed/", "/shorts/"]):
            return ""
        return url
    if "youtu.be/" in low:
        return url
    if "tiktok.com/" in low:
        if "/video/" not in low and "vm.tiktok.com/" not in low:
            return ""
        return url
    if "bsky.app/" in low or "threads.net/" in low:
        if "/post/" not in low:
            return ""
        return url
    return ""


def extract_embed_from_node(node, base_url: str) -> str:
    if not node or is_local_noise_node(node):
        return ""
    iframe = node if getattr(node, "name", "") == "iframe" else node.find("iframe")
    if iframe and iframe.get("src"):
        url = canonical_embed_url(iframe.get("src"), base_url)
        if url:
            return url
    cite = node.get("cite") if hasattr(node, "get") else None
    if cite:
        url = canonical_embed_url(cite, base_url)
        if url:
            return url
    for k, v in getattr(node, "attrs", {}).items():
        if isinstance(v, str) and any(token in k.lower() for token in ["url", "href", "src", "embed", "permalink"]):
            url = canonical_embed_url(v, base_url)
            if url:
                return url
    links: List[str] = []
    for a in node.find_all("a", href=True) if hasattr(node, "find_all") else []:
        url = canonical_embed_url(a.get("href"), base_url)
        if url:
            links.append(url)
    return links[0] if links else ""


def is_bad_inline_image(src: str, img=None) -> bool:
    low = (src or "").lower()
    bad_terms = ["avatar", "avatar_user", "author", "profile", "user_", "96x96", "80x80", "150x150", "derek%20holloway", "derek-holloway"]
    if any(term in low for term in bad_terms):
        return True
    if img is not None:
        try:
            w = int(str(img.get("width") or "0").replace("px", "") or 0)
            h = int(str(img.get("height") or "0").replace("px", "") or 0)
            if w and h and max(w, h) <= 180:
                return True
        except Exception:
            pass
    return False


def should_skip_block_text(text: str) -> bool:
    norm = normalize_text(text)
    if not norm:
        return True
    skip_phrases = [
        "posts by ringsidenews", "tweets by ringsidenews", "follow us", "connect with us",
        "please credit ringside news", "please cite ringside news", "if you use the transcription",
        "derek holloway is a writer", "ringside news specializing", "youtube com channel",
        "instagram com ringsidenewscom", "twitter com intent tweet", "source ringside news",
    ]
    return any(p in norm for p in skip_phrases)


def is_standalone_quote_text(text: str) -> bool:
    t = clean_text(text)
    if len(t) < 35:
        return False
    return (t.startswith('"') and t.endswith('"')) or (t.startswith("“") and t.endswith("”"))
'''
text = text[:pos] + helpers + text[pos:]

start = text.find("def extract_blocks(content, base_url: str) -> List[Dict[str, str]]:")
end = text.find("\n\ndef scrape_article", start)
if start == -1 or end == -1:
    raise SystemExit("[V92 BLOCK NOISE] extract_blocks bounds non trovati")

new_func = r'''def extract_blocks(content, base_url: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    if not content:
        return blocks
    remove_block_noise(content)
    seen_images: set[str] = set()
    seen_embeds: set[str] = set()
    allowed = ["h2", "h3", "p", "blockquote", "li", "img", "picture", "amp-img", "iframe", "figure", "a"]
    for el in content.find_all(allowed):
        if el.find_parent(["script", "style", "nav", "footer", "header", "aside", "form"]):
            continue
        # Skip if inside a compact noise block, but do not skip simply because a
        # high-level article wrapper contains noisy footer text elsewhere.
        if any(is_local_noise_node(parent) for parent in el.parents if parent is not content):
            continue

        embed_url = extract_embed_from_node(el, base_url)
        if embed_url:
            if embed_url not in seen_embeds:
                seen_embeds.add(embed_url)
                blocks.append({"type": "embed", "url": embed_url})
            continue

        if el.name in {"img", "amp-img"}:
            src = best_img_src(el, base_url)
            if src and not is_bad_inline_image(src, el) and src not in seen_images:
                seen_images.add(src)
                alt = clean_text(el.get("alt") or "")
                blocks.append({"type": "image", "src": src, "alt": alt})
            continue

        if el.name == "picture":
            img = el.find(["img", "amp-img"])
            if img:
                src = best_img_src(img, base_url)
                if src and not is_bad_inline_image(src, img) and src not in seen_images:
                    seen_images.add(src)
                    alt = clean_text(img.get("alt") or "")
                    blocks.append({"type": "image", "src": src, "alt": alt})
            continue

        if el.name in {"figure", "iframe", "a"}:
            continue

        text = clean_text(el.get_text(" ", strip=True))
        if len(text) < 20 or should_skip_block_text(text):
            continue
        if el.name in {"h2", "h3"}:
            blocks.append({"type": "heading", "level": el.name, "text": text})
        elif el.name == "blockquote" or is_standalone_quote_text(text):
            blocks.append({"type": "quote", "text": text.strip('“”\"')})
        else:
            blocks.append({"type": "paragraph", "text": text})
    return blocks
'''
text = text[:start] + new_func + text[end:]

p.write_text(text, encoding="utf-8")
print("[V92 BLOCK NOISE] noise/embed/quote cleanup applicato")
