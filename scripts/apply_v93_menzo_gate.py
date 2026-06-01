from pathlib import Path

p = Path("bot_v92.py")
text = p.read_text(encoding="utf-8")

if "V93_MENZO_GATE_ACTIVE = True" in text:
    print("[V93 MENZO GATE] gia applicato")
    raise SystemExit(0)

# Add state path constants after the v92 news state files are available.
needle = 'NEWS_SOFT_POOL_FILE = STATE_DIR / "news_soft_pool.json"\n'
if needle not in text:
    raise SystemExit("[V93 MENZO GATE] NEWS_SOFT_POOL_FILE marker non trovato")
constants = 'V93_MENZO_ALLOWED_NEWS_FILE = NEWSROOM_STATE_DIR / "v92_allowed_news_urls.json"\nV93_MENZO_GATE_ACTIVE = True\n'
if 'NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"' in text:
    text = text.replace(needle, needle + constants, 1)
else:
    text = text.replace(
        needle,
        needle
        + 'NEWSROOM_STATE_DIR = STATE_DIR / "newsroom"\n'
        + constants,
        1,
    )

# Add helpers before run_news_pipeline.
insert_before = '\n\ndef run_news_pipeline(wp_ok: bool, now: datetime) -> int:\n'
if insert_before not in text:
    raise SystemExit("[V93 MENZO GATE] run_news_pipeline marker non trovato")

helpers = r'''

def v93_gate_key(url: str) -> str:
    raw = str(url or "").strip().lower()
    if not raw:
        return ""
    raw = raw.split("#", 1)[0]
    raw = raw.split("?", 1)[0]
    return raw.rstrip("/")


def load_v93_menzo_allowed_urls() -> set[str]:
    data = load_json(V93_MENZO_ALLOWED_NEWS_FILE, {})
    urls = data.get("allowed_urls", []) if isinstance(data, dict) else []
    if not isinstance(urls, list):
        return set()
    return {v93_gate_key(str(url)) for url in urls if v93_gate_key(str(url))}


def v93_menzo_gate_enabled() -> bool:
    return str(os.getenv("V93_MENZO_GATE", "1")).strip().lower() not in {"0", "false", "no", "off"}


def v93_menzo_allows(entry: Dict[str, Any], allowed: set[str]) -> bool:
    if not allowed:
        return True
    url = v93_gate_key(str(entry.get("url") or entry.get("source_url") or ""))
    return bool(url and url in allowed)


def v93_filter_soft_pool_items(items: List[Dict[str, Any]], allowed: set[str]) -> List[Dict[str, Any]]:
    if not allowed:
        return items
    return [item for item in items if v93_menzo_allows(item, allowed)]
'''
text = text.replace(insert_before, helpers + insert_before, 1)

old = '''    entries = feed_entries(feeds_cfg.get("feeds", []))
    hard_items: List[Dict[str, Any]] = []
    soft_items: List[Dict[str, Any]] = hydrate_soft_pool(soft_pool, now)
    seen: set[str] = set()

    for entry in entries:
'''
new = '''    entries = feed_entries(feeds_cfg.get("feeds", []))
    allowed_urls = load_v93_menzo_allowed_urls() if v93_menzo_gate_enabled() else set()
    if allowed_urls:
        log(f"[NEWS v92] V93 Menzo gate attivo: allowed_urls={len(allowed_urls)}")
    else:
        log("[NEWS v92] V93 Menzo gate non vincolante: allowed_urls vuoto o gate disattivato")
    hard_items: List[Dict[str, Any]] = []
    hydrated_soft_items = hydrate_soft_pool(soft_pool, now)
    soft_items: List[Dict[str, Any]] = v93_filter_soft_pool_items(hydrated_soft_items, allowed_urls)
    if allowed_urls and len(soft_items) != len(hydrated_soft_items):
        log(f"[NEWS v92] V93 Menzo gate soft_pool filtrata: kept={len(soft_items)} original={len(hydrated_soft_items)}")
    seen: set[str] = set()

    for entry in entries:
'''
if old not in text:
    raise SystemExit("[V93 MENZO GATE] blocco entries non trovato")
text = text.replace(old, new, 1)

old = '''        if url in hard_skips:
            continue

        if is_report_like_news(entry):
'''
new = '''        if url in hard_skips:
            continue
        if not v93_menzo_allows(entry, allowed_urls):
            log(f"[NEWS v92] Skip V93 Menzo gate: {title}")
            continue

        if is_report_like_news(entry):
'''
if old not in text:
    raise SystemExit("[V93 MENZO GATE] blocco hard_skips non trovato")
text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")
print("[V93 MENZO GATE] applicato")
