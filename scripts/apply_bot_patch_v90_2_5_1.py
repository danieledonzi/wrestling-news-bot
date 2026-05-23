from pathlib import Path

MARK = "# v90.2.5.1 processed skip recorder"
CODE = r'''

# v90.2.5.1 processed skip recorder
BOT_VERSION = "v90_2_5_1_processed_skip_recorder"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_5_1_ENABLED = os.getenv("V90_2_5_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v90251_norm_title_key(title):
    try:
        return normalize_for_check(title)
    except Exception:
        return str(title or "").strip().lower()


def v90251_build_title_url_map():
    mapping = {}
    for var_name in ("queue", "pending_items", "pending", "candidates"):
        try:
            items = globals().get(var_name) or []
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    title = it.get("title") or it.get("titolo") or ""
                    url = it.get("url") or it.get("link") or ""
                    if title and url:
                        mapping[v90251_norm_title_key(title)] = it
        except Exception:
            pass
    return mapping


def v90251_find_item_by_title(title):
    key = v90251_norm_title_key(title)
    current = globals().get("v90251_current_item")
    if isinstance(current, dict):
        cur_title = current.get("title") or current.get("titolo") or ""
        if v90251_norm_title_key(cur_title) == key:
            return current
    mapping = globals().get("v90251_title_url_map")
    if not isinstance(mapping, dict) or not mapping:
        mapping = v90251_build_title_url_map()
        globals()["v90251_title_url_map"] = mapping
    return mapping.get(key)


def v90251_record_title_skip(title, status="rejected", reason="skip_log"):
    if not V90_2_5_1_ENABLED:
        return
    try:
        item = v90251_find_item_by_title(title)
        if not isinstance(item, dict):
            return
        url = item.get("url") or item.get("link") or ""
        if not url:
            return
        score = item.get("score")
        canonical_title = item.get("title") or item.get("titolo") or title
        if "v9025_record_processed_url" in globals():
            v9025_record_processed_url(url, title=canonical_title, status=status, reason=reason, score=score, extra={"event_key": item.get("event_key"), "semantic_id": item.get("semantic_id"), "source": "v90.2.5.1_log_recorder"})
            print(f"[PROCESSED v90.2.5.1] Recorded final skip status={status} reason={reason} - {canonical_title}")
    except Exception as e:
        print(f"[PROCESSED v90.2.5.1] Warning record skip: {e}")


def v90251_title_after_marker(text, marker):
    s = str(text or "")
    if marker not in s:
        return ""
    return s.split(marker, 1)[1].strip()


def v90251_find_known_title_in_text(text):
    s = str(text or "")
    mapping = globals().get("v90251_title_url_map")
    if not isinstance(mapping, dict) or not mapping:
        mapping = v90251_build_title_url_map()
        globals()["v90251_title_url_map"] = mapping
    best = ""
    for item in mapping.values():
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("titolo") or "").strip()
        if title and title in s and len(title) > len(best):
            best = title
    return best


def v90251_title_from_skip_message(text):
    s = str(text or "")
    known = v90251_find_known_title_in_text(s)
    if known:
        return known
    if " - " in s:
        tail = s.rsplit(" - ", 1)[1].strip()
        if v90251_find_item_by_title(tail):
            return tail
    return ""

try:
    _ORIG_V90251_PRINT = print
    def print(*args, **kwargs):
        try:
            msg = " ".join(str(a) for a in args)
            if msg.startswith("[BOT] Elaborazione:"):
                title = v90251_title_after_marker(msg, "[BOT] Elaborazione:")
                item = v90251_find_item_by_title(title)
                if isinstance(item, dict):
                    globals()["v90251_current_item"] = item
            elif "[SKIP] Score sotto soglia editoriale dopo raffinamento:" in msg:
                title = v90251_title_from_skip_message(msg)
                v90251_record_title_skip(title, status="skipped_below_threshold", reason="refined_score_below_threshold")
            elif "[SKIP v87] Blocco tier3 opinion/interview sotto" in msg:
                title = v90251_title_from_skip_message(msg)
                v90251_record_title_skip(title, status="skipped_soft_trash", reason="tier3_opinion_interview_below_threshold")
            elif "[SKIP v88.4.1] Canonical event core gia pubblicato:" in msg:
                title = v90251_title_from_skip_message(msg)
                v90251_record_title_skip(title, status="skipped_duplicate", reason="canonical_core_already_published")
            elif "[SKIP] Preview/show announcement scaduta dopo scraping:" in msg:
                title = v90251_title_after_marker(msg, "[SKIP] Preview/show announcement scaduta dopo scraping:")
                v90251_record_title_skip(title, status="skipped_stale", reason="expired_preview_after_scraping")
            elif "[SKIP] Preview/show announcement scaduta:" in msg:
                title = v90251_title_after_marker(msg, "[SKIP] Preview/show announcement scaduta:")
                v90251_record_title_skip(title, status="skipped_stale", reason="expired_preview")
            elif "[SKIP v90.2] Follow-up duplicato/non sostanziale" in msg:
                title = v90251_title_from_skip_message(msg)
                v90251_record_title_skip(title, status="skipped_duplicate", reason="v90_2_non_substantial_followup")
        except Exception:
            pass
        return _ORIG_V90251_PRINT(*args, **kwargs)
except Exception:
    pass

print("[BOOT v90.2.5.1] Processed URL skip recorder attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.5.1] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.5.1] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.5.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
