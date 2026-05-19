from __future__ import annotations

from pathlib import Path

BOT_PATH = Path("bot.py")
MARKER = "# v90.0.1: normalize inline image records before dedupe"
OLD = "    inline_images = dedupe_preserve_order([u for u in inline_images if u])"
NEW = """    # v90.0.1: normalize inline image records before dedupe
    # Some extractors may return image records as dictionaries instead of raw URL strings.
    # v88_media_record eventually calls dedupe_preserve_order(), which expects strings and
    # crashes on dict.strip(). Normalize every image candidate to a URL first.
    def _v9001_inline_image_url(value):
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("url", "src", "source_url", "image_url", "href"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            return ""
        return ""

    inline_images = dedupe_preserve_order([
        _v9001_inline_image_url(u) for u in inline_images if _v9001_inline_image_url(u)
    ])"""


def main() -> int:
    text = BOT_PATH.read_text(encoding="utf-8")
    if MARKER in text:
        print("[HOTFIX v90.0.1] bot.py gia aggiornato")
        return 0
    if OLD not in text:
        raise SystemExit("[HOTFIX v90.0.1] pattern target non trovato in bot.py")
    text = text.replace(OLD, NEW, 1)
    BOT_PATH.write_text(text, encoding="utf-8")
    print("[HOTFIX v90.0.1] Normalizzazione inline_images applicata a bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
