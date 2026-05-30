from pathlib import Path

# -----------------------------------------------------------------------------
# v92 robust news scraper patch.
# Problem observed: Ringside news workshop sometimes extracted chars=0 while still
# seeing featured=True. Gemini then translated mostly from title/context, causing
# factual drift. The uploaded Ringside HTML confirmed that the real body exists
# in .entry-content.rsn-single-content, so this patch makes that selector a
# first-class/preferred container and saves the raw HTML whenever extraction is
# weak, so the GitHub Actions response can be compared with browser-saved HTML.
# -----------------------------------------------------------------------------

p = Path("modules/news_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_NEWS_ROBUST_SCRAPER_PATCH = True" in text:
    print("[V92 NEWS SCRAPER] robust scraper gia applicato")
    raise SystemExit(0)

text = text.replace(
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n",
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_NEWS_ROBUST_SCRAPER_PATCH = True\nV92_NEWS_SCRAPE_DEBUG_DIR = ROOT / \"debug\" / \"news_scrape\"\n",
    1,
)

anchor = "\n\ndef extract_article_text_and_media(url: str)"
pos = text.find(anchor)
if pos == -1:
    raise SystemExit("[V92 NEWS SCRAPER] extract_article_text_and_media non trovato")

helpers = r'''

def node_text_len(node) -> int:
    if node is None:
        return 0
    try:
        txt = clean_text(node.get_text(" ", strip=True))
    except Exception:
        return 0
    norm = normalize_text(txt)
    if not norm:
        return 0
    noise = ["advertisement", "follow us", "share this", "related articles", "subscribe", "comments"]
    if any(x in norm for x in noise) and len(norm) < 800:
        return 0
    return len(txt)


def find_best_news_container(soup: BeautifulSoup, url: str):
    # Ringside single articles put the real body here. Prefer it over generic
    # article/main containers, which can include wrappers, social bars or empty
    # layout nodes.
    preferred_selectors = [
        ".entry-content.rsn-single-content",
        ".rsn-single-content",
        "article .entry-content",
        ".entry-content",
    ]
    diagnostics: List[Tuple[int, str]] = []
    for sel in preferred_selectors:
        nodes = soup.select(sel)
        best = None
        best_score = 0
        for node in nodes:
            score = node_text_len(node)
            diagnostics.append((score, sel))
            if score > best_score:
                best_score = score
                best = node
        if best is not None and best_score >= 250:
            print(f"[NEWS v92] Scraper container preferito: selector={sel} chars={best_score} url={url}", flush=True)
            return best

    selectors = [
        "article",
        "main article",
        ".article-content",
        ".post-content",
        ".article-body",
        ".single-post-content",
        ".td-post-content",
        ".content-area article",
        "main",
    ]
    candidates = []
    for sel in selectors:
        for node in soup.select(sel):
            score = node_text_len(node)
            diagnostics.append((score, sel))
            if score:
                candidates.append((score, sel, node))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        score, sel, node = candidates[0]
        diag = "; ".join(f"{s}:{c}" for c, s in sorted(diagnostics, reverse=True)[:8])
        print(f"[NEWS v92] Scraper container scelto: selector={sel} chars={score} url={url} | candidates={diag}", flush=True)
        return node
    diag = "; ".join(f"{s}:{c}" for c, s in sorted(diagnostics, reverse=True)[:8])
    print(f"[NEWS v92] WARNING: nessun container testuale forte trovato, uso body url={url} | candidates={diag}", flush=True)
    return soup.body or soup


def extract_jsonld_article_text(soup: BeautifulSoup) -> str:
    bodies: List[str] = []

    def visit(obj: Any) -> None:
        if isinstance(obj, dict):
            typ = obj.get("@type") or obj.get("type") or ""
            typ_blob = " ".join(typ) if isinstance(typ, list) else str(typ)
            if any(x in typ_blob.lower() for x in ["article", "newsarticle", "blogposting"]):
                for key in ["articleBody", "description"]:
                    value = obj.get(key)
                    if isinstance(value, str) and len(clean_text(value)) > 250:
                        bodies.append(clean_text(value))
            for value in obj.values():
                visit(value)
        elif isinstance(obj, list):
            for item in obj:
                visit(item)

    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
            visit(data)
        except Exception:
            continue
    if not bodies:
        return ""
    bodies = sorted(set(bodies), key=len, reverse=True)
    print(f"[NEWS v92] JSON-LD articleBody fallback disponibile: chars={len(bodies[0])}", flush=True)
    return bodies[0]


def extract_meta_description_text(soup: BeautifulSoup) -> str:
    chunks: List[str] = []
    for selector in ["meta[property='og:description']", "meta[name='description']", "meta[name='twitter:description']"]:
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            val = clean_text(tag.get("content"))
            if len(val) > 120:
                chunks.append(val)
    return "\n\n".join(dict.fromkeys(chunks))


def save_weak_scrape_debug_html(url: str, html: str, article_text: str, soup: BeautifulSoup) -> None:
    try:
        V92_NEWS_SCRAPE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        slug = slugify(urlparse(url).path.strip("/") or "news")[:100]
        html_path = V92_NEWS_SCRAPE_DEBUG_DIR / f"{slug}.html"
        meta_path = V92_NEWS_SCRAPE_DEBUG_DIR / f"{slug}.debug.txt"
        html_path.write_text(html or "", encoding="utf-8", errors="ignore")
        selector_lines = []
        for sel in [
            ".entry-content.rsn-single-content", ".rsn-single-content", "article .entry-content",
            ".entry-content", "article", "main article", "main", "body",
        ]:
            nodes = soup.select(sel)
            scores = [node_text_len(n) for n in nodes[:5]]
            selector_lines.append(f"{sel}: count={len(nodes)} scores={scores}")
        h1 = soup.find("h1")
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_path.write_text(
            "\n".join([
                f"url={url}",
                f"html_chars={len(html or '')}",
                f"article_chars={len(article_text or '')}",
                f"title={title}",
                f"h1={clean_text(h1.get_text(' ', strip=True)) if h1 else ''}",
                *selector_lines,
            ]),
            encoding="utf-8",
        )
        print(f"[NEWS v92] Debug scrape salvato: {html_path} | {meta_path}", flush=True)
    except Exception as exc:
        print(f"[NEWS v92] WARNING: impossibile salvare debug scrape: {exc}", flush=True)


def safe_remove_social_noise(container) -> None:
    fn = globals().get("remove_social_noise")
    if callable(fn):
        try:
            fn(container)
        except Exception as exc:
            print(f"[NEWS v92] WARNING: remove_social_noise fallita: {exc}", flush=True)


def is_embed_node_safe(el, url: str) -> bool:
    fn = globals().get("is_social_embed_node")
    if callable(fn):
        try:
            return bool(fn(el, url))
        except Exception:
            return False
    return False


def extract_embed_url_safe(el, url: str) -> Optional[str]:
    fn = globals().get("extract_embed_url")
    if callable(fn):
        try:
            return fn(el, url)
        except Exception:
            return None
    return None


def make_embed_placeholder_safe(index: int) -> str:
    fn = globals().get("make_embed_placeholder")
    if callable(fn):
        return fn(index)
    return f"[[OWTV_EMBED_{index}]]"
'''
text = text[:pos] + helpers + text[pos:]

start = text.find("def extract_article_text_and_media(url: str)")
end = text.find("\n\ndef gemini_client", start)
if start == -1 or end == -1:
    raise SystemExit("[V92 NEWS SCRAPER] function bounds non trovati")

new_func = r'''def extract_article_text_and_media(url: str) -> Tuple[str, Optional[str], List[Dict[str, str]]]:
    res = session.get(url, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    raw_html = res.text
    print(f"[NEWS v92] Scrape fetch status={res.status_code} content_type={res.headers.get('content-type', '')} html_chars={len(raw_html or '')} url={url}", flush=True)
    soup = BeautifulSoup(raw_html, "html.parser")
    for node in soup.select("script:not([type*='ld+json']), style, noscript, nav, footer, aside, form"):
        node.decompose()
    container = find_best_news_container(soup, url)
    safe_remove_social_noise(container)
    featured = extract_meta_image(soup, url)
    parts: List[str] = []
    embeds: List[Dict[str, str]] = []

    for el in container.find_all(["h2", "h3", "p", "li", "blockquote", "figure", "iframe", "div"]):
        if any(is_embed_node_safe(parent, url) for parent in el.parents if parent is not container):
            continue

        if is_embed_node_safe(el, url):
            embed_url = extract_embed_url_safe(el, url)
            if embed_url and not any(e.get("url") == embed_url for e in embeds):
                placeholder = make_embed_placeholder_safe(len(embeds) + 1)
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

    article_text = "\n\n".join(dict.fromkeys([p for p in parts if p.strip()]))

    if len(article_text) < 400:
        jsonld_text = extract_jsonld_article_text(soup)
        if len(jsonld_text) > len(article_text):
            article_text = jsonld_text

    if len(article_text) < 250:
        meta_text = extract_meta_description_text(soup)
        if len(meta_text) > len(article_text):
            article_text = meta_text

    if len(article_text) < 250:
        fallback = clean_text(container.get_text(" ", strip=True))
        if len(fallback) > len(article_text):
            article_text = fallback[:8000]

    if embeds:
        print(f"[NEWS v92] Embed totali estratti: {len(embeds)}", flush=True)
    if len(article_text) < 650:
        print(f"[NEWS v92] WARNING: estrazione news debole chars={len(article_text)} url={url}", flush=True)
        save_weak_scrape_debug_html(url, raw_html, article_text, soup)
    return article_text[:18000], featured, embeds
'''
text = text[:start] + new_func + text[end:]

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
if 'body_html = inject_news_embeds(body_html, embeds)' not in text and 'inject_news_embeds' in text:
    text = text.replace(
        'print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)',
        'body_html = inject_news_embeds(body_html, embeds)\n    print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)',
        1,
    )

p.write_text(text, encoding="utf-8")
print("[V92 NEWS SCRAPER] robust scraper applicato")
