from pathlib import Path

MARK = "# v90.2.3.1: inline image dict normalization"
NEEDLE = "    inline_images = dedupe_preserve_order([u for u in inline_images if u])\n"
REPLACEMENT = r'''    # v90.2.3.1: inline image dict normalization
    def _v90231_inline_image_url(value):
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("url", "src", "source_url", "image_url", "href"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            nested = value.get("image") or value.get("media")
            if isinstance(nested, dict):
                for key in ("url", "src", "source_url", "image_url", "href"):
                    candidate = nested.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        return candidate.strip()
        return ""
    inline_images = dedupe_preserve_order([_v90231_inline_image_url(u) for u in inline_images if _v90231_inline_image_url(u)])
'''

BOOT_CODE = r'''

# v90.2.3.1: inline image dict normalization
try:
    print("[BOOT v90.2.3.1] Inline image dict normalization attiva in v88_media_record")
except Exception:
    pass
'''

def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v90.2.3.1] bot.py gia aggiornato")
        return 0
    if NEEDLE not in text:
        raise SystemExit("[SOURCE PATCH v90.2.3.1] target inline_images dedupe line not found")
    text = text.replace(NEEDLE, REPLACEMENT, 1)
    entry = '\n\nif __name__ == "__main__":\n'
    if entry in text:
        text = text.replace(entry, BOOT_CODE + entry, 1)
    p.write_text(text, encoding="utf-8")
    print("[SOURCE PATCH v90.2.3.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
