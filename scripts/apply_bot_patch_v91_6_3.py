from pathlib import Path

MARK = "# v91.6.3 force standard pipeline for resolved report"
CODE = r'''

# v91.6.3 force standard pipeline for resolved report
BOT_VERSION = "v91_6_3_resolved_report_standard_pipeline"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V91_6_3_ENABLED = os.getenv("V91_6_3_ENABLED", "1").lower() not in {"0", "false", "no", "off"}

_V9163_ACTIVE_URLS = set()
_V9163_ACTIVE_CORES = set()


def v9163_norm_url(url=""):
    return str(url or "").split("?", 1)[0].rstrip("/")


def v9163_is_active_url(url=""):
    u = v9163_norm_url(url)
    return bool(V91_6_3_ENABLED and u and u in _V9163_ACTIVE_URLS)


def v9163_mark_active(item):
    if not isinstance(item, dict):
        return ""
    url = v9163_norm_url(item.get("url") or item.get("link") or "")
    core = ""
    for k in ("event_key", "story_signature_v71", "news_core_key", "core"):
        v = str(item.get(k) or "").strip()
        if v.startswith("resolved-report-source:"):
            core = v
            break
    if url:
        _V9163_ACTIVE_URLS.add(url)
    if core:
        _V9163_ACTIVE_CORES.add(core)
    return url


def v9163_unmark_active(url=""):
    u = v9163_norm_url(url)
    if u:
        _V9163_ACTIVE_URLS.discard(u)


def v9163_wrap_return_false(name):
    fn = globals().get(name)
    if not callable(fn):
        return
    prev_name = f"_PREV_V9163_{name}"
    if prev_name in globals():
        return
    globals()[prev_name] = fn
    def wrapper(*args, **kwargs):
        try:
            blob = " ".join(str(a) for a in args[:4]) + " " + " ".join(f"{k}={v}" for k, v in list(kwargs.items())[:4])
            for u in list(_V9163_ACTIVE_URLS):
                if u and u in blob:
                    print(f"[REPORT v91.6.3] Suppresso helper report {name} per fonte risolta")
                    return False
        except Exception:
            pass
        if globals().get("_V9162_SUPPRESS_REPORT_GATE", False):
            return False
        return globals()[prev_name](*args, **kwargs)
    globals()[name] = wrapper


def v9163_wrap_return_empty(name):
    fn = globals().get(name)
    if not callable(fn):
        return
    prev_name = f"_PREV_V9163_{name}"
    if prev_name in globals():
        return
    globals()[prev_name] = fn
    def wrapper(*args, **kwargs):
        try:
            blob = " ".join(str(a) for a in args[:4]) + " " + " ".join(f"{k}={v}" for k, v in list(kwargs.items())[:4])
            for u in list(_V9163_ACTIVE_URLS):
                if u and u in blob:
                    print(f"[REPORT v91.6.3] Suppresso report key helper {name} per fonte risolta")
                    return ""
        except Exception:
            pass
        if globals().get("_V9162_SUPPRESS_REPORT_GATE", False):
            return ""
        return globals()[prev_name](*args, **kwargs)
    globals()[name] = wrapper

# Broader helper names, including likely inline helpers not caught by v91.6.2.
for _n in (
    "is_results_report", "is_result_report", "is_report_article", "is_true_results_report",
    "v86_is_results_report", "v865_is_true_results_report", "v866_is_true_results_report", "v867_is_true_results_report",
    "v868_is_true_results_report", "v869_is_true_results_report", "v86_5_is_true_results_report",
    "v86_6_is_true_results_report", "v86_7_is_true_results_report", "v86_9_is_true_results_report",
):
    try:
        v9163_wrap_return_false(_n)
    except Exception as e:
        print(f"[REPORT v91.6.3] Warning wrap false {_n}: {e}")

for _n in (
    "report_key_from_registry", "event_registry_report_key", "get_report_key", "get_report_event_key",
    "detect_report_event_key", "report_event_key_for_title", "v902541_report_key_from_registry",
    "v90254_report_key_from_registry", "v865_report_event_key", "v866_report_event_key", "v867_report_event_key",
    "v868_report_event_key", "v869_report_event_key", "v86_5_report_event_key", "v86_6_report_event_key",
):
    try:
        v9163_wrap_return_empty(_n)
    except Exception as e:
        print(f"[REPORT v91.6.3] Warning wrap empty {_n}: {e}")

try:
    _PREV_V9163_v9161_call_oldest_candidate = v9161_call_oldest_candidate
    def v9161_call_oldest_candidate(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        url = ""
        old_gate = globals().get("_V9162_SUPPRESS_REPORT_GATE", False)
        try:
            url = v9163_mark_active(item)
            globals()["_V9162_SUPPRESS_REPORT_GATE"] = True
            print(f"[REPORT v91.6.3] Pipeline standard for resolved report attiva: {url}")
            return _PREV_V9163_v9161_call_oldest_candidate(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        finally:
            globals()["_V9162_SUPPRESS_REPORT_GATE"] = old_gate
            v9163_unmark_active(url)
except Exception as e:
    print(f"[REPORT v91.6.3] Warning call_oldest wrapper failed: {e}")

print("[BOOT v91.6.3] Force standard pipeline for resolved report attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.6.3] bot.py gia aggiornato")
        return 0
    if "# v91.6.2 suppress report gate during resolved direct publish" not in text:
        raise SystemExit("[SOURCE PATCH v91.6.3] base v91.6.2 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.6.3] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.6.3] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
