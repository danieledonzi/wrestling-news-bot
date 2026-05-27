from pathlib import Path

p = Path('modules/report_workshop_v92.py')
text = p.read_text(encoding='utf-8')

if 'V92_AUTO_RAW_RINGSIDE_EMBED_PATCH = True' in text:
    print('[V92 RAW RSN] patch gia applicata')
    raise SystemExit(0)

marker = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
if marker in text:
    text = text.replace(marker, 'V92_AUTO_RAW_RINGSIDE_EMBED_PATCH = True\n' + marker, 1)

# Need URL decoding for escaped lazy payloads.
if 'from urllib.parse import unquote' not in text:
    text = text.replace('from urllib.parse import urljoin, urlparse\n', 'from urllib.parse import urljoin, urlparse, unquote\n', 1)

helper = '''

def rsn_decode_variants(value: str) -> List[str]:
    raw = str(value or '')
    if not raw:
        return []
    variants: List[str] = []
    def add(v: str) -> None:
        if v and v not in variants:
            variants.append(v)
    add(raw)
    add(html_lib.unescape(raw))
    add(unquote(raw))
    add(unquote(html_lib.unescape(raw)))
    try:
        add(raw.encode('utf-8', errors='ignore').decode('unicode_escape', errors='ignore'))
    except Exception:
        pass
    # Decode possible base64/base64url html payloads if helper exists.
    try:
        for v in decode_possible_base64_html(raw):
            add(v)
            add(html_lib.unescape(v))
            add(unquote(v))
            add(unquote(html_lib.unescape(v)))
    except Exception:
        pass
    expanded: List[str] = []
    for v in variants:
        add_v = v.replace('\\/', '/').replace('\\u002F', '/').replace('\\u002f', '/')
        expanded.append(add_v)
        expanded.append(unquote(add_v))
    for v in expanded:
        add(v)
    return variants


def rsn_status_urls_from_value(value: str) -> List[str]:
    ids: List[str] = []
    seen: set[str] = set()
    for raw in rsn_decode_variants(value):
        # Accept normal, backslash-escaped, unicode-escaped and percent-encoded slash separators.
        patterns = [
            r'(?:status|statuses)[/\\]+([0-9]{8,25})',
            r'(?:status|statuses)(?:%2[fF])+([0-9]{8,25})',
            r'(?:status|statuses)(?:\\u002[fF])+([0-9]{8,25})',
        ]
        for pat in patterns:
            for m in re.finditer(pat, raw, flags=re.I):
                sid = m.group(1)
                if sid not in seen:
                    seen.add(sid)
                    ids.append(sid)
    return [f'https://twitter.com/i/status/{sid}' for sid in ids]


def rsn_is_social_or_share_node(el) -> bool:
    try:
        node = el
        while node is not None and getattr(node, 'name', None):
            cls = ' '.join(node.get('class') or []).lower()
            node_id = str(node.get('id') or '').lower()
            marker = cls + ' ' + node_id
            if 'rsn-social' in marker or 'social-share' in marker or 'share-buttons' in marker or 'post-share' in marker:
                return True
            node = node.parent
    except Exception:
        return False
    return False


def rsn_remove_social_blocks(content) -> None:
    if not content:
        return
    selectors = [
        '.rsn-social', '.rsn-socials', '.social-share', '.share-buttons', '.post-share',
        '.article-social', '.entry-share', '.follow-us', '.author-social', '.social-links'
    ]
    for sel in selectors:
        try:
            for node in content.select(sel):
                node.decompose()
        except Exception:
            pass
'''
anchor = '\n\ndef extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:\n'
if 'def rsn_status_urls_from_value' not in text and anchor in text:
    text = text.replace(anchor, helper + anchor, 1)

start = text.find('def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:')
end = text.find('\n\ndef merge_ringside_embeds_by_position', start)
if start == -1 or end == -1:
    raise SystemExit('[V92 RAW RSN] extractor block non trovato')

new_func = '''def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:
    if 'ringsidenews.com' not in get_domain(base_url):
        return []
    root = content or soup
    blocks: List[Dict[str, str]] = []
    seen: set[str] = set()

    def add_urls(urls: List[str], paragraph_anchor: int, source: str) -> None:
        for url in urls:
            key = social_embed_key(url)
            if not key or key in seen:
                continue
            seen.add(key)
            blocks.append({'type': 'embed', 'url': normalize_social_url(url), 'paragraph_anchor': str(paragraph_anchor), 'source': source})

    paragraph_count = 0
    try:
        for el in root.find_all(True):
            if el.name in {'p', 'h2', 'h3', 'blockquote', 'li'}:
                txt = clean_text(el.get_text(' ', strip=True))
                if len(txt) >= 20:
                    paragraph_count += 1
            if rsn_is_social_or_share_node(el):
                continue
            attrs = ['data-rsn-html', 'data-rsn_html', 'data-html', 'data-embed', 'data-lazy', 'data-src', 'data-url', 'href', 'src', 'cite']
            for attr in attrs:
                val = el.get(attr)
                if val:
                    urls = rsn_status_urls_from_value(val)
                    if urls:
                        add_urls(urls, paragraph_count, f'{el.name}:{attr}')
            cls = ' '.join(el.get('class') or []).lower()
            if 'rsn-lazy' in cls or 'twitter' in cls or 'embed' in cls:
                urls = rsn_status_urls_from_value(str(el))
                if urls:
                    add_urls(urls, paragraph_count, f'{el.name}:outer_html')
    except Exception as exc:
        print(f'[RSN EMBED v92] Warning raw Ringside extraction failed: {exc}', flush=True)

    print(f'[RSN EMBED v92] Estratti raw rsn-lazy/status Ringside: {len(blocks)} url={base_url}', flush=True)
    return blocks
'''
text = text[:start] + new_func + text[end:]

# Remove Ringside social/share blocks before base body extraction so the 3 social bar links do not enter blocks.
old_scrape = '''    soup = BeautifulSoup(html, "html.parser")
    content = parse_content_container(soup, url)
    featured = extract_meta_image(soup, url)
    blocks = extract_blocks(content, url)
'''
new_scrape = '''    soup = BeautifulSoup(html, "html.parser")
    content = parse_content_container(soup, url)
    if "ringsidenews.com" in get_domain(url):
        rsn_remove_social_blocks(content)
    featured = extract_meta_image(soup, url)
    blocks = extract_blocks(content, url)
'''
if old_scrape in text:
    text = text.replace(old_scrape, new_scrape, 1)
else:
    print('[V92 RAW RSN] scrape_article social cleanup insertion non trovato')

# Same cleanup path for optional raw html helper if present.
old_raw = '''    soup = BeautifulSoup(html, "html.parser")
    content = parse_content_container(soup, url)
    featured = extract_meta_image(soup, url)
    blocks = extract_blocks(content, url)
'''
# second occurrence may already be changed; replace only if still exists
if old_raw in text:
    text = text.replace(old_raw, new_scrape, 1)

p.write_text(text, encoding='utf-8')
print('[V92 RAW RSN] auto raw Ringside embed extraction applicata')
