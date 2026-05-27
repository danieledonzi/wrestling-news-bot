from pathlib import Path

p = Path('modules/report_workshop_v92.py')
text = p.read_text(encoding='utf-8')

if 'V92_RINGSIDE_STATUS_ONLY_PATCH = True' in text:
    print('[V92 RSN STATUS] patch gia applicata')
    raise SystemExit(0)

marker = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
if marker in text:
    text = text.replace(marker, 'V92_RINGSIDE_STATUS_ONLY_PATCH = True\n' + marker, 1)

helper = '''

def extract_tweet_status_urls_from_fragment(fragment: str) -> List[str]:
    out: List[str] = []
    if not fragment:
        return out
    candidates = decode_possible_base64_html(str(fragment)) if 'decode_possible_base64_html' in globals() else [str(fragment)]
    for candidate in candidates:
        raw = html_lib.unescape(str(candidate))
        tweet_url_pattern = r"https?://(?:www\\.)?(?:twitter\\.com|x\\.com)/[^\\s\\\"'<>]+"
        for m in re.finditer(tweet_url_pattern, raw, flags=re.I):
            u = normalize_social_url(m.group(0)).rstrip('),.;]')
            if re.search(r'/(?:status|statuses)/\\d+', u, re.I):
                out.append(u)
    deduped: List[str] = []
    seen: set[str] = set()
    for u in out:
        key = social_embed_key(u)
        if key and key not in seen:
            seen.add(key)
            deduped.append(u)
    return deduped
'''
anchor = '\n\ndef extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:\n'
if 'def extract_tweet_status_urls_from_fragment' not in text and anchor in text:
    text = text.replace(anchor, helper + anchor, 1)

start = text.find('def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:')
end = text.find('\n\ndef merge_ringside_embeds_by_position', start)
if start == -1 or end == -1:
    raise SystemExit('[V92 RSN STATUS] extractor non trovato')

new_func = '''def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:
    domain = get_domain(base_url)
    if 'ringsidenews.com' not in domain:
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
            blocks.append({
                'type': 'embed',
                'url': normalize_social_url(url),
                'paragraph_anchor': str(paragraph_anchor),
                'source': source,
            })

    paragraph_count = 0
    try:
        for el in root.find_all(True):
            if el.name in {'p', 'h2', 'h3', 'blockquote', 'li'}:
                txt = clean_text(el.get_text(' ', strip=True))
                if len(txt) >= 20:
                    paragraph_count += 1
            for attr in ['data-rsn-html', 'data-rsn_html', 'data-html', 'data-embed', 'data-lazy', 'data-src', 'data-url', 'href', 'src', 'cite']:
                val = el.get(attr)
                if val:
                    urls = extract_tweet_status_urls_from_fragment(val)
                    if urls:
                        add_urls(urls, paragraph_count, f'{el.name}:{attr}')
            cls = ' '.join(el.get('class') or [])
            if 'rsn-lazy' in cls or 'twitter' in cls:
                urls = extract_tweet_status_urls_from_fragment(str(el))
                if urls:
                    add_urls(urls, paragraph_count, f'{el.name}:outer_html')
    except Exception as exc:
        print(f'[RSN EMBED v92] Warning status extraction failed: {exc}', flush=True)

    try:
        urls = extract_tweet_status_urls_from_fragment(str(root))
        add_urls(urls, paragraph_count, 'global_status_html')
    except Exception as exc:
        print(f'[RSN EMBED v92] Warning status global fallback failed: {exc}', flush=True)

    print(f'[RSN EMBED v92] Estratti tweet/status Ringside: {len(blocks)} url={base_url}', flush=True)
    return blocks
'''
text = text[:start] + new_func + text[end:]

p.write_text(text, encoding='utf-8')
print('[V92 RSN STATUS] status-only Ringside patch applicata')
