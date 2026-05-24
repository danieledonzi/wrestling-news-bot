from pathlib import Path

MARK = "# v90.2.5.3 SNME event and publish processed guards"
CODE = r'''

# v90.2.5.3 SNME event and publish processed guards
BOT_VERSION = "v90_2_5_3_snme_publish_processed"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_5_3_ENABLED = os.getenv("V90_2_5_3_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V90_2_5_3_SNME_FLOOR = int(os.getenv("V90_2_5_3_SNME_FLOOR", "82"))


def v90253_title_text(title):
    return str(title or "").strip()


def v90253_norm_title(title):
    try:
        return normalize_for_check(title)
    except Exception:
        return v90253_title_text(title).lower()


def v90253_is_snme(title):
    t = v90253_title_text(title).lower()
    return "saturday night's main event" in t or "saturday nights main event" in t or "snme" in t


def v90253_is_snme_results_or_recap(title):
    t = v90253_title_text(title).lower()
    if not v90253_is_snme(t):
        return False
    result_terms = [
        "result", "results", "recap", "highlights", "key moments", "moments",
        "retains", "retain", "wins", "defeats", "defends", "title", "championship",
        "controversial finish", "dq", "open challenge", "appears", "returns",
    ]
    preview_terms = ["preview", "predictions", "full & final card", "full final card", "lineup", "start time", "how to watch", "betting odds"]
    if any(term in t for term in preview_terms) and not any(term in t for term in ["results", "recap", "highlights", "retains", "wins", "defeats"]):
        return False
    return any(term in t for term in result_terms)


def v90253_extract_title_from_args(args, kwargs):
    title = ""
    for obj in args or []:
        if isinstance(obj, dict):
            title = obj.get("title") or obj.get("titolo") or title
        elif isinstance(obj, str) and (v90253_is_snme(obj) or len(obj) > len(title)):
            title = obj
    return title or str((kwargs or {}).get("title") or "")


def v90253_apply_floor_to_score_result(result, title, label):
    if not V90_2_5_3_ENABLED or not v90253_is_snme_results_or_recap(title):
        return result
    try:
        if isinstance(result, tuple) and result:
            lst = list(result)
            old = int(lst[0])
            if old < V90_2_5_3_SNME_FLOOR:
                lst[0] = V90_2_5_3_SNME_FLOOR
                print(f"[SNME v90.2.5.3] {label} floor {old}->{lst[0]} - {title}")
            return tuple(lst)
        if isinstance(result, int):
            old = int(result)
            if old < V90_2_5_3_SNME_FLOOR:
                print(f"[SNME v90.2.5.3] {label} floor {old}->{V90_2_5_3_SNME_FLOOR} - {title}")
                return V90_2_5_3_SNME_FLOOR
    except Exception:
        return result
    return result


def v90253_mark_url_published(url, title="", reason="publish_log_ok", extra=None):
    if not V90_2_5_3_ENABLED or not url:
        return
    try:
        if "v9025_record_processed_url" in globals():
            v9025_record_processed_url(url, title=title, status="published", reason=reason, score=None, extra=extra or {"source": "v90.2.5.3_publish_log"})
            print(f"[PROCESSED v90.2.5.3] Mark published URL da publish log - {title or url}")
    except Exception as e:
        print(f"[PROCESSED v90.2.5.3] Warning mark published: {e}")

try:
    _ORIG_V90253_calculate_importance_score = calculate_importance_score
    def calculate_importance_score(*args, **kwargs):
        result = _ORIG_V90253_calculate_importance_score(*args, **kwargs)
        title = v90253_extract_title_from_args(args, kwargs)
        return v90253_apply_floor_to_score_result(result, title, "Pre-AI event score")
except Exception:
    pass

try:
    _ORIG_V90253_v723_conservative_score_after_ai = v723_conservative_score_after_ai
    def v723_conservative_score_after_ai(*args, **kwargs):
        result = _ORIG_V90253_v723_conservative_score_after_ai(*args, **kwargs)
        title = v90253_extract_title_from_args(args, kwargs)
        return v90253_apply_floor_to_score_result(result, title, "Event report")
except Exception:
    pass

try:
    _ORIG_V90253_record_processed_url = v9025_record_processed_url
    def v9025_record_processed_url(url, title="", status="rejected", reason="", score=None, extra=None):
        if V90_2_5_3_ENABLED and v90253_is_snme_results_or_recap(title):
            s = str(status or "").strip().lower()
            if s in {"rejected", "skipped_below_threshold", "skipped_stale", "skipped_soft_trash"}:
                status = "competitive_deferred"
                reason = "snme_event_report_not_final"
        return _ORIG_V90253_record_processed_url(url, title=title, status=status, reason=reason, score=score, extra=extra)
except Exception:
    pass

try:
    _ORIG_V90253_PRINT = print
    def print(*args, **kwargs):
        try:
            msg = " ".join(str(a) for a in args)
            if msg.startswith("[BOT] Elaborazione:"):
                title = msg.split("[BOT] Elaborazione:", 1)[1].strip()
                item = None
                if "v90251_find_item_by_title" in globals():
                    item = v90251_find_item_by_title(title)
                if isinstance(item, dict):
                    globals()["v90253_current_processing_item"] = item
                    globals()["v90253_current_processing_title"] = item.get("title") or item.get("titolo") or title
                else:
                    globals()["v90253_current_processing_item"] = None
                    globals()["v90253_current_processing_title"] = title
            elif msg.startswith("[OK] Pubblicato:"):
                published_title = msg.split("[OK] Pubblicato:", 1)[1].strip()
                current = globals().get("v90253_current_processing_item")
                source_title = globals().get("v90253_current_processing_title") or ""
                if isinstance(current, dict):
                    original_title = current.get("title") or current.get("titolo") or ""
                    published_norm = v90253_norm_title(published_title)
                    source_norm = v90253_norm_title(source_title)
                    original_norm = v90253_norm_title(original_title)
                    match_ok = bool(published_norm and (published_norm == source_norm or published_norm == original_norm or source_norm in published_norm or original_norm in published_norm or published_norm in source_norm or published_norm in original_norm))
                    if match_ok:
                        url = current.get("url") or current.get("link") or ""
                        v90253_mark_url_published(url, title=original_title or source_title or published_title, reason="ok_published_log", extra={"published_title": published_title, "source": "v90.2.5.3_ok_log"})
                    else:
                        print(f"[PROCESSED v90.2.5.3] Skip mark published: titolo non combacia current='{original_title}' published='{published_title}'")
        except Exception:
            pass
        return _ORIG_V90253_PRINT(*args, **kwargs)
except Exception:
    pass

print("[BOOT v90.2.5.3] SNME event report guard e processed publish success attivi")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.5.3] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.5.3] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.5.3] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
