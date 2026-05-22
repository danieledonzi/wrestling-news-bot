from __future__ import annotations

from pathlib import Path

PATCH_MARKER = "# =========================\n# v90.2.1: report dedupe protection"
PATCH_CODE = r'''

# =========================
# v90.2.1: report dedupe protection
# =========================
BOT_VERSION = "v90_2_1_report_dedupe_protection"
BOT_VERSION_FULL = f"{BOT_VERSION} ({GIT_SHA_SHORT})"

V90_2_1_ENABLED = os.getenv("V90_2_1_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def v9021_scope_get(scope, *names, default=""):
    for name in names:
        try:
            value = scope.get(name)
        except Exception:
            value = None
        if value not in (None, ""):
            return value
    return default


def v9021_item_from_scope(scope):
    item = v9021_scope_get(scope, "item", default={})
    return item if isinstance(item, dict) else {}


def v9021_report_key_from_scope(scope):
    item = v9021_item_from_scope(scope)
    for value in [
        item.get("report_event_key"),
        item.get("event_key"),
        v9021_scope_get(scope, "report_event_key"),
        v9021_scope_get(scope, "event_key"),
    ]:
        value = str(value or "").strip()
        if value.startswith("report:"):
            return value
    title = str(item.get("title") or v9021_scope_get(scope, "title", "source_title") or "")
    url = str(item.get("url") or v9021_scope_get(scope, "url", "source_url") or "")
    text = str(item.get("prefetched_text") or v9021_scope_get(scope, "text", "source_text", "article_text") or "")
    try:
        key = make_report_event_key(title, url, text)
        if key and str(key).startswith("report:"):
            return key
    except Exception:
        pass
    return ""


def v9021_title_url_text_from_scope(scope):
    item = v9021_item_from_scope(scope)
    title = str(item.get("title") or v9021_scope_get(scope, "title", "source_title") or "")
    url = str(item.get("url") or v9021_scope_get(scope, "url", "source_url") or "")
    text = str(
        item.get("prefetched_text")
        or item.get("text")
        or v9021_scope_get(scope, "text", "source_text", "article_text", "source_text_joined")
        or ""
    )
    return title, url, text


def v9021_is_report_context(scope):
    item = v9021_item_from_scope(scope)
    title, url, text = v9021_title_url_text_from_scope(scope)
    report_key = v9021_report_key_from_scope(scope)
    if report_key.startswith("report:"):
        return True
    if item.get("kind") == "report" or item.get("force_process_report"):
        return True
    try:
        editorial_analysis = scope.get("editorial_analysis") or scope.get("analysis") or {}
        if isinstance(editorial_analysis, dict):
            atype = normalize_article_type(editorial_analysis.get("article_type", ""))
            if atype == "RESULTS_REPORT":
                return True
    except Exception:
        pass
    try:
        if is_results_article(title, url, text):
            return True
    except Exception:
        pass
    try:
        if v75_is_hard_results_report(title, url, text):
            return True
    except Exception:
        pass
    probe = normalize_for_check(f"{title} {url}") if "normalize_for_check" in globals() else f"{title} {url}".lower()
    return "risultati e momenti salienti" in probe or " results " in f" {probe} "


def v9021_report_confirmed(scope, report_key):
    if not report_key:
        return False
    title, url, _ = v9021_title_url_text_from_scope(scope)
    try:
        return bool(wp_has_published_event(report_key, title=title, url=url))
    except Exception as e:
        print(f"[REPORT v90.2.1] WP report confirmation lookup failed, no bypass: {report_key} | {e}")
        return True


def v9021_should_bypass_generic_dedupe(scope):
    """Protect mature true-results reports from generic story/fingerprint dedupe.

    Report publication authority must be the strict report key + WordPress confirmation.
    Generic story fingerprints can collide with post-show news or partial report material,
    as seen with TNA Impact 2026-05-21.
    """
    if not V90_2_1_ENABLED:
        return False
    if not v9021_is_report_context(scope):
        return False
    report_key = v9021_report_key_from_scope(scope)
    if report_key and v9021_report_confirmed(scope, report_key):
        return False
    title, url, _ = v9021_title_url_text_from_scope(scope)
    print(f"[REPORT v90.2.1] Bypass dedupe generico per true-results non confermato: {report_key or '-'} - {title[:90]}")
    return True

try:
    print("[BOOT v90.2.1] Report dedupe protection attiva: true-results usa solo report gate stretto")
except Exception:
    pass
'''

SKIP_LITERAL = "News probabilmente già pubblicata da altra fonte"
GUARD_CALL = "v9021_should_bypass_generic_dedupe(locals())"


def inject_patch_code(text: str) -> str:
    if PATCH_MARKER in text:
        return text
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v90.2.1] entrypoint marker not found")
    return text.replace(needle, PATCH_CODE + needle, 1)


def patch_generic_dedupe_condition(text: str) -> str:
    if GUARD_CALL in text:
        return text
    lines = text.splitlines(keepends=True)
    skip_indexes = [i for i, line in enumerate(lines) if SKIP_LITERAL in line]
    if not skip_indexes:
        raise SystemExit(f"[SOURCE PATCH v90.2.1] skip literal not found: {SKIP_LITERAL}")
    patched = 0
    for idx in skip_indexes:
        skip_indent = len(lines[idx]) - len(lines[idx].lstrip(" "))
        for j in range(idx - 1, max(-1, idx - 40), -1):
            stripped = lines[j].strip()
            indent = len(lines[j]) - len(lines[j].lstrip(" "))
            if indent <= skip_indent and stripped.startswith("if ") and stripped.endswith(":"):
                if GUARD_CALL in lines[j]:
                    break
                line_no_newline = lines[j].rstrip("\n")
                newline = "\n" if lines[j].endswith("\n") else ""
                lines[j] = line_no_newline[:-1] + f" and not {GUARD_CALL}:" + newline
                patched += 1
                break
        else:
            raise SystemExit(f"[SOURCE PATCH v90.2.1] parent if not found for skip literal near line {idx + 1}")
    if patched < 1:
        raise SystemExit("[SOURCE PATCH v90.2.1] no generic dedupe condition patched")
    print(f"[SOURCE PATCH v90.2.1] Generic dedupe conditions patched: {patched}")
    return "".join(lines)


def main() -> int:
    path = Path("bot.py")
    text = path.read_text(encoding="utf-8")
    text = inject_patch_code(text)
    text = patch_generic_dedupe_condition(text)
    path.write_text(text, encoding="utf-8")
    print("[SOURCE PATCH v90.2.1] patch applicata a bot.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
