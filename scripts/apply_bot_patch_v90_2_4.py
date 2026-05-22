from pathlib import Path

MARK = "# v90.2.4: offline pending hard-skip guard"
CODE = r'''

# v90.2.4: offline pending hard-skip guard
BOT_VERSION = "v90_2_4_offline_pending_hardskip"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_4_ENABLED = os.getenv("V90_2_4_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V90_2_4_OFFLINE_PENDING_GUARD_ENABLED = os.getenv("V90_2_4_OFFLINE_PENDING_GUARD_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
V90_2_4_MIN_OFFLINE_PENDING_SCORE = int(os.getenv("V90_2_4_MIN_OFFLINE_PENDING_SCORE", "75"))
V90_2_4_MIN_OFFLINE_PENDING_FRESHNESS = float(os.getenv("V90_2_4_MIN_OFFLINE_PENDING_FRESHNESS", "0.45"))


def v9024_norm_text(*parts):
    try:
        return normalize_for_check(" ".join(str(p or "") for p in parts))
    except Exception:
        return " ".join(str(p or "") for p in parts).lower()


def v9024_item_url(item):
    try:
        return v867_item_url(item)
    except Exception:
        return (item or {}).get("url") or (item or {}).get("link") or ""


def v9024_is_true_report(item):
    try:
        return bool(v867_is_true_results_item(item))
    except Exception:
        title = (item or {}).get("title", "")
        url = v9024_item_url(item)
        return bool((item or {}).get("report_event_key") or str((item or {}).get("event_key", "")).startswith("report:") or is_results_article(title, url, ""))


def v9024_report_key(item):
    try:
        return v867_report_key(item)
    except Exception:
        return (item or {}).get("report_event_key") or (item or {}).get("event_key") or ""


def v9024_history_sets():
    try:
        h = load_history()
    except Exception:
        h = {}
    return h if isinstance(h, dict) else {}


def v9024_history_contains(history, bucket, value):
    if not value:
        return False
    try:
        values = history.get(bucket, set()) or set()
        return value in values
    except Exception:
        return False


def v9024_url_hard_seen(item, history):
    url = v9024_item_url(item)
    if not url:
        return False
    return v9024_history_contains(history, "urls", url)


def v9024_signature_seen(item, history):
    sig = (item or {}).get("story_signature_v71") or ""
    if sig and v9024_history_contains(history, "story_signatures_v71", sig):
        return True
    sem = (item or {}).get("semantic_id") or ""
    if sem and v9024_history_contains(history, "semantic_ids", sem):
        return True
    title_key = (item or {}).get("title_key") or ""
    if title_key and v9024_history_contains(history, "title_keys", title_key):
        return True
    return False


def v9024_report_confirmed(item, history):
    if not v9024_is_true_report(item):
        return False
    key = v9024_report_key(item)
    if key and v9024_history_contains(history, "event_keys", key):
        return True
    try:
        # In offline mode do not query WP; trust strong local memory only.
        for fn in ("v872_is_strong_report_confirmed", "v87_is_confirmed_report_event_key", "v881_is_report_confirmed"):
            if key and fn in globals() and globals()[fn](key):
                return True
    except Exception:
        pass
    return False


def v9024_core_already_covered(item, history):
    event_key = (item or {}).get("event_key") or ""
    report_key = (item or {}).get("report_event_key") or ""
    if event_key and not str(event_key).startswith("report:") and v9024_history_contains(history, "event_keys", event_key):
        return True
    if report_key and v9024_history_contains(history, "event_keys", report_key):
        return True
    try:
        title = (item or {}).get("title", "")
        summary = (item or {}).get("summary", "")
        core = make_news_core_key(title, summary)
        if core and v9024_history_contains(history, "news_core_keys", core):
            return True
    except Exception:
        pass
    return False


def v9024_has_major_update_signal(item):
    text = v9024_norm_text((item or {}).get("title", ""), (item or {}).get("summary", ""))
    major_terms = [
        "confirmed", "official", "announced", "cleared", "arrested", "released", "injured", "signed",
        "title change", "championship", "new champion", "return", "debut", "fired", "lawsuit", "settlement",
        "conferm", "ufficial", "annunc", "infortun", "arrest", "licenzi", "ritorno", "debutto",
    ]
    return any(t in text for t in major_terms)


def v9024_fresh_enough(item):
    if v9024_is_true_report(item):
        return True
    try:
        freshness = float((item or {}).get("freshness", 0) or 0)
        if freshness >= V90_2_4_MIN_OFFLINE_PENDING_FRESHNESS:
            return True
    except Exception:
        pass
    return v9024_has_major_update_signal(item)


def v9024_should_keep_for_offline_pending(item, history):
    score = int((item or {}).get("score", 0) or 0)
    title = (item or {}).get("title", "")
    if score < V90_2_4_MIN_OFFLINE_PENDING_SCORE and not v9024_is_true_report(item):
        print(f"[PENDING v90.2.4] Hard skip offline pending: score basso {score} - {title}")
        return False
    if v9024_url_hard_seen(item, history):
        print(f"[PENDING v90.2.4] Hard skip offline pending: URL gia processato - {title}")
        return False
    if v9024_report_confirmed(item, history):
        print(f"[PENDING v90.2.4] Hard skip offline pending: report gia confermato {v9024_report_key(item)} - {title}")
        return False
    if v9024_signature_seen(item, history):
        print(f"[PENDING v90.2.4] Hard skip offline pending: signature/semantic gia processata - {title}")
        return False
    if v9024_core_already_covered(item, history) and not v9024_has_major_update_signal(item):
        print(f"[PENDING v90.2.4] Hard skip offline pending: core gia coperto senza major update - {title}")
        return False
    if not v9024_fresh_enough(item):
        print(f"[PENDING v90.2.4] Hard skip offline pending: freshness insufficiente - {title}")
        return False
    return True

try:
    _ORIG_V9024_save_selected_candidates_to_pending = save_selected_candidates_to_pending
    def save_selected_candidates_to_pending(queue, reason="", limit=3):
        if V90_2_4_ENABLED and V90_2_4_OFFLINE_PENDING_GUARD_ENABLED and str(reason or "").startswith(("wp_down", "wp_firewall")):
            history = v9024_history_sets()
            filtered = []
            dropped = 0
            for item in list(queue or []):
                if v9024_should_keep_for_offline_pending(item, history):
                    filtered.append(item)
                else:
                    dropped += 1
            print(f"[PENDING v90.2.4] Offline pending guard: keep={len(filtered)} drop={dropped} reason={reason}")
            return _ORIG_V9024_save_selected_candidates_to_pending(filtered, reason=reason, limit=limit)
        return _ORIG_V9024_save_selected_candidates_to_pending(queue, reason=reason, limit=limit)
except Exception:
    pass

try:
    print("[BOOT v90.2.4] Offline pending hard-skip guard attiva")
except Exception:
    pass
'''

def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.4] bot.py gia aggiornato")
        return 0
    entry = '\n\nif __name__ == "__main__":\n'
    if entry not in text:
        raise SystemExit("[SOURCE PATCH v90.2.4] entrypoint marker not found")
    p.write_text(text.replace(entry, CODE + entry, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.4] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
