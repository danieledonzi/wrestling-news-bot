from pathlib import Path

MARK = "# v90.2.4.1 report hard title"
CODE = '''

# v90.2.4.1 report hard title
BOT_VERSION = "v90_2_4_1_report_hard_title"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_4_1_ENABLED = os.getenv("V90_2_4_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v90241_hard_report_title(event_key):
    key = str(event_key or "")
    if not key.startswith("report:"):
        return ""
    body = key.split(":", 1)[1]
    parts = body.rsplit("-", 3)
    if len(parts) != 4:
        return ""
    show_key, year, month, day = parts
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return ""
    show_map = {
        "raw": "WWE RAW", "wwe-raw": "WWE RAW",
        "smackdown": "WWE SmackDown", "wwe-smackdown": "WWE SmackDown",
        "nxt": "WWE NXT", "wwe-nxt": "WWE NXT",
        "dynamite": "AEW Dynamite", "aew-dynamite": "AEW Dynamite",
        "collision": "AEW Collision", "aew-collision": "AEW Collision",
        "impact": "TNA Impact", "tna-impact": "TNA Impact", "tna": "TNA Impact",
    }
    month_map = {"01":"gennaio","02":"febbraio","03":"marzo","04":"aprile","05":"maggio","06":"giugno","07":"luglio","08":"agosto","09":"settembre","10":"ottobre","11":"novembre","12":"dicembre"}
    show = show_map.get(show_key.lower(), show_key.replace("-", " ").title())
    return f"{show} del {int(day)} {month_map.get(month, month)} {year}: risultati e momenti salienti"

try:
    _v90241_orig_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        if V90_2_4_1_ENABLED and isinstance(data, dict):
            hard_title = v90241_hard_report_title(event_key)
            if hard_title:
                data = dict(data)
                data["titolo"] = hard_title
                data["title"] = hard_title
                print("[TITLE v90.2.4.1] Report hard-title forzato: " + hard_title)
        return _v90241_orig_create_post_without_image(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)
except Exception:
    pass

print("[BOOT v90.2.4.1] Report hard-title guard attiva")
'''

def main():
    p = Path("bot.py")
    t = p.read_text(encoding="utf-8")
    if MARK in t:
        print("[SOURCE PATCH v90.2.4.1] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in t:
        raise SystemExit("[SOURCE PATCH v90.2.4.1] entrypoint marker not found")
    p.write_text(t.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.4.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
