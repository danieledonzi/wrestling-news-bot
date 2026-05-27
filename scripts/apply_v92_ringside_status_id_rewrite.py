from pathlib import Path

p = Path('modules/report_workshop_v92.py')
text = p.read_text(encoding='utf-8')

if 'V92_RINGSIDE_STATUS_ID_REWRITE = True' in text:
    print('[V92 RSN ID] patch gia applicata')
    raise SystemExit(0)

marker = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
if marker in text:
    text = text.replace(marker, 'V92_RINGSIDE_STATUS_ID_REWRITE = True\n' + marker, 1)

helper = '''

def extract_tweet_status_urls_from_fragment(fragment: str) -> List[str]:
    """Extract only concrete tweet status ids from decoded Ringside lazy HTML."""
    if not fragment:
        return []
    candidates = decode_possible_base64_html(str(fragment)) if 'decode_possible_base64_html' in globals() else [str(fragment)]
    ids: List[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        raw = html_lib.unescape(str(candidate))
        # Search by status id rather than full URL to avoid profile/t.co/noise and quoting issues.
        for m in re.finditer('/(?:status|statuses)/([0-9]{8,25})', raw, flags=re.I):
            sid = m.group(1)
            if sid not in seen:
                seen.add(sid)
                ids.append(sid)
    return [f'https://twitter.com/i/status/{sid}' for sid in ids]
'''

start = text.find('def extract_tweet_status_urls_from_fragment(fragment: str) -> List[str]:')
end = text.find('\n\ndef extract_ringside_embed_blocks', start)
if start != -1 and end != -1:
    text = text[:start] + helper.strip() + text[end:]
else:
    anchor = '\n\ndef extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:\n'
    if anchor in text:
        text = text.replace(anchor, helper + anchor, 1)
    else:
        raise SystemExit('[V92 RSN ID] anchor extractor non trovato')

start = text.find('def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:')
end = text.find('\n\ndef merge_ringside_embeds_by_position', start)
if start == -1 or end == -1:
    raise SystemExit('[V92 RSN ID] extractor block non trovato')

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
            if 'rsn-lazy' in cls or 'twitter' in cls or 'embed' in cls:
                urls = extract_tweet_status_urls_from_fragment(str(el))
                if urls:
                    add_urls(urls, paragraph_count, f'{el.name}:outer_html')
    except Exception as exc:
        print(f'[RSN EMBED v92] Warning id extraction failed: {exc}', flush=True)

    try:
        urls = extract_tweet_status_urls_from_fragment(str(root))
        add_urls(urls, paragraph_count, 'global_status_id_html')
    except Exception as exc:
        print(f'[RSN EMBED v92] Warning id global fallback failed: {exc}', flush=True)

    print(f'[RSN EMBED v92] Estratti tweet/status-id Ringside: {len(blocks)} url={base_url}', flush=True)
    return blocks
'''
text = text[:start] + new_func + text[end:]

p.write_text(text, encoding='utf-8')
print('[V92 RSN ID] status-id rewrite applicata')
