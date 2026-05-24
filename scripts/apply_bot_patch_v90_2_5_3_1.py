from pathlib import Path

MARK = "# v90.2.5.3.1 tighten SNME and publish guards"
CODE = r'''

# v90.2.5.3.1 tighten SNME and publish guards
BOT_VERSION = "v90_2_5_3_1_snme_publish_tighten"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_5_3_1_ENABLED = os.getenv("V90_2_5_3_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v902531_title_text(title):
    return str(title or "").strip()


def v902531_is_snme(title):
    t = v902531_title_text(title).lower()
    return "saturday night's main event" in t or "saturday nights main event" in t or "snme" in t


def v902531_is_full_event_recap(title):
    t = v902531_title_text(title).lower()
    if not v902531_is_snme(t):
        return False
    hard_no = [
        "full & final card", "full final card", "predictions", "preview", "lineup",
        "start time", "how to watch", "betting odds", "fans furious", "fan reaction",
        "fans react", "backlash", "controversial finish", "major change", "added to",
        "title match during", "pulls off", "retains", "retain", "cheat to retain",
        "open challenge", "wardrobe malfunction",
    ]
    if any(x in t for x in hard_no):
        return False
    full_event_terms = ["results", "recap", "full results", "highlights and key moments", "key moments"]
    return any(x in t for x in full_event_terms)

try:
    def v90253_is_snme_results_or_recap(title):
        return v902531_is_full_event_recap(title)
except Exception:
    pass

try:
    _ORIG_V902531_PRINT = print
    def print(*args, **kwargs):
        try:
            msg = " ".join(str(a) for a in args)
            if msg.startswith("[BOT] Elaborazione:"):
                title = msg.split("[BOT] Elaborazione:", 1)[1].strip()
                item = None
                if "v90251_find_item_by_title" in globals():
                    item = v90251_find_item_by_title(title)
                globals()["v902531_current_url"] = ""
                globals()["v902531_current_title"] = title
                if isinstance(item, dict):
                    globals()["v902531_current_url"] = item.get("url") or item.get("link") or ""
                    globals()["v902531_current_title"] = item.get("title") or item.get("titolo") or title
            elif msg.startswith("[OK] Pubblicato:"):
                published_title = msg.split("[OK] Pubblicato:", 1)[1].strip()
                url = globals().get("v902531_current_url") or ""
                source_title = globals().get("v902531_current_title") or published_title
                if url and "v9025_record_processed_url" in globals():
                    v9025_record_processed_url(url, title=source_title, status="published", reason="ok_published_log_v90_2_5_3_1", score=None, extra={"published_title": published_title, "source": "v90.2.5.3.1_ok_log"})
                    print(f"[PROCESSED v90.2.5.3.1] Mark published current URL - {source_title}")
                globals()["v902531_current_url"] = ""
                globals()["v902531_current_title"] = ""
        except Exception:
            pass
        return _ORIG_V902531_PRINT(*args, **kwargs)
except Exception:
    pass

print("[BOOT v90.2.5.3.1] SNME floor ristretto e processed publish corrente attivi")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.5.3.1] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.5.3.1] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.5.3.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
