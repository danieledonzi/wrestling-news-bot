from pathlib import Path

MARK = "# v91.5.3 report pending unwrap recursion guard"
CODE = r'''

# v91.5.3 report pending unwrap recursion guard
V91_5_3_ENABLED = os.getenv("V91_5_3_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
_V9153_REPORT_PENDING_ACTIVE = set()


def v9153_report_key(item):
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("report_event_key")
        or item.get("event_key")
        or item.get("story_signature_v71")
        or item.get("url")
        or item.get("title")
        or ""
    )


def v9153_is_report_pending_item(item):
    if not isinstance(item, dict):
        return False
    if item.get("__v9153_unwrapped_report_pending"):
        return False
    status = str(item.get("status") or "")
    key = v9153_report_key(item)
    if item.get("kind") == "report":
        return True
    if item.get("report_event_key"):
        return True
    if status.startswith("waiting_report") or status == "waiting_report_morning_hold":
        return True
    if key.startswith("report:") and item.get("sources"):
        return True
    return False


def v9153_mature_report_pending(item):
    try:
        not_before = float(item.get("not_before") or 0)
        return not_before <= 0 or time.time() >= not_before
    except Exception:
        return True


def v9153_source_url_title(item):
    url = str(item.get("url") or item.get("link") or "").strip()
    title = str(item.get("title") or item.get("titolo") or "").strip()
    sources = item.get("sources")
    if isinstance(sources, list):
        # Prefer WrestlingInc for structured reports when available, otherwise first concrete source.
        concrete = [s for s in sources if isinstance(s, dict) and (s.get("url") or s.get("link"))]
        preferred = None
        for s in concrete:
            su = str(s.get("url") or s.get("link") or "")
            if "wrestlinginc.com" in su:
                preferred = s
                break
        if preferred is None and concrete:
            preferred = concrete[0]
        if preferred:
            url = str(preferred.get("url") or preferred.get("link") or url).strip()
            title = str(preferred.get("title") or title).strip()
    return url, title


def v9153_unwrap_report_pending(item):
    candidate = dict(item)
    url, title = v9153_source_url_title(candidate)
    if url:
        candidate["url"] = url
        candidate["link"] = url
    if title:
        candidate["title"] = title
    report_key = str(candidate.get("report_event_key") or candidate.get("event_key") or candidate.get("story_signature_v71") or "")
    # Remove fields that make legacy routers send the item back into process_report_pending_item.
    for key in (
        "kind",
        "report_event_key",
        "not_before",
        "hold_until_label",
        "first_seen",
        "last_seen",
        "sources",
    ):
        candidate.pop(key, None)
    candidate["status"] = "raw"
    candidate["reason"] = "v91_5_3_unwrapped_report_pending"
    candidate["__v9153_unwrapped_report_pending"] = True
    candidate["__v9153_original_report_key"] = report_key
    # Keep report identity for dedupe, but avoid fields likely used as pending routers.
    if report_key.startswith("report:"):
        candidate["event_key"] = report_key
        candidate["story_signature_v71"] = report_key
        candidate["semantic_id"] = candidate.get("semantic_id") or report_key.replace(":", "-")
    return candidate


try:
    _PREV_V9153_process_report_pending_item = process_report_pending_item
    def process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if not V91_5_3_ENABLED or not v9153_is_report_pending_item(item):
            return _PREV_V9153_process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        key = v9153_report_key(item)
        if key in _V9153_REPORT_PENDING_ACTIVE:
            print(f"[REPORT v91.5.3] Ricorsione report pending evitata: {key}")
            return "skipped"
        if not v9153_mature_report_pending(item):
            return _PREV_V9153_process_report_pending_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        candidate = v9153_unwrap_report_pending(item)
        print(f"[REPORT v91.5.3] Report pending maturo spacchettato in candidate normale: {key} -> {candidate.get('url')}")
        _V9153_REPORT_PENDING_ACTIVE.add(key)
        try:
            return process_candidate_item(candidate, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        finally:
            _V9153_REPORT_PENDING_ACTIVE.discard(key)
except Exception as e:
    print(f"[REPORT v91.5.3] Warning process_report_pending_item guard failed: {e}")

try:
    _PREV_V9153_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if V91_5_3_ENABLED and isinstance(item, dict) and item.get("__v9153_unwrapped_report_pending"):
            # Defensive cleanup in case older wrappers still inspect pending-specific fields.
            for key in ("kind", "report_event_key", "not_before", "hold_until_label", "sources"):
                item.pop(key, None)
            item["status"] = "raw"
        return _PREV_V9153_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception as e:
    print(f"[REPORT v91.5.3] Warning process_candidate_item guard failed: {e}")

print("[BOOT v91.5.3] Report pending unwrap recursion guard attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.5.3] bot.py gia aggiornato")
        return 0
    if "# v91.5.2 final safe print recursion guard" not in text:
        raise SystemExit("[SOURCE PATCH v91.5.3] base v91.5.2 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.5.3] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.5.3] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
