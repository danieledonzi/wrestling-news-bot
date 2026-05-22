from pathlib import Path

MARK = "# v90.2.3: social embed quote positioning"
CODE = r'''

# v90.2.3: social embed quote positioning
BOT_VERSION = "v90_2_3_social_embed_quote_position"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_3_ENABLED = os.getenv("V90_2_3_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V90_2_3_SOCIAL_QUOTE_ENABLED = os.getenv("V90_2_3_SOCIAL_QUOTE_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
SOCIAL_EMBED_URL_RE_V9023 = re.compile(r"https?://(?:www\.)?(?:x\.com|twitter\.com)/[^\s<>\"']+/status/\d+[^\s<>\"']*", re.I)
SOCIAL_PIC_RE_V9023 = re.compile(r"\bpic\.twitter\.com/[A-Za-z0-9_]+\b", re.I)


def v9023_clean_social_text(text):
    text = SOCIAL_EMBED_URL_RE_V9023.sub("", str(text or ""))
    text = SOCIAL_PIC_RE_V9023.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def v9023_is_social_url_only(text):
    raw = str(text or "").strip()
    cleaned = v9023_clean_social_text(raw).strip(" .\u00a0")
    return bool(SOCIAL_EMBED_URL_RE_V9023.search(raw)) and not cleaned


def v9023_canonical_social_url(text):
    m = SOCIAL_EMBED_URL_RE_V9023.search(str(text or ""))
    if not m:
        return ""
    url = m.group(0).strip().rstrip(".,;)"]}")
    url = re.sub(r"\?.*$", "", url)
    return url


def v9023_quote_html(text):
    try:
        escaped = html.escape(v9023_clean_social_text(text), quote=False)
    except Exception:
        escaped = v9023_clean_social_text(text)
    if not escaped:
        return ""
    return (
        '<blockquote class="owtv-social-quote" style="border-left:4px solid #4b5cff;'
        'background:#eef3fb;margin:24px 0;padding:18px 22px;font-style:italic;">'
        f'{escaped}'
        '</blockquote>'
    )


def v9023_fix_social_embed_quotes(html_text):
    if not V90_2_3_ENABLED or not V90_2_3_SOCIAL_QUOTE_ENABLED or not html_text:
        return html_text
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        nodes = [n for n in soup.find_all(["p", "blockquote"]) if n and n.parent]
        seen = set()
        changed = 0
        i = 0
        while i < len(nodes):
            node = nodes[i]
            if not node.parent:
                i += 1
                continue
            node_text = node.get_text(" ", strip=True)
            url = v9023_canonical_social_url(node_text)
            if not url:
                i += 1
                continue
            if url in seen:
                node.decompose()
                changed += 1
                i += 1
                continue
            seen.add(url)
            # Make the embed URL paragraph clean and unique.
            node.clear()
            node.append(url)
            # Gather translated tweet text from immediately following paragraphs until normal article prose resumes.
            quote_parts = []
            j = i + 1
            while j < len(nodes) and len(quote_parts) < 3:
                nxt = nodes[j]
                if not nxt.parent:
                    j += 1
                    continue
                txt = nxt.get_text(" ", strip=True)
                if not txt:
                    j += 1
                    continue
                if SOCIAL_EMBED_URL_RE_V9023.search(txt):
                    nxt.decompose(); changed += 1; j += 1; continue
                clean = v9023_clean_social_text(txt)
                # Tweet text is usually short, emoji/hashtag-heavy, and adjacent to the social URL.
                # Stop on article prose attribution/transition.
                if re.match(r"^(secondo|nel documento|dalla presentazione|pertanto|la presenza|l'arresto|a pochi giorni|al momento)\b", clean, flags=re.I):
                    break
                if len(clean) > 260:
                    break
                quote_parts.append(clean)
                nxt.decompose(); changed += 1; j += 1
            quote_text = "\n\n".join([p for p in quote_parts if p])
            if quote_text:
                quote_soup = BeautifulSoup(v9023_quote_html(quote_text), "html.parser")
                node.insert_after(quote_soup)
                changed += 1
            i = j
        if changed:
            print(f"[EMBED v90.2.3] Social embed/quote normalizzati: {changed}")
            return str(soup)
    except Exception as e:
        print(f"[EMBED v90.2.3] social quote guard warning: {e}")
    return html_text

try:
    _ORIG_V9023_create_post = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        if V90_2_3_ENABLED and isinstance(data, dict):
            try:
                data = dict(data)
                data["testo"] = v9023_fix_social_embed_quotes(data.get("testo", ""))
            except Exception as e:
                print(f"[EMBED v90.2.3] pre-publish social guard warning: {e}")
        return _ORIG_V9023_create_post(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)
except Exception:
    pass

try:
    print("[BOOT v90.2.3] Social embed quote positioning attivo")
except Exception:
    pass
'''

def main():
    p = Path("bot.py")
    t = p.read_text(encoding="utf-8")
    if MARK in t:
        print("[SOURCE PATCH v90.2.3] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in t:
        raise SystemExit("[SOURCE PATCH v90.2.3] entrypoint marker not found")
    p.write_text(t.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.3] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
