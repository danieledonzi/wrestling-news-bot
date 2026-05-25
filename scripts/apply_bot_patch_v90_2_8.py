from pathlib import Path

MARK = "# v90.2.8 feed-level processed URL hard skip"
CODE = r'''

# v90.2.8 feed-level processed URL hard skip
BOT_VERSION = "v90_2_8_feed_level_processed_skip"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_8_ENABLED = os.getenv("V90_2_8_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V9028_PROCESSED_CACHE = None


def v9028_entry_get(entry, key, default=""):
    try:
        if hasattr(entry, "get"):
            return entry.get(key, default) or default
        return getattr(entry, key, default) or default
    except Exception:
        return default


def v9028_entry_url(entry):
    for key in ("link", "url", "id", "guid"):
        value = str(v9028_entry_get(entry, key, "") or "").strip()
        if value.startswith("http"):
            return value
    return ""


def v9028_entry_title(entry):
    return str(v9028_entry_get(entry, "title", "") or v9028_entry_get(entry, "titolo", "") or "").strip()


def v9028_load_processed_records_cached():
    global V9028_PROCESSED_CACHE
    if V9028_PROCESSED_CACHE is not None:
        return V9028_PROCESSED_CACHE
    try:
        if "v90272_load_processed_store" in globals():
            data = v90272_load_processed_store()
        elif "v9025_load_processed" in globals():
            data = v9025_load_processed()
        elif "v9025_load_processed_records" in globals():
            data = v9025_load_processed_records()
        elif "v9025_load_processed_urls" in globals():
            data = v9025_load_processed_urls()
        else:
            data = None
        records = data.get("records", data) if isinstance(data, dict) else data
        V9028_PROCESSED_CACHE = records if isinstance(records, dict) else {}
    except Exception as e:
        print(f"[FEED SKIP v90.2.8] Warning load processed: {e}")
        V9028_PROCESSED_CACHE = {}
    return V9028_PROCESSED_CACHE


def v9028_processed_url_final(url):
    if not V90_2_8_ENABLED or not url:
        return False, None
    try:
        records = v9028_load_processed_records_cached()
        norm = normalize_url_for_history(url) if "normalize_url_for_history" in globals() else url
        rec = records.get(url) or records.get(norm)
        if "v90272_processed_record_is_final" in globals():
            is_final = v90272_processed_record_is_final(rec)
        else:
            status = str((rec or {}).get("status") or "") if isinstance(rec, dict) else ""
            is_final = status in {"published", "skipped_duplicate", "skipped_existing_wp", "skipped_existing_history", "skipped_editorial_exclude", "skipped_soft_trash", "skipped_stale", "low_score_final"}
        return (True, rec) if is_final else (False, rec)
    except Exception as e:
        print(f"[FEED SKIP v90.2.8] Warning processed check: {e}")
        return False, None


def v9028_filter_parsed_feed(parsed, feed_url=""):
    if not V90_2_8_ENABLED:
        return parsed
    try:
        entries = getattr(parsed, "entries", None)
        if entries is None and hasattr(parsed, "get"):
            entries = parsed.get("entries")
        if not isinstance(entries, list):
            return parsed
        kept = []
        skipped = 0
        for entry in entries:
            url = v9028_entry_url(entry)
            title = v9028_entry_title(entry)
            final, rec = v9028_processed_url_final(url)
            if final:
                skipped += 1
                status = rec.get("status") if isinstance(rec, dict) else ""
                reason = rec.get("reason") if isinstance(rec, dict) else ""
                print(f"[FEED SKIP v90.2.8] URL finale gia lavorato: status={status} reason={reason} - {title}")
                continue
            kept.append(entry)
        if skipped:
            try:
                parsed.entries = kept
            except Exception:
                pass
            try:
                parsed["entries"] = kept
            except Exception:
                pass
            print(f"[FEED SKIP v90.2.8] Feed filtrato: skip={skipped} keep={len(kept)} source={feed_url}")
    except Exception as e:
        print(f"[FEED SKIP v90.2.8] Warning filtro feed: {e}")
    return parsed

try:
    _ORIG_V9028_feedparser_parse = feedparser.parse
    def v9028_feedparser_parse(*args, **kwargs):
        parsed = _ORIG_V9028_feedparser_parse(*args, **kwargs)
        feed_url = str(args[0]) if args else str(kwargs.get("url_file_stream_or_string", ""))
        return v9028_filter_parsed_feed(parsed, feed_url=feed_url)
    feedparser.parse = v9028_feedparser_parse
except Exception as e:
    print(f"[FEED SKIP v90.2.8] Warning hook feedparser.parse non installato: {e}")

print("[BOOT v90.2.8] Feed-level processed URL hard skip attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.8] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.8] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.8] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
