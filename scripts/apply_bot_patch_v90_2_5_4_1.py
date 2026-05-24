from pathlib import Path

MARK = "# v90.2.5.4.1 event registry report key"
CODE = r'''

# v90.2.5.4.1 event registry report key
BOT_VERSION = "v90_2_5_4_1_event_registry_report_key"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_5_4_1_ENABLED = os.getenv("V90_2_5_4_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v902541_registry_report_key(title="", url="", text=""):
    if not V90_2_5_4_1_ENABLED:
        return ""
    try:
        raw = " ".join([str(title or ""), str(url or ""), str(text or "")])
        if "v90254_match_event" in globals() and "v90254_is_event_results_text" in globals() and "v90254_report_key_from_text" in globals():
            if v90254_match_event(raw) and v90254_is_event_results_text(raw):
                return v90254_report_key_from_text(raw, "", url) or ""
    except Exception:
        pass
    return ""

try:
    _ORIG_V902541_make_report_event_key = make_report_event_key
    def make_report_event_key(title="", url="", text=""):
        rk = v902541_registry_report_key(title, url, text)
        if rk:
            print(f"[EVENTREG v90.2.5.4.1] report key da registry: {rk}")
            return rk
        return _ORIG_V902541_make_report_event_key(title, url, text)
except Exception:
    pass

print("[BOOT v90.2.5.4.1] Event registry collegata a make_report_event_key")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.5.4.1] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.5.4.1] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.5.4.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
