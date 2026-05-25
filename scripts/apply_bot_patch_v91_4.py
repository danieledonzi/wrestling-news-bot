from pathlib import Path

MARK = "# v91.4 publish processed and soft pool repair"
CODE = r'''

# v91.4 publish processed and soft pool repair
BOT_VERSION = "v91_4_publish_processed_softpool_repair"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V91_4_ENABLED = os.getenv("V91_4_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_4_RECONCILE_PUBLISHED_ENABLED = os.getenv("V91_4_RECONCILE_PUBLISHED_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_4_SOFT_POOL_CLEANUP_ENABLED = os.getenv("V91_4_SOFT_POOL_CLEANUP_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V91_4_SOFT_POOL_FILE = os.getenv("V91_4_SOFT_POOL_FILE", "soft_pool.json")


def v914_post_id_from_publish_result(result):
    """Extract a WordPress post id from the known publish return shapes."""
    try:
        if result is True:
            return 1
        if isinstance(result, (int, float)):
            return int(result) if int(result) > 0 else 0
        if isinstance(result, str):
            raw = result.strip().lower()
            return 1 if raw in globals().get("V90_2_5_SUCCESS_STRINGS", {"published", "ok", "success"}) else 0
        if isinstance(result, dict):
            if result.get("error") or result.get("failed"):
                return 0
            for key in ("post_id", "id", "wp_post_id"):
                if result.get(key):
                    try:
                        return int(result.get(key))
                    except Exception:
                        return 1
            status = str(result.get("status") or result.get("result") or "").strip().lower()
            if status in globals().get("V90_2_5_SUCCESS_STRINGS", {"published", "ok", "success"}):
                return 1
            if str(result.get("wp_status") or "").strip().lower() == "publish":
                return 1
            return 0
        if isinstance(result, (tuple, list)):
            # Common shape after draft-first publishing: (post_id, post_json)
            if not result:
                return 0
            first = v914_post_id_from_publish_result(result[0])
            if first:
                return first
            for part in result[1:]:
                found = v914_post_id_from_publish_result(part)
                if found:
                    return found
    except Exception:
        return 0
    return 0


try:
    _PREV_V914_v9025_publish_succeeded = v9025_publish_succeeded
    def v9025_publish_succeeded(result):
        if V91_4_ENABLED and v914_post_id_from_publish_result(result):
            return True
        return _PREV_V914_v9025_publish_succeeded(result)
except Exception as e:
    print(f"[V91.4] Warning publish success guard failed: {e}")


try:
    _PREV_V914_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        result = _PREV_V914_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )
        try:
            if V91_4_ENABLED and "v9025_record_processed_url" in globals() and v9025_publish_succeeded(result):
                title = ""
                if isinstance(data, dict):
                    title = data.get("titolo") or data.get("title") or ""
                post_id = v914_post_id_from_publish_result(result)
                v9025_record_processed_url(
                    url,
                    title=title,
                    status="published",
                    reason="v91_4_confirmed_wordpress_publish",
                    extra={"event_key": event_key, "semantic_id": sem_id, "wp_post_id": post_id},
                )
                print(f"[PROCESSED v91.4] URL marcato published dopo publish confermato: {url}")
        except Exception as e:
            print(f"[PROCESSED v91.4] Warning final publish record guard: {e}")
        return result
except Exception as e:
    print(f"[V91.4] Warning create_post_without_image guard failed: {e}")


def v914_load_json(path, default):
    try:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if data is not None else default
    except Exception as e:
        print(f"[V91.4] Warning load {path}: {e}")
    return default


def v914_save_json(path, data):
    try:
        p = Path(path)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        print(f"[V91.4] Warning save {path}: {e}")


def v914_reconcile_published_artifacts():
    if not V91_4_ENABLED or not V91_4_RECONCILE_PUBLISHED_ENABLED:
        return
    if "v9025_record_processed_url" not in globals() or "v9025_processed_record" not in globals():
        return
    root = Path("published")
    if not root.exists():
        return
    fixed = 0
    scanned = 0
    for meta_path in sorted(root.glob("*_metadata.json")):
        scanned += 1
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = str(meta.get("source_url") or "").strip()
        if not url:
            continue
        wp_status = str(meta.get("wp_status") or "").strip().lower()
        wp_post_id = meta.get("wp_post_id")
        if wp_status != "publish" and not wp_post_id:
            continue
        rec = v9025_processed_record(url)
        if isinstance(rec, dict) and str(rec.get("status") or "").lower() == "published":
            continue
        v9025_record_processed_url(
            url,
            title=meta.get("title") or "",
            status="published",
            reason="v91_4_published_artifact_reconcile",
            extra={
                "event_key": meta.get("event_key") or "",
                "semantic_id": meta.get("semantic_id") or "",
                "wp_post_id": wp_post_id,
                "metadata_file": str(meta_path),
            },
        )
        fixed += 1
    if scanned or fixed:
        print(f"[PROCESSED v91.4] Published artifact reconcile: scanned={scanned} fixed={fixed}")


def v914_parse_dt(value):
    try:
        if not value:
            return None
        txt = str(value).replace("Z", "").strip()
        return datetime.fromisoformat(txt)
    except Exception:
        return None


def v914_soft_pool_repaired_core(entry):
    title = str(entry.get("title") or "")
    url = str(entry.get("url") or "")
    raw = f"{title} {url}".lower()
    old_core = str(entry.get("core") or "")
    if old_core and not old_core.startswith("title:"):
        return old_core
    if "double or nothing" in raw or "double-nothing" in raw:
        if "results" in raw or "risult" in raw:
            return "report:aew-double-or-nothing-2026-05-24"
        if any(x in raw for x in ("mjf", "darby", "world title", "hair", "thekla", "moxley", "takeshita", "fletcher", "stadium stampede")):
            return "event:aew-double-or-nothing-2026-05-25:post-show-angle"
    if "becky" in raw and "sol ruca" in raw:
        return "event:wwe-snme-2026-05-25:becky-lynch-story"
    return old_core


def v914_cleanup_soft_pool():
    if not V91_4_ENABLED or not V91_4_SOFT_POOL_CLEANUP_ENABLED:
        return
    p = Path(V91_4_SOFT_POOL_FILE)
    if not p.exists():
        return
    pool = v914_load_json(p, [])
    if not isinstance(pool, list):
        return
    now = datetime.utcnow()
    cleaned = []
    expired = 0
    migrated = 0
    for entry in pool:
        if not isinstance(entry, dict):
            continue
        ttl = entry.get("ttl_hours", 8)
        try:
            ttl = float(ttl)
        except Exception:
            ttl = 8.0
        created = v914_parse_dt(entry.get("created_at"))
        if created is not None and (now - created).total_seconds() > max(ttl, 1.0) * 3600:
            expired += 1
            continue
        old_core = str(entry.get("core") or "")
        new_core = v914_soft_pool_repaired_core(entry)
        if new_core and new_core != old_core:
            entry = dict(entry)
            entry["core"] = new_core
            entry["core_repaired_by"] = "v91.4"
            migrated += 1
        cleaned.append(entry)
    if expired or migrated or len(cleaned) != len(pool):
        v914_save_json(p, cleaned)
    print(f"[SOFTPOOL v91.4] cleanup keep={len(cleaned)} expired={expired} migrated={migrated}")


try:
    _PREV_V914_run_bot = run_bot
    def run_bot():
        v914_reconcile_published_artifacts()
        v914_cleanup_soft_pool()
        return _PREV_V914_run_bot()
except Exception as e:
    print(f"[V91.4] Warning run_bot guard failed: {e}")

print("[BOOT v91.4] Publish processed + soft pool repair attivi")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.4] bot.py gia aggiornato")
        return 0
    if "# v91.3 corrected v723 parser" not in text:
        raise SystemExit("[SOURCE PATCH v91.4] base v91.3 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.4] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.4] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
