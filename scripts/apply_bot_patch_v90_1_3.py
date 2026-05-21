from __future__ import annotations

from pathlib import Path

PATCH_MARKER = "# =========================\n# v90.1.3: spoiler hotfix"

PATCH_CODE = r'''

# =========================
# v90.1.3: spoiler hotfix
# =========================
BOT_VERSION = "v90_1_3_spoiler_hotfix"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V90_1_3_ENABLED = os.getenv("V90_1_3_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
V90_1_3_SPOILER_HOTFIX_ENABLED = os.getenv("V90_1_3_SPOILER_HOTFIX_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def v9013_probe(text=""):
    try:
        return re.sub(r"\s+", " ", str(text or "").strip().lower())
    except Exception:
        return ""


def v9013_should_prefix_spoiler(title="", source_title="", event_key="", url="", html=""):
    """Single source of truth for spoiler prefixes after v90.1.3.

    v90.1.1 had an overly broad spoiler guard. It fired on non-show WWE items
    such as legal/arrest news because those articles contained action words and WWE.
    From this patch onward spoiler labels are allowed only through the stricter
    calendar-aware v90.1.2 rule.
    """
    if not (V90_1_3_ENABLED and V90_1_3_SPOILER_HOTFIX_ENABLED):
        return False
    try:
        if "v9012_should_prefix_spoiler" in globals():
            return bool(v9012_should_prefix_spoiler(title=title, source_title=source_title, event_key=event_key, url=url, html=html))
    except Exception as e:
        print(f"[WARN v90.1.3] calendar spoiler check failed: {e}")
    return False


# Override the broad v90.1.1 function directly, because create_post wrappers are nested.
# A later wrapper alone cannot reliably clean the title if the older wrapper adds [SPOILER]
# after the cleanup has already run.
if V90_1_3_ENABLED and V90_1_3_SPOILER_HOTFIX_ENABLED:
    try:
        v9011_should_prefix_spoiler = v9013_should_prefix_spoiler
        print("[SPOILER v90.1.3] v90.1.1 spoiler guard sovrascritta con calendar-aware guard")
    except Exception as e:
        print(f"[WARN v90.1.3] override v9011_should_prefix_spoiler failed: {e}")


if V90_1_3_ENABLED and V90_1_3_SPOILER_HOTFIX_ENABLED and "create_post_without_image" in globals():
    _ORIG_V9013_create_post_without_image = create_post_without_image

    def create_post_without_image(data, sem_id, url, embed_urls=None, event_key="", inline_images=None, featured_image_url=""):
        # Final defensive cleanup: even if an older wrapper produced a false spoiler,
        # remove it unless the strict calendar-aware rule says to keep it.
        try:
            source_title = ""
            try:
                source_title = _V901_SOURCE_TITLE_BY_URL.get(url or "", "")
            except Exception:
                source_title = ""
            if not source_title and isinstance(data, dict):
                source_title = str(data.get("source_title") or data.get("original_title") or "")
            if isinstance(data, dict):
                data = dict(data)
                html = data.get("testo", "") or ""
                final_title = data.get("titolo") or data.get("title") or ""
                if final_title and re.match(r"^\s*\[\s*spoiler\s*\]", str(final_title), flags=re.I):
                    keep = v9013_should_prefix_spoiler(final_title, source_title=source_title, event_key=event_key, url=url, html=html)
                    if not keep:
                        cleaned = re.sub(r"^\s*\[\s*spoiler\s*\]\s*[:\-–—]?\s*", "", str(final_title), flags=re.I).strip()
                        if cleaned:
                            print(f"[SPOILER v90.1.3] Rimosso spoiler falso/fuori calendario: {final_title} -> {cleaned}")
                            data["titolo"] = cleaned
                            data["title"] = cleaned
        except Exception as e:
            print(f"[WARN v90.1.3] final spoiler cleanup warning: {e}")
        return _ORIG_V9013_create_post_without_image(
            data,
            sem_id,
            url,
            embed_urls=embed_urls,
            event_key=event_key,
            inline_images=inline_images,
            featured_image_url=featured_image_url,
        )

try:
    if V90_1_3_ENABLED and V90_1_3_SPOILER_HOTFIX_ENABLED:
        print("[BOOT v90.1.3] Spoiler hotfix attiva: solo calendar-aware guard puo' aggiungere [SPOILER]")
    else:
        print("[BOOT v90.1.3] Spoiler hotfix disattivata")
except Exception:
    pass
'''


def main() -> int:
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        print("[SOURCE PATCH v90.1.3] bot.py gia aggiornato")
        return 0
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.1.3] entrypoint marker not found")
    text = text.replace(needle, PATCH_CODE + needle, 1)
    path.write_text(text, encoding="utf-8")
    print("[SOURCE PATCH v90.1.3] patch applicata a bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
