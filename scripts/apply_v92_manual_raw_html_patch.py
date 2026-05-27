from pathlib import Path

p = Path("modules/report_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_MANUAL_RAW_HTML_PATCH = True" in text:
    print("[V92 RAW HTML] patch gia applicata")
    raise SystemExit(0)

marker = 'SOCIAL_DOMAINS = ["twitter.com", "x.com", "instagram.com", "youtube.com", "youtu.be"]\n'
if marker in text:
    text = text.replace(marker, 'V92_MANUAL_RAW_HTML_PATCH = True\n' + marker, 1)

helper = '''

def scrape_article_from_html(raw_html: str, url: str) -> Tuple[List[Dict[str, str]], str, Optional[str]]:
    html = raw_html or ""
    soup = BeautifulSoup(html, "html.parser")
    content = parse_content_container(soup, url)
    featured = extract_meta_image(soup, url)
    blocks = extract_blocks(content, url)
    if "ringsidenews.com" in get_domain(url) and "extract_ringside_embed_blocks" in globals():
        try:
            rsn_embeds = extract_ringside_embed_blocks(soup, content, url)
            blocks = merge_ringside_embeds_by_position(blocks, rsn_embeds)
        except Exception as exc:
            print(f"[V92 RAW HTML] Warning merge Ringside embed da HTML grezzo fallito: {exc}", flush=True)
    print(f"[V92 RAW HTML] Usato HTML grezzo manuale: chars={len(html)} blocks={len(blocks)} embeds={sum(1 for b in blocks if b.get('type') == 'embed')}", flush=True)
    return blocks, html, featured
'''
anchor = "\n\ndef extract_json_object(raw_text: str) -> Dict[str, Any]:\n"
if "def scrape_article_from_html" not in text and anchor in text:
    text = text.replace(anchor, helper + anchor, 1)

old = '    blocks, _html, featured_image = scrape_article(job["source_url"])\n'
new = '''    if job.get("source_html"):
        blocks, _html, featured_image = scrape_article_from_html(str(job.get("source_html") or ""), job["source_url"])
    else:
        blocks, _html, featured_image = scrape_article(job["source_url"])
'''
if old in text:
    text = text.replace(old, new, 1)
elif 'scrape_article_from_html(str(job.get("source_html")' in text:
    print("[V92 RAW HTML] run_report_workshop gia raw-aware")
else:
    print("[V92 RAW HTML] linea scrape_article in run_report_workshop non trovata")

p.write_text(text, encoding="utf-8")
print("[V92 RAW HTML] manual raw HTML support applicato")
