from pathlib import Path
import re

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_RINGSIDE_EMBED_RECOVERY = True" in text:
    print("[V92 RSN] embed recovery gia applicata")
    raise SystemExit(0)

# Marker.
marker = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
text = text.replace(marker, 'V92_RINGSIDE_EMBED_RECOVERY = True\n' + marker, 1)

# Add imports required by html unescape if not already available as html_lib exists.

helper = r'''

def social_embed_key(url: str) -> str:
    u = normalize_social_url(url or "").strip().lower()
    u = u.split("?", 1)[0].rstrip("/")
    # Tweet/status id is the strongest canonical key.
    m = re.search(r"/(?:status|statuses)/(\d+)", u)
    if m:
        return "tweet:" + m.group(1)
    return re.sub(r"\W+", "", u)


def looks_like_social_embed_url(url: str) -> bool:
    u = normalize_social_url(url or "")
    if not re.search(r"(?:twitter\.com|x\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com)", u, re.I):
        return False
    # Filter obvious sharing/profile/credit noise where possible.
    if re.search(r"/(share|intent|hashtag|search)(?:/|\?|$)", u, re.I):
        return False
    return True


def extract_social_urls_from_html_fragment(fragment: str) -> List[str]:
    out: List[str] = []
    if not fragment:
        return out
    raw = html_lib.unescape(str(fragment))
    try:
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup.find_all(["a", "iframe", "blockquote"]):
            for attr in ["href", "src", "cite", "data-href", "data-url"]:
                val = tag.get(attr)
                if val and looks_like_social_embed_url(val):
                    out.append(normalize_social_url(val))
    except Exception:
        pass
    for m in re.finditer(r"https?://[^\s'\"<>]+", raw, flags=re.I):
        u = m.group(0).rstrip("),.;]")
        if looks_like_social_embed_url(u):
            out.append(normalize_social_url(u))
    deduped: List[str] = []
    seen: set[str] = set()
    for u in out:
        key = social_embed_key(u)
        if key and key not in seen:
            seen.add(key)
            deduped.append(u)
    return deduped


def extract_ringside_embed_blocks(soup: BeautifulSoup, content, base_url: str) -> List[Dict[str, str]]:
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
            for attr in ["data-rsn-html", "data-html", "data-embed", "data-lazy", "data-src", "data-url", "href", "src"]:
                val = el.get(attr)
                if val:
                    attrs_to_scan.append((attr, val))
            cls = " ".join(el.get("class") or [])
            if "rsn-lazy" in cls or attrs_to_scan:
                for attr, val in attrs_to_scan:
                    urls = extract_social_urls_from_html_fragment(val)
                    if urls:
                        add_urls(urls, paragraph_count, f"{el.name}:{attr}")
            # Some lazy embed containers keep escaped markup as text.
            if "rsn-lazy" in cls:
                html_blob = str(el)
                urls = extract_social_urls_from_html_fragment(html_blob)
                if urls:
                    add_urls(urls, paragraph_count, f"{el.name}:outer_html")
    except Exception as exc:
        print(f"[RSN EMBED v92] Warning extraction failed: {exc}", flush=True)

    # Global fallback over full HTML, still useful for rsn-lazy script blobs.
    try:
        global_urls = extract_social_urls_from_html_fragment(str(root))
        add_urls(global_urls, paragraph_count, "global_html")
    except Exception as exc:
        print(f"[RSN EMBED v92] Warning global fallback failed: {exc}", flush=True)

    print(f"[RSN EMBED v92] Estratti embed Ringside: {len(blocks)} url={base_url}", flush=True)
    return blocks


def merge_ringside_embeds_by_position(blocks: List[Dict[str, str]], rsn_embeds: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not rsn_embeds:
        return blocks
    existing_keys = {social_embed_key(b.get("url", "")) for b in blocks if b.get("type") == "embed"}
    new_embeds = [e for e in rsn_embeds if social_embed_key(e.get("url", "")) not in existing_keys]
    if not new_embeds:
        print(f"[RSN EMBED v92] Nessun embed Ringside aggiuntivo da reinserire", flush=True)
        return blocks

    out: List[Dict[str, str]] = []
    text_seen = 0
    pending = sorted(new_embeds, key=lambda e: int(e.get("paragraph_anchor") or 0))
    inserted = 0
    for block in blocks:
        out.append(block)
        if block.get("type") in {"heading", "paragraph", "quote"}:
            text_seen += 1
            while pending and int(pending[0].get("paragraph_anchor") or 0) <= text_seen:
                out.append(pending.pop(0))
                inserted += 1
    for e in pending:
        out.append(e)
        inserted += 1
    print(
        f"[RSN EMBED v92] Positional merge: existing={len(existing_keys)} added={inserted} total_expected={len(existing_keys) + inserted}",
        flush=True,
    )
    return out
'''

insert_before = "\n\ndef extract_blocks(content, base_url: str) -> List[Dict[str, str]]:\n"
if "def extract_ringside_embed_blocks" not in text:
    text = text.replace(insert_before, helper + insert_before, 1)

# Modify scrape_article to merge RSN embeds.
old_scrape = '''    content = parse_content_container(soup, url)
    featured = extract_meta_image(soup, url)
    blocks = extract_blocks(content, url)
    return blocks, html, featured
'''
new_scrape = '''    content = parse_content_container(soup, url)
    featured = extract_meta_image(soup, url)
    blocks = extract_blocks(content, url)
    rsn_embeds = extract_ringside_embed_blocks(soup, content, url)
    blocks = merge_ringside_embeds_by_position(blocks, rsn_embeds)
    return blocks, html, featured
'''
if old_scrape not in text:
    raise SystemExit("[V92 RSN] scrape_article block non trovato")
text = text.replace(old_scrape, new_scrape, 1)

p.write_text(text, encoding="utf-8")
print("[V92 RSN] Ringside embed recovery applicata")
