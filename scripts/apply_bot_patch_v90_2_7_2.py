from pathlib import Path

MARK = "# v90.2.7.2 queue type and report source fix"
CODE = r'''

# v90.2.7.2 queue type and report source fix
BOT_VERSION = "v90_2_7_2_queue_type_report_source_fix"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_7_2_ENABLED = os.getenv("V90_2_7_2_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v90272_assign_from_text(title="", url="", text=""):
    if not V90_2_7_2_ENABLED or "assign_story_core_v9027" not in globals():
        return {}
    try:
        assigned = assign_story_core_v9027({}, title or text or "", url or "", text or title or "", None)
        return assigned if isinstance(assigned, dict) else {}
    except Exception as e:
        print(f"[CORE v90.2.7.2] Warning assign_from_text: {e}")
        return {}


def v90272_story_signature_result(original_result, core):
    """Always return a dict-compatible story signature payload."""
    if isinstance(original_result, dict):
        out = dict(original_result)
    else:
        out = {}
    out["signature"] = core
    out["core"] = core
    out["news_core_key"] = core
    out["assigned_by"] = "v90.2.7.2"
    return out


def v90272_args_to_title_text_url(args, kwargs):
    title = kwargs.get("title") or ""
    text = kwargs.get("text") or kwargs.get("summary") or kwargs.get("body") or ""
    url = kwargs.get("url") or ""
    if args:
        title = title or str(args[0] or "")
    if len(args) >= 2:
        text = text or str(args[1] or "")
    if len(args) >= 3:
        url = url or str(args[2] or "")
    return title, text, url

try:
    _ORIG_V90272_build_story_signature_v71 = build_story_signature_v71
    def build_story_signature_v71(*args, **kwargs):
        original = _ORIG_V90272_build_story_signature_v71(*args, **kwargs)
        title, text, url = v90272_args_to_title_text_url(args, kwargs)
        assigned = v90272_assign_from_text(title, url, text)
        if assigned.get("core"):
            return v90272_story_signature_result(original, assigned["core"])
        return original if isinstance(original, dict) else v90272_story_signature_result(original, str(original or ""))
except Exception:
    pass

try:
    _ORIG_V90272_make_story_signature_v71 = make_story_signature_v71
    def make_story_signature_v71(*args, **kwargs):
        original = _ORIG_V90272_make_story_signature_v71(*args, **kwargs)
        title, text, url = v90272_args_to_title_text_url(args, kwargs)
        assigned = v90272_assign_from_text(title, url, text)
        if assigned.get("core"):
            return v90272_story_signature_result(original, assigned["core"])
        return original if isinstance(original, dict) else v90272_story_signature_result(original, str(original or ""))
except Exception:
    pass


def v90272_processed_record_is_final(rec):
    if not isinstance(rec, dict):
        return False
    status = str(rec.get("status") or "")
    if status in {"published", "skipped_duplicate", "skipped_existing_wp", "skipped_existing_history", "skipped_editorial_exclude", "skipped_soft_trash", "skipped_stale", "low_score_final"}:
        return True
    if status in {"skipped_below_threshold", "rejected"}:
        try:
            return int(rec.get("score") or 0) <= int(os.getenv("V90_2_5_2_LOW_SCORE_FINAL_MAX", "54"))
        except Exception:
            return True
    return False


def v90272_load_processed_store():
    try:
        if "v9025_load_processed" in globals():
            return v9025_load_processed()
        if "v9025_load_processed_records" in globals():
            return v9025_load_processed_records()
        if "v9025_load_processed_urls" in globals():
            return v9025_load_processed_urls()
    except Exception as e:
        print(f"[PROCESSED v90.2.7.2] Warning load processed store: {e}")
    return None


def v90272_processed_url_final(url):
    if not V90_2_7_2_ENABLED or not url:
        return False, None
    try:
        data = v90272_load_processed_store()
        records = data.get("records", data) if isinstance(data, dict) else data
        rec = None
        if isinstance(records, dict):
            norm = normalize_url_for_history(url) if "normalize_url_for_history" in globals() else url
            rec = records.get(url) or records.get(norm)
        if v90272_processed_record_is_final(rec):
            return True, rec
    except Exception as e:
        print(f"[PROCESSED v90.2.7.2] Warning processed check: {e}")
    return False, None

try:
    _ORIG_V90272_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if isinstance(item, dict):
            url = item.get("url") or item.get("link") or ""
            title = item.get("title") or item.get("titolo") or ""
            final, rec = v90272_processed_url_final(url)
            if final:
                print(f"[PROCESSED v90.2.7.2] Feed/process hard skip URL finale status={rec.get('status')} reason={rec.get('reason')} - {title}")
                return "skipped"
        return _ORIG_V90272_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
except Exception:
    pass


def v90272_report_item_has_source(item):
    if not isinstance(item, dict):
        return False
    if item.get("url") or item.get("link"):
        return True
    sources = item.get("sources")
    if isinstance(sources, list) and any(isinstance(s, dict) and (s.get("url") or s.get("link")) for s in sources):
        return True
    return False

try:
    _ORIG_V90272_process_report_pending_item = process_report_pending_item
    def process_report_pending_item(report_item, *args, **kwargs):
        if isinstance(report_item, dict):
            key = report_item.get("report_event_key") or report_item.get("event_key") or report_item.get("key") or ""
            if (report_item.get("core_type_v9027") == "event_report" or str(key).startswith("report:")) and not v90272_report_item_has_source(report_item):
                print(f"[REPORT v90.2.7.2] Report senza fonte concreta: skip pending invalido {key}")
                return False
        return _ORIG_V90272_process_report_pending_item(report_item, *args, **kwargs)
except Exception:
    pass

print("[BOOT v90.2.7.2] Queue type contract + report source guard attivi")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.7.2] bot.py gia aggiornato")
        return 0
    if "# v90.2.7 central story core assignment" not in text:
        raise SystemExit("[SOURCE PATCH v90.2.7.2] base v90.2.7 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.7.2] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.7.2] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
