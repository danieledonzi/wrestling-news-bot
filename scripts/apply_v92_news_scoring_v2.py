from pathlib import Path

# -----------------------------------------------------------------------------
# Patch modules/news_workshop_v92.py: add editorial analysis + HTML cleanup.
# -----------------------------------------------------------------------------
news_path = Path("modules/news_workshop_v92.py")
news = news_path.read_text(encoding="utf-8")

if "V92_NEWS_SCORING_V2_WORKSHOP = True" not in news:
    news = news.replace(
        "HEADERS = {\n",
        "V92_NEWS_SCORING_V2_WORKSHOP = True\nHEADERS = {\n",
        1,
    )

    analyze_helper = r'''

def analyze_news_editorial(source_title: str, summary: str, source: str, url: str, local_score: int, local_reason: str) -> Dict[str, Any]:
    """Light editorial analysis for v92 news scoring.

    Gemini returns semantic fields; the final score is still computed in bot_v92.py.
    """
    prompt = f"""
Sei un editor italiano esperto di wrestling. Devi valutare se una news merita pubblicazione su OpenWrestlingTV.
Non devi tradurre l'articolo. Devi solo classificarlo editorialmente.

Classi ammesse:
- hard_news: sviluppo concreto, urgente o rilevante
- event_outcome: risultato/evento autonomo rilevante, non report completo
- strategic_discussion: business, TV deal, WWE/AEW/TKO, problemi organizzativi, direzione creativa rilevante
- standard_useful: intervista o dettaglio utile ma non urgente
- soft_news: curiosità o dichiarazione interessante ma leggera
- opinion: opinione/commentary/listicle
- report_like: report/results/recap show, da non trattare come news normale
- low_value: contenuto debole, marginale, evergreen o non adatto

Restituisci SOLO JSON valido:
{{
  "article_type": "hard_news | event_outcome | strategic_discussion | standard_useful | soft_news | opinion | report_like | low_value",
  "priority": "hard | soft | skip",
  "category": "WWE | AEW | NXT | TNA | World | Business",
  "main_entities": ["..."],
  "story_core": "slug-breve-del-nucleo-notizia",
  "news_action": "azione_narrativa_breve",
  "freshness": "fresh | stale | evergreen",
  "editorial_notes": "motivo sintetico"
}}

Criteri:
- hard solo se c'e' uno sviluppo concreto o molto rilevante.
- soft per interviste, curiosita' backstage, dichiarazioni interessanti ma non decisive.
- skip per report/results/recap, listicle leggero, opinione senza fatto nuovo, rumor troppo vago, contenuto marginale.
- Non penalizzare automaticamente una news solo perche' parla dello stesso personaggio di altre.

Fonte: {source_label(source)}
URL: {url}
Titolo: {source_title}
Summary feed: {summary}
Pre-score locale: {local_score}/100
Motivo pre-score: {local_reason}
""".strip()
    raw, model = gemini_generate(prompt, purpose="news_editorial_analysis")
    data = extract_json(raw)
    data["analysis_model"] = model
    return data


def cleanup_news_html(body_html: str) -> str:
    """Normalize Gemini HTML before publishing.

    In particular, prevent blockquotes from being nested inside paragraphs.
    """
    html = str(body_html or "").strip()
    if not html:
        return html
    # Common malformed pattern: <p>text <blockquote>quote</blockquote></p>
    html = re.sub(
        r"<p>([^<]*?)\s*<blockquote>(.*?)</blockquote>\s*</p>",
        lambda m: (f"<p>{m.group(1).strip()}</p>" if m.group(1).strip() else "") + f"<blockquote>{m.group(2).strip()}</blockquote>",
        html,
        flags=re.I | re.S,
    )
    # If there are still blockquotes inside p tags, split conservatively.
    html = re.sub(r"<p>\s*(<blockquote>.*?</blockquote>)\s*</p>", r"\1", html, flags=re.I | re.S)
    html = re.sub(r"</blockquote>\s*</p>", "</blockquote>", html, flags=re.I)
    html = re.sub(r"<p>\s*<blockquote>", "<blockquote>", html, flags=re.I)
    return html
'''

    insert_anchor = "\n\ndef translate_news(source_title: str, source_text: str, source: str) -> Tuple[str, str, str]:\n"
    if "def analyze_news_editorial" not in news and insert_anchor in news:
        news = news.replace(insert_anchor, analyze_helper + insert_anchor, 1)

    old = '''    body = str(data.get("body_html") or "").strip()
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
    new = '''    body = cleanup_news_html(str(data.get("body_html") or "").strip())
    if not body:
        raise RuntimeError("Gemini non ha restituito body_html")
    return title, body, model
'''
    if old in news:
        news = news.replace(old, new, 1)

    # Safety net before publish, in case body_html comes from future paths.
    old_publish = '''    payload: Dict[str, Any] = {
        "title": translated_title,
        "content": append_source(body_html, str(job.get("source") or ""), str(job.get("source_url") or "")),
'''
    new_publish = '''    body_html = cleanup_news_html(body_html)
    payload: Dict[str, Any] = {
        "title": translated_title,
        "content": append_source(body_html, str(job.get("source") or ""), str(job.get("source_url") or "")),
'''
    if old_publish in news:
        news = news.replace(old_publish, new_publish, 1)

news_path.write_text(news, encoding="utf-8")
print("[V92 NEWS V2] workshop analysis/html cleanup applicati")

# -----------------------------------------------------------------------------
# Patch bot_v92.py: replace v1 news scoring with hard/soft architecture.
# -----------------------------------------------------------------------------
bot_path = Path("bot_v92.py")
text = bot_path.read_text(encoding="utf-8")

if "V92_NEWS_SCORING_V2_ACTIVE = True" in text:
    print("[V92 NEWS V2] bot gia applicato")
    raise SystemExit(0)

# Imports.
text = text.replace(
    "from modules.news_workshop_v92 import run_news_workshop\n",
    "from modules.news_workshop_v92 import analyze_news_editorial, run_news_workshop\n",
    1,
)

# Constants/state files.
text = text.replace(
    'PUBLISHED_NEWS_FILE = STATE_DIR / "published_news.json"\nV92_NEWS_PIPELINE_ACTIVE = True\n',
    'PUBLISHED_NEWS_FILE = STATE_DIR / "published_news.json"\nNEWS_HARD_SKIPS_FILE = STATE_DIR / "news_hard_skips.json"\nNEWS_SOFT_POOL_FILE = STATE_DIR / "news_soft_pool.json"\nV92_NEWS_PIPELINE_ACTIVE = True\nV92_NEWS_SCORING_V2_ACTIVE = True\n',
    1,
)

# Replace helper block from old v1 patch.
start = text.find("def is_report_like_news(entry: Dict[str, Any]) -> bool:")
end = text.find("\n\ndef run_news_pipeline(wp_ok: bool, now: datetime) -> int:", start)
if start == -1 or end == -1:
    raise SystemExit("[V92 NEWS V2] helper block not found")

helper = r'''
def is_report_like_news(entry: Dict[str, Any]) -> bool:
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('url', '')}")
    hard = [
        "results", "result", "risultati", "live coverage", "coverage", "play by play",
        "things we hated", "things we loved", "draws duds", "review", "recap",
    ]
    show_terms = ["raw", "smackdown", "nxt", "dynamite", "collision", "rampage"]
    return any(x in blob for x in hard) and any(x in blob for x in show_terms)


def news_category_for_entry(entry: Dict[str, Any], analysis: Optional[Dict[str, Any]] = None) -> List[str]:
    if analysis:
        cat = str(analysis.get("category") or "").strip()
        if cat in {"WWE", "AEW", "NXT", "TNA", "World"}:
            return [cat]
        if cat == "Business":
            return ["World"]
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('summary', '')} {entry.get('url', '')}")
    if "nxt" in blob:
        return ["NXT"]
    if "aew" in blob or "dynamite" in blob or "collision" in blob:
        return ["AEW"]
    if "tna" in blob or "impact" in blob:
        return ["TNA"]
    if "wwe" in blob or "raw" in blob or "smackdown" in blob or "roman reigns" in blob or "cody rhodes" in blob:
        return ["WWE"]
    return ["World"]


def mark_hard_skip(hard_skips: Dict[str, Any], entry: Dict[str, Any], reason: str, stage: str, score: Optional[int] = None) -> None:
    url = str(entry.get("url") or "").strip()
    if not url:
        return
    hard_skips[url] = {
        "reason": reason,
        "stage": stage,
        "score": score,
        "title": entry.get("title"),
        "source": entry.get("source"),
        "created_at": utcnow().isoformat(),
    }


def local_pre_score_news(entry: Dict[str, Any]) -> Dict[str, Any]:
    title = normalize_text(entry.get("title", ""))
    summary = normalize_text(entry.get("summary", ""))
    url = normalize_text(entry.get("url", ""))
    blob = f"{title} {summary} {url}"
    score = 20
    reasons: List[str] = []

    hard_signals = {
        "death": 30, "died": 30, "passes away": 30,
        "arrested": 28, "lawsuit": 24, "legal": 16,
        "injury": 22, "injured": 22, "concussion": 22, "surgery": 20,
        "released": 24, "fired": 24, "departs": 18, "exit": 14,
        "returns": 20, "return": 18, "debut": 20, "signs": 18, "contract": 18,
        "champion": 16, "championship": 14, "title": 10,
        "acquisition": 24, "ownership": 24, "tv deal": 22, "media rights": 22,
        "netflix": 16, "espn": 14, "tko": 16,
    }
    strategic_signals = {
        "wwe": 8, "aew": 8, "nxt": 6, "tna": 6,
        "roman reigns": 12, "cody rhodes": 12, "cm punk": 12, "the rock": 12,
        "john cena": 10, "randy orton": 10, "seth rollins": 10, "rhea ripley": 10,
        "backstage": 8, "creative": 8, "plans": 8, "reportedly": 8, "rumor": 6,
    }
    soft_penalties = {
        "possibility": -8, "possible": -6, "discusses": -6, "addresses": -4,
        "reflects": -8, "reaction": -8, "reacts": -8, "social media": -8,
        "photo": -10, "photos": -10, "jokes": -10, "joke": -10,
        "biggest winners and losers": -22, "things we hated": -30, "things we loved": -30,
        "preview": -18, "fan fest": -10,
    }
    for term, pts in hard_signals.items():
        if term in blob:
            score += pts
            reasons.append(f"+{pts}:{term}")
    for term, pts in strategic_signals.items():
        if term in blob:
            score += pts
            reasons.append(f"+{pts}:{term}")
    for term, pts in soft_penalties.items():
        if term in blob:
            score += pts
            reasons.append(f"{pts}:{term}")
    if len(title) > 20:
        score += 5
    if len(summary) > 80:
        score += 5
    if is_report_like_news(entry):
        return {"score": 0, "lane": "hard_skip", "reason": "report_like"}
    score = max(0, min(score, 100))
    if score <= 14:
        lane = "hard_skip"
    elif score < 30:
        lane = "low_soft"
    else:
        lane = "candidate_b"
    return {"score": score, "lane": lane, "reason": ",".join(reasons[:8]) or "local_baseline"}


def score_editorial_analysis(entry: Dict[str, Any], analysis: Dict[str, Any], local_score: int) -> int:
    article_type = str(analysis.get("article_type") or "low_value").strip()
    base_by_type = {
        "hard_news": 70,
        "event_outcome": 68,
        "strategic_discussion": 62,
        "standard_useful": 52,
        "soft_news": 45,
        "opinion": 35,
        "low_value": 20,
        "report_like": 0,
    }
    score = base_by_type.get(article_type, 20)
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('summary', '')} {analysis.get('editorial_notes', '')} {analysis.get('news_action', '')}")
    bonuses = [
        (20, ["death", "died", "passes away", "arrested", "lawsuit"]),
        (18, ["injury", "injured", "concussion", "released", "fired", "departs"]),
        (16, ["return", "returns", "debut", "signs", "contract", "new champion", "title change"]),
        (14, ["acquisition", "ownership", "tv deal", "media rights", "netflix", "espn", "tko"]),
        (12, ["storyline", "creative", "plans", "backstage report"]),
        (10, ["rumor", "reportedly", "confirmed", "update"]),
        (8, ["roman reigns", "cody rhodes", "cm punk", "the rock", "john cena", "randy orton", "rhea ripley"]),
    ]
    penalties = [
        (-30, ["report_like", "results", "recap", "things we hated", "things we loved"]),
        (-20, ["preview", "stale"]),
        (-18, ["generic quote", "quote generica", "podcast"]),
        (-15, ["social reaction", "reacts", "reaction", "listicle"]),
        (-12, ["photo", "lifestyle", "curiosity", "curiosita"]),
        (-8, ["possibility", "possible", "addresses whether", "may still"]),
    ]
    for pts, terms in bonuses:
        if any(t in blob for t in terms):
            score += pts
    for pts, terms in penalties:
        if any(t in blob for t in terms):
            score += pts
    # Local score is a weak prior, not the final decision.
    score += max(-5, min(8, int((local_score - 50) / 6)))
    return max(0, min(int(score), 100))


def priority_from_score(score: int, article_type: str) -> str:
    if article_type in {"report_like", "low_value"}:
        return "skip"
    if score >= 75:
        return "hard"
    if score >= 50:
        return "soft"
    return "skip"


def parse_dt_or_now(value: str) -> datetime:
    try:
        dt = parsedate_to_datetime(value or "")
        if dt.tzinfo is not None:
            dt = dt.astimezone(ROME_TZ).replace(tzinfo=None)
        return dt
    except Exception:
        return now_local_naive()


def soft_pool_ttl_hours(item: Dict[str, Any]) -> int:
    article_type = str(item.get("article_type") or "")
    if article_type == "hard_news":
        return 12
    if "post_show" in str(item.get("news_action") or ""):
        return 3
    if str(item.get("freshness") or "") == "evergreen":
        return 12
    return 6


def hydrate_soft_pool(soft_pool: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
    active: List[Dict[str, Any]] = []
    expired: List[str] = []
    for url, item in soft_pool.items():
        expires = item.get("expires_at")
        try:
            exp = datetime.fromisoformat(expires) if expires else now
        except Exception:
            exp = now
        if exp < now:
            expired.append(url)
            continue
        active.append(dict(item))
    for url in expired:
        soft_pool.pop(url, None)
    return active


def store_soft_candidate(soft_pool: Dict[str, Any], item: Dict[str, Any], now: datetime) -> None:
    url = str(item.get("url") or item.get("source_url") or "")
    if not url:
        return
    ttl = soft_pool_ttl_hours(item)
    existing = soft_pool.get(url, {})
    first_seen = existing.get("first_seen") or utcnow().isoformat()
    soft_pool[url] = {
        **item,
        "url": url,
        "first_seen": first_seen,
        "last_seen": utcnow().isoformat(),
        "expires_at": (now + timedelta(hours=ttl)).isoformat(),
    }


def build_news_candidate(entry: Dict[str, Any], analysis: Dict[str, Any], final_score: int, priority: str, local: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **entry,
        "score": final_score,
        "priority": priority,
        "article_type": analysis.get("article_type"),
        "category": analysis.get("category"),
        "main_entities": analysis.get("main_entities") or [],
        "story_core": analysis.get("story_core") or slugify(str(entry.get("title") or "")),
        "news_action": analysis.get("news_action"),
        "freshness": analysis.get("freshness"),
        "editorial_notes": analysis.get("editorial_notes"),
        "analysis_model": analysis.get("analysis_model"),
        "local_score": local.get("score"),
        "local_reason": local.get("reason"),
    }


def select_news_final(hard_items: List[Dict[str, Any]], soft_items: List[Dict[str, Any]], limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    hard_items = sorted(hard_items, key=lambda e: (int(e.get("score") or 0), str(e.get("published") or "")), reverse=True)
    soft_items = sorted(soft_items, key=lambda e: (int(e.get("score") or 0), str(e.get("last_seen") or e.get("published") or "")), reverse=True)
    if len(hard_items) >= limit:
        chosen = hard_items[:limit]
    else:
        chosen = hard_items + soft_items[: max(0, limit - len(hard_items))]
    chosen_urls = {str(x.get("url") or x.get("source_url") or "") for x in chosen}
    remaining_soft = [x for x in soft_items if str(x.get("url") or x.get("source_url") or "") not in chosen_urls]
    return chosen, remaining_soft
'''
text = text[:start] + helper + text[end:]

# Replace run_news_pipeline.
start = text.find("def run_news_pipeline(wp_ok: bool, now: datetime) -> int:")
end = text.find("\n\ndef main() -> int:", start)
if start == -1 or end == -1:
    raise SystemExit("[V92 NEWS V2] run_news_pipeline not found")

run_func = r'''def run_news_pipeline(wp_ok: bool, now: datetime) -> int:
    if not wp_ok:
        log("[NEWS v92] WordPress non disponibile: skip news")
        return 0

    feeds_cfg = load_json(FEEDS_CONFIG, {"feeds": []})
    published_urls = load_json(PUBLISHED_NEWS_FILE, {})
    hard_skips = load_json(NEWS_HARD_SKIPS_FILE, {})
    soft_pool = load_json(NEWS_SOFT_POOL_FILE, {})
    pending: List[Dict[str, Any]] = []

    entries = feed_entries(feeds_cfg.get("feeds", []))
    hard_items: List[Dict[str, Any]] = []
    soft_items: List[Dict[str, Any]] = hydrate_soft_pool(soft_pool, now)
    seen: set[str] = set()

    for entry in entries:
        url = str(entry.get("url") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not url or not title:
            continue
        if url in seen:
            continue
        seen.add(url)
        if url in published_urls:
            continue
        if url in hard_skips:
            continue

        if is_report_like_news(entry):
            log(f"[NEWS v92] Hard skip deterministic report-like: {title}")
            mark_hard_skip(hard_skips, entry, "report_like", "deterministic", 0)
            continue

        local = local_pre_score_news(entry)
        local_score = int(local.get("score") or 0)
        if local.get("lane") == "hard_skip":
            log(f"[NEWS v92] Hard skip Fase A ({local_score}/100): {title} | {local.get('reason')}")
            mark_hard_skip(hard_skips, entry, str(local.get("reason") or "local_hard_skip"), "phase_a", local_score)
            continue
        if local.get("lane") == "low_soft":
            log(f"[NEWS v92] Low-soft Fase A ({local_score}/100): {title} | non mando a Gemini")
            low_item = build_news_candidate(
                entry,
                {"article_type": "soft_news", "priority": "soft", "category": news_category_for_entry(entry)[0], "story_core": slugify(title), "freshness": "fresh", "editorial_notes": "low_soft_phase_a"},
                max(40, min(local_score + 15, 49)),
                "soft",
                local,
            )
            store_soft_candidate(soft_pool, low_item, now)
            continue

        try:
            analysis = analyze_news_editorial(
                str(entry.get("title") or ""),
                str(entry.get("summary") or ""),
                str(entry.get("source") or ""),
                url,
                local_score,
                str(local.get("reason") or ""),
            )
        except Exception as exc:
            log(f"[NEWS v92] Analisi editoriale fallita, uso fallback locale: {title} | {exc}")
            analysis = {
                "article_type": "standard_useful" if local_score >= 50 else "soft_news",
                "priority": "soft",
                "category": news_category_for_entry(entry)[0],
                "main_entities": [],
                "story_core": slugify(title),
                "news_action": "local_fallback",
                "freshness": "fresh",
                "editorial_notes": "fallback_local_analysis",
            }

        article_type = str(analysis.get("article_type") or "low_value")
        final_score = score_editorial_analysis(entry, analysis, local_score)
        priority = priority_from_score(final_score, article_type)
        candidate = build_news_candidate(entry, analysis, final_score, priority, local)

        if priority == "skip":
            log(f"[NEWS v92] Hard skip Fase B ({final_score}/100 {article_type}): {title} | {analysis.get('editorial_notes')}")
            mark_hard_skip(hard_skips, entry, f"phase_b_{article_type}", "phase_b", final_score)
            continue
        if priority == "hard":
            log(f"[NEWS v92] Hard news Fase B ({final_score}/100 {article_type}): {title}")
            hard_items.append(candidate)
        else:
            log(f"[NEWS v92] Soft pool Fase B ({final_score}/100 {article_type}): {title}")
            soft_items.append(candidate)
            store_soft_candidate(soft_pool, candidate, now)

    chosen, remaining_soft = select_news_final(hard_items, soft_items, MAX_NEWS_PER_RUN)
    chosen_urls = {str(x.get("url") or x.get("source_url") or "") for x in chosen}
    for item in remaining_soft:
        store_soft_candidate(soft_pool, item, now)
    for url in list(soft_pool.keys()):
        if url in chosen_urls or url in published_urls:
            soft_pool.pop(url, None)

    published = 0
    for entry in chosen:
        url = str(entry.get("url") or entry.get("source_url") or "")
        if not url or url in published_urls:
            continue
        key = f"news:{slugify(url)}"
        categories = news_category_for_entry(entry, entry)
        job = {
            "kind": "news",
            "news_key": key,
            "source": entry.get("source"),
            "source_url": url,
            "source_title": entry.get("title"),
            "categories": categories,
            "score": entry.get("score"),
            "priority": entry.get("priority"),
            "article_type": entry.get("article_type"),
            "story_core": entry.get("story_core"),
            "created_at": utcnow().isoformat(),
        }
        try:
            log(f"[NEWS v92] Pubblico {job['priority']} score={job['score']}/100 type={job['article_type']} source={job['source']} title={job['source_title']}")
            post_id, post_json = run_news_workshop(job, PUBLISHED_DIR, REVIEW_DIR)
            published_urls[url] = {
                "status": "published",
                "wp_post_id": post_id,
                "source": job["source"],
                "source_title": job["source_title"],
                "categories": categories,
                "score": job["score"],
                "priority": job["priority"],
                "article_type": job["article_type"],
                "story_core": job["story_core"],
                "published_at": utcnow().isoformat(),
                "link": post_json.get("link"),
            }
            soft_pool.pop(url, None)
            published += 1
        except Exception as exc:
            log(f"[NEWS v92] Errore pubblicazione news: {job['source_title']} | {exc}")
            pending.append({**job, "status": "failed_technical", "error": str(exc)[:1000]})
            continue

    save_json(PUBLISHED_NEWS_FILE, published_urls)
    save_json(NEWS_HARD_SKIPS_FILE, hard_skips)
    save_json(NEWS_SOFT_POOL_FILE, soft_pool)
    save_json(PENDING_NEWS_FILE, pending)
    log(f"[NEWS v92] Pubblicate news={published}/{MAX_NEWS_PER_RUN} | hard_candidates={len(hard_items)} soft_candidates={len(soft_items)} soft_pool_saved={len(soft_pool)}")
    return published
'''
text = text[:start] + run_func + text[end:]

bot_path.write_text(text, encoding="utf-8")
print("[V92 NEWS V2] scoring hard/soft pipeline applicata")
