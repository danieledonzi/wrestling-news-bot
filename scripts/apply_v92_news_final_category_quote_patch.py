from pathlib import Path

# -----------------------------------------------------------------------------
# v92 final category + quote cleanup patch.
# Observed:
# - Cody/GUNTHER style articles can still reach publish with Business category.
# - Gemini sometimes places a stray period after quote/blockquotes.
# - Some direct quotes are emitted as normal paragraphs instead of blockquotes.
#
# Fix:
# - add a final category normalizer immediately before run_news_workshop;
# - force event_outcome/storyline/match items out of Business unless there is a
#   real corporate/media-rights context;
# - clean quote punctuation and convert standalone quoted paragraphs to blockquote.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# bot_v92.py final category normalization.
# -----------------------------------------------------------------------------
bot_path = Path("bot_v92.py")
s = bot_path.read_text(encoding="utf-8")

if "V92_NEWS_FINAL_CATEGORY_QUOTE_PATCH_ACTIVE = True" not in s:
    marker = "V92_NEWS_CATEGORY_EVENT_FIX_ACTIVE = True\n"
    if marker in s:
        s = s.replace(marker, marker + "V92_NEWS_FINAL_CATEGORY_QUOTE_PATCH_ACTIVE = True\n", 1)
    else:
        s = s.replace("V92_NEWS_DEDUPE_PLACEHOLDER_ACTIVE = True\n", "V92_NEWS_DEDUPE_PLACEHOLDER_ACTIVE = True\nV92_NEWS_FINAL_CATEGORY_QUOTE_PATCH_ACTIVE = True\n", 1)

if "def final_news_categories_for_publish" not in s:
    insert_at = s.find("\n\ndef select_news_final")
    helpers = r'''

def final_news_categories_for_publish(entry: Dict[str, Any]) -> List[str]:
    """Last safety net before WordPress publish.

    Business must mean corporate/business, not a match/storyline/show item with
    ESPN/Netflix mentioned as broadcast context. Event outcomes always resolve to
    the relevant promotion unless a real corporate context is present.
    """
    raw_categories = list(entry.get("categories") or [])
    article_type = str(entry.get("article_type") or "")
    blob = f"{entry.get('title', '')} {entry.get('source_title', '')} {entry.get('summary', '')} {entry.get('story_core', '')} {entry.get('news_action', '')} {entry.get('editorial_notes', '')} {entry.get('url', '')}"
    promo = promo_category_from_blob(blob) if "promo_category_from_blob" in globals() else news_category_for_entry(entry, entry)[0]

    match_or_story_context = any(term in normalize_text(blob) for term in [
        "match", "title", "championship", "smackdown", "raw", "nxt", "dynamite", "collision",
        "impact", "king of the ring", "queen of the ring", "gunther", "cody rhodes", "sami zayn",
        "rhea ripley", "finisher", "riptide", "walks out", "declares", "tournament",
    ])
    corporate = real_business_context(entry, entry) if "real_business_context" in globals() else has_business_signal(entry, entry)

    if article_type == "event_outcome":
        return [promo]
    if "Business" in raw_categories and not corporate:
        log(f"[NEWS v92] Category safety override: Business -> {promo} | title={entry.get('title') or entry.get('source_title')}")
        return [promo]
    if "Business" in raw_categories and match_or_story_context and not corporate:
        log(f"[NEWS v92] Category safety override match/story: Business -> {promo} | title={entry.get('title') or entry.get('source_title')}")
        return [promo]
    if raw_categories:
        return raw_categories
    return news_category_for_entry(entry, entry)
'''
    if insert_at != -1:
        s = s[:insert_at] + helpers + s[insert_at:]
    else:
        print("[V92 FINAL CATEGORY] select_news_final anchor non trovato")

old = '''        categories = news_category_for_entry(entry, entry)
        job = {
'''
new = '''        categories = final_news_categories_for_publish(entry)
        job = {
'''
if old in s:
    s = s.replace(old, new, 1)
else:
    print("[V92 FINAL CATEGORY] publish categories anchor non trovato")

bot_path.write_text(s, encoding="utf-8")
print("[V92 FINAL CATEGORY] final category normalizer applicato")

# -----------------------------------------------------------------------------
# modules/news_workshop_v92.py quote cleanup.
# -----------------------------------------------------------------------------
news_path = Path("modules/news_workshop_v92.py")
news = news_path.read_text(encoding="utf-8")

if "V92_NEWS_QUOTE_CLEANUP_PATCH = True" not in news:
    # Put marker after media cache flags if possible.
    if "V92_NEWS_PLACEHOLDER_CLEANUP_PATCH = True\n" in news:
        news = news.replace("V92_NEWS_PLACEHOLDER_CLEANUP_PATCH = True\n", "V92_NEWS_PLACEHOLDER_CLEANUP_PATCH = True\nV92_NEWS_QUOTE_CLEANUP_PATCH = True\n", 1)
    elif "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n" in news:
        news = news.replace("_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n", "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_NEWS_QUOTE_CLEANUP_PATCH = True\n", 1)

if "def cleanup_news_quotes" not in news:
    marker = "\n\ndef publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:\n"
    helper = r'''

def cleanup_news_quotes(body_html: str) -> str:
    out = body_html or ""
    before = out

    # No punctuation after a closed blockquote generated by Gemini.
    out = re.sub(r"(</blockquote>)\s*[\.]", r"\1", out, flags=re.I)
    out = re.sub(r"(</figure>)\s*[\.]", r"\1", out, flags=re.I)

    # Remove stray period after a closing quote before paragraph/block closing.
    out = re.sub(r"([”\"])\s*\.\s*(</p>)", r"\1\2", out, flags=re.I)

    # Convert standalone quoted paragraphs into blockquotes. This intentionally
    # targets only paragraphs that start and end with quotes, so normal prose with
    # partial quoted phrases remains untouched.
    def convert_quoted_paragraph(match):
        inner = match.group(1).strip()
        plain = re.sub(r"<[^>]+>", "", inner).strip()
        if len(plain) < 35:
            return match.group(0)
        if not re.match(r"^[\"“].*[\"”]$", plain, flags=re.S):
            return match.group(0)
        return f"<blockquote><p>{inner}</p></blockquote>"

    out = re.sub(r"<p>\s*((?:[\"“])[^<]{35,}(?:[\"”]))\s*</p>", convert_quoted_paragraph, out, flags=re.I | re.S)

    # Clean accidental empty paragraphs after conversions.
    out = re.sub(r"<p>\s*</p>", "", out, flags=re.I)
    if out != before:
        print("[NEWS v92] Quote cleanup applicato", flush=True)
    return out.strip()
'''
    if marker in news:
        news = news.replace(marker, helper + marker, 1)
    else:
        print("[V92 QUOTE CLEANUP] publish_news marker non trovato")

# Strengthen prompt when the anchor exists.
prompt_anchor = "- Mantieni tutte le citazioni attribuite: se nel testo originale ci sono virgolette o dichiarazioni, riportale in italiano in modo fedele.\n"
prompt_add = "- Le citazioni dirette lunghe o isolate devono essere in <blockquote>, non in un normale <p>. Non aggiungere un punto dopo la chiusura della citazione o del blockquote.\n"
if prompt_anchor in news and prompt_add not in news:
    news = news.replace(prompt_anchor, prompt_anchor + prompt_add, 1)

# Apply cleanup in translate return if possible.
old1 = '''    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
new1 = '''    body = cleanup_news_quotes(body)
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
if old1 in news and new1 not in news:
    news = news.replace(old1, new1, 1)
else:
    print("[V92 QUOTE CLEANUP] translate return anchor non trovato o gia modificato")

# Apply cleanup at publish boundary as final safety net.
old2 = '''def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
'''
new2 = '''def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    body_html = cleanup_news_quotes(body_html)
'''
if old2 in news and new2 not in news:
    news = news.replace(old2, new2, 1)
else:
    print("[V92 QUOTE CLEANUP] publish_news cleanup anchor non trovato o gia applicato")

news_path.write_text(news, encoding="utf-8")
print("[V92 QUOTE CLEANUP] quote formatting cleanup applicato")
