from pathlib import Path

MARK = "# v90.2.5 processed URL hard-skip"
CODE = r'''

# v90.2.5 processed URL hard-skip
BOT_VERSION = "v90_2_5_processed_url_hardskip"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_5_ENABLED = os.getenv("V90_2_5_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V90_2_5_PROCESSED_FILE = os.getenv("V90_2_5_PROCESSED_FILE", "processed_urls.json")
V90_2_5_MAX_RECORDS = int(os.getenv("V90_2_5_MAX_RECORDS", "5000"))
V90_2_5_FINAL_STATUSES = {
    "published",
    "rejected",
    "skipped_below_threshold",
    "skipped_duplicate",
    "skipped_stale",
    "skipped_soft_trash",
    "skipped_editorial_exclude",
    "skipped_existing_wp",
    "skipped_existing_history",
}
V90_2_5_TEMP_STATUSES = {"pending", "wp_down", "wp_firewall", "publish_error", "temporary_error"}
V90_2_5_SUCCESS_STRINGS = {"published", "publish_ok", "ok", "success"}
V90_2_5_TEMP_STRINGS = {"wp_fail", "wp_firewall", "wp_down", "publish_error", "temporary_error", "retry", "pending"}


def v9025_now_iso():
    try:
        return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    except Exception:
        return str(time.time())


def v9025_load_processed():
    try:
        p = Path(V90_2_5_PROCESSED_FILE)
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception as e:
        print(f"[PROCESSED v90.2.5] Errore lettura processed urls: {e}")
    return {}


def v9025_save_processed(data):
    if not isinstance(data, dict):
        data = {}
    try:
        if len(data) > V90_2_5_MAX_RECORDS:
            items = sorted(data.items(), key=lambda kv: str((kv[1] or {}).get("updated_at", "")), reverse=True)
            data = dict(items[:V90_2_5_MAX_RECORDS])
        Path(V90_2_5_PROCESSED_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as e:
        print(f"[PROCESSED v90.2.5] Errore salvataggio processed urls: {e}")


def v9025_url_from_any(obj):
    if isinstance(obj, dict):
        return str(obj.get("url") or obj.get("link") or "").strip()
    try:
        return str(getattr(obj, "link", "") or "").strip()
    except Exception:
        return ""


def v9025_title_from_any(obj):
    if isinstance(obj, dict):
        return str(obj.get("title") or obj.get("titolo") or "").strip()
    try:
        return str(getattr(obj, "title", "") or "").strip()
    except Exception:
        return ""


def v9025_normalized_url(url):
    url = str(url or "").strip()
    if not url:
        return ""
    try:
        return normalize_url_for_compare(url)
    except Exception:
        return url.split("#", 1)[0].rstrip("/")


def v9025_is_final_status(status):
    return str(status or "").strip().lower() in V90_2_5_FINAL_STATUSES


def v9025_record_processed_url(url, title="", status="rejected", reason="", score=None, extra=None):
    if not V90_2_5_ENABLED:
        return
    key = v9025_normalized_url(url)
    if not key:
        return
    status = str(status or "").strip().lower()
    if status in V90_2_5_TEMP_STATUSES:
        return
    data = v9025_load_processed()
    old = data.get(key) if isinstance(data, dict) else None
    if isinstance(old, dict) and old.get("status") == "published":
        return
    old_title = old.get("title", "") if isinstance(old, dict) else ""
    rec = {
        "url": url,
        "title": title or old_title,
        "status": status or "rejected",
        "reason": reason,
        "score": score,
        "updated_at": v9025_now_iso(),
    }
    if isinstance(extra, dict):
        rec["extra"] = extra
    data[key] = rec
    v9025_save_processed(data)


def v9025_processed_record(url):
    key = v9025_normalized_url(url)
    if not key:
        return None
    data = v9025_load_processed()
    rec = data.get(key) if isinstance(data, dict) else None
    return rec if isinstance(rec, dict) else None


def v9025_should_hard_skip_url(url):
    rec = v9025_processed_record(url)
    if not rec:
        return False, None
    if v9025_is_final_status(rec.get("status")):
        return True, rec
    return False, rec


def v9025_publish_succeeded(result):
    if result is True:
        return True
    if isinstance(result, str):
        return result.strip().lower() in V90_2_5_SUCCESS_STRINGS
    if isinstance(result, (int, float)):
        return int(result) > 0
    if isinstance(result, dict):
        if result.get("error") or result.get("failed"):
            return False
        status = str(result.get("status") or result.get("result") or "").strip().lower()
        if status in V90_2_5_SUCCESS_STRINGS:
            return True
        post_id = result.get("post_id") or result.get("id") or result.get("wp_post_id")
        try:
            return bool(post_id and int(post_id) > 0)
        except Exception:
            return bool(post_id)
    return False


def v9025_reject_status_from_result(result, item):
    if result is None:
        return "rejected", "process_candidate_none"
    if result is False:
        return "rejected", "process_candidate_false"
    if isinstance(result, str):
        raw = result.strip().lower()
        if raw in V90_2_5_SUCCESS_STRINGS or raw in V90_2_5_TEMP_STRINGS:
            return "", raw
        mapping = {
            "skipped": "rejected",
            "skip": "rejected",
            "below_threshold": "skipped_below_threshold",
            "score_below_threshold": "skipped_below_threshold",
            "validation_fail": "rejected",
            "duplicate": "skipped_duplicate",
            "stale": "skipped_stale",
            "soft_trash": "skipped_soft_trash",
            "editorial_exclude": "skipped_editorial_exclude",
            "existing_wp": "skipped_existing_wp",
            "existing_history": "skipped_existing_history",
        }
        return mapping.get(raw, "rejected"), raw
    if isinstance(result, dict):
        raw = str(result.get("status") or result.get("result") or result.get("reason") or "").strip().lower()
        if raw in V90_2_5_SUCCESS_STRINGS or raw in V90_2_5_TEMP_STRINGS:
            return "", raw
        if result.get("duplicate"):
            return "skipped_duplicate", "duplicate"
        if result.get("validation_fail"):
            return "rejected", "validation_fail"
        if raw:
            return v9025_reject_status_from_result(raw, item)
    try:
        score = int((item or {}).get("score", 0) or 0)
        if score and score < int(globals().get("MIN_PUBLISH_SCORE", 75)):
            return "skipped_below_threshold", "score_below_threshold_or_refined"
    except Exception:
        pass
    return "", "non_final_result"

try:
    _ORIG_V9025_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        result = _ORIG_V9025_create_post_without_image(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)
        try:
            if v9025_publish_succeeded(result):
                title = ""
                if isinstance(data, dict):
                    title = data.get("titolo") or data.get("title") or ""
                v9025_record_processed_url(url, title=title, status="published", reason="wordpress_publish_ok", extra={"event_key": event_key, "semantic_id": sem_id})
            else:
                print("[PROCESSED v90.2.5] Publish result non conclusivo: non marco URL published")
        except Exception as e:
            print(f"[PROCESSED v90.2.5] Warning record published URL: {e}")
        return result
except Exception:
    pass

try:
    _ORIG_V9025_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if V90_2_5_ENABLED and isinstance(item, dict):
            url = v9025_url_from_any(item)
            skip, rec = v9025_should_hard_skip_url(url)
            if skip:
                print(f"[PROCESSED v90.2.5] Hard skip URL gia lavorato status={rec.get('status')} reason={rec.get('reason')} - {item.get('title', '')}")
                return "skipped_processed_url"
        result = _ORIG_V9025_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        try:
            if V90_2_5_ENABLED and isinstance(item, dict):
                status, reason = v9025_reject_status_from_result(result, item)
                if status and v9025_is_final_status(status):
                    url = v9025_url_from_any(item)
                    title = v9025_title_from_any(item)
                    score = item.get("score")
                    v9025_record_processed_url(url, title=title, status=status, reason=reason, score=score, extra={"event_key": item.get("event_key"), "semantic_id": item.get("semantic_id"), "raw_result": str(result)[:120]})
        except Exception as e:
            print(f"[PROCESSED v90.2.5] Warning record rejected URL: {e}")
        return result
except Exception:
    pass

try:
    _ORIG_V9025_run_bot = run_bot
    def run_bot():
        try:
            globals()["processed_urls_v9025"] = v9025_load_processed()
            print(f"[PROCESSED v90.2.5] Loaded processed URL records: {len(globals().get('processed_urls_v9025') or {})}")
        except Exception:
            pass
        return _ORIG_V9025_run_bot()
except Exception:
    pass

print("[BOOT v90.2.5] Processed URL hard-skip attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.5] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.5] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.5] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
