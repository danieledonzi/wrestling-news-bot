from pathlib import Path

# -----------------------------------------------------------------------------
# v92 deterministic category resolution patch.
# Problem observed: news appeared under Business even when the bot should have
# assigned WWE/AEW. Make WP category resolution deterministic:
# - log category names before publish;
# - resolve by exact name or slug across all categories;
# - never use the first fuzzy search result;
# - create missing known categories instead of falling back to WP default.
# -----------------------------------------------------------------------------

p = Path("modules/news_workshop_v92.py")
text = p.read_text(encoding="utf-8")

if "V92_DETERMINISTIC_CATEGORY_RESOLUTION = True" in text:
    print("[V92 CATEGORY] deterministic category resolution gia applicata")
    raise SystemExit(0)

text = text.replace(
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\n",
    "_media_cache: Dict[str, Tuple[Optional[int], Optional[str]]] = {}\nV92_DETERMINISTIC_CATEGORY_RESOLUTION = True\n_ALL_CATEGORY_CACHE: Optional[List[Dict[str, Any]]] = None\n",
    1,
)

start = text.find("def resolve_category_id(name: str) -> Optional[int]:")
end = text.find("\n\ndef upload_media", start)
if start == -1 or end == -1:
    raise SystemExit("[V92 CATEGORY] resolve_category block non trovato")

new_block = r'''def category_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def fetch_all_categories() -> List[Dict[str, Any]]:
    global _ALL_CATEGORY_CACHE
    if _ALL_CATEGORY_CACHE is not None:
        return _ALL_CATEGORY_CACHE
    cats: List[Dict[str, Any]] = []
    page = 1
    while page <= 5:
        res = wp_request_with_retry("get", wp_categories_url(), params={"per_page": 100, "page": page}, auth=wp_auth())
        if res.status_code != 200:
            break
        chunk = res.json()
        if not isinstance(chunk, list) or not chunk:
            break
        cats.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    _ALL_CATEGORY_CACHE = cats
    print(f"[NEWS v92] Categorie WP caricate: {len(cats)}", flush=True)
    return cats


def create_category(name: str) -> Optional[int]:
    global _ALL_CATEGORY_CACHE
    res = wp_request_with_retry("post", wp_categories_url(), json={"name": name, "slug": category_slug(name)}, auth=wp_auth())
    if res.status_code in {200, 201}:
        data = res.json()
        cid = int(data.get("id")) if data.get("id") else None
        _ALL_CATEGORY_CACHE = None
        print(f"[NEWS v92] Categoria WP creata: {name} -> {cid}", flush=True)
        return cid
    print(f"[NEWS v92] Creazione categoria WP fallita: {name} status={res.status_code} body={res.text[:200]}", flush=True)
    return None


def resolve_category_id(name: str) -> Optional[int]:
    clean = (name or "").strip()
    if not clean:
        return None
    key = clean.lower()
    if key in _category_cache:
        return _category_cache[key]

    target_slug = category_slug(clean)
    cats = fetch_all_categories()

    # Exact name first.
    for cat in cats:
        if str(cat.get("name", "")).strip().lower() == key:
            cid = int(cat["id"])
            _category_cache[key] = cid
            print(f"[NEWS v92] Categoria risolta exact-name: {clean} -> {cid}", flush=True)
            return cid

    # Exact slug second.
    for cat in cats:
        if str(cat.get("slug", "")).strip().lower() == target_slug:
            cid = int(cat["id"])
            _category_cache[key] = cid
            print(f"[NEWS v92] Categoria risolta exact-slug: {clean}/{target_slug} -> {cid}", flush=True)
            return cid

    # Never use fuzzy first result. Create missing expected category instead.
    cid = create_category(clean)
    _category_cache[key] = cid
    return cid


def resolve_category_ids(names: List[str]) -> List[int]:
    out: List[int] = []
    clean_names = [str(name).strip() for name in names if str(name).strip()]
    print(f"[NEWS v92] Categorie richieste: {clean_names}", flush=True)
    for name in clean_names:
        cid = resolve_category_id(name)
        if cid and cid not in out:
            out.append(cid)
    print(f"[NEWS v92] Categorie risolte ids: {out}", flush=True)
    return out
'''

text = text[:start] + new_block + text[end:]

# Add explicit publish log before payload category resolution.
old = '''def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    media_id, _src = upload_media(image_url)
    payload: Dict[str, Any] = {
        "title": translated_title,
        "content": append_source(body_html, str(job.get("source") or ""), str(job.get("source_url") or "")),
        "status": "publish",
        "categories": resolve_category_ids(list(job.get("categories") or [])),
        "meta": {"original_url": job.get("source_url"), "news_key": job.get("news_key")},
    }
'''
new = '''def publish_news(job: Dict[str, Any], translated_title: str, body_html: str, image_url: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    media_id, _src = upload_media(image_url)
    category_names = list(job.get("categories") or [])
    print(f"[NEWS v92] Publish categories decision: {category_names} | title={translated_title}", flush=True)
    category_ids = resolve_category_ids(category_names)
    payload: Dict[str, Any] = {
        "title": translated_title,
        "content": append_source(body_html, str(job.get("source") or ""), str(job.get("source_url") or "")),
        "status": "publish",
        "categories": category_ids,
        "meta": {"original_url": job.get("source_url"), "news_key": job.get("news_key")},
    }
'''
if old in text:
    text = text.replace(old, new, 1)
else:
    print("[V92 CATEGORY] publish_news payload block non trovato")

p.write_text(text, encoding="utf-8")
print("[V92 CATEGORY] deterministic category resolution applicata")
