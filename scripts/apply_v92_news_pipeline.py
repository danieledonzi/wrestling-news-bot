from pathlib import Path

p = Path("bot_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_NEWS_PIPELINE_ACTIVE = True" in text:
    print("[V92 NEWS] pipeline gia applicata")
    raise SystemExit(0)

text = text.replace('import requests\n', 'import requests\nfrom modules.news_workshop_v92 import run_news_workshop\n', 1)
text = text.replace('CONFIG_DIR = ROOT / "config"\n', 'CONFIG_DIR = ROOT / "config"\nPUBLISHED_DIR = ROOT / "published"\nREVIEW_DIR = ROOT / "published_html_review"\n', 1)
text = text.replace('PENDING_NEWS_FILE = STATE_DIR / "pending_news.json"\n', 'PENDING_NEWS_FILE = STATE_DIR / "pending_news.json"\nPUBLISHED_NEWS_FILE = STATE_DIR / "published_news.json"\nV92_NEWS_PIPELINE_ACTIVE = True\n', 1)
text = text.replace('    LOG_DIR.mkdir(parents=True, exist_ok=True)\n', '    LOG_DIR.mkdir(parents=True, exist_ok=True)\n    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)\n    REVIEW_DIR.mkdir(parents=True, exist_ok=True)\n', 1)

helper = r'''

def is_report_like_news(entry: Dict[str, Any]) -> bool:
    blob = normalize_text(f"{entry.get('title', '')} {entry.get('url', '')}")
    hard = [
        "results", "result", "risultati", "live coverage", "coverage", "play by play",
        "things we hated", "things we loved", "draws duds", "review", "recap",
    ]
    show_terms = ["raw", "smackdown", "nxt", "dynamite", "collision", "rampage"]
    if any(x in blob for x in hard) and any(x in blob for x in show_terms):
        return True
    return False


def news_category_for_entry(entry: Dict[str, Any]) -> List[str]:
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


def score_news_entry(entry: Dict[str, Any]) -> int:
    title = normalize_text(entry.get("title", ""))
    summary = normalize_text(entry.get("summary", ""))
    blob = f"{title} {summary}"
    score = 0
    major_terms = [
        "wwe", "aew", "nxt", "tna", "roman reigns", "cody rhodes", "cm punk", "john cena",
        "the rock", "seth rollins", "becky lynch", "rhea ripley", "mercedes mone",
        "contract", "injury", "return", "released", "signs", "championship", "title",
        "backstage", "report", "confirmed", "update", "plans", "premium live event",
    ]
    for term in major_terms:
        if term in blob:
            score += 8
    if any(x in blob for x in ["spoiler", "spoilers"]):
        score += 10
    if any(x in blob for x in ["rumor", "rumour", "reportedly", "report"]):
        score += 5
    if len(title) > 20:
        score += 10
    if len(summary) > 80:
        score += 5
    return min(score, 100)


def select_news_candidates(entries: List[Dict[str, Any]], published_urls: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        url = str(entry.get("url") or "").strip()
        title = str(entry.get("title") or "").strip()
        if not url or not title:
            continue
        if url in published_urls or url in seen:
            continue
        seen.add(url)
        if is_report_like_news(entry):
            log(f"[NEWS v92] Skip report-like: {title}")
            continue
        score = score_news_entry(entry)
        if score < 35:
            log(f"[NEWS v92] Skip score basso ({score}/100): {title}")
            continue
        item = dict(entry)
        item["score"] = score
        candidates.append(item)
    candidates.sort(key=lambda e: (int(e.get("score") or 0), str(e.get("published") or "")), reverse=True)
    return candidates[:limit]
'''

insert_before = '\n\ndef run_news_pipeline(wp_ok: bool, now: datetime) -> int:\n'
text = text.replace(insert_before, helper + insert_before, 1)

old = '''def run_news_pipeline(wp_ok: bool, now: datetime) -> int:
    save_json(PENDING_NEWS_FILE, [])
    log(f"[NEWS v92] Pipeline news non ancora attiva. max_news_per_run={MAX_NEWS_PER_RUN}")
    return 0
'''
new = '''def run_news_pipeline(wp_ok: bool, now: datetime) -> int:
    if not wp_ok:
        log("[NEWS v92] WordPress non disponibile: skip news")
        return 0
    feeds_cfg = load_json(FEEDS_CONFIG, {"feeds": []})
    published_urls = load_json(PUBLISHED_NEWS_FILE, {})
    pending: List[Dict[str, Any]] = []
    entries = feed_entries(feeds_cfg.get("feeds", []))
    candidates = select_news_candidates(entries, published_urls, MAX_NEWS_PER_RUN)
    published = 0
    for entry in candidates:
        url = str(entry.get("url") or "")
        key = f"news:{slugify(url)}"
        categories = news_category_for_entry(entry)
        job = {
            "kind": "news",
            "news_key": key,
            "source": entry.get("source"),
            "source_url": url,
            "source_title": entry.get("title"),
            "categories": categories,
            "score": entry.get("score"),
            "created_at": utcnow().isoformat(),
        }
        try:
            log(f"[NEWS v92] Pubblico candidato score={job['score']}/100 source={job['source']} title={job['source_title']}")
            post_id, post_json = run_news_workshop(job, PUBLISHED_DIR, REVIEW_DIR)
            published_urls[url] = {
                "status": "published",
                "wp_post_id": post_id,
                "source": job["source"],
                "source_title": job["source_title"],
                "categories": categories,
                "score": job["score"],
                "published_at": utcnow().isoformat(),
                "link": post_json.get("link"),
            }
            published += 1
        except Exception as exc:
            log(f"[NEWS v92] Errore pubblicazione news: {job['source_title']} | {exc}")
            pending.append({**job, "status": "failed_technical", "error": str(exc)[:1000]})
            continue
    save_json(PUBLISHED_NEWS_FILE, published_urls)
    save_json(PENDING_NEWS_FILE, pending)
    log(f"[NEWS v92] Pubblicate news={published}/{MAX_NEWS_PER_RUN}")
    return published
'''
if old not in text:
    raise SystemExit("[V92 NEWS] run_news_pipeline placeholder non trovato")
text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")
print("[V92 NEWS] pipeline news applicata")
