from pathlib import Path

MARK = "# v90.2.4.2 report casing guard"
CODE = '''

# v90.2.4.2 report casing guard
BOT_VERSION = "v90_2_4_2_report_artifacts_recovery"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"
V90_2_4_2_ENABLED = os.getenv("V90_2_4_2_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v90242_fix_wrestling_name_casing(text):
    if not text:
        return text
    fixes = {
        "rhea ripley": "Rhea Ripley",
        "tiffany stratton": "Tiffany Stratton",
        "cody rhodes": "Cody Rhodes",
        "gunther": "Gunther",
        "lash legend": "Lash Legend",
        "nia jax": "Nia Jax",
        "jade cargill": "Jade Cargill",
        "naomi": "Naomi",
        "alexa bliss": "Alexa Bliss",
        "charlotte flair": "Charlotte Flair",
        "becky lynch": "Becky Lynch",
        "sol ruca": "Sol Ruca",
        "bianca belair": "Bianca Belair",
        "baron corbin": "Baron Corbin",
        "blake monroe": "Blake Monroe",
        "roman reigns": "Roman Reigns",
        "jacob fatu": "Jacob Fatu",
        "cm punk": "CM Punk",
        "john cena": "John Cena",
        "seth rollins": "Seth Rollins",
        "wwe": "WWE",
        "aew": "AEW",
        "tna": "TNA",
        "nxt": "NXT",
    }
    out = str(text)
    for src, dst in fixes.items():
        out = re.sub(r"(?<![A-Za-z])" + re.escape(src) + r"(?![A-Za-z])", dst, out, flags=re.I)
    return out

try:
    _v90242_orig_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        if V90_2_4_2_ENABLED and isinstance(data, dict) and str(event_key or "").startswith("report:"):
            data = dict(data)
            if "testo" in data:
                data["testo"] = v90242_fix_wrestling_name_casing(data.get("testo", ""))
            if "content" in data:
                data["content"] = v90242_fix_wrestling_name_casing(data.get("content", ""))
            if "titolo" in data:
                data["titolo"] = v90242_fix_wrestling_name_casing(data.get("titolo", ""))
            if "title" in data:
                data["title"] = v90242_fix_wrestling_name_casing(data.get("title", ""))
            print("[TEXT v90.2.4.2] Report name casing guard applicata")
        return _v90242_orig_create_post_without_image(data, sem_id, url, embed_urls=embed_urls, event_key=event_key, inline_images=inline_images, featured_image_url=featured_image_url)
except Exception:
    pass

print("[BOOT v90.2.4.2] Report artifacts/casing recovery attiva")
'''

def main():
    p = Path("bot.py")
    t = p.read_text(encoding="utf-8")
    if MARK in t:
        print("[SOURCE PATCH v90.2.4.2] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in t:
        raise SystemExit("[SOURCE PATCH v90.2.4.2] entrypoint marker not found")
    p.write_text(t.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v90.2.4.2] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
