from pathlib import Path

p = Path('modules/report_workshop_v92.py')
text = p.read_text(encoding='utf-8')

if 'V92_RINGSIDE_BROAD_FINAL_CLEANUP = True' in text:
    print('[V92 RSN FINAL] patch gia applicata')
    raise SystemExit(0)

marker = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
if marker in text:
    text = text.replace(marker, 'V92_RINGSIDE_BROAD_FINAL_CLEANUP = True\n' + marker, 1)

# Restore permissive social URL detection so the broad extractor recovers all Ringside lazy embeds.
start = text.find('def looks_like_social_embed_url(url: str) -> bool:')
end = text.find('\n\ndef extract_social_urls_from_html_fragment', start)
if start != -1 and end != -1:
    broad_func = '''def looks_like_social_embed_url(url: str) -> bool:
    u = normalize_social_url(url or "")
    if not re.search(r"(?:twitter\.com|x\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com)", u, re.I):
        return False
    if re.search(r"/(share|intent|hashtag|search)(?:/|\?|$)", u, re.I):
        return False
    return True
'''
    text = text[:start] + broad_func + text[end:]

# Restore broad Ringside extractor, equivalent to the version that produced all embeds.
start = text.find('def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:')
end = text.find('\n\ndef merge_ringside_embeds_by_position', start)
if start != -1 and end != -1:
    broad_extractor = '''def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:
    domain = get_domain(base_url)
    if "ringsidenews.com" not in domain:
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
                "type": "embed",
                "url": normalize_social_url(url),
                "paragraph_anchor": str(paragraph_anchor),
                "source": source,
            })

    paragraph_count = 0
    try:
        for el in root.find_all(True):
            if el.name in {"p", "h2", "h3", "blockquote", "li"}:
                txt = clean_text(el.get_text(" ", strip=True))
                if len(txt) >= 20:
                    paragraph_count += 1
            attrs_to_scan = []
            for attr in ["data-rsn-html", "data-rsn_html", "data-html", "data-embed", "data-lazy", "data-src", "data-url", "href", "src", "cite"]:
                val = el.get(attr)
                if val:
                    attrs_to_scan.append((attr, val))
            cls = " ".join(el.get("class") or [])
            if "rsn-lazy" in cls or attrs_to_scan:
                for attr, val in attrs_to_scan:
                    urls = extract_social_urls_from_html_fragment(val)
                    if urls:
                        add_urls(urls, paragraph_count, f"{el.name}:{attr}")
            if "rsn-lazy" in cls:
                urls = extract_social_urls_from_html_fragment(str(el))
                if urls:
                    add_urls(urls, paragraph_count, f"{el.name}:outer_html")
    except Exception as exc:
        print(f"[RSN EMBED v92] Warning broad extraction failed: {exc}", flush=True)
    try:
        global_urls = extract_social_urls_from_html_fragment(str(root))
        add_urls(global_urls, paragraph_count, "global_html")
    except Exception as exc:
        print(f"[RSN EMBED v92] Warning broad global fallback failed: {exc}", flush=True)
    print(f"[RSN EMBED v92] Estratti broad Ringside embed: {len(blocks)} url={base_url}", flush=True)
    return blocks
'''
    text = text[:start] + broad_extractor + text[end:]

helper = '''

def is_bad_ringside_render_line(line: str) -> bool:
    raw = (line or '').strip()
    low = raw.lower()
    if not raw:
        return False
    if 'tweets by ringsidenews' in low:
        return True
    if 'sanjay thakur' in low and ('wwe' in low or 'aew' in low or 'risultati' in low or 'results' in low):
        return True
    if 'riporta i risultati in diretta degli show wwe e aew' in low:
        return True
    if 'provides live results for wwe and aew shows' in low:
        return True
    # Social/channel/profile lines are not article content. Keep only concrete tweet/status URLs.
    if re.match(r'^https?://', raw, re.I):
        if re.search(r'(twitter\.com|x\.com)', raw, re.I):
            return not bool(re.search(r'/(status|statuses)/\d+', raw, re.I))
        if re.search(r'(youtube\.com/channel|youtube\.com/@|instagram\.com/ringsidenews|instagram\.com/ringsidenewscom|facebook\.com|linkedin\.com|pinterest\.com|t\.me)', raw, re.I):
            return True
    return False


def cleanup_ringside_rendered_html(content: str, job: Dict[str, Any]) -> str:
    if str(job.get('source') or '').lower() != 'ringsidenews':
        return content
    lines = (content or '').splitlines()
    cleaned: List[str] = []
    removed = 0
    for line in lines:
        if is_bad_ringside_render_line(line):
            removed += 1
            continue
        cleaned.append(line)
    out = '\n'.join(cleaned)
    # Remove simple paragraphs/blocks containing known boilerplate if translation wrapped them.
    out = re.sub(r'<p>[^<]*Sanjay Thakur[^<]*(?:WWE|AEW)[^<]*</p>\s*', '', out, flags=re.I)
    out = re.sub(r'<p>[^<]*riporta i risultati in diretta degli show WWE e AEW[^<]*</p>\s*', '', out, flags=re.I)
    if removed:
        print(f"[RSN CLEAN v92] Rimosse righe/link social spurie post-render: {removed}", flush=True)
    return out
'''
anchor = '\n\ndef publish_report(job: Dict[str, Any], content: str, featured_image_url: Optional[str]) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:\n'
if 'def cleanup_ringside_rendered_html' not in text and anchor in text:
    text = text.replace(anchor, helper + anchor, 1)

# Apply final cleanup immediately before WordPress/content_with_embeds.
old = '    content = append_source_attribution(content_with_embeds(content), job)\n'
new = '    content = cleanup_ringside_rendered_html(content, job)\n    content = append_source_attribution(content_with_embeds(content), job)\n'
if old in text and 'cleanup_ringside_rendered_html(content, job)' not in text:
    text = text.replace(old, new, 1)

p.write_text(text, encoding='utf-8')
print('[V92 RSN FINAL] broad embed + final cleanup applicati')
