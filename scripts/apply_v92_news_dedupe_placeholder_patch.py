from pathlib import Path

# -----------------------------------------------------------------------------
# v92 news dedupe + placeholder cleanup patch.
# Problems observed:
# 1) same hard news published twice from WrestlingInc and RingsideNews;
# 2) internal placeholder variants like [OWTV EMBED] reached final article body.
#
# Fixes:
# - semantic cross-source duplicate detection before publication and inside final
#   selection;
# - prefer higher score and, when close, WrestlingInc over RingsideNews;
# - skip future candidates if semantically equivalent to a recently published
#   item;
# - strip any leaked OWTV embed placeholders before writing/publishing HTML.
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# modules/news_workshop_v92.py cleanup.
# -----------------------------------------------------------------------------
news_path = Path("modules/news_workshop_v92.py")
news = news_path.read_text(encoding="utf-8")

if "V92_NEWS_PLACEHOLDER_CLEANUP_PATCH = True" not in news:
    news = news.replace(
        "V92_NEWS_EMBED_HANDLING_PATCH = True\n",
        "V92_NEWS_EMBED_HANDLING_PATCH = True\nV92_NEWS_PLACEHOLDER_CLEANUP_PATCH = True\n",
        1,
    )

if "def strip_internal_placeholders" not in news:
    marker = "\n\ndef inject_news_embeds(body_html: str, embeds: List[Dict[str, str]]) -> str:\n"
    helper = r'''

def strip_internal_placeholders(body_html: str) -> str:
    out = body_html or ""
    before = out
    # Remove exact placeholders and common Gemini-mutated variants.
    patterns = [
        r"\[\[\s*OWTV[_\s-]*EMBED[_\s-]*\d+\s*\]\]",
        r"\[\s*OWTV[_\s-]*EMBED[_\s-]*\d*\s*\]",
        r"OWTV[_\s-]*EMBED[_\s-]*\d+",
        r"\[\[\s*OWTV[_\s-]*EMBED\s*\]\]",
    ]
    for pattern in patterns:
        out = re.sub(pattern, "", out, flags=re.I)
    # Remove empty paragraphs left behind.
    out = re.sub(r"<p>\s*</p>", "", out, flags=re.I)
    out = re.sub(r"\n{3,}", "\n\n", out)
    if before != out:
        print("[NEWS v92] WARNING: rimossi placeholder interni OWTV_EMBED dal corpo finale", flush=True)
    return out.strip()
'''
    if marker in news:
        news = news.replace(marker, helper + marker, 1)
    else:
        print("[V92 NEWS DEDUPE] marker inject_news_embeds non trovato")

# Ensure cleanup after embed injection, before save/publish.
old = '''    body_html = inject_news_embeds(body_html, embeds)
    print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)
'''
new = '''    body_html = inject_news_embeds(body_html, embeds)
    body_html = strip_internal_placeholders(body_html)
    print(f"[NEWS v92] Traduzione completata: modello={model} title={title}", flush=True)
'''
if old in news and new not in news:
    news = news.replace(old, new, 1)
else:
    print("[V92 NEWS DEDUPE] run_news_workshop placeholder cleanup anchor non trovato o gia applicato")

# Also clean at publish boundary as final safety net.
old_publish = '''def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    print(f"[NEWS v92] Publish featured candidate: {image_url}", flush=True)
'''
new_publish = '''def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    body_html = strip_internal_placeholders(body_html)
    print(f"[NEWS v92] Publish featured candidate: {image_url}", flush=True)
'''
if old_publish in news and new_publish not in news:
    news = news.replace(old_publish, new_publish, 1)
else:
    print("[V92 NEWS DEDUPE] publish_news placeholder cleanup anchor non trovato o gia applicato")

news_path.write_text(news, encoding="utf-8")
print("[V92 NEWS DEDUPE] placeholder cleanup applicato")

# -----------------------------------------------------------------------------
# bot_v92.py semantic dedupe.
# -----------------------------------------------------------------------------
bot_path = Path("bot_v92.py")
text = bot_path.read_text(encoding="utf-8")

if "V92_NEWS_DEDUPE_PLACEHOLDER_ACTIVE = True" not in text:
    text = text.replace(
        "V92_BUSINESS_BOUNDARY_PATCH_ACTIVE = True\n",
        "V92_BUSINESS_BOUNDARY_PATCH_ACTIVE = True\nV92_NEWS_DEDUPE_PLACEHOLDER_ACTIVE = True\n",
        1,
    )

# Add helpers before select_news_final.
if "def news_action_bucket" not in text:
    marker = "\n\ndef select_news_final(hard_items: List[Dict[str, Any]], soft_items: List[Dict[str, Any]], limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:\n"
    helpers = r'''

def news_action_bucket(item: Dict[str, Any]) -> str:
    blob = normalize_text(
        f"{item.get('title', '')} {item.get('source_title', '')} {item.get('summary', '')} "
        f"{item.get('story_core', '')} {item.get('news_action', '')} {item.get('editorial_notes', '')}"
    )
    buckets = [
        ("injury", ["injury", "injured", "hurt", "legitimately hurt", "status", "injury concern", "scare"]),
        ("legal", ["lawsuit", "court", "filing", "filings", "legal", "sues", "settlement"]),
        ("arrest", ["arrest", "arrested", "drunk driving", "dui", "charged", "bail"]),
        ("contract", ["contract", "signs", "signed", "free agent", "extension", "deal"]),
        ("return_debut", ["return", "returns", "debut", "debuting", "comeback"]),
        ("card_match", ["set to open", "match set", "announced", "added", "card", "clash", "ple", "ppv"]),
        ("business", ["merger", "acquisition", "ownership", "media rights", "tv deal", "streaming", "netflix", "tko"]),
        ("storyline", ["attack", "attacks", "turns", "walks out", "confronts", "promo"]),
    ]
    for bucket, terms in buckets:
        if any(term in blob for term in terms):
            return bucket
    return "general"


def news_token_set(item: Dict[str, Any]) -> set[str]:
    blob = normalize_text(
        f"{item.get('title', '')} {item.get('source_title', '')} {item.get('summary', '')} {item.get('story_core', '')}"
    )
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "after", "ahead", "before", "during", "over",
        "wwe", "aew", "tna", "nxt", "news", "report", "reportedly", "legitimately", "major", "update",
        "gets", "being", "about", "into", "will", "could", "would", "italy", "clash", "live", "event",
    }
    return {t for t in blob.split() if len(t) >= 3 and t not in stop}


def news_entity_tokens(item: Dict[str, Any]) -> set[str]:
    raw_entities = item.get("main_entities") or []
    entity_blob = normalize_text(" ".join(str(e) for e in raw_entities))
    title_blob = normalize_text(f"{item.get('title', '')} {item.get('source_title', '')}")
    known = [
        "jacob fatu", "sol ruca", "vince mcmahon", "cody rhodes", "sami zayn", "gunther", "brock lesnar",
        "rhea ripley", "john cena", "seth rollins", "roman reigns", "cm punk", "logan paul",
        "kenny omega", "will ospreay", "mjf", "samoa joe", "stephanie vaquer",
    ]
    out: set[str] = set()
    for name in known:
        if name in title_blob or name in entity_blob:
            out.add(name)
    # Also use Gemini entities as normalized tokens when provided.
    for ent in raw_entities:
        ent_norm = normalize_text(str(ent))
        if ent_norm and len(ent_norm) >= 4:
            out.add(ent_norm)
    return out


def news_semantic_duplicate(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    au = str(a.get("url") or a.get("source_url") or "")
    bu = str(b.get("url") or b.get("source_url") or "")
    if au and bu and au == bu:
        return True
    if news_action_bucket(a) != news_action_bucket(b):
        return False
    ae = news_entity_tokens(a)
    be = news_entity_tokens(b)
    if ae and be and not (ae & be):
        return False
    at = news_token_set(a)
    bt = news_token_set(b)
    if not at or not bt:
        return False
    inter = len(at & bt)
    union = len(at | bt)
    sim = inter / max(1, union)
    # Same entity + same action can use a lower token threshold because sources
    # phrase the same story differently.
    if ae & be and sim >= 0.28:
        return True
    return sim >= 0.45


def news_source_rank(source: str) -> int:
    source = str(source or "").lower()
    if source == "wrestlinginc":
        return 3
    if source == "ringsidenews":
        return 2
    return 1


def news_candidate_sort_key(item: Dict[str, Any]) -> Tuple[int, int, str]:
    return (int(item.get("score") or 0), news_source_rank(str(item.get("source") or "")), str(item.get("published") or item.get("last_seen") or ""))


def dedupe_news_candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(items, key=news_candidate_sort_key, reverse=True)
    kept: List[Dict[str, Any]] = []
    for item in ordered:
        duplicate_of = None
        for existing in kept:
            if news_semantic_duplicate(item, existing):
                duplicate_of = existing
                break
        if duplicate_of:
            log(f"[NEWS v92] Skip duplicato semantico cross-source: {item.get('title') or item.get('source_title')} ~= {duplicate_of.get('title') or duplicate_of.get('source_title')}")
            continue
        kept.append(item)
    return kept


def already_published_semantic_duplicate(candidate: Dict[str, Any], published_urls: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for url, item in published_urls.items():
        if not isinstance(item, dict):
            continue
        published_item = {
            "url": url,
            "source_title": item.get("source_title"),
            "title": item.get("source_title"),
            "story_core": item.get("story_core"),
            "article_type": item.get("article_type"),
            "category": (item.get("categories") or [""])[0] if isinstance(item.get("categories"), list) else item.get("categories"),
            "score": item.get("score"),
            "source": item.get("source"),
        }
        if news_semantic_duplicate(candidate, published_item):
            return {**published_item, "url": url}
    return None
'''
    if marker in text:
        text = text.replace(marker, helpers + marker, 1)
    else:
        print("[V92 NEWS DEDUPE] marker select_news_final non trovato")

# Replace select_news_final with deduped version. This runs after quality patch.
start = text.find("def select_news_final(hard_items: List[Dict[str, Any]], soft_items: List[Dict[str, Any]], limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:")
end = text.find("\n\ndef run_news_pipeline", start)
if start != -1 and end != -1:
    new_select = r'''def select_news_final(hard_items: List[Dict[str, Any]], soft_items: List[Dict[str, Any]], limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    hard_items = dedupe_news_candidates(hard_items)
    soft_items = dedupe_news_candidates(soft_items)
    hard_items = sorted(hard_items, key=news_candidate_sort_key, reverse=True)
    soft_items = sorted(soft_items, key=news_candidate_sort_key, reverse=True)
    publishable_hard = [x for x in hard_items if int(x.get("score") or 0) >= V92_MIN_HARD_PUBLISH_SCORE]
    publishable_soft = [x for x in soft_items if int(x.get("score") or 0) >= V92_MIN_SOFT_PUBLISH_SCORE]
    if len(publishable_hard) >= limit:
        chosen = publishable_hard[:limit]
    else:
        chosen = publishable_hard + publishable_soft[: max(0, limit - len(publishable_hard))]
    chosen_urls = {str(x.get("url") or x.get("source_url") or "") for x in chosen}
    remaining_soft = [x for x in soft_items if str(x.get("url") or x.get("source_url") or "") not in chosen_urls]
    return chosen, remaining_soft
'''
    text = text[:start] + new_select + text[end:]
else:
    print("[V92 NEWS DEDUPE] select_news_final block non trovato")

# Add published duplicate check after candidate build and before priority handling.
old = '''        candidate = build_news_candidate(entry, analysis, final_score, priority, local)

        if article_type == "event_outcome" and event_outcome_has_published_report(entry, analysis):
'''
new = '''        candidate = build_news_candidate(entry, analysis, final_score, priority, local)

        existing_duplicate = already_published_semantic_duplicate(candidate, published_urls)
        if existing_duplicate:
            log(f"[NEWS v92] Hard skip duplicato semantico gia pubblicato: {title} ~= {existing_duplicate.get('source_title')}")
            mark_hard_skip(hard_skips, entry, "semantic_duplicate_published", "phase_b", final_score)
            continue

        if article_type == "event_outcome" and event_outcome_has_published_report(entry, analysis):
'''
if old in text:
    text = text.replace(old, new, 1)
else:
    # Fallback for pre-quality-patch shape.
    old2 = '''        candidate = build_news_candidate(entry, analysis, final_score, priority, local)

        if priority == "skip":
'''
    new2 = '''        candidate = build_news_candidate(entry, analysis, final_score, priority, local)

        existing_duplicate = already_published_semantic_duplicate(candidate, published_urls)
        if existing_duplicate:
            log(f"[NEWS v92] Hard skip duplicato semantico gia pubblicato: {title} ~= {existing_duplicate.get('source_title')}")
            mark_hard_skip(hard_skips, entry, "semantic_duplicate_published", "phase_b", final_score)
            continue

        if priority == "skip":
'''
    if old2 in text:
        text = text.replace(old2, new2, 1)
    else:
        print("[V92 NEWS DEDUPE] candidate duplicate anchor non trovato")

bot_path.write_text(text, encoding="utf-8")
print("[V92 NEWS DEDUPE] semantic dedupe applicato")
