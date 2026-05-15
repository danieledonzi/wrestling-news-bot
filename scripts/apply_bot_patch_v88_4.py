from pathlib import Path

PATCH = r'''
# =========================
# v88.4: quality microfixes for quotes, report media and soft items
# =========================
BOT_VERSION = "v88_4_quality_microfixes"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V884_QUALITY_MICROFIXES_ENABLED = os.getenv("V88_4_QUALITY_MICROFIXES_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V884_REPORT_CREDIT_EMBED_GUARD_ENABLED = os.getenv("V88_4_REPORT_CREDIT_EMBED_GUARD_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V884_BLOCKQUOTE_SANITIZER_ENABLED = os.getenv("V88_4_BLOCKQUOTE_SANITIZER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V884_SOFT_GAMING_SKIP_ENABLED = os.getenv("V88_4_SOFT_GAMING_SKIP_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V884_HEALTH_PERSONAL_CAP = int(os.getenv("V88_4_HEALTH_PERSONAL_CAP", "54"))
V884_GAMING_CAP = int(os.getenv("V88_4_GAMING_CAP", "45"))

# The layoffs terms are deliberately NOT enough by themselves. They must be paired with
# a clear gaming/WWE 2K context, otherwise legitimate wrestling layoffs would be skipped.
V884_GAMING_CONTEXT_TERMS = [
    "wwe 2k", "visual concepts", "2k developers", "2k developer", "game developers",
    "gaming", "video game", "videogame", "developer team", "development team",
]
V884_LAYOFF_TERMS = ["company-wide layoffs", "layoffs", "licenziamenti", "hit hard", "colpito"]
V884_GAMING_OPERATIONAL_TERMS = [
    "cover star", "roster reveal", "dlc", "release date", "gameplay trailer", "announced for wwe 2k",
]


def v884_probe(*parts):
    try:
        return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception:
        return " ".join(str(p or "") for p in parts).lower()


def v884_is_gaming_soft_non_news(title="", text="", url="", editorial_analysis=None):
    p = v884_probe(title, url, (text or "")[:2000], (editorial_analysis or {}).get("article_type_reason", ""))
    if any(term in p for term in V884_GAMING_OPERATIONAL_TERMS):
        return False
    has_gaming_context = any(term in p for term in V884_GAMING_CONTEXT_TERMS)
    has_layoff_context = any(term in p for term in V884_LAYOFF_TERMS)
    # Skip/cap only when the story is explicitly gaming/2K/Visual Concepts and not a wrestling-roster layoff.
    return bool(has_gaming_context and has_layoff_context)


def v884_is_health_personal_non_operational(title="", text="", url="", editorial_analysis=None):
    try:
        return v883_is_health_personal_non_operational(title, text, url, editorial_analysis)
    except Exception:
        p = v884_probe(title, url, (text or "")[:2000], (editorial_analysis or {}).get("article_type_reason", ""))
        health = ["rare eye", "eye condition", "ignored symptoms", "patologia oculare", "medical condition", "diagnosed"]
        operational = ["injury", "surgery", "medically cleared", "return", "absence", "in-ring", "match", "calendar", "schedule", "storyline"]
        return any(x in p for x in health) and not any(x in p for x in operational)


def v884_fix_quote_body(body=""):
    s = str(body or "").strip()
    if not s:
        return s
    try:
        soup = BeautifulSoup(s, "html.parser")
        txt = soup.get_text(" ", strip=True)
        if txt and not re.search(r"[.!?…][\"'”’)]*$", txt):
            # Preserve simple plain-quote bodies and avoid touching complex HTML too much.
            if "<" not in s or re.fullmatch(r"[\"'“”‘’\s\w\W]+", s):
                s = re.sub(r"([\"”’)]*)\s*$", r".\1", s)
    except Exception:
        if s and not re.search(r"[.!?…][\"'”’)]*$", s):
            s = re.sub(r"([\"”’)]*)\s*$", r".\1", s)
    return s


def v884_sanitize_inline_blockquotes(html=""):
    if not html:
        return html
    before = html

    def repl(match):
        lead = (match.group(1) or "").strip()
        attrs = match.group(2) or ""
        body = v884_fix_quote_body(match.group(3) or "")
        tail = (match.group(4) or "").strip()
        parts = []
        if lead:
            parts.append(f"<p>{lead}</p>")
        parts.append(f"<blockquote{attrs}>{body}</blockquote>")
        # A bare dot after a blockquote becomes a lonely visual dot in WordPress; drop it.
        if tail and tail not in {".", "&nbsp;", "&#160;"}:
            parts.append(f"<p>{tail}</p>")
        return "".join(parts)

    # Fix invalid HTML generated as <p>intro <blockquote>quote</blockquote>.</p>.
    html = re.sub(r"<p\b[^>]*>(.*?)\s*<blockquote\b([^>]*)>(.*?)</blockquote>\s*([^<]*?)</p>", repl, html, flags=re.I | re.S)
    # Remove paragraphs that contain only punctuation left by quote extraction.
    html = re.sub(r"<p\b[^>]*>\s*[.。]\s*</p>", "", html, flags=re.I)
    # Normalize whitespace around blockquotes.
    html = re.sub(r"</blockquote>\s*<p>\s*([.。])\s*</p>", "</blockquote>", html, flags=re.I)
    if html != before:
        print("[HTML v88.4] Sanitizzate citazioni inline/puntini orfani")
    return html


def v884_embed_key(url=""):
    try:
        if "v872_embed_key" in globals():
            return v872_embed_key(url or "")
        if "canonical_social_key" in globals():
            return canonical_social_key(url or "")
    except Exception:
        pass
    return re.sub(r"\W+", "", str(url or "").lower())


def v884_gallery_credit_embed_keys(html=""):
    keys = set()
    if not html:
        return keys
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        for a in soup.find_all("a"):
            cls = " ".join(a.get("class") or [])
            href = a.get("href") or ""
            if "gallery-image-credit" not in cls:
                continue
            if not re.search(r"(?:x\.com|twitter\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com)", href, re.I):
                continue
            key = v884_embed_key(href)
            if key:
                keys.add(key)
    except Exception as e:
        print(f"[MEDIA v88.4] Lettura credit embed fallita: {e}")
    return keys


if V884_QUALITY_MICROFIXES_ENABLED and "v883_apply_quality_caps" in globals():
    _ORIG_V884_v883_apply_quality_caps = v883_apply_quality_caps
    def v883_apply_quality_caps(score, reasons, title="", text="", url="", editorial_analysis=None, stage=""):
        score_i, reasons = _ORIG_V884_v883_apply_quality_caps(score, reasons, title, text, url, editorial_analysis, stage)
        try:
            current = int(score_i or 0)
        except Exception:
            current = 0
        reasons = list(reasons or [])
        if v884_is_gaming_soft_non_news(title, text, url, editorial_analysis) and current > V884_GAMING_CAP:
            label = f"v88.4 cap gaming/2K non-news {current}->{V884_GAMING_CAP}"
            print(f"[SCORE v88.4] {label} - {title}")
            reasons.append(label)
            current = V884_GAMING_CAP
        if v884_is_health_personal_non_operational(title, text, url, editorial_analysis) and current > V884_HEALTH_PERSONAL_CAP:
            label = f"v88.4 cap salute/personale non operativo {current}->{V884_HEALTH_PERSONAL_CAP}"
            print(f"[SCORE v88.4] {label} - {title}")
            reasons.append(label)
            current = V884_HEALTH_PERSONAL_CAP
        return current, reasons


if V884_SOFT_GAMING_SKIP_ENABLED and "process_candidate_item" in globals():
    _ORIG_V884_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        try:
            title = (item or {}).get("title", "")
            url = (item or {}).get("url", "")
            summary = (item or {}).get("summary", "") or (item or {}).get("description", "") or (item or {}).get("prefetched_text", "")
            if v884_is_gaming_soft_non_news(title, summary, url, None):
                print(f"[SKIP v88.4] Gaming/WWE 2K non-news esclusa: {title}")
                return "skipped"
        except Exception as e:
            print(f"[WARN v88.4] Gaming pre-guard warning: {e}")
        return _ORIG_V884_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)


if V884_REPORT_CREDIT_EMBED_GUARD_ENABLED and "v88_media_record" in globals():
    _ORIG_V884_v88_media_record = v88_media_record
    def v88_media_record(url="", html="", embed_urls=None, inline_images=None, featured_url=""):
        rec = _ORIG_V884_v88_media_record(url=url, html=html, embed_urls=embed_urls, inline_images=inline_images, featured_url=featured_url)
        try:
            credit_keys = v884_gallery_credit_embed_keys(html or "")
            if credit_keys and isinstance(rec, dict):
                old_embeds = list(rec.get("embeds") or [])
                old_meta = list(rec.get("embed_meta") or [])
                new_embeds = [u for u in old_embeds if v884_embed_key(u) not in credit_keys]
                new_meta = [m for m in old_meta if v884_embed_key((m or {}).get("url", "")) not in credit_keys]
                removed = (len(old_embeds) - len(new_embeds)) + (len(old_meta) - len(new_meta))
                if removed:
                    rec = dict(rec)
                    rec["embeds"] = new_embeds
                    rec["embed_meta"] = new_meta
                    if url:
                        _V88_MEDIA_BY_URL[url] = rec
                    if url and "V873_EXPECTED_EMBEDS_BY_URL" in globals():
                        V873_EXPECTED_EMBEDS_BY_URL[url] = new_meta
                    print(f"[MEDIA v88.4] Rimossi embed derivati da credit immagine gallery: {removed} url={url}")
        except Exception as e:
            print(f"[MEDIA v88.4] Credit embed guard warning: {e}")
        return rec


if V884_BLOCKQUOTE_SANITIZER_ENABLED and "create_post_without_image" in globals():
    _ORIG_V884_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        if isinstance(data, dict) and data.get("testo"):
            data = dict(data)
            data["testo"] = v884_sanitize_inline_blockquotes(data.get("testo", ""))
            try:
                if v883_is_report_context(sem_id=sem_id, event_key=event_key, title=data.get("titolo") or data.get("title") or "", url=url, data=data):
                    data["testo"] = v883_remove_orphan_tail_report_images(data.get("testo", ""))
            except Exception:
                pass
        return _ORIG_V884_create_post_without_image(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)

try:
    print("[BOOT v88.4] Quality microfixes attive: quote sanitizer, report credit media guard, gaming/health caps")
except Exception:
    pass
'''


def main():
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if "v88.4: quality microfixes for quotes" in text:
        print("[SOURCE PATCH v88.4] bot.py gia aggiornato")
        return False
    marker = "# =========================\n# Runtime entrypoint"
    idx = text.rfind(marker)
    if idx < 0:
        idx = text.rfind('if __name__ == "__main__"')
    if idx < 0:
        raise SystemExit("runtime entrypoint marker not found")
    path.write_text(text[:idx] + PATCH + "\n\n" + text[idx:], encoding="utf-8")
    print("[SOURCE PATCH v88.4] patch scritta direttamente in bot.py")
    return True


if __name__ == "__main__":
    main()
    raise SystemExit(0)
