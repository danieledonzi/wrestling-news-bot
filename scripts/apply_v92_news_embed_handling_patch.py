from pathlib import Path

# -----------------------------------------------------------------------------
# v92 news embed handling patch.
# Problem: news extraction treated all blockquotes as editorial quotes. On pages
# with embedded tweets/Instagram/YouTube, this can turn an embed into a long quote
# in the translated article. This patch preserves social/video embeds as explicit
# placeholders during translation and renders them as WordPress embed blocks after
# Gemini returns HTML.
#
# Important v2 correction:
# - do not append lost placeholders at the bottom, because that can create
#   duplicate/out-of-position embeds;
# - expand shortlinks/media links such as pic.twitter.com and t.co to canonical
#   x.com/twitter status URLs before rendering the WordPress embed.
# -----------------------------------------------------------------------------

p = Path("modules/news_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_NEWS_EMBED_HANDLING_PATCH = True" in text:
    print("[V92 NEWS EMBED] patch gia applicata")
    raise SystemExit(0)

text = text.replace(
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n",
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_NEWS_EMBED_HANDLING_PATCH = True\n",
    1,
)

helper_anchor = "\n\ndef should_skip_text(text: str) -> bool:\n"
helpers = r'''

def normalize_embed_url(raw_url: str) -> Optional[str]:
    url = html_lib.unescape((raw_url or "").strip())
    if not url:
        return None
    url = re.sub(r"[\s\"'<>]+$", "", url)
    url = url.split("?", 1)[0]
    url = url.rstrip("/.,)]}")
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith(("http://", "https://")):
        return None
    return url


def is_short_social_url(url: str) -> bool:
    low = (url or "").lower()
    return "pic.twitter.com/" in low or "t.co/" in low


def is_embed_url(url: str) -> bool:
    low = (url or "").lower()
    domains = [
        "twitter.com/", "x.com/", "pic.twitter.com/", "t.co/",
        "instagram.com/", "youtube.com/", "youtu.be/", "tiktok.com/",
        "facebook.com/", "threads.net/", "bsky.app/",
    ]
    if not any(d in low for d in domains):
        return False
    if "twitter.com/share" in low or "x.com/share" in low:
        return False
    return True


def canonicalize_embed_url(raw_url: str) -> Optional[str]:
    url = normalize_embed_url(raw_url)
    if not url or not is_embed_url(url):
        return None
    low = url.lower()
    if is_short_social_url(url):
        try:
            # pic.twitter.com/t.co often resolve to the real tweet/status. Use GET,
            # not only HEAD, because some social shortlinks do not resolve on HEAD.
            res = session.get(url, timeout=8, allow_redirects=True)
            final_url = normalize_embed_url(res.url)
            if final_url and is_embed_url(final_url):
                print(f"[NEWS v92] Embed shortlink risolto: {url} -> {final_url}", flush=True)
                url = final_url
                low = url.lower()
        except Exception as exc:
            print(f"[NEWS v92] WARNING: impossibile risolvere shortlink embed {url}: {exc}", flush=True)
    # WordPress oEmbed needs the canonical post/video URL, not media shortlinks.
    if "pic.twitter.com/" in low or "t.co/" in low:
        print(f"[NEWS v92] WARNING: embed shortlink non canonico scartato: {url}", flush=True)
        return None
    if ("twitter.com/" in low or "x.com/" in low) and "/status/" not in low:
        print(f"[NEWS v92] WARNING: URL X/Twitter senza status scartato: {url}", flush=True)
        return None
    return url


def extract_embed_url(node, base_url: str) -> Optional[str]:
    iframe = node if getattr(node, "name", "") == "iframe" else node.find("iframe")
    if iframe and iframe.get("src"):
        candidate = canonicalize_embed_url(urljoin(base_url, iframe.get("src")))
        if candidate:
            return candidate

    cite = node.get("cite") if hasattr(node, "get") else None
    if cite:
        candidate = canonicalize_embed_url(urljoin(base_url, cite))
        if candidate:
            return candidate

    if hasattr(node, "attrs"):
        for key, value in list(node.attrs.items()):
            if not isinstance(value, str):
                continue
            if "url" in key.lower() or "href" in key.lower() or "src" in key.lower() or "embed" in key.lower():
                candidate = canonicalize_embed_url(urljoin(base_url, value))
                if candidate:
                    return candidate

    links: List[str] = []
    for a in node.find_all("a", href=True) if hasattr(node, "find_all") else []:
        candidate = canonicalize_embed_url(urljoin(base_url, a.get("href")))
        if candidate:
            links.append(candidate)
    for candidate in links:
        low = candidate.lower()
        if "/status/" in low or "/p/" in low or "/reel/" in low or "youtu" in low:
            return candidate
    return links[0] if links else None


def is_social_embed_node(node, base_url: str) -> bool:
    if not getattr(node, "name", None):
        return False
    classes = " ".join(node.get("class", []) if hasattr(node, "get") else []).lower()
    if any(marker in classes for marker in ["twitter-tweet", "instagram-media", "tiktok-embed", "wp-block-embed", "embed"]):
        return bool(extract_embed_url(node, base_url))
    if node.name in {"iframe", "figure", "blockquote", "div"} and extract_embed_url(node, base_url):
        return True
    return False


def make_embed_placeholder(index: int) -> str:
    return f"[[OWTV_EMBED_{index}]]"


def provider_slug_for_embed(url: str) -> str:
    low = (url or "").lower()
    if "twitter.com/" in low or "x.com/" in low:
        return "twitter"
    if "instagram.com/" in low:
        return "instagram"
    if "youtube.com/" in low or "youtu.be/" in low:
        return "youtube"
    if "tiktok.com/" in low:
        return "tiktok"
    if "facebook.com/" in low:
        return "facebook"
    return "embed"


def render_wp_embed(url: str) -> str:
    canonical = canonicalize_embed_url(url)
    if not canonical:
        return ""
    safe_url = html_lib.escape(canonical)
    provider = provider_slug_for_embed(canonical)
    return (
        f'<!-- wp:embed {{"url":"{safe_url}","type":"rich","providerNameSlug":"{provider}"}} -->\n'
        f'<figure class="wp-block-embed is-type-rich is-provider-{provider} wp-block-embed-{provider}">'
        f'<div class="wp-block-embed__wrapper">\n{safe_url}\n</div></figure>\n'
        f'<!-- /wp:embed -->'
    )


def inject_news_embeds(body_html: str, embeds: List[Dict[str, str]]) -> str:
    out = body_html or ""
    for embed in embeds:
        placeholder = embed.get("placeholder", "")
        url = embed.get("url", "")
        embed_html = render_wp_embed(url)
        if not embed_html:
            print(f"[NEWS v92] WARNING: embed non renderizzato, URL non valido per oEmbed: {url}", flush=True)
            continue
        if placeholder and placeholder in out:
            out = re.sub(rf"<p>\s*{re.escape(placeholder)}\s*</p>", embed_html, out)
            out = out.replace(placeholder, embed_html)
        else:
            # Do not append automatically: if Gemini lost the placeholder, appending
            # the embed at the end can create duplicates or wrong placement.
            print(f"[NEWS v92] WARNING: placeholder embed perso da Gemini, non appendo per evitare doppioni: {placeholder} -> {url}", flush=True)
    return out
'''
if helper_anchor not in text:
    raise SystemExit("[V92 NEWS EMBED] anchor should_skip_text non trovato")
text = text.replace(helper_anchor, helpers + helper_anchor, 1)

start = text.find("def extract_article_text_and_media(url: str) -> Tuple[str, Optional[str]]:")
end = text.find("\n\ndef gemini_client", start)
if start == -1 or end == -1:
    raise SystemExit("[V92 NEWS EMBED] extract_article_text_and_media block non trovato")

new_extract = r'''def extract_article_text_and_media(url: str) -> Tuple[str, Optional[str], List[Dict[str, str]]]:
    res = session.get(url, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    for node in soup.select("script, style, noscript, nav, footer, aside, form"):
        node.decompose()
    container = parse_content_container(soup, url)
    featured = extract_meta_image(soup, url)
    parts: List[str] = []
    embeds: List[Dict[str, str]] = []

    for el in container.find_all(["h2", "h3", "p", "li", "blockquote", "figure", "iframe", "div"]):
        if any(parent in container.find_all(["blockquote", "figure", "div"]) and parent is not el and is_social_embed_node(parent, url) for parent in el.parents):
            continue

        if is_social_embed_node(el, url):
            embed_url = extract_embed_url(el, url)
            if embed_url:
                if not any(e.get("url") == embed_url for e in embeds):
                    placeholder = make_embed_placeholder(len(embeds) + 1)
                    embeds.append({"placeholder": placeholder, "url": embed_url})
                    parts.append(placeholder)
                    print(f"[NEWS v92] Embed rilevato: {placeholder} -> {embed_url}", flush=True)
            continue

        if el.name in {"figure", "iframe", "div"}:
            continue

        txt = clean_text(el.get_text(" ", strip=True))
        if should_skip_text(txt):
            continue
        if el.name in {"h2", "h3"}:
            parts.append(f"## {txt}")
        elif el.name == "blockquote":
            parts.append(f"> {txt}")
        else:
            parts.append(txt)

    article_text = "\n\n".join(parts)
    if len(article_text) < 400:
        title = soup.find("h1")
        fallback = clean_text(container.get_text(" ", strip=True))
        article_text = (clean_text(title.get_text(" ", strip=True)) + "\n\n" if title else "") + fallback[:8000]
    if embeds:
        print(f"[NEWS v92] Embed totali estratti: {len(embeds)}", flush=True)
    return article_text[:18000], featured, embeds
'''
text = text[:start] + new_extract + text[end:]

prompt_anchor = '- Non citare la fonte nel corpo: la fonte viene aggiunta automaticamente dal sistema.\n'
embed_rules = (
    '- Se nel testo trovi placeholder come [[OWTV_EMBED_1]], [[OWTV_EMBED_2]], mantienili identici, da soli, senza tradurli e senza trasformarli in citazioni.\n'
    '- Non trasformare tweet, post social, iframe o embed in blockquote testuali: gli embed vengono reinseriti automaticamente dal sistema.\n'
)
if embed_rules not in text:
    text = text.replace(prompt_anchor, prompt_anchor + embed_rules, 1)

old_run = '''def run_news_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:
    print(f"[NEWS v92] Avvio workshop news: {job.get('news_key')} url={job.get('source_url')}", flush=True)
    source_text, image_url = extract_article_text_and_media(str(job["source_url"]))
    print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)}", flush=True)
    title, body_html, model = translate_news(str(job.get("source_title") or ""), source_text, str(job.get("source") or ""))
    print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    (review_dir / f"news_{slug}.prepublish.html").write_text(body_html, encoding="utf-8")
    post_id, post_json = publish_news(job, title, body_html, image_url)
    (published_dir / f"news_{slug}.html").write_text(body_html, encoding="utf-8")
    return post_id, post_json
'''
new_run = '''def run_news_workshop(job: Dict[str, Any], published_dir: Path, review_dir: Path) -> Tuple[int, Dict[str, Any]]:
    print(f"[NEWS v92] Avvio workshop news: {job.get('news_key')} url={job.get('source_url')}", flush=True)
    source_text, image_url, embeds = extract_article_text_and_media(str(job["source_url"]))
    print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)} embeds={len(embeds)}", flush=True)
    title, body_html, model = translate_news(str(job.get("source_title") or ""), source_text, str(job.get("source") or ""))
    body_html = inject_news_embeds(body_html, embeds)
    print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)
    published_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    (review_dir / f"news_{slug}.prepublish.html").write_text(body_html, encoding="utf-8")
    post_id, post_json = publish_news(job, title, body_html, image_url)
    (published_dir / f"news_{slug}.html").write_text(body_html, encoding="utf-8")
    return post_id, post_json
'''
if old_run in text:
    text = text.replace(old_run, new_run, 1)
else:
    text = text.replace(
        'source_text, image_url = extract_article_text_and_media(str(job["source_url"]))',
        'source_text, image_url, embeds = extract_article_text_and_media(str(job["source_url"]))',
        1,
    )
    text = text.replace(
        'print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)}", flush=True)',
        'print(f"[NEWS v92] Testo estratto: chars={len(source_text)} featured={bool(image_url)} embeds={len(embeds)}", flush=True)',
        1,
    )
    text = text.replace(
        'print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)',
        'body_html = inject_news_embeds(body_html, embeds)\n    print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)',
        1,
    )

p.write_text(text, encoding="utf-8")
print("[V92 NEWS EMBED] gestione embed news applicata")
