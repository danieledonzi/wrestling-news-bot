from pathlib import Path

MARK = "# v91.6.2 suppress report gate during resolved direct publish"
CODE = r'''

# v91.6.2 suppress report gate during resolved direct publish
BOT_VERSION = "v91_6_2_resolved_report_gate_suppression"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V91_6_2_ENABLED = os.getenv("V91_6_2_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
_V9162_SUPPRESS_REPORT_GATE = False


def v9162_is_suppressed():
    return bool(V91_6_2_ENABLED and globals().get("_V9162_SUPPRESS_REPORT_GATE", False))


def v9162_no_report_key(*args, **kwargs):
    return ""


def v9162_false(*args, **kwargs):
    return False


def v9162_wrap_report_gate_function(name, falsey=""):
    fn = globals().get(name)
    if not callable(fn):
        return
    prev_name = f"_PREV_V9162_{name}"
    if prev_name in globals():
        return
    globals()[prev_name] = fn
    def wrapper(*args, **kwargs):
        if v9162_is_suppressed():
            if falsey is False:
                return False
            return ""
        return globals()[prev_name](*args, **kwargs)
    globals()[name] = wrapper
    print(f"[REPORT v91.6.2] Wrapped report gate function: {name}")

# Known report-key / report-confirmation / report-gate helpers used across v86-v90 wrappers.
for _name in (
    "v902541_report_key_from_registry",
    "v90254_report_key_from_registry",
    "v865_report_event_key",
    "v866_report_event_key",
    "v869_report_event_key",
    "detect_report_event_key",
    "get_report_event_key",
    "report_event_key_for_title",
):
    try:
        v9162_wrap_report_gate_function(_name, "")
    except Exception as e:
        print(f"[REPORT v91.6.2] Warning wrap {_name}: {e}")

for _name in (
    "is_true_results_report",
    "v865_is_true_results_report",
    "v866_is_true_results_report",
    "v869_is_true_results_report",
    "v9011_is_report_confirmed",
    "v881_is_report_confirmed",
    "v872_is_strong_report_confirmed",
    "v87_is_confirmed_report_event_key",
):
    try:
        v9162_wrap_report_gate_function(_name, False)
    except Exception as e:
        print(f"[REPORT v91.6.2] Warning wrap {_name}: {e}")

# Re-wrap v91.6.1 helper so the oldest candidate path runs while report gates are suppressed.
try:
    _PREV_V9162_v9161_call_oldest_candidate = v9161_call_oldest_candidate
    def v9161_call_oldest_candidate(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        global _V9162_SUPPRESS_REPORT_GATE
        old = _V9162_SUPPRESS_REPORT_GATE
        _V9162_SUPPRESS_REPORT_GATE = True
        try:
            print(f"[REPORT v91.6.2] Suppress report gate durante direct publish: {item.get('title') if isinstance(item, dict) else ''}")
            return _PREV_V9162_v9161_call_oldest_candidate(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        finally:
            _V9162_SUPPRESS_REPORT_GATE = old
except Exception as e:
    print(f"[REPORT v91.6.2] Warning v9161_call_oldest_candidate wrapper failed: {e}")

print("[BOOT v91.6.2] Resolved report gate suppression attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.6.2] bot.py gia aggiornato")
        return 0
    if "# v91.6.1 resolved report publish bypass and spoiler consistency" not in text:
        raise SystemExit("[SOURCE PATCH v91.6.2] base v91.6.1 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.6.2] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.6.2] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
