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
    _ORIG_V90253_refine_score_after_ai = refine_score_after_ai
    def refine_score_after_ai(*args, **kwargs):
        result = _ORIG_V90253_refine_score_after_ai(*args, **kwargs)
        if not V90_2_5_3_ENABLED:
            return result
        try:
            title = ""
            if args:
                for obj in args:
                    if isinstance(obj, dict):
                        title = obj.get("title") or obj.get("titolo") or title
                    elif isinstance(obj, str) and v90253_is_snme(obj):
                        title = obj
            if not title:
                title = str(kwargs.get("title") or "")
            if not v90253_is_snme_results_or_recap(title):
                return result
            if isinstance(result, tuple) and result:
                lst = list(result)
                try:
                    old = int(lst[0])
                    if old < V90_2_5_3_SNME_FLOOR:
                        lst[0] = V90_2_5_3_SNME_FLOOR
                        print(f"[SNME v90.2.5.3] Event report floor {old}->{lst[0]} - {title}")
                    return tuple(lst)
                except Exception:
                    return result
            if isinstance(result, int) and result < V90_2_5_3_SNME_FLOOR:
                print(f"[SNME v90.2.5.3] Event report floor {result}->{V90_2_5_3_SNME_FLOOR} - {title}")
                return V90_2_5_3_SNME_FLOOR
        except Exception:
            pass
        return result
except Exception:
    pass

try:
    _ORIG_V90253_score_article = score_article
    def score_article(*args, **kwargs):
        result = _ORIG_V90253_score_article(*args, **kwargs)
        if not V90_2_5_3_ENABLED:
            return result
        try:
            title = ""
            if args:
                first = args[0]
                if isinstance(first, dict):
                    title = first.get("title") or first.get("titolo") or ""
                elif isinstance(first, str):
                    title = first
            title = title or str(kwargs.get("title") or "")
            if not v90253_is_snme_results_or_recap(title):
                return result
            if isinstance(result, tuple) and result:
                lst = list(result)
                try:
                    old = int(lst[0])
                    if old < V90_2_5_3_SNME_FLOOR:
                        lst[0] = V90_2_5_3_SNME_FLOOR
                        print(f"[SNME v90.2.5.3] Pre-AI event score floor {old}->{lst[0]} - {title}")
                    return tuple(lst)
                except Exception:
                    return result
            if isinstance(result, int) and result < V90_2_5_3_SNME_FLOOR:
                print(f"[SNME v90.2.5.3] Pre-AI event score floor {result}->{V90_2_5_3_SNME_FLOOR} - {title}")
                return V90_2_5_3_SNME_FLOOR
        except Exception:
            pass
        return result
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
            if msg.startswith("[OK] Pubblicato:"):
                title = msg.split("[OK] Pubblicato:", 1)[1].strip()
                current = globals().get("v90251_current_item")
                if isinstance(current, dict):
                    url = current.get("url") or current.get("link") or ""
                    source_title = current.get("title") or current.get("titolo") or title
                    v90253_mark_url_published(url, title=source_title, reason="ok_published_log", extra={"published_title": title, "source": "v90.2.5.3_ok_log"})
            elif "[WP] Status create: 201" in msg:
                globals()["v90253_wp_create_201_seen"] = True
            elif "[WP v85] Status publish draft: 200" in msg:
                globals()["v90253_wp_publish_200_seen"] = True
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
