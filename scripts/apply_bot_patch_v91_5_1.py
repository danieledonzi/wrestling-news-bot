from pathlib import Path

MARK = "# v91.5.1 final strict publish return guard"
CODE = r'''

# v91.5.1 final strict publish return guard
V91_5_1_ENABLED = os.getenv("V91_5_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v9151_tuple2(result):
    """Final outermost normalization for legacy callers: post_id, post_json = create_post_without_image(...)."""
    try:
        if isinstance(result, tuple):
            if len(result) >= 2:
                return result[0], result[1]
            if len(result) == 1:
                return result[0], {}
            return None, {}
        if isinstance(result, list):
            if len(result) >= 2:
                return result[0], result[1]
            if len(result) == 1:
                return result[0], {}
            return None, {}
        if result is False or result is None:
            return None, {}
        if isinstance(result, dict):
            post_id = result.get("post_id") or result.get("id") or result.get("wp_post_id")
            return post_id, result
        if isinstance(result, (int, float)):
            return int(result), {}
        return result, {}
    except Exception:
        return None, {"normalization_error": True}

try:
    _PREV_V9151_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        result = _PREV_V9151_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )
        if not V91_5_1_ENABLED:
            return result
        normalized = v9151_tuple2(result)
        if isinstance(result, (tuple, list)) and len(result) != 2:
            print(f"[V91.5.1 PUBLISH] Final normalize create_post_without_image len={len(result)} -> 2")
        return normalized
except Exception as e:
    print(f"[V91.5.1] Warning final publish return guard failed: {e}")

print("[BOOT v91.5.1] Final strict publish return guard attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.5.1] bot.py gia aggiornato")
        return 0
    if "# v91.5 html integrity and block-safe repair guard" not in text:
        raise SystemExit("[SOURCE PATCH v91.5.1] base v91.5 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.5.1] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.5.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
