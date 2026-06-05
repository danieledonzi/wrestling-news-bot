from pathlib import Path
import re

# v93.35: media extraction + ranking refinements
# - Preserve YouTube video ID casing in the URL posted to WordPress.
# - Keep Instagram post/reel URLs as plain URLs so WordPress/plugin can oEmbed them.
# - Recover Ringside lazy Instagram embeds from data-rsn-html base64 wrappers.
# - Recover article images from lazy srcset/data-srcset, including Smush AVIF wrappers.
# - Hard-skip non-major-brand medical-return stories and rank major brands above OVW/indie at similar score.

# -------------------------
# Base Publisher media rules
# -------------------------
pub = Path('agents/publisher.py')
s = pub.read_text(encoding='utf-8')

if 'v93_35_media_case_instagram_policy' not in s:
    s = re.sub(r'PUBLISHER_VERSION = "[^"]+"', 'PUBLISHER_VERSION = "v93_35_media_case_instagram_policy"', s, count=1)
    s = s.replace('return "youtube:" + vid.lower()', 'return "youtube:" + vid')
    old = '''def embed_block(url: str) -> str:
    u = display_embed_url(url)
    host = urlparse(u).netloc.lower().replace("www.", "")
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be"}:
        # v93.33: YouTube embeds work best in WordPress as a plain URL on its own line.
        # This avoids an ugly Shortcode block in the editor while preserving front-end oEmbed.
        return html.escape(u)
    # v93.33: social embeds are kept as shortcode blocks because plain X/Twitter URLs
    # often remain plain text until a manual editor conversion.
    return '<!-- wp:shortcode -->\\n[embed]' + html.escape(u) + '[/embed]\\n<!-- /wp:shortcode -->'
'''
    new = '''def embed_block(url: str) -> str:
    u = display_embed_url(url)
    host = urlparse(u).netloc.lower().replace("www.", "")
    if host in {"youtube.com", "youtube-nocookie.com", "youtu.be", "instagram.com"}:
        # v93.35: YouTube IDs are case-sensitive, so keep the original display URL.
        # Instagram posts/reels are also left as plain URLs: WordPress/plugin resolves them reliably.
        return html.escape(u)
    # v93.33/v93.35: X/Twitter and similar social embeds stay shortcode-backed because
    # plain X/Twitter URLs often remain plain text until a manual editor conversion.
    return '<!-- wp:shortcode -->\\n[embed]' + html.escape(u) + '[/embed]\\n<!-- /wp:shortcode -->'
'''
    if old in s:
        s = s.replace(old, new, 1)
    elif 'host in {"youtube.com", "youtube-nocookie.com", "youtu.be", "instagram.com"}' not in s:
        raise SystemExit('[V93 MEDIA] Publisher embed_block anchor non trovato')
    s = s.replace('"plain_youtube_urls_for_wordpress_oembed": True, "social_embed_shortcode_blocks": True,', '"plain_youtube_urls_for_wordpress_oembed": True, "plain_instagram_urls_for_wordpress_oembed": True, "social_embed_shortcode_blocks": True,')
    pub.write_text(s, encoding='utf-8')
    print('[V93 MEDIA] Base Publisher media policy applicata')
else:
    print('[V93 MEDIA] Base Publisher gia applicato')

# -------------------------
# Bob extraction refinements
# -------------------------
bob = Path('agents/bob.py')
s = bob.read_text(encoding='utf-8')

if 'v93_35_media_extract_instagram_images' not in s:
    s = re.sub(r'BOB_VERSION = "[^"]+"', 'BOB_VERSION = "v93_35_media_extract_instagram_images"', s, count=1)
    if 'import base64\n' not in s:
        s = s.replace('import html\n', 'import base64\nimport html\n', 1)

    helper_anchor = '''def extract_embed_urls_from_text(raw: str, base_url: str) -> list[str]:
'''
    helper = '''def decode_possible_rsn_lazy_embed_html(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def pick_srcset_url(value: str) -> str:
    raw = html.unescape(str(value or "").replace("\\/", "/")).strip()
    if not raw:
        return ""
    best_url = ""
    best_width = -1
    for part in raw.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0].strip()
        width = 0
        if len(bits) > 1:
            m = re.search(r"(\\d+)w", bits[1])
            if m:
                width = int(m.group(1))
        if width >= best_width:
            best_url = url
            best_width = width
    return best_url


def normalize_ringside_image_url(url: str) -> str:
    u = html.unescape(str(url or "").replace("\\/", "/")).strip()
    if not u or u.startswith("data:"):
        return ""
    u = re.sub(r"\\?.*$", "", u)
    u = u.replace("/wp-content/smush-avif/", "/wp-content/uploads/")
    if u.lower().endswith(".avif"):
        u = u[:-5]
    return u


def image_url_from_node(node: Tag, base_url: str) -> str:
    candidates: list[str] = []
    for attr in ["src", "data-src", "data-lazy-src", "data-original", "data-orig-src"]:
        value = node.get(attr)
        if value:
            candidates.append(str(value))
    for attr in ["srcset", "data-srcset", "data-lazy-srcset", "data-original-srcset"]:
        value = node.get(attr)
        if value:
            picked = pick_srcset_url(str(value))
            if picked:
                candidates.append(picked)
    for raw in candidates:
        url = normalize_ringside_image_url(absolute_url(base_url, raw))
        if url:
            return url
    return ""


'''
    if helper_anchor not in s:
        raise SystemExit('[V93 MEDIA] Bob helper anchor non trovato')
    s = s.replace(helper_anchor, helper + helper_anchor, 1)

    old_extract = '''def extract_embed_url(node: Tag, base_url: str) -> str:
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
    new_extract = '''def extract_embed_url(node: Tag, base_url: str) -> str:
    candidates: list[str] = []
    for attr in ["src", "href", "cite", "data-url", "data-href", "data-src", "data-lazy-src", "data-embed-url", "data-permalink", "data-instgrm-permalink"]:
        value = node.get(attr)
        if value:
            candidates.append(str(value))
    lazy_html = decode_possible_rsn_lazy_embed_html(str(node.get("data-rsn-html") or ""))
    if lazy_html:
        candidates.extend(extract_embed_urls_from_text(lazy_html, base_url))
        try:
            lazy_soup = BeautifulSoup(lazy_html, "html.parser")
            for tag in lazy_soup.find_all(True):
                for attr in ["href", "src", "data-instgrm-permalink", "data-permalink"]:
                    value = tag.get(attr)
                    if value:
                        candidates.append(str(value))
        except Exception:
            pass
    for link in node.find_all("a", href=True):
        candidates.append(str(link.get("href")))
    candidates.extend(extract_embed_urls_from_text(str(node), base_url))
    for raw in candidates:
        url = canonical_embed_url(absolute_url(base_url, raw))
        if is_valid_editorial_embed_url(url):
            return url
    return ""
'''
    if old_extract not in s:
        raise SystemExit('[V93 MEDIA] Bob extract_embed_url anchor non trovato')
    s = s.replace(old_extract, new_extract, 1)

    old_img = '''    if name == "img":
        src = node.get("src") or node.get("data-src") or node.get("data-lazy-src") or ""
        if not src and node.get("srcset"):
            src = str(node.get("srcset")).split(",")[0].strip().split(" ")[0]
        src = absolute_url(base_url, src)
        if not src or src.startswith("data:"):
            return None
        return {"type": "image", "url": src, "alt": clean_text(node.get("alt", ""))}
'''
    new_img = '''    if name == "img":
        src = image_url_from_node(node, base_url)
        if not src:
            return None
        return {"type": "image", "url": src, "alt": clean_text(node.get("alt", ""))}
'''
    if old_img not in s:
        raise SystemExit('[V93 MEDIA] Bob image anchor non trovato')
    s = s.replace(old_img, new_img, 1)

    prompt_anchor = '''REGOLE
- Non riassumere e non aggiungere informazioni.
'''
    if prompt_anchor in s and 'Bob non deve cercare media' not in s:
        s = s.replace(prompt_anchor, '''REGOLE
- Non riassumere e non aggiungere informazioni.
- Bob non deve cercare media con Gemini: immagini, YouTube, Instagram/Reel, X/Twitter e altri embed sono estratti dal DOM prima della traduzione e vanno preservati nella sequenza originale.
''', 1)

    bob.write_text(s, encoding='utf-8')
    print('[V93 MEDIA] Bob media extraction applicata')
else:
    print('[V93 MEDIA] Bob gia applicato')

# -------------------------
# Menzo medical/ranking rules
# -------------------------
menzo = Path('agents/menzo_policy_v93_15.py')
s = menzo.read_text(encoding='utf-8')

if 'v93_35_medical_brand_ranking' not in s:
    s = s.replace('MENZO_VERSION = "v93_34_menzo_footprint_policy"', 'MENZO_VERSION = "v93_35_medical_brand_ranking"')
    s = s.replace('MENZO_VERSION = "v93_20_selective_softpool"', 'MENZO_VERSION = "v93_35_medical_brand_ranking"')
    s = s.replace('MENZO_VERSION = "v93_32_menzo_story_dedupe"', 'MENZO_VERSION = "v93_35_medical_brand_ranking"')

    old_sort = '''def sort_item(item: dict[str, Any]) -> tuple[int, float, str]:
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    try:
        age = float(item.get("age_hours", 999999) or 999999)
    except Exception:
        age = 999999.0
    return score, -age, str(item.get("published") or "")
'''
    new_sort = '''def brand_rank(item: dict[str, Any]) -> int:
    text = " ".join(str(item.get(k) or "") for k in ["category_hint", "title", "summary", "reason", "source", "url", "source_url"]).lower()
    if "wwe" in text or "smackdown" in text or "raw" in text:
        return 100
    if "nxt" in text:
        return 92
    if "aew" in text or "dynamite" in text or "collision" in text:
        return 90
    if "tna" in text or "impact" in text or "slammiversary" in text:
        return 72
    if "roh" in text or "cmll" in text or "stardom" in text:
        return 68
    if "ovw" in text or "ohio valley" in text:
        return 25
    if "indie" in text or "independent" in text:
        return 20
    return 40


def is_medical_return_story(item: dict[str, Any]) -> bool:
    text = " ".join(str(item.get(k) or "") for k in ["title", "summary", "reason", "article_type", "url", "source_url"]).lower()
    return any(x in text for x in ["medical emergency", "medically cleared", "cleared to return", "medical return", "emergenza medica", "rientro", "ritorno sul ring"])


def apply_medical_brand_policy(result: dict[str, Any]) -> None:
    moved: list[dict[str, Any]] = []
    for section in ["selected", "pending"]:
        kept: list[dict[str, Any]] = []
        for item in result.get(section, []) if isinstance(result.get(section), list) else []:
            if not isinstance(item, dict):
                continue
            if is_medical_return_story(item) and brand_rank(item) < 80:
                item = dict(item)
                item["decision"] = "skip"
                item["priority"] = "skip"
                item["article_type"] = "low_value"
                item["reason"] = "skip:medical_return_non_major_brand; " + str(item.get("reason") or "")
                item.setdefault("menzo_policy", {})["medical_return_major_brands_only"] = True
                moved.append(item)
            else:
                kept.append(item)
        result[section] = kept
    result.setdefault("skipped", []).extend(moved)
    result.setdefault("postprocess", {})["medical_return_non_major_brand_skipped"] = len(moved)


def sort_item(item: dict[str, Any]) -> tuple[int, int, float, str]:
    try:
        score = int(item.get("score", 0) or 0)
    except Exception:
        score = 0
    try:
        age = float(item.get("age_hours", 999999) or 999999)
    except Exception:
        age = 999999.0
    # Brand importance is a tie-breaker after score: at equal or near-equal editorial value,
    # TNA/ROH outrank OVW/indie, and WWE/NXT/AEW outrank all.
    return score, brand_rank(item), -age, str(item.get("published") or "")
'''
    if old_sort not in s:
        raise SystemExit('[V93 MEDIA] Menzo sort anchor non trovato')
    s = s.replace(old_sort, new_sort, 1)

    # Insert the medical gate after source-opinion and before footprint policy when v93.34 is active.
    old_gate = '''    apply_source_opinion_policy(result)
    apply_story_footprint_policy(result)
'''
    new_gate = '''    apply_source_opinion_policy(result)
    apply_medical_brand_policy(result)
    apply_story_footprint_policy(result)
'''
    if old_gate in s:
        s = s.replace(old_gate, new_gate, 1)
    else:
        # fallback when footprint policy has not been injected yet
        old_base = '''    rebuild_decisions(result)
    result["version"] = MENZO_VERSION
'''
        if old_base in s:
            s = s.replace(old_base, '''    rebuild_decisions(result)
    apply_medical_brand_policy(result)
    result["version"] = MENZO_VERSION
''', 1)
        else:
            raise SystemExit('[V93 MEDIA] Menzo gate anchor non trovato')

    s = s.replace('    result.setdefault("policy", {})["story_footprints_ttl_days"] = 7\n', '    result.setdefault("policy", {})["story_footprints_ttl_days"] = 7\n    result.setdefault("policy", {})["medical_return_major_brands_only"] = True\n    result.setdefault("policy", {})["brand_rank_tiebreaker"] = "WWE/NXT/AEW > TNA/ROH > OVW/indie"\n')
    s = s.replace('footprint_dupes={result.get(\'postprocess\', {}).get(\'story_footprint_duplicates_skipped\', 0)} softpool=', 'footprint_dupes={result.get(\'postprocess\', {}).get(\'story_footprint_duplicates_skipped\', 0)} medical_non_major={result.get(\'postprocess\', {}).get(\'medical_return_non_major_brand_skipped\', 0)} softpool=')
    menzo.write_text(s, encoding='utf-8')
    print('[V93 MEDIA] Menzo medical/brand ranking applicato')
else:
    print('[V93 MEDIA] Menzo gia applicato')
