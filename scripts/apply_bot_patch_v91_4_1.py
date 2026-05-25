from pathlib import Path

MARK = "# v91.4.1 strict publish return tuple contract"
CODE = r'''

# v91.4.1 strict publish return tuple contract
V91_4_1_ENABLED = os.getenv("V91_4_1_ENABLED", "1").lower() not in {"0", "false", "no", "off"}


def v9141_tuple2(result):
    """Normalize create_post_without_image returns for legacy callers doing post_id, post_json = ..."""
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

try:
    _PREV_V9141_create_post_without_image = create_post_without_image
    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        result = _PREV_V9141_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )
        if not V91_4_1_ENABLED:
            return result
        normalized = v9141_tuple2(result)
        if isinstance(result, (tuple, list)) and len(result) != 2:
            print(f"[V91.4.1 PUBLISH] Normalizzo return create_post_without_image len={len(result)} -> 2")
        return normalized
except Exception as e:
    print(f"[V91.4.1] Warning publish return tuple guard failed: {e}")

print("[BOOT v91.4.1] Strict publish return tuple contract attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.4.1] bot.py gia aggiornato")
        return 0
    if "# v91.4 publish processed and soft pool repair" not in text:
        raise SystemExit("[SOURCE PATCH v91.4.1] base v91.4 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.4.1] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.4.1] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
