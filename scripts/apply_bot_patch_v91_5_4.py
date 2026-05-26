from pathlib import Path

MARK = "# v91.5.4 report candidate circuit breaker"
CODE = r'''

# v91.5.4 report candidate circuit breaker
V91_5_4_ENABLED = os.getenv("V91_5_4_ENABLED", "1").lower() not in {"0", "false", "no", "off"}
_V9154_REPORT_ACTIVE = set()
_V9154_REPORT_ATTEMPTED = set()


def v9154_report_core(item):
    if not isinstance(item, dict):
        return ""
    for key in ("report_event_key", "event_key", "story_signature_v71", "news_core_key", "core"):
        val = str(item.get(key) or "").strip()
        if val.startswith("report:"):
            return val
    title = str(item.get("title") or item.get("titolo") or "").lower()
    url = str(item.get("url") or item.get("link") or "").lower()
    raw = f"{title} {url}"
    if "raw" in raw and "result" in raw:
        return str(item.get("event_key") or item.get("url") or item.get("title") or "report:unknown")
    return ""


def v9154_mark_report_manual_review(item, reason, error=""):
    title = ""
    url = ""
    core = ""
    try:
        if isinstance(item, dict):
            title = item.get("title") or item.get("titolo") or ""
            url = item.get("url") or item.get("link") or ""
            core = v9154_report_core(item)
        print(f"[REPORT v91.5.4] Report isolato: reason={reason} core={core} title={title}")
        if "v9025_record_processed_url" in globals() and url:
            v9025_record_processed_url(
                url,
                title=title,
                status="needs_manual_review",
                reason=reason,
                extra={"core": core, "error": str(error)[:500]},
            )
    except Exception as e:
        try:
            print(f"[REPORT v91.5.4] Warning mark manual review failed: {e}")
        except Exception:
            pass

try:
    _PREV_V9154_process_candidate_item = process_candidate_item
    def process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts):
        if not V91_5_4_ENABLED:
            return _PREV_V9154_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        core = v9154_report_core(item)
        if not core:
            return _PREV_V9154_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)

        if core in _V9154_REPORT_ACTIVE:
            print(f"[REPORT v91.5.4] Ricorsione candidate report evitata: {core}")
            v9154_mark_report_manual_review(item, "v91_5_4_report_candidate_recursion")
            return "skipped"
        if core in _V9154_REPORT_ATTEMPTED:
            print(f"[REPORT v91.5.4] Secondo tentativo stesso report nella run evitato: {core}")
            return "skipped"

        _V9154_REPORT_ACTIVE.add(core)
        _V9154_REPORT_ATTEMPTED.add(core)
        try:
            return _PREV_V9154_process_candidate_item(item, history, seen_story_fingerprints, seen_news_core_keys, seen_event_keys, seen_story_signatures_v71, source_fail_counts)
        except RecursionError as e:
            v9154_mark_report_manual_review(item, "v91_5_4_report_recursion_error", e)
            return "skipped"
        except Exception as e:
            # Only isolate report candidates. Normal news still uses original failure behavior.
            if "maximum recursion" in str(e).lower() or "recursion" in e.__class__.__name__.lower():
                v9154_mark_report_manual_review(item, "v91_5_4_report_exception_isolated", e)
                return "skipped"
            raise
        finally:
            _V9154_REPORT_ACTIVE.discard(core)
except Exception as e:
    print(f"[REPORT v91.5.4] Warning process_candidate_item circuit breaker failed: {e}")

print("[BOOT v91.5.4] Report candidate circuit breaker attivo")
'''


def main():
    p = Path("bot.py")
    text = p.read_text(encoding="utf-8")
    if MARK in text:
        print("[SOURCE PATCH v91.5.4] bot.py gia aggiornato")
        return 0
    if "# v91.5.3 report pending unwrap recursion guard" not in text:
        raise SystemExit("[SOURCE PATCH v91.5.4] base v91.5.3 mancante")
    needle = '\n\nif __name__ == "__main__":\n'
    if needle not in text:
        raise SystemExit("[SOURCE PATCH v91.5.4] entrypoint marker not found")
    p.write_text(text.replace(needle, CODE + needle, 1), encoding="utf-8")
    print("[SOURCE PATCH v91.5.4] patch applicata a bot.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
